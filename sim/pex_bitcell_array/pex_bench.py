"""Shared bench construction and DUT checks for the `klt pex`
schematic-vs-extracted retention comparison (issue #383).

The study measures one spec row, the stored-'1 hold-decay retention time
`t_ret_tran_s`, on both legs of two layouts (`layout/gain_cell_2t.gds`,
`layout/gain_cell_2t_array.gds`) driven through `klt pex
--measure-command` (klt 0.9.1). `klt pex` hands each leg's netlist to
`measure_pex_retention.py`, which builds a write/read/hold transient bench
around it with the helpers here, runs it as a `klt sim` batch grid, and
reduces the crossing exactly the way `sim/bitcell-transient/` (issue #182)
does -- this module is the single copy of the bench geometry so the two
legs' decks differ ONLY in the inlined DUT block.

What lives here:
  * CELLS -- the per-cell facts: layout, expected flat top name and
    ORDERED pin list (asserted against both the committed
    `layout/*.extract.parasitics.spice` header and every fresh leg klt
    hands over, so a pin-order drift can never silently scramble the X
    instantiation), expected sky130 device count, and the selected array
    cell's drive mapping.
  * DUT checks -- parse the flat `.SUBCKT` header, count the
    `sky130_fd_pr__nfet_01v8` instances, and union-find the resistor
    network so every MOS body is shown to reach the GND pin (the
    extractor's substrate reference alone does not establish that path;
    see the bitcell header `RGND_t0 GND__t0 GND 73.19` ties).
  * bench rendering -- the write/read/hold stimulus of
    `sim/bitcell-transient/tb_bitcell_transient.spice.tmpl` (timing parsed
    from that template's own `.param` block via `gen_bitcell_transient`),
    with the template's lumped extracted `c_sn` deliberately OMITTED so
    the fresh extract supplies the storage node's wiring capacitance
    exactly once (the schematic leg is the pre-layout circuit: device
    capacitance only, no lumped stand-in).

Stdlib only; no klt, no ngspice, no network -- CI runs the tests in
`test_pex_bitcell_array.py` against this module offline.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

STUDY_DIR = Path(__file__).resolve().parent
SIM_DIR = STUDY_DIR.parent
REPO_ROOT = SIM_DIR.parent

sys.path.insert(0, str(SIM_DIR))
sys.path.insert(0, str(SIM_DIR / "bitcell-transient"))
sys.path.insert(0, str(SIM_DIR / "retention"))

from _evidence_common import join_lines  # noqa: E402
import gen_bitcell_transient as G  # noqa: E402
import run_bitcell_transient as R  # noqa: E402

#: The sky130 subcircuit every device on both legs instantiates
#: (design/gain_cell_2t.spice cards; a --pdk-bound extraction writes the
#: same name -- extract.md "SPICE model binding").
NFET_MODEL = "sky130_fd_pr__nfet_01v8"

from reduce_bitcell_transient import ladder_crossing  # noqa: E402

#: Ratified worst-case single-cell retention benchmark,
#: spec/retention-refresh-budget.md §5 (the §7 5.03 us refresh interval is
#: a different quantity and is NOT this limit).
T_RET_MIN_S = 1.005989e-05

#: Sense margin, the same labelled ASSUMPTION the bitcell-transient study
#: carries (delta_V = VDD/2 = 0.9 V; sim/retention/ "Sense margin").
DELTA_V_V = R.DEFAULT_DELTA_V

_COMMITTED_BITCELL_EXTRACT = REPO_ROOT / "layout" / "gain_cell_2t.extract.parasitics.spice"
_COMMITTED_ARRAY_EXTRACT = REPO_ROOT / "layout" / "gain_cell_2t_array.extract.parasitics.spice"

_ARRAY_PINS = (
    ["GND"]
    + [f"bl_{c}" for c in range(4)]
    + [f"rbl_{c}" for c in range(4)]
    + [f"rwl_{r}" for r in range(4)]
    + [f"sn_{r}_{c}" for r in range(4) for c in range(4)]
    + [f"wl_{r}" for r in range(4)]
)

CELLS: dict[str, dict] = {
    "bitcell": {
        "layout": "layout/gain_cell_2t.gds",
        "top": "gain_cell_2t_layout_0",
        "pins": ["GND", "bl", "rbl", "rwl", "sn", "wl"],
        "committed_extract": _COMMITTED_BITCELL_EXTRACT,
        "reference": STUDY_DIR / "reference" / "gain_cell_2t_schematic.spice",
        "nfet_count": 2,
        "selected_sn": "sn",
        "sn_nets": ["sn"],
    },
    "array": {
        "layout": "layout/gain_cell_2t_array.gds",
        "top": "gain_cell_2t_array_4x4_layout_0",
        "pins": _ARRAY_PINS,
        "committed_extract": _COMMITTED_ARRAY_EXTRACT,
        "reference": STUDY_DIR / "reference" / "gain_cell_2t_array_4x4_schematic.spice",
        "nfet_count": 32,
        # The array cell both legs measure: row 0, column 0 (sn_0_0),
        # named by the issue; the neighbouring cells' documented state is
        # in build_bench()'s stimulus comments.
        "selected_sn": "sn_0_0",
        "sn_nets": [f"sn_{r}_{c}" for r in range(4) for c in range(4)],
    },
}


class BenchError(RuntimeError):
    """A DUT or bench-construction violation that must stop the run."""


# ---------------------------------------------------------------------------
# flat-netlist parsing
# ---------------------------------------------------------------------------


def subckt_header(text: str) -> tuple[str, list[str]]:
    """(name, ordered pins) of the FIRST `.SUBCKT` in a flat netlist."""
    for line in join_lines(text).splitlines():
        s = line.strip()
        if s.lower().startswith(".subckt"):
            toks = s.split()
            if len(toks) < 2:
                raise BenchError(f"malformed .SUBCKT line: {s!r}")
            return toks[1], toks[2:]
    raise BenchError("no .SUBCKT header found")


def device_cards(text: str) -> list[tuple[str, str, list[str], str]]:
    """Every device card as (kind, name, nodes, model) with `kind` one of
    X/M/R. X and M nodes are the four d/g/s/b terminals; R nodes are the
    two resistor terminals. Comment lines and all other cards are skipped."""
    out: list[tuple[str, str, list[str], str]] = []
    for line in join_lines(text).splitlines():
        s = line.strip()
        if not s or s.startswith("*") or s.startswith("."):
            continue
        toks = s.split()
        kind = toks[0][0].upper()
        if kind in ("X", "M"):
            if len(toks) < 6:
                raise BenchError(f"malformed {kind} card: {s!r}")
            out.append((kind, toks[0], toks[1:5], toks[5]))
        elif kind == "R":
            if len(toks) < 4:
                raise BenchError(f"malformed R card: {s!r}")
            out.append(("R", toks[0], toks[1:3], toks[3]))
    return out


def nfet_01v8_count(text: str) -> int:
    """Instances of the SKY130 nfet subcircuit (case-insensitive model
    token, exactly as `klt pex`'s own model_mismatch tallies cards)."""
    n = 0
    for kind, _name, _nodes, model in device_cards(text):
        if kind in ("X", "M") and model.lower() == NFET_MODEL.lower():
            n += 1
    return n


def _ground_component(text: str, gnd_pin: str) -> set[str]:
    """All nets that reach `gnd_pin` through R cards (any value) plus the
    SPICE ground aliases."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for kind, _name, nodes, _model in device_cards(text):
        if kind == "R":
            union(nodes[0], nodes[1])
    ground = {find(gnd_pin), "0", "gnd", "GND"}
    return {n for n in list(parent) if find(n) in ground} | ground


def dut_problems(text: str, cell: dict) -> list[str]:
    """Every reason this DUT text cannot serve as the cell's leg. Empty
    list = the header matches the committed extraction's ORDERED pin list,
    the SKY130 device count is exact, and every MOS body net reaches the
    GND pin through the resistor network (drawn taps / ties, not the
    extractor's capacitive substrate reference)."""
    name, pins = subckt_header(text)
    want_name, want_pins = cell["top"], cell["pins"]
    problems: list[str] = []
    if name != want_name:
        problems.append(f"top cell {name!r} != expected {want_name!r}")
    if pins != want_pins:
        problems.append(f"pin list {pins!r} != expected ordered {want_pins!r}")
    committed = subckt_header(cell["committed_extract"].read_text())
    if (name, pins) != committed:
        problems.append(
            f"header {(name, pins)!r} != committed extraction header {committed!r} "
            f"({cell['committed_extract'].name})"
        )
    n = nfet_01v8_count(text)
    if n != cell["nfet_count"]:
        problems.append(f"{NFET_MODEL} instance count {n} != expected {cell['nfet_count']}")
    gnd_comp = _ground_component(text, "GND")
    for kind, dname, nodes, model in device_cards(text):
        if kind not in ("X", "M"):
            continue
        body = nodes[3]
        if body not in gnd_comp:
            problems.append(
                f"device {dname} ({model}) body net {body!r} has no resistor path "
                "to the GND pin"
            )
    return problems


# ---------------------------------------------------------------------------
# bench rendering
# ---------------------------------------------------------------------------


def _g(x: float) -> str:
    return f"{x:.6e}"


def _param_block() -> str:
    """The write/read/hold phase block, byte-identical in shape to
    `bitcell_d1.spice`'s (parsed out of the committed template, the single
    source of truth -- never retyped here)."""
    p = G.params()
    return "\n".join(
        [
            f".param VDD    = {p['VDD']:g}",
            f".param VRBL   = {p['VDD'] / 2.0:g}",
            f".param TEDGE       = {_g(p['TEDGE'])}",
            f".param TWL_ON      = {_g(p['TWL_ON'])}",
            f".param TWL_OFF     = {_g(p['TWL_OFF'])}",
            f".param TBL_OFF     = {_g(p['TBL_OFF'])}",
            f".param TRWL_ON     = {_g(p['TRWL_ON'])}",
            f".param TRWL_OFF    = {_g(p['TRWL_OFF'])}",
            f".param THOLD_START = {_g(p['THOLD_START'])}",
            ".param VBL_DATA = 1.8",
            ".param VSN_INIT = 0",
        ]
    )


def hold_measurements_for(cell: dict, window: float) -> list[dict]:
    """The stored-'1 hold `.meas` set of `gen_bitcell_transient.
    hold_measurements(1, window)`, re-pointed at THIS cell's selected
    storage node (`sn` for the bitcell, `sn_0_0` for the array): the same
    FIND samples and the same fixed falling-crossing level ladder the
    bitcell-transient study reduces, on the node this study measures. Every
    card must name `v(sn)` exactly once or the rewrite refuses, so a
    template change cannot silently leave a card behind."""
    node = cell["selected_sn"]
    out = []
    for m in G.hold_measurements(1, window):
        spice, n = re.subn(r"v\(sn\)", f"v({node})", m["spice"])
        if n != 1:
            raise BenchError(
                f"measurement card does not name v(sn) exactly once: {m['spice']!r}"
            )
        out.append({**m, "spice": spice})
    return out


def reduce_t_ret(m: dict, window_s: float) -> dict:
    """Reduce one corner's hold measurements (the names
    `hold_measurements_for` emits) into the `t_ret_tran_s` row of the
    `klt pex` measurement document, reusing the bitcell-transient study's
    crossing reduction verbatim (`reduce_bitcell_transient.ladder_crossing`):
    the threshold is THIS leg's own `v_sn_hold_start_v` minus the 0.9 V
    sense margin, and the crossing is the cubic interpolation over the 4
    nearest crossed ladder rungs. The ladder `WHEN ... TD` values are
    relative to the hold start (validated by the study's `.meas`-vs-Python
    equivalence probe), so no hold-start subtraction happens here.

    Returns the row: `value` (seconds or None), `status` ("pass"/"fail"
    against the ratified §5 benchmark -- a measured value below it is a
    numerical failure and remains evidence -- or "error" for an unresolved
    crossing), `message` (cause + observation window, unresolved rows
    only) and the audit fields."""
    vhs = m["v_sn_hold_start_v"]
    thr = vhs - DELTA_V_V
    ladder = {mv / 1000: m.get(G.ladder_name(mv)) for mv in G.LADDER_MV}
    if thr <= R.THRESHOLD_FLOOR_V:
        t_ret = None
        cause = (
            f"threshold {thr:.6f} V at or below the {R.THRESHOLD_FLOOR_V} V floor: "
            "written level below delta_v (write-margin failure, not a retention "
            "result)"
        )
    else:
        t_ret = ladder_crossing(thr, ladder)
        if t_ret is None:
            cause = (
                f"threshold {thr:.6f} V outside the crossed .meas ladder "
                f"({G.LADDER_MV[0]}-{G.LADDER_MV[-1]} mV) within the "
                f"{window_s:.6e} s observation window"
            )
    return {
        "v_sn_hold_start_v": vhs,
        "threshold_v": thr,
        "ladder_crossed_levels_v": sorted(
            (lv, t) for lv, t in ladder.items() if t is not None
        ),
        "value": t_ret,
        "status": "error" if t_ret is None else ("pass" if t_ret >= T_RET_MIN_S else "fail"),
        **({"message": cause + f"; observation window {window_s:.6e} s"} if t_ret is None else {}),
    }


def _x_line(cell: dict) -> str:
    """The DUT instantiation: every formal bound positionally, GND bound to
    SPICE node 0 so both legs' bodies land on the bench ground, every other
    pin on a top-level net of the same name (storage nodes stay observable
    and electrically free -- no source touches an sn net)."""
    nets = ["0" if pin == "GND" else pin for pin in cell["pins"]]
    return f"Xdut {' '.join(nets)} {cell['top']}"


def _stimulus(cell: dict) -> str:
    """Write/read/hold stimulus, the single-cell sequence verbatim for the
    bitcell; the array drives the selected row/column (0, 0) with every
    unselected line held at its documented idle bias."""
    if cell["top"] == "gain_cell_2t_layout_0":
        return "\n".join(
            [
                "vwl  wl  0 pulse(0 {VDD} {TWL_ON} {TEDGE} {TEDGE} {TWL_OFF-TWL_ON-TEDGE} 1)",
                "vbl  bl  0 pwl(0 {VBL_DATA} {TBL_OFF} {VBL_DATA} {TBL_OFF+TEDGE} 0)",
                "vrwl rwl 0 pwl(0 {VDD} {TRWL_ON} {VDD} {TRWL_ON+TEDGE} 0 {TRWL_OFF} 0 {TRWL_OFF+TEDGE} {VDD})",
                "vrbl rbl 0 dc {VRBL}",
                ".ic v(sn)={VSN_INIT}",
            ]
        )
    lines = ["* selected row 0 / column 0: the single-cell write/read sequence"]
    for r in range(4):
        if r == 0:
            lines.append(
                "vwl_0 wl_0 0 pulse(0 {VDD} {TWL_ON} {TEDGE} {TEDGE} {TWL_OFF-TWL_ON-TEDGE} 1)"
            )
        else:
            lines.append(f"vwl_{r} wl_{r} 0 dc 0")
    for c in range(4):
        if c == 0:
            lines.append("vbl_0 bl_0 0 pwl(0 {VBL_DATA} {TBL_OFF} {VBL_DATA} {TBL_OFF+TEDGE} 0)")
        else:
            lines.append(f"vbl_{c} bl_{c} 0 dc 0")
    for r in range(4):
        if r == 0:
            lines.append(
                "vrwl_0 rwl_0 0 pwl(0 {VDD} {TRWL_ON} {VDD} {TRWL_ON+TEDGE} 0 {TRWL_OFF} 0 {TRWL_OFF+TEDGE} {VDD})"
            )
        else:
            lines.append(f"vrwl_{r} rwl_{r} 0 dc {{VDD}}")
    for c in range(4):
        lines.append(f"vrbl_{c} rbl_{c} 0 dc {{VRBL}}")
    lines.append("* every storage node starts empty (stored '0'); sn_0_0 is then written '1'")
    lines.extend(f".ic v({sn})={{VSN_INIT}}" for sn in cell["sn_nets"])
    lines.append(
        "* unselected-line biases during hold: wl_*=0, bl_*=0 (write path off),"
        " rwl_*=VDD (rows deselected, active-low read), rbl_*=VRBL"
    )
    return "\n".join(lines)


def build_bench(dut_text: str, cell: dict, side: str, netlist_path: str, sha: str) -> str:
    """The per-side `klt sim` circuit body: header comments with the leg's
    identity and DUT content hash, the phase `.param` block, the DUT
    inlined VERBATIM (no `.include` -- the harness builds each side's deck
    itself in --measure-command mode, and a self-contained deck needs
    nothing from the transport), the X instantiation, and the stimulus.
    No `.lib`/`.temp`/`.control`/`.end`: klt appends them per corner."""
    return "\n".join(
        [
            f"* bench_{side} -- write/read/hold transient for the {cell['top']} {side} leg (issue #383).",
            "* GENERATED by measure_pex_retention.py via pex_bench.build_bench(); do not edit.",
            "* Circuit body for `klt sim`: the PDK .lib / .temp are appended per corner by klt;",
            "* analysis and .meas cards are in the sibling request_*.json.",
            "* Same phase timing / bias as sim/bitcell-transient/bitcell_d1.spice (parsed from",
            "* tb_bitcell_transient.spice.tmpl -- single source of truth). The template's lumped",
            f"* extracted c_sn is OMITTED: the {'fresh extraction supplies' if side == 'extracted' else 'pre-layout leg carries no'}",
            "* storage-node wiring capacitance exactly once.",
            f"* {side}-leg DUT, inlined verbatim from {netlist_path} (sha256:{sha}).",
            "*",
            _param_block(),
            dut_text.rstrip("\n"),
            "",
            _x_line(cell),
            "* substrate DC reference: the extraction declares .GLOBAL vsubs and ties it",
            "* through 1e12 ohm; an explicit 0 V source anchors it on BOTH legs (a coupling-",
            "* capacitance delta needs a real AC ground, which a 1 Tohm tie is not). On the",
            "* schematic leg the node simply does not exist in the DUT and the source is idle.",
            "Vvsubs vsubs 0 DC 0",
            "",
            _stimulus(cell),
            "",
        ]
    )
