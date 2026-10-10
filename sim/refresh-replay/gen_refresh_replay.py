#!/usr/bin/env python3
"""Generate the RTL-strobe replay deck + `klt sim` request for one run (issue #128).

Stdlib only. Inputs: a golden RTL trace (export_rtl_trace.py). Writes a NEW run directory
``results/<RUN_ID>/`` (refuses to reuse one) holding:

* ``rtl_trace.json``          copy of the golden trace
* ``refresh_replay.spice``    flat circuit body for `klt sim` (same circuit as sim/refresh-op)
* ``request.json``            5 process corners x {27, 125} C, one `tran`, backend batch
* ``waveforms.json``          every converted control waveform, incl. the latch-hold adapter waveform
* ``consistency_check.json``  deck-vs-trace and trace-vs-golden findings per variant
* ``manifest.json``           variants, instances, timing, assumptions and source/tool pins

Variants (same circuit, initial levels, loads, restore criteria; only the control waveform differs):
  baseline_analog  the existing sim/refresh-op sequence at SENSE 10 ns, WWL 20 ns (re-created from its generator)
  rtl_raw          RTL edges converted 1:1 through PIN_MAP (1-cycle sample pulse drives the latch enable)
  rtl_hold         rtl_raw + the explicit latch-hold adapter (enable set at sense_en rise, held to busy fall)
  neg_missing_wb   rtl_hold with the wwl_en/bl_drive edges deleted         (negative control, must fail restore)
  neg_short_wb     rtl_hold with a 0.2 ns write-back pulse                  (negative control, must fail restore)
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "sim" / "refresh-op"))
sys.path.insert(0, str(REPO / "sim" / "sense-stage"))
sys.path.insert(0, str(REPO / "sim"))
import replay_lib as L  # noqa: E402
import gen_refresh_op as G  # noqa: E402
import gen_sense_stage as S  # noqa: E402

BASE_SENSE_S, BASE_WB_S = 10e-9, 20e-9        # the existing contract-sense / ideal-reference pulse point
PATTERNS = [("op1", v) for v in G.SN1_PRE_V] + [("op0", v) for v in G.SN0_PRE_V]
VARIANTS = ["baseline_analog", "rtl_raw", "rtl_hold", "neg_missing_wb", "neg_short_wb"]
NEGATIVE = {"neg_missing_wb": "missing_wb", "neg_short_wb": "short_wb"}
T_MEAS_NS = G.T_MEAS_S * 1e9
SN_DEC_LEAD_NS = 0.1       # decision / pre-read probes this long before the reference WWL rise (as sim/refresh-op)
STROBES = list(L.PIN_MAP)


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def baseline_trace() -> dict:
    """The sim/refresh-op sequence for (SENSE 10 ns, WWL 20 ns) as a logical strobe edge list."""
    t = G.times(BASE_SENSE_S, BASE_WB_S)
    ns = {k: round(v * 1e9, 6) for k, v in t.items()}
    e = [L.edge(0, "pre_en", 1), L.edge(G.T_PRE_ON_S * 1e9, "pre_en", 0),
         L.edge(G.T_READ_S * 1e9, "rwl_sel", 1), L.edge(ns["t_rel"], "rwl_sel", 0),
         L.edge(ns["t_en"], "sense_en", 1), L.edge(ns["t_rel"], "sense_en", 0),
         L.edge(ns["t_on"], "wwl_en", 1), L.edge(ns["t_off"], "wwl_en", 0),
         L.edge(ns["t_on"], "bl_drive", 1), L.edge(ns["t_rel"], "bl_drive", 0),
         L.edge(0, "busy", 1), L.edge(ns["t_rel"], "busy", 0)]
    return dict(initial={s: 0 for s in L.SIGNALS}, edges=L.sorted_edges(e))


def variant_traces(golden: dict) -> dict:
    """variant -> dict(trace=<logical strobe trace>, adapter=<None|latch hold waveform>, ...)."""
    out = {"baseline_analog": dict(trace=baseline_trace(), adapter=False),
           "rtl_raw": dict(trace=golden, adapter=False),
           "rtl_hold": dict(trace=golden, adapter=True)}
    for name, kind in NEGATIVE.items():
        out[name] = dict(trace=L.mutate_trace(golden, kind), adapter=True)
    return out


def node_waveforms(trace: dict, adapter: bool) -> dict:
    """node -> (initial logical value, edges, invert); the enable node optionally replaced by the adapter."""
    nodes = {}
    for sig, pm in L.PIN_MAP.items():
        nodes[pm["node"]] = (trace["initial"].get(sig, 0), L.trace_signal_edges(trace, sig), pm["invert"])
    if adapter:
        ad = L.latch_hold_adapter(trace)
        nodes[L.ADAPTER_NODE] = (ad["initial"], ad["edges"], False)
    return nodes


def node_pwl(nodes: dict) -> dict:
    return {n: L.edges_to_pwl(init, edges, inv) for n, (init, edges, inv) in nodes.items()}


def timing(trace: dict, golden: dict, nodes: dict) -> dict:
    """Probe times (ns). The decision / pre-read probes use the GOLDEN WWL rise so the negative controls
    (which delete or shorten the write-back) are still probed at the instant the write would start."""
    wr = [t for t, v in L.trace_signal_edges(trace, "wwl_en") if v == 1]
    wf = [t for t, v in L.trace_signal_edges(trace, "wwl_en") if v == 0]
    gwr = [t for t, v in L.trace_signal_edges(golden, "wwl_en") if v == 1]
    ref_rise = (wr or gwr)[0]
    ctl_last = max(t for n, (i, ed, inv) in nodes.items() for t, _ in ed) if any(ed for _, ed, _ in nodes.values()) else 0.0
    return dict(t_dec_ns=round(ref_rise - SN_DEC_LEAD_NS, 6), t_wwl_rise_ns=wr[0] if wr else None,
                t_wwl_fall_ns=wf[0] if wf else None, t_release_ns=ctl_last, t_meas_ns=round(ctl_last + T_MEAS_NS, 6),
                t_wbl_probe_ns=round((wf[0] if wf else ref_rise + 1.0) - SN_DEC_LEAD_NS, 6))


def inst_name(kind: str, sn: float, variant: str) -> str:
    tag = ("n%03d" % round(-sn * 1000)) if sn < 0 else ("%04d" % round(sn * 1000))
    return f"{kind}_{tag}_{variant}"


def build_instances(golden: dict) -> list[dict]:
    vt = variant_traces(golden)
    insts = []
    for variant in VARIANTS:
        tr, ad = vt[variant]["trace"], vt[variant]["adapter"]
        nodes = node_waveforms(tr, ad)
        tm = timing(tr, golden, nodes)
        for kind, sn in PATTERNS:
            insts.append(dict(name=inst_name(kind, sn, variant), kind=kind, sn=sn, variant=variant, trace=tr,
                              adapter=ad, nodes=nodes, **tm))
    # in-deck reference write: SN from 0 V, ideal 1.8 V WBL, 20 ns WWL (as sim/refresh-op `refw`)
    bt = baseline_trace()
    tm = timing(bt, golden, node_waveforms(bt, False))
    insts.append(dict(name="refw", kind="ref", sn=0.0, variant="reference_write", trace=bt, adapter=False,
                      nodes=node_waveforms(bt, False), **tm))
    return insts


def src_line(prefix: str, node: str, name: str, pts) -> str:
    return f"{prefix}_{name} {node}_{name} 0 {L.pwl_text(pts)}"


def build_netlist(c_sn_f: float, insts: list[dict]) -> str:
    (wr_m, wr_p), (rd_m, rd_p) = S.design_cell_cards()
    Ln: list[str] = []
    a = Ln.append
    a("* refresh_replay.spice -- RTL-strobe replay of one REFRESH op in the refresh-op circuit, issue #128")
    a("* GENERATED by gen_refresh_replay.py; do not edit by hand.")
    a("*")
    a("* PROPOSED/UNRATIFIED SCOPE: 27 C and 125 C, tt/ss/ff/sf/fs global corners, 1.8 V, no mismatch.")
    a("* Circuit body identical to sim/refresh-op/refresh_op.spice (ideal drivers, 100 ohm switches,")
    a("* C_RBL = C_WBL = 10 fF assumed, 4-row column, ref = VRBL - 100 mV, same latch); ONLY the control")
    a("* PWL sources differ. Sources per instance: ctl<-pre_en, rwls<-rwl_sel (inverted), en/enb<-sense_en")
    a("* (or the latch-hold adapter waveform), wwl<-wwl_en, wbc<-bl_drive. Instance suffix = variant.")
    a("")
    a(f".param VDD   = {S._fmt(G.VDD_V)}")
    a(f".param VRBL  = {S._fmt(G.VRBL_V)}   $ ASSUMPTION (contract)")
    a(f".param C_RBL = {S._fmt(S.C_RBL_F)}   $ ASSUMPTION (contract; not extracted)")
    a(f".param C_WBL = {S._fmt(G.C_WBL_F)}   $ ASSUMPTION (not extracted)")
    a(f".param C_SN  = {S._fmt(c_sn_f)}   $ extracted-from-netlist (layout/gain_cell_2t.extract.parasitics.json)")
    a("")
    a("* ---- shared static drivers (ideal) ----")
    a("vdd   vdd 0 dc {VDD}")
    a("vrwld rwl_des 0 dc {VDD}")
    a("vwwld wwl_des 0 dc 0")
    a("vpre  prea 0 dc {VRBL}")
    a(f"vref  pref 0 dc {S._fmt(G.VRBL_V - G.DREF_V)}   $ reference = VRBL - {S._fmt(G.DREF_V)} (ASSUMPTION)")
    a(".model swpre sw(vt=0.9 vh=0.1 ron=100 roff=1e12)")
    a(f".model swwbl sw(vt=0.9 vh=0.1 ron={G.R_WBL_SW} roff=1e12)")
    a("")
    ics: list[str] = []
    for i, p in enumerate(insts):
        n = p["name"]
        rb, rf, vn, vp, wb = f"rbl_{n}", f"ref_{n}", f"vn_{n}", f"vp_{n}", f"wbl_{n}"
        a(f"* ---- instance {i}: {n} (variant {p['variant']}; probe dec {p['t_dec_ns']:.4g} ns, release {p['t_release_ns']:.4g} ns, meas {p['t_meas_ns']:.4g} ns) ----")
        pw = node_pwl(p["nodes"])
        a(src_line("vctl", "ctl", n, pw["ctl"]))
        a(src_line("vrs", "rwls", n, pw["rwls"]))
        a(src_line("ven", "en", n, pw["en"]))
        a(src_line("venb", "enb", n, L.complement_pts(pw["en"])))
        a(src_line("vww", "wwl", n, pw["wwl"]))
        a(src_line("vwc", "wbc", n, pw["wbc"]))
        if p["kind"] == "ref":
            a("* reference write: ideal 1.8 V WBL; rbl/ref/latch idle (no read)")
            a(f"vwbr_{n} {wb} 0 dc {{VDD}}")
            ics.append(f"v({wb})={S._fmt(G.VDD_V)}")
        else:
            ics.append(f"v({wb})=0")
            a(f"swb_{n} {rf} {wb} wbc_{n} 0 swwbl")
        a(f"cwbl_{n} {wb} 0 {{C_WBL}}")
        a(f"spa_{n} prea {rb} ctl_{n} 0 swpre")
        a(f"spr_{n} pref {rf} ctl_{n} 0 swpre")
        a(f"crbl_{n} {rb} 0 {{C_RBL}}")
        a(f"cref_{n} {rf} 0 {{C_RBL}}   $ ASSUMPTION: ideal matched dummy load")
        ics.append(f"v({rb})={S._fmt(G.VDD_V)}")
        ics.append(f"v({rf})=0")
        for r in range(G.N_ROWS):
            sn = f"sn_{n}_{r}"
            rwl = f"rwls_{n}" if r == 0 else "rwl_des"
            wwl = f"wwl_{n}" if r == 0 else "wwl_des"
            a(f"XMWR_{n}_{r} {sn} {wwl} {wb} 0 {wr_m} {wr_p}")
            a(f"XMRD_{n}_{r} {rb} {sn} {rwl} 0 {rd_m} {rd_p}")
            a(f"csn_{n}_{r} {sn} 0 {{C_SN}}")
            ics.append(f"v({sn})={S._fmt(p['sn'])}")
        ln, lp, fo, he = S.LATCH_N, S.LATCH_P, S.FOOTER, S.HEADER
        a(f"XMN1_{n} {rb} {rf} {vn} 0 {ln[0]} {S.dev_params(ln[1], ln[2])}")
        a(f"XMN2_{n} {rf} {rb} {vn} 0 {ln[0]} {S.dev_params(ln[1], ln[2])}")
        a(f"XMP1_{n} {rb} {rf} {vp} vdd {lp[0]} {S.dev_params(lp[1], lp[2])}")
        a(f"XMP2_{n} {rf} {rb} {vp} vdd {lp[0]} {S.dev_params(lp[1], lp[2])}")
        a(f"XMNF_{n} {vn} en_{n} 0 0 {fo[0]} {S.dev_params(fo[1], fo[2])}")
        a(f"XMPH_{n} {vp} enb_{n} vdd vdd {he[0]} {S.dev_params(he[1], he[2])}")
        ics.append(f"v({vn})=0.45")
        ics.append(f"v({vp})=1.35")
        a(f"bd_{n} d_{n} 0 v=v({rb})-v({rf})")
        a("")
    a("* initial conditions (tran uic)")
    for k in range(0, len(ics), 6):
        a(".ic " + " ".join(ics[k:k + 6]))
    a("")
    return "\n".join(Ln)


def t_stop_ns(insts) -> float:
    return max(p["t_meas_ns"] for p in insts) + 1.0


def build_request(insts: list[dict]) -> dict:
    meas = []
    for p in insts:
        n = p["name"]
        meas += [
            {"name": f"snend_{n}", "unit": "V", "spice": f".meas tran snend_{n} FIND v(sn_{n}_0) AT={p['t_meas_ns']:.6g}n"},
            {"name": f"snrd_{n}", "unit": "V", "spice": f".meas tran snrd_{n} FIND v(sn_{n}_0) AT={p['t_dec_ns']:.6g}n"},
            {"name": f"dec_{n}", "unit": "V", "spice": f".meas tran dec_{n} FIND v(d_{n}) AT={p['t_dec_ns']:.6g}n"},
            {"name": f"wblp_{n}", "unit": "V", "spice": f".meas tran wblp_{n} FIND v(wbl_{n}) AT={p['t_wbl_probe_ns']:.6g}n"},
            {"name": f"snwf_{n}", "unit": "V", "spice": f".meas tran snwf_{n} FIND v(sn_{n}_0) AT={p['t_wbl_probe_ns']:.6g}n"},
        ]
    return {"netlist": "refresh_replay.spice", "engine": "ngspice", "backend": "batch",
            "models": {"pdk": "sky130A", "lib": "libs.tech/combined/sky130.lib.spice"},
            "corners": {"process": G.PROCESS_CORNERS, "temperature_c": G.TEMPS_C},
            "analysis": {"kind": "tran", "args": f"10p {t_stop_ns(insts):.6g}n 0 50p uic"},
            "measurements": meas, "options": {"timeout_s": 1800, "keep_artifacts": False, "waveforms": False}}


def verify_deck(deck: str, insts: list[dict], golden: dict) -> dict:
    """Parse the generated deck back and compare with the variant traces and the golden RTL trace."""
    import re
    srcs = {}
    for ln in deck.splitlines():
        m = re.match(r"(vctl|vrs|ven|venb|vww|vwc)_(\S+)\s+\S+\s+0\s+(pwl\(.*\))", ln)
        if m:
            srcs[(m.group(1), m.group(2))] = m.group(3)
    node_src = {"ctl": "vctl", "rwls": "vrs", "en": "ven", "wwl": "vww", "wbc": "vwc"}
    res = {}
    for p in insts:
        name = p["name"]
        findings, got_trace_edges, init = [], [], {}
        for sig, pm in L.PIN_MAP.items():
            node = pm["node"]
            exp_init, exp_edges, inv = p["nodes"][node]
            try:
                g_init, g_edges = L.pwl_to_edges(srcs[(node_src[node], name)], inv)
            except (KeyError, ValueError) as ex:
                findings.append(dict(kind="deck_unparsable", node=node, detail=str(ex)))
                continue
            exp_init, exp_edges = L.absorb_t0(exp_init, exp_edges)
            expt = dict(initial={sig: exp_init}, edges=[L.edge(t, sig, v) for t, v in exp_edges])
            got = dict(initial={sig: g_init}, edges=[L.edge(t, sig, v) for t, v in g_edges])
            for f in L.check_trace_consistency(expt, got, [sig]):
                findings.append(dict(f, node=node, check="deck_vs_variant_trace"))
        # complement of the enable
        try:
            ei, ee = L.pwl_to_edges(srcs[("ven", name)], False)
            ci, ce = L.pwl_to_edges(srcs[("venb", name)], True)
            if ei != ci or ee != ce:
                findings.append(dict(kind="enb_not_complement", node="enb"))
        except (KeyError, ValueError) as ex:
            findings.append(dict(kind="deck_unparsable", node="enb", detail=str(ex)))
        # trace vs golden RTL (strobes only); baseline is compared against itself (no RTL golden)
        if p["variant"] in ("baseline_analog", "reference_write"):
            tv = []
        else:
            tv = L.check_trace_consistency(golden, p["trace"])
        res[name] = dict(variant=p["variant"], deck_matches_trace=not findings, deck_findings=findings,
                         trace_matches_golden_rtl=not tv, trace_findings=tv)
    return res


def git(*a) -> str:
    return subprocess.run(["git", "-C", str(REPO), *a], capture_output=True, text=True).stdout.strip()


def pins(golden: dict) -> dict:
    files = ["digital/phase-control/phase_seq.v", "digital/phase-control/tb_trace_export.v",
             "sim/refresh-replay/replay_lib.py", "sim/refresh-replay/gen_refresh_replay.py",
             "sim/refresh-replay/export_rtl_trace.py", "sim/refresh-op/gen_refresh_op.py",
             "sim/sense-stage/gen_sense_stage.py", "design/gain_cell_2t.spice",
             "layout/gain_cell_2t.extract.parasitics.json"]
    try:
        klt = subprocess.run(["klt", "--version"], capture_output=True, text=True).stdout.strip()
    except OSError:
        klt = "unknown"
    import _evidence_common as EC
    return dict(git_head=git("rev-parse", "HEAD"), source_tree_dirty=bool(git("status", "--porcelain", "--", "sim", "digital")),
                source_sha256={f: sha256(REPO / f) for f in files if (REPO / f).exists()},
                rtl_trace_pins=golden.get("pins"), klt_client=klt, pdk_variant=EC.DEFAULT_PDK_VARIANT,
                pdk_open_pdks_commit=EC.PDK_OPEN_PDKS_COMMIT, pdk_pin_doc="docs/pdk-pin.md")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("trace", type=Path, help="golden RTL trace JSON (export_rtl_trace.py)")
    ap.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    ap.add_argument("--results-dir", type=Path, default=HERE / "results")
    a = ap.parse_args(argv)
    run_dir = a.results_dir / a.run_id
    if run_dir.exists():
        print(f"refusing to reuse existing run directory {run_dir}", file=sys.stderr)
        return 2
    golden = json.loads(a.trace.read_text())
    insts = build_instances(golden)
    c_sn_ff, prov = S.load_extracted_c_sn(S.EXTRACT_JSON, "sn")
    deck = build_netlist(c_sn_ff * 1e-15, insts)
    req = build_request(insts)
    check = verify_deck(deck, insts, golden)
    run_dir.mkdir(parents=True)
    (run_dir / "rtl_trace.json").write_text(json.dumps(golden, indent=1) + "\n")
    (run_dir / "refresh_replay.spice").write_text(deck)
    (run_dir / "request.json").write_text(json.dumps(req, indent=1) + "\n")
    wf = {}
    for v in VARIANTS + ["reference_write"]:
        p = next(i for i in insts if i["variant"] == v)
        wf[v] = {"pin_map": {s: L.PIN_MAP[s] for s in STROBES} | {"latch_en_held": dict(node="en", adapter="set at sense_en rise, cleared at busy fall (explicit adapter)")},
                 "adapter_applied": p["adapter"],
                 "pwl_points_ns_level": {n: [[t, lv] for t, lv in pts] for n, pts in node_pwl(p["nodes"]).items()},
                 "strobe_edges": {n: [[t, val] for t, val in ed] for n, (_, ed, _) in p["nodes"].items()}}
    (run_dir / "waveforms.json").write_text(json.dumps(wf, indent=1) + "\n")
    (run_dir / "consistency_check.json").write_text(json.dumps(check, indent=1) + "\n")
    man = dict(
        run_id=a.run_id, status="PROPOSED_OPERATING_RANGE_NOT_RATIFIED", issue=128,
        deck_sha256=hashlib.sha256(deck.encode()).hexdigest(), request_sha256=hashlib.sha256((json.dumps(req, indent=1) + "\n").encode()).hexdigest(),
        variants=VARIANTS, negative_controls=NEGATIVE, patterns=[dict(kind=k, sn_v=v) for k, v in PATTERNS],
        instances=[dict(name=p["name"], kind=p["kind"], sn_v=p["sn"], variant=p["variant"],
                        t_dec_ns=p["t_dec_ns"], t_wwl_rise_ns=p["t_wwl_rise_ns"], t_wwl_fall_ns=p["t_wwl_fall_ns"],
                        t_release_ns=p["t_release_ns"], t_meas_ns=p["t_meas_ns"],
                        digital=L.digital_duration(p["trace"]) if p["variant"] not in ("baseline_analog", "reference_write") else None)
                   for p in insts],
        assumptions=dict(
            cycle_ns=1.0, t_edge_ns=L.T_EDGE_NS, vdd_v=L.VDD_V, launch_adapter_latency_ns=0.0,
            latch_hold_adapter="enable set at sense_en rise, cleared at busy fall; no delay; RWL is NOT held (RTL timing)",
            t_meas_after_release_ns=T_MEAS_NS, decision_probe_lead_ns=SN_DEC_LEAD_NS,
            baseline=dict(sense_ns=BASE_SENSE_S * 1e9, wwl_ns=BASE_WB_S * 1e9, from_="sim/refresh-op generator constants"),
            c_rbl_f=S.C_RBL_F, c_wbl_f=G.C_WBL_F, c_sn_ff=c_sn_ff, c_sn_provenance=str(prov),
            budget_cycles_provisional=34, shared_circuit="sim/refresh-op circuit body (ideal drivers; column driver is #114/#117)"),
        pins=pins(golden))
    (run_dir / "manifest.json").write_text(json.dumps(man, indent=1) + "\n")
    bad = [n for n, c in check.items() if not c["deck_matches_trace"]]
    print(f"wrote {run_dir} ({len(insts)} instances); deck-vs-trace mismatches: {bad or 'none'}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
