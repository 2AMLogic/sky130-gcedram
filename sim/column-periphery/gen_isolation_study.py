#!/usr/bin/env python3
"""Generate the isolation-gate / write-driver study decks and `klt sim` requests (issue #117).

Follow-up to ``gen_column_periphery.py`` (issue #114). Stdlib only. Imports the
timeline, bias, ASSUMPTIONs and card parsers from it so the two cannot drift.
Writes, next to this file (the #114 files are never touched):

* ``isolation_study.spice`` / ``request_isolation.json``     global-corner sweep
* ``isolation_mc.spice``    / ``request_isolation_mc.json``  Monte Carlo (mismatch)

Every instance is a 4-row column (row 0 written, then read, latch enabled), as
in #114. Instance kinds:

* ``ideal``  existing ideal sources, latch directly on rbl (the #114 control).
* ``real``   the designed slice with per-instance overrides:
             ``wn``/``wp``  isolation nfet / pfet width (um; 0 = device omitted)
             ``dscale``     reference-side dummy gate width = dscale x main gate
             ``lead``       isolation gates close this long before the latch enable
             ``drv``        {device: W um} overrides of the write-driver devices
             ``csb``        extra capacitance (F) on each of sbl and sref

Why the isolation gates are *closed* before the enable: ``sel`` falls at
``T_EN - lead`` (see ``gen_column_periphery.py``); the latch then regenerates
on its own isolated input nodes. ``dpre`` is the latch-input difference just
before the gates start to close and ``din`` is the difference at the enable
instant, so ``din - dpre`` is the closing disturbance (charge injection plus
the signal still moving on rbl) and separates it from the read signal.

PROPOSED, NOT RATIFIED: the corner set is the restricted range of
``spec/operating-range-decision-PROPOSED.md`` (27 C and 125 C, five global
corners, VDD = 1.8 V); the Monte Carlo request uses the PDK ``_mm`` sections at
the four corners of ``sim/sense-mismatch`` (tt/27, fs/27, ss/125, sf/125).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gen_column_periphery as G  # noqa: E402

STUDY_NETLIST = HERE / "isolation_study.spice"
STUDY_REQUEST = HERE / "request_isolation.json"
MC_NETLIST = HERE / "isolation_mc.spice"
MC_REQUEST = HERE / "request_isolation_mc.json"

# ---- baseline (#114) values ----
WN0, WP0, LEAD0 = 1.0, 2.0, 0.5e-9

# ---- Monte Carlo scope: the four corners of sim/sense-mismatch ----
MC_CORNERS = ["tt_mm", "fs_mm", "ss_mm", "sf_mm"]
MC_EXCLUDE = [("tt_mm", 125), ("fs_mm", 125), ("ss_mm", 27), ("sf_mm", 27)]
MC_N = 40
MC_SEED = 2026101517
MC_REPLICAS = 4
# chosen point of the sweep (set from the recorded study; see README)
CHOSEN = "f00"


def set_width(params: str, w_um: float) -> str:
    """As gen_column_periphery.set_width but with 14 significant digits, the precision xschem
    writes (so a resized card equals the schematic-derived netlist byte for byte, e.g. nrd =
    0.29/0.42 = 0.69047619047619)."""
    ad, pd, nr = w_um * G.DIFF_UM, 2 * (w_um + G.DIFF_UM), G.DIFF_UM / w_um
    p = re.sub(r"\bW=\S+", f"W={w_um:.14g}", params)
    for k, v in (("ad", ad), ("as", ad), ("pd", pd), ("ps", pd), ("nrd", nr), ("nrs", nr)):
        p, n = re.subn(rf"\b{k}=\S+", f"{k}={v:.14g}", p)
        if n != 1:
            raise ValueError(f"set_width: expected exactly one {k}= in {params!r}")
    return p


def baseline_cards() -> dict[str, tuple[list[str], str, str]]:
    """The #114 slice device cards (frozen in gen_column_periphery.SLICE_114_CARDS). Not read from
    design/column_periphery.spice: that schematic is the *current* design (revised by this issue),
    and this study's baseline must stay the design #114 recorded."""
    return {k: (list(n), m, p) for k, (n, m, p) in G.SLICE_114_CARDS.items()}


def iso(tag, desc, wn=WN0, wp=WP0, dscale=1.0, lead=LEAD0, drv=None, csb=0.0,
        refpre="ideal", wpre=4.0, pdum=0.0, pedge=G.T_EDGE_S, crbl=None):
    """One real-slice variant. refpre: reference-side precharge, 'ideal' (the #114 testbench
    convention: ideal switch) or 'matched' (a copy of MPPRE on the reference node, as a
    dummy reference column would have). wpre: MPPRE width (um). pdum: dummy-switch pfet on rbl
    (drain = source = rbl, gate = the opposite-phase precharge), width = pdum x wpre (0 = none).
    pedge: precharge release edge time (s). crbl: array-side rbl capacitance (F); None = C_RBL."""
    return dict(tag=tag, desc=desc, wn=wn, wp=wp, dscale=dscale, lead=lead, drv=drv or {}, csb=csb,
                refpre=refpre, wpre=wpre, pdum=pdum, pedge=pedge, crbl=crbl)


# isolation-gate variants (both data values each).  i00 = the #114 design.
ISO_VARIANTS = [
    iso("i00", "baseline: TG nfet 1.0 / pfet 2.0, dummy 1x, lead 0.5 ns"),
    iso("i01", "lead 0.1 ns", lead=0.1e-9),
    iso("i02", "lead 1.0 ns", lead=1.0e-9),
    iso("i03", "lead 2.0 ns", lead=2.0e-9),
    iso("i04", "TG 0.5 / 1.0", wn=0.5, wp=1.0),
    iso("i05", "TG 0.42 / 0.42", wn=0.42, wp=0.42),
    iso("i06", "TG 0.42 / 0.84", wn=0.42, wp=0.84),
    iso("i07", "TG 2.0 / 4.0 (direction check)", wn=2.0, wp=4.0),
    iso("i08", "nfet only 1.0", wn=1.0, wp=0.0),
    iso("i09", "nfet only 0.42", wn=0.42, wp=0.0),
    iso("i10", "pfet only 1.0", wn=0.0, wp=1.0),
    iso("i11", "pfet only 0.5", wn=0.0, wp=0.5),
    iso("i12", "baseline TG, dummy 0.5x", dscale=0.5),
    iso("i13", "baseline TG, dummy 0.75x", dscale=0.75),
    iso("i14", "baseline TG, dummy 1.5x", dscale=1.5),
    iso("i15", "TG 0.42 / 0.84, +5 fF on sbl and sref", wn=0.42, wp=0.84, csb=5e-15),
]

# precharge-release variants (attribution + compensation), isolation at the #114 baseline
PRE_VARIANTS = [
    iso("p00", "ref-side precharge = matched copy of MPPRE", refpre="matched"),
    iso("p01", "matched ref precharge, MPPRE 2.0", refpre="matched", wpre=2.0),
    iso("p02", "ideal ref, MPPRE 2.0", wpre=2.0),
    iso("p03", "ideal ref, MPPRE 1.0", wpre=1.0),
    iso("p04", "ideal ref, dummy switch 0.5 x MPPRE", pdum=0.5),
    iso("p05", "ideal ref, dummy switch 0.25 x MPPRE", pdum=0.25),
    iso("p06", "ideal ref, release edge 0.5 ns", pedge=0.5e-9),
    iso("p07", "ideal ref, release edge 1.0 ns", pedge=1.0e-9),
    iso("p08", "matched ref precharge, release edge 0.5 ns", refpre="matched", pedge=0.5e-9),
]

# combined candidates: the low-capacitance isolation (nfet only 0.42) with the injection fixes
COMBO_VARIANTS = [
    iso("c00", "nfet-only 0.42, matched ref precharge", wn=0.42, wp=0.0, refpre="matched"),
    iso("c01", "nfet-only 0.42, matched ref, release edge 0.5 ns", wn=0.42, wp=0.0, refpre="matched", pedge=0.5e-9),
    iso("c02", "nfet-only 0.42, dummy switch 0.25 x MPPRE", wn=0.42, wp=0.0, pdum=0.25),
    iso("c03", "nfet-only 0.42, dummy switch 0.5 x MPPRE", wn=0.42, wp=0.0, pdum=0.5),
    iso("c04", "nfet-only 0.42, release edge 0.5 ns", wn=0.42, wp=0.0, pedge=0.5e-9),
    iso("c05", "nfet-only 0.42, MPPRE 3.0, matched ref", wn=0.42, wp=0.0, refpre="matched", wpre=3.0),
]

# the final design (schematic design/column_periphery.sch as updated by issue #117): low-capacitance
# nfet-only isolation, matched reference-side precharge (MPPRE = MPPREF = 5.0 um, the smallest swept width
# with >= 10 % precharge-settle margin at every corner), stiffer write-'0' pull-down
DRV_FINAL = {"MND1": 4.0, "MND2": 4.0, "MNI": 2.0}
FINAL = iso("f00", "FINAL: nfet-only 0.42 isolation, matched ref precharge 5.0, MND1/MND2 4.0, MNI 2.0",
            wn=0.42, wp=0.0, refpre="matched", wpre=5.0, drv=DRV_FINAL)
FINAL_VARIANTS = [
    iso("f01", "final with MPPRE = MPPREF 4.0", wn=0.42, wp=0.0, refpre="matched", wpre=4.0, drv=DRV_FINAL),
    iso("f02", "final with MPPRE = MPPREF 4.5", wn=0.42, wp=0.0, refpre="matched", wpre=4.5, drv=DRV_FINAL),
    iso("f03", "final with MPPRE = MPPREF 6.0", wn=0.42, wp=0.0, refpre="matched", wpre=6.0, drv=DRV_FINAL),
    iso("f04", "final with array-side rbl C = 6.26 fF (total 10 fF incl. the 3.74 fF fs/27 C periphery probe value; the 'C_RBL is the total' reading)",
        wn=0.42, wp=0.0, refpre="matched", wpre=5.0, drv=DRV_FINAL, crbl=6.26e-15),
]
# write-driver variants (data '0' only; isolation at baseline, irrelevant to sn)
DRV_VARIANTS = [
    iso("d00", "driver as #114 (control)"),
    iso("d01", "pull-down stack MND1/MND2 1.0", drv={"MND1": 1.0, "MND2": 1.0}),
    iso("d02", "pull-down stack MND1/MND2 2.0", drv={"MND1": 2.0, "MND2": 2.0}),
    iso("d03", "idle pull-down MNI 1.0", drv={"MNI": 1.0}),
    iso("d04", "MND1/MND2 2.0 + MNI 1.0", drv={"MND1": 2.0, "MND2": 2.0, "MNI": 1.0}),
    iso("d05", "MND1/MND2 4.0 + MNI 2.0", drv={"MND1": 4.0, "MND2": 4.0, "MNI": 2.0}),
    iso("d06", "MND1/MND2 8.0 + MNI 4.0", drv={"MND1": 8.0, "MND2": 8.0, "MNI": 4.0}),
    iso("d07", "MND1/MND2 4.0 + MNI 0.42 (idle clamp unchanged)", drv={"MND1": 4.0, "MND2": 4.0}),
]


def matched_copy(v):
    """The same isolation variant on a matched reference-side precharge ('m' tag)."""
    return dict(v, tag="m" + v["tag"][1:], desc=v["desc"] + " [matched ref precharge]", refpre="matched")


MATCHED_VARIANTS = [matched_copy(v) for v in ISO_VARIANTS]


def study_points() -> list[dict]:
    pts = []
    for d in (1, 0):
        pts.append(dict(name=f"ideal_w{d}", kind="ideal", data=d, tag="ideal"))
    for v in ISO_VARIANTS + MATCHED_VARIANTS + PRE_VARIANTS + COMBO_VARIANTS + [FINAL] + FINAL_VARIANTS:
        for d in (1, 0):
            pts.append(dict(v, name=f"{v['tag']}_w{d}", kind="real", data=d))
    for v in DRV_VARIANTS:
        pts.append(dict(v, name=f"{v['tag']}_w0", kind="real", data=0))
    pts += probe_points()
    for i, p in enumerate(pts):
        p["idx"] = i
    return pts


PROBE_TAGS = ["f00", "f03", "f01", "c04", "c03", "c05", "i00", "i04", "i05", "i06", "i07", "i08", "i09", "i10", "i11", "i15", "p02", "p03", "p04"]
I_PROBE_A = 0.1e-6
T_PROBE_1, T_PROBE_2 = 5e-9, 15e-9


def probe_points() -> list[dict]:
    """Capacitance probes: the periphery (precharge, isolation gate, optional dummy/hold cap) on an
    rbl node with no array load and no latch, gates idle (precharge off, isolation on), discharged
    by a constant current. C = I*dt/dV is the capacitance the periphery adds to rbl; the latch gate
    load is present in the ideal and the real column alike and is not part of it."""
    allv = {v["tag"]: v for v in ISO_VARIANTS + PRE_VARIANTS + COMBO_VARIANTS + [FINAL] + FINAL_VARIANTS}
    pts = []
    for t in PROBE_TAGS:
        pts.append(dict(allv[t], name=f"cp_{t}", kind="cprobe", data=1, probe="real"))
    return pts


def mc_points() -> list[dict]:
    chosen = FINAL
    base = next(v for v in ISO_VARIANTS if v["tag"] == "i00")
    pts = []
    for d in (1, 0):
        for k in range(MC_REPLICAS):
            pts.append(dict(name=f"ideal_w{d}_r{k}", kind="ideal", data=d, tag="ideal", rep=k))
            for v in (base, chosen):
                pts.append(dict(v, name=f"{v['tag']}_w{d}_r{k}", kind="real", data=d, rep=k))
    for i, p in enumerate(pts):
        p["idx"] = i
    return pts


def t_iso(p: dict) -> float:
    return G.T_EN_S - p["lead"]


def build_netlist(points: list[dict], c_sn_f: float, title: str) -> str:
    cell = G.parse_cards(G.DESIGN / "gain_cell_2t.spice")
    latch = G.parse_cards(G.DESIGN / "sense_latch.spice")
    per = baseline_cards()
    wr_m, wr_p = cell["M_WR"][1], cell["M_WR"][2]
    rd_m, rd_p = cell["M_RD"][1], cell["M_RD"][2]
    t_pre_rel = G.T_READ_S - G.T_PRE_GAP_S
    fm = G._fmt
    L: list[str] = []
    a = L.append
    a(f"* {title} -- GENERATED by gen_isolation_study.py (issue #117); do not edit by hand.")
    a("*")
    a("* Follow-up to sim/column-periphery (issue #114). PROPOSED/UNRATIFIED SCOPE: corners from")
    a("* spec/operating-range-decision-PROPOSED.md (27 C and 125 C only). Inputs follow")
    a("* sim/loaded-column/cold-corner/SENSE_INPUT_CONTRACT.md (baseline column).")
    a("* CIRCUIT BODY for `klt sim`: no .control/.end; PDK .lib/.temp cards are appended per corner.")
    a("*")
    a("* Instance kinds: ideal_w<d> = existing ideal sources (the #114 control); <tag>_w<d> = designed")
    a("* slice with the per-instance overrides listed in the README; d = data written to row 0.")
    a("* Per-instance isolation sources vs_<name>/vsb_<name> close the gates `lead` before the enable.")
    a("*")
    a("* ASSUMPTIONS (labelled; none is a spec value): C_RBL, C_WBL, VRBL, vpre rail an ideal 0.9 V")
    a("* source, 4-row column, all four SN at one level before the write except the written row,")
    a("* sense instant, reference level, ideal reference-side precharge and matched dummy load, ideal")
    a("* digital control edges (100 ps). sbl/sref carry only device parasitics unless csb is set.")
    a("")
    a(f".param VDD     = {fm(G.VDD_V)}")
    a(f".param VRBL    = {fm(G.VRBL_V)}   $ ASSUMPTION (contract)")
    a(f".param VREF    = {fm(G.VRBL_V - G.DREF_V)}   $ ASSUMPTION: VRBL - 0.1 V (as sense-stage)")
    a(f".param TEDGE   = {fm(G.T_EDGE_S)}")
    a(f".param C_RBL   = {fm(G.C_RBL_F)}   $ ASSUMPTION (contract; not extracted)")
    a(f".param C_WBL   = {fm(G.C_WBL_F)}   $ ASSUMPTION (not extracted)")
    a(f".param C_SN    = {fm(c_sn_f)}   $ extracted-from-netlist (layout/gain_cell_2t.extract.parasitics.json)")
    a("")
    a("* ---- shared control (ideal digital edges) ----")
    a("vdd   vdd 0 dc {VDD}")
    e, te = fm(G.T_PRE_ON_S), fm(G.T_PRE_ON_S + G.T_EDGE_S)
    a(f"vpca  pca 0 pwl(0 0 {e} 0 {te} {{VDD}} {fm(t_pre_rel)} {{VDD}} {fm(t_pre_rel + G.T_EDGE_S)} 0)")
    a(f"vpcb  pcb 0 pwl(0 {{VDD}} {e} {{VDD}} {te} 0 {fm(t_pre_rel)} 0 {fm(t_pre_rel + G.T_EDGE_S)} {{VDD}})")
    a(f"vwen  wen 0 pwl(0 0 {fm(G.T_WBL_ON_S)} 0 {fm(G.T_WBL_ON_S + G.T_EDGE_S)} {{VDD}} {fm(G.T_WBL_OFF_S)} {{VDD}} {fm(G.T_WBL_OFF_S + G.T_EDGE_S)} 0)")
    a(f"vwenb wenb 0 pwl(0 {{VDD}} {fm(G.T_WBL_ON_S)} {{VDD}} {fm(G.T_WBL_ON_S + G.T_EDGE_S)} 0 {fm(G.T_WBL_OFF_S)} 0 {fm(G.T_WBL_OFF_S + G.T_EDGE_S)} {{VDD}})")
    a("vdinb1 dinb1 0 dc 0          $ data '1': wbl = NOT dinb = VDD")
    a("vdinb0 dinb0 0 dc {VDD}      $ data '0'")
    a(f"vwl   wl 0 pwl(0 0 {fm(G.T_WL_ON_S)} 0 {fm(G.T_WL_ON_S + G.T_EDGE_S)} {{VDD}} {fm(G.T_WL_OFF_S)} {{VDD}} {fm(G.T_WL_OFF_S + G.T_EDGE_S)} 0)")
    a(f"vrwls rwl_sel 0 pwl(0 {{VDD}} {fm(G.T_READ_S)} {{VDD}} {fm(G.T_READ_S + G.T_EDGE_S)} 0)")
    a("vrwld rwl_des 0 dc {VDD}")
    a(f"ven   en  0 pwl(0 0 {fm(G.T_EN_S)} 0 {fm(G.T_EN_S + G.T_EDGE_S)} {{VDD}})")
    a(f"venb  enb 0 pwl(0 {{VDD}} {fm(G.T_EN_S)} {{VDD}} {fm(G.T_EN_S + G.T_EDGE_S)} 0)")
    a("vprea prea 0 dc {VRBL}       $ ASSUMPTION: ideal 0.9 V precharge rail")
    a("vpref pref 0 dc {VREF}")
    a(".model swpre sw(vt=0.9 vh=0.1 ron=100 roff=1e12)")
    # per-release-edge precharge pairs for the real instances (the ideal switches keep pca/pcb)
    for ped in sorted({round(p["pedge"] * 1e12) for p in points if p["kind"] == "real"}):
        tr = ped * 1e-12
        a(f"vpca_{ped} pca_{ped} 0 pwl(0 0 {e} 0 {te} {{VDD}} {fm(t_pre_rel)} {{VDD}} {fm(t_pre_rel + tr)} 0)")
        a(f"vpcb_{ped} pcb_{ped} 0 pwl(0 {{VDD}} {e} {{VDD}} {te} 0 {fm(t_pre_rel)} 0 {fm(t_pre_rel + tr)} {{VDD}})")
    # distinct isolation edge times (one source pair per lead value)
    leads = sorted({round(t_iso(p) * 1e12) for p in points if p["kind"] == "real"})
    for ti in leads:
        t = ti * 1e-12
        a(f"vsel_{ti}  sel_{ti}  0 pwl(0 {{VDD}} {fm(t)} {{VDD}} {fm(t + G.T_EDGE_S)} 0)")
        a(f"vselb_{ti} selb_{ti} 0 pwl(0 0 {fm(t)} 0 {fm(t + G.T_EDGE_S)} {{VDD}})")
    a("")
    ics: list[str] = []
    for p in points:
        n, d, kind = p["name"], p["data"], p["kind"]
        rb, rf, wb = f"rbl_{n}", f"ref_{n}", f"wbl_{n}"
        vn, vp = f"vn_{n}", f"vp_{n}"
        if kind == "cprobe":
            sbl = f"sbl_{n}"
            a(f"* ---- instance {p['idx']}: {n} (capacitance probe, no array load) ----")
            a(f"icp_{n} {rb} 0 dc {fm(I_PROBE_A)}")
            ics += [f"v({rb})={fm(G.VRBL_V)}", f"v({sbl})={fm(G.VRBL_V)}"]
            if True:
                pw = {"MNS": p["wn"], "MPS": p["wp"], "MPPRE": p["wpre"]}
                nm = {"rbl": rb, "sbl": sbl, "pre_b": "vdd", "vpre": "prea", "sel": "vdd", "selb": "0", "GND": "0", "vdd": "vdd"}
                for dev in ("MPPRE", "MNS", "MPS"):
                    nets, model, params = per[dev]
                    if pw[dev] <= 0:
                        continue
                    if abs(pw[dev] - float(params.split("W=")[1].split()[0])) > 1e-12:
                        params = set_width(params, pw[dev])
                    a(f"X{dev}_{n} {' '.join(nm[x] for x in nets)} {model} {params}")
                if p["pdum"] > 0:
                    a(f"XMPDUM_{n} {rb} vdd {rb} prea {per['MPPRE'][1]} {set_width(per['MPPRE'][2], p['pdum'] * p['wpre'])}")
                if p["csb"] > 0:
                    a(f"csb_{n} {sbl} 0 {fm(p['csb'])}")
            a("")
            continue
        a(f"* ---- instance {p['idx']}: {n}" + (f" ({p['desc']})" if kind == "real" else "") + " ----")
        for r in range(G.N_ROWS):
            sn = f"sn_{n}_{r}"
            rwl = "rwl_sel" if r == 0 else "rwl_des"
            gate = "wl" if r == 0 else "0"
            a(f"XMWR_{n}_{r} {sn} {gate} {wb} 0 {wr_m} {wr_p}")
            a(f"XMRD_{n}_{r} {rb} {sn} {rwl} 0 {rd_m} {rd_p}")
            a(f"csn_{n}_{r} {sn} 0 {{C_SN}}")
            if r == 0:
                ics.append(f"v({sn})={fm(0.0 if d == 1 else G.SN_HOLD1_V)}")
            else:
                ics.append(f"v({sn})={fm(G.SN_HOLD1_V if d == 1 else 0.0)}")
        a(f"crbl_{n} {rb} 0 " + (fm(p["crbl"]) if p.get("crbl") else "{C_RBL}"))
        a(f"cwbl_{n} {wb} 0 {{C_WBL}}")
        a(f"cref_{n} {rf} 0 {{C_RBL}}   $ ASSUMPTION: ideal matched dummy load")
        if kind == "ideal" or p["refpre"] == "ideal":
            a(f"spr_{n} pref {rf} pca 0 swpre   $ reference-side precharge: ideal switch (#114 convention)")
        ics += [f"v({rb})=0", f"v({rf})={fm(G.VRBL_V - G.DREF_V)}", f"v({wb})=0"]
        if kind == "ideal":
            sbl, sref = rb, rf
            a(f"spa_{n} prea {rb} pca 0 swpre   $ existing ideal precharge switch")
            lvl = "{VDD}" if d == 1 else "0"
            a(f"vwbl_{n} {wb} 0 pwl(0 0 {fm(G.T_WBL_ON_S)} 0 {fm(G.T_WBL_ON_S + G.T_EDGE_S)} {lvl} "
              f"{fm(G.T_WBL_OFF_S)} {lvl} {fm(G.T_WBL_OFF_S + G.T_EDGE_S)} 0)   $ ideal write source")
        else:
            sbl, sref = f"sbl_{n}", f"sref_{n}"
            ti = round(t_iso(p) * 1e12)
            ped = round(p["pedge"] * 1e12)
            netmap = {"rbl": rb, "sbl": sbl, "ref": rf, "sref": sref, "wbl": wb,
                      "pre_b": f"pcb_{ped}", "vpre": "prea", "dinb": f"dinb{d}",
                      "wen": "wen", "wenb": "wenb", "sel": f"sel_{ti}", "selb": f"selb_{ti}",
                      "vdd": "vdd", "GND": "0", "0": "0", "vref": "pref"}
            width = {"MNS": p["wn"], "MPS": p["wp"],
                     "MNSR": p["wn"] * p["dscale"], "MPSR": p["wp"] * p["dscale"], "MPPRE": p["wpre"],
                     **p["drv"]}
            for dev, (nets, model, params) in per.items():
                if dev in width:
                    if width[dev] <= 0:
                        continue  # device omitted
                    if abs(width[dev] - float(params.split("W=")[1].split()[0])) > 1e-12:
                        params = set_width(params, width[dev])
                nn = [netmap.get(x, f"{x}_{n}") for x in nets]
                a(f"X{dev}_{n} {' '.join(nn)} {model} {params}")
            pre_params = per["MPPRE"][2]
            if abs(p["wpre"] - 4.0) > 1e-12:
                pre_params = set_width(pre_params, p["wpre"])
            if p["refpre"] == "matched":
                a(f"XMPPREF_{n} {rf} pcb_{ped} pref pref {per['MPPRE'][1]} {pre_params}   $ reference-side precharge: copy of MPPRE")
            if p["pdum"] > 0:
                a(f"XMPDUM_{n} {rb} pca_{ped} {rb} prea {per['MPPRE'][1]} {set_width(per['MPPRE'][2], p['pdum'] * p['wpre'])}"
                  "   $ STUDY option: dummy switch, opposite-phase gate")
            if p["csb"] > 0:
                a(f"csb_{n} {sbl} 0 {fm(p['csb'])}   $ STUDY option: extra latch-input hold capacitance")
                a(f"csr_{n} {sref} 0 {fm(p['csb'])}")
            ics += [f"v({sbl})=0", f"v({sref})={fm(G.VRBL_V - G.DREF_V)}"]
        lmap = {"rbl": sbl, "ref": sref, "en": "en", "enb": "enb", "vdd": "vdd", "vn": vn, "vp": vp, "GND": "0", "0": "0"}
        for dev, (nets, model, params) in latch.items():
            a(f"X{dev}_{n} {' '.join(lmap[x] for x in nets)} {model} {params}")
        ics += [f"v({vn})=0.45", f"v({vp})=1.35"]
        a(f"bd_{n} d_{n} 0 v=v({sbl})-v({sref})")
        a(f"bdabs_{n} dabs_{n} 0 v=abs(v({sbl})-v({sref}))")
        a("")
    a("* initial conditions (tran uic): rbl fully discharged, stored levels, tail nodes")
    for k in range(0, len(ics), 6):
        a(".ic " + " ".join(ics[k:k + 6]))
    a("")
    return "\n".join(L)


def build_request(points: list[dict], netlist: str, mc: bool) -> dict:
    meas = []
    f = lambda t: G._fmt(t * 1e9)
    for p in points:
        n = p["name"]
        if p["kind"] == "cprobe":
            for k, t in (("1", T_PROBE_1), ("2", T_PROBE_2)):
                meas.append({"name": f"vcp{k}_{n}", "unit": "V",
                             "spice": f".meas tran vcp{k}_{n} FIND v(rbl_{n}) AT={f(t)}n"})
            continue
        meas += [
            {"name": f"sn_{n}", "unit": "V",
             "spice": f".meas tran sn_{n} FIND v(sn_{n}_0) AT={f(G.T_WRCHK_S)}n"},
            {"name": f"snmin_{n}", "unit": "V",
             "spice": f".meas tran snmin_{n} MIN v(sn_{n}_0) FROM={f(G.T_WL_OFF_S)}n TO={f(G.T_WRCHK_S)}n"},
            {"name": f"din_{n}", "unit": "V",
             "spice": f".meas tran din_{n} FIND v(d_{n}) AT={f(G.T_EN_S)}n"},
            {"name": f"dend_{n}", "unit": "V",
             "spice": f".meas tran dend_{n} FIND v(d_{n}) AT={f(G.T_STOP_S)}n"},
            {"name": f"tdec_{n}", "unit": "s",
             "spice": f".meas tran tdec_{n} WHEN v(dabs_{n})=0.9 RISE=1 TD={f(G.T_EN_S)}n"},
        ]
        meas += [
            {"name": f"tpre_{n}", "unit": "s",
             "spice": f".meas tran tpre_{n} WHEN v(rbl_{n})={G._fmt(G.VRBL_V - G.SETTLE_V)} RISE=1"},
            {"name": f"vrel_{n}", "unit": "V",
             "spice": f".meas tran vrel_{n} FIND v(rbl_{n}) AT={f(G.T_READ_S - G.T_PRE_GAP_S)}n"},
        ]
        meas.append({"name": f"dpost_{n}", "unit": "V",
                     "spice": f".meas tran dpost_{n} FIND v(rbl_{n}) AT={f(G.T_READ_S - 0.1e-9)}n"})
        meas.append({"name": f"rpre_{n}", "unit": "V",
                     "spice": f".meas tran rpre_{n} FIND v(rbl_{n}) AT={f(G.T_READ_S - G.T_PRE_GAP_S)}n"})
        if p["kind"] == "real":
            meas.append({"name": f"dpre_{n}", "unit": "V",
                         "spice": f".meas tran dpre_{n} FIND v(d_{n}) AT={f(t_iso(p))}n"})
        else:
            meas.append({"name": f"dpre_{n}", "unit": "V",
                         "spice": f".meas tran dpre_{n} FIND v(d_{n}) AT={f(G.T_EN_S - WN_LEAD_IDEAL)}n"})
    req = {
        "netlist": netlist,
        "engine": "ngspice",
        "backend": "batch",
        "models": {"pdk": "sky130A", "lib": "libs.tech/combined/sky130.lib.spice"},
        "corners": {"process": MC_CORNERS if mc else G.PROCESS_CORNERS, "temperature_c": G.TEMPS_C},
    }
    if mc:
        req["exclude"] = [{"process": p, "temperature_c": t} for p, t in MC_EXCLUDE]
        req["monte_carlo"] = {"n": MC_N, "seed": MC_SEED, "vary": "mismatch", "quantiles": [2.5, 50, 97.5]}
    req["analysis"] = {"kind": "tran", "args": f"10p {f(G.T_STOP_S)}n 0 50p uic"}
    req["measurements"] = meas
    req["options"] = {"timeout_s": 900 if not mc else 3000, "keep_artifacts": False, "waveforms": False}
    return req


WN_LEAD_IDEAL = LEAD0  # the ideal control's dpre is read at the baseline isolation instant


def render() -> dict[Path, str]:
    c_sn_ff, _prov = G.load_extracted_c_sn(G.EXTRACT_JSON, "sn")
    c = c_sn_ff * 1e-15
    sp, mp = study_points(), mc_points()
    out = {
        STUDY_NETLIST: build_netlist(sp, c, "isolation_study.spice -- isolation-gate / write-driver sweep"),
        STUDY_REQUEST: json.dumps(build_request(sp, STUDY_NETLIST.name, False), indent=1) + "\n",
        MC_NETLIST: build_netlist(mp, c, "isolation_mc.spice -- Monte Carlo offset of the isolation pair"),
        MC_REQUEST: json.dumps(build_request(mp, MC_NETLIST.name, True), indent=1) + "\n",
    }
    return out


def main() -> int:
    for path, text in render().items():
        path.write_text(text)
        print(f"wrote {path.name}")
    print(f"{len(study_points())} study instances, {len(mc_points())} MC instances")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
