#!/usr/bin/env python3
"""Generate the sense-stage Monte Carlo mismatch decks and `klt sim` requests (issue #81).

Stdlib only. Writes, next to this file:

* ``sense_mismatch.spice`` + ``request.json`` -- STAGE-ONLY latch offset study:
  the latch of ``sim/sense-stage`` (same devices, sizes, timing and bias, taken
  from ``gen_sense_stage.py`` by import so the two cannot drift), replicated
  ``N_REPLICAS`` times at every swept input differential. Run over the
  mismatch-enabled ``*_mm`` sections of the pinned sky130 library at the
  corners in ``STAGE_CORNERS`` with ``monte_carlo`` (``vary: mismatch``).
* ``sense_mismatch_cell.spice`` + ``request_cell.json`` -- END-TO-END variant
  (``cell1``/``cell0`` instances: 4-row column + latch) at the least-margin
  corner only (fs/27 C). It reports the READ-DEVICE (cell/column) induced
  spread of the differential delivered to the latch separately from the latch
  offset; it is never folded into the latch sigma.

Why replicas inside one deck: the sky130 ``*_mm`` sections draw the Vth
mismatch term with ``AGAUSS`` inside each device subcircuit's ``.param``
block, so every device INSTANCE gets its own draw. ``R`` replicas at the same
differential are therefore ``R`` independent latches per Monte Carlo sample,
and one ``tran`` per sample yields ``R x len(D_MV)`` Bernoulli decisions.
The analysis checks this (replicas must disagree somewhere, samples must
differ) instead of assuming it.

PROPOSED, NOT RATIFIED: corners/temperatures are inside the restricted range
of ``spec/operating-range-decision-PROPOSED.md`` (27 C and 125 C, VDD = 1.8 V).
Nothing outside it is simulated. Re-run after editing any constant;
``test_sense_mismatch.py`` fails if the committed files are stale.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "sim" / "sense-stage"))
import gen_sense_stage as G  # noqa: E402
sys.path.insert(0, str(REPO / "sim"))
from _evidence_common import VDD_V, fmt_g6, parse_cards  # noqa: E402
from klt_request import build_request as klt_request, mc_block  # noqa: E402

STAGE_NETLIST_PATH = HERE / "sense_mismatch.spice"
STAGE_REQUEST_PATH = HERE / "request.json"
CELL_NETLIST_PATH = HERE / "sense_mismatch_cell.spice"
CELL_REQUEST_PATH = HERE / "request_cell.json"

# ---- scope (subset of the PROPOSED restricted range; nothing outside it) ----
# (mismatch-enabled .lib section, temperature C). Base corners chosen from the
# committed sense-stage summary (sim/sense-stage/README.md results table):
#   ss/125 and tt/27 (named in issue #81), fs/27 (least margin: min resolvable SN
#   0.7-0.8 V), sf/125 (ratified worst-case retention corner; cheap to add).
STAGE_CORNERS = [("tt_mm", 27), ("fs_mm", 27), ("ss_mm", 125), ("sf_mm", 125)]
CELL_CORNERS = [("fs_mm", 27)]

# ---- Monte Carlo (recorded in the request and echoed in the report) ----
MC_SEED = 20261009_81          # base seed; klt derives per-sample seeds from it (SHA-256)
MC_N_STAGE = 40                # samples per stage corner
MC_N_CELL = 40                 # samples at the cell corner

# ---- T1 item 6 / spec row 2e yield campaign (issue #384) ----
# Same stage deck, corners and measurement set as the study above, with a
# larger n (klt yield's zero-failure sample-size verdict needs >= 183 pooled
# samples; 4 corners x 64 = 256) and its own recorded seed, plus a NEGATIVE
# CONTROL deck: the committed stage deck with one seeded defect -- the shared
# reference source (and its .ic) forced high by CONTROL_REF_OFFSET_V, a
# deterministic input-referred offset of about 6.8 sigma_worst on every
# instance (d_eff = d - offset). Same seed and n as the nominal campaign
# (common random numbers), so the degradation is attributable to the defect
# alone and a re-run reproduces it exactly.
ROW2E_MC_N = 64                            # samples per corner (256 pooled)
ROW2E_MC_SEED = 20261120_384               # new seed, recorded here and in the request
CONTROL_REF_OFFSET_V = 0.130               # seeded reference offset (V), see README
ROW2E_MARGIN_D_MV = 150                    # graded differential: largest swept |d| at or
                                           # below the committed 2a worst-case half-separation
                                           # (fs/27 C aged 0.3289 V / 2 = 164.5 mV)
CONTROL_NETLIST_PATH = HERE / "sense_mismatch_control.spice"
ROW2E_REQUEST_PATH = HERE / "request_row2e.json"
CONTROL_REQUEST_PATH = HERE / "request_row2e_control.json"

# ---- stage-only sweep (ASSUMPTION: grid; same common mode as sense-stage st_*) ----
STAGE_DREF_V = G.STAGE_ONLY_DREF_V          # ref = VRBL - 0.1 V, rbl = ref + d (as in sense-stage)
D_MV = [0, 2, -2, 5, -5, 10, -10, 15, -15, 20, -20, 30, -30, 40, -40,
        50, -50, 60, -60, 80, -80, 100, -100, 150, -150]
N_REPLICAS = 6                 # independent latches per differential per sample

# ---- end-to-end (cell) variant at fs/27 (ASSUMPTION: grid) ----
CELL_DVREF_V = [0.05, 0.10]    # 50 mV = best swept reference at fs/27; 100 mV = placeholder separation
CELL_SN1_LEVELS_V = [round(0.60 + 0.05 * k, 2) for k in range(9)]   # 0.60 .. 1.00 V stored '1'
CELL_SN0_LEVELS_V = [0.00]     # stored '0' negative control
N_CELL_REPLICAS = 4

# ---- timing: as sense-stage, but stop 10 ns after enable (window is 5 ns) ----
T_STOP_S = G.T_EN_S + 10e-9


def _mv_tag(d: int) -> str:
    return ("z" if d == 0 else "p" if d > 0 else "m") + f"{abs(d):03d}"


def stage_instances() -> list[dict]:
    pts = []
    for d in D_MV:
        for r in range(N_REPLICAS):
            pts.append(dict(kind="stage", dref=STAGE_DREF_V, d_mv=d, rep=r,
                            name=f"s{_mv_tag(d)}_{r}"))
    return pts


def cell_instances() -> list[dict]:
    pts = []
    for dref in CELL_DVREF_V:
        for kind, levels in (("cell0", CELL_SN0_LEVELS_V), ("cell1", CELL_SN1_LEVELS_V)):
            for lvl in levels:
                for r in range(N_CELL_REPLICAS):
                    pts.append(dict(kind=kind, dref=dref, sn=lvl, rep=r,
                                    name=f"{'c1' if kind == 'cell1' else 'c0'}_r{round(dref * 1000):03d}_{G.sn_mv_tag(lvl)}_{r}"))
    return pts


def _header(title: str, kinds: str) -> list[str]:
    return [
        f"* {title}",
        "* GENERATED by sim/sense-mismatch/gen_sense_mismatch.py (issue #81); do not edit by hand.",
        "*",
        "* PROPOSED/UNRATIFIED SCOPE: corners/temperatures from spec/operating-range-decision-PROPOSED.md.",
        "* CIRCUIT BODY for `klt sim`: no .control/.end; klt appends the .lib (a *_mm mismatch section,",
        "* MC_MM_SWITCH=1), .temp and the per-sample `.options seed` cards.",
        "* Latch/footer/header devices, sizes, timing and bias are those of sim/sense-stage/gen_sense_stage.py.",
        "* Every sky130 FET instance gets its own AGAUSS Vth-mismatch draw (the PDK switch is global per",
        "* section: footer/header/cell devices also carry mismatch, see README).",
        f"* Instance kinds: {kinds}",
        "*",
        "* ASSUMPTIONS (labelled; none is a spec value): C_RBL, VRBL, reference level, sense instant,",
        "* latch/footer/header sizes, ideal precharge switch, ideal drivers, ideal matched dummy load.",
        "",
        f".param VDD     = {fmt_g6(VDD_V)}",
        f".param VRBL    = {fmt_g6(G.VRBL_V)}   $ ASSUMPTION (contract)",
        f".param TEDGE   = {fmt_g6(G.T_EDGE_S)}",
        f".param T_READ  = {fmt_g6(G.T_READ_S)}   $ select edge",
        f".param T_PGAP  = {fmt_g6(G.T_PRE_GAP_S)}   $ precharge released this long before T_READ",
        f".param T_EN    = {fmt_g6(G.T_EN_S)}   $ ASSUMPTION: latch enable = contract sense instant (T_READ+10n)",
        f".param C_RBL   = {fmt_g6(G.C_RBL_F)}   $ ASSUMPTION (contract; not extracted)",
        "",
        "* ---- shared drivers (ideal) ----",
        "vdd   vdd 0 dc {VDD}",
        "vctl  ctl 0 pwl(0 {VDD} {T_READ-T_PGAP} {VDD} {T_READ-T_PGAP+TEDGE} 0)",
        "ven   en  0 pwl(0 0 {T_EN} 0 {T_EN+TEDGE} {VDD})",
        "venb  enb 0 pwl(0 {VDD} {T_EN} {VDD} {T_EN+TEDGE} 0)",
        ".model swpre sw(vt=0.9 vh=0.1 ron=100 roff=1e12)",
    ]


def build_stage_netlist(ref_offset_v: float = 0.0) -> str:
    """Stage deck; ``ref_offset_v != 0`` emits the NEGATIVE-CONTROL variant
    (issue #384): the same deck with the shared reference (source and .ic)
    forced by that offset -- a deterministic input-referred offset of
    ``ref_offset_v`` on every instance. At ``0`` the output is byte-identical
    to the committed study deck (test_sense_mismatch.py checks this)."""
    control = ref_offset_v != 0.0
    title = ("sense_mismatch_control.spice -- NEGATIVE CONTROL of the stage-only latch offset"
             if control else "sense_mismatch.spice -- stage-only latch offset Monte Carlo (sense-stage latch, R replicas)")
    L = _header(title, "s<p|m|z><mV>_<r>: rbl precharged to VREF+d, no cells, replica r")
    a = L.append
    if control:
        a(f"* SEEDED DEFECT (issue #384 negative control): shared reference forced +{fmt_g6(ref_offset_v)} V")
        a(f"* (input-referred offset on every instance; d_eff = d - {fmt_g6(ref_offset_v)}). Deterministic:")
        a("* same corners, n and seed as request_row2e.json (common random numbers).")
        a("")
    ref = f"pref_{round(STAGE_DREF_V * 1000):03d}"
    ref_level = G.VRBL_V - STAGE_DREF_V + ref_offset_v
    a(f"vref_{round(STAGE_DREF_V * 1000):03d} {ref} 0 dc {fmt_g6(ref_level)}   $ reference = VRBL - {fmt_g6(STAGE_DREF_V)} (ASSUMPTION)"
      + (f" + seeded defect {fmt_g6(ref_offset_v)} V" if control else ""))
    for d in D_MV:
        va = G.VRBL_V - STAGE_DREF_V + d * 1e-3
        a(f"vpa_{_mv_tag(d)} pa_{_mv_tag(d)} 0 dc {va:.6f}")
    a("")
    latch = parse_cards(G.REPO / "design" / "sense_latch.spice")
    ics: list[str] = []
    for p in stage_instances():
        n = p["name"]
        rb, rf = f"rbl_{n}", f"ref_{n}"
        va = G.VRBL_V - STAGE_DREF_V + p["d_mv"] * 1e-3
        a(f"* ---- {n}: d = {p['d_mv']} mV, replica {p['rep']} ----")
        a(f"spa_{n} pa_{_mv_tag(p['d_mv'])} {rb} ctl 0 swpre")
        a(f"crbl_{n} {rb} 0 {{C_RBL}}")
        a(f"spr_{n} {ref} {rf} ctl 0 swpre")
        a(f"cref_{n} {rf} 0 {{C_RBL}}   $ ASSUMPTION: ideal matched dummy load")
        ics.append(f"v({rb})={va:.6f}")
        ics.append(f"v({rf})={ref_level:.6f}")
        G.emit_sense_latch(a, ics, n, rb, rf, latch)
        a("")
    a("* initial conditions (tran uic): precharged rails, stored levels, tail nodes")
    L += G.ic_lines(ics)
    a("")
    return "\n".join(L)


def build_cell_netlist(c_sn_f: float) -> str:
    (wr_m, wr_p), (rd_m, rd_p) = G.design_cell_cards()
    L = _header("sense_mismatch_cell.spice -- end-to-end (4-row column + latch) Monte Carlo at fs/27 C",
                "c1_* stored '1', c0_* stored '0'; r<mV> = reference offset; last field = replica")
    a = L.append
    a(f".param C_SN    = {fmt_g6(c_sn_f)}   $ extracted-from-netlist (layout/gain_cell_2t.extract.parasitics.json)")
    a("vrwls rwl_sel 0 pwl(0 {VDD} {T_READ} {VDD} {T_READ+TEDGE} 0)")
    a("vrwld rwl_des 0 dc {VDD}")
    a("vpre  prea 0 dc {VRBL}")
    for dref in CELL_DVREF_V:
        a(f"vref_{round(dref * 1000):03d} pref_{round(dref * 1000):03d} 0 dc {fmt_g6(G.VRBL_V - dref)}   $ reference = VRBL - {fmt_g6(dref)} (ASSUMPTION)")
    a("")
    latch = parse_cards(G.REPO / "design" / "sense_latch.spice")
    ics: list[str] = []
    for p in cell_instances():
        n = p["name"]
        rb, rf = f"rbl_{n}", f"ref_{n}"
        a(f"* ---- {n}: {p['kind']} SN = {p['sn']} V, ref offset {p['dref']} V, replica {p['rep']} ----")
        a(f"spa_{n} prea {rb} ctl 0 swpre")
        ics.append(f"v({rb})={fmt_g6(G.VRBL_V)}")
        G.emit_column_cells(a, ics, n, rb, "0", (wr_m, wr_p), (rd_m, rd_p),
                            rwl=("rwl_sel", "rwl_des"), sn_ic=lambda _r: p["sn"])
        a(f"crbl_{n} {rb} 0 {{C_RBL}}")
        a(f"spr_{n} pref_{round(p['dref'] * 1000):03d} {rf} ctl 0 swpre")
        a(f"cref_{n} {rf} 0 {{C_RBL}}   $ ASSUMPTION: ideal matched dummy load")
        ics.append(f"v({rf})={G.VRBL_V - p['dref']:.6f}")
        G.emit_sense_latch(a, ics, n, rb, rf, latch)
        a("")
    a("* initial conditions (tran uic): precharged rails, stored levels, tail nodes")
    L += G.ic_lines(ics)
    a("")
    return "\n".join(L)


def _corners(cs: list[tuple[str, int]]) -> tuple[dict, list[dict]]:
    procs = list(dict.fromkeys(p for p, _ in cs))
    temps = sorted({t for _, t in cs})
    excl = [{"process": p, "temperature_c": t} for p in procs for t in temps if (p, t) not in cs]
    out: dict = {"process": procs, "temperature_c": temps}
    return out, excl


def _request(netlist: str, cs: list[tuple[str, int]], n_mc: int, meas: list[dict],
             seed: int = MC_SEED) -> dict:
    corners, excl = _corners(cs)
    return klt_request(netlist, corners, f"10p {fmt_g6(T_STOP_S * 1e9)}n 0 50p uic", meas, 900,
                       exclude=excl, monte_carlo=mc_block(n_mc, seed))


def build_stage_request() -> dict:
    names = [p["name"] for p in stage_instances()]
    return _request(STAGE_NETLIST_PATH.name, STAGE_CORNERS, MC_N_STAGE,
                    G.sense_stage_meas(names, t_stop_s=T_STOP_S))


def build_row2e_request() -> dict:
    """Nominal campaign for the row-2e yield evidence: the committed stage deck
    (netlist unchanged, same measurements), larger n, its own seed."""
    names = [p["name"] for p in stage_instances()]
    return _request(STAGE_NETLIST_PATH.name, STAGE_CORNERS, ROW2E_MC_N,
                    G.sense_stage_meas(names, t_stop_s=T_STOP_S), seed=ROW2E_MC_SEED)


def build_control_request() -> dict:
    """Negative-control campaign: the seeded-defect deck, same n and seed as
    the nominal row-2e campaign (common random numbers)."""
    names = [p["name"] for p in stage_instances()]
    return _request(CONTROL_NETLIST_PATH.name, STAGE_CORNERS, ROW2E_MC_N,
                    G.sense_stage_meas(names, t_stop_s=T_STOP_S), seed=ROW2E_MC_SEED)


def build_cell_request() -> dict:
    names = [p["name"] for p in cell_instances()]
    return _request(CELL_NETLIST_PATH.name, CELL_CORNERS, MC_N_CELL,
                    G.sense_stage_meas(names, t_stop_s=T_STOP_S))


def render() -> dict[Path, str]:
    c_sn_ff, _prov = G.load_extracted_c_sn(G.EXTRACT_JSON, "sn")
    return {
        STAGE_NETLIST_PATH: build_stage_netlist(),
        STAGE_REQUEST_PATH: json.dumps(build_stage_request(), indent=1) + "\n",
        CELL_NETLIST_PATH: build_cell_netlist(c_sn_ff * 1e-15),
        CELL_REQUEST_PATH: json.dumps(build_cell_request(), indent=1) + "\n",
        CONTROL_NETLIST_PATH: build_stage_netlist(CONTROL_REF_OFFSET_V),
        ROW2E_REQUEST_PATH: json.dumps(build_row2e_request(), indent=1) + "\n",
        CONTROL_REQUEST_PATH: json.dumps(build_control_request(), indent=1) + "\n",
    }


def main() -> int:
    for path, text in render().items():
        path.write_text(text)
        print(f"wrote {path.name}")
    print(f"{len(stage_instances())} stage instances, {len(cell_instances())} cell instances")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
