#!/usr/bin/env python3
"""Generate the write-disturb netlist and `klt sim` request (issue #98).

Stdlib only. Writes, next to this file:

* ``write_disturb.spice`` -- a *circuit body* (no ``.control``/``.end``), as
  ``klt sim`` requires, FLAT and self-contained: the batch fleet receives only
  ``netlist.cir`` + ``request.json``. Every instance is the committed
  *extracted* 4x4 array
  (``layout/gain_cell_2t_array.extract.parasitics.spice``: 32 devices, per-net
  lumped R, ground C and net-to-net coupling C) re-emitted node-for-node with
  an instance suffix and the generic ``nfet`` model replaced by
  ``sky130_fd_pr__nfet_01v8`` (this script does the translation; the test
  suite checks the device/R/C counts and values against the source).
* ``request.json`` -- the ``klt sim`` request: the five global process corners
  x {27 C, 125 C}, one ``tran`` per corner; every scenario is an independent
  parallel instance inside that one deck.

Re-run after editing any constant; ``test_write_disturb.py`` fails if the
committed files are stale.

PROPOSED, NOT RATIFIED: the corner/temperature set is the restricted range of
``spec/operating-range-decision-PROPOSED.md`` (27 C and 125 C, five global
corners, VDD = 1.8 V). Nothing outside it is simulated.

Scenarios (instance names are lower case; see README.md for the rationale):

* ``ctl0`` / ``ctl1``   no-disturb controls: write wordlines off, every write
  bitline held at its idle level (0 V / VDD) for the whole run.
* ``rep1``              repeated writes of '1' to column 1 of row 0 (WBL idles
  at 0 V and pulses to VDD with each write); the other three columns of the
  asserted row are half-selected with their bitline at the idle level (a
  rewrite of their own '0').
* ``rep0``              mirror image (WBL idles at VDD, pulses to 0 V).
* ``hs_p1`` / ``hs_p0`` ONE write to row 0 with a mixed data word so that the
  half-selected cells sit between aggressor columns of both polarities.
* ``neg_*``             NEGATIVE CONTROL: the same four stimuli with every
  write access device widened by ``LEAKY_W_FACTOR`` (a deliberately leaky
  access device). The analyzer must flag it.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

NETLIST_PATH = HERE / "write_disturb.spice"
REQUEST_PATH = HERE / "request.json"
ARRAY_NETLIST = REPO / "layout" / "gain_cell_2t_array.extract.parasitics.spice"

# ---- scope: restricted range of the PROPOSED record (nothing outside it) ----
PROCESS_CORNERS = ["tt", "ss", "ff", "sf", "fs"]
TEMPS_C = [27, 125]            # 27 C = restricted cold bound; 125 C = worst-case retention corner
VDD_V = 1.8
N_ROWS = 4
N_COLS = 4

# ---- levels (ASSUMPTIONS) ----
V_SN1_V = 1.0                  # stored '1' level at the start (between delta_V=0.9 V and typical written 1.0-1.2 V)
V_SN0_V = 0.0                  # stored '0' level at the start
VRBL_V = 0.9                   # idle read bitline (SENSE_INPUT_CONTRACT precharge level), ideal source
DELTA_V_V = 0.9                # ratified retention-derivation delta_V = VDD/2 (ASSUMPTION there)
T_RET_RATIFIED_S = 1.005989e-05  # spec/retention-refresh-budget.md section 7 (2T-min, sf/125 C)
REFRESH_BOUND_S = T_RET_RATIFIED_S / 2   # ratified refresh interval ~5.03 us

# ---- timing (ASSUMPTIONS) ----
T_EDGE_S = 100e-12             # 100 ps edges (existing loaded-column convention)
T_START_S = 10e-9              # first write cycle begins here
T_CYC_S = 34e-9                # one write op = T_ROW = 34 ns (digital/refresh-scheduler, sim/refresh-overhead anchored)
T_WL_ON_S = 2e-9               # WL rises this long after the bitline moves (setup)
T_WL_W_S = 20e-9               # WL pulse width = existing write pulse (loaded-column)
T_BL_HOLD_S = 24e-9            # bitline returns to idle this long after cycle start (2 ns hold after WL falls)
T_SETTLE_S = 4e-9              # checkpoint is taken this long before the end of the cycle (bitline idle again)
N_MAX = int(REFRESH_BOUND_S // T_CYC_S)           # writes the scheduler could issue in one 5.03 us window
N_SET = [1, 4, 16, 64, N_MAX]
T_STOP_S = T_START_S + N_MAX * T_CYC_S + 10e-9
TRAN_STEP_S = 10e-12
TRAN_MAX_S = 100e-12

# ---- stored-data pattern (ASSUMPTION): rows 1..3 hold '1','0','1' in every column,
# so each write bitline sees victims of both polarities.
VICTIM_ROWS_STORED = {1: 1, 2: 0, 3: 1}
TARGET_COL = 1                 # the column whose WBL is toggled / written

# ---- negative control ----
LEAKY_W_FACTOR = 10.0          # every write access device 10x wider (~10x off-current)

# ---- numerical options (ASSUMPTION; documented in README) ----
# Defaults (gmin 1e-12 S, abstol 1e-12 A, chgtol 1e-14 C) are of the same order as the
# physical off-current (27 C) and the storage charge (~1e-15 C) being measured.
SIM_OPTIONS = "gmin=1e-15 abstol=1e-15 chgtol=1e-18"

STAGE_NAMES = ["ctl0", "ctl1", "rep1", "rep0", "hs_p1", "hs_p0",
               "neg_ctl0", "neg_ctl1", "neg_rep1", "neg_rep0"]

PRE_T_S = 5e-9                 # "pre" sample for single-write scenarios


def _fmt(x: float) -> str:
    return f"{x:.6g}"


# ---------------------------------------------------------------------------
# scenario table
# ---------------------------------------------------------------------------
def scenarios() -> list[dict]:
    """Ordered scenario list. ``bl`` entries are shared-driver names; ``s0`` is the
    stored word of row 0 ('1' -> V_SN1_V); rows 1..3 follow VICTIM_ROWS_STORED."""
    def sc(name, leaky, family, wl, bl, s0):
        return dict(name=name, leaky=leaky, family=family, wl=wl, bl=bl, s0=s0)
    out = []
    for leaky, pre in ((False, ""), (True, "neg_")):
        out += [
            sc(pre + "ctl0", leaky, "ctl0", "off", ["zero"] * 4, [0, 0, 0, 0]),
            sc(pre + "ctl1", leaky, "ctl1", "off", ["vdd"] * 4, [1, 1, 1, 1]),
            sc(pre + "rep1", leaky, "rep1", "train", ["zero", "hi_train", "zero", "zero"], [0, 0, 0, 0]),
            sc(pre + "rep0", leaky, "rep0", "train", ["vdd", "lo_train", "vdd", "vdd"], [1, 1, 1, 1]),
        ]
    out += [
        sc("hs_p1", False, "hs_p1", "one", ["zero", "hi_one", "vdd", "zero"], [0, 0, 1, 0]),
        sc("hs_p0", False, "hs_p0", "one", ["vdd", "lo_one", "zero", "vdd"], [1, 1, 0, 1]),
    ]
    order = {n: i for i, n in enumerate(STAGE_NAMES)}
    out.sort(key=lambda s: order[s["name"]])
    return out


def stored_level(sc: dict, r: int, c: int) -> float:
    bit = sc["s0"][c] if r == 0 else VICTIM_ROWS_STORED[r]
    return V_SN1_V if bit else V_SN0_V


def stored_bit(sc: dict, r: int, c: int) -> int:
    return sc["s0"][c] if r == 0 else VICTIM_ROWS_STORED[r]


def checkpoint_time_s(n: int) -> float:
    """Sample instant after the n-th write completes (bitline back at idle)."""
    return T_START_S + (n - 1) * T_CYC_S + T_CYC_S - T_SETTLE_S


# ---------------------------------------------------------------------------
# extracted-array parsing
# ---------------------------------------------------------------------------
def parse_array(path: Path = ARRAY_NETLIST) -> dict:
    """Parse the extracted subcircuit: {ports, mos, res, cap}.

    mos:  (name, d, g, s, b, params dict in um / um^2)
    res:  (name, n1, n2, ohm)         cap: (name, n1, n2, farad)
    """
    text = re.sub(r"\n\+", " ", path.read_text())
    lines = [ln.strip() for ln in text.splitlines()]
    in_sub = False
    ports: list[str] = []
    mos, res, cap = [], [], []
    for ln in lines:
        if not ln or ln.startswith("*"):
            continue
        u = ln.upper()
        if u.startswith(".SUBCKT"):
            in_sub = True
            ports = ln.split()[2:]
            continue
        if u.startswith(".ENDS"):
            in_sub = False
            continue
        if not in_sub:
            continue
        tok = ln.split()
        kind = tok[0][0].upper()
        if kind == "M":
            if tok[5].lower() != "nfet":
                raise RuntimeError(f"unexpected device model in extracted array: {ln}")
            par = {}
            for t in tok[6:]:
                k, v = t.split("=")
                par[k.upper()] = float(re.sub(r"[UuPp]$", "", v))
            mos.append((tok[0], tok[1], tok[2], tok[3], tok[4], par))
        elif kind == "R":
            res.append((tok[0], tok[1], tok[2], float(tok[3])))
        elif kind == "C":
            cap.append((tok[0], tok[1], tok[2], float(tok[3])))
        else:
            raise RuntimeError(f"unexpected element in extracted array: {ln}")
    if len(mos) != 2 * N_ROWS * N_COLS:
        raise RuntimeError("expected 32 devices in the extracted 4x4 array")
    return dict(ports=ports, mos=mos, res=res, cap=cap)


def node_name(node: str, inst: str) -> str:
    if node in ("GND", "vsubs", "0"):
        return "0"           # ideal ground and ideal substrate (ASSUMPTION; see README)
    return f"{node.lower()}_{inst}"


def is_write_device(gate: str) -> bool:
    return gate.startswith("wl_")


def mos_card(m, inst: str, leaky: bool) -> str:
    name, d, g, s, b, par = m
    w, l = par["W"], par["L"]
    ad, as_, pd, ps = par["AD"], par["AS"], par["PD"], par["PS"]
    if leaky and is_write_device(g):
        f = LEAKY_W_FACTOR
        ad, as_ = ad * f, as_ * f
        pd, ps = pd + 2 * (f - 1) * w, ps + 2 * (f - 1) * w
        w = w * f
    nm = "xm" + name[2:].lower() + "_" + inst
    return (f"{nm} {node_name(d, inst)} {node_name(g, inst)} {node_name(s, inst)} {node_name(b, inst)} "
            f"sky130_fd_pr__nfet_01v8 L={_fmt(l)} W={_fmt(w)} nf=1 ad={_fmt(ad)} as={_fmt(as_)} "
            f"pd={_fmt(pd)} ps={_fmt(ps)} mult=1 m=1")


# ---------------------------------------------------------------------------
# shared drivers
# ---------------------------------------------------------------------------
def pwl(points: list[tuple[float, float]]) -> str:
    chunks, cur = [], []
    for t, v in points:
        cur.append(f"{t:.10g} {_fmt(v)}")
        if len(cur) == 6:
            chunks.append(" ".join(cur))
            cur = []
    if cur:
        chunks.append(" ".join(cur))
    return "pwl(" + "\n+ ".join(chunks) + ")"


def train(n_cycles: int, kind: str) -> list[tuple[float, float]]:
    e = T_EDGE_S
    pts: list[tuple[float, float]] = [(0.0, {"wl": 0.0, "hi": 0.0, "lo": VDD_V}[kind])]
    for k in range(n_cycles):
        c = T_START_S + k * T_CYC_S
        if kind == "wl":
            t0, t1 = c + T_WL_ON_S, c + T_WL_ON_S + T_WL_W_S
            pts += [(t0, 0.0), (t0 + e, VDD_V), (t1, VDD_V), (t1 + e, 0.0)]
        else:
            idle, act = (0.0, VDD_V) if kind == "hi" else (VDD_V, 0.0)
            t1 = c + T_BL_HOLD_S
            pts += [(c, idle), (c + e, act), (t1, act), (t1 + e, idle)]
    return pts


DRIVERS = {  # shared node -> (kind, n_cycles); const nodes handled separately
    "g_wl_train": ("wl", N_MAX), "g_wl_one": ("wl", 1),
    "g_hi_train": ("hi", N_MAX), "g_hi_one": ("hi", 1),
    "g_lo_train": ("lo", N_MAX), "g_lo_one": ("lo", 1),
}
BL_NODE = {"zero": "0", "vdd": "vdd", "hi_train": "g_hi_train", "lo_train": "g_lo_train",
           "hi_one": "g_hi_one", "lo_one": "g_lo_one"}
WL_NODE = {"off": "0", "train": "g_wl_train", "one": "g_wl_one"}


def build_netlist() -> str:
    arr = parse_array()
    L: list[str] = []
    a = L.append
    a("* write_disturb.spice -- write disturb of unselected / half-selected cells in the extracted 4x4")
    a("* 2T gain-cell array (issue #98, Epic #24 item 6). GENERATED by gen_write_disturb.py; do not edit.")
    a("*")
    a("* PROPOSED/UNRATIFIED SCOPE: corners/temperatures come from")
    a("* spec/operating-range-decision-PROPOSED.md (27 C and 125 C only).")
    a("* CIRCUIT BODY for `klt sim`: no .control/.end; the PDK .lib/.temp cards are appended per corner")
    a("* by klt. Flat and self-contained (batch fleet gets only this file + request.json).")
    a("*")
    a("* Each instance below is the committed extracted array")
    a("* layout/gain_cell_2t_array.extract.parasitics.spice (as-is; array C_SN not yet reconciled, #89),")
    a("* node-for-node with the instance name appended to every net, generic `nfet` -> sky130_fd_pr__nfet_01v8,")
    a("* GND and vsubs tied to ideal ground (ASSUMPTION). Drawn diffusion AD/AS/PD/PS are the extracted ones.")
    a("* ASSUMPTIONS (all labelled; none is a spec value): ideal rail-to-rail bitline / wordline drivers, ideal")
    a("* read bitline source (0.9 V) and read wordline (VDD, read device off), no mismatch, global corners only,")
    a("* stored levels and 34 ns write cadence as in the generator constants, no sense / read activity.")
    a("")
    a(f".options {SIM_OPTIONS}")
    a(f".param VDD = {_fmt(VDD_V)}")
    a("vdd  vdd  0 dc {VDD}")
    a(f"vrbl vrbl 0 dc {_fmt(VRBL_V)}")
    for node, (kind, n) in DRIVERS.items():
        a(f"v{node} {node} 0 {pwl(train(n, kind))}")
    a("")
    ics: list[str] = []
    for sc in scenarios():
        inst = sc["name"]
        a(f"* ---- instance {inst}: family {sc['family']}{' (LEAKY write devices x%g)' % LEAKY_W_FACTOR if sc['leaky'] else ''} ----")
        for m in arr["mos"]:
            a(mos_card(m, inst, sc["leaky"]))
        for nm, n1, n2, ohm in arr["res"]:
            if nm == "Rvsubs_dctie":
                continue
            a(f"{nm.lower()}_{inst} {node_name(n1, inst)} {node_name(n2, inst)} {_fmt(ohm)}")
        for nm, n1, n2, f in arr["cap"]:
            a(f"{nm.lower()}_{inst} {node_name(n1, inst)} {node_name(n2, inst)} {_fmt(f)}")
        # ideal drivers: 0 V sources tie each hub to its shared drive node (or 0 / vdd / vrbl)
        for r in range(N_ROWS):
            a(f"vdw_{inst}_{r} wl_{r}_{inst} {WL_NODE[sc['wl']] if r == 0 else '0'} dc 0")
            a(f"vdr_{inst}_{r} rwl_{r}_{inst} vdd dc 0")
        for c in range(N_COLS):
            a(f"vdb_{inst}_{c} bl_{c}_{inst} {BL_NODE[sc['bl'][c]]} dc 0")
            a(f"vdp_{inst}_{c} rbl_{c}_{inst} vrbl dc 0")
        # initial conditions: stored levels on the hub and both terminal nodes; driven nets at their idle value
        nets = {n for (_nm, d, g, s, b, _p) in arr["mos"] for n in (d, g, s)} | {
            n for (_nm, n1, n2, _o) in arr["res"] for n in (n1, n2)}
        for net in sorted(nets):
            mm = re.fullmatch(r"(sn|bl|rbl|rwl|wl)_(\d+)(?:_(\d+))?(__t\d+)?", net)
            if not mm:
                continue
            kind, i1, i2, tail = mm.group(1), mm.group(2), mm.group(3), mm.group(4)
            if kind == "sn":
                val = stored_level(sc, int(i1), int(i2))
            elif kind == "bl":
                bln = sc["bl"][int(i1)]
                val = 0.0 if bln == "zero" or bln.startswith("hi") else VDD_V
            elif kind == "rbl":
                val = VRBL_V
            elif kind == "rwl":
                val = VDD_V
            else:
                val = 0.0
            if kind == "sn" or tail:
                ics.append(f"v({node_name(net, inst)})={_fmt(val)}")
        a("")
    a("* initial conditions (tran uic): stored levels, driven nets at their idle level")
    for k in range(0, len(ics), 4):
        a(".ic " + " ".join(ics[k:k + 4]))
    a("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# measurements
# ---------------------------------------------------------------------------
def meas_name(kind: str, inst: str, r: int, c: int, tag: str) -> str:
    return f"{kind}_{inst}_{r}{c}_{tag}"


def build_request() -> dict:
    meas = []
    for sc in scenarios():
        inst = sc["name"]
        for r in range(N_ROWS):
            for c in range(N_COLS):
                node = f"v(sn_{r}_{c}_{inst})"
                if sc["family"].startswith("hs_"):
                    c0 = T_START_S
                    t_lo, t_hi = c0 + T_WL_ON_S + 0.5e-9, c0 + T_WL_ON_S + T_WL_W_S
                    t_post = c0 + T_CYC_S - T_SETTLE_S
                    for tag, expr in (
                        ("pre", f"FIND {node} AT={_fmt(PRE_T_S * 1e9)}n"),
                        ("post", f"FIND {node} AT={_fmt(t_post * 1e9)}n"),
                    ) + ((
                        ("min", f"MIN {node} FROM={_fmt(t_lo * 1e9)}n TO={_fmt(t_hi * 1e9)}n"),
                        ("max", f"MAX {node} FROM={_fmt(t_lo * 1e9)}n TO={_fmt(t_hi * 1e9)}n"),
                    ) if r == 0 else ()):
                        nm = meas_name("hs", inst, r, c, tag)
                        meas.append({"name": nm, "unit": "V", "spice": f".meas tran {nm} {expr}"})
                else:
                    for n in N_SET:
                        nm = meas_name("sn", inst, r, c, f"n{n}")
                        meas.append({"name": nm, "unit": "V",
                                     "spice": f".meas tran {nm} FIND {node} AT={_fmt(checkpoint_time_s(n) * 1e9)}n"})
    stop = _fmt(T_STOP_S * 1e9)
    return {
        "netlist": "write_disturb.spice",
        "engine": "ngspice",
        "backend": "batch",
        "models": {"pdk": "sky130A", "lib": "libs.tech/combined/sky130.lib.spice"},
        "corners": {"process": PROCESS_CORNERS, "temperature_c": TEMPS_C},
        "analysis": {"kind": "tran",
                     "args": f"{_fmt(TRAN_STEP_S * 1e12)}p {stop}n 0 {_fmt(TRAN_MAX_S * 1e12)}p uic"},
        "measurements": meas,
        "options": {"timeout_s": 3600, "keep_artifacts": False, "waveforms": False},
    }


def render() -> tuple[str, str]:
    return build_netlist(), json.dumps(build_request(), indent=1) + "\n"


def main() -> int:
    net, req = render()
    NETLIST_PATH.write_text(net)
    REQUEST_PATH.write_text(req)
    print(f"wrote {NETLIST_PATH.name} ({len(scenarios())} instances) and {REQUEST_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
