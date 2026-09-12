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

import csv
import os
import subprocess
import sys
from pathlib import Path
from shutil import which

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
