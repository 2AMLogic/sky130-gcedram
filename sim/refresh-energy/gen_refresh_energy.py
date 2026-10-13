#!/usr/bin/env python3
"""Generate the refresh-energy netlist and `klt sim` requests (issue #115).

Stdlib only. Writes, next to this file:

* ``refresh_energy.spice`` -- flat circuit body (no ``.control``/``.end``) for ``klt sim``.
  Every instance is the committed *extracted* 4x4 array
  (``layout/gain_cell_2t_array.extract.parasitics.spice``) re-emitted node-for-node with
  an instance suffix (parser shared with ``sim/write-disturb/gen_write_disturb.py``),
  generic ``nfet`` -> ``sky130_fd_pr__nfet_01v8``. Every array port is driven by its OWN
  ideal independent source per instance (no shared drivers), so the currents of one
  instance can never contaminate another's.
* ``request.json`` -- 5 global corners x {27, 125} C, one ``tran`` (TMAX = TRAN_MAX_S).
* ``request_fine.json`` -- the identical deck and grid at a 4x finer maximum step
  (TRAN_MAX_FINE_S): the time-resolution convergence repeat.

The operation replayed is the row refresh of ``sim/refresh-op`` (#110), same phase
definitions (imported from ``gen_refresh_op.py``), at the 10 ns sense basis and a
10 ns write-back pulse, applied to row 0 of the extracted array with ideal external
sources and WITHOUT the latch: precharge -> RWL0 select -> sense interval -> WWL0
pulse with WBL driven to the decided value -> release. Adaptations to the extracted
topology are listed in ``ADAPTATIONS`` and README.md.

Power is measured per source as p_s(t) = -v_s(t) * i_s(t) (SPICE i positive INTO the
positive terminal), emitted as behavioural nodes in W (unscaled: a 1e12 pW scaling
ill-conditioned the Newton solve in the local debug probe) and integrated with ``.meas INTEG`` (trapezoidal over
the accepted time points) between T_START_S and T_END_S: net, gross = integral of
max(p, 0), recovered = integral of max(-p, 0). The charge integral of every source is
measured too (calculation control: for a DC source E = -V * Q exactly).

PROPOSED, NOT RATIFIED: scope is the restricted range of
``spec/operating-range-decision-PROPOSED.md`` (27/125 C, VDD 1.8 V, global corners, no
mismatch). Re-run after editing any constant; ``test_refresh_energy.py`` fails if the
committed files are stale.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "sim" / "refresh-op"))
sys.path.insert(0, str(REPO / "sim" / "write-disturb"))
import gen_refresh_op as G  # noqa: E402  (#110 operation reference)
import gen_write_disturb as WD  # noqa: E402  (extracted-array parser)

NETLIST_PATH = HERE / "refresh_energy.spice"
REQUEST_PATH = HERE / "request.json"
REQUEST_FINE_PATH = HERE / "request_fine.json"
ARRAY_NETLIST = WD.ARRAY_NETLIST

# ---- scope (restricted PROPOSED range; nothing outside it) ----
PROCESS_CORNERS = ["tt", "ss", "ff", "sf", "fs"]
TEMPS_C = [27, 125]
VDD_V = 1.8
N_ROWS = 4
N_COLS = 4
SEL_ROW = 0                     # the refreshed row (issue: row 0, all four columns)

# ---- levels ----
VRBL_V = G.VRBL_V               # 0.9 V read-bitline precharge (contract, as #110)
DREF_V = G.DREF_V               # ASSUMPTION (#110): sense reference = VRBL - 100 mV
V_SN1_V = 0.90                  # ASSUMPTION (issue): aged stored '1' at refresh time (retention delta_V = VDD/2)
V_SN0_V = 0.00                  # ASSUMPTION (issue): stored '0'
WBL_IDLE_V = 0.0                # ASSUMPTION: idle write-bitline level (#110 WBL starts at 0 V)

# ---- phases (s); FIXED ones are #110's, imported, not retyped ----
T_EDGE_S = G.T_EDGE_S           # 100 ps edges
T_INIT_S = 5e-9                 # ASSUMPTION: settling time after the .ic initialisation, excluded from energy
SENSE_S = 10e-9                 # PROPOSED ASSUMPTION derived from #110: sense-stage contract basis (select -> enable)
WB_S = 10e-9                    # PROPOSED ASSUMPTION derived from #110: conservative write-back pulse
#                                 (#110 measured w_min <= 5 ns at FRAC 0.95, 10 ns sense, on its column deck)
REF_WB_S = G.REF_WB_S           # #110 reference write: SN from 0 V, ideal 1.8 V WBL, 20 ns WWL
R_PRE_SW = 100                  # ASSUMPTION (#110 swpre): ideal precharge switch on-resistance (ohm)

# ---- numerics (pinned; ASSUMPTION, see README) ----
TRAN_STEP_S = 10e-12
TRAN_MAX_S = 20e-12             # main run: maximum time step
TRAN_MAX_FINE_S = 5e-12         # convergence repeat: 4x finer maximum step
SIM_OPTIONS = "method=trap gmin=1e-15 abstol=1e-15 chgtol=1e-18"

# ---- patterns: explicit 4x4 bit maps (row-major, row 0 is refreshed) ----
PATTERNS = {
    "zero": [[0, 0, 0, 0] for _ in range(N_ROWS)],
    "one": [[1, 1, 1, 1] for _ in range(N_ROWS)],
    "checker": [[1 if (r + c) % 2 == 0 else 0 for c in range(N_COLS)] for r in range(N_ROWS)],
    "inv_checker": [[0 if (r + c) % 2 == 0 else 1 for c in range(N_COLS)] for r in range(N_ROWS)],
}
PAT_CODE = {"zero": "z", "one": "o", "checker": "c", "inv_checker": "i"}
NOP_PATTERN = "checker"         # no-pulse control: active code path with every pulse at its standby level

ADAPTATIONS = [
    "operation source: sim/refresh-op (#110) phase definitions (precharge-on 2 ns, gap 2 ns, latch delay 1 ns, "
    "guard 2 ns, measurement settle 2 ns, 100 ps edges) imported from gen_refresh_op.py; SENSE = 10 ns, WB = 10 ns",
    "topology: the extracted 4x4 array replaces #110's four-row single column of schematic cells; "
    "no external C_RBL / C_WBL (the 10 fF #110 assumptions are periphery/longer-bitline loads, outside the array boundary)",
    "no sense latch, no reference node: the read decision is taken from V(RBL) vs VREF = VRBL - 100 mV at the "
    "sense instant (select + SENSE) and the write-back value is the stored bit (an ideal, correct decision); a "
    "wrong-polarity read is classified as a read failure and the point is excluded from successful costs",
    "WBL driven by an ideal source (idle 0 V, decided value from WWL rise to release) instead of the latch "
    "complement through a 100 ohm switch",
    "RBL: standby-precharged to VRBL through the 100 ohm ideal switch (on outside the operation), released "
    "2 ns before select, reconnected at release (#110 started the bitline at the previous op's latch rail; "
    "that rail is a latch artefact outside this boundary)",
    "every one of the 16 cells stores its pattern bit (#110: all four rows of the column at one level)",
    "array GND (body taps) and vsubs (substrate / extracted-capacitance reference) each returned through their "
    "own 0 V source per instance (write-disturb tied them to ideal ground directly)",
]


def _fmt(x: float) -> str:
    return f"{x:.6g}"


def _ns(x: float) -> str:
    return f"{x * 1e9:.6g}n"


# ---------------------------------------------------------------------------
# timing
# ---------------------------------------------------------------------------
def times(sense: float = SENSE_S, wb: float = WB_S) -> dict:
    """Phase instants of one operation starting (precharge onset) at T_INIT_S."""
    t0 = T_INIT_S
    t_pre_off = t0 + G.T_PRE_ON_S
    t_sel = t_pre_off + G.T_PRE_GAP_S
    t_en = t_sel + sense
    t_on = t_en + G.T_LATCH_S
    t_off = t_on + wb
    t_rel = t_off + G.T_GUARD_S
    t_end = t_rel + G.T_MEAS_S
    return dict(t_start=t0, t_pre_off=t_pre_off, t_sel=t_sel, t_en=t_en, t_on=t_on,
                t_off=t_off, t_rel=t_rel, t_end=t_end)


T = times()
T_START_S = T["t_start"]
T_END_S = T["t_end"]
T_REF = times(SENSE_S, REF_WB_S)
T_STOP_S = T_REF["t_end"] + 1e-9


def t_row_refresh_op_s() -> float:
    """#110's definition of the operation's wall time (imported formula)."""
    return G.t_row_refresh_op_s(SENSE_S, WB_S)


# ---------------------------------------------------------------------------
# instances and sources
# ---------------------------------------------------------------------------
def instances() -> list[dict]:
    out = []
    for pat in PATTERNS:
        out.append(dict(name=f"act_{PAT_CODE[pat]}", mode="active", pattern=pat, energy=True))
    for pat in PATTERNS:
        out.append(dict(name=f"idl_{PAT_CODE[pat]}", mode="idle", pattern=pat, energy=True))
    out.append(dict(name=f"nop_{PAT_CODE[NOP_PATTERN]}", mode="nop", pattern=NOP_PATTERN, energy=True))
    out.append(dict(name="refw", mode="ref", pattern=None, energy=False))
    return out


def bit(inst: dict, r: int, c: int) -> int:
    if inst["mode"] == "ref":
        return 0                 # reference write starts every SN at 0 V (#110 refw)
    return PATTERNS[inst["pattern"]][r][c]


def source_roles() -> list[tuple[str, str, int | None]]:
    """(source stem, role, index) for every array-boundary source of one instance."""
    s = [(f"vpre{c}", "rbl_precharge", c) for c in range(N_COLS)]
    s += [(f"vwbl{c}", "wbl_writeback", c) for c in range(N_COLS)]
    s += [(f"vrwl{r}", "rwl_selected" if r == SEL_ROW else "rwl_deselected", r) for r in range(N_ROWS)]
    s += [(f"vwwl{r}", "wwl_selected" if r == SEL_ROW else "wwl_deselected", r) for r in range(N_ROWS)]
    s += [("vbody", "body_bias_gnd", None), ("vsub", "substrate_vsubs", None)]
    return s


def src_name(stem: str, inst: str) -> str:
    return f"{stem}_{inst}"


def src_pos_node(stem: str, inst: str) -> str:
    """Positive terminal node of a boundary source (negative terminal is always ground 0)."""
    if stem.startswith("vpre"):
        return f"pre{stem[4:]}_{inst}"
    if stem.startswith("vwbl"):
        return f"bl_{stem[4:]}_{inst}"
    if stem.startswith("vrwl"):
        return f"rwl_{stem[4:]}_{inst}"
    if stem.startswith("vwwl"):
        return f"wl_{stem[4:]}_{inst}"
    if stem == "vbody":
        return f"gnd_{inst}"
    if stem == "vsub":
        return f"vsubs_{inst}"
    raise KeyError(stem)


EXCLUDED_SOURCES = [("vctl", "precharge switch control (ideal sw model draws no control current; outside the array boundary)")]


def node_name(node: str, inst: str) -> str:
    return f"{node.lower()}_{inst}"


def mos_card(m, inst: str) -> str:
    name, d, g, s, b, par = m
    nm = "xm" + name[2:].lower() + "_" + inst
    return (f"{nm} {node_name(d, inst)} {node_name(g, inst)} {node_name(s, inst)} {node_name(b, inst)} "
            f"sky130_fd_pr__nfet_01v8 L={_fmt(par['L'])} W={_fmt(par['W'])} nf=1 ad={_fmt(par['AD'])} "
            f"as={_fmt(par['AS'])} pd={_fmt(par['PD'])} ps={_fmt(par['PS'])} mult=1 m=1")


def pwl(points: list[tuple[float, float]]) -> str:
    return "pwl(" + " ".join(f"{t:.6e} {_fmt(v)}" for t, v in points) + ")"


def _step_pair(lo: float, hi: float, t_up: float, t_dn: float) -> list[tuple[float, float]]:
    e = T_EDGE_S
    return [(0.0, lo), (t_up, lo), (t_up + e, hi), (t_dn, hi), (t_dn + e, lo)]


def drive(inst: dict, stem: str) -> str:
    """Source value expression for `stem` in instance `inst`."""
    mode = inst["mode"]
    t = T_REF if mode == "ref" else T
    pulsed = mode in ("active", "ref")
    if stem.startswith("vpre"):
        return f"dc {_fmt(VRBL_V)}"
    if stem.startswith("vwbl"):
        c = int(stem[4:])
        if mode == "ref":
            return f"dc {_fmt(VDD_V)}"            # #110 refw: ideal 1.8 V WBL throughout
        if mode == "active" and bit(inst, SEL_ROW, c) == 1:
            return pwl(_step_pair(WBL_IDLE_V, VDD_V, t["t_on"], t["t_rel"]))
        return f"dc {_fmt(WBL_IDLE_V)}"
    if stem.startswith("vrwl"):
        r = int(stem[4:])
        if pulsed and r == SEL_ROW:
            return pwl(_step_pair(VDD_V, 0.0, t["t_sel"], t["t_rel"]))
        return f"dc {_fmt(VDD_V)}"
    if stem.startswith("vwwl"):
        r = int(stem[4:])
        if pulsed and r == SEL_ROW:
            return pwl(_step_pair(0.0, VDD_V, t["t_on"], t["t_off"]))
        return "dc 0"
    if stem in ("vbody", "vsub"):
        return "dc 0"
    raise KeyError(stem)


def ctl_drive(inst: dict) -> str:
    t = T_REF if inst["mode"] == "ref" else T
    if inst["mode"] in ("active", "ref"):
        return pwl(_step_pair(VDD_V, 0.0, t["t_pre_off"], t["t_rel"]))
    return f"dc {_fmt(VDD_V)}"


def is_dc(inst: dict, stem: str) -> bool:
    return drive(inst, stem).startswith("dc ")


def dc_value(inst: dict, stem: str) -> float:
    return float(drive(inst, stem).split()[1])


# ---------------------------------------------------------------------------
# netlist
# ---------------------------------------------------------------------------
def build_netlist() -> str:
    arr = WD.parse_array(ARRAY_NETLIST)
    L: list[str] = []
    a = L.append
    a("* refresh_energy.spice -- ideal-driver array-boundary energy of one row refresh of the extracted")
    a("* 4x4 2T gain-cell array, and matched idle control (issue #115). GENERATED by gen_refresh_energy.py;")
    a("* do not edit by hand.")
    a("*")
    a("* PROPOSED/UNRATIFIED SCOPE: 27 C / 125 C, five global corners, 1.8 V (spec/operating-range-decision-PROPOSED.md).")
    a("* CIRCUIT BODY for `klt sim`: no .control/.end; .lib/.temp are appended per corner by klt.")
    a("*")
    a("* Instances (each the committed extracted array, own sources, no shared drivers):")
    a("*   act_<p>  refresh of row 0 (precharge -> RWL0 select -> 10 ns sense -> 10 ns WWL0 write-back of the")
    a("*            stored bit -> release); idl_<p> matched idle (standby levels, no pulses); nop_c active code")
    a("*            path with every pulse at its standby level (control); refw = #110 reference write (SN 0 V,")
    a("*            ideal 1.8 V WBL, 20 ns WWL) -- its energy is NOT measured.")
    a("*   <p> = z all-zero, o all-one, c checkerboard (bit = (r+c) even), i inverse checkerboard.")
    a("* Power nodes p{n,g,r}_<source> = net / max(p,0) / max(-p,0) of p = -v*i in W.")
    a("* ASSUMPTIONS (none is a spec value): ideal drivers, ideal 100 ohm precharge switch, stored '1' 0.9 V,")
    a("* idle WBL 0 V, standby RBL precharged, ideal decision, global corners only (no mismatch).")
    a("")
    a(f".options {SIM_OPTIONS}")
    a(f".model swpre sw(vt=0.9 vh=0.1 ron={R_PRE_SW} roff=1e12)")
    a("")
    ics: list[str] = []
    for inst in instances():
        n = inst["name"]
        a(f"* ---- instance {n}: mode {inst['mode']}, pattern {inst['pattern']} ----")
        for m in arr["mos"]:
            a(mos_card(m, n))
        for nm, n1, n2, ohm in arr["res"]:
            if nm == "Rvsubs_dctie":
                continue         # replaced by the vsub source below
            a(f"{nm.lower()}_{n} {node_name(n1, n)} {node_name(n2, n)} {_fmt(ohm)}")
        for nm, n1, n2, f in arr["cap"]:
            a(f"{nm.lower()}_{n} {node_name(n1, n)} {node_name(n2, n)} {_fmt(f)}")
        # boundary sources (negative terminal = ground for every one of them)
        for stem, _role, _i in source_roles():
            a(f"{src_name(stem, n)} {src_pos_node(stem, n)} 0 {drive(inst, stem)}")
        a(f"vctl_{n} ctl_{n} 0 {ctl_drive(inst)}   $ EXCLUDED: switch control, outside the boundary")
        for c in range(N_COLS):
            a(f"spre{c}_{n} pre{c}_{n} rbl_{c}_{n} ctl_{n} 0 swpre")
        if inst["energy"]:
            for stem, _role, _i in source_roles():
                s, v = src_name(stem, n), src_pos_node(stem, n)
                p = f"(-v({v})*i({s}))"
                a(f"bpn_{s} pn_{s} 0 v={p}")
                a(f"bpg_{s} pg_{s} 0 v=max({p},0)")
                a(f"bpr_{s} pr_{s} 0 v=max(-{p},0)")
        # initial conditions: stored levels on SN hubs/terminals, driven nets at their t=0 value
        nets = {x for (_nm, d, g, s, b, _p) in arr["mos"] for x in (d, g, s)} | {
            x for (_nm, n1, n2, _o) in arr["res"] for x in (n1, n2)}
        for net in sorted(nets):
            kind = net.split("_")[0]
            if kind == "sn":
                r, c = int(net.split("_")[1]), int(net.split("_")[2])
                val = V_SN1_V if bit(inst, r, c) else V_SN0_V
            elif kind == "bl":
                val = VDD_V if inst["mode"] == "ref" else WBL_IDLE_V
            elif kind == "rbl":
                val = VRBL_V
            elif kind == "rwl":
                val = VDD_V
            elif kind == "wl":
                val = 0.0
            else:
                continue
            ics.append(f"v({node_name(net, n)})={_fmt(val)}")
        a("")
    a("* initial conditions (tran uic)")
    for k in range(0, len(ics), 6):
        a(".ic " + " ".join(ics[k:k + 6]))
    a("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# measurements
# ---------------------------------------------------------------------------
def build_measurements() -> list[dict]:
    meas = []
    win = f"FROM={_ns(T_START_S)} TO={_ns(T_END_S)}"
    for inst in instances():
        n = inst["name"]
        if inst["energy"]:
            for stem, _role, _i in source_roles():
                s = src_name(stem, n)
                meas += [
                    {"name": f"en_{s}", "unit": "J", "spice": f".meas tran en_{s} INTEG v(pn_{s}) {win}"},
                    {"name": f"eg_{s}", "unit": "J", "spice": f".meas tran eg_{s} INTEG v(pg_{s}) {win}"},
                    {"name": f"er_{s}", "unit": "J", "spice": f".meas tran er_{s} INTEG v(pr_{s}) {win}"},
                    {"name": f"q_{s}", "unit": "C", "spice": f".meas tran q_{s} INTEG i({s}) {win}"},
                ]
            for r in range(N_ROWS):
                for c in range(N_COLS):
                    sn = f"v(sn_{r}_{c}_{n})"
                    meas += [
                        {"name": f"sna_{n}_{r}{c}", "unit": "V", "spice": f".meas tran sna_{n}_{r}{c} FIND {sn} AT={_ns(T_START_S)}"},
                        {"name": f"snb_{n}_{r}{c}", "unit": "V", "spice": f".meas tran snb_{n}_{r}{c} FIND {sn} AT={_ns(T_END_S)}"},
                    ]
            if inst["mode"] in ("active", "nop"):
                for c in range(N_COLS):
                    meas += [
                        {"name": f"rbs_{n}_{c}", "unit": "V",
                         "spice": f".meas tran rbs_{n}_{c} FIND v(rbl_{c}_{n}) AT={_ns(T['t_en'])}"},
                        {"name": f"snr_{n}_{c}", "unit": "V",
                         "spice": f".meas tran snr_{n}_{c} FIND v(sn_{SEL_ROW}_{c}_{n}) AT={_ns(T['t_on'] - 0.1e-9)}"},
                    ]
        else:  # reference write
            for c in range(N_COLS):
                meas.append({"name": f"snref_{c}", "unit": "V",
                             "spice": f".meas tran snref_{c} FIND v(sn_{SEL_ROW}_{c}_{n}) AT={_ns(T_REF['t_end'])}"})
    return meas


def build_request(tmax_s: float) -> dict:
    return {
        "netlist": "refresh_energy.spice",
        "engine": "ngspice",
        "backend": "batch",
        "models": {"pdk": "sky130A", "lib": "libs.tech/combined/sky130.lib.spice"},
        "corners": {"process": PROCESS_CORNERS, "temperature_c": TEMPS_C},
        "analysis": {"kind": "tran",
                     "args": f"{_fmt(TRAN_STEP_S * 1e12)}p {_fmt(T_STOP_S * 1e9)}n 0 {_fmt(tmax_s * 1e12)}p uic"},
        "measurements": build_measurements(),
        "options": {"timeout_s": 3600, "keep_artifacts": False, "waveforms": False},
    }


def render() -> tuple[str, str, str]:
    return (build_netlist(),
            json.dumps(build_request(TRAN_MAX_S), indent=1) + "\n",
            json.dumps(build_request(TRAN_MAX_FINE_S), indent=1) + "\n")


def main() -> int:
    net, req, req_fine = render()
    NETLIST_PATH.write_text(net)
    REQUEST_PATH.write_text(req)
    REQUEST_FINE_PATH.write_text(req_fine)
    print(f"wrote {NETLIST_PATH.name} ({len(instances())} instances), {REQUEST_PATH.name}, {REQUEST_FINE_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
