#!/usr/bin/env python3
"""Retention-time derivation for candidate 2T/3T gain-cell geometries (issue #3).

Second and third links in the retention/refresh budget evidence chain
CLAUDE.md requires: a storage-node capacitance value combined with the
measured worst-case access-device leakage from sim/leakage/ (issue #2) to
derive a retention-time estimate, at the worst-case temperature corner, for
named candidate 2T/3T geometries.

This is a derivation/write-up script, not a simulation driver: it does not
invoke ngspice, and it does not invoke `klt` either. It does three things,
kept clearly separate per CLAUDE.md's "a retention number without its chain
is not a result":

  1. COMPUTED (not assumed): the gate-oxide capacitance of the read
     transistor's gate, from the same minimum-geometry access device
     already characterized in sim/leakage/ (W=0.42um, L=0.15um), using the
     `toxe` (electrical oxide thickness) and `epsrox` (oxide relative
     permittivity) parameters read directly out of the shipped sky130
     BSIM4 model card for the worst-case leakage corner. This is a real,
     reproducible number derived from public PDK model constants -- not a
     simulation result, but not an assumption either.

  2. EXTRACTED (issue #7, `2T-min` only): the *total* storage-node
     capacitance for the `2T-min` geometry, read from a committed
     post-layout `klt extract --parasitics --critical-net sn` run against
     `layout/gain_cell_2t.gds` (see EXTRACTED_C_SN_SOURCES below) -- the
     storage node's lumped ground capacitance (junction + overlap +
     routing-to-substrate, from the deck's curated sheet-capacitance
     table) plus every same-layer lateral coupling capacitor the
     `--critical-net sn` pass resolved onto `sn` (real physical
     capacitance hanging off the storage node, even though its other
     terminal is a named net rather than ground). This replaces the
     margin-factor ASSUMPTION below for `2T-min`, now that a bitcell
     layout exists to extract from (see load_extracted_c_sn()).

  3. ASSUMED (explicitly labelled, `3T-min` only): the *total* storage-node
     capacitance, expressed as a margin factor over the computed
     gate-oxide term above. No `3T-min` layout exists yet for this macro
     (3T is a documented alternative, not the ratified baseline -- see
     spec/retention-refresh-budget.md Section 6), so junction, overlap,
     and routing parasitics cannot be extracted for it -- this repo
     assumes a margin factor (see MARGIN_FACTORS below) informed by
     qualitative topology reasoning, not measurement. This assumption is
     revisited once a `3T-min` layout exists to extract from.

Usage:
    python3 sim/retention/derive_retention.py
    python3 sim/retention/derive_retention.py --check-env
    python3 sim/retention/derive_retention.py --pdk-root /path/to/.volare

Stdlib only, no virtualenv required. Reads (never modifies)
sim/leakage/results/leakage_results.csv, the shipped sky130 PDK model card
resolved from $PDK_ROOT/--pdk-root, and the committed post-layout
parasitics-extraction JSON under layout/ -- no local model or layout edits.

This script never overwrites sim/retention/results/retention_results.csv --
it always appends (creating the file with a header on first run), per
CLAUDE.md's "sim/ results are append-only evidence." The CSV schema (column
names/order) is unchanged from issue #3 so the header line and all
previously-committed rows stay byte-identical; per the `_ASSUMPTION`-suffixed
columns' provenance being repurposed (not renamed) for the extracted
`2T-min` rows, see load_extracted_c_sn()'s docstring and the `notes` column
each such row carries.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import json
import re
import sys
from pathlib import Path

SIM_RETENTION_DIR = Path(__file__).resolve().parent
REPO_ROOT = SIM_RETENTION_DIR.parent.parent

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
# Both margin factors were ASSUMPTIONS, not measurements or extractions,
# when this repo had no bitcell layout at all (issue #3). Issue #7 replaced
# `2T-min`'s entry with an EXTRACTED value (see EXTRACTED_C_SN_SOURCES /
# load_extracted_c_sn() below) now that a `2T-min` layout exists --
# `MARGIN_FACTORS["2T-min"]` below is therefore no longer read by main()
# (kept only as a documented historical reference for the assumption it
# replaced). `3T-min` has no layout yet (3T is a documented alternative,
# not the ratified baseline -- spec/retention-refresh-budget.md Section 6),
# so it remains on the margin-factor ASSUMPTION path: expressed relative to
# the one component this script CAN compute from public PDK model data --
# the read transistor's gate-oxide capacitance (see compute_cox_and_cgate
# below) -- covering the storage node's other real contributors (M1's
# drain-body junction capacitance, overlap capacitance, and local routing)
# that pre-layout sizing has no extractable value for.
MARGIN_FACTORS = {
    "2T-min": 2.0,  # historical (issue #3); superseded by EXTRACTED_C_SN_SOURCES, issue #7
    "3T-min": 4.0,
}
TOPOLOGY = {
    "2T-min": "2T",
    "3T-min": "3T",
}

# --- EXTRACTED block (issue #7): post-layout storage-node parasitics -----
#
# `2T-min` now has a committed sky130 bitcell layout (layout/gain_cell_2t.gds,
# issue #15/PR #18) and a committed post-layout parasitics extraction run
# against it (layout/gain_cell_2t.extract.parasitics.json), produced via:
#
#   klt extract layout/gain_cell_2t.gds --deck sky130 \
#       --top gain_cell_2t_layout_0 --parasitics --critical-net sn \
#       -o layout/gain_cell_2t.extract.parasitics.spice --format json
#
# (`--critical-net sn` scopes the lateral same-layer coupling-capacitance
# pass onto the storage node, since `sn` couples to the adjacent `bl`/`rwl`
# routing in the routed layout; verified against locally installed
# `klt 0.3.0` -- see docs/cli/extract.md in 2AMLogic/klayout-tools for the
# flag contract.) `3T-min` has no layout, so it is intentionally absent
# from this mapping and stays on the MARGIN_FACTORS ASSUMPTION path above.
EXTRACTED_C_SN_SOURCES = {
    "2T-min": {
        "extract_json": REPO_ROOT / "layout" / "gain_cell_2t.extract.parasitics.json",
        "net": "sn",
        "command": (
            "klt extract layout/gain_cell_2t.gds --deck sky130 "
            "--top gain_cell_2t_layout_0 --parasitics --critical-net sn "
            "-o layout/gain_cell_2t.extract.parasitics.spice --format json"
        ),
    },
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


def load_extracted_c_sn(extract_json_path: Path, net_name: str) -> tuple[float, dict]:
    """EXTRACTED (issue #7): total storage-node parasitic capacitance from a
    committed post-layout `klt extract --parasitics --critical-net <net>`
    JSON report -- NOT a closed-form computation (unlike compute_cox_and_cgate)
    and NOT a qualitative margin-factor ASSUMPTION (unlike the MARGIN_FACTORS
    path 3T-min still uses).

    Total = the net's own lumped ground capacitance (`parasitics.nets[].
    capacitance_ff` -- junction/overlap/routing-to-substrate, from the
    deck's curated sheet-capacitance table) PLUS every same-layer lateral
    coupling capacitor `--critical-net` resolved onto this net
    (`parasitics.nets[].coupled[].capacitance_ff`, summed). A coupling
    capacitor is real physical capacitance loading the storage node even
    though its far terminal is a named net (`bl`, `rwl`) rather than
    ground/substrate -- omitting it would understate the node's true
    capacitive load, so this derivation includes it (a conservative,
    documented choice: it does not assume the coupled net is quiet, only
    that the capacitance itself is real).
    """
    if not extract_json_path.is_file():
        raise RuntimeError(
            f"parasitics extraction report not found: {extract_json_path} -- "
            "run the `klt extract --parasitics --critical-net "
            f"{net_name}` command documented in EXTRACTED_C_SN_SOURCES first"
        )
    data = json.loads(extract_json_path.read_text())
    parasitics = data.get("parasitics")
    if not parasitics:
        raise RuntimeError(
            f"{extract_json_path} has no 'parasitics' block -- was it "
            "generated with --parasitics? (see EXTRACTED_C_SN_SOURCES)"
        )
    net_entry = next(
        (n for n in parasitics.get("nets", []) if n.get("net") == net_name), None
    )
    if net_entry is None:
        raise RuntimeError(
            f"net {net_name!r} not found in parasitics.nets[] of {extract_json_path}"
        )
    ground_c_ff = float(net_entry["capacitance_ff"])
    coupled = net_entry.get("coupled", [])
    coupling_c_ff = sum(float(c["capacitance_ff"]) for c in coupled)
    total_c_ff = ground_c_ff + coupling_c_ff
    provenance = {
        "extract_json_path": extract_json_path,
        "klt_version": data.get("provenance", {}).get("klt_version", "unknown"),
        "input_content_hash": data.get("provenance", {})
        .get("input", {})
        .get("content_hash", "unknown"),
        "ground_c_ff": ground_c_ff,
        "coupling_c_ff": coupling_c_ff,
        "coupled_nets": [c.get("net") for c in coupled],
    }
    return total_c_ff, provenance


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
    for geometry_name, source in EXTRACTED_C_SN_SOURCES.items():
        if not source["extract_json"].is_file():
            print(
                f"ERROR: parasitics extraction for {geometry_name} not found: "
                f"{source['extract_json']}",
                file=sys.stderr,
            )
            print(f"  Run: {source['command']}", file=sys.stderr)
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
        help=(
            "Only check that inputs (leakage CSV, PDK model card, and the "
            "committed 2T-min parasitics extraction JSON) resolve, and exit"
        ),
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
            for geometry_name, source in EXTRACTED_C_SN_SOURCES.items():
                print(
                    f"OK: {geometry_name} parasitics extraction found at "
                    f"{source['extract_json']}"
                )
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
    for geometry_name in MARGIN_FACTORS:
        extracted_source = EXTRACTED_C_SN_SOURCES.get(geometry_name)
        if extracted_source is not None:
            # EXTRACTED path (issue #7): post-layout parasitics, not a
            # margin-factor ASSUMPTION. The `_ASSUMPTION`-suffixed CSV
            # columns are repurposed (not renamed, to keep the CSV schema
            # and previously-committed rows byte-identical -- see module
            # docstring): the margin-factor column is left blank (no
            # margin factor was applied) and the C_SN column now holds the
            # extracted total, with full provenance in `notes`.
            c_sn_ff, prov = load_extracted_c_sn(
                extracted_source["extract_json"], extracted_source["net"]
            )
            c_sn_f = c_sn_ff * 1e-15
            retention_s = c_sn_f * SENSE_MARGIN_V_ASSUMPTION / ileak_a
            print(
                f"{geometry_name:8} ({TOPOLOGY[geometry_name]}): "
                f"C_SN EXTRACTED (klt extract --parasitics --critical-net "
                f"{extracted_source['net']}) = ground {prov['ground_c_ff']:.6f} fF "
                f"+ coupling({','.join(prov['coupled_nets'])}) "
                f"{prov['coupling_c_ff']:.6f} fF = {c_sn_ff:.6f} fF  "
                f"-> retention = {retention_s:.6e} s ({retention_s * 1e6:.3f} us)"
            )
            margin_factor_field = ""
            notes = (
                "C_SN EXTRACTED (not ASSUMED) via `"
                f"{extracted_source['command']}` "
                f"(klt {prov['klt_version']}, input content_hash "
                f"{prov['input_content_hash']}); ground={prov['ground_c_ff']:.6f}fF "
                f"+ coupling to {','.join(prov['coupled_nets']) or 'none'}"
                f"={prov['coupling_c_ff']:.6f}fF; see "
                f"{prov['extract_json_path'].relative_to(REPO_ROOT)} and "
                "sim/retention/README.md (issue #7)."
            )
        else:
            margin_factor = MARGIN_FACTORS[geometry_name]
            c_sn_ff = c_gate_ff * margin_factor
            c_sn_f = c_sn_ff * 1e-15
            retention_s = c_sn_f * SENSE_MARGIN_V_ASSUMPTION / ileak_a
            print(
                f"{geometry_name:8} ({TOPOLOGY[geometry_name]}): "
                f"C_SN ASSUMED = {margin_factor:.1f} x C_gate = {c_sn_ff:.4f} fF  "
                f"-> retention = {retention_s:.6e} s ({retention_s * 1e6:.3f} us)"
            )
            margin_factor_field = margin_factor
            notes = ""

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
            "c_storage_node_margin_factor_ASSUMPTION": margin_factor_field,
            "c_storage_node_ff_ASSUMPTION": f"{c_sn_ff:.6f}",
            "delta_v_sense_margin_v_ASSUMPTION": SENSE_MARGIN_V_ASSUMPTION,
            "retention_time_s": f"{retention_s:.6e}",
            "notes": notes,
        }
        append_result(RESULTS_CSV, CSV_FIELDS, row)
        n_written += 1

    print(f"\nAppended {n_written} rows to {RESULTS_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
