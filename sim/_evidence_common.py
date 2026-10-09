"""Shared helpers for the retention/refresh evidence-chain scripts.

Used by both `sim/leakage/run_leakage_sweep.py` (link 1) and
`sim/retention/derive_retention.py` (links 2/3) of the evidence chain
CLAUDE.md requires. Kept stdlib-only, matching the "Stdlib only, no
virtualenv required" constraint both callers document for themselves.

These are small, evidence-chain-integrity-critical helpers -- in
particular `append_result()` is what both scripts rely on to honor
CLAUDE.md's "sim/ results are append-only evidence." Consolidating them
here means a fix to that guarantee (or to PDK-root resolution, or to the
git-sha provenance stamp written into every result row) applies to both
scripts at once instead of silently drifting between two copies.
"""

from __future__ import annotations

import bisect
import csv
import os
import re
import subprocess
import sys
from pathlib import Path
from shutil import which

# Canonical sky130 PDK pin (family/variant/open_pdks commit) for every
# script under sim/ -- the single Python-side source of truth issue #37
# consolidated this to, out of what were previously 7 independently
# hand-maintained copies (three now-deleted sim/*/pdk.json and
# design/pdk.json documentation files, design/env.sh's and
# design/xschemrc's shell/Tcl fallback defaults, and two per-testbench
# DEFAULT_PDK_VARIANT constants). See docs/pdk-pin.md for the full
# rationale and the shell/Tcl-side mirror this cannot eliminate (Python
# constants aren't importable from design/env.sh or design/xschemrc).
#
# sky130 flavor directory to use (A/B differ in metal stack only;
# irrelevant to a device-level SPICE sim or to schematic capture).
DEFAULT_PDK_VARIANT = "sky130A"

# sky130A path to the combined ngspice model library, relative to a PDK
# root's variant directory (e.g. `$PDK_ROOT/sky130A/...`).
DEFAULT_NGSPICE_LIB_REL = "libs.tech/combined/sky130.lib.spice"

# The open_pdks commit the shipped model library is pinned to, quoted in
# the install hint `check_ngspice_available()` prints on failure.
PDK_OPEN_PDKS_COMMIT = "c6d73a35f524070e85faff4a6a9eef49553ebc2b"


def resolve_pdk_root(
    cli_pdk_root: str | None,
    env_var: str = "PDK_ROOT",
    default: str = "~/.volare",
) -> Path:
    """Resolve the sky130 PDK root: an explicit CLI override, else the
    named environment variable, else the given default."""
    if cli_pdk_root:
        return Path(cli_pdk_root).expanduser()
    env_root = os.environ.get(env_var)
    if env_root:
        return Path(env_root).expanduser()
    return Path(default).expanduser()


def repo_git_sha(cwd: Path) -> str:
    """`git rev-parse --short HEAD` run from `cwd`, for the provenance
    stamp written into every appended result row. Returns "unknown" on
    any failure (e.g. no git binary, not a git checkout) rather than
    raising, so evidence collection is never blocked by a missing repo."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=10,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def resolve_ngspice_lib(pdk_root: Path, variant: str) -> Path:
    """Resolve the combined sky130 ngspice model library path for a given
    PDK root and variant (e.g. "sky130A")."""
    return pdk_root / variant / DEFAULT_NGSPICE_LIB_REL


def check_ngspice_available(ngspice_lib: Path) -> bool:
    """Check that the sky130 ngspice model library exists and `ngspice`
    is on PATH, printing an install hint on failure. Callers with
    additional environment checks (e.g. a testbench template or design
    netlist) run those separately and AND the result with this one."""
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
    return ok


def ngspice_version() -> str:
    """`ngspice --version`'s banner line naming the version, for the
    provenance stamp written into every appended result row. Returns
    "unknown" on any failure rather than raising."""
    try:
        out = subprocess.run(
            ["ngspice", "--version"], capture_output=True, text=True, timeout=10
        )
        # Line 1 of `ngspice --version` is a "******" banner rule; the
        # actual "ngspice-NN : Circuit level simulation program" line is
        # the first line containing "ngspice".
        for line in (out.stdout or "").splitlines():
            if "ngspice" in line.lower():
                return line.strip()
        return "unknown"
    except Exception:
        return "unknown"


def append_result(results_csv: Path, csv_fields: list[str], row: dict) -> None:
    """Append a single result row immediately, so partial runs (e.g. an
    interrupted sweep) still leave committed-quality evidence for the
    points that did complete, instead of losing everything to an
    all-at-the-end write. Never truncates or rewrites existing rows, per
    CLAUDE.md's 'sim/ results are append-only evidence.'"""
    results_csv.parent.mkdir(parents=True, exist_ok=True)
    write_header = not results_csv.exists()
    with results_csv.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, lineterminator="\n")
        if write_header:
            writer.writeheader()
        writer.writerow(row)


# --------------------------------------------------------------------------
# SPICE number / waveform helpers (issue #58) -- shared by
# sim/bitcell-transient/run_bitcell_transient.py and
# sim/loaded-column/run_loaded_column.py (and, via the latter, the
# cold-corner variant runner). Stdlib only, no numpy.
# --------------------------------------------------------------------------

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


def spice_number(text: str) -> float:
    """Parse a SPICE numeric literal with an optional engineering suffix
    (`100p`, `21n`, `1.8`, `1meg`). Raises ValueError on anything else
    (including an unknown suffix) -- a silently mis-parsed timing
    parameter would move a measurement instant. Callers that want to skip
    non-numeric `.param` values catch ValueError."""
    m = re.fullmatch(r"([+-]?[0-9]*\.?[0-9]+(?:[eE][+-]?[0-9]+)?)\s*([A-Za-z]*)", text)
    if not m:
        raise ValueError(f"not a SPICE numeric literal: {text!r}")
    value = float(m.group(1))
    suffix = m.group(2).lower()
    if not suffix:
        return value
    if suffix.startswith("meg"):
        return value * SI_SUFFIX["meg"]
    if suffix[0] in SI_SUFFIX:
        return value * SI_SUFFIX[suffix[0]]
    raise ValueError(f"unknown SPICE suffix in {text!r}")


def read_wrdata(path: Path, min_points: int) -> list[list[float]]:
    """Parse an ngspice `wrdata` ASCII table into columns.

    `wrdata out v(a) v(b) ...` emits one (x, y) column PAIR per vector, so
    a row is [t, y1, t, y2, ...]. Returns `[t, y1, y2, ...]` (the shared
    time column once, then each vector's y column). Rows with fewer than 4
    fields or non-numeric fields are skipped. Raises RuntimeError if fewer
    than `min_points` timepoints were parsed (the caller picks the limit:
    3 for the bitcell transient, 10 for the loaded column).
    """
    cols: list[list[float]] | None = None
    for line in Path(path).read_text().splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            row = [float(x) for x in parts]
        except ValueError:
            continue
        if cols is None:
            cols = [[] for _ in range(len(row) // 2 + 1)]
        cols[0].append(row[0])
        for i in range(len(row) // 2):
            cols[i + 1].append(row[2 * i + 1])
    if cols is None or len(cols[0]) < min_points:
        raise RuntimeError(f"ngspice produced too few timepoints in {path}")
    return cols


def interp_at(t: list[float], y: list[float], tq: float) -> float:
    """Linear interpolation of y(tq) on a non-decreasing t, clamped to the
    end values outside the sampled window. Duplicate timestamps do not
    divide by zero."""
    if tq <= t[0]:
        return y[0]
    if tq >= t[-1]:
        return y[-1]
    hi = bisect.bisect_right(t, tq)
    lo = hi - 1
    if t[hi] == t[lo]:
        return y[lo]
    frac = (tq - t[lo]) / (t[hi] - t[lo])
    return y[lo] + frac * (y[hi] - y[lo])


def first_crossing_below(
    t: list[float], y: list[float], threshold: float, t_from: float
) -> float | None:
    """ABSOLUTE time of the first fall to `threshold` at or after `t_from`,
    linearly interpolated between the bracketing timepoints. If the first
    sample at/after `t_from` is already <= threshold, that sample's time is
    returned (no interpolation from `t_from`). None if never reached.
    Contrast `first_below()`."""
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


def first_below(t: list[float], y: list[float], t0: float, level: float) -> float | None:
    """Time RELATIVE to `t0` at which y first reaches <= level (linear
    interpolation, bracket starting at max(t[i-1], t0)). Returns 0.0 if y
    is already <= level at t0; None if never reached. Contrast
    `first_crossing_below()` (absolute time, different already-below and
    bracketing behaviour, different argument order)."""
    if interp_at(t, y, t0) <= level:
        return 0.0
    for i in range(1, len(t)):
        if t[i] <= t0:
            continue
        if y[i] <= level:
            ta = max(t[i - 1], t0)
            ya = interp_at(t, y, ta)
            return ta + (level - ya) / (y[i] - ya) * (t[i] - ta) - t0
    return None
