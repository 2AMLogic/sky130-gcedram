#!/usr/bin/env python3
"""Generate the closed-loop refresh-operation netlist and `klt sim` request (issue #110).

Stdlib only. Writes, next to this file:

* ``refresh_op.spice`` -- flat circuit body (no ``.control``/``.end``) for ``klt sim``.
  One full row refresh operation per parallel instance: precharge, RWL select,
  latch enable, latch complement output drives WBL, WWL pulse writes the decided
  value back, release. Sweep axes (every point an independent instance):
  select-to-enable sense time x write-back WWL pulse width x stored pattern.
* ``request.json`` -- 5 global process corners x {27, 125} C, one ``tran`` each.

Reuses the sense-stage latch, sizes, column and constants from
``sim/sense-stage/gen_sense_stage.py`` (single source of truth); the bitcell
cards are inlined from ``design/gain_cell_2t.spice``.

PROPOSED, NOT RATIFIED: scope is the restricted range of
``spec/operating-range-decision-PROPOSED.md`` (27/125 C, VDD 1.8 V, global
corners, no mismatch). Re-run after editing any constant; the stdlib test
fails if the committed files are stale.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "sim" / "sense-stage"))
import gen_sense_stage as S  # noqa: E402

NETLIST_PATH = HERE / "refresh_op.spice"
REQUEST_PATH = HERE / "request.json"

PROCESS_CORNERS = S.PROCESS_CORNERS
TEMPS_C = S.TEMPS_C
VDD_V = S.VDD_V
VRBL_V = S.VRBL_V
DREF_V = 0.10                  # ASSUMPTION: reference = VRBL - 100 mV (the sense-stage placeholder separation)
N_ROWS = S.N_ROWS
T_EDGE_S = S.T_EDGE_S

# ---- phases of one row refresh operation (ns). SWEPT = searched; FIXED = ASSUMPTION ----
T_PRE_ON_S = 2e-9              # FIXED ASSUMPTION: ideal precharge switch (100 ohm x 10 fF ~ 1 ps) held 2 ns (contract lead)
T_PRE_GAP_S = S.T_PRE_GAP_S    # FIXED (contract): precharge released 2 ns before the select edge
T_READ_S = T_PRE_ON_S + T_PRE_GAP_S   # select edge at 4 ns; op starts at t = 0
T_LATCH_S = 1e-9               # FIXED ASSUMPTION: enable -> WWL/WBL-connect delay (latch decides in <1 ns, sense-stage tdec 0.05-0.5 ns)
T_GUARD_S = 2e-9               # FIXED ASSUMPTION: WWL fall -> release of latch/WBL/RWL (loaded-column bl-release delay)
T_MEAS_S = 2e-9                # SN is read this long after the release edge (lets RWL-coupling settle)
SENSE_S = [0.5e-9, 1e-9, 2e-9, 5e-9, 10e-9]  # SWEPT: select edge -> latch enable (contract value is 10 ns)
WB_S = [0.5e-9, 1e-9, 2e-9, 3e-9, 5e-9, 7.5e-9, 10e-9, 15e-9, 20e-9, 30e-9, 50e-9]   # SWEPT: WWL pulse (50 % width)
NEG_CONTROL_WB_S = 0.2e-9      # negative control: deliberately too-short WWL pulse; the analyzer must flag it unrestored
REF_WB_S = 20e-9               # in-deck reference write: ideal 1.8 V WBL, 20 ns WWL (bitcell-transient default), SN from 0 V
C_WBL_F = 10e-15               # ASSUMPTION: write-bitline load, not extracted (same as C_RBL)
R_WBL_SW = 100                 # ASSUMPTION: ideal WBL connect switch on-resistance (ohm)
SN1_PRE_V = [0.90, 1.00]       # stored '1' pre-read level: 0.9 V = the retention study's VDD/2 stored-level; 1.0 V fresher.
                               # Kept below 0.95 x the lowest-corner reference write (~1.14 V) so a no-write cannot pass
SN0_PRE_V = [-0.10, 0.00]      # stored '0' pre-read level (sense-stage)


def sense_grid() -> list[float]:
    return list(SENSE_S)


def wb_grid() -> list[float]:
    return [NEG_CONTROL_WB_S] + list(WB_S)


def _ns(x: float) -> str:
    return f"{x * 1e9:.4g}".replace(".", "p").replace("-", "m")


def instances() -> list[dict]:
    pts = []
    for sn in SN1_PRE_V:
        for s in SENSE_S:
            for w in wb_grid():
                pts.append(dict(kind="op1", sn=sn, sense=s, wb=w))
    for sn in SN0_PRE_V:
        for s in SENSE_S:
            for w in wb_grid():
                pts.append(dict(kind="op0", sn=sn, sense=s, wb=w))
    pts.append(dict(kind="ref", sn=0.0, sense=SENSE_S[-1], wb=REF_WB_S))
    for i, p in enumerate(pts):
        if p["kind"] == "ref":
            p["name"] = "refw"
        else:
            tag = ("n%03d" % round(-p["sn"] * 1000)) if p["sn"] < 0 else ("%04d" % round(p["sn"] * 1000))
            p["name"] = f"{p['kind']}_{tag}_s{_ns(p['sense'])}_w{_ns(p['wb'])}"
        p["idx"] = i
        p.update(times(p["sense"], p["wb"]))
    return pts


def times(sense: float, wb: float) -> dict:
    t_en = T_READ_S + sense
    t_on = t_en + T_LATCH_S
    t_off = t_on + wb
    t_rel = t_off + T_GUARD_S
    return dict(t_en=t_en, t_on=t_on, t_off=t_off, t_rel=t_rel, t_meas=t_rel + T_MEAS_S)


def t_stop_s() -> float:
    return max(p["t_meas"] for p in instances()) + 1e-9


def t_row_refresh_op_s(sense: float, wb: float) -> float:
    """Total wall time of one row operation: precharge-on + precharge gap + sense + latch + pulse + guard."""
    return T_PRE_ON_S + T_PRE_GAP_S + sense + T_LATCH_S + wb + T_GUARD_S


def _pwl_pulse(hi: str, lo: str, t0: float, t1: float) -> str:
    """pwl: `lo` until t0, ramp to `hi` over TEDGE, hold, ramp back to `lo` at t1 (50 % points at t0/t1 ignoring edge)."""
    return (f"pwl(0 {lo} {t0:.4e} {lo} {t0 + T_EDGE_S:.4e} {hi} {t1:.4e} {hi} {t1 + T_EDGE_S:.4e} {lo})")


def build_netlist(c_sn_f: float) -> str:
    (wr_m, wr_p), (rd_m, rd_p) = S.design_cell_cards()
    pts = instances()
    L: list[str] = []
    a = L.append
    a("* refresh_op.spice -- closed-loop row refresh operation (sense -> write-back), issue #110")
    a("* GENERATED by gen_refresh_op.py; do not edit by hand.")
    a("*")
    a("* PROPOSED/UNRATIFIED SCOPE: corners/temperatures (27 C, 125 C, five global corners, 1.8 V)")
    a("* come from spec/operating-range-decision-PROPOSED.md. CIRCUIT BODY for `klt sim`.")
    a("*")
    a("* One op = precharge (rbl/ref to VRBL/VREF) -> RWL select -> latch enable at select+SENSE ->")
    a("* (+T_LATCH) WWL pulse of width WB with the latch COMPLEMENT node `ref` connected to WBL")
    a("* (stored '1' pulls rbl down, so ref goes high and writes '1') -> +T_GUARD release of")
    a("* latch, WBL connection and RWL -> SN read T_MEAS later.")
    a("* Instances: op1_* / op0_* = full op, pre-read SN level in name (n=negative, mV), s<ns> =")
    a("* sense time, w<ns> = WWL pulse (p = decimal point). refw = in-deck reference write:")
    a("* SN from 0 V, ideal 1.8 V WBL, 20 ns WWL (the 'post-write level' the restore test is")
    a("* measured against). w0p2 = NEGATIVE CONTROL pulse (too short; must be flagged unrestored).")
    a("*")
    a("* ASSUMPTIONS (none is a spec value): ideal switches for precharge / WBL connect (100 ohm),")
    a("* ideal WWL/RWL/enable drivers, C_RBL = C_WBL = 10 fF (not extracted), 4-row column all rows")
    a("* at one level, ideal matched dummy reference load, reference = VRBL - 100 mV, latch sizes")
    a("* (first pass), T_LATCH and T_GUARD fixed, global corners only (no mismatch).")
    a("")
    a(f".param VDD   = {S._fmt(VDD_V)}")
    a(f".param VRBL  = {S._fmt(VRBL_V)}   $ ASSUMPTION (contract)")
    a(f".param TEDGE = {S._fmt(T_EDGE_S)}")
    a(f".param T_READ = {S._fmt(T_READ_S)}   $ select edge = T_PRE_ON + T_PRE_GAP")
    a(f".param T_PGAP = {S._fmt(T_PRE_GAP_S)}")
    a(f".param C_RBL = {S._fmt(S.C_RBL_F)}   $ ASSUMPTION (contract; not extracted)")
    a(f".param C_WBL = {S._fmt(C_WBL_F)}   $ ASSUMPTION (not extracted)")
    a(f".param C_SN  = {S._fmt(c_sn_f)}   $ extracted-from-netlist (layout/gain_cell_2t.extract.parasitics.json)")
    a("")
    a("* ---- shared drivers (ideal) ----")
    a("vdd   vdd 0 dc {VDD}")
    a("vctl  ctl 0 pwl(0 {VDD} {T_READ-T_PGAP} {VDD} {T_READ-T_PGAP+TEDGE} 0)")
    a("vrwld rwl_des 0 dc {VDD}")
    a("vwwld wwl_des 0 dc 0")
    a("vpre  prea 0 dc {VRBL}")
    a(f"vref  pref 0 dc {S._fmt(VRBL_V - DREF_V)}   $ reference = VRBL - {S._fmt(DREF_V)} (ASSUMPTION)")
    a("vwbi  wbl_ideal 0 dc {VDD}")
    a(".model swpre sw(vt=0.9 vh=0.1 ron=100 roff=1e12)")
    a(f".model swwbl sw(vt=0.9 vh=0.1 ron={R_WBL_SW} roff=1e12)")
    a("")
    ics: list[str] = []
    for p in pts:
        n = p["name"]
        rb, rf, vn, vp, wb = f"rbl_{n}", f"ref_{n}", f"vn_{n}", f"vp_{n}", f"wbl_{n}"
        a(f"* ---- instance {p['idx']}: {n} (t_en {p['t_en']*1e9:.4g} ns, WWL {p['t_on']*1e9:.4g}..{p['t_off']*1e9:.4g} ns, release {p['t_rel']*1e9:.4g} ns) ----")
        a(f"ven_{n}  en_{n}  0 pwl(0 0 {p['t_en']:.4e} 0 {p['t_en'] + T_EDGE_S:.4e} {{VDD}} {p['t_rel']:.4e} {{VDD}} {p['t_rel'] + T_EDGE_S:.4e} 0)")
        a(f"venb_{n} enb_{n} 0 pwl(0 {{VDD}} {p['t_en']:.4e} {{VDD}} {p['t_en'] + T_EDGE_S:.4e} 0 {p['t_rel']:.4e} 0 {p['t_rel'] + T_EDGE_S:.4e} {{VDD}})")
        a(f"vrs_{n}  rwls_{n} 0 pwl(0 {{VDD}} {{T_READ}} {{VDD}} {{T_READ+TEDGE}} 0 {p['t_rel']:.4e} 0 {p['t_rel'] + T_EDGE_S:.4e} {{VDD}})")
        a(f"vww_{n}  wwl_{n} 0 " + _pwl_pulse("{VDD}", "0", p["t_on"], p["t_off"]))
        a(f"vwc_{n}  wbc_{n} 0 pwl(0 0 {p['t_on']:.4e} 0 {p['t_on'] + T_EDGE_S:.4e} {{VDD}} {p['t_rel']:.4e} {{VDD}} {p['t_rel'] + T_EDGE_S:.4e} 0)")
        if p["kind"] == "ref":
            a(f"* reference write: ideal 1.8 V WBL; rbl/ref/latch idle (no read)")
            a(f"vwbr_{n} {wb} 0 dc {{VDD}}")
            ics.append(f"v({wb})={S._fmt(VDD_V)}")
        else:
            ics.append(f"v({wb})=0")
            a(f"swb_{n} {rf} {wb} wbc_{n} 0 swwbl")
        a(f"cwbl_{n} {wb} 0 {{C_WBL}}")
        # previous-op rails (worst case for precharge): rbl high, ref low
        a(f"spa_{n} prea {rb} ctl 0 swpre")
        a(f"spr_{n} pref {rf} ctl 0 swpre")
        a(f"crbl_{n} {rb} 0 {{C_RBL}}")
        a(f"cref_{n} {rf} 0 {{C_RBL}}   $ ASSUMPTION: ideal matched dummy load")
        ics.append(f"v({rb})={S._fmt(VDD_V)}")
        ics.append(f"v({rf})=0")
        for r in range(N_ROWS):
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
    return "\n".join(L)


def build_request() -> dict:
    meas = []
    for p in instances():
        n = p["name"]
        sn0 = f"sn_{n}_0"
        meas += [
            {"name": f"snend_{n}", "unit": "V",
             "spice": f".meas tran snend_{n} FIND v({sn0}) AT={p['t_meas'] * 1e9:.6g}n"},
            {"name": f"snrd_{n}", "unit": "V",
             "spice": f".meas tran snrd_{n} FIND v({sn0}) AT={(p['t_on'] - 0.1e-9) * 1e9:.6g}n"},
            {"name": f"dec_{n}", "unit": "V",
             "spice": f".meas tran dec_{n} FIND v(d_{n}) AT={(p['t_on'] - 0.1e-9) * 1e9:.6g}n"},
        ]
    return {
        "netlist": "refresh_op.spice",
        "engine": "ngspice",
        "backend": "batch",
        "models": {"pdk": "sky130A", "lib": "libs.tech/combined/sky130.lib.spice"},
        "corners": {"process": PROCESS_CORNERS, "temperature_c": TEMPS_C},
        "analysis": {"kind": "tran", "args": f"10p {t_stop_s() * 1e9:.6g}n 0 50p uic"},
        "measurements": meas,
        "options": {"timeout_s": 1800, "keep_artifacts": False, "waveforms": False},
    }


def render() -> tuple[str, str]:
    c_sn_ff, _prov = S.load_extracted_c_sn(S.EXTRACT_JSON, "sn")
    return build_netlist(c_sn_ff * 1e-15), json.dumps(build_request(), indent=1) + "\n"


def main() -> int:
    net, req = render()
    NETLIST_PATH.write_text(net)
    REQUEST_PATH.write_text(req)
    print(f"wrote {NETLIST_PATH.name} ({len(instances())} instances) and {REQUEST_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
