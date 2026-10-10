#!/usr/bin/env python3
"""Generate the matched initialization-control study for the refresh replay (issue #139). Stdlib only.

Question: the #128/#131/#134 refresh-replay evidence starts every storage node (SN) from a ``.ic`` LABEL under ``tran ... uic`` with
no initial condition on the idle-high read-select pin. #134 found that the forced pin steps 0 -> VDD in the first time step and
lifts SN above its label before the read. Which recorded sense / restore conclusions depend on that legacy start, and which survive
when the stored level is prepared differently?

Three initialization regimes of the SAME circuit, nominal data targets (labels), operation waveform, loads, criteria and probes:

  legacy    the unchanged #131 control instances (SN = label as ``.ic``, no RWL pin IC). Instance names / deck lines are the #131 ones.
  pin_ic    legacy + an explicit idle-high RWL pin initial condition ``.ic v(rwls_<inst>)=VDD`` (the #134 ``ic_artifact_check`` change).
  physical  zero-hold physical write/settle preparation: row 0's SN starts at the OPPOSITE data level (ASSUMPTION: 0 V for a '1'
            target, 1.2 V for a '0' target, so a write that does not happen is visible), the RWL pin has the explicit idle-high IC, and a
            declared ideal preparation driver writes the label voltage onto WBL through the existing 100 ohm switch model while row 0's WWL
            is pulsed (same 20 ns width as the operation's write-back). After the WWL falls the preparation driver returns WBL to 0 V (the
            legacy WBL start level) and disconnects; the operation then starts at T_PREP_NS. NO retention hold is inserted (zero hold).
            UNAVOIDABLE preparation-time change (recorded as part of the variant): every operation edge, probe and the gating probe move by
            +T_PREP_NS, and the latch / bitline nodes float for T_PREP_NS before the operation's precharge (legacy: precharge at t = 0).

Variants per regime (ideal drivers; the #131 waveforms): baseline_analog, rtl_hold, rwl_late_hold, plus the restoration negative
control neg_missing_wb (#128). Initialization negative control: ``pwnw_rwl_late_hold`` = the physical rwl_late_hold with the
preparation WWL pulse DELETED (no write), so SN stays at the opposite level; the analysis must flag its pre-read level as not the
label and its sense decisions as wrong.

Writes a NEW ``init_control_results/<RUN_ID>/`` (refuses to reuse one): rtl_trace.json, init_control.spice, request.json,
consistency_check.json (declared-change-only proof per instance against its legacy counterpart), manifest.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gen_refresh_replay as GR  # noqa: E402
import replay_lib as L  # noqa: E402

GEN = GR.G
S = GR.S
RESULTS_DIR = HERE / "init_control_results"

BASE_VARIANTS = ["baseline_analog", "rtl_hold", "rwl_late_hold", "neg_missing_wb"]   # curator-verified set (#139)
REGIMES = {"legacy": "", "pin_ic": "pic_", "physical": "pw_"}                       # variant-id prefix per regime
INIT_NEG_PREFIX = "pwnw_"                                                             # physical, preparation write deleted
INIT_NEG_BASE = "rwl_late_hold"

# ---- physical preparation: ASSUMPTIONS (declared; human review requested) ------------------------------------------------
T_PREP_NS = 24.0             # operation start (all op edges shifted by this)
PREP_WWL_RISE_NS = 1.0       # preparation write pulse on row 0's WWL (same 20 ns width as the op write-back)
PREP_WWL_FALL_NS = 21.0
PREP_WBL_RETURN_NS = 22.0    # preparation data source ramps (0.1 ns) from the label voltage back to 0 V (the legacy WBL start)
PREP_SW_OPEN_NS = 23.0       # preparation switch opens; WBL then floats at 0 V as in legacy
POST_WRITE_PROBE_NS = 21.9   # "achieved post-write level": SN after the prep WWL fall ramp, before the WBL return
OP_START_PROBE_NS = round(T_PREP_NS - 0.1, 6)
POST_INIT_PROBE_NS = 0.5     # IC regimes: SN after the t = 0 start-up steps (no write exists in these regimes)
PRE_READ_LEAD_NS = 0.1       # pre-read level = SN this long before the read-select assert edge starts
OPPOSITE_LEVEL_V = {"op1": 0.0, "op0": 1.2}   # physical regime: row-0 SN start level (opposite data; ASSUMPTION)


def vid(regime: str, base: str) -> str:
    return REGIMES[regime] + base


def shift_trace(trace: dict, dt: float) -> dict:
    """Every edge moved by +dt (initial levels unchanged). An edge at t = 0 (initial set) becomes a real edge at dt."""
    return dict(trace, edges=L.sorted_edges([dict(e, t_ns=round(e["t_ns"] + dt, 6)) for e in trace["edges"]]))


def prep_wwl_edges() -> list[tuple[float, int]]:
    return [(PREP_WWL_RISE_NS, 1), (PREP_WWL_FALL_NS, 0)]


def assert_time(trace: dict) -> float:
    return [t for t, v in L.trace_signal_edges(trace, "rwl_sel") if v == 1][0]


def build_instances(golden: dict) -> list[dict]:
    """All instances: legacy = the original #131 control instances (unchanged dicts) + pin_ic + physical + init negative + refw."""
    controls = {(i["variant"], i["kind"], i["sn"]): i for i in GR.build_instances(golden)}
    vt = GR.variant_traces(golden)
    out = []
    for regime in REGIMES:
        for base in BASE_VARIANTS:
            for kind, sn in GR.PATTERNS:
                leg = controls[(base, kind, sn)]
                if regime == "physical":
                    out.append(physical_instance(golden, vt, base, kind, sn, prep_write=True))
                    continue
                inst = dict(leg)
                if regime != "legacy":
                    inst = dict(leg, name=GR.inst_name(kind, sn, vid(regime, base)), variant=vid(regime, base))
                inst.update(regime=regime, base=base, legacy_name=leg["name"], prep_write=None, t_prep_ns=0.0,
                            t_pre_read_ns=round(assert_time(leg["trace"]) - PRE_READ_LEAD_NS, 6), t_post_init_ns=POST_INIT_PROBE_NS,
                            t_op_start_probe_ns=None, sn_ic_row0_v=sn, pin_ic=(regime == "pin_ic"), init_negative=False)
                out.append(inst)
    for kind, sn in GR.PATTERNS:
        out.append(physical_instance(golden, vt, INIT_NEG_BASE, kind, sn, prep_write=False))
    ref = controls[("reference_write", "ref", 0.0)]
    out.append(dict(ref, regime="legacy", base="reference_write", legacy_name=ref["name"], prep_write=None, t_prep_ns=0.0,
                    t_pre_read_ns=None, t_post_init_ns=None, t_op_start_probe_ns=None, sn_ic_row0_v=0.0, pin_ic=False, init_negative=False))
    names = [i["name"] for i in out]
    assert len(names) == len(set(names)), "duplicate instance name"
    return out


def physical_instance(golden: dict, vt: dict, base: str, kind: str, sn: float, prep_write: bool) -> dict:
    tr = shift_trace(vt[base]["trace"], T_PREP_NS)
    g_sh = shift_trace(golden, T_PREP_NS)
    lr = vt[base].get("latch_release")
    nodes = GR.node_waveforms(tr, vt[base]["adapter"], None if lr is None else lr + T_PREP_NS)
    tm = GR.timing(tr, g_sh, nodes)
    if prep_write:
        init, ed, inv = nodes["wwl"]
        nodes = dict(nodes, wwl=(init, prep_wwl_edges() + list(ed), inv))
    variant = (vid("physical", base) if prep_write else INIT_NEG_PREFIX + base)
    leg_name = GR.inst_name(kind, sn, base)
    return dict(name=GR.inst_name(kind, sn, variant), kind=kind, sn=sn, variant=variant, trace=tr, adapter=vt[base]["adapter"], nodes=nodes,
                regime="physical", base=base, legacy_name=leg_name, prep_write=prep_write, t_prep_ns=T_PREP_NS,
                t_pre_read_ns=round(assert_time(tr) - PRE_READ_LEAD_NS, 6), t_post_init_ns=POST_WRITE_PROBE_NS,
                t_op_start_probe_ns=OP_START_PROBE_NS, sn_ic_row0_v=OPPOSITE_LEVEL_V[kind], pin_ic=True, init_negative=not prep_write, **tm)


# ---- deck ------------------------------------------------------------------------------------------------------------------
def prep_lines(inst: dict) -> list[str]:
    """Declared ideal preparation driver (physical regime only): data source -> 100 ohm switch (existing swwbl model) -> WBL."""
    n, lab = inst["name"], inst["sn"]
    data = f"pwl(0 {S._fmt(lab)} {PREP_WBL_RETURN_NS * 1e-9:.4e} {S._fmt(lab)} {(PREP_WBL_RETURN_NS + L.T_EDGE_NS) * 1e-9:.4e} 0)"
    ctl = L.pwl_text(L.edges_to_pwl(1, [(PREP_SW_OPEN_NS, 0)], False))
    return [f"* preparation driver (physical regime; write {'ENABLED' if inst['prep_write'] else 'DELETED (init negative control)'}): "
            f"WBL <- {S._fmt(lab)} V until {PREP_WBL_RETURN_NS:g} ns, then 0 V; switch open at {PREP_SW_OPEN_NS:g} ns",
            f"vpw_{n} wpd_{n} 0 {data}", f"vpc_{n} pctl_{n} 0 {ctl}", f"spw_{n} wpd_{n} wbl_{n} pctl_{n} 0 swwbl"]


def build_deck(c_sn_f: float, insts: list[dict]) -> str:
    deck = GR.build_netlist(c_sn_f, insts)
    by = {i["name"]: i for i in insts}
    out, extra_ic = [], []
    for ln in deck.splitlines():
        if ln.startswith(".ic"):
            toks = ln.split()[1:]
            new = []
            for t in toks:
                m = re.match(r"v\(sn_(\S+)_0\)=(\S+)$", t)
                if m and m.group(1) in by and by[m.group(1)]["regime"] == "physical":
                    t = f"v(sn_{m.group(1)}_0)={S._fmt(by[m.group(1)]['sn_ic_row0_v'])}"
                new.append(t)
            out.append(".ic " + " ".join(new))
            continue
        out.append(ln)
        m = re.match(r"vwc_(\S+) ", ln)
        if m and m.group(1) in by:
            inst = by[m.group(1)]
            if inst["regime"] == "physical":
                out += prep_lines(inst)
            if inst.get("pin_ic"):
                extra_ic.append(f"v(rwls_{inst['name']})={S._fmt(GEN.VDD_V)}")
    if out and out[-1] == "":
        out.pop()
    out.append("* explicit idle-high RWL pin initial conditions (pin_ic and physical regimes ONLY; legacy has none)")
    for k in range(0, len(extra_ic), 4):
        out.append(".ic " + " ".join(extra_ic[k:k + 4]))
    out.append("")
    return "\n".join(out)


# ---- request -----------------------------------------------------------------------------------------------------------------
def extra_meas(p: dict) -> list[dict]:
    n = p["name"]
    m = [{"name": f"snpre_{n}", "unit": "V", "spice": f".meas tran snpre_{n} FIND v(sn_{n}_0) AT={p['t_pre_read_ns']:.6g}n"},
         {"name": f"snini_{n}", "unit": "V", "spice": f".meas tran snini_{n} FIND v(sn_{n}_0) AT={p['t_post_init_ns']:.6g}n"}]
    if p["t_op_start_probe_ns"] is not None:
        m.append({"name": f"snos_{n}", "unit": "V", "spice": f".meas tran snos_{n} FIND v(sn_{n}_0) AT={p['t_op_start_probe_ns']:.6g}n"})
    return m


def build_request(insts: list[dict]) -> dict:
    req = GR.build_request(insts)
    for p in insts:
        if p["kind"] != "ref":
            req["measurements"] += extra_meas(p)
    req["netlist"] = "init_control.spice"
    return req


# ---- verification: every instance differs from its legacy counterpart ONLY by its regime's declared changes ------------------
SRC = ("vctl_", "vrs_", "ven_", "venb_", "vww_", "vwc_")
PREP = ("vpw_", "vpc_", "spw_")
NODE_OF = {"vctl_": "ctl", "vrs_": "rwls", "ven_": "en", "vww_": "wwl", "vwc_": "wbc"}


def inst_lines(deck: str, name: str) -> list[str]:
    rx = re.compile(r"(?<=_)" + re.escape(name) + r"(?:_\d+)?(?![A-Za-z0-9_])")
    return [ln.replace(name, "@") for ln in deck.splitlines() if rx.search(ln) and not ln.startswith(("*", ".ic"))]


def ic_tokens(deck: str, name: str) -> dict:
    rx = re.compile(r"v\((\S+?)\)=(\S+)")
    nrx = re.compile(r"(?<=_)" + re.escape(name) + r"(?:_\d+)?$")
    out = {}
    for ln in deck.splitlines():
        if ln.startswith(".ic"):
            for node, val in rx.findall(ln):
                if nrx.search(node):
                    out[node.replace(name, "@")] = val
    return out


def _split(lines: list[str]):
    src, prep, other = {}, {}, []
    for ln in lines:
        pre = ln.split("_", 1)[0] + "_"
        if pre in SRC:
            src[pre] = ln
        elif pre in PREP:
            prep[pre] = ln
        else:
            other.append(ln)
    return src, prep, other


def expected_ics(leg_ics: dict, inst: dict) -> dict:
    want = dict(leg_ics)
    if inst["pin_ic"]:
        want["rwls_@"] = S._fmt(GEN.VDD_V)
    if inst["regime"] == "physical":
        want["sn_@_0"] = S._fmt(inst["sn_ic_row0_v"])
    return want


def verify(deck: str, insts: list[dict]) -> dict:
    by = {i["name"]: i for i in insts}
    res = {}
    for i in insts:
        n = i["name"]
        f = []
        leg = by[i["legacy_name"]]
        ls, lp, lo = _split(inst_lines(deck, leg["name"]))
        s, p, o = _split(inst_lines(deck, n))
        if o != lo:
            f.append(dict(kind="structure_changed"))
        if ic_tokens(deck, n) != expected_ics(ic_tokens(deck, leg["name"]), i):
            f.append(dict(kind="initial_conditions_changed", got=ic_tokens(deck, n), expected=expected_ics(ic_tokens(deck, leg["name"]), i)))
        if i["regime"] != "physical":
            if s != ls:
                f.append(dict(kind="control_source_changed"))
            if p:
                f.append(dict(kind="undeclared_preparation_driver"))
        else:
            want = {k: v for k, v in zip(PREP, [ln.replace(i["name"], "@") for ln in prep_lines(i)[1:]])}
            if p != want:
                f.append(dict(kind="preparation_driver_not_declared_one", got=p, expected=want))
            if s.get("venb_") is None:
                f.append(dict(kind="source_missing", source="venb_"))
            for pre, node in NODE_OF.items():
                inv = L.PIN_MAP[next(k for k, v in L.PIN_MAP.items() if v["node"] == node)]["invert"]
                try:
                    gi, ge = L.pwl_to_edges(s[pre].split(None, 3)[3], inv)
                    li, le = L.pwl_to_edges(ls[pre].split(None, 3)[3], inv)
                except (KeyError, ValueError) as ex:
                    f.append(dict(kind="source_unparsable", source=pre, detail=str(ex)))
                    continue
                exp = [(round(t + T_PREP_NS, 6), v) for t, v in le]
                raw_init = leg["nodes"][node][0]
                if li != raw_init:
                    # a legacy edge AT t = 0 (e.g. precharge on) sets the initial PWL value; shifted, it is a real edge at T_PREP
                    exp = [(T_PREP_NS, li)] + exp
                    li = raw_init
                if node == "wwl" and i["prep_write"]:
                    exp = prep_wwl_edges() + exp
                if gi != li or len(ge) != len(exp) or any(a[1] != b[1] or abs(a[0] - b[0]) > L.TIME_TOL_NS for a, b in zip(ge, exp)):
                    f.append(dict(kind="source_not_legacy_shifted_plus_declared", source=pre, got=[gi, ge], expected=[li, exp]))
        res[n] = dict(regime=i["regime"], base=i["base"], variant=i["variant"], legacy_instance=leg["name"], declared_changes_only=not f, findings=f)
    return res


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("trace", type=Path, help="golden RTL trace JSON (export_rtl_trace.py)")
    ap.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    ap.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    a = ap.parse_args(argv)
    run_dir = a.results_dir / a.run_id
    if run_dir.exists():
        print(f"refusing to reuse existing run directory {run_dir}", file=sys.stderr)
        return 2
    golden = json.loads(a.trace.read_text())
    insts = build_instances(golden)
    c_sn_ff, prov = S.load_extracted_c_sn(S.EXTRACT_JSON, "sn")
    deck = build_deck(c_sn_ff * 1e-15, insts)
    req = build_request(insts)
    check = verify(deck, insts)
    legacy_ctl = [i for i in insts if i["regime"] == "legacy"]
    ctl_check = GR.verify_deck(deck, legacy_ctl, golden)
    for n, c in ctl_check.items():
        check[n] = dict(check[n], deck_matches_trace=c["deck_matches_trace"], trace_matches_golden_rtl=c["trace_matches_golden_rtl"])
    run_dir.mkdir(parents=True)
    (run_dir / "rtl_trace.json").write_text(json.dumps(golden, indent=1) + "\n")
    (run_dir / "init_control.spice").write_text(deck)
    (run_dir / "request.json").write_text(json.dumps(req, indent=1) + "\n")
    (run_dir / "consistency_check.json").write_text(json.dumps(check, indent=1) + "\n")
    man = dict(
        run_id=a.run_id, status="PROPOSED_OPERATING_RANGE_NOT_RATIFIED", issue=139,
        regimes=dict(
            legacy="unchanged #131 control instances: SN = label (.ic), no RWL pin IC, tran uic",
            pin_ic="legacy + explicit idle-high RWL pin IC (the #134 ic_artifact_check change); nothing else",
            physical=f"zero-hold physical write/settle: row-0 SN starts at the opposite data level {OPPOSITE_LEVEL_V}, RWL pin IC idle-high, "
                     f"ideal prep driver writes the label onto WBL (100 ohm switch) with a WWL pulse {PREP_WWL_RISE_NS:g}-{PREP_WWL_FALL_NS:g} ns, "
                     f"WBL returned to 0 V at {PREP_WBL_RETURN_NS:g} ns, switch open {PREP_SW_OPEN_NS:g} ns, op shifted +{T_PREP_NS:g} ns",
            init_negative=f"{INIT_NEG_PREFIX}{INIT_NEG_BASE}: physical regime with the preparation WWL pulse deleted (SN stays at the opposite level)"),
        base_variants=BASE_VARIANTS, regime_prefixes=REGIMES, init_negative_variant=INIT_NEG_PREFIX + INIT_NEG_BASE,
        restoration_negative_base="neg_missing_wb",
        preparation_assumptions=dict(t_prep_ns=T_PREP_NS, prep_wwl_rise_ns=PREP_WWL_RISE_NS, prep_wwl_fall_ns=PREP_WWL_FALL_NS,
                                     prep_wbl_return_ns=PREP_WBL_RETURN_NS, prep_switch_open_ns=PREP_SW_OPEN_NS, opposite_level_v=OPPOSITE_LEVEL_V,
                                     prep_driver="ideal PWL source at the label voltage through the existing 100 ohm swwbl switch model",
                                     hold_ns=0.0, unavoidable_changes="all op edges/probes +T_PREP; latch/bitline nodes float for T_PREP before the op precharge",
                                     note="ASSUMPTIONS; the label voltage is driven, not tuned: the achieved post-write level is measured and reported"),
        probe_definitions=dict(
            snpre="PRE-READ level: SN of row 0 at (read-select assert edge start - 0.1 ns); the nominal label never stands in for it",
            snini="IC regimes: SN at 0.5 ns (after the t = 0 start-up steps). physical: ACHIEVED POST-WRITE level, SN at 21.9 ns (after the prep WWL fall ramp)",
            snos="physical only: SN at op start - 0.1 ns (after the WBL return and switch open)",
            dec="signed latch decision d = V(rbl) - V(ref) just before the op WWL rise (stored '1' -> d <= -0.9 V, '0' -> d >= +0.9 V)",
            snend="SN at the gating restore probe (#131 control value, +T_PREP in the physical regime)"),
        deck_sha256=hashlib.sha256(deck.encode()).hexdigest(), request_sha256=hashlib.sha256((json.dumps(req, indent=1) + "\n").encode()).hexdigest(),
        patterns=[dict(kind=k, sn_v=v) for k, v in GR.PATTERNS],
        instances=[dict(name=p["name"], kind=p["kind"], sn_v=p["sn"], variant=p["variant"], regime=p["regime"], base=p["base"],
                        legacy_instance=p["legacy_name"], prep_write=p["prep_write"], init_negative=p["init_negative"], pin_ic=p["pin_ic"],
                        sn_ic_row0_v=p["sn_ic_row0_v"], t_prep_ns=p["t_prep_ns"], t_pre_read_ns=p["t_pre_read_ns"], t_post_init_ns=p["t_post_init_ns"],
                        t_op_start_probe_ns=p["t_op_start_probe_ns"], t_dec_ns=p["t_dec_ns"], t_wwl_rise_ns=p["t_wwl_rise_ns"],
                        t_wwl_fall_ns=p["t_wwl_fall_ns"], t_release_ns=p["t_release_ns"], t_meas_ns=p["t_meas_ns"]) for p in insts],
        assumptions=dict(cycle_ns=1.0, vdd_v=L.VDD_V, c_rbl_f=S.C_RBL_F, c_wbl_f=GEN.C_WBL_F, c_sn_ff=c_sn_ff, c_sn_provenance=str(prov),
                         circuit="sim/refresh-op circuit body via gen_refresh_replay.build_netlist (ideal drivers, 100 ohm switches, 4-row column)"),
        pins=GR.pins(golden))
    for f in ("gen_init_control.py", "analyze_init_control.py", "gen_rwl_driver_sweep.py", "replay_lib.py"):
        man["pins"]["source_sha256"][f"sim/refresh-replay/{f}"] = sha(HERE / f) if (HERE / f).exists() else None
    (run_dir / "manifest.json").write_text(json.dumps(man, indent=1) + "\n")
    bad = [n for n, c in check.items() if not c["declared_changes_only"] or not c.get("deck_matches_trace", True)]
    print(f"wrote {run_dir} ({len(insts)} instances); mismatches: {bad or 'none'}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
