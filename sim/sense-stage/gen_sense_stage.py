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

This module is also the single source of the deck elements every sense-path
generator shares (issue #456): ``sn_mv_tag``, ``emit_column_cells``,
``emit_sense_latch``, ``ic_lines`` and ``sense_stage_meas``. Each generator's
committed deck pins their output byte for byte.

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
sys.path.insert(0, str(REPO / "sim"))
from _evidence_common import VDD_V, fmt_g6, parse_cards  # noqa: E402
from klt_request import build_request as klt_request  # noqa: E402

NETLIST_PATH = HERE / "sense_stage.spice"
REQUEST_PATH = HERE / "request.json"
DESIGN = REPO / "design"
DESIGN_NETLIST = DESIGN / "gain_cell_2t.spice"
LATCH_SPICE = DESIGN / "sense_latch.spice"
EXTRACT_JSON = REPO / "layout" / "gain_cell_2t.extract.parasitics.json"

# ---- scope: restricted range of the PROPOSED record (nothing outside it) ----
PROCESS_CORNERS = ["tt", "ss", "ff", "sf", "fs"]
TEMPS_C = [27, 125]            # 27 C = restricted cold bound; 125 C = worst-case retention corner

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
# The latch/footer/header device cards are emitted from the schematic-derived
# design/sense_latch.spice via parse_cards() (issue #293), so the simulated
# geometry (incl. nrd/nrs/sa/sb/sd) is the design netlist's, never retyped.
# Sizes there are first-pass choices: latch N 1.0/0.15, P 2.0/0.15,
# footer 2.0/0.15, header 4.0/0.15 um.

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


PRE244_C_RBL_FF = 0.859179   # extracted_4row_worst_total_ff before PR #248 (issue #244) regenerated the layout


def variants() -> dict:
    """Variant registry. ``*_p244_l293`` are generated from the current layout summary.

    ``legacy`` entries are committed history (``sim/`` is append-only): their decks
    and results are frozen and no longer regenerated. The un-suffixed ids are the
    2026-10-11 pre-#244 variants and carry the frozen pre-#244 C_RBL; the ``*_p244``
    ids are the 2026-10-29 post-#244 variants, simulated on the pre-#293 latch
    (retyped geometry without nrd/nrs/sa/sb/sd). Both keep their summaries
    reproducible. The ``*_p244_l293`` ids are the same post-#244 C_RBL on the
    schematic-derived latch of issue #293; their decks are generated and committed
    but not yet simulated.
    """
    ext = extracted_c_rbl_ff() * 1e-15
    lab = ("EXTRACTED-4-ROW (layout/gain_cell_2t_array.parasitics.summary.json "
           "comparison.c_rbl.extracted_4row_worst_total_ff; N_rows = 4 is a STUDY-ASSUMPTION)")
    lab_old = lab   # unchanged text: the frozen summaries record exactly this label
    old = PRE244_C_RBL_FF * 1e-15
    reg = {
        "crbl_ext4row": dict(c_rbl_f=old, c_rbl_label=lab_old, card="design", legacy=True,
                             c_rbl_source_ff=PRE244_C_RBL_FF),
        "crbl_2f": dict(c_rbl_f=2e-15, c_rbl_label="ASSUMPTION (mid-point, not extracted)", card="design",
                        legacy=True, c_rbl_source_ff=PRE244_C_RBL_FF),
        "crbl_ext4row_layoutcard": dict(c_rbl_f=old, c_rbl_label=lab_old, card="layout", legacy=True,
                                        c_rbl_source_ff=PRE244_C_RBL_FF),
        "crbl_ext4row_p244": dict(c_rbl_f=ext, c_rbl_label=lab, card="design", legacy=True,
                                  c_rbl_source_ff=extracted_c_rbl_ff()),
        "crbl_2f_p244": dict(c_rbl_f=2e-15, c_rbl_label="ASSUMPTION (mid-point, not extracted)", card="design",
                             legacy=True, c_rbl_source_ff=extracted_c_rbl_ff()),
        "crbl_ext4row_layoutcard_p244": dict(c_rbl_f=ext, c_rbl_label=lab, card="layout", legacy=True,
                                             c_rbl_source_ff=extracted_c_rbl_ff()),
    }
    for k in [k for k in reg if k.endswith("_p244")]:
        reg[k + "_l293"] = {**reg[k], "legacy": False}
    return reg


def current_variants() -> dict:
    return {k: v for k, v in variants().items() if not v["legacy"]}


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


def sn_mv_tag(sn_v: float) -> str:
    """Instance-name tag of a storage-node level in mV: ``n100`` for -0.10 V, ``0900`` for 0.90 V."""
    return ("n%03d" % round(-sn_v * 1000)) if sn_v < 0 else ("%04d" % round(sn_v * 1000))


def _row_net(spec, r: int) -> str:
    """The net row ``r``'s control connects to under ``spec``: a ``(selected, deselected)`` pair -- row 0
    selected, the read-select convention of every deck here -- or a callable of the row index for the
    decks with a per-row write wordline / select (aged-read, closed-loop)."""
    if callable(spec):
        return spec(r)
    return spec[0] if r == 0 else spec[1]


def emit_column_cells(a, ics: list[str], name: str, rbl: str, wbl: str, wr_card: tuple[str, str],
                      rd_card: tuple[str, str], *, rwl, wwl=("0", "0"), sn_ic, n_rows: int = N_ROWS) -> None:
    """Emit the ``n_rows``-row gain-cell column of instance ``name``: per row ``r`` the write device
    ``XMWR_<name>_<r>`` (drain on the storage node, gate on the row's write wordline, source on
    ``wbl``), the read device ``XMRD_<name>_<r>`` (drain on ``rbl``, gate on the row's read wordline)
    and ``csn_<name>_<r>``, then append ``v(sn_<name>_<r>)=`` to the initial conditions ``ics``.

    ``wr_card`` / ``rd_card`` are the ``(model, params)`` bitcell cards; each deck passes its own
    (``design_cell_cards()`` or a ``parse_cards`` tuple, whose spacing differs). ``wbl`` = ``"0"`` with
    ``wwl`` left at its default leaves the write device off (the sense-stage decks). ``rwl`` / ``wwl``:
    see ``_row_net``. ``sn_ic(r)`` is the pre-read storage-node level (V) of row ``r``.
    """
    (wr_m, wr_p), (rd_m, rd_p) = wr_card, rd_card
    for r in range(n_rows):
        sn = f"sn_{name}_{r}"
        a(f"XMWR_{name}_{r} {sn} {_row_net(wwl, r)} {wbl} 0 {wr_m} {wr_p}")
        a(f"XMRD_{name}_{r} {rbl} {sn} {_row_net(rwl, r)} 0 {rd_m} {rd_p}")
        a(f"csn_{name}_{r} {sn} 0 {{C_SN}}")
        ics.append(f"v({sn})={fmt_g6(sn_ic(r))}")


def emit_sense_latch(a, ics: list[str], name: str, rbl: str, ref: str, latch: dict, *, en: str = "en",
                     enb: str = "enb", bdabs: bool = True) -> None:
    """Emit the sense latch of instance ``name``: the ``design/sense_latch.spice`` cards ``latch`` (via
    ``parse_cards``, issue #293) with its inputs on ``rbl`` / ``ref`` and its enable on ``en`` /
    ``enb``; the tail-node initial conditions appended to ``ics`` (settle values of the floating tail
    nodes; ASSUMPTION: ~ source-follower levels, then settle in idle time); and the differential
    probe source ``bd_<name>`` on ``d_<name>``, plus ``bdabs_<name>`` on ``dabs_<name>`` when ``bdabs``.
    """
    vn, vp = f"vn_{name}", f"vp_{name}"
    lmap = {"rbl": rbl, "ref": ref, "vn": vn, "vp": vp, "en": en, "enb": enb,
            "vdd": "vdd", "GND": "0", "0": "0"}
    for dev, (nets, model, params) in latch.items():
        a(f"X{dev}_{name} {' '.join(lmap[x] for x in nets)} {model} {params}")
    ics.append(f"v({vn})=0.45")
    ics.append(f"v({vp})=1.35")
    a(f"bd_{name} d_{name} 0 v=v({rbl})-v({ref})")
    if bdabs:
        a(f"bdabs_{name} dabs_{name} 0 v=abs(v({rbl})-v({ref}))")


def ic_lines(ics: list[str], per_line: int = 6) -> list[str]:
    """``.ic`` cards (``tran uic``): ``per_line`` node assignments per card."""
    return [".ic " + " ".join(ics[k:k + per_line]) for k in range(0, len(ics), per_line)]


def sense_stage_meas(names: list[str], *, t_en_s: float = T_EN_S, t_stop_s: float = T_STOP_S) -> list[dict]:
    """The sense-stage measurement set per instance in ``names``: ``din`` (differential at the enable
    instant ``t_en_s``), ``dend`` (at ``t_stop_s``) and ``tdec`` (shared ``en`` rise -> |differential|
    0.9 V)."""
    t_en_ns = fmt_g6(t_en_s * 1e9)
    t_stop_ns = fmt_g6(t_stop_s * 1e9)
    meas: list[dict] = []
    for n in names:
        meas += [
            {"name": f"din_{n}", "unit": "V",
             "spice": f".meas tran din_{n} FIND v(d_{n}) AT={t_en_ns}n"},
            {"name": f"dend_{n}", "unit": "V",
             "spice": f".meas tran dend_{n} FIND v(d_{n}) AT={t_stop_ns}n"},
            {"name": f"tdec_{n}", "unit": "s",
             "spice": f".meas tran tdec_{n} TRIG v(en) VAL=0.9 RISE=1 TARG v(dabs_{n}) VAL=0.9 RISE=1"},
        ]
    return meas


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
            p["name"] = f"{p['kind']}_r{round(p['dref'] * 1000):03d}_{sn_mv_tag(p['sn'])}"
        p["idx"] = i
    return pts


def build_netlist(c_sn_f: float, variant: str | None = None) -> str:
    (wr_m, wr_p), (rd_m, rd_p) = design_cell_cards()
    c_rbl_f, c_rbl_label = C_RBL_F, "ASSUMPTION (contract; not extracted)"
    if variant is not None:
        v = variants()[variant]
        if v["legacy"]:
            raise ValueError(f"variant {variant!r} is frozen pre-#244 history; its deck is not regenerated")
        c_rbl_f, c_rbl_label = v["c_rbl_f"], v["c_rbl_label"]
        if v["card"] == "layout":
            wr_p, rd_p = layout_card(wr_p), layout_card(rd_p)
    latch = parse_cards(LATCH_SPICE)
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
    a(f".param VDD     = {fmt_g6(VDD_V)}")
    a(f".param VRBL    = {fmt_g6(VRBL_V)}   $ ASSUMPTION (contract)")
    a(f".param TEDGE   = {fmt_g6(T_EDGE_S)}")
    a(f".param T_READ  = {fmt_g6(T_READ_S)}   $ select edge")
    a(f".param T_PGAP  = {fmt_g6(T_PRE_GAP_S)}   $ precharge released this long before T_READ")
    a(f".param T_EN    = {fmt_g6(T_EN_S)}   $ ASSUMPTION: latch enable = contract sense instant (T_READ+10n)")
    a(f".param C_RBL   = {fmt_g6(c_rbl_f)}   $ {c_rbl_label}")
    a(f".param C_SN    = {fmt_g6(c_sn_f)}   $ extracted-from-netlist (layout/gain_cell_2t.extract.parasitics.json)")
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
        a(f"vref_{round(dref * 1000):03d} pref_{round(dref * 1000):03d} 0 dc {fmt_g6(VRBL_V - dref)}   $ reference = VRBL - {fmt_g6(dref)} (ASSUMPTION)")
    a(".model swpre sw(vt=0.9 vh=0.1 ron=100 roff=1e12)")
    a("")
    ics: list[str] = []
    for p in pts:
        i = p["idx"]
        n = p["name"]
        rb, rf = f"rbl_{n}", f"ref_{n}"
        a(f"* ---- instance {i}: {n} ----")
        refbus = f"pref_{round(p['dref'] * 1000):03d}"
        if p["kind"] == "stage":
            va = VRBL_V - p["dref"] + p["d_mv"] * 1e-3
            a(f"vpa_{n} pa_{n} 0 dc {va:.6f}")
            a(f"spa_{n} pa_{n} {rb} ctl 0 swpre")
            ics.append(f"v({rb})={va:.6f}")
        else:
            a(f"spa_{n} prea {rb} ctl 0 swpre")
            ics.append(f"v({rb})={fmt_g6(VRBL_V)}")
            emit_column_cells(a, ics, n, rb, "0", (wr_m, wr_p), (rd_m, rd_p),
                              rwl=("rwl_sel", "rwl_des"), sn_ic=lambda _r: p["sn"])
        a(f"crbl_{n} {rb} 0 {{C_RBL}}")
        a(f"spr_{n} {refbus} {rf} ctl 0 swpre")
        a(f"cref_{n} {rf} 0 {{C_RBL}}   $ ASSUMPTION: ideal matched dummy load")
        ics.append(f"v({rf})={VRBL_V - p['dref']:.6f}")
        emit_sense_latch(a, ics, n, rb, rf, latch)
        a("")
    a("* initial conditions (tran uic): precharged rails, stored levels, tail nodes")
    L += ic_lines(ics)
    a("")
    return "\n".join(L)


def build_request(variant: str | None = None) -> dict:
    return klt_request(variant_paths(variant)[0].name,
                       {"process": PROCESS_CORNERS, "temperature_c": TEMPS_C},
                       f"10p {fmt_g6(T_STOP_S * 1e9)}n 0 50p uic",
                       sense_stage_meas([p["name"] for p in instances()]), 900)


def render(variant: str | None = None) -> tuple[str, str]:
    c_sn_ff, _prov = load_extracted_c_sn(EXTRACT_JSON, "sn")
    net = build_netlist(c_sn_ff * 1e-15, variant)
    req = json.dumps(build_request(variant), indent=1) + "\n"
    return net, req


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--variant", choices=sorted(current_variants()), default=None,
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
