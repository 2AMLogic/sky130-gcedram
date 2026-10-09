#!/usr/bin/env python3
"""Generate the column-periphery comparison deck and `klt sim` request (issue #114).

Stdlib only. Writes, next to this file:

* ``column_periphery.spice`` -- a *circuit body* (no ``.control``/``.end``), as
  ``klt sim`` requires, FLAT and self-contained. The slice and latch device
  cards are copied from ``design/column_periphery.spice`` and
  ``design/sense_latch.spice``; the bitcell cards from
  ``design/gain_cell_2t.spice`` (``design/test_column_periphery.py`` checks the
  deck still equals the schematic-derived netlists).
* ``request.json`` -- the ``klt sim`` request: five global process corners x
  {27 C, 125 C}, one ``tran`` per corner; every case is an independent
  parallel instance inside that one deck.

Instance kinds (each: 4-row column, row 0 written then read, latch enabled):

* ``ideal_w1/w0``  the existing ideal-source setup (100 ohm ideal precharge
                   switch, ideal write-bitline source, latch directly on rbl).
* ``real_w1/w0``   the same column with the designed slice: PMOS precharge,
                   tri-state write driver, rbl/ref isolation gates.
* ``sw_<W>``       precharge-width sweep (real slice, '1' data; only the
                   precharge metrics are used) -- the sizing evidence.

Re-run after editing any constant; the tests fail if committed files are stale.

PROPOSED, NOT RATIFIED: the corner/temperature set is the restricted range of
``spec/operating-range-decision-PROPOSED.md`` (27 C and 125 C, five global
corners, VDD = 1.8 V). Nothing outside it is simulated.
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

NETLIST_PATH = HERE / "column_periphery.spice"
REQUEST_PATH = HERE / "request.json"
DESIGN = REPO / "design"
EXTRACT_JSON = REPO / "layout" / "gain_cell_2t.extract.parasitics.json"

# ---- scope: restricted range of the PROPOSED record (nothing outside it) ----
PROCESS_CORNERS = ["tt", "ss", "ff", "sf", "fs"]
TEMPS_C = [27, 125]
VDD_V = 1.8

# ---- bias / timing (contract inputs, SENSE_INPUT_CONTRACT.md) ----
VRBL_V = 0.9                   # precharge level (contract)
DREF_V = 0.1                   # reference = VRBL - 0.1 V (sense-stage ASSUMPTION)
C_RBL_F = 10e-15               # ASSUMPTION (contract; not extracted, #88 pending)
C_WBL_F = 10e-15               # ASSUMPTION: write-bitline load, same value as C_RBL; not extracted
N_ROWS = 4
SN_HOLD1_V = 1.0               # rows 1..3 hold this when the data is '1' (STUDY-ASSUMPTION, as sense-stage)
T_EDGE_S = 100e-12
T_PRE_ON_S = 1e-9              # precharge asserts here (rbl starts at 0 V = fully discharged)
T_PRE_BUDGET_S = 2e-9          # precharge phase of t_row_refresh_op `anchored` (sim/refresh-overhead)
SETTLE_V = 0.01                # settled = within 10 mV of VRBL (ASSUMPTION)
T_WBL_ON_S = 10e-9
T_WL_ON_S = 12e-9              # WL rises 2 ns after the bitline moves (loaded-column TBL_LAG)
T_WL_OFF_S = 32e-9             # 20 ns pulse (existing write pulse)
T_WBL_OFF_S = 34e-9
T_WRCHK_S = 45e-9              # stored level sampled here (wbl idle again, ~13 ns after WL fell)
T_READ_S = 60e-9               # select edge
T_PRE_GAP_S = 2e-9             # precharge released 2 ns before select (contract)
T_EN_S = T_READ_S + 10e-9      # sense instant 10 ns after select edge (contract)
T_ISO_LEAD_S = 0.5e-9          # isolation gates open this long before the latch enable (ASSUMPTION)
T_STOP_S = T_EN_S + 20e-9

# ---- precharge-width sweep (um) for the sizing evidence ----
PRE_W_SWEEP_UM = [1.0, 2.0, 4.0, 8.0]
DIFF_UM = 0.29


def _fmt(x: float) -> str:
    return f"{x:.6g}"


def join_lines(text: str) -> str:
    return re.sub(r"\n\+", " ", text)


def parse_cards(path: Path) -> dict[str, tuple[list[str], str, str]]:
    """{device: (nets[D G S B], model, trailing params)} for every X card."""
    out = {}
    for line in join_lines(path.read_text()).splitlines():
        if line.startswith("*"):
            continue
        t = line.split()
        if t and t[0].startswith("XM"):
            out[t[0][1:]] = (t[1:5], t[5], " ".join(t[6:]))
    return out


def set_width(params: str, w_um: float) -> str:
    """Rewrite W and ALL width-dependent geometry for a sweep width.

    Single-finger xschem/bitcell convention (as in design/*.spice):
    ad = as = W * 0.29, pd = ps = 2 * (W + 0.29), nrd = nrs = 0.29 / W.
    Every one of the six must follow W (nrd/nrs were missed in the first
    sweep, run 20261009T204412Z; design/test_column_periphery.py now checks
    the full geometry).
    """
    ad = w_um * DIFF_UM
    pd = 2 * (w_um + DIFF_UM)
    nr = DIFF_UM / w_um
    p = re.sub(r"\bW=\S+", f"W={_fmt(w_um)}", params)
    for k, v in (("ad", ad), ("as", ad), ("pd", pd), ("ps", pd), ("nrd", nr), ("nrs", nr)):
        p, n = re.subn(rf"\b{k}=\S+", f"{k}={_fmt(v)}", p)
        if n != 1:
            raise ValueError(f"set_width: expected exactly one {k}= in {params!r}")
    return p


def instances() -> list[dict]:
    pts = []
    for kind in ("ideal", "real"):
        for d in (1, 0):
            pts.append(dict(kind=kind, data=d, name=f"{kind}_w{d}"))
    for w in PRE_W_SWEEP_UM:
        pts.append(dict(kind="sweep", data=1, w=w, name=f"sw_{round(w * 100):04d}"))
    for i, p in enumerate(pts):
        p["idx"] = i
    return pts


def build_netlist(c_sn_f: float) -> str:
    cell = parse_cards(DESIGN / "gain_cell_2t.spice")
    latch = parse_cards(DESIGN / "sense_latch.spice")
    per = parse_cards(DESIGN / "column_periphery.spice")
    wr_m, wr_p = cell["M_WR"][1], cell["M_WR"][2]
    rd_m, rd_p = cell["M_RD"][1], cell["M_RD"][2]
    pts = instances()
    t_pre_rel = T_READ_S - T_PRE_GAP_S
    L: list[str] = []
    a = L.append
    a("* column_periphery.spice -- ideal-source vs designed column periphery on the 2T gain-cell")
    a("* column (issue #114). GENERATED by gen_column_periphery.py; do not edit by hand.")
    a("*")
    a("* PROPOSED/UNRATIFIED SCOPE: corners/temperatures come from")
    a("* spec/operating-range-decision-PROPOSED.md (27 C and 125 C only). Inputs follow")
    a("* sim/loaded-column/cold-corner/SENSE_INPUT_CONTRACT.md (baseline column).")
    a("* CIRCUIT BODY for `klt sim`: no .control/.end; PDK .lib/.temp cards are appended per corner.")
    a("*")
    a("* Instance kinds: ideal_w<d> = existing ideal sources (100 ohm switch, ideal write source, latch")
    a("* on rbl); real_w<d> = designed slice (design/column_periphery.spice); sw_<W*100> = precharge")
    a("* width sweep (W in um x100). d = data written to row 0 ('1' or '0').")
    a("*")
    a("* ASSUMPTIONS (labelled; none is a spec value): C_RBL, C_WBL, VRBL, vpre rail an ideal 0.9 V")
    a("* source, 4-row column, all four SN at one level before the write except the written row,")
    a("* sense instant, reference level, ideal reference-side precharge and matched dummy load, ideal")
    a("* digital control edges (100 ps), global corners only.")
    a("")
    a(f".param VDD     = {_fmt(VDD_V)}")
    a(f".param VRBL    = {_fmt(VRBL_V)}   $ ASSUMPTION (contract)")
    a(f".param VREF    = {_fmt(VRBL_V - DREF_V)}   $ ASSUMPTION: VRBL - 0.1 V (as sense-stage)")
    a(f".param TEDGE   = {_fmt(T_EDGE_S)}")
    a(f".param C_RBL   = {_fmt(C_RBL_F)}   $ ASSUMPTION (contract; not extracted)")
    a(f".param C_WBL   = {_fmt(C_WBL_F)}   $ ASSUMPTION (not extracted)")
    a(f".param C_SN    = {_fmt(c_sn_f)}   $ extracted-from-netlist (layout/gain_cell_2t.extract.parasitics.json)")
    a("")
    a("* ---- shared control (ideal digital edges) ----")
    a("vdd   vdd 0 dc {VDD}")
    a(f"vpca  pca 0 pwl(0 0 {_fmt(T_PRE_ON_S)} 0 {_fmt(T_PRE_ON_S + T_EDGE_S)} {{VDD}} {_fmt(t_pre_rel)} {{VDD}} {_fmt(t_pre_rel + T_EDGE_S)} 0)   $ active-high precharge")
    a(f"vpcb  pcb 0 pwl(0 {{VDD}} {_fmt(T_PRE_ON_S)} {{VDD}} {_fmt(T_PRE_ON_S + T_EDGE_S)} 0 {_fmt(t_pre_rel)} 0 {_fmt(t_pre_rel + T_EDGE_S)} {{VDD}})   $ active-low precharge")
    a(f"vwen  wen 0 pwl(0 0 {_fmt(T_WBL_ON_S)} 0 {_fmt(T_WBL_ON_S + T_EDGE_S)} {{VDD}} {_fmt(T_WBL_OFF_S)} {{VDD}} {_fmt(T_WBL_OFF_S + T_EDGE_S)} 0)")
    a(f"vwenb wenb 0 pwl(0 {{VDD}} {_fmt(T_WBL_ON_S)} {{VDD}} {_fmt(T_WBL_ON_S + T_EDGE_S)} 0 {_fmt(T_WBL_OFF_S)} 0 {_fmt(T_WBL_OFF_S + T_EDGE_S)} {{VDD}})")
    a("vdinb1 dinb1 0 dc 0          $ data '1': wbl = NOT dinb = VDD")
    a("vdinb0 dinb0 0 dc {VDD}      $ data '0'")
    a(f"vwl   wl 0 pwl(0 0 {_fmt(T_WL_ON_S)} 0 {_fmt(T_WL_ON_S + T_EDGE_S)} {{VDD}} {_fmt(T_WL_OFF_S)} {{VDD}} {_fmt(T_WL_OFF_S + T_EDGE_S)} 0)")
    a(f"vrwls rwl_sel 0 pwl(0 {{VDD}} {_fmt(T_READ_S)} {{VDD}} {_fmt(T_READ_S + T_EDGE_S)} 0)")
    a("vrwld rwl_des 0 dc {VDD}")
    t_iso = T_EN_S - T_ISO_LEAD_S
    a(f"vsel  sel  0 pwl(0 {{VDD}} {_fmt(t_iso)} {{VDD}} {_fmt(t_iso + T_EDGE_S)} 0)")
    a(f"vselb selb 0 pwl(0 0 {_fmt(t_iso)} 0 {_fmt(t_iso + T_EDGE_S)} {{VDD}})")
    a(f"ven   en  0 pwl(0 0 {_fmt(T_EN_S)} 0 {_fmt(T_EN_S + T_EDGE_S)} {{VDD}})")
    a(f"venb  enb 0 pwl(0 {{VDD}} {_fmt(T_EN_S)} {{VDD}} {_fmt(T_EN_S + T_EDGE_S)} 0)")
    a("vprea prea 0 dc {VRBL}       $ ASSUMPTION: ideal 0.9 V precharge rail")
    a("vpref pref 0 dc {VREF}")
    a(".model swpre sw(vt=0.9 vh=0.1 ron=100 roff=1e12)")
    a("")
    ics: list[str] = []
    for p in pts:
        n, d, kind = p["name"], p["data"], p["kind"]
        rb, rf, wb = f"rbl_{n}", f"ref_{n}", f"wbl_{n}"
        vn, vp = f"vn_{n}", f"vp_{n}"
        a(f"* ---- instance {p['idx']}: {n} ----")
        # column: write access M_WR source on wbl, read M_RD drain on rbl
        for r in range(N_ROWS):
            sn = f"sn_{n}_{r}"
            rwl = "rwl_sel" if r == 0 else "rwl_des"
            gate = "wl" if r == 0 else "0"
            a(f"XMWR_{n}_{r} {sn} {gate} {wb} 0 {wr_m} {wr_p}")
            a(f"XMRD_{n}_{r} {rb} {sn} {rwl} 0 {rd_m} {rd_p}")
            a(f"csn_{n}_{r} {sn} 0 {{C_SN}}")
            # row 0 starts at the OPPOSITE of the data (genuine overwrite); rows 1..3 at the data level
            if r == 0:
                ics.append(f"v({sn})={_fmt(0.0 if d == 1 else SN_HOLD1_V)}")
            else:
                ics.append(f"v({sn})={_fmt(SN_HOLD1_V if d == 1 else 0.0)}")
        a(f"crbl_{n} {rb} 0 {{C_RBL}}")
        a(f"cwbl_{n} {wb} 0 {{C_WBL}}")
        a(f"cref_{n} {rf} 0 {{C_RBL}}   $ ASSUMPTION: ideal matched dummy load")
        a(f"spr_{n} pref {rf} pca 0 swpre   $ reference-side precharge stays an ideal switch")
        ics += [f"v({rb})=0", f"v({rf})={_fmt(VRBL_V - DREF_V)}", f"v({wb})=0"]
        if kind == "ideal":
            sbl, sref = rb, rf
            a(f"spa_{n} prea {rb} pca 0 swpre   $ existing ideal precharge switch")
            # ideal write-bitline source: same edges as the WEN window, data level
            lvl = "{VDD}" if d == 1 else "0"
            a(f"vwbl_{n} {wb} 0 pwl(0 0 {_fmt(T_WBL_ON_S)} 0 {_fmt(T_WBL_ON_S + T_EDGE_S)} {lvl} "
              f"{_fmt(T_WBL_OFF_S)} {lvl} {_fmt(T_WBL_OFF_S + T_EDGE_S)} 0)   $ ideal write source")
        else:
            sbl, sref = f"sbl_{n}", f"sref_{n}"
            netmap = {"rbl": rb, "sbl": sbl, "ref": rf, "sref": sref, "wbl": wb,
                      "pre_b": "pcb", "vpre": "prea", "dinb": f"dinb{d}",
                      "wen": "wen", "wenb": "wenb", "sel": "sel", "selb": "selb",
                      "vdd": "vdd", "GND": "0", "0": "0"}
            for dev, (nets, model, params) in per.items():
                nn = [netmap.get(x, f"{x}_{n}") for x in nets]
                if kind == "sweep" and dev == "MPPRE":
                    params = set_width(params, p["w"])
                a(f"X{dev}_{n} {' '.join(nn)} {model} {params}")
            ics += [f"v({sbl})=0", f"v({sref})={_fmt(VRBL_V - DREF_V)}"]
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


def build_request() -> dict:
    meas = []
    f = lambda t: _fmt(t * 1e9)
    for p in instances():
        n = p["name"]
        # lower-case names only (klayout-tools#2914)
        meas += [
            {"name": f"tpre_{n}", "unit": "s",
             "spice": f".meas tran tpre_{n} WHEN v(rbl_{n})={_fmt(VRBL_V - SETTLE_V)} RISE=1"},
            {"name": f"vrel_{n}", "unit": "V",
             "spice": f".meas tran vrel_{n} FIND v(rbl_{n}) AT={f(T_READ_S - T_PRE_GAP_S)}n"},
        ]
        if p["kind"] == "sweep":
            continue
        meas += [
            {"name": f"sn_{n}", "unit": "V",
             "spice": f".meas tran sn_{n} FIND v(sn_{n}_0) AT={f(T_WRCHK_S)}n"},
            {"name": f"din_{n}", "unit": "V",
             "spice": f".meas tran din_{n} FIND v(d_{n}) AT={f(T_EN_S)}n"},
            {"name": f"dend_{n}", "unit": "V",
             "spice": f".meas tran dend_{n} FIND v(d_{n}) AT={f(T_STOP_S)}n"},
            {"name": f"tdec_{n}", "unit": "s",
             "spice": f".meas tran tdec_{n} WHEN v(dabs_{n})=0.9 RISE=1 TD={f(T_EN_S)}n"},
        ]
    return {
        "netlist": "column_periphery.spice",
        "engine": "ngspice",
        "backend": "batch",
        "models": {"pdk": "sky130A", "lib": "libs.tech/combined/sky130.lib.spice"},
        "corners": {"process": PROCESS_CORNERS, "temperature_c": TEMPS_C},
        "analysis": {"kind": "tran", "args": f"10p {f(T_STOP_S)}n 0 50p uic"},
        "measurements": meas,
        "options": {"timeout_s": 900, "keep_artifacts": False, "waveforms": False},
    }


def render() -> tuple[str, str]:
    c_sn_ff, _prov = load_extracted_c_sn(EXTRACT_JSON, "sn")
    return build_netlist(c_sn_ff * 1e-15), json.dumps(build_request(), indent=1) + "\n"


def main() -> int:
    net, req = render()
    NETLIST_PATH.write_text(net)
    REQUEST_PATH.write_text(req)
    print(f"wrote {NETLIST_PATH.name} ({len(instances())} instances) and {REQUEST_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
