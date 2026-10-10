#!/usr/bin/env python3
"""Append a refresh-overhead record from a MEASURED t_row_refresh_op (issue #110).

Feeds the slowest-restricted-corner `t_row_refresh_op` of a committed
``sim/refresh-op/results/refresh_op_summary_<RUN_ID>.json`` into the ratified
Section 7 formula via ``refresh_overhead.py`` (same retention rows, same
interval = t_retention / 2 margin ASSUMPTION), and APPENDS rows to
``results/refresh_overhead_measured.csv``. Prior records
(``refresh_overhead_results.csv``, ``refresh_overhead_breakeven.csv``) are never
touched. Rows already present for a (summary run, retention row, restore
fraction, N_rows) key are skipped. Stdlib only.

    python3 -I sim/refresh-overhead/eval_measured_t_row.py <refresh_op_summary_RUN.json>

The 3c limit (50 %) is an ASSUMPTION of spec/macro-pass-conditions-PROPOSED.md; N_rows
is unratified (array not designed): every N_rows is an ASSUMPTION, the measured
t_row_refresh_op is for the 4-row loaded column of sim/refresh-op under the deck's
fixed-phase ASSUMPTIONs (see its README).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import refresh_overhead as R  # noqa: E402
import _evidence_common as common  # noqa: E402

MEASURED_CSV = HERE / "results" / "refresh_overhead_measured.csv"
THRESHOLD_3C = 0.50            # ASSUMPTION (spec/macro-pass-conditions-PROPOSED.md row 3c)
FIELDS = [
    "timestamp_utc", "repo_git_sha", "refresh_op_run_id", "refresh_op_batch_job_id", "sense_basis",
    "restore_fraction_ASSUMPTION", "slowest_corner", "t_row_refresh_op_ns_MEASURED",
    "retention_row_timestamp_utc", "retention_geometry", "retention_c_sn_ff", "retention_c_sn_basis",
    "t_retention_s", "safety_margin_ASSUMPTION", "refresh_interval_s_ASSUMPTION",
    "n_rows_ASSUMPTION", "refresh_bandwidth_overhead", "overhead_pct",
    "threshold_3c_pct_ASSUMPTION", "meets_3c", "n_rows_at_3c_threshold", "max_pow2_n_rows_le_3c", "notes",
]
NOTE = ("t_row_refresh_op MEASURED in sim/refresh-op (fixed precharge/gap/latch/guard phases are ASSUMPTIONs; "
        "ideal drivers; C_RBL/C_WBL ASSUMPTION; global corners only); N_rows unratified; "
        "50 % limit is an ASSUMPTION; ENVELOPE, not a macro claim")


def keys(path: Path) -> set:
    if not path.exists():
        return set()
    with path.open(newline="") as f:
        return {(r["refresh_op_run_id"], r["sense_basis"], r["restore_fraction_ASSUMPTION"], r["retention_row_timestamp_utc"],
                 r["retention_geometry"], r["n_rows_ASSUMPTION"]) for r in csv.DictReader(f)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("summary", type=Path)
    ap.add_argument("--retention-csv", type=Path, default=R.RETENTION_CSV)
    ap.add_argument("--measured-csv", type=Path, default=MEASURED_CSV)
    a = ap.parse_args(argv)
    summ = json.loads(a.summary.read_text())
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    sha = common.repo_git_sha(HERE)
    have = keys(a.measured_csv)
    added = 0
    bases = (("min_searched_sense", summ["slowest_corner_t_row_refresh_op"]),
             ("contract_10ns_sense", summ["slowest_corner_t_row_refresh_op_contract_sense_10ns"]))
    todo = [(b, frac, v) for b, d in bases for frac, v in d.items()]
    for basis, frac, v in todo:
        t_ns = v["t_row_refresh_op_ns"]
        if t_ns is None:
            print(f"{basis} fraction {frac}: no passing point at some corner; nothing appended")
            continue
        for r in R.load_worst_case_retention(a.retention_csv):
            interval = float(r["retention_time_s"]) / R.SAFETY_MARGIN_ASSUMPTION
            nat = R.n_rows_at(THRESHOLD_3C, t_ns * 1e-9, interval)
            for n in R.N_ROWS_GRID:
                key = (summ["run_id"], basis, frac, r["timestamp_utc"], r["geometry_name"], str(n))
                if key in have:
                    continue
                ov = R.overhead(n, t_ns * 1e-9, interval)
                common.append_result(a.measured_csv, FIELDS, {
                    "timestamp_utc": ts, "repo_git_sha": sha, "refresh_op_run_id": summ["run_id"],
                    "refresh_op_batch_job_id": summ.get("batch_job_id"), "sense_basis": basis,
                    "restore_fraction_ASSUMPTION": frac, "slowest_corner": v["slowest_corner"],
                    "t_row_refresh_op_ns_MEASURED": f"{t_ns:.4f}",
                    "retention_row_timestamp_utc": r["timestamp_utc"], "retention_geometry": r["geometry_name"],
                    "retention_c_sn_ff": r["c_storage_node_ff_ASSUMPTION"], "retention_c_sn_basis": R.c_sn_basis(r),
                    "t_retention_s": r["retention_time_s"], "safety_margin_ASSUMPTION": R.SAFETY_MARGIN_ASSUMPTION,
                    "refresh_interval_s_ASSUMPTION": f"{interval:.6e}", "n_rows_ASSUMPTION": n,
                    "refresh_bandwidth_overhead": f"{ov:.6f}", "overhead_pct": f"{ov * 100:.2f}",
                    "threshold_3c_pct_ASSUMPTION": f"{THRESHOLD_3C * 100:.0f}",
                    "meets_3c": "yes" if ov <= THRESHOLD_3C else "no",
                    "n_rows_at_3c_threshold": f"{nat:.2f}", "max_pow2_n_rows_le_3c": R.max_pow2_le(nat),
                    "notes": NOTE})
                added += 1
    print(f"appended {added} rows to {a.measured_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
