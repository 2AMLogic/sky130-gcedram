#!/usr/bin/env python3
"""Generate the bitcell-transient decks and `klt sim` batch requests (issue #182).

Stdlib only. Expresses the grid that ``run_bitcell_transient.py`` runs as a local
``ngspice -b`` loop as committed ``klt sim`` corner requests, so it can go to the batch
fleet instead:

* ``bitcell_d1.spice`` / ``bitcell_d0.spice``  circuit bodies (stored '1' / '0') for
  ``klt sim``: no ``.lib``/``.temp``/``.control``/``.end`` (klt appends them per
  corner). The two access/read devices are copied VERBATIM from
  ``design/gain_cell_2t.spice`` (no absolute ``.include`` -- a batch worker cannot read
  one); the generator records the design netlist's sha256 in the deck header and the
  test fails if the two drift. Phase timing / bias come from the ``.param`` block of
  ``tb_bitcell_transient.spice.tmpl`` (the single source of truth, as for the driver).
* ``request_hold_d{1,0}_t{-40,27,125}.json``  one request per (stored value, temperature)
  over the 5 process corners; ``.tran`` window sized ONCE, here, from the current-pin
  (``f6eeac7``) leakage rows only. ``.meas`` reductions equivalent to ``measure()``.
* ``request_read_d{1,0}.json``  the separate short fine-``tmax`` (TEDGE/10) read-phase
  request (``read_phase_window()``), all 15 PVT points.

The driver's grow-up-to-3-times loop cannot run on the fleet; it is replaced by a fixed
window (HOLD_WINDOW_SLACK x the analytic estimate, worst corner of each temperature) and
``reduce_bitcell_transient.py`` checks the threshold crossing fell inside it.

Re-run after editing; ``test_gen_bitcell_transient.py`` fails if committed files are stale.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM = HERE.parent
REPO = SIM.parent
sys.path.insert(0, str(SIM))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SIM / "retention"))
from _evidence_common import PDK_OPEN_PDKS_COMMIT, sha256_prefixed  # noqa: E402
from klt_request import build_request as klt_request  # noqa: E402
from derive_retention import load_extracted_c_sn  # noqa: E402
import run_bitcell_transient as R  # noqa: E402

PROCESS_CORNERS = list(R.DEFAULT_CORNERS)
TEMPS_C = list(R.DEFAULT_TEMPS_C)
DESIGN = REPO / "design" / "gain_cell_2t.spice"
EXTRACT_JSON = R.EXTRACT_JSON
TEMPLATE = R.TEMPLATE_PATH
PIN = PDK_OPEN_PDKS_COMMIT
MEAS_PRECISION = {"ngspice_init": ["set measureprec=12", "set numdgt=12"]}


class GenError(ValueError):
    pass


#: The current-pin leakage loader, delegated to the driver's single
#: definition (malformed CSV rows are skipped there, not KeyError-crashed).
load_leakage_current_pin = R.load_leakage_by_point


def design_device_lines(path: Path = DESIGN) -> list[str]:
    """Device cards (+ continuations) and .GLOBAL from the derived design netlist."""
    out = []
    for line in Path(path).read_text().splitlines():
        s = line.strip()
        if s.upper().startswith(("XM_", "+", ".GLOBAL")):
            out.append(line.rstrip())
    if not any(l.upper().startswith("XM_WR") for l in out) or not any(l.upper().startswith("XM_RD") for l in out):
        raise GenError(f"{path}: expected XM_WR and XM_RD device cards")
    return out


def hold_window_s(leak: dict, temp_c: int, c_sn_ff: float, delta_v: float = R.DEFAULT_DELTA_V,
                  corner: str | None = None) -> float:
    """Fixed hold window: the driver's seed (HOLD_WINDOW_SLACK x analytic estimate) for one
    corner, or the longest over all corners at this temperature when `corner` is None."""
    wins = []
    for c in ([corner] if corner else PROCESS_CORNERS):
        i = leak.get((c, temp_c))
        if i is None or i <= 0:
            raise GenError(f"no {PIN[:7]} leakage row for corner={c} temp_c={temp_c}")
        wins.append(R.seed_hold_window(i, c_sn_ff, delta_v))
    return max(wins)


#: The `.tran` step clamp, delegated to the driver's single definition.
tmax_for = R.tmax_for


def params() -> dict:
    return R.parse_template_params(TEMPLATE.read_text())


def g(x: float) -> str:
    return f"{x:.6e}"


def param_block(stored: int, p: dict | None = None) -> str:
    """The write/read/hold phase `.param` block, parsed out of the committed
    template -- the single source of truth. `VBL_DATA` / `VSN_INIT` track the
    template's VDD for this stored value."""
    p = params() if p is None else p
    vdd = p["VDD"]
    vbl = vdd if stored == 1 else 0.0
    vsn = 0.0 if stored == 1 else vdd
    return "\n".join(
        [
            f".param VDD    = {vdd:g}",
            f".param VRBL   = {vdd / 2.0:g}",
            f".param TEDGE       = {g(p['TEDGE'])}",
            f".param TWL_ON      = {g(p['TWL_ON'])}",
            f".param TWL_OFF     = {g(p['TWL_OFF'])}",
            f".param TBL_OFF     = {g(p['TBL_OFF'])}",
            f".param TRWL_ON     = {g(p['TRWL_ON'])}",
            f".param TRWL_OFF    = {g(p['TRWL_OFF'])}",
            f".param THOLD_START = {g(p['THOLD_START'])}",
            f".param VBL_DATA = {vbl:g}",
            f".param VSN_INIT = {vsn:g}",
        ]
    )


#: The single-cell stimulus waveform cards, verbatim from the template's
#: bench section (plain strings: the {BRACE} tokens are ngspice's, not
#: f-string interpolation).
WL_PULSE = "vwl  wl  0 pulse(0 {VDD} {TWL_ON} {TEDGE} {TEDGE} {TWL_OFF-TWL_ON-TEDGE} 1)"
BL_PWL = "vbl  bl  0 pwl(0 {VBL_DATA} {TBL_OFF} {VBL_DATA} {TBL_OFF+TEDGE} 0)"
RWL_PWL = "vrwl rwl 0 pwl(0 {VDD} {TRWL_ON} {VDD} {TRWL_ON+TEDGE} 0 {TRWL_OFF} 0 {TRWL_OFF+TEDGE} {VDD})"


def single_cell_stimulus() -> str:
    """The five write/read/hold stimulus cards of the template's bench,
    verbatim -- the single definition shared by this generator's decks and
    the pex_bitcell_array bench."""
    return "\n".join(
        [
            WL_PULSE,
            BL_PWL,
            RWL_PWL,
            "vrbl rbl 0 dc {VRBL}",
            ".ic v(sn)={VSN_INIT}",
        ]
    )


def render_deck(stored: int, c_sn_ff: float) -> str:
    p = params()
    body = "\n".join(design_device_lines())
    return f"""* bitcell_d{stored}.spice -- 2T-min bitcell write / read / hold transient, stored '{stored}' (issue #182).
* GENERATED by gen_bitcell_transient.py; do not edit. Circuit body for `klt sim`: the PDK .lib / .temp
* are appended per corner by klt; analysis and .meas cards are in request_*.json.
* Same circuit as tb_bitcell_transient.spice.tmpl (phase timing / bias parsed from its .param block).
* Device cards copied verbatim from design/gain_cell_2t.spice ({sha256_prefixed(DESIGN)}).
* c_sn = {c_sn_ff:.6f} fF: extracted total for `sn` (layout/gain_cell_2t.extract.parasitics.json).
{param_block(stored, p)}
{body}
c_sn sn 0 {c_sn_ff * 1e-15:.6e}
{single_cell_stimulus()}
"""


def _m(name: str, unit: str, spice: str) -> dict:
    return {"name": name, "unit": unit, "spice": spice}


# ngspice rejects an AT exactly on the last .tran point ("out of interval"), so the
# hold-end sample is taken 1 ns inside tstop (change in V(sn) over 1 ns is < 1e-5 V).
HOLD_END_BACKOFF_S = 1e-9
LADDER_MV = list(range(50, 401, 25))  # crossing-level ladder, mV (stored '1' only)


def ladder_name(mv: int) -> str:
    return f"t_lvl_{mv:04d}mv"


def hold_tstop(window: float) -> float:
    """tstop rounded to the 6 significant digits it is written with, so the
    `.tran` stop and the hold-end `.meas` instant are the same number."""
    return float(g(params()["THOLD_START"] + window))


def hold_measurements(stored: int, window: float) -> list[dict]:
    p = params()
    th = p["THOLD_START"]
    tstop = hold_tstop(window)
    window = tstop - th
    t_pre = p["TRWL_ON"] - 5 * p["TEDGE"]
    t_rend = p["TRWL_OFF"] - 5 * p["TEDGE"]
    ms = [
        _m("v_sn_end_wl_pulse_v", "V", f".meas tran v_sn_end_wl_pulse_v FIND v(sn) AT={g(p['TWL_OFF'])}"),
        _m("v_sn_after_write_settled_v", "V", f".meas tran v_sn_after_write_settled_v FIND v(sn) AT={g(t_pre)}"),
        _m("v_sn_read_gate_v", "V", f".meas tran v_sn_read_gate_v FIND v(sn) AT={g(t_rend)}"),
        _m("v_sn_hold_start_v", "V", f".meas tran v_sn_hold_start_v FIND v(sn) AT={g(th)}"),
        _m("v_sn_slope_end_v", "V", f".meas tran v_sn_slope_end_v FIND v(sn) AT={g(th + 0.02 * window)}"),
        _m("v_sn_hold_end_v", "V", f".meas tran v_sn_hold_end_v FIND v(sn) AT={g(tstop - HOLD_END_BACKOFF_S)}"),
    ]
    if stored == 1:
        # A .meas card cannot read another .meas result, so the data-dependent
        # threshold (v_sn_hold_start_v - delta_V) cannot be a WHEN target. Record
        # the first falling crossing time of a fixed level ladder instead; the
        # reducer interpolates t_ret at the threshold between adjacent rungs.
        for mv in LADDER_MV:
            ms.append(_m(ladder_name(mv), "s",
                         f".meas tran {ladder_name(mv)} WHEN v(sn)={mv / 1000:g} FALL=1 TD={g(th)}"))
    return ms


def read_measurements() -> list[dict]:
    p = params()
    return [
        _m("i_rbl_deselect_raw_a", "A", f".meas tran i_rbl_deselect_raw_a FIND i(vrbl) AT={g(p['TRWL_ON'] - 5 * p['TEDGE'])}"),
        _m("i_read_raw_a", "A", f".meas tran i_read_raw_a FIND i(vrbl) AT={g(p['TRWL_OFF'] - 5 * p['TEDGE'])}"),
    ]


def tag_t(t: int) -> str:
    return f"tm{-t}" if t < 0 else f"t{t}"


def hold_name(stored: int, t: int, corner: str | None = None) -> str:
    """Stored '1' is one request per (corner, temp) -- each point's window is sized from its own
    leakage, as the driver does; stored '0' (no retention crossing) is one request per temp."""
    return f"request_hold_d{stored}_{corner + '_' if corner else ''}{tag_t(t)}.json"


def read_name(stored: int) -> str:
    return f"request_read_d{stored}.json"


def build_hold(stored: int, t: int, window: float, corner: str | None = None) -> dict:
    th = params()["THOLD_START"]
    args = f"{R.TSTEP} {g(hold_tstop(window))} 0 {g(tmax_for(window))}"
    return klt_request(f"bitcell_d{stored}.spice", {"process": [corner] if corner else list(PROCESS_CORNERS), "temperature_c": [t]},
                       args, hold_measurements(stored, window), 3600, extra_options=MEAS_PRECISION)


def build_read(stored: int) -> dict:
    tstop, tmax = R.read_phase_window(params())
    args = f"{R.TSTEP} {g(tstop)} 0 {g(tmax)}"
    return klt_request(f"bitcell_d{stored}.spice", {"process": list(PROCESS_CORNERS), "temperature_c": list(TEMPS_C)},
                       args, read_measurements(), 1800, extra_options=MEAS_PRECISION)


def render_all() -> dict[str, str]:
    c_sn_ff, _ = load_extracted_c_sn(EXTRACT_JSON, "sn")
    leak = load_leakage_current_pin()
    files = {f"bitcell_d{d}.spice": render_deck(d, c_sn_ff) for d in (1, 0)}
    for d in (1, 0):
        for t in TEMPS_C:
            for c in (PROCESS_CORNERS if d == 1 else [None]):
                w = hold_window_s(leak, t, c_sn_ff, corner=c)
                files[hold_name(d, t, c)] = json.dumps(build_hold(d, t, w, c), indent=2) + "\n"
        files[read_name(d)] = json.dumps(build_read(d), indent=2) + "\n"
    return files


def main() -> int:
    for name, text in render_all().items():
        (HERE / name).write_text(text)
        print(f"wrote {HERE / name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
