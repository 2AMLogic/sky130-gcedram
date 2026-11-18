#!/usr/bin/env python3
"""Generate the repeated closed-loop refresh decks and `klt sim` requests (issue #147).

Stdlib only. Writes, next to this file, one flat circuit body + one request per VARIANT
(``closed_loop_<variant>.spice`` / ``request_<variant>.json``; 5 global corners x {27, 125} C = the
restricted range of ``spec/operating-range-decision-PROPOSED.md``, one ``tran`` per corner).

One instance = a 4-row column (the #94 column: extracted 4-row ``C_RBL``, array-minimum ``C_SN``, drawn
AD/AS/PD/PS, corrected latch ``design/sense_latch.spice``, ideal drivers, 10 fF ``C_WBL`` as sim/refresh-op).
All four rows are WRITTEN ONCE through ``M_WR`` (each cell starting at the opposite of its data), then the
same continuous transient carries every storage node through ``cycles`` refresh cycles. Row k is refreshed at
``S(n,k) = wl_fall_k + n*dwell`` (select-edge to select-edge interval = dwell; the first age is exactly
dwell). Every refresh is the closed loop of sim/refresh-op: precharge -> select -> latch enable -> the latch
COMPLEMENT node drives WBL -> WWL pulse. There is no ``.ic`` reset and no ideal expected-data source after the
initial write: the actual latch decision (right or wrong) is what gets written back and carried forward.

Waveforms (controls are the existing evidence, reused unchanged):

* ``ana``   the sim/refresh-op analog baseline sequence (SENSE 10 ns / WWL 20 ns; RWL and latch held through
            the write-back) -- the MAIN case.
* ``rtl``   the UNCHANGED committed phase-sequencer REFRESH strobes + the explicit latch-hold adapter
            (sim/refresh-replay ``rtl_hold``); single-op replay restores 0/10 corners, so it is a control.
* ``late``  EXPERIMENTAL, UNAPPROVED: ``rtl`` with the RWL release moved after the WWL fall (sim/refresh-replay
            ``rwl_late_hold``). Not an overlap-rule change; the contractual RTL is unchanged.
* ``nowb``  NEGATIVE CONTROL: the ``ana`` waveform with the write-back WWL pulses deleted.

PROPOSED, NOT RATIFIED: scope is the proposed operating range. The ratified 5.03 us bound is only read.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
for sub in ("sim", "sim/sense-stage", "sim/aged-read", "sim/refresh-op", "sim/refresh-replay"):
    sys.path.insert(0, str(REPO / sub))
from _evidence_common import VDD_V, fmt_g6, parse_cards  # noqa: E402
from klt_request import build_request as klt_request  # noqa: E402
import gen_sense_stage as S  # noqa: E402
import gen_aged_read as A  # noqa: E402
import gen_refresh_op as R  # noqa: E402
import gen_refresh_replay as P  # noqa: E402
import replay_lib as L  # noqa: E402

TRACE_PATH = REPO / "sim" / "refresh-replay" / "results" / "20261115T120746Z" / "rtl_trace.json"
LATCH_SPICE = REPO / "design" / "sense_latch.spice"

PROCESS_CORNERS = S.PROCESS_CORNERS
TEMPS_C = S.TEMPS_C
N_ROWS = 4
VRBL_V = A.VRBL_V
DREF_V = A.DREF_V
REFRESH_BOUND_S = A.REFRESH_BOUND_S          # ratified 5.03 us, read only
C_WBL_F = R.C_WBL_F                          # ASSUMPTION (not extracted), as sim/refresh-op
R_SW = R.R_WBL_SW
TEDGE_NS = 0.1
W0_NS = 1.0                                  # first initial-write slot
SLOT_NS = 40.0                               # slot / refresh-op pitch (> every op length, so ops never overlap)
WPULSE_NS = 20.0
BL_LEAD_NS = 0.5
BL_LAG_NS = 2.0
T_MEAS_NS = R.T_MEAS_S * 1e9                 # SN is read this long after the last release edge (refresh-op convention)
WR_PROBE_NS = 0.5                            # initial-write level probe after the WWL fall (as #94)
PRE_LEAD_NS = 0.2                            # pre-read probe before the select edge (as #94)
DEC_LEAD_NS = 0.1                            # decision probe before the write-back WWL rise (as sim/refresh-op)
TMAX_NS = 2.0
OPTIONS = A.OPTIONS

PATTERNS_ALL = ["1111", "0000", "1000", "0111", "1010", "0101", "1101", "0010"]   # row0..row3 data; STARTING POINT
PATTERNS_CTRL = ["1111", "0000", "1010", "0101"]
PATTERNS_NOWB = ["1111", "1010"]
PATTERNS_EXCESS = ["1111", "1010", "0000"]

# Waveform keys -> (source variant in sim/refresh-replay, write-back present)
WAVEFORMS = {"ana": ("baseline_analog", True), "rtl": ("rtl_hold", True),
             "late": ("rwl_late_hold", True), "nowb": ("baseline_analog", False)}

# Declared horizon: 10 refresh cycles per row. Rationale (README): enough for a per-cycle loss/drift trend to
# separate from a single-cycle offset and for a wrong write-back to feed >= 9 later reads, still a FINITE horizon.
HORIZON_CYCLES = 10
VARIANTS = [
    dict(name="d2500", dwell_ns=2500.0, cycles=HORIZON_CYCLES, role="shorter dwell than the ratified bound",
         groups=[("ana", "main", PATTERNS_ALL), ("rtl", "control_rtl_unchanged", PATTERNS_CTRL),
                 ("late", "experimental_unapproved", PATTERNS_CTRL), ("nowb", "control_missing_writeback", PATTERNS_NOWB)]),
    dict(name="d5030", dwell_ns=5030.0, cycles=HORIZON_CYCLES, role="the ratified refresh-interval bound (5.03 us)",
         groups=[("ana", "main", PATTERNS_ALL), ("rtl", "control_rtl_unchanged", PATTERNS_CTRL),
                 ("late", "experimental_unapproved", PATTERNS_CTRL), ("nowb", "control_missing_writeback", PATTERNS_NOWB)]),
    dict(name="d8000", dwell_ns=8000.0, cycles=HORIZON_CYCLES, role="longer dwell than the ratified bound (1.6x)",
         groups=[("ana", "main", PATTERNS_ALL), ("rtl", "control_rtl_unchanged", PATTERNS_CTRL),
                 ("late", "experimental_unapproved", PATTERNS_CTRL), ("nowb", "control_missing_writeback", PATTERNS_NOWB)]),
    dict(name="d60000", dwell_ns=60000.0, cycles=2, role="EXCESSIVE-DWELL control (12x the ratified bound)",
         groups=[("ana", "control_excessive_dwell", PATTERNS_EXCESS)]),
]


def pwl_text(pts: list[tuple[float, str]]) -> str:
    """PWL source text; times in seconds with 12 significant digits (replay_lib's 5 digits cannot resolve 0.1 ns edges at tens of us)."""
    return "pwl(" + " ".join(f"{t * 1e-9:.12g} {lv}" for t, lv in pts) + ")"


def variant(name: str) -> dict:
    return next(v for v in VARIANTS if v["name"] == name)


def trace_waves() -> dict:
    """waveform key -> dict(nodes=node->(init, edges, invert) for ONE op with t=0 at the op start, write_back)."""
    golden = json.loads(TRACE_PATH.read_text())
    vt = P.variant_traces(golden)
    out = {}
    for key, (src, wb) in WAVEFORMS.items():
        v = vt[src]
        out[key] = dict(source_variant=src, write_back=wb,
                        nodes=P.node_waveforms(v["trace"], v["adapter"], v.get("latch_release")))
    return out


def op_shape(nodes: dict) -> dict:
    """Op-relative times (ns): select edge, write-back WWL rise/fall, last release edge, op end."""
    sel = min(t for t, v in nodes["rwls"][1] if v == 1)
    wwl_rise = min(t for t, v in nodes["wwl"][1] if v == 1)
    wwl_fall = max(t for t, v in nodes["wwl"][1] if v == 0)
    last = max(t for _, ed, _ in nodes.values() for t, _ in ed)
    return dict(sel=sel, wwl_rise=wwl_rise, wwl_fall=wwl_fall, last=last, end=last + 1.0)


def wl_fall_ns(k: int) -> float:
    """Fall of row k's initial write pulse (end of the 0.1 ns ramp)."""
    return W0_NS + k * SLOT_NS + WPULSE_NS + TEDGE_NS


def select_ns(v: dict, k: int, n: int) -> float:
    """Select edge of row k's n-th refresh (n = 1..cycles): interval from the initial write = dwell."""
    return wl_fall_ns(k) + n * v["dwell_ns"]


def ops(v: dict) -> list[tuple[int, int, float]]:
    return sorted(((n, k, select_ns(v, k, n)) for n in range(1, v["cycles"] + 1) for k in range(N_ROWS)), key=lambda x: x[2])


def instances(v: dict) -> list[dict]:
    pts = []
    for wf, kind, pats in v["groups"]:
        for bits in pats:
            pts.append(dict(wf=wf, kind=kind, bits=bits, name=f"{wf}_{bits}"))
    for i, p in enumerate(pts):
        p["idx"] = i
        p["data"] = [int(c) for c in p["bits"]]
    return pts


def probe_times(v: dict, wf: str, k: int, n: int, waves: dict) -> dict:
    sh = op_shape(waves[wf]["nodes"])
    s = select_ns(v, k, n)
    o = s - sh["sel"]
    return dict(pre=s - PRE_LEAD_NS, dec=o + sh["wwl_rise"] - DEC_LEAD_NS, post=o + sh["last"] + T_MEAS_NS)


def t_stop_ns(v: dict, waves: dict) -> float:
    return max(probe_times(v, wf, k, n, waves)["post"] for wf in {g[0] for g in v["groups"]}
               for k in range(N_ROWS) for n in (v["cycles"],)) + 1.0


def _composite(v: dict, wf: str, waves: dict) -> dict:
    """Absolute-time PWL point lists (ns) for the shared control sources of one waveform key."""
    w = waves[wf]
    nodes = w["nodes"]
    sh = op_shape(nodes)
    idle = {"ctl": 1, "rwls": 0, "en": 0, "wwl": 0, "wbc": 0}
    edges: dict[str, list[tuple[float, int]]] = {f"{n}{k}": [] for n in ("rwls", "wwl") for k in range(N_ROWS)}
    for n in ("ctl", "en", "wbc"):
        edges[n] = []
    for k in range(N_ROWS):   # initial write pulses (all waveforms)
        tu = W0_NS + k * SLOT_NS
        edges[f"wwl{k}"] += [(tu, 1), (tu + WPULSE_NS, 0)]
    for n, k, s in ops(v):
        o = s - sh["sel"]
        for node, (init, ed, inv) in nodes.items():
            if node == "wwl" and not w["write_back"]:
                continue
            eff = init
            for t, val in ed:
                if t <= 1e-6:
                    eff = val          # t = 0 edges set the op's starting level
            assert eff == idle[node], (wf, node, eff)
            for t, val in ed:
                if t <= 1e-6:
                    continue
                key = node if node in ("ctl", "en", "wbc") else f"{node}{k}"
                edges[key].append((round(o + t, 6), val))
        edges["ctl"].append((round(o + sh["end"], 6), 1))   # precharge back on after the op (the trace never closes it)
    pts = {}
    for key, ed in edges.items():
        node = key.rstrip("0123")
        inv = nodes[node][2]
        pts[key] = L.edges_to_pwl(idle[node], sorted(ed), inv)
    return pts


def _bl_init(bits: str) -> list[tuple[float, str]]:
    pts = [(0.0, "0")]
    for k, ch in enumerate(bits):
        if ch == "1":
            t0 = W0_NS + k * SLOT_NS
            pts += [(t0 - BL_LEAD_NS, "0"), (t0 - BL_LEAD_NS + TEDGE_NS, "{VDD}"),
                    (t0 + WPULSE_NS + TEDGE_NS + BL_LAG_NS, "{VDD}"), (t0 + WPULSE_NS + 2 * TEDGE_NS + BL_LAG_NS, "0")]
    return pts


def build_netlist(v: dict, waves: dict | None = None) -> str:
    waves = waves or trace_waves()
    (wr_m, wr_p), (rd_m, rd_p) = S.design_cell_cards()
    wr_p, rd_p = S.layout_card(wr_p), S.layout_card(rd_p)
    latch = parse_cards(LATCH_SPICE)
    c_rbl_f = S.extracted_c_rbl_ff() * 1e-15
    c_sn_f = A.array_c_sn_ff() * 1e-15
    pts = instances(v)
    L_: list[str] = []
    a = L_.append
    a(f"* closed_loop_{v['name']}.spice -- repeated closed-loop refresh, dwell {fmt_g6(v['dwell_ns'])} ns x {v['cycles']} cycles ({v['role']}), issue #147")
    a("* GENERATED by gen_closed_loop.py; do not edit by hand.")
    a("*")
    a("* PROPOSED/UNRATIFIED SCOPE: 27 C and 125 C, tt/ss/ff/sf/fs, VDD 1.8 V (spec/operating-range-decision-PROPOSED.md).")
    a("* One continuous transient per instance: 4 rows written ONCE through M_WR (each cell starting at the opposite of its")
    a("* data), then closed-loop refresh of every row each dwell: precharge -> select -> latch enable -> latch COMPLEMENT")
    a("* node drives WBL -> WWL pulse. No .ic reset and no ideal expected-data source after the initial write; the actual")
    a("* latch decision is written back and carried into the next cycle. Instance name <waveform>_<row0..row3 data>.")
    a("* Waveforms: ana = sim/refresh-op analog baseline; rtl = UNCHANGED phase-sequencer strobes + latch-hold adapter;")
    a("* late = EXPERIMENTAL UNAPPROVED rtl with RWL released after WWL fall; nowb = ana with write-back WWL pulses deleted.")
    a("*")
    a("* ASSUMPTIONS (labelled, none is a spec value): ideal drivers and 100 ohm switches, C_WBL = 10 fF (not extracted),")
    a("* ideal matched dummy reference load, VREF = VRBL - 100 mV, 4-row column, C_RBL = extracted 4-row worst net,")
    a("* C_SN = extracted array MINIMUM wiring C, global corners only, NO mismatch, no device-level column/row driver.")
    a("")
    a(f".options {OPTIONS}")
    a(f".param VDD   = {fmt_g6(VDD_V)}")
    a(f".param VRBL  = {fmt_g6(VRBL_V)}")
    a(f".param C_RBL = {fmt_g6(c_rbl_f)}   $ extracted_4row_worst_total_ff, layout/gain_cell_2t_array.parasitics.summary.json")
    a(f".param C_WBL = {fmt_g6(C_WBL_F)}   $ ASSUMPTION (not extracted)")
    a(f".param C_SN  = {fmt_g6(c_sn_f)}   $ comparison.c_sn.array_min_total_ff (wiring only; array-context, issue #89)")
    a("vdd   vdd 0 dc {VDD}")
    a("vprea prea 0 dc {VRBL}")
    a(f"vpref pref 0 dc {fmt_g6(VRBL_V - DREF_V)}")
    a("vrwld rwl_des 0 dc {VDD}")
    a(".model swpre sw(vt=0.9 vh=0.1 ron=100 roff=1e12)")
    a(f".model swwbl sw(vt=0.9 vh=0.1 ron={R_SW} roff=1e12)")
    a("")
    for wf in dict.fromkeys(g[0] for g in v["groups"]):
        c = _composite(v, wf, waves)
        a(f"* ---- shared control sources, waveform {wf} (source variant {waves[wf]['source_variant']}, write-back {waves[wf]['write_back']}) ----")
        a(f"vctl_{wf} ctl_{wf} 0 {pwl_text(c['ctl'])}")
        a(f"ven_{wf} en_{wf} 0 {pwl_text(c['en'])}")
        a(f"venb_{wf} enb_{wf} 0 {pwl_text(L.complement_pts(c['en']))}")
        a(f"vwbc_{wf} wbc_{wf} 0 {pwl_text(c['wbc'])}")
        a(f"vbpk_{wf} bpk_{wf} 0 {pwl_text(L.complement_pts(c['wbc']))}   $ ideal initial-write/park driver connected except during write-back")
        for k in range(N_ROWS):
            a(f"vrws{k}_{wf} rwls{k}_{wf} 0 {pwl_text(c[f'rwls{k}'])}")
            a(f"vwl{k}_{wf} wl{k}_{wf} 0 {pwl_text(c[f'wwl{k}'])}")
    for bits in sorted({p["bits"] for p in pts}):
        a(f"vbld{bits} bld{bits} 0 {pwl_text(_bl_init(bits))}")
    a("")
    ics: list[str] = []
    for p in pts:
        n, wf, bits = p["name"], p["wf"], p["bits"]
        rb, rf, vn, vp, wb = f"rbl_{n}", f"ref_{n}", f"vn_{n}", f"vp_{n}", f"wbl_{n}"
        a(f"* ---- instance {p['idx']}: {n} ({p['kind']}) ----")
        a(f"sbi_{n} bld{bits} {wb} bpk_{wf} 0 swwbl")
        a(f"swb_{n} {rf} {wb} wbc_{wf} 0 swwbl")
        a(f"cwbl_{n} {wb} 0 {{C_WBL}}")
        ics.append(f"v({wb})=0")
        a(f"spa_{n} prea {rb} ctl_{wf} 0 swpre")
        a(f"spr_{n} pref {rf} ctl_{wf} 0 swpre")
        a(f"crbl_{n} {rb} 0 {{C_RBL}}")
        a(f"cref_{n} {rf} 0 {{C_RBL}}   $ ASSUMPTION: ideal matched dummy load")
        ics.append(f"v({rb})={fmt_g6(VRBL_V)}")
        ics.append(f"v({rf})={fmt_g6(VRBL_V - DREF_V)}")
        for r in range(N_ROWS):
            sn = f"sn_{n}_{r}"
            a(f"XMWR_{n}_{r} {sn} wl{r}_{wf} {wb} 0 {wr_m} {wr_p}")
            a(f"XMRD_{n}_{r} {rb} {sn} rwls{r}_{wf} 0 {rd_m} {rd_p}")
            a(f"csn_{n}_{r} {sn} 0 {{C_SN}}")
            ics.append(f"v({sn})={fmt_g6(0.0 if p['data'][r] else VDD_V)}")   # opposite of the data to be written
        lmap = {"rbl": rb, "ref": rf, "vn": vn, "vp": vp, "en": f"en_{wf}", "enb": f"enb_{wf}",
                "vdd": "vdd", "GND": "0", "0": "0"}
        for dev, (nets, model, params) in latch.items():
            a(f"X{dev}_{n} {' '.join(lmap[x] for x in nets)} {model} {params}")
        ics.append(f"v({vn})=0.45")
        ics.append(f"v({vp})=1.35")
        a(f"bd_{n} d_{n} 0 v=v({rb})-v({rf})")
        a("")
    a("* initial conditions (tran uic): precharged rails, cells at the opposite of their data, latch tail nodes.")
    a("* They apply ONLY at t = 0 (before the initial write); nothing is reset between refresh cycles.")
    for k in range(0, len(ics), 6):
        a(".ic " + " ".join(ics[k:k + 6]))
    a("")
    return "\n".join(L_)


def build_request(v: dict, waves: dict | None = None) -> dict:
    waves = waves or trace_waves()
    stop = fmt_g6(t_stop_ns(v, waves))
    meas = []
    for p in instances(v):
        n = p["name"]
        for k in range(N_ROWS):
            t = fmt_g6(wl_fall_ns(k) + WR_PROBE_NS)
            meas.append({"name": f"wr_{n}_r{k}", "unit": "V", "spice": f".meas tran wr_{n}_r{k} FIND v(sn_{n}_{k}) AT={t}n"})
            for c in range(1, v["cycles"] + 1):
                pt = probe_times(v, p["wf"], k, c, waves)
                meas += [
                    {"name": f"pre_{n}_r{k}_c{c}", "unit": "V", "spice": f".meas tran pre_{n}_r{k}_c{c} FIND v(sn_{n}_{k}) AT={fmt_g6(pt['pre'])}n"},
                    {"name": f"dec_{n}_r{k}_c{c}", "unit": "V", "spice": f".meas tran dec_{n}_r{k}_c{c} FIND v(d_{n}) AT={fmt_g6(pt['dec'])}n"},
                    {"name": f"post_{n}_r{k}_c{c}", "unit": "V", "spice": f".meas tran post_{n}_r{k}_c{c} FIND v(sn_{n}_{k}) AT={fmt_g6(pt['post'])}n"},
                ]
    return klt_request(f"closed_loop_{v['name']}.spice", {"process": PROCESS_CORNERS, "temperature_c": TEMPS_C},
                       f"100p {stop}n 0 {fmt_g6(TMAX_NS)}n uic", meas, 3300)


def paths(v: dict) -> tuple[Path, Path]:
    return HERE / f"closed_loop_{v['name']}.spice", HERE / f"request_{v['name']}.json"


def render(v: dict, waves: dict | None = None) -> tuple[str, str]:
    waves = waves or trace_waves()
    return build_netlist(v, waves), json.dumps(build_request(v, waves), indent=1) + "\n"


def main() -> int:
    waves = trace_waves()
    for v in VARIANTS:
        net, req = render(v, waves)
        np_, rp = paths(v)
        np_.write_text(net)
        rp.write_text(req)
        print(f"wrote {np_.name} ({len(instances(v))} instances) and {rp.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
