#!/usr/bin/env python3
"""Refresh-overhead envelope (issue #59, part of #24 item 3).

Evaluates the ratified spec/retention-refresh-budget.md Section 7 formula

    refresh_bandwidth_overhead = (N_rows * t_row_refresh_op) / refresh_interval

over a grid of N_rows (4..1024, powers of two) x t_row_refresh_op scenarios,
at the worst-case corner (sf, 125 C). refresh_interval = t_retention / margin
where t_retention is READ from sim/retention/results/retention_results.csv
(not retyped) and margin is the spec's ASSUMED 2x.

This is a refresh-cost ENVELOPE, not a macro claim. No ngspice is run.
Stdlib only. Results are append-only (existing rows are never rewritten;
keys already present are skipped).

    python3 sim/refresh-overhead/refresh_overhead.py
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import _evidence_common as common  # noqa: E402

RETENTION_CSV = HERE.parent / "retention" / "results" / "retention_results.csv"
RESULTS_CSV = HERE / "results" / "refresh_overhead_results.csv"
BREAKEVEN_CSV = HERE / "results" / "refresh_overhead_breakeven.csv"

WORST_CASE_ROW = "corner=sf,temp_c=125"
TOPOLOGY = "2T"  # ratified topology (spec Section 6)
SAFETY_MARGIN_ASSUMPTION = 2.0  # spec Section 7: ASSUMED 2x margin
N_ROWS_GRID = [2**k for k in range(2, 11)]  # 4 .. 1024
THRESHOLDS = (1.00, 0.25, 0.10)

# t_row_refresh_op scenarios: ordered (phase, ns, basis). Every phase is an
# ASSUMPTION for refresh; "anchored" means the number is borrowed from a
# committed testbench deck setting, which is itself a declared choice, not a
# ratified spec value. No refresh controller exists; the schematic sense
# latch (`design/sense_latch.sch`, #109) contributes no validated timing.
SCENARIOS = {
    "fast": [
        ("precharge", 1.0, "ASSUMPTION: half the 2 ns precharge lead in sim/loaded-column"),
        ("sense", 5.0, "ASSUMPTION: half of loaded-column t_sense (10 ns)"),
        ("writeback_wl_pulse", 5.0, "ASSUMPTION: shortened write pulse; bitcell-transient default is 20 ns and its sweep shows shorter pulses cap the written level"),
        ("bl_release_guard", 1.0, "ASSUMPTION: half of the 2 ns bl-release delay in sim/loaded-column"),
    ],
    "anchored": [
        ("precharge", 2.0, "anchored: 2 ns precharge lead, sim/loaded-column/README.md (declared deck choice)"),
        ("sense", 10.0, "anchored: t_sense = 10 ns, sim/loaded-column/README.md (ASSUMED there, not derived from the sense latch)"),
        ("writeback_wl_pulse", 20.0, "anchored: 20 ns write pulse, sim/bitcell-transient/README.md (deck choice, not a ratified access time)"),
        ("bl_release_guard", 2.0, "anchored: bl returns to 0 V 2 ns after wl low, sim/loaded-column/README.md"),
    ],
    "full_read_pulse": [
        ("precharge", 2.0, "anchored: as 'anchored'"),
        ("sense", 20.0, "anchored: full 20 ns read pulse, sim/bitcell-transient/README.md, instead of the 10 ns t_sense"),
        ("writeback_wl_pulse", 20.0, "anchored: 20 ns write pulse, sim/bitcell-transient/README.md"),
        ("bl_release_guard", 2.0, "anchored: as 'anchored'"),
    ],
    "slow": [
        ("precharge", 5.0, "ASSUMPTION: 2.5x the 2 ns precharge lead"),
        ("sense", 25.0, "ASSUMPTION: 2.5x loaded-column t_sense"),
        ("writeback_wl_pulse", 50.0, "ASSUMPTION: 2.5x the 20 ns bitcell-transient write pulse"),
        ("bl_release_guard", 5.0, "ASSUMPTION: 2.5x the 2 ns bl-release delay"),
    ],
}

FIELDS = [
    "timestamp_utc", "repo_git_sha",
    "retention_row_timestamp_utc", "retention_geometry", "retention_c_sn_ff",
    "retention_c_sn_basis", "retention_leakage_row", "t_retention_s",
    "safety_margin_ASSUMPTION", "refresh_interval_s_ASSUMPTION",
    "scenario", "t_row_refresh_op_ns_ASSUMPTION", "n_rows_ASSUMPTION",
    "refresh_bandwidth_overhead", "overhead_pct", "feasible_lt_100pct", "notes",
]
BREAK_FIELDS = [
    "timestamp_utc", "repo_git_sha", "retention_row_timestamp_utc",
    "retention_geometry", "t_retention_s", "refresh_interval_s_ASSUMPTION",
    "scenario", "t_row_refresh_op_ns_ASSUMPTION",
    "n_rows_at_100pct", "n_rows_at_25pct", "n_rows_at_10pct",
    "max_pow2_n_rows_le_100pct", "max_pow2_n_rows_le_25pct",
    "max_pow2_n_rows_le_10pct", "notes",
]
NOTE = ("ENVELOPE not a macro claim; N_rows and t_row_refresh_op are "
        "unratified ASSUMPTIONs; consumed by the later macro row-count decision")


def overhead(n_rows: float, t_row_s: float, interval_s: float) -> float:
    """Ratified Section 7 formula. All times in seconds -> dimensionless."""
    return n_rows * t_row_s / interval_s


def n_rows_at(fraction: float, t_row_s: float, interval_s: float) -> float:
    """N_rows at which overhead == fraction (inverse of the formula)."""
    return fraction * interval_s / t_row_s


def max_pow2_le(x: float) -> int:
    """Largest power of two <= x (0 if x < 1)."""
    n = 0
    p = 1
    while p <= x:
        n, p = p, p * 2
    return n


def t_row_ns(scenario: str) -> float:
    return sum(ns for _, ns, _ in SCENARIOS[scenario])


def load_worst_case_retention(path: Path = RETENTION_CSV) -> list[dict]:
    """All 2T worst-case (sf/125 C) rows, in file order. Several exist
    because the retention CSV is append-only: the first uses the ASSUMED
    C_SN (the ratified 10.06 us); a later one uses the extracted C_SN."""
    with path.open(newline="") as f:
        rows = [r for r in csv.DictReader(f)
                if r["topology"] == TOPOLOGY
                and r["leakage_source_row"] == WORST_CASE_ROW]
    if not rows:
        raise SystemExit(f"no {TOPOLOGY} {WORST_CASE_ROW} rows in {path}")
    return rows


# Identity of the two worst-case 2T rows a G4 record scales against (issue
# #171). Selected by row identity, NEVER by position or by value: the
# 2026-10-28 row prints exactly the same retention time as the qualified
# row (both 6.116519e-06 s from the same extracted C_SN), so a numeric
# comparison cannot tell them apart -- only the row timestamp plus the
# leakage job cited in its notes can. The 3T-min row shares the qualified
# row's timestamp but is excluded by topology ("2T") upstream.
HISTORICAL_ASSUMED_2T_TS = "2026-08-20T22:38:54+00:00"  # ratified ASSUMED C_SN basis (spec value)
QUALIFIED_EXTRACTED_2T_TS = "2026-11-20T00:35:05+00:00"  # #377 stamp-matched leakage re-run
QUALIFIED_LEAKAGE_JOB_ID = "klt-sim-65de062d8f5c"        # its report's worker stamp comparison is "match"


def select_retention_row(rows: list[dict], timestamp: str, *, geometry: str = "2T-min",
                         leakage_job: str | None = None) -> dict:
    """One retention row selected by identity; SystemExit on absence,
    ambiguity or (when `leakage_job` is given) missing leakage
    traceability. The qualified row must cite the stamp-matched leakage
    job in its notes and carry an EXTRACTED C_SN basis; the historical
    ASSUMED row must keep its ASSUMED basis. Both checks fail closed."""
    matches = [r for r in rows if r["timestamp_utc"] == timestamp and r["geometry_name"] == geometry]
    if not matches:
        raise SystemExit(f"no retention row {timestamp} {geometry} in the worst-case 2T set; "
                         "cannot select a G4 scaling basis by identity")
    if len(matches) != 1:
        raise SystemExit(f"retention row {timestamp} {geometry} is ambiguous "
                         f"({len(matches)} rows); cannot select a G4 scaling basis by identity")
    r = matches[0]
    if leakage_job is not None:
        if leakage_job not in r["notes"]:
            raise SystemExit(f"retention row {timestamp} {geometry} does not cite the stamp-matched "
                             f"leakage job {leakage_job} in its notes; refusing to qualify it")
        if c_sn_basis(r) != "EXTRACTED (layout)":
            raise SystemExit(f"retention row {timestamp} {geometry} qualified basis must be EXTRACTED, "
                             f"found {c_sn_basis(r)!r}")
    return r


def qualified_retention_rows(path: Path = RETENTION_CSV) -> list[dict]:
    """The two identity-selected worst-case 2T rows G4 records scale
    against (issue #171): the ratified ASSUMED-C_SN row (the separately
    labelled historical comparison) and the 2026-11-20 EXTRACTED row whose
    leakage input is the stamp-matched re-run (the qualified basis)."""
    rows = load_worst_case_retention(path)
    historical = select_retention_row(rows, HISTORICAL_ASSUMED_2T_TS)
    if c_sn_basis(historical) != "ASSUMED margin factor":
        raise SystemExit(f"historical comparison row {HISTORICAL_ASSUMED_2T_TS} must keep its "
                         f"ASSUMED C_SN basis, found {c_sn_basis(historical)!r}")
    qualified = select_retention_row(rows, QUALIFIED_EXTRACTED_2T_TS, leakage_job=QUALIFIED_LEAKAGE_JOB_ID)
    return [historical, qualified]


def c_sn_basis(r: dict) -> str:
    return ("ASSUMED margin factor" if r["c_storage_node_margin_factor_ASSUMPTION"]
            else "EXTRACTED (layout)")


def existing_keys(path: Path, cols: list[str]) -> set:
    if not path.exists():
        return set()
    with path.open(newline="") as f:
        return {tuple(r[c] for c in cols) for r in csv.DictReader(f)}


def header_banner() -> str:
    return "\n".join([
        "Refresh-overhead envelope (issue #59) -- NOT a macro claim.",
        "MEASURED/derived input: t_retention, read from sim/retention results CSV.",
        f"ASSUMPTION: safety margin {SAFETY_MARGIN_ASSUMPTION}x (spec Section 7).",
        "ASSUMPTION: every t_row_refresh_op phase (no refresh controller exists; no phase is derived from the sense latch).",
        "ASSUMPTION: every N_rows value (array not designed).",
        "A ~5 us-interval gain cell is a very different proposition from SRAM.",
    ])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--retention-csv", type=Path, default=RETENTION_CSV)
    ap.add_argument("--results-csv", type=Path, default=RESULTS_CSV)
    ap.add_argument("--breakeven-csv", type=Path, default=BREAKEVEN_CSV)
    args = ap.parse_args()

    print(header_banner())
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    sha = common.repo_git_sha(HERE)
    keycols = ["retention_row_timestamp_utc", "retention_geometry",
               "retention_c_sn_ff", "scenario", "n_rows_ASSUMPTION"]
    bkeycols = ["retention_row_timestamp_utc", "retention_geometry",
                "t_retention_s", "scenario"]
    have = existing_keys(args.results_csv, keycols)
    bhave = existing_keys(args.breakeven_csv, bkeycols)
    added = 0
    for r in load_worst_case_retention(args.retention_csv):
        t_ret = float(r["retention_time_s"])
        interval = t_ret / SAFETY_MARGIN_ASSUMPTION
        print(f"\nretention row {r['timestamp_utc']} {r['geometry_name']} "
              f"C_SN {c_sn_basis(r)}: t_retention {t_ret*1e6:.3f} us, "
              f"interval {interval*1e6:.3f} us")
        for sc in SCENARIOS:
            t_row_s = t_row_ns(sc) * 1e-9
            be = {f: n_rows_at(f, t_row_s, interval) for f in THRESHOLDS}
            print(f"  {sc:16s} t_row {t_row_ns(sc):6.1f} ns  N@100% {be[1.0]:7.1f}"
                  f"  N@25% {be[0.25]:6.1f}  N@10% {be[0.10]:6.1f}")
            bk = (r["timestamp_utc"], r["geometry_name"], r["retention_time_s"], sc)
            if tuple(map(str, bk)) not in bhave:
                common.append_result(args.breakeven_csv, BREAK_FIELDS, {
                    "timestamp_utc": ts, "repo_git_sha": sha,
                    "retention_row_timestamp_utc": r["timestamp_utc"],
                    "retention_geometry": r["geometry_name"],
                    "t_retention_s": r["retention_time_s"],
                    "refresh_interval_s_ASSUMPTION": f"{interval:.6e}",
                    "scenario": sc,
                    "t_row_refresh_op_ns_ASSUMPTION": f"{t_row_ns(sc):.1f}",
                    "n_rows_at_100pct": f"{be[1.0]:.2f}",
                    "n_rows_at_25pct": f"{be[0.25]:.2f}",
                    "n_rows_at_10pct": f"{be[0.10]:.2f}",
                    "max_pow2_n_rows_le_100pct": max_pow2_le(be[1.0]),
                    "max_pow2_n_rows_le_25pct": max_pow2_le(be[0.25]),
                    "max_pow2_n_rows_le_10pct": max_pow2_le(be[0.10]),
                    "notes": NOTE,
                })
            for n in N_ROWS_GRID:
                ov = overhead(n, t_row_s, interval)
                key = (r["timestamp_utc"], r["geometry_name"],
                       r["c_storage_node_ff_ASSUMPTION"], sc, str(n))
                if key in have:
                    continue
                common.append_result(args.results_csv, FIELDS, {
                    "timestamp_utc": ts, "repo_git_sha": sha,
                    "retention_row_timestamp_utc": r["timestamp_utc"],
                    "retention_geometry": r["geometry_name"],
                    "retention_c_sn_ff": r["c_storage_node_ff_ASSUMPTION"],
                    "retention_c_sn_basis": c_sn_basis(r),
                    "retention_leakage_row": r["leakage_source_row"],
                    "t_retention_s": r["retention_time_s"],
                    "safety_margin_ASSUMPTION": SAFETY_MARGIN_ASSUMPTION,
                    "refresh_interval_s_ASSUMPTION": f"{interval:.6e}",
                    "scenario": sc,
                    "t_row_refresh_op_ns_ASSUMPTION": f"{t_row_ns(sc):.1f}",
                    "n_rows_ASSUMPTION": n,
                    "refresh_bandwidth_overhead": f"{ov:.6f}",
                    "overhead_pct": f"{ov*100:.2f}",
                    "feasible_lt_100pct": "yes" if ov < 1.0 else "no",
                    "notes": NOTE,
                })
                added += 1
    print(f"\nappended {added} grid rows to {args.results_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
