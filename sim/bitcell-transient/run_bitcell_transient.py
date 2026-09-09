#!/usr/bin/env python3
"""2T-min bitcell transient write / read / hold PVT sweep (issue #27).

The first circuit-level simulation of this repo's ratified bitcell.
`sim/leakage/` is a DC operating point on a single access device and
`sim/retention/` is an analytic `t = C_SN * delta_V / I_leak` derivation --
neither exercises the cell as a circuit. This driver renders
`tb_bitcell_transient.spice.tmpl` (which includes `design/gain_cell_2t.spice`
verbatim), runs one `.tran` per (corner, temperature, stored value) across
the full 15-point PVT grid, and appends the measured write levels, read
currents and hold-decay times to
`results/bitcell_transient_results.csv`.

Usage:
    python3 sim/bitcell-transient/run_bitcell_transient.py --check-env
    python3 sim/bitcell-transient/run_bitcell_transient.py
    python3 sim/bitcell-transient/run_bitcell_transient.py --c-sn-ff 0
    python3 sim/bitcell-transient/run_bitcell_transient.py --dry-run
    python3 sim/bitcell-transient/run_bitcell_transient.py \
        --corners sf --temps-c 125 --tmax-ns 1   # numerics convergence check

Stdlib only, no virtualenv required. Uses ONLY the shipped sky130 PDK
model library resolved below -- no local model edits, no uncommitted
.include paths. Requires `ngspice` on PATH and a stock volare/open_pdks
sky130A install (see sim/README.md for the install command).

Provenance/append-only handling is NOT reimplemented here: `resolve_pdk_root`,
`repo_git_sha` and `append_result` all come from `sim/_evidence_common.py`
(issue #11), and the default lumped storage-node capacitance is read through
`sim/retention/derive_retention.py`'s own `load_extracted_c_sn()` so the two
studies can never disagree about what the extracted `C_SN` is.

This script never overwrites results/bitcell_transient_results.csv -- it
always appends (creating the file with a header on first run), per
CLAUDE.md's "sim/ results are append-only evidence."

WHAT IS MEASURED, AND WHERE THE MEASUREMENT INSTANTS COME FROM
--------------------------------------------------------------
Every sampling instant below is parsed out of the `.param` block of
`tb_bitcell_transient.spice.tmpl` at run time (see `parse_template_params`),
never hard-coded here, so the deck's waveform and this driver's sampling
points cannot drift apart. Per (corner, temp, stored value):

  v_sn_end_wl_pulse_v        V(sn) at TWL_OFF -- the instant the wordline
                             fall begins. This is the plain-VDD write
                             ceiling (VDD - Vth of M_WR), the number
                             design/README.md previously quoted from an
                             uncommitted tt-only DC smoke check.
  v_sn_after_write_settled_v V(sn) just before the read pulse -- the level
                             actually retained, i.e. the ceiling above
                             MINUS the wordline-to-storage-node
                             feedthrough step that a DC check cannot see.
  i_rbl_deselect_a           |i(vrbl)| just before the read pulse: what one
                             DESELECTED cell injects into the read bitline.
  v_sn_read_gate_v           V(sn) at the end of the read pulse -- the gate
                             drive M_RD actually sees, after `rwl`'s falling
                             edge couples down onto the floating node.
  i_read_a                   |i(vrbl)| at the end of the read pulse.
  v_sn_read_disturb_v        V(sn) after the read minus V(sn) before it.
  v_sn_hold_start_v          V(sn) at THOLD_START: the level the hold-phase
                             decay starts from, and the reference the
                             sense-margin threshold is taken below.
  dvdt_hold_start_v_per_s    Secant slope of V(sn) over the first 2 % of the
                             hold window.
  t_ret_tran_s               SIMULATED time, from THOLD_START, for V(sn) to
                             fall by delta_v (default 0.9 V) -- linearly
                             interpolated between the two bracketing
                             timepoints. Blank when the threshold is
                             unreachable, i.e. when the written level is
                             itself below delta_v (a WRITE-margin failure,
                             not a retention result -- see the README).
  t_ret_linear_extrap_s      delta_v / |dvdt_hold_start| -- the same
                             constant-current linear-decay approximation
                             sim/retention/derive_retention.py uses, but
                             with the slope MEASURED here instead of
                             computed from an assumed C_SN and the DC
                             leakage number. Defined at every corner, so
                             it is the apples-to-apples cross-check against
                             the analytic figure.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from shutil import which

SIM_BITCELL_DIR = Path(__file__).resolve().parent
SIM_DIR = SIM_BITCELL_DIR.parent
REPO_ROOT = SIM_DIR.parent

sys.path.insert(0, str(SIM_DIR))
from _evidence_common import append_result, repo_git_sha, resolve_pdk_root  # noqa: E402

sys.path.insert(0, str(SIM_DIR / "retention"))
from derive_retention import load_extracted_c_sn  # noqa: E402

TEMPLATE_PATH = SIM_BITCELL_DIR / "tb_bitcell_transient.spice.tmpl"
RESULTS_CSV = SIM_BITCELL_DIR / "results" / "bitcell_transient_results.csv"
DESIGN_NETLIST = REPO_ROOT / "design" / "gain_cell_2t.spice"
EXTRACT_JSON = REPO_ROOT / "layout" / "gain_cell_2t.extract.parasitics.json"
LEAKAGE_CSV = SIM_DIR / "leakage" / "results" / "leakage_results.csv"

DEFAULT_CORNERS = ["tt", "ss", "ff", "sf", "fs"]
DEFAULT_TEMPS_C = [-40, 27, 125]
DEFAULT_NGSPICE_LIB_REL = "libs.tech/combined/sky130.lib.spice"
DEFAULT_PDK_VARIANT = "sky130A"
PDK_OPEN_PDKS_COMMIT = "c6d73a35f524070e85faff4a6a9eef49553ebc2b"

# Sense margin. Same labelled ASSUMPTION sim/retention/README.md "Sense
# margin" carries (delta_V = VDD/2 = 0.9 V, the coarse half-VDD bound used
# absent a sense-amplifier offset/noise budget). Kept identical on purpose:
# this study's whole point is to be comparable to that derivation.
DEFAULT_DELTA_V = 0.9

# .tran numerics. `tstep` is only ngspice's suggested initial/print step --
# the accepted timepoints are LTE-controlled, with breakpoints forced at
# every source-waveform corner, so the nanosecond-scale write/read edges
# stay resolved even when `tmax` is sized for the microsecond-to-
# millisecond hold window. `tmax` is derived per run as
# clamp(hold_window / TMAX_DIVISOR, TMAX_MIN_S, TMAX_MAX_S); see the
# README's "Numerics: .tran settings and the convergence check" for the
# tmax sweep that justifies these values.
TSTEP = "10p"
TMAX_DIVISOR = 2000
TMAX_MIN_S = 1e-9
TMAX_MAX_S = 5e-6

# Hold-window sizing. The window is seeded from the analytic estimate
# C_est * delta_V / I_leak, using the DC leakage already recorded for the
# same (corner, temp) in sim/leakage/, then multiplied by HOLD_WINDOW_SLACK
# because the transient decay is expected to be SLOWER than that estimate
# (the node starts below VDD, so its leakage starts below the recorded
# Vds = VDD value, and it falls further as the node discharges). If the
# threshold is still not crossed the window is grown and the point re-run.
C_INTRINSIC_EST_FF = 0.30  # rough allowance for the device models' own
# storage-node capacitance (M_RD gate + M_WR drain junction/overlap). Used
# ONLY to size the simulation window -- it is not a reported quantity and
# never enters a recorded result.
HOLD_WINDOW_SLACK = 12.0
HOLD_WINDOW_MIN_S = 1e-6
HOLD_WINDOW_MAX_S = 8e-3
HOLD_WINDOW_GROWTH = 4.0
HOLD_WINDOW_ATTEMPTS = 3
# A threshold this close to the bitline rail (0 V) is approached only
# asymptotically; growing the window would never resolve it, so it is
# reported as unreachable rather than retried.
THRESHOLD_FLOOR_V = 0.05

CSV_FIELDS = [
    "timestamp_utc",
    "repo_git_sha",
    "pdk_open_pdks_commit",
    "ngspice_version",
    "corner",
    "temp_c",
    "stored_value",
    "c_sn_ff",
    "c_sn_source",
    "vdd_v",
    "vrbl_bias_v",
    "t_edge_ns",
    "t_wl_pulse_ns",
    "t_rwl_pulse_ns",
    "tmax_s",
    "tstop_s",
    "v_sn_end_wl_pulse_v",
    "v_sn_after_write_settled_v",
    "v_sn_read_gate_v",
    "i_read_a",
    "i_rbl_deselect_a",
    "i_read_ratio_1_over_0",
    "v_sn_read_disturb_v",
    "v_sn_hold_start_v",
    "v_sn_hold_end_v",
    "hold_window_s",
    "dvdt_hold_start_v_per_s",
    "delta_v_sense_margin_v_ASSUMPTION",
    "t_ret_tran_s",
    "t_ret_linear_extrap_s",
    "notes",
]

SI_SUFFIX = {
    "f": 1e-15,
    "p": 1e-12,
    "n": 1e-9,
    "u": 1e-6,
    "m": 1e-3,
    "k": 1e3,
    "meg": 1e6,
    "g": 1e9,
}

PARAM_RE = re.compile(r"^\.param\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(\S+)\s*$")

# Phase-timing parameters that follow the write pulse and must therefore
# shift with it when --t-wl-pulse-ns changes the wordline pulse width.
DOWNSTREAM_TIMING_PARAMS = ["TWL_OFF", "TBL_OFF", "TRWL_ON", "TRWL_OFF", "THOLD_START"]

# The effective testbench template for this invocation: the committed
# template, possibly with its timing .param lines rewritten by
# --t-wl-pulse-ns. Set once by main(); everything downstream (both the
# rendered deck AND the driver's measurement instants) reads from this same
# text, so a timing override can never desynchronise the two.
_TEMPLATE_TEXT: str | None = None


def effective_template() -> str:
    if _TEMPLATE_TEXT is None:  # pragma: no cover - programming error
        raise RuntimeError("effective_template() used before main() set it")
    return _TEMPLATE_TEXT


def rewrite_param(template: str, name: str, value_s: float) -> str:
    """Rewrite one literal `.param NAME = <time>` line, in seconds."""
    pattern = re.compile(rf"^(\.param\s+{name}\s*=\s*)(\S+)\s*$", re.MULTILINE)
    new, n = pattern.subn(rf"\g<1>{value_s:.6e}", template)
    if n != 1:
        raise RuntimeError(f"expected exactly one `.param {name}` line, found {n}")
    return new


def apply_wl_pulse_override(template: str, new_width_s: float) -> str:
    """Widen/narrow the write-wordline pulse, shifting every later phase by
    the same delta so the read and hold phases keep their relative timing.

    This exists for the write-ceiling settling sensitivity check documented
    in the README: the plain-VDD write level is approached asymptotically,
    so the recorded ceiling is a function of the wordline pulse width and
    that dependence has to be measurable, not asserted.
    """
    params = parse_template_params(template)
    old_width = params["TWL_OFF"] - params["TWL_ON"]
    delta = new_width_s - old_width
    for name in DOWNSTREAM_TIMING_PARAMS:
        template = rewrite_param(template, name, params[name] + delta)
    return template


# --------------------------------------------------------------------------
# template parameters (single source of truth for timing/bias)
# --------------------------------------------------------------------------


def spice_number(text: str) -> float:
    """Parse a SPICE numeric literal with an optional engineering suffix
    (`100p`, `21n`, `1.8`). Raises on anything else -- a silently
    mis-parsed timing parameter would move a measurement instant."""
    m = re.fullmatch(r"([+-]?[0-9]*\.?[0-9]+(?:[eE][+-]?[0-9]+)?)\s*([A-Za-z]*)", text)
    if not m:
        raise ValueError(f"not a SPICE numeric literal: {text!r}")
    value = float(m.group(1))
    suffix = m.group(2).lower()
    if not suffix:
        return value
    for name in ("meg",):
        if suffix.startswith(name):
            return value * SI_SUFFIX[name]
    if suffix[0] in SI_SUFFIX:
        return value * SI_SUFFIX[suffix[0]]
    raise ValueError(f"unknown SPICE suffix in {text!r}")


def parse_template_params(template: str) -> dict[str, float]:
    """Read the literal `.param` lines out of the testbench template.

    Only lines whose value is a plain numeric literal are returned -- the
    substituted ones (`@@VRBL@@`, `@@VBL_DATA@@`, ...) are skipped, since
    this driver supplies those itself. This is what keeps the deck's
    waveform and this driver's sampling instants from drifting apart: the
    measurement instants below are the template's own numbers.
    """
    params: dict[str, float] = {}
    for line in template.splitlines():
        m = PARAM_RE.match(line.strip())
        if not m:
            continue
        name, raw = m.group(1), m.group(2)
        if raw.startswith("@@"):
            continue
        try:
            params[name] = spice_number(raw)
        except ValueError:
            continue
    required = [
        "VDD",
        "TEDGE",
        "TWL_ON",
        "TWL_OFF",
        "TBL_OFF",
        "TRWL_ON",
        "TRWL_OFF",
        "THOLD_START",
    ]
    missing = [r for r in required if r not in params]
    if missing:
        raise RuntimeError(
            f"{TEMPLATE_PATH} is missing required literal .param(s): {missing}"
        )
    # Ordering invariant: the deck only makes sense if the phases are
    # sequential and each measurement instant lands where it is meant to.
    order = [
        params["TWL_ON"],
        params["TWL_OFF"],
        params["TBL_OFF"] + params["TEDGE"],
        params["TRWL_ON"],
        params["TRWL_OFF"],
        params["THOLD_START"],
    ]
    if any(b <= a for a, b in zip(order, order[1:])):
        raise RuntimeError(
            f"{TEMPLATE_PATH} phase timing is not strictly ordered: {order}"
        )
    return params


# --------------------------------------------------------------------------
# waveform helpers (stdlib only -- no numpy)
# --------------------------------------------------------------------------


def read_wrdata(path: Path) -> tuple[list[float], list[float], list[float]]:
    """Parse an ngspice `wrdata` ASCII table.

    `wrdata out v(sn) i(vrbl)` emits one (x, y) column PAIR per vector, so
    the columns are: time, v(sn), time, i(vrbl).
    """
    t: list[float] = []
    vsn: list[float] = []
    irbl: list[float] = []
    with path.open() as f:
        for line in f:
            parts = line.split()
            if len(parts) < 4:
                continue
            try:
                row = [float(p) for p in parts]
            except ValueError:
                continue
            t.append(row[0])
            vsn.append(row[1])
            irbl.append(row[3])
    if len(t) < 3:
        raise RuntimeError(f"ngspice produced too few timepoints in {path}")
    return t, vsn, irbl


def interp_at(t: list[float], y: list[float], tq: float) -> float:
    """Linear interpolation of y(tq) on a monotonically increasing t."""
    if tq <= t[0]:
        return y[0]
    if tq >= t[-1]:
        return y[-1]
    lo, hi = 0, len(t) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if t[mid] <= tq:
            lo = mid
        else:
            hi = mid
    if t[hi] == t[lo]:
        return y[lo]
    frac = (tq - t[lo]) / (t[hi] - t[lo])
    return y[lo] + frac * (y[hi] - y[lo])


def first_crossing_below(
    t: list[float], y: list[float], threshold: float, t_from: float
) -> float | None:
    """First time at or after `t_from` where y falls to `threshold`,
    linearly interpolated between the bracketing timepoints. Returns None
    if y never reaches the threshold inside the simulated window."""
    prev_t = None
    prev_y = None
    for ti, yi in zip(t, y):
        if ti < t_from:
            continue
        if prev_t is not None and yi <= threshold < prev_y:
            if prev_y == yi:
                return ti
            frac = (prev_y - threshold) / (prev_y - yi)
            return prev_t + frac * (ti - prev_t)
        if prev_t is None and yi <= threshold:
            return ti
        prev_t, prev_y = ti, yi
    return None


# --------------------------------------------------------------------------
# environment
# --------------------------------------------------------------------------


def resolve_ngspice_lib(pdk_root: Path, variant: str) -> Path:
    return pdk_root / variant / DEFAULT_NGSPICE_LIB_REL


def check_env(ngspice_lib: Path) -> bool:
    ok = True
    if not ngspice_lib.is_file():
        print(
            f"ERROR: sky130 ngspice model library not found: {ngspice_lib}",
            file=sys.stderr,
        )
        print(
            "  Install a stock PDK with volare, e.g.:\n"
            f"    volare enable --pdk sky130 {PDK_OPEN_PDKS_COMMIT}\n"
            "  or set PDK_ROOT to an existing open_pdks sky130A install.",
            file=sys.stderr,
        )
        ok = False
    if not which("ngspice"):
        print("ERROR: `ngspice` not found on PATH.", file=sys.stderr)
        ok = False
    if not TEMPLATE_PATH.is_file():
        print(f"ERROR: testbench template not found: {TEMPLATE_PATH}", file=sys.stderr)
        ok = False
    if not DESIGN_NETLIST.is_file():
        print(
            f"ERROR: design netlist not found: {DESIGN_NETLIST} -- regenerate it "
            "with ./design/regen_netlist.sh",
            file=sys.stderr,
        )
        ok = False
    if not EXTRACT_JSON.is_file():
        print(
            f"ERROR: extracted parasitics not found: {EXTRACT_JSON} (source of the "
            "default --c-sn-ff value; pass --c-sn-ff explicitly to bypass)",
            file=sys.stderr,
        )
        ok = False
    if not LEAKAGE_CSV.is_file():
        print(
            f"ERROR: leakage results not found: {LEAKAGE_CSV} -- run "
            "sim/leakage/run_leakage_sweep.py first (used only to size the "
            "hold-phase simulation window)",
            file=sys.stderr,
        )
        ok = False
    return ok


def ngspice_version() -> str:
    try:
        out = subprocess.run(
            ["ngspice", "--version"], capture_output=True, text=True, timeout=10
        )
        for line in (out.stdout or "").splitlines():
            if "ngspice" in line.lower():
                return line.strip()
        return "unknown"
    except Exception:
        return "unknown"


def load_leakage_by_point() -> dict[tuple[str, int], float]:
    """Worst (maximum) recorded DC leakage per (corner, temp_c) from
    sim/leakage/results/leakage_results.csv. Used ONLY to size the
    hold-phase simulation window -- never as a reported result."""
    table: dict[tuple[str, int], float] = {}
    with LEAKAGE_CSV.open(newline="") as f:
        for row in csv.DictReader(f):
            try:
                key = (row["corner"], int(row["temp_c"]))
                val = float(row["ileak_a"])
            except (KeyError, ValueError):
                continue
            if key not in table or val > table[key]:
                table[key] = val
    return table


# --------------------------------------------------------------------------
# one .tran run
# --------------------------------------------------------------------------


def render_netlist(
    ngspice_lib: Path,
    corner: str,
    temp_c: int,
    c_sn_f: float,
    vrbl: float,
    vbl_data: float,
    vsn_init: float,
    tstop: float,
    tmax: float,
    out_path: Path,
) -> str:
    template = effective_template()
    subs = {
        "@@PDK_NGSPICE_LIB@@": str(ngspice_lib),
        "@@CORNER@@": corner,
        "@@TEMP_C@@": str(temp_c),
        "@@DESIGN_NETLIST@@": str(DESIGN_NETLIST),
        "@@C_SN_F@@": f"{c_sn_f:.6e}",
        "@@VRBL@@": f"{vrbl:.6f}",
        "@@VBL_DATA@@": f"{vbl_data:.6f}",
        "@@VSN_INIT@@": f"{vsn_init:.6f}",
        "@@TSTEP@@": TSTEP,
        "@@TSTOP@@": f"{tstop:.6e}",
        "@@TMAX@@": f"{tmax:.6e}",
        "@@OUT@@": str(out_path),
    }
    for key, value in subs.items():
        template = template.replace(key, value)
    leftover = re.findall(r"@@[A-Z_]+@@", template)
    if leftover:
        raise RuntimeError(f"unsubstituted template tokens remain: {sorted(set(leftover))}")
    return template


def run_tran(
    ngspice_lib: Path,
    corner: str,
    temp_c: int,
    c_sn_f: float,
    vrbl: float,
    vbl_data: float,
    vsn_init: float,
    tstop: float,
    tmax: float,
    tag: str,
) -> tuple[list[float], list[float], list[float]]:
    tmpdir = Path(tempfile.mkdtemp(prefix=f"gcedram_tran_{tag}_"))
    deck_path = tmpdir / "tb.spice"
    out_path = tmpdir / "tran.dat"
    deck_path.write_text(
        render_netlist(
            ngspice_lib,
            corner,
            temp_c,
            c_sn_f,
            vrbl,
            vbl_data,
            vsn_init,
            tstop,
            tmax,
            out_path,
        )
    )
    try:
        result = subprocess.run(
            ["ngspice", "-b", str(deck_path)],
            capture_output=True,
            text=True,
            timeout=1800,
        )
        if not out_path.is_file():
            raise RuntimeError(
                f"ngspice produced no output for {tag}\n"
                f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
            )
        return read_wrdata(out_path)
    finally:
        for p in (deck_path, out_path):
            try:
                os.unlink(p)
            except OSError:
                pass
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass


def measure(
    t: list[float],
    vsn: list[float],
    irbl: list[float],
    params: dict[str, float],
    hold_window: float,
    delta_v: float,
) -> dict:
    """Extract every scalar this study records from one .tran waveform.

    All instants come from `params` (the template's own `.param` block).
    `i(vrbl)` is negative while the cell pulls current out of the read
    bitline, so magnitudes are reported.
    """
    t_hold = params["THOLD_START"]
    # Sample a short settle time before each falling/rising edge, expressed
    # in units of the deck's own edge time so it tracks TEDGE: 5*TEDGE
    # after the previous transition has completed and before the next one
    # begins.
    t_pre_read = params["TRWL_ON"] - 5 * params["TEDGE"]
    t_read_end = params["TRWL_OFF"] - 5 * params["TEDGE"]

    v_end_wl = interp_at(t, vsn, params["TWL_OFF"])
    v_settled = interp_at(t, vsn, t_pre_read)
    i_desel = abs(interp_at(t, irbl, t_pre_read))
    v_read_gate = interp_at(t, vsn, t_read_end)
    i_read = abs(interp_at(t, irbl, t_read_end))
    v_hold_start = interp_at(t, vsn, t_hold)
    v_hold_end = interp_at(t, vsn, t_hold + hold_window)

    slope_window = 0.02 * hold_window
    dvdt = (interp_at(t, vsn, t_hold + slope_window) - v_hold_start) / slope_window

    threshold = v_hold_start - delta_v
    if threshold <= THRESHOLD_FLOOR_V:
        t_ret = None
        reachable = False
    else:
        t_cross = first_crossing_below(t, vsn, threshold, t_hold)
        t_ret = None if t_cross is None else t_cross - t_hold
        reachable = True

    return {
        "v_sn_end_wl_pulse_v": v_end_wl,
        "v_sn_after_write_settled_v": v_settled,
        "v_sn_read_gate_v": v_read_gate,
        "i_read_a": i_read,
        "i_rbl_deselect_a": i_desel,
        "v_sn_read_disturb_v": v_hold_start - v_settled,
        "v_sn_hold_start_v": v_hold_start,
        "v_sn_hold_end_v": v_hold_end,
        "dvdt_hold_start_v_per_s": dvdt,
        "t_ret_tran_s": t_ret,
        "threshold_v": threshold,
        "threshold_reachable": reachable,
    }


def run_point(
    ngspice_lib: Path,
    corner: str,
    temp_c: int,
    stored: int,
    c_sn_f: float,
    vrbl: float,
    params: dict[str, float],
    delta_v: float,
    hold_window: float,
    tmax_override: float | None,
    grow: bool,
) -> tuple[dict, float, float, float]:
    """Run one (corner, temp, stored value) point, growing the hold window
    until the sense-margin threshold is crossed (or until it is shown to be
    unreachable). Returns (measurements, hold_window, tstop, tmax)."""
    vdd = params["VDD"]
    vbl_data = vdd if stored == 1 else 0.0
    # Write '1' starts from an empty node; write '0' starts from a full
    # VDD node, so the write-'0' measurement is a genuine overwrite of the
    # strongest possible stored level rather than a no-op.
    vsn_init = 0.0 if stored == 1 else vdd

    attempts = HOLD_WINDOW_ATTEMPTS if grow else 1
    for attempt in range(attempts):
        tstop = params["THOLD_START"] + hold_window
        tmax = (
            tmax_override
            if tmax_override is not None
            else min(max(hold_window / TMAX_DIVISOR, TMAX_MIN_S), TMAX_MAX_S)
        )
        t, vsn, irbl = run_tran(
            ngspice_lib,
            corner,
            temp_c,
            c_sn_f,
            vrbl,
            vbl_data,
            vsn_init,
            tstop,
            tmax,
            f"{corner}_{temp_c}_d{stored}",
        )
        m = measure(t, vsn, irbl, params, hold_window, delta_v)
        done = (
            not m["threshold_reachable"]
            or m["t_ret_tran_s"] is not None
            or attempt == attempts - 1
            or hold_window >= HOLD_WINDOW_MAX_S
        )
        if done:
            return m, hold_window, tstop, tmax
        hold_window = min(hold_window * HOLD_WINDOW_GROWTH, HOLD_WINDOW_MAX_S)
    raise AssertionError("unreachable")


def fmt(value, spec: str = "{:.6e}") -> str:
    return "" if value is None else spec.format(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--pdk-root", default=None, help="Override PDK_ROOT")
    parser.add_argument("--pdk", default=DEFAULT_PDK_VARIANT, help="PDK variant dir")
    parser.add_argument(
        "--corners",
        default=",".join(DEFAULT_CORNERS),
        help=f"Comma-separated process corners (default: {','.join(DEFAULT_CORNERS)})",
    )
    parser.add_argument(
        "--temps-c",
        default=",".join(str(t) for t in DEFAULT_TEMPS_C),
        help="Comma-separated temperatures in C (default: -40,27,125)",
    )
    parser.add_argument(
        "--c-sn-ff",
        type=float,
        default=None,
        help=(
            "Lumped storage-node capacitance in fF added on `sn`. Default: the "
            "post-layout extracted total from layout/gain_cell_2t.extract."
            "parasitics.json (issue #7). Pass 0 for intrinsic model "
            "capacitance only."
        ),
    )
    parser.add_argument(
        "--vrbl-v",
        type=float,
        default=None,
        help="Read-bitline bias in volts (default: VDD/2 from the template's VDD)",
    )
    parser.add_argument(
        "--delta-v",
        type=float,
        default=DEFAULT_DELTA_V,
        help=f"Sense margin in volts (default: {DEFAULT_DELTA_V}, the labelled "
        "ASSUMPTION sim/retention/ uses)",
    )
    parser.add_argument(
        "--tmax-ns",
        type=float,
        default=None,
        help="Force the .tran tmax (ns) instead of deriving it from the hold "
        "window -- used for the numerics convergence check documented in the "
        "README",
    )
    parser.add_argument(
        "--t-wl-pulse-ns",
        type=float,
        default=None,
        help="Override the write-wordline pulse width (ns), shifting the read "
        "and hold phases with it -- used for the write-ceiling settling "
        "sensitivity check documented in the README",
    )
    parser.add_argument(
        "--no-grow",
        action="store_true",
        help="Do not grow the hold window when the sense-margin threshold is "
        "not crossed (one .tran per point)",
    )
    parser.add_argument("--check-env", action="store_true", help="Check inputs and exit")
    parser.add_argument(
        "--dry-run", action="store_true", help="Render decks but do not run ngspice"
    )
    args = parser.parse_args(argv)

    pdk_root = resolve_pdk_root(args.pdk_root)
    ngspice_lib = resolve_ngspice_lib(pdk_root, args.pdk)

    if args.check_env:
        ok = check_env(ngspice_lib)
        if ok:
            c_sn_ff, prov = load_extracted_c_sn(EXTRACT_JSON, "sn")
            print(f"OK: ngspice found, PDK model library found at {ngspice_lib}")
            print(f"OK: design netlist included verbatim from {DESIGN_NETLIST}")
            print(
                f"OK: default C_SN = {c_sn_ff:.6f} fF (extracted, klt "
                f"{prov['klt_version']}, {EXTRACT_JSON.name})"
            )
        return 0 if ok else 1

    if not check_env(ngspice_lib):
        return 1

    global _TEMPLATE_TEXT
    _TEMPLATE_TEXT = TEMPLATE_PATH.read_text()
    if args.t_wl_pulse_ns is not None:
        _TEMPLATE_TEXT = apply_wl_pulse_override(
            _TEMPLATE_TEXT, args.t_wl_pulse_ns * 1e-9
        )
    params = parse_template_params(_TEMPLATE_TEXT)
    vdd = params["VDD"]

    if args.c_sn_ff is None:
        c_sn_ff, prov = load_extracted_c_sn(EXTRACT_JSON, "sn")
        c_sn_source = (
            f"EXTRACTED post-layout total for net `sn` from "
            f"{EXTRACT_JSON.relative_to(REPO_ROOT)} (klt {prov['klt_version']}, "
            f"input {prov['input_content_hash']}): ground "
            f"{prov['ground_c_ff']:.6f} fF + lateral coupling to "
            f"{','.join(prov['coupled_nets'])} {prov['coupling_c_ff']:.6f} fF"
        )
    else:
        c_sn_ff = args.c_sn_ff
        c_sn_source = (
            "intrinsic device-model capacitance only (--c-sn-ff 0)"
            if c_sn_ff == 0
            else f"--c-sn-ff {c_sn_ff} override"
        )

    vrbl = args.vrbl_v if args.vrbl_v is not None else vdd / 2.0
    delta_v = args.delta_v
    corners = [c.strip() for c in args.corners.split(",") if c.strip()]
    temps_c = [int(t.strip()) for t in args.temps_c.split(",") if t.strip()]
    tmax_override = None if args.tmax_ns is None else args.tmax_ns * 1e-9

    print(f"C_SN (lumped, added on `sn`) = {c_sn_ff:.6f} fF")
    print(f"  source: {c_sn_source}")
    print(f"VDD = {vdd} V, rbl bias = {vrbl} V, sense margin delta_V = {delta_v} V")
    print(
        "phase timing (from the template's .param block): "
        + ", ".join(
            f"{k}={params[k] * 1e9:g}ns"
            for k in ("TWL_ON", "TWL_OFF", "TBL_OFF", "TRWL_ON", "TRWL_OFF", "THOLD_START")
        )
    )

    if args.dry_run:
        deck = render_netlist(
            ngspice_lib,
            corners[0],
            temps_c[0],
            c_sn_ff * 1e-15,
            vrbl,
            vdd,
            0.0,
            params["THOLD_START"] + 1e-5,
            1e-8,
            Path("/dev/null"),
        )
        print(f"--- dry-run deck: corner={corners[0]} temp_c={temps_c[0]} ---")
        print(deck)
        return 0

    leakage = load_leakage_by_point()
    sha = repo_git_sha(SIM_BITCELL_DIR)
    ver = ngspice_version()
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

    n_written = 0
    worst = None  # (t_ret_tran_s, corner, temp_c)
    weakest_write = None  # (v_sn_hold_start_v, corner, temp_c)

    for corner in corners:
        for temp_c in temps_c:
            ileak = leakage.get((corner, temp_c))
            if ileak is None or ileak <= 0:
                raise RuntimeError(
                    f"no leakage row for corner={corner} temp_c={temp_c} in "
                    f"{LEAKAGE_CSV} -- needed to size the hold window"
                )
            c_est_f = (c_sn_ff + C_INTRINSIC_EST_FF) * 1e-15
            hold_window = min(
                max(HOLD_WINDOW_SLACK * c_est_f * delta_v / ileak, HOLD_WINDOW_MIN_S),
                HOLD_WINDOW_MAX_S,
            )

            m1, hold_window, tstop, tmax = run_point(
                ngspice_lib,
                corner,
                temp_c,
                1,
                c_sn_ff * 1e-15,
                vrbl,
                params,
                delta_v,
                hold_window,
                tmax_override,
                grow=not args.no_grow,
            )
            # The stored-'0' point is deliberately run over the SAME hold
            # window the stored-'1' point needed, so "no spurious crossing
            # for a cell written low" is a statement about the same window
            # in which the '1' decayed by the full sense margin.
            m0, _, tstop0, tmax0 = run_point(
                ngspice_lib,
                corner,
                temp_c,
                0,
                c_sn_ff * 1e-15,
                vrbl,
                params,
                delta_v,
                hold_window,
                tmax_override,
                grow=False,
            )

            ratio = (
                m1["i_read_a"] / m0["i_read_a"] if m0["i_read_a"] > 0 else None
            )

            t_ret = m1["t_ret_tran_s"]
            if t_ret is not None and (worst is None or t_ret < worst[0]):
                worst = (t_ret, corner, temp_c)
            if weakest_write is None or m1["v_sn_hold_start_v"] < weakest_write[0]:
                weakest_write = (m1["v_sn_hold_start_v"], corner, temp_c)

            print(
                f"corner={corner:>3} temp_c={temp_c:>4}  "
                f"v_sn(write1 ceiling)={m1['v_sn_end_wl_pulse_v']:.4f} V  "
                f"retained={m1['v_sn_hold_start_v']:.4f} V  "
                f"I_read(1)={m1['i_read_a']:.4e} A  I_read(0)={m0['i_read_a']:.4e} A  "
                f"ratio={'n/a' if ratio is None else f'{ratio:.3e}'}  "
                f"t_ret_tran="
                + (
                    "n/a (written level below delta_V)"
                    if not m1["threshold_reachable"]
                    else ("not reached in window" if t_ret is None else f"{t_ret:.6e} s")
                )
            )

            for stored, m, tstop_i, tmax_i in ((1, m1, tstop, tmax), (0, m0, tstop0, tmax0)):
                notes = [c_sn_source]
                if stored == 1:
                    if not m["threshold_reachable"]:
                        notes.append(
                            f"t_ret_tran_s BLANK: the retained level "
                            f"{m['v_sn_hold_start_v']:.6f} V is below the "
                            f"{delta_v} V sense margin, so the threshold "
                            f"({m['threshold_v']:.6f} V) sits at or below the "
                            "bitline rail and can never be crossed -- a WRITE-margin "
                            "failure at this corner, not a retention number"
                        )
                    elif m["t_ret_tran_s"] is None:
                        notes.append(
                            f"t_ret_tran_s BLANK: threshold "
                            f"{m['threshold_v']:.6f} V not crossed within the "
                            f"{hold_window:.6e} s simulated hold window"
                        )
                else:
                    notes.append(
                        "stored '0': written by pulsing wl with bl at 0 from an "
                        f"initial sn = {vdd} V (a genuine overwrite). "
                        "t_ret_tran_s/t_ret_linear_extrap_s are not defined for a "
                        "cell written low -- there is no stored charge to decay; "
                        "v_sn_hold_end_v records where the node actually sat at the "
                        "end of the same hold window the stored-'1' run used"
                    )
                row = {
                    "timestamp_utc": timestamp,
                    "repo_git_sha": sha,
                    "pdk_open_pdks_commit": PDK_OPEN_PDKS_COMMIT,
                    "ngspice_version": ver,
                    "corner": corner,
                    "temp_c": temp_c,
                    "stored_value": stored,
                    "c_sn_ff": f"{c_sn_ff:.6f}",
                    "c_sn_source": "extracted" if args.c_sn_ff is None else "override",
                    "vdd_v": vdd,
                    "vrbl_bias_v": vrbl,
                    "t_edge_ns": params["TEDGE"] * 1e9,
                    "t_wl_pulse_ns": (params["TWL_OFF"] - params["TWL_ON"]) * 1e9,
                    "t_rwl_pulse_ns": (params["TRWL_OFF"] - params["TRWL_ON"]) * 1e9,
                    "tmax_s": f"{tmax_i:.6e}",
                    "tstop_s": f"{tstop_i:.6e}",
                    "v_sn_end_wl_pulse_v": f"{m['v_sn_end_wl_pulse_v']:.6f}",
                    "v_sn_after_write_settled_v": f"{m['v_sn_after_write_settled_v']:.6f}",
                    "v_sn_read_gate_v": f"{m['v_sn_read_gate_v']:.6f}",
                    "i_read_a": f"{m['i_read_a']:.6e}",
                    "i_rbl_deselect_a": f"{m['i_rbl_deselect_a']:.6e}",
                    "i_read_ratio_1_over_0": fmt(ratio),
                    "v_sn_read_disturb_v": f"{m['v_sn_read_disturb_v']:.6f}",
                    "v_sn_hold_start_v": f"{m['v_sn_hold_start_v']:.6f}",
                    "v_sn_hold_end_v": f"{m['v_sn_hold_end_v']:.6f}",
                    "hold_window_s": f"{hold_window:.6e}",
                    "dvdt_hold_start_v_per_s": f"{m['dvdt_hold_start_v_per_s']:.6e}",
                    "delta_v_sense_margin_v_ASSUMPTION": delta_v,
                    "t_ret_tran_s": fmt(m["t_ret_tran_s"]) if stored == 1 else "",
                    "t_ret_linear_extrap_s": (
                        fmt(delta_v / abs(m["dvdt_hold_start_v_per_s"]))
                        if stored == 1 and abs(m["dvdt_hold_start_v_per_s"]) > 1e-3
                        else ""
                    ),
                    "notes": "; ".join(notes),
                }
                append_result(RESULTS_CSV, CSV_FIELDS, row)
                n_written += 1

    print(f"\nAppended {n_written} rows to {RESULTS_CSV}")
    if worst is not None:
        t_ret, corner, temp_c = worst
        print(
            f"Worst-case (shortest) simulated retention this run: corner={corner} "
            f"temp_c={temp_c} t_ret_tran={t_ret:.6e} s"
        )
    if weakest_write is not None:
        v, corner, temp_c = weakest_write
        print(
            f"Weakest retained write-'1' level this run: corner={corner} "
            f"temp_c={temp_c} v_sn={v:.6f} V"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
