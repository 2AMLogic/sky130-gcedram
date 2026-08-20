#!/usr/bin/env python3
"""Access-device off-state leakage sweep for sky130-gcedram (issue #2).

Sweeps sky130_fd_pr__nfet_01v8 (the candidate 2T/3T gain-cell access
device, see sim/leakage/README.md "Device choice") across the shipped
sky130 MOS process corners and a -40/27/125 C temperature range, and
appends each result to sim/leakage/results/leakage_results.csv. This is
the first link in the retention/refresh budget evidence chain CLAUDE.md
requires: device-level leakage measured against the shipped sky130
models, before any storage-node capacitance assumption or retention
number is derived (see #3).

Usage:
    python3 sim/leakage/run_leakage_sweep.py
    python3 sim/leakage/run_leakage_sweep.py --check-env
    python3 sim/leakage/run_leakage_sweep.py --pdk-root /path/to/.volare
    python3 sim/leakage/run_leakage_sweep.py --dry-run

Stdlib only, no virtualenv required. Uses ONLY the shipped sky130 PDK
model library resolved below -- no local model edits, no uncommitted
.include paths. Requires `ngspice` on PATH and a stock volare/open_pdks
sky130A install (see sim/README.md for the install command).

This script never overwrites sim/leakage/results/leakage_results.csv --
it always appends (creating the file with a header on first run), per
CLAUDE.md's "sim/ results are append-only evidence."
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

SIM_LEAKAGE_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = SIM_LEAKAGE_DIR / "tb_access_leakage.spice.tmpl"
RESULTS_CSV = SIM_LEAKAGE_DIR / "results" / "leakage_results.csv"
CSV_FIELDS = [
    "timestamp_utc",
    "repo_git_sha",
    "pdk_open_pdks_commit",
    "corner",
    "temp_c",
    "device",
    "w_um",
    "l_um",
    "vgs_v",
    "vds_v",
    "vbs_v",
    "ileak_a",
    "ngspice_version",
    "notes",
]

DEVICE = "sky130_fd_pr__nfet_01v8"
W_UM = 0.42
L_UM = 0.15
VDD = 1.8
DEFAULT_CORNERS = ["tt", "ss", "ff", "sf", "fs"]
DEFAULT_TEMPS_C = [-40, 27, 125]
DEFAULT_NGSPICE_LIB_REL = "libs.tech/combined/sky130.lib.spice"
DEFAULT_PDK_VARIANT = "sky130A"
PDK_OPEN_PDKS_COMMIT = "c6d73a35f524070e85faff4a6a9eef49553ebc2b"

ILEAK_RE = re.compile(r"ileak_a\s*=\s*([0-9.eE+-]+)")


def resolve_pdk_root(cli_pdk_root: str | None) -> Path:
    if cli_pdk_root:
        return Path(cli_pdk_root).expanduser()
    env_root = os.environ.get("PDK_ROOT")
    if env_root:
        return Path(env_root).expanduser()
    return Path("~/.volare").expanduser()


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
    ngspice_bin = None
    for candidate in ("ngspice",):
        from shutil import which

        ngspice_bin = which(candidate)
        if ngspice_bin:
            break
    if not ngspice_bin:
        print("ERROR: `ngspice` not found on PATH.", file=sys.stderr)
        ok = False
    return ok


def ngspice_version() -> str:
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


def repo_git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=SIM_LEAKAGE_DIR,
            timeout=10,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def render_netlist(ngspice_lib: Path, corner: str, temp_c: int) -> str:
    template = TEMPLATE_PATH.read_text()
    return (
        template.replace("@@PDK_NGSPICE_LIB@@", str(ngspice_lib))
        .replace("@@CORNER@@", corner)
        .replace("@@TEMP_C@@", str(temp_c))
    )


def run_one(ngspice_lib: Path, corner: str, temp_c: int) -> float:
    netlist = render_netlist(ngspice_lib, corner, temp_c)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".spice", prefix=f"leak_{corner}_{temp_c}_", delete=False
    ) as f:
        f.write(netlist)
        netlist_path = f.name
    try:
        result = subprocess.run(
            ["ngspice", "-b", netlist_path],
            capture_output=True,
            text=True,
            timeout=120,
        )
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        match = ILEAK_RE.search(stdout) or ILEAK_RE.search(stderr)
        if not match:
            raise RuntimeError(
                f"could not parse ileak_a from ngspice output for corner={corner} "
                f"temp_c={temp_c}\n--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}"
            )
        return float(match.group(1))
    finally:
        try:
            os.unlink(netlist_path)
        except OSError:
            pass


def append_result(row: dict) -> None:
    """Append a single result row immediately, so partial sweeps (e.g. an
    interrupted run) still leave committed-quality evidence for the points
    that did complete, instead of losing everything to an all-at-the-end
    write. Never truncates or rewrites existing rows."""
    RESULTS_CSV.parent.mkdir(parents=True, exist_ok=True)
    write_header = not RESULTS_CSV.exists()
    with RESULTS_CSV.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, lineterminator="\n")
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pdk-root",
        default=None,
        help="Override PDK_ROOT (default: $PDK_ROOT or ~/.volare)",
    )
    parser.add_argument(
        "--pdk", default=DEFAULT_PDK_VARIANT, help="PDK variant dir (default: sky130A)"
    )
    parser.add_argument(
        "--corners",
        default=",".join(DEFAULT_CORNERS),
        help=f"Comma-separated process corners (default: {','.join(DEFAULT_CORNERS)})",
    )
    parser.add_argument(
        "--temps-c",
        default=",".join(str(t) for t in DEFAULT_TEMPS_C),
        help=f"Comma-separated temperatures in C (default: {','.join(str(t) for t in DEFAULT_TEMPS_C)})",
    )
    parser.add_argument(
        "--check-env",
        action="store_true",
        help="Only check PDK/ngspice availability and exit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Render netlists but do not invoke ngspice",
    )
    args = parser.parse_args(argv)

    pdk_root = resolve_pdk_root(args.pdk_root)
    ngspice_lib = resolve_ngspice_lib(pdk_root, args.pdk)

    if args.check_env:
        ok = check_env(ngspice_lib)
        if ok:
            print(f"OK: ngspice found, PDK model library found at {ngspice_lib}")
        return 0 if ok else 1

    if not check_env(ngspice_lib):
        return 1

    corners = [c.strip() for c in args.corners.split(",") if c.strip()]
    temps_c = [int(t.strip()) for t in args.temps_c.split(",") if t.strip()]

    sha = repo_git_sha()
    ver = ngspice_version()
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds"
    )

    n_written = 0
    worst = None  # (ileak_a, corner, temp_c)
    for corner in corners:
        for temp_c in temps_c:
            if args.dry_run:
                netlist = render_netlist(ngspice_lib, corner, temp_c)
                print(f"--- dry-run netlist: corner={corner} temp_c={temp_c} ---")
                print(netlist)
                continue
            ileak_a = run_one(ngspice_lib, corner, temp_c)
            print(f"corner={corner:>3} temp_c={temp_c:>4}  ileak = {ileak_a:.6e} A")
            if worst is None or ileak_a > worst[0]:
                worst = (ileak_a, corner, temp_c)
            row = {
                "timestamp_utc": timestamp,
                "repo_git_sha": sha,
                "pdk_open_pdks_commit": PDK_OPEN_PDKS_COMMIT,
                "corner": corner,
                "temp_c": temp_c,
                "device": DEVICE,
                "w_um": W_UM,
                "l_um": L_UM,
                "vgs_v": 0.0,
                "vds_v": VDD,
                "vbs_v": 0.0,
                "ileak_a": f"{ileak_a:.6e}",
                "ngspice_version": ver,
                "notes": "",
            }
            append_result(row)
            n_written += 1

    if args.dry_run:
        return 0

    print(f"\nAppended {n_written} rows to {RESULTS_CSV}")
    if worst is not None:
        ileak_a, corner, temp_c = worst
        print(
            f"Worst-case (max leakage) this run: corner={corner} temp_c={temp_c} ileak={ileak_a:.6e} A"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
