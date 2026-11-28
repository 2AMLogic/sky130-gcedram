#!/usr/bin/env python3
"""Generate the physical write -> hold -> loaded-read deck and `klt sim` request (issue #94).

Stdlib only. Writes, next to this file: ``aged_read.spice`` (flat circuit body for
``klt sim``; every case is an independent parallel instance) and ``request.json``
(5 global corners x {27, 125} C = the restricted range of
``spec/operating-range-decision-PROPOSED.md``, one ``tran`` per corner).

Every case is: 4-row column, all four rows WRITTEN through their M_WR access device
(wordline pulse, ideal bitline driver; each cell starts at the OPPOSITE of its data so
the write must flip it), HELD with the shipped device models evolving the storage node
(no imposed SN level), then precharge released, selected ``rwl`` falls, the corrected
latch (``design/sense_latch.spice``) enables 10 ns later. The selected row is written
LAST so its hold age is exactly the case age; the other rows are older by 25-75 ns.

PROPOSED, NOT RATIFIED: scope is the proposed operating range. Nothing is a spec value.
"""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "sim"))
sys.path.insert(0, str(REPO / "sim" / "sense-stage"))
from _evidence_common import VDD_V, fmt_g6, parse_cards  # noqa: E402
from klt_request import build_request as klt_request  # noqa: E402
import gen_sense_stage as S  # noqa: E402

NETLIST_PATH = HERE / "aged_read.spice"
REQUEST_PATH = HERE / "request.json"
SUMMARY = REPO / "layout" / "gain_cell_2t_array.parasitics.summary.json"
LATCH_SPICE = REPO / "design" / "sense_latch.spice"

PROCESS_CORNERS = S.PROCESS_CORNERS
TEMPS_C = S.TEMPS_C
N_ROWS = 4
VRBL_V = 0.9
DREF_V = 0.10                  # ASSUMPTION: reference = VRBL - 100 mV (as the sense-stage stage-only sweep)
TEDGE_S = 100e-12
T_W0_S = 1e-9                  # first write slot start
T_SLOT_S = 25e-9               # slot pitch (loaded-column convention)
T_WPULSE_S = 20e-9             # write wordline pulse width (existing write drive, no boost)
T_BL_LEAD_S = 0.5e-9             # bitline set this long before the wordline rises
T_BL_LAG_S = 2e-9              # bitline returns to 0 this long after wordline is low
T_PRE_GAP_S = 2e-9             # precharge released this long before the select edge
T_SENSE_S = 10e-9              # latch enable this long after the select edge (contract instant)
T_TAIL_S = 20e-9               # observation window after enable
WEAK_WL_V = 0.55               # NEGATIVE CONTROL: write wordline drive below the access-device Vt
TMAX_S = 2e-9
OPTIONS = "method=trap gmin=1e-15 abstol=1e-15 chgtol=1e-18"
# Existing ratified refresh-interval upper bound (spec/retention-refresh-budget.md section 7);
# used ONLY to classify points, never altered.
REFRESH_BOUND_S = 5.03e-6
# Hold ages (ns) from the selected row's wordline fall to the select edge. 5 ns is the
# zero-hold control (shortest age the write-to-read sequencing allows). Points on both sides of the bound.
AGES_NS = [5, 500, 1000, 2000, 3000, 4000, 5030, 6500, 8000, 12000]
# Neighbour patterns of the three non-selected rows (in ascending row order); S = same
# value as the selected cell, O = opposite. A STARTING POINT, not a proven worst-case enumeration.
NEIGHBOUR_PATTERNS = ["sss", "ooo", "sos", "oso"]
VALUES = [1, 0]


def t_wl_off_s() -> float:
    return T_W0_S + (N_ROWS - 1) * T_SLOT_S + TEDGE_S + T_WPULSE_S + TEDGE_S


def t_read_s(age_ns: int) -> float:
    return t_wl_off_s() + age_ns * 1e-9


def t_en_s(age_ns: int) -> float:
    return t_read_s(age_ns) + T_SENSE_S


def t_stop_s() -> float:
    return t_en_s(max(AGES_NS)) + T_TAIL_S


def array_c_sn_ff() -> float:
    return float(json.loads(SUMMARY.read_text())["comparison"]["c_sn"]["array_min_total_ff"])


def instances() -> list[dict]:
    pts = []
    for age, row, val, pat in itertools.product(AGES_NS, range(N_ROWS), VALUES, NEIGHBOUR_PATTERNS):
        pts.append(dict(kind="main", age_ns=age, row=row, value=val, pattern=pat, weak=False))
    for val in (1,):  # NEGATIVE CONTROL: inadequate write of a '1' (wordline at WEAK_WL_V), at zero hold and mid hold
        for age in (5, 2000):
            pts.append(dict(kind="control_weak_write", age_ns=age, row=0, value=val, pattern="sss", weak=True))
    for i, p in enumerate(pts):
        p["idx"] = i
        pre = "c" if p["weak"] else "m"
        p["name"] = f"{pre}_a{p['age_ns']:05d}_r{p['row']}_v{p['value']}_{p['pattern']}"
        nb = [r for r in range(N_ROWS) if r != p["row"]]
        p["data"] = {p["row"]: p["value"]}
        for r, ch in zip(nb, p["pattern"]):
            p["data"][r] = p["value"] if ch == "s" else 1 - p["value"]
        # write order: neighbours ascending, selected LAST
        p["order"] = nb + [p["row"]]
        p["slot_bits"] = "".join(str(p["data"][r]) for r in p["order"])
    return pts


def build_netlist(variant_label: str = "") -> str:
    (wr_m, wr_p), (rd_m, rd_p) = S.design_cell_cards()
    wr_p, rd_p = S.layout_card(wr_p), S.layout_card(rd_p)   # drawn diffusion (issue #89 reconciliation)
    c_rbl_f = S.extracted_c_rbl_ff() * 1e-15
    c_sn_f = array_c_sn_ff() * 1e-15
    latch = parse_cards(LATCH_SPICE)
    pts = instances()
    e, a_ = TEDGE_S, None
    L: list[str] = []
    a = L.append
    a("* aged_read.spice -- physical write -> hold -> loaded-read of the 2T gain cell (issue #94, Epic #24 item 2).")
    a("* GENERATED by gen_aged_read.py; do not edit by hand.")
    a("*")
    a("* PROPOSED/UNRATIFIED SCOPE: 27 C and 125 C, tt/ss/ff/sf/fs, VDD 1.8 V only")
    a("* (spec/operating-range-decision-PROPOSED.md). CIRCUIT BODY for `klt sim` (flat, self-contained).")
    a("* Every case is an independent parallel instance: 4 cells written through M_WR (selected row written last,")
    a("* each cell starting at the OPPOSITE of its data), held with the device models evolving SN, then read:")
    a("* precharge released, selected rwl falls, corrected latch (design/sense_latch.spice) enabled 10 ns later.")
    a("* Case name m_a<age ns>_r<selected row>_v<value>_<neighbour pattern s=same/o=opposite, ascending rows>;")
    a("* c_* are NEGATIVE CONTROLS (inadequate write: wordline high level 0.55 V < Vt).")
    a("*")
    a("* ASSUMPTIONS (labelled, none is a spec value): ideal write/wordline/bitline drivers, ideal 100 ohm precharge")
    a("* switch, ideal matched dummy reference load, VREF = VRBL - 100 mV, sense instant, 4-row column,")
    a("* C_RBL = extracted 4-row worst net (post-#244), C_SN = extracted array MINIMUM wiring C (junction/gate C")
    a("* are in the device models, drawn AD/AS/PD/PS used), global corners only, NO mismatch.")
    a("")
    a(f".options {OPTIONS}")
    a(f".param VDD     = {fmt_g6(VDD_V)}")
    a(f".param VRBL    = {fmt_g6(VRBL_V)}")
    a(f".param TEDGE   = {fmt_g6(TEDGE_S)}")
    a(f".param C_RBL   = {fmt_g6(c_rbl_f)}   $ extracted_4row_worst_total_ff, layout/gain_cell_2t_array.parasitics.summary.json")
    a(f".param C_SN    = {fmt_g6(c_sn_f)}   $ comparison.c_sn.array_min_total_ff (wiring only; array-context, issue #89)")
    a("")
    a("vdd   vdd 0 dc {VDD}")
    a("vprea prea 0 dc {VRBL}")
    a(f"vpref pref 0 dc {fmt_g6(VRBL_V - DREF_V)}")
    a("vrwld rwl_des 0 dc {VDD}")
    a(".model swpre sw(vt=0.9 vh=0.1 ron=100 roff=1e12)")
    # write wordline slot sources (shared)
    def wlpulse(t0: float, hi: str) -> str:
        return f"pwl(0 0 {fmt_g6(t0)} 0 {fmt_g6(t0 + e)} {hi} {fmt_g6(t0 + e + T_WPULSE_S)} {hi} {fmt_g6(t0 + 2 * e + T_WPULSE_S)} 0)"
    for k in range(N_ROWS):
        a(f"vwls{k} wls{k} 0 {wlpulse(T_W0_S + k * T_SLOT_S, '{VDD}')}")
    a(f"vwlsw wlsw 0 {wlpulse(T_W0_S + (N_ROWS - 1) * T_SLOT_S, fmt_g6(WEAK_WL_V))}   $ negative control: weak write, last slot")
    for bits in sorted({p['slot_bits'] for p in pts}):
        v = ["0 0"]
        for k, ch in enumerate(bits):
            if ch == "1":
                t0 = T_W0_S + k * T_SLOT_S
                v.append(f"{fmt_g6(t0 - T_BL_LEAD_S)} 0 {fmt_g6(t0 - T_BL_LEAD_S + e)} {{VDD}} "
                         f"{fmt_g6(t0 + e + T_WPULSE_S + e + T_BL_LAG_S)} {{VDD}} {fmt_g6(t0 + e + T_WPULSE_S + e + T_BL_LAG_S + e)} 0")
        a(f"vbl{bits} bld{bits} 0 pwl({' '.join(v)})")
    for age in AGES_NS:
        tr, te = t_read_s(age), t_en_s(age)
        a(f"vctl{age} ctl{age} 0 pwl(0 {{VDD}} {fmt_g6(tr - T_PRE_GAP_S)} {{VDD}} {fmt_g6(tr - T_PRE_GAP_S + e)} 0)")
        a(f"vrwl{age} rwls{age} 0 pwl(0 {{VDD}} {fmt_g6(tr)} {{VDD}} {fmt_g6(tr + e)} 0)")
        a(f"ven{age} en{age} 0 pwl(0 0 {fmt_g6(te)} 0 {fmt_g6(te + e)} {{VDD}})")
        a(f"venb{age} enb{age} 0 pwl(0 {{VDD}} {fmt_g6(te)} {{VDD}} {fmt_g6(te + e)} 0)")
    a("")
    ics: list[str] = []
    for p in pts:
        n, age = p["name"], p["age_ns"]
        rb, rf = f"rbl_{n}", f"ref_{n}"
        a(f"* ---- instance {p['idx']}: {n} (write order rows {p['order']}, slot bits {p['slot_bits']}) ----")
        a(f"spa_{n} prea {rb} ctl{age} 0 swpre")
        ics.append(f"v({rb})={fmt_g6(VRBL_V)}")
        bl = f"bld{p['slot_bits']}"
        S.emit_column_cells(a, ics, n, rb, bl, (wr_m, wr_p), (rd_m, rd_p),
                            rwl=lambda r: f"rwls{age}" if r == p["row"] else "rwl_des",
                            wwl=lambda r: "wlsw" if (p["weak"] and r == p["row"]) else f"wls{p['order'].index(r)}",
                            sn_ic=lambda r: 0.0 if p["data"][r] else VDD_V,   # opposite of the data to be written
                            n_rows=N_ROWS)
        a(f"crbl_{n} {rb} 0 {{C_RBL}}")
        a(f"spr_{n} pref {rf} ctl{age} 0 swpre")
        a(f"cref_{n} {rf} 0 {{C_RBL}}   $ ASSUMPTION: ideal matched dummy load")
        ics.append(f"v({rf})={fmt_g6(VRBL_V - DREF_V)}")
        S.emit_sense_latch(a, ics, n, rb, rf, latch, en=f"en{age}", enb=f"enb{age}")
        a("")
    a("* initial conditions (tran uic): precharged rails, cells at the opposite of their data, latch tail nodes")
    L += S.ic_lines(ics)
    a("")
    return "\n".join(L)


def build_request() -> dict:
    meas = []
    stop = fmt_g6(t_stop_s() * 1e9)
    for p in instances():
        n, age, r = p["name"], p["age_ns"], p["row"]
        tr, te = t_read_s(age), t_en_s(age)
        sn = f"sn_{n}_{r}"
        # lower-case only (klayout-tools#2914)
        meas += [
            {"name": f"wr_{n}", "unit": "V", "spice": f".meas tran wr_{n} FIND v({sn}) AT={fmt_g6((t_wl_off_s() + 0.5e-9) * 1e9)}n"},
            {"name": f"pre_{n}", "unit": "V", "spice": f".meas tran pre_{n} FIND v({sn}) AT={fmt_g6((tr - 0.2e-9) * 1e9)}n"},
            {"name": f"post_{n}", "unit": "V", "spice": f".meas tran post_{n} FIND v({sn}) AT={fmt_g6(te * 1e9)}n"},
            {"name": f"din_{n}", "unit": "V", "spice": f".meas tran din_{n} FIND v(d_{n}) AT={fmt_g6(te * 1e9)}n"},
            {"name": f"dend_{n}", "unit": "V", "spice": f".meas tran dend_{n} FIND v(d_{n}) AT={stop}n"},
            {"name": f"tdec_{n}", "unit": "s",
             "spice": f".meas tran tdec_{n} TRIG v(en{age}) VAL=0.9 RISE=1 TARG v(dabs_{n}) VAL=0.9 RISE=1"},
        ]
    return klt_request(NETLIST_PATH.name, {"process": PROCESS_CORNERS, "temperature_c": TEMPS_C},
                       f"100p {stop}n 0 {fmt_g6(TMAX_S * 1e9)}n uic", meas, 3300)


def render() -> tuple[str, str]:
    return build_netlist(), json.dumps(build_request(), indent=1) + "\n"


def main() -> int:
    net, req = render()
    NETLIST_PATH.write_text(net)
    REQUEST_PATH.write_text(req)
    print(f"wrote {NETLIST_PATH.name} ({len(instances())} instances) and {REQUEST_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
