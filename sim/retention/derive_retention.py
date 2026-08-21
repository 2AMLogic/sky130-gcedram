#!/usr/bin/env python3
"""Retention-time derivation for candidate 2T/3T gain-cell geometries (issue #3).

Second and third links in the retention/refresh budget evidence chain
CLAUDE.md requires: a storage-node capacitance ASSUMPTION (explicitly not a
measured quantity) combined with the measured worst-case access-device
leakage from sim/leakage/ (issue #2) to derive a retention-time estimate,
at the worst-case temperature corner, for named candidate 2T/3T geometries.

This is a derivation/write-up script, not a simulation driver: it does not
invoke ngspice. It does two things, kept clearly separate per CLAUDE.md's
"a retention number without its chain is not a result":

  1. COMPUTED (not assumed): the gate-oxide capacitance of the read
     transistor's gate, from the same minimum-geometry access device
     already characterized in sim/leakage/ (W=0.42um, L=0.15um), using the
     `toxe` (electrical oxide thickness) and `epsrox` (oxide relative
     permittivity) parameters read directly out of the shipped sky130
     BSIM4 model card for the worst-case leakage corner. This is a real,
     reproducible number derived from public PDK model constants -- not a
     simulation result, but not an assumption either.

  2. ASSUMED (explicitly labelled): the *total* storage-node capacitance
     per candidate geometry, expressed as a margin factor over the
     computed gate-oxide term above. No layout exists yet for this macro,
     so junction, overlap, and routing parasitics cannot be extracted --
     this repo assumes a margin factor per topology (see MARGIN_FACTORS
     below) informed by qualitative topology reasoning, not measurement.
     This assumption is revisited once a layout exists to extract from.

Usage:
    python3 sim/retention/derive_retention.py
    python3 sim/retention/derive_retention.py --check-env
    python3 sim/retention/derive_retention.py --pdk-root /path/to/.volare

Stdlib only, no virtualenv required. Reads (never modifies)
sim/leakage/results/leakage_results.csv and the shipped sky130 PDK model
card resolved from $PDK_ROOT/--pdk-root -- no local model edits.

This script never overwrites sim/retention/results/retention_results.csv --
it always appends (creating the file with a header on first run), per
CLAUDE.md's "sim/ results are append-only evidence."
"""

from __future__ import annotations

import argparse
import csv
import datetime
import re
import sys
from pathlib import Path

SIM_RETENTION_DIR = Path(__file__).resolve().parent

sys.path.insert(0, str(SIM_RETENTION_DIR.parent))
from _evidence_common import append_result, repo_git_sha, resolve_pdk_root

LEAKAGE_CSV = SIM_RETENTION_DIR.parent / "leakage" / "results" / "leakage_results.csv"
RESULTS_CSV = SIM_RETENTION_DIR / "results" / "retention_results.csv"

CSV_FIELDS = [
    "timestamp_utc",
    "repo_git_sha",
    "geometry_name",
    "topology",
    "leakage_source_row",  # corner/temp_c cite into leakage_results.csv
    "leakage_ileak_a",
    "device",
    "w_um",
    "l_um",
    "toxe_m",
    "epsrox",
    "cox_ff_per_um2",
    "c_gate_read_transistor_ff",
    "c_storage_node_margin_factor_ASSUMPTION",
    "c_storage_node_ff_ASSUMPTION",
    "delta_v_sense_margin_v_ASSUMPTION",
    "retention_time_s",
    "notes",
]

DEVICE = "sky130_fd_pr__nfet_01v8"
DEFAULT_PDK_VARIANT = "sky130A"
DEFAULT_PDK_VARIANT_MODEL = "sky130B"  # libs.ref model cards live under sky130B
MODEL_REL_DIR = "libs.ref/sky130_fd_pr/spice"
PDK_OPEN_PDKS_COMMIT = "c6d73a35f524070e85faff4a6a9eef49553ebc2b"

EPS0 = 8.8541878128e-12  # F/m, vacuum permittivity (physical constant)

# --- ASSUMPTION block (explicitly NOT measured) --------------------------
#
# Candidate geometries. Both reuse the exact access-device sizing already
# measured in sim/leakage/ (W=0.42um, L=0.15um -- the minimum-size,
# worst-case-leakage device per sim/leakage/README.md "Geometry"), since
# that is the only leakage number this repo has measured evidence for.
# What differs between the two candidates is the storage-node capacitance
# ASSUMPTION, driven by topology:
#
#   - 2T gain cell: write-access transistor M1 (drain = storage node) +
#     read transistor M2 (gate = storage node, drain tied directly to the
#     read bitline). No dedicated read-select device sits near the
#     storage node -- a comparatively compact layout.
#   - 3T gain cell: adds a dedicated read-access transistor M3 between M2's
#     drain and the read bitline (isolating the read bitline swing from
#     M2, the classic 3T motivation). M3 is not DC-connected to the
#     storage node in this topology (only M1's drain and M2's gate are),
#     so it does not add leakage into the node -- the leakage number from
#     #2 is unchanged. It does, however, sit physically closer to the
#     storage-node routing than the 2T layout, so this repo assumes a
#     larger routing/coupling capacitance margin for the 3T candidate.
#
# Both margin factors are ASSUMPTIONS, not measurements or extractions:
# no layout exists yet for this macro, so junction, overlap, and routing
# parasitics on the storage node cannot be extracted from a real layout.
# The margin is expressed relative to the one component this script CAN
# compute from public PDK model data -- the read transistor's gate-oxide
# capacitance (see compute_cox_and_cgate below) -- covering the storage
# node's other real contributors (M1's drain-body junction capacitance,
# overlap capacitance, and local routing) that pre-layout sizing has no
# extractable value for.
MARGIN_FACTORS = {
    "2T-min": 2.0,
    "3T-min": 4.0,
}
TOPOLOGY = {
    "2T-min": "2T",
    "3T-min": "3T",
}

# Sense margin: the storage-node voltage droop, from a written '1' at VDD,
# that a read-side sense scheme can tolerate before it can no longer
# reliably discriminate a stored '1' from a '0'. No sense-amplifier design
# exists yet for this macro, so this repo assumes the conservative
# half-VDD bound used as a coarse worst-case sizing rule in SRAM/DRAM
# sensing design (absent a specific sense-amp offset/noise budget) rather
# than a value validated against this macro's own sense circuit.
SENSE_MARGIN_V_ASSUMPTION = 1.8 / 2.0  # VDD/2, ASSUMPTION

TOXE_RE = re.compile(r"toxe\s*=\s*\{\s*([0-9.eE+-]+)\s*\+\s*MC_MM_SWITCH")
EPSROX_RE = re.compile(r"epsrox\s*=\s*([0-9.eE+-]+)")


def resolve_model_file(pdk_root: Path, model_variant: str, corner: str) -> Path:
    return pdk_root / model_variant / MODEL_REL_DIR / f"{DEVICE}__{corner}.pm3.spice"


def parse_toxe_epsrox(model_file: Path) -> tuple[float, float]:
    """Parse the corner-level (geometry-bin-independent) `toxe` base term and
    `epsrox` directly from the shipped BSIM4 model card. Verified against
    the pinned open_pdks commit: every W/L bin in a given corner file shares
    the same base `toxe` coefficient (only the mismatch term scales with
    bin geometry), so the first match is representative of the whole file.
    """
    text = model_file.read_text()
    toxe_match = TOXE_RE.search(text)
    epsrox_match = EPSROX_RE.search(text)
    if not toxe_match or not epsrox_match:
        raise RuntimeError(
            f"could not parse toxe/epsrox from {model_file} -- model card "
            "format may have changed"
        )
    return float(toxe_match.group(1)), float(epsrox_match.group(1))


def load_worst_case_leakage(leakage_csv: Path) -> dict:
    """Read sim/leakage/results/leakage_results.csv and return the row with
    the maximum ileak_a -- the worst-case (max leakage) measured point, per
    CLAUDE.md's 'Retention claims are made at the worst-case temperature
    corner, not typicals.' Re-running this script after a new leakage sweep
    is appended automatically re-derives against whatever is currently the
    worst-case row -- this is the mechanism that satisfies #3's Test Plan
    'confirm the derivation is re-run ... if #2's numbers change.'
    """
    if not leakage_csv.is_file():
        raise RuntimeError(
            f"leakage results not found: {leakage_csv} -- run "
            "sim/leakage/run_leakage_sweep.py first (see sim/leakage/README.md)"
        )
    with leakage_csv.open(newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise RuntimeError(f"leakage results file is empty: {leakage_csv}")
    return max(rows, key=lambda r: float(r["ileak_a"]))


def compute_cox_and_cgate(toxe_m: float, epsrox: float, w_um: float, l_um: float):
    """COMPUTED (not assumed): gate-oxide capacitance per unit area and the
    resulting gate capacitance of a device with the given drawn W/L, from
    the public PDK model card's toxe/epsrox. Cox'' = eps0*epsrox/toxe is
    the standard planar-capacitor relation (BSIM4 electrical-oxide
    convention)."""
    cox_area_f_per_m2 = EPS0 * epsrox / toxe_m
    cox_area_ff_per_um2 = cox_area_f_per_m2 * 1e-12 * 1e15
    c_gate_f = cox_area_f_per_m2 * (w_um * 1e-6) * (l_um * 1e-6)
    c_gate_ff = c_gate_f * 1e15
    return cox_area_ff_per_um2, c_gate_ff


def check_env(leakage_csv: Path, model_file: Path) -> bool:
    ok = True
    if not leakage_csv.is_file():
        print(f"ERROR: leakage results not found: {leakage_csv}", file=sys.stderr)
        print(
            "  Run sim/leakage/run_leakage_sweep.py first (see sim/leakage/README.md).",
            file=sys.stderr,
        )
        ok = False
    if not model_file.is_file():
        print(f"ERROR: sky130 model card not found: {model_file}", file=sys.stderr)
        print(
            "  Install a stock PDK with volare, e.g.:\n"
            f"    volare enable --pdk sky130 {PDK_OPEN_PDKS_COMMIT}\n"
            "  or set PDK_ROOT to an existing open_pdks sky130A/sky130B install.",
            file=sys.stderr,
        )
        ok = False
    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pdk-root",
        default=None,
        help="Override PDK_ROOT (default: $PDK_ROOT or ~/.volare)",
    )
    parser.add_argument(
        "--pdk-model-variant",
        default=DEFAULT_PDK_VARIANT_MODEL,
        help=f"PDK variant dir holding libs.ref model cards (default: {DEFAULT_PDK_VARIANT_MODEL})",
    )
    parser.add_argument(
        "--leakage-csv",
        default=str(LEAKAGE_CSV),
        help="Path to sim/leakage/results/leakage_results.csv (default: repo-relative path)",
    )
    parser.add_argument(
        "--check-env",
        action="store_true",
        help="Only check that inputs (leakage CSV + PDK model card) resolve, and exit",
    )
    args = parser.parse_args(argv)

    pdk_root = resolve_pdk_root(args.pdk_root)
    leakage_csv = Path(args.leakage_csv)

    worst = load_worst_case_leakage(leakage_csv) if leakage_csv.is_file() else None
    corner = (
        worst["corner"] if worst else "sf"
    )  # fallback name for --check-env path probe
    model_file = resolve_model_file(pdk_root, args.pdk_model_variant, corner)

    if args.check_env:
        ok = check_env(leakage_csv, model_file)
        if ok:
            print(f"OK: leakage results found at {leakage_csv}")
            print(f"OK: sky130 model card found at {model_file}")
        return 0 if ok else 1

    if not check_env(leakage_csv, model_file):
        return 1

    worst = load_worst_case_leakage(leakage_csv)
    corner = worst["corner"]
    temp_c = worst["temp_c"]
    ileak_a = float(worst["ileak_a"])
    w_um = float(worst["w_um"])
    l_um = float(worst["l_um"])
    device = worst["device"]

    model_file = resolve_model_file(pdk_root, args.pdk_model_variant, corner)
    toxe_m, epsrox = parse_toxe_epsrox(model_file)
    cox_ff_per_um2, c_gate_ff = compute_cox_and_cgate(toxe_m, epsrox, w_um, l_um)

    sha = repo_git_sha(SIM_RETENTION_DIR)
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds"
    )

    print(
        f"Worst-case leakage input (from {leakage_csv.name}): "
        f"corner={corner} temp_c={temp_c} ileak_a={ileak_a:.6e} A "
        f"(device={device}, W={w_um}um, L={l_um}um)"
    )
    print(
        f"Computed (not assumed) gate-oxide term: toxe={toxe_m:.6e} m, "
        f"epsrox={epsrox}, Cox''={cox_ff_per_um2:.6f} fF/um^2, "
        f"C_gate(read transistor, same geometry)={c_gate_ff:.6f} fF"
    )
    print(
        f"ASSUMED sense margin (VDD/2, no sense-amp design exists yet): "
        f"delta_V={SENSE_MARGIN_V_ASSUMPTION} V"
    )
    print()

    n_written = 0
    for geometry_name, margin_factor in MARGIN_FACTORS.items():
        c_sn_ff = c_gate_ff * margin_factor
        c_sn_f = c_sn_ff * 1e-15
        retention_s = c_sn_f * SENSE_MARGIN_V_ASSUMPTION / ileak_a
        print(
            f"{geometry_name:8} ({TOPOLOGY[geometry_name]}): "
            f"C_SN ASSUMED = {margin_factor:.1f} x C_gate = {c_sn_ff:.4f} fF  "
            f"-> retention = {retention_s:.6e} s ({retention_s * 1e6:.3f} us)"
        )
        row = {
            "timestamp_utc": timestamp,
            "repo_git_sha": sha,
            "geometry_name": geometry_name,
            "topology": TOPOLOGY[geometry_name],
            "leakage_source_row": f"corner={corner},temp_c={temp_c}",
            "leakage_ileak_a": f"{ileak_a:.6e}",
            "device": device,
            "w_um": w_um,
            "l_um": l_um,
            "toxe_m": f"{toxe_m:.6e}",
            "epsrox": epsrox,
            "cox_ff_per_um2": f"{cox_ff_per_um2:.6f}",
            "c_gate_read_transistor_ff": f"{c_gate_ff:.6f}",
            "c_storage_node_margin_factor_ASSUMPTION": margin_factor,
            "c_storage_node_ff_ASSUMPTION": f"{c_sn_ff:.6f}",
            "delta_v_sense_margin_v_ASSUMPTION": SENSE_MARGIN_V_ASSUMPTION,
            "retention_time_s": f"{retention_s:.6e}",
            "notes": "",
        }
        append_result(RESULTS_CSV, CSV_FIELDS, row)
        n_written += 1

    print(f"\nAppended {n_written} rows to {RESULTS_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
