#!/usr/bin/env python3
"""Generate the RWL-driver slew / impedance / release-delay sensitivity study (issue #134). Stdlib only.

EXPERIMENTAL STIMULUS MODEL -- NOT a designed physical driver. The selected row's read-wordline (RWL) source
(the read-device source pin of row 0, active-low) is driven by an ideal PWL source whose edge ramp time
(``slew_ns``, 0 -> 100 % linear, applied to every RWL edge) and series output resistance (``r_ohm``, between the
source and the cell pin) are the declared parameters. The cell pin is the node ``rwls_<inst>``; voltages and
threshold crossings are recorded THERE, never at the source. Everything else (circuit, loads, write pulse, initial
levels, latch hold, restoration thresholds, fixed gating probe time) is the unchanged #131 deck.

Writes a NEW ``driver_sweep_results/<RUN_ID>/`` (refuses to reuse one):
  rtl_trace.json, rwl_driver_sweep.spice, request.json, waveforms.json (source-edge PWL per instance),
  consistency_check.json (deck-vs-declared-parameter check per instance), manifest.json (points, probes, pins).

Controls (``ctl`` group) are the ten original #131 variants, unchanged, with the original instance names.
Sweep points are derived from three bases at identical loads / write pulses / initial levels / thresholds:
  an  baseline_analog (RWL release 37 ns)      rh  rtl_hold (RWL release 12 ns)      rl  rwl_late_hold (release 34 ns)
plus negative controls  nr (missing write-back, release 12)  and  nl (missing write-back, RWL release 34).
Sweep VALUES are ASSUMPTIONS (no committed driver design exists); they bracket the cell-pin RC and edge times
of interest and are reviewed by a human, not sourced.
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
RESULTS_DIR = HERE / "driver_sweep_results"
IDEAL_SLEW_NS = L.T_EDGE_NS          # the ideal control edge (0.1 ns)

# ---- sweep values: ASSUMPTIONS (human review of bounds requested in the PR) --------------------------------
SLEW_ONLY_NS = [0.5, 1.0, 2.0, 5.0]                 # R = 0 (no series resistor)
R_ONLY_OHM = [1e3, 3e3, 1e4, 3e4, 1e5, 3e5, 1e6]     # slew = ideal 0.1 ns (series R also degenerates the read path: the pin sinks the read current)
COMBINED = [(1.0, 1e4), (1.0, 1e5), (2.0, 1e4), (2.0, 1e5)]   # (slew_ns, r_ohm) -- only after the axes above
RELEASE_DELAYS_NS = [-16.0, -8.0, -4.0, -2.0, 0.0, 1.0, 2.0, 3.0]    # RWL release start minus WWL fall start (32 ns); +2 = the #131 rwl_late_hold
RELEASE_DRIVERS = [(IDEAL_SLEW_NS, 0.0), (1.0, 1e4), (2.0, 1e5)]
# group ic_artifact_check: SAME as the ideal / R points but with an explicit idle-high pin initial condition (see README: the legacy
# controls have none, so under `uic` the pin steps 0 -> VDD in the first step and lifts the stored level by ~0.1 V before the read).
IC_CHECK = [("an", IDEAL_SLEW_NS, 0.0), ("rh", IDEAL_SLEW_NS, 0.0), ("rl", IDEAL_SLEW_NS, 0.0), ("rl", IDEAL_SLEW_NS, 1e3), ("rl", IDEAL_SLEW_NS, 1e4)]
WWL_FALL_NS = 32.0                                   # unchanged RTL
BASES = {"an": "baseline_analog", "rh": "rtl_hold", "rl": "rwl_late_hold", "nr": "neg_missing_wb", "nl": "neg_missing_wb"}
NEG_BASES = ("nr", "nl")
TRAJ_OFFSETS_NS = [0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 24.0]   # SN trajectory probes after the LAST control edge start
VPIN_FRACS = {"10": 0.1, "50": 0.5, "90": 0.9}            # cell-pin threshold crossings (fractions of VDD)


def fmt_num(x: float) -> str:
    return ("%g" % x).replace(".", "p").replace("-", "m").replace("+", "")


def fmt_r(r: float) -> str:
    if r <= 0:
        return "r0"
    # lower case ONLY: ngspice case-folds .meas names and the fleet runner matches them case-sensitively (klayout-tools#2914)
    if r >= 1e3 and r % 1e3 == 0:
        return "r%dk" % (r // 1e3)
    return "r%g" % r


def point_id(base: str, slew: float, r: float, delay: float | None) -> str:
    p = f"{base}_s{fmt_num(slew)}_{fmt_r(r)}"
    if delay is not None:
        p += "_d" + ("%+06.1f" % delay).replace("+", "p").replace("-", "m").replace(".", "p")   # fixed width: no id is a prefix of another
    return p


def sweep_points() -> list[dict]:
    """Declared sweep. Axes are varied independently BEFORE the combined points."""
    pts: list[dict] = []

    def add(base, slew, r, group, delay=None, release=None, pin_ic=False):
        pts.append(dict(id=point_id(base, slew, r, delay) + ("_ic" if pin_ic else ""), base=base, parent=BASES[base], slew_ns=slew, r_ohm=r,
                        group=group, release_delay_ns=delay, rwl_release_ns=release, pin_ic=pin_ic))

    for base in ("an", "rh", "rl"):
        for sl in SLEW_ONLY_NS:
            add(base, sl, 0.0, "slew_only")
        for r in R_ONLY_OHM:
            add(base, IDEAL_SLEW_NS, r, "r_only")
        for sl, r in COMBINED:
            add(base, sl, r, "combined")
    for sl, r in RELEASE_DRIVERS:
        for d in RELEASE_DELAYS_NS:
            add("rl", sl, r, "release_delay", delay=d, release=round(WWL_FALL_NS + d, 6))
    for base, sl, r in IC_CHECK:
        add(base, sl, r, "ic_artifact_check", pin_ic=True)
    # negative controls: missing write-back must stay a failure, incl. with the late RWL release the study is about
    for sl, r in RELEASE_DRIVERS:
        add("nr", sl, r, "negative_control")
        add("nl", sl, r, "negative_control", release=GR.RWL_LATE_NS)
    ids = [p["id"] for p in pts]
    assert len(ids) == len(set(ids)), "duplicate sweep point id"
    return pts


def point_trace(pt: dict, golden: dict) -> tuple[dict, bool]:
    b = pt["base"]
    if b == "an":
        return GR.baseline_trace(), False
    tr = L.mutate_trace(golden, "missing_wb") if b in NEG_BASES else golden
    if pt["rwl_release_ns"] is not None or b == "rl":
        tr = L.retime_edge(tr, "rwl_sel", 0, pt["rwl_release_ns"] if pt["rwl_release_ns"] is not None else GR.RWL_LATE_NS)
    return tr, True


def build_sweep_instances(golden: dict, controls: list[dict], points: list[dict]) -> list[dict]:
    ctl_meas = {}
    for c in controls:
        ctl_meas.setdefault(c["variant"], c["t_meas_ns"])
    out = []
    for pt in points:
        tr, ad = point_trace(pt, golden)
        nodes = GR.node_waveforms(tr, ad)
        tm = GR.timing(tr, golden, nodes)
        gate = ctl_meas[pt["parent"]]
        rel_edges = [t for t, v in L.trace_signal_edges(tr, "rwl_sel") if v == 0]
        as_edges = [t for t, v in L.trace_signal_edges(tr, "rwl_sel") if v == 1]
        ctl_last = tm["t_release_ns"]
        tm = dict(tm, t_meas_rel_ns=tm["t_meas_ns"], t_meas_ns=gate, t_meas_fixed_ns=gate)   # gating probe NEVER moved
        for kind, sn in GR.PATTERNS:
            out.append(dict(name=GR.inst_name(kind, sn, pt["id"]), kind=kind, sn=sn, variant=pt["id"], point=pt, trace=tr, adapter=ad,
                            nodes=nodes, t_src_assert_start_ns=as_edges[0], t_src_release_start_ns=rel_edges[-1],
                            t_src_release_50_ns=round(rel_edges[-1] + pt["slew_ns"] / 2, 6),
                            t_src_release_end_ns=round(rel_edges[-1] + pt["slew_ns"], 6), ctl_last_ns=ctl_last, **tm))
    return out


def rwl_source_line(inst: dict) -> list[str]:
    n, pt = inst["name"], inst["point"]
    init, edges, inv = inst["nodes"]["rwls"]
    pts = L.edges_to_pwl(init, edges, inv, pt["slew_ns"])
    if pt["r_ohm"] > 0:
        return [f"vrs_{n} rwlsrc_{n} 0 {L.pwl_text(pts)}", f"rdrv_{n} rwlsrc_{n} rwls_{n} {pt['r_ohm']:g}"]
    return [f"vrs_{n} rwls_{n} 0 {L.pwl_text(pts)}"]


def build_deck(c_sn_f: float, controls: list[dict], sweep: list[dict]) -> str:
    # the shared structure is GR's (unchanged) netlist writer; only the RWL source of sweep instances is rewritten
    deck = GR.build_netlist(c_sn_f, controls + sweep)
    sweep_by_name = {i["name"]: i for i in sweep}
    out, ics = [], []
    for ln in deck.splitlines():
        m = re.match(r"vrs_(\S+) ", ln)
        if m and m.group(1) in sweep_by_name:
            inst = sweep_by_name[m.group(1)]
            out.append(f"* RWL driver model (EXPERIMENTAL): slew {inst['point']['slew_ns']:g} ns, series R {inst['point']['r_ohm']:g} ohm;"
                       f" cell pin = rwls_{inst['name']}")
            out += rwl_source_line(inst)
            # Default: NO pin initial condition (as the legacy controls) so every sweep instance starts in the same effective regime
            # (under `uic` the forced/charged pin steps 0 -> VDD at t = 0 and injects charge onto SN through the read device;
            # see the README). `pin_ic` points (group ic_artifact_check) DECLARE an explicit idle-high pin IC to quantify that artifact.
            if inst["point"].get("pin_ic"):
                ics.append(f"v(rwls_{inst['name']})={S._fmt(GEN.VDD_V)}" + (f" v(rwlsrc_{inst['name']})={S._fmt(GEN.VDD_V)}" if inst["point"]["r_ohm"] > 0 else ""))
            continue
        out.append(ln)
    out.append("* initial conditions of the finite-impedance RWL pins (idle = VDD)")
    for k in range(0, len(ics), 4):
        out.append(".ic " + " ".join(ics[k:k + 4]))
    out.append("")
    return "\n".join(out)


# ---- probes / request ---------------------------------------------------------------------------------------
def traj_times(p: dict) -> list[float]:
    return [round(p["t_release_ns"] + o, 6) for o in TRAJ_OFFSETS_NS]


def extra_meas(p: dict) -> list[dict]:
    n = p["name"]
    m = []
    for k, t in enumerate(traj_times(p)):
        m.append({"name": f"snt{k}_{n}", "unit": "V", "spice": f".meas tran snt{k}_{n} FIND v(sn_{n}_0) AT={t:.6g}n"})
    m.append({"name": f"snpre_{n}", "unit": "V", "spice": f".meas tran snpre_{n} FIND v(sn_{n}_0) AT=1.9n"})   # effective stored level before RWL assert
    # cell-pin (read-device source) voltages and threshold crossings; the source is never probed
    m.append({"name": f"pinm_{n}", "unit": "V", "spice": f".meas tran pinm_{n} FIND v(rwls_{n}) AT={p['t_meas_ns']:.6g}n"})
    m.append({"name": f"pina_{n}", "unit": "V", "spice": f".meas tran pina_{n} FIND v(rwls_{n}) AT={p['t_after_rwl_rel_ns']:.6g}n"})
    for tag, fr in VPIN_FRACS.items():
        m.append({"name": f"tp{tag}r_{n}", "unit": "s",
                  "spice": f".meas tran tp{tag}r_{n} WHEN v(rwls_{n})={fr * GEN.VDD_V:.4g} RISE=1"})
    m.append({"name": f"tpa50_{n}", "unit": "s", "spice": f".meas tran tpa50_{n} WHEN v(rwls_{n})={0.5 * GEN.VDD_V:.4g} FALL=1"})
    if p["t_wwl_fall_ns"] is not None:
        m.append({"name": f"twf50_{n}", "unit": "s", "spice": f".meas tran twf50_{n} WHEN v(wwl_{n})={0.5 * GEN.VDD_V:.4g} FALL=1"})
    return m


def build_request(allinst: list[dict]) -> dict:
    req = GR.build_request(allinst)
    for p in allinst:
        if p["kind"] != "ref":
            req["measurements"] += extra_meas(p)
    t_stop = max([GR.t_stop_ns(allinst)] + [max(traj_times(p)) + 1.0 for p in allinst if p["kind"] != "ref"])
    req["analysis"] = {"kind": "tran", "args": f"10p {t_stop:.6g}n 0 50p uic"}
    req["netlist"] = "rwl_driver_sweep.spice"
    return req


# ---- verification (declared-change-only proof) ----------------------------------------------------------------
SRC_PREFIXES = ("vctl_", "vrs_", "ven_", "venb_", "vww_", "vwc_")


def inst_lines(deck: str, name: str) -> list[str]:
    rx = re.compile(r"(?<=_)" + re.escape(name) + r"(?:_\d+)?(?![A-Za-z0-9_])")
    return [ln.replace(name, "@") for ln in deck.splitlines() if rx.search(ln) and not ln.startswith(("*", ".ic"))]


def ic_tokens(deck: str, name: str) -> dict:
    """``.ic v(node)=value`` tokens of one instance, name masked."""
    rx = re.compile(r"v\((\S+?)\)=(\S+)")
    nrx = re.compile(r"(?<=_)" + re.escape(name) + r"(?:_\d+)?$")
    out = {}
    for ln in deck.splitlines():
        if ln.startswith(".ic"):
            for node, val in rx.findall(ln):
                if nrx.search(node):
                    out[node.replace(name, "@")] = val
    return out


def split_lines(lines: list[str]):
    srcs, other = {}, []
    for ln in lines:
        pre = ln.split("_", 1)[0] + "_"
        if pre in SRC_PREFIXES:
            srcs[pre] = ln
        else:
            other.append(ln)
    return srcs, other


def verify_sweep(deck: str, allinst: list[dict]) -> dict:
    """Per sweep instance: relative to the same-pattern PARENT control instance, the only differences are
    (a) the RWL source ramp time, (b) the declared RWL release time, (c) the added series resistor. Per control
    instance: its own deck sources reproduce its edge list. Everything else must be byte-identical."""
    ctl = {(i["variant"], i["kind"], i["sn"]): i for i in allinst if "point" not in i}
    res = {}
    for i in allinst:
        name = i["name"]
        findings = []
        if "point" not in i:
            res[name] = dict(variant=i["variant"], group="control", declared_changes_only=True, findings=[])
            continue
        pt = i["point"]
        par = ctl[(pt["parent"], i["kind"], i["sn"])]
        ps, po = split_lines(inst_lines(deck, par["name"]))
        ss, so = split_lines(inst_lines(deck, name))
        rdrv = [ln for ln in so if ln.startswith("rdrv_")]
        so = [ln for ln in so if not ln.startswith("rdrv_")]
        # the series resistor splits the source/pin node; mask it to compare the structure
        so = [ln.replace("rwlsrc_@", "rwls_@") for ln in so]
        if so != po:
            findings.append(dict(kind="structure_changed"))
        if bool(rdrv) != (pt["r_ohm"] > 0):
            findings.append(dict(kind="rdrv_presence_mismatch"))
        for r_ln in rdrv:
            if r_ln.split()[-1] != "%g" % pt["r_ohm"]:
                findings.append(dict(kind="rdrv_value_mismatch", line=r_ln))
        for pre in SRC_PREFIXES:
            if pre == "vrs_":
                continue
            if ss.get(pre) != ps.get(pre):
                findings.append(dict(kind="other_source_changed", source=pre))
        # initial conditions: identical to the parent's, plus ONLY the declared idle-high pin IC (group ic_artifact_check)
        want = dict(ic_tokens(deck, par["name"]))
        if pt.get("pin_ic"):
            want["rwls_@"] = "1.8"
            if pt["r_ohm"] > 0:
                want["rwlsrc_@"] = "1.8"
        if ic_tokens(deck, name) != want:
            findings.append(dict(kind="initial_conditions_changed", got=ic_tokens(deck, name), expected=want))
        # RWL source: parse back with the declared slew and compare with the parent edge list (+declared release)
        init, edges, inv = i["nodes"]["rwls"]
        try:
            g_init, g_edges = L.pwl_to_edges(ss["vrs_"].split(None, 3)[3], inv, pt["slew_ns"])
        except (KeyError, ValueError) as ex:
            findings.append(dict(kind="rwl_source_unparsable", detail=str(ex)))
            g_init, g_edges = None, None
        p_init, p_edges, _ = par["nodes"]["rwls"]
        exp_edges = list(p_edges)
        declared_release = pt["rwl_release_ns"]
        if declared_release is not None:
            exp_edges = [(declared_release if v == 0 else t, v) for t, v in exp_edges]
        if g_edges is not None:
            if g_init != init or len(g_edges) != len(exp_edges) or any(a[1] != b[1] or abs(a[0] - b[0]) > L.TIME_TOL_NS
                                                                     for a, b in zip(sorted(g_edges), sorted(exp_edges))):
                findings.append(dict(kind="rwl_edges_not_parent_plus_declared_release", got=g_edges, expected=exp_edges))
        # the other control nodes' logical waveforms equal the parent's
        d = [x for x in L.diff_node_waveforms(par["nodes"], i["nodes"]) if x["node"] != "rwls"]
        if d:
            findings.append(dict(kind="other_node_waveform_changed", diffs=d))
        res[name] = dict(variant=i["variant"], group=pt["group"], parent_instance=par["name"], declared=dict(
            slew_ns=pt["slew_ns"], r_ohm=pt["r_ohm"], rwl_release_ns=declared_release), declared_changes_only=not findings,
            findings=findings)
    return res


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("trace", type=Path, help="golden RTL trace JSON (export_rtl_trace.py)")
    ap.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    ap.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    ap.add_argument("--only", default=None, help="DEBUG: comma list of sweep point ids (plus no controls) -> small probe deck")
    a = ap.parse_args(argv)
    run_dir = a.results_dir / a.run_id
    if run_dir.exists():
        print(f"refusing to reuse existing run directory {run_dir}", file=sys.stderr)
        return 2
    golden = json.loads(a.trace.read_text())
    controls = GR.build_instances(golden)
    points = sweep_points()
    if a.only:
        keep = set(a.only.split(","))
        points = [p for p in points if p["id"] in keep]
        controls = [c for c in controls if c["variant"] in {"rtl_hold", "baseline_analog", "rwl_late_hold", "neg_missing_wb", "reference_write"}]
    sweep = build_sweep_instances(golden, controls, points)
    allinst = controls + sweep
    c_sn_ff, prov = S.load_extracted_c_sn(S.EXTRACT_JSON, "sn")
    deck = build_deck(c_sn_ff * 1e-15, controls, sweep)
    req = build_request(allinst)
    check = verify_sweep(deck, allinst)
    ctl_check = GR.verify_deck(deck, controls, golden)       # controls: deck vs trace / golden RTL (as #131)
    for n, c in ctl_check.items():
        check[n] = dict(check[n], deck_matches_trace=c["deck_matches_trace"], trace_matches_golden_rtl=c["trace_matches_golden_rtl"],
                        experiment_diff=c.get("experiment_diff"))
    run_dir.mkdir(parents=True)
    (run_dir / "rtl_trace.json").write_text(json.dumps(golden, indent=1) + "\n")
    (run_dir / "rwl_driver_sweep.spice").write_text(deck)
    (run_dir / "request.json").write_text(json.dumps(req, indent=1) + "\n")
    wf = {}
    for p in sweep:
        if p["point"]["id"] in wf:
            continue
        wf[p["point"]["id"]] = dict(point=p["point"], source_edges_ns=[[t, v] for t, v in p["nodes"]["rwls"][1]],
                                    rwl_source_pwl_ns_level=[[t, lv] for t, lv in L.edges_to_pwl(*p["nodes"]["rwls"], p["point"]["slew_ns"])],
                                    t_src_release_start_ns=p["t_src_release_start_ns"], t_src_release_50_ns=p["t_src_release_50_ns"],
                                    t_src_release_end_ns=p["t_src_release_end_ns"], t_wwl_fall_start_ns=p["t_wwl_fall_ns"])
    (run_dir / "waveforms.json").write_text(json.dumps(wf, indent=1) + "\n")
    (run_dir / "consistency_check.json").write_text(json.dumps(check, indent=1) + "\n")
    man = dict(
        run_id=a.run_id, status="PROPOSED_OPERATING_RANGE_NOT_RATIFIED", issue=134,
        experimental_stimulus_model="RWL source: PWL with declared 0-100% ramp time (all RWL edges) + series resistor to the cell pin; NOT a designed physical driver",
        sweep_values_assumptions=dict(slew_only_ns=SLEW_ONLY_NS, r_only_ohm=R_ONLY_OHM, combined_slew_ns_r_ohm=COMBINED,
                                      release_delays_ns=RELEASE_DELAYS_NS, release_drivers_slew_ns_r_ohm=RELEASE_DRIVERS, ic_artifact_check=IC_CHECK,
                                      wwl_fall_start_ns=WWL_FALL_NS, ideal_slew_ns=IDEAL_SLEW_NS,
                                      note="ASSUMPTIONS; no committed driver design exists. Human review of bounds requested."),
        deck_sha256=hashlib.sha256(deck.encode()).hexdigest(), request_sha256=hashlib.sha256((json.dumps(req, indent=1) + "\n").encode()).hexdigest(),
        control_variants=GR.VARIANTS, control_negatives=GR.NEGATIVE, patterns=[dict(kind=k, sn_v=v) for k, v in GR.PATTERNS],
        points=points, traj_offsets_ns=TRAJ_OFFSETS_NS,
        probe_definitions=dict(
            snend="SN of row 0 at the FIXED gating time t_meas_fixed_ns (36 ns RTL-derived / 39 ns analog baseline = the #131 control values); never moved with the release delay, slew or R",
            snset="SN at last-control-edge-start + 10 ns (diagnostic, not gating)",
            snt_k="SN at last-control-edge-start + TRAJ_OFFSETS_NS[k] (diagnostic trajectory; quantized time-to-restore)",
            pinm_pina="voltage at the CELL PIN (read-device source, node rwls_<inst>) at t_meas and at release start + 0.2 ns",
            tp10r_tp50r_tp90r="time of the cell-pin rising crossing of 10/50/90 % VDD (the RWL release; .meas WHEN RISE=1), seconds",
            tpa50="time of the cell-pin falling 50 % crossing (the RWL assert), seconds",
            twf50="time of the WWL falling 50 % crossing at the WWL pin, seconds (absent for missing-write-back instances)",
            source_edge_timing="t_src_release_start_ns (programmed edge start), t_src_release_50_ns = start + slew/2, t_src_release_end_ns = start + slew; "
                               "distinct from the measured pin crossings"),
        instances=[dict(name=p["name"], kind=p["kind"], sn_v=p["sn"], variant=p["variant"], group=p["point"]["group"] if "point" in p else "control",
                        point=p.get("point"), t_dec_ns=p["t_dec_ns"], t_wwl_rise_ns=p["t_wwl_rise_ns"], t_wwl_fall_ns=p["t_wwl_fall_ns"],
                        t_release_ns=p["t_release_ns"], t_meas_ns=p["t_meas_ns"], t_rwl_release_ns=p["t_rwl_release_ns"],
                        t_latch_release_ns=p["t_latch_release_ns"], t_after_rwl_rel_ns=p["t_after_rwl_rel_ns"],
                        t_src_release_start_ns=p.get("t_src_release_start_ns"), t_src_release_50_ns=p.get("t_src_release_50_ns"),
                        t_src_release_end_ns=p.get("t_src_release_end_ns"), traj_times_ns=traj_times(p),
                        digital=L.digital_duration(p["trace"]) if p["variant"] not in ("baseline_analog", "reference_write") and not str(p["variant"]).startswith("an_") else None)
                   for p in allinst],
        assumptions=dict(cycle_ns=1.0, vdd_v=L.VDD_V, budget_cycles_provisional=34, c_rbl_f=S.C_RBL_F, c_wbl_f=GEN.C_WBL_F, c_sn_ff=c_sn_ff,
                         c_sn_provenance=str(prov), loads_fixed="C_RBL, C_WBL, C_SN, 100 ohm switches, other rows' RWL (ideal VDD) are identical to #131; the "
                         "driver model adds only the RWL source ramp time and a series resistor on the selected row"),
        pins=GR.pins(golden))
    man["pins"]["source_sha256"]["sim/refresh-replay/gen_rwl_driver_sweep.py"] = sha(HERE / "gen_rwl_driver_sweep.py")
    man["pins"]["source_sha256"]["sim/refresh-replay/analyze_rwl_driver_sweep.py"] = sha(HERE / "analyze_rwl_driver_sweep.py") if (HERE / "analyze_rwl_driver_sweep.py").exists() else None
    man["pins"]["source_sha256"]["sim/refresh-replay/replay_lib.py"] = sha(HERE / "replay_lib.py")
    (run_dir / "manifest.json").write_text(json.dumps(man, indent=1) + "\n")
    bad = [n for n, c in check.items() if not c["declared_changes_only"] or not c.get("deck_matches_trace", True)]
    print(f"wrote {run_dir} ({len(allinst)} instances: {len(controls)} control, {len(sweep)} sweep); mismatches: {bad or 'none'}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
