#!/usr/bin/env python3
"""Generate the sense-stage netlist and `klt sim` request (issue #60).

Stdlib only. Writes, next to this file:

* ``sense_stage.spice`` -- a *circuit body* (no ``.control``/``.end``), as
  ``klt sim`` requires, FLAT and self-contained: the batch fleet receives
  only ``netlist.cir`` + ``request.json``, so the bitcell device cards are
  inlined (copied from ``design/gain_cell_2t.spice`` by this script; the
  test suite checks they still match) instead of ``.include``d.
* ``request.json`` -- the ``klt sim`` request: process corners x
  temperatures taken from RESTRICTED_RANGE below, one ``tran`` per corner,
  every sweep point an independent parallel instance inside that one deck.

Re-run after editing any constant; ``test_sense_stage.py`` fails if the
committed files are stale.

PROPOSED, NOT RATIFIED: the corner/temperature set is the restricted range
of ``spec/operating-range-decision-PROPOSED.md`` (27 C and 125 C, five
global process corners, VDD = 1.8 V). Nothing outside it is simulated.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "sim" / "retention"))
from derive_retention import load_extracted_c_sn  # noqa: E402

NETLIST_PATH = HERE / "sense_stage.spice"
REQUEST_PATH = HERE / "request.json"
DESIGN_NETLIST = REPO / "design" / "gain_cell_2t.spice"
EXTRACT_JSON = REPO / "layout" / "gain_cell_2t.extract.parasitics.json"

# ---- scope: restricted range of the PROPOSED record (nothing outside it) ----
PROCESS_CORNERS = ["tt", "ss", "ff", "sf", "fs"]
TEMPS_C = [27, 125]            # 27 C = restricted cold bound; 125 C = worst-case retention corner
VDD_V = 1.8

# ---- bias / timing (contract inputs, SENSE_INPUT_CONTRACT.md) ----
VRBL_V = 0.9                   # rbl precharge (contract)
C_RBL_F = 10e-15               # ASSUMPTION (contract; not extracted)
T_READ_S = 10e-9               # select edge; precharge released 2 ns earlier (contract)
T_PRE_GAP_S = 2e-9
T_EN_S = T_READ_S + 10e-9      # latch enable = contract sense instant, 10 ns after select edge
T_STOP_S = T_EN_S + 20e-9
T_EDGE_S = 100e-12

# ---- sweeps (ASSUMPTIONS) ----
DVREF_V = [0.02, 0.05, 0.10, 0.20]         # reference = VRBL - DVREF (ASSUMPTION; contract forbids the UNVALIDATED common_reference values)
STAGE_ONLY_DREF_V = 0.10       # stage-only offset sweep uses this reference
STAGE_ONLY_D_MV = [-100, -50, -20, -10, -5, -2, -1, 1, 2, 5, 10, 20, 50, 100]  # rbl - ref at the enable instant
SN1_LEVELS_V = [round(0.30 + 0.05 * k, 2) for k in range(19)]  # 0.30 .. 1.20 pre-read stored-'1' level
SN0_LEVELS_V = [-0.10, 0.00]   # stored '0' pre-read level (undershoot floor -0.135 V in the contract)
N_ROWS = 4                     # contract column size (ASSUMPTION)

# ---- sense-stage devices (ASSUMPTION: sizes are first-pass choices) ----
# (model, W um, L um); ad/as/pd/ps follow the bitcell convention 0.29 um diffusion.
LATCH_N = ("sky130_fd_pr__nfet_01v8", 1.0, 0.15)
LATCH_P = ("sky130_fd_pr__pfet_01v8", 2.0, 0.15)
FOOTER = ("sky130_fd_pr__nfet_01v8", 2.0, 0.15)
HEADER = ("sky130_fd_pr__pfet_01v8", 4.0, 0.15)
DIFF_UM = 0.29

# ---- issue #88 variants (default output above is unchanged) ----
# ``--variant NAME`` writes ``sense_stage_<NAME>.spice`` and ``request_<NAME>.json``
# instead; without ``--variant`` the output is unchanged byte for byte. A variant
# changes only the lumped C_RBL (on ``rbl`` AND on the matched dummy reference
# load) and, for ``*_layoutcard``, the bitcell diffusion card.
PARASITICS_SUMMARY = REPO / "layout" / "gain_cell_2t_array.parasitics.summary.json"
C_RBL_KEY = ("comparison", "c_rbl", "extracted_4row_worst_total_ff")
# Diffusion card drawn by the layout (layout/gain_cell_2t_array.extract.parasitics.spice);
# design/gain_cell_2t.spice uses ad=as=0.1218, pd=ps=1.42. Reconciliation is issue #89.
LAYOUT_CARD = {"ad": "0.1974", "as": "0.1974", "pd": "1.78", "ps": "1.78"}


def extracted_c_rbl_ff() -> float:
    v = json.loads(PARASITICS_SUMMARY.read_text())
    for k in C_RBL_KEY:
        v = v[k]
    return float(v)


def variants() -> dict:
    ext = extracted_c_rbl_ff() * 1e-15
    lab = ("EXTRACTED-4-ROW (layout/gain_cell_2t_array.parasitics.summary.json "
           "comparison.c_rbl.extracted_4row_worst_total_ff; N_rows = 4 is a STUDY-ASSUMPTION)")
    return {
        "crbl_ext4row": dict(c_rbl_f=ext, c_rbl_label=lab, card="design"),
        "crbl_2f": dict(c_rbl_f=2e-15, c_rbl_label="ASSUMPTION (mid-point, not extracted)", card="design"),
        "crbl_ext4row_layoutcard": dict(c_rbl_f=ext, c_rbl_label=lab, card="layout"),
    }


def layout_card(params: str) -> str:
    out = params
    for k, v in LAYOUT_CARD.items():
        out, n = re.subn(rf"\b{k}=[0-9.eE+-]+", f"{k}={v}", out)
        if n != 1:
            raise RuntimeError(f"card has {n} '{k}=' fields: {params}")
    return out


def variant_paths(variant: str | None) -> tuple[Path, Path]:
    if variant is None:
        return NETLIST_PATH, REQUEST_PATH
    return HERE / f"sense_stage_{variant}.spice", HERE / f"request_{variant}.json"


def _fmt(x: float) -> str:
    return f"{x:.6g}"


def dev_params(w: float, l: float) -> str:
    ad = w * DIFF_UM
    pd = 2 * (w + DIFF_UM)
    return (f"L={_fmt(l)} W={_fmt(w)} nf=1 ad={_fmt(ad)} as={_fmt(ad)} "
            f"pd={_fmt(pd)} ps={_fmt(pd)} mult=1 m=1")


def design_cell_cards() -> tuple[str, str]:
    """(model, trailing params) of M_WR and M_RD from design/gain_cell_2t.spice."""
    text = re.sub(r"\n\+", " ", DESIGN_NETLIST.read_text())
    out = {}
    for line in text.splitlines():
        m = re.match(r"^X(M_WR|M_RD)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(.*)$", line)
        if m:
            out[m.group(1)] = (m.group(6), m.group(7).strip())
    if set(out) != {"M_WR", "M_RD"}:
        raise RuntimeError("could not parse M_WR/M_RD from design/gain_cell_2t.spice")
    return out["M_WR"], out["M_RD"]


def instances() -> list[dict]:
    """Ordered sweep points; each becomes one parallel instance in the deck."""
    pts = []
    for d in STAGE_ONLY_D_MV:
        pts.append(dict(kind="stage", dref=STAGE_ONLY_DREF_V, d_mv=d))
    for dref in DVREF_V:
        for lvl in SN0_LEVELS_V:
            pts.append(dict(kind="cell0", dref=dref, sn=lvl))
        for lvl in SN1_LEVELS_V:
            pts.append(dict(kind="cell1", dref=dref, sn=lvl))
    for i, p in enumerate(pts):
        if p["kind"] == "stage":
            # lower-case only: the fleet runner's klt matches .meas names case-sensitively
            # against ngspice's lower-cased output (klayout-tools#2914)
            p["name"] = f"st_{'p' if p['d_mv'] > 0 else 'm'}{abs(p['d_mv'])}mv"
        else:
            tag = ("n%03d" % round(-p["sn"] * 1000)) if p["sn"] < 0 else ("%04d" % round(p["sn"] * 1000))
            p["name"] = f"{p['kind']}_r{round(p['dref'] * 1000):03d}_{tag}"
        p["idx"] = i
    return pts


def build_netlist(c_sn_f: float, variant: str | None = None) -> str:
    (wr_m, wr_p), (rd_m, rd_p) = design_cell_cards()
    c_rbl_f, c_rbl_label = C_RBL_F, "ASSUMPTION (contract; not extracted)"
    if variant is not None:
        v = variants()[variant]
        c_rbl_f, c_rbl_label = v["c_rbl_f"], v["c_rbl_label"]
        if v["card"] == "layout":
            wr_p, rd_p = layout_card(wr_p), layout_card(rd_p)
    pts = instances()
    L: list[str] = []
    a = L.append
    if variant is None:
        a("* sense_stage.spice -- single-ended latch sense stage on the 2T gain-cell read bitline")
        a("* (issue #60, Epic #24 item 2). GENERATED by gen_sense_stage.py; do not edit by hand.")
    else:
        a(f"* sense_stage_{variant}.spice -- issue #88 variant of the issue #60 sense-stage deck.")
        a(f"* GENERATED by gen_sense_stage.py --variant {variant}; do not edit by hand.")
        a(f"* Changed from the default deck ONLY: C_RBL on rbl and on the matched dummy reference load"
          + (", and the bitcell diffusion card (layout: ad=as=0.1974 pd=ps=1.78)" if variants()[variant]["card"] == "layout" else "")
          + ".")
    a("*")
    a("* PROPOSED/UNRATIFIED SCOPE: the corners/temperatures this deck is run over come from")
    a("* spec/operating-range-decision-PROPOSED.md (27 C and 125 C only). Inputs follow")
    a("* sim/loaded-column/cold-corner/SENSE_INPUT_CONTRACT.md (baseline column).")
    a("* CIRCUIT BODY for `klt sim`: no .control/.end; the PDK .lib/.temp cards are appended per")
    a("* corner by klt. Flat and self-contained (batch fleet gets only this file + request.json).")
    a("*")
    a("* Every swept point is an independent parallel instance (own rbl/ref/latch/cells), so a")
    a("* corner needs ONE tran. Instance kinds:")
    a("*   st_*     stage-only: rbl precharged to VREF+d, no cells (offset / resolution of the latch)")
    a("*   cell1_*  end-to-end: 4-row column, all four SN pre-read at the stated level (stored '1')")
    a("*   cell0_*  same, stored '0' level")
    a("* Naming r<mV> = reference offset below the precharge level (VREF = VRBL - r).")
    a("*")
    a("* ASSUMPTIONS (all labelled; none is a spec value): C_RBL, VRBL, 4-row column, sense instant,")
    a("* reference level, latch/footer/header sizes, ideal precharge switch, ideal drivers, ideal")
    a("* matched dummy load on the reference side, all four SN at one level, global corners only.")
    a("")
    a(f".param VDD     = {_fmt(VDD_V)}")
    a(f".param VRBL    = {_fmt(VRBL_V)}   $ ASSUMPTION (contract)")
    a(f".param TEDGE   = {_fmt(T_EDGE_S)}")
    a(f".param T_READ  = {_fmt(T_READ_S)}   $ select edge")
    a(f".param T_PGAP  = {_fmt(T_PRE_GAP_S)}   $ precharge released this long before T_READ")
    a(f".param T_EN    = {_fmt(T_EN_S)}   $ ASSUMPTION: latch enable = contract sense instant (T_READ+10n)")
    a(f".param C_RBL   = {_fmt(c_rbl_f)}   $ {c_rbl_label}")
    a(f".param C_SN    = {_fmt(c_sn_f)}   $ extracted-from-netlist (layout/gain_cell_2t.extract.parasitics.json)")
    a("")
    a("* ---- shared drivers (ideal) ----")
    a("vdd   vdd 0 dc {VDD}")
    a("vctl  ctl 0 pwl(0 {VDD} {T_READ-T_PGAP} {VDD} {T_READ-T_PGAP+TEDGE} 0)")
    a("ven   en  0 pwl(0 0 {T_EN} 0 {T_EN+TEDGE} {VDD})")
    a("venb  enb 0 pwl(0 {VDD} {T_EN} {VDD} {T_EN+TEDGE} 0)")
    a("vrwls rwl_sel 0 pwl(0 {VDD} {T_READ} {VDD} {T_READ+TEDGE} 0)")
    a("vrwld rwl_des 0 dc {VDD}")
    a("vpre  prea 0 dc {VRBL}")
    for dref in sorted({p["dref"] for p in pts}):
        a(f"vref_{round(dref * 1000):03d} pref_{round(dref * 1000):03d} 0 dc {_fmt(VRBL_V - dref)}   $ reference = VRBL - {_fmt(dref)} (ASSUMPTION)")
    a(".model swpre sw(vt=0.9 vh=0.1 ron=100 roff=1e12)")
    a("")
    ics: list[str] = []
    for p in pts:
        i = p["idx"]
        n = p["name"]
        rb, rf, vn, vp = f"rbl_{n}", f"ref_{n}", f"vn_{n}", f"vp_{n}"
        a(f"* ---- instance {i}: {n} ----")
        refbus = f"pref_{round(p['dref'] * 1000):03d}"
        if p["kind"] == "stage":
            va = VRBL_V - p["dref"] + p["d_mv"] * 1e-3
            a(f"vpa_{n} pa_{n} 0 dc {va:.6f}")
            a(f"spa_{n} pa_{n} {rb} ctl 0 swpre")
            ics.append(f"v({rb})={va:.6f}")
        else:
            a(f"spa_{n} prea {rb} ctl 0 swpre")
            ics.append(f"v({rb})={_fmt(VRBL_V)}")
            for r in range(N_ROWS):
                sn = f"sn_{n}_{r}"
                rwl = "rwl_sel" if r == 0 else "rwl_des"
                a(f"XMWR_{n}_{r} {sn} 0 0 0 {wr_m} {wr_p}")
                a(f"XMRD_{n}_{r} {rb} {sn} {rwl} 0 {rd_m} {rd_p}")
                a(f"csn_{n}_{r} {sn} 0 {{C_SN}}")
                ics.append(f"v({sn})={_fmt(p['sn'])}")
        a(f"crbl_{n} {rb} 0 {{C_RBL}}")
        a(f"spr_{n} {refbus} {rf} ctl 0 swpre")
        a(f"cref_{n} {rf} 0 {{C_RBL}}   $ ASSUMPTION: ideal matched dummy load")
        ics.append(f"v({rf})={VRBL_V - p['dref']:.6f}")
        ln, lp, fo, he = LATCH_N, LATCH_P, FOOTER, HEADER
        a(f"XMN1_{n} {rb} {rf} {vn} 0 {ln[0]} {dev_params(ln[1], ln[2])}")
        a(f"XMN2_{n} {rf} {rb} {vn} 0 {ln[0]} {dev_params(ln[1], ln[2])}")
        a(f"XMP1_{n} {rb} {rf} {vp} vdd {lp[0]} {dev_params(lp[1], lp[2])}")
        a(f"XMP2_{n} {rf} {rb} {vp} vdd {lp[0]} {dev_params(lp[1], lp[2])}")
        a(f"XMNF_{n} {vn} en 0 0 {fo[0]} {dev_params(fo[1], fo[2])}")
        a(f"XMPH_{n} {vp} enb vdd vdd {he[0]} {dev_params(he[1], he[2])}")
        # settle values of the floating tail nodes (ASSUMPTION: ~ source-follower levels, then settle in idle time)
        ics.append(f"v({vn})=0.45")
        ics.append(f"v({vp})=1.35")
        a(f"bd_{n} d_{n} 0 v=v({rb})-v({rf})")
        a(f"bdabs_{n} dabs_{n} 0 v=abs(v({rb})-v({rf}))")
        a("")
    a("* initial conditions (tran uic): precharged rails, stored levels, tail nodes")
    for k in range(0, len(ics), 6):
        a(".ic " + " ".join(ics[k:k + 6]))
    a("")
    return "\n".join(L)


def build_request(variant: str | None = None) -> dict:
    meas = []
    t_en_ns = _fmt(T_EN_S * 1e9)
    t_stop_ns = _fmt(T_STOP_S * 1e9)
    for p in instances():
        n = p["name"]
        meas += [
            {"name": f"din_{n}", "unit": "V",
             "spice": f".meas tran din_{n} FIND v(d_{n}) AT={t_en_ns}n"},
            {"name": f"dend_{n}", "unit": "V",
             "spice": f".meas tran dend_{n} FIND v(d_{n}) AT={t_stop_ns}n"},
            {"name": f"tdec_{n}", "unit": "s",
             "spice": f".meas tran tdec_{n} TRIG v(en) VAL=0.9 RISE=1 TARG v(dabs_{n}) VAL=0.9 RISE=1"},
        ]
    return {
        "netlist": variant_paths(variant)[0].name,
        "engine": "ngspice",
        "backend": "batch",
        "models": {"pdk": "sky130A", "lib": "libs.tech/combined/sky130.lib.spice"},
        "corners": {"process": PROCESS_CORNERS, "temperature_c": TEMPS_C},
        "analysis": {"kind": "tran", "args": f"10p {t_stop_ns}n 0 50p uic"},
        "measurements": meas,
        "options": {"timeout_s": 900, "keep_artifacts": False, "waveforms": False},
    }


def render(variant: str | None = None) -> tuple[str, str]:
    c_sn_ff, _prov = load_extracted_c_sn(EXTRACT_JSON, "sn")
    net = build_netlist(c_sn_ff * 1e-15, variant)
    req = json.dumps(build_request(variant), indent=1) + "\n"
    return net, req


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--variant", choices=sorted(variants()), default=None,
                    help="issue #88 variant (default: the unchanged issue #60 deck)")
    a = ap.parse_args(argv)
    net, req = render(a.variant)
    net_path, req_path = variant_paths(a.variant)
    net_path.write_text(net)
    req_path.write_text(req)
    print(f"wrote {net_path.name} ({len(instances())} instances) and {req_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
