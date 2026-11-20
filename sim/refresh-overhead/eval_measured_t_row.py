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

Since issue #171 the retention bases are SELECTED BY IDENTITY, not iterated
whole: the appended record covers the ratified ASSUMED-C_SN 2T row (the
separately noted historical comparison) and the 2026-11-20 EXTRACTED row whose
leakage input is the stamp-matched re-run (the qualified basis; the 2026-10-28
row prints the same retention time and must never silently occupy the qualified
slot). The refresh-op report the summary was reduced from must carry a worker
``pdk_stamp_comparison`` of ``match`` or nothing is appended (fail closed).

    python3 -I sim/refresh-overhead/eval_measured_t_row.py <refresh_op_summary_RUN.json> [--report <klt_report.json[.gz]>]

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
from _evidence_common import worker_pdk_stamp_problems  # noqa: E402

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
NOTE_QUALIFIED = (NOTE + "; qualified retention row: leakage re-run job " + R.QUALIFIED_LEAKAGE_JOB_ID
                  + " (worker PDK stamp comparison match, issue #377)")
NOTE_HISTORICAL = (NOTE + "; historical comparison basis: ratified ASSUMED-C_SN 2T row "
                   + R.HISTORICAL_ASSUMED_2T_TS + ", superseded as current evidence by the extracted rows")


def find_report(summary: Path) -> Path | None:
    """The klt report a summary was reduced from, if it sits next to it in
    results/ (`klt_report_<run_id>.json[.gz]`). None when absent."""
    rid = json.loads(summary.read_text())["run_id"]
    for cand in (summary.with_name(f"klt_report_{rid}.json.gz"), summary.with_name(f"klt_report_{rid}.json")):
        if cand.exists():
            return cand
    return None


def keys(path: Path) -> set:
    if not path.exists():
        return set()
    with path.open(newline="") as f:
        return {(r["refresh_op_run_id"], r["sense_basis"], r["restore_fraction_ASSUMPTION"], r["retention_row_timestamp_utc"],
                 r["retention_geometry"], r["n_rows_ASSUMPTION"]) for r in csv.DictReader(f)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("summary", type=Path)
    ap.add_argument("--report", type=Path, default=None,
                    help="klt report the summary was reduced from (default: discovered next to the summary); "
                         "its worker PDK stamp comparison must be 'match' for any row to be appended (#171)")
    ap.add_argument("--retention-csv", type=Path, default=R.RETENTION_CSV)
    ap.add_argument("--measured-csv", type=Path, default=MEASURED_CSV)
    a = ap.parse_args(argv)
    summ = json.loads(a.summary.read_text())
    # G4 stamp gate (#171): a measured-overhead record is a qualified result, so
    # the refresh-op report it scales must come from a worker proven to have
    # executed the pinned open_pdks revision. Fails closed when the block is
    # missing (pre-#377 reports), mismatched, or not comparable -- the committed
    # 2026-11-15 refresh-op report is 'not_comparable' and is refused by this.
    report = a.report if a.report is not None else find_report(a.summary)
    if report is None:
        print("ERROR: no klt report found next to the summary and none given with --report; "
              "a measured-overhead record cannot be qualified without the report's worker "
              "PDK stamp comparison", file=sys.stderr)
        return 1
    problems = worker_pdk_stamp_problems(common.load_json(report))
    if problems:
        print(f"ERROR ({report.name}): {'; '.join(problems)}", file=sys.stderr)
        return 1
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    sha = common.repo_git_sha(HERE)
    have = keys(a.measured_csv)
    h, q = R.qualified_retention_rows(a.retention_csv)
    added = 0
    bases = (("min_searched_sense", summ["slowest_corner_t_row_refresh_op"]),
             ("contract_10ns_sense", summ["slowest_corner_t_row_refresh_op_contract_sense_10ns"]))
    todo = [(b, frac, v) for b, d in bases for frac, v in d.items()]
    for basis, frac, v in todo:
        t_ns = v["t_row_refresh_op_ns"]
        if t_ns is None:
            print(f"{basis} fraction {frac}: no passing point at some corner; nothing appended")
            continue
        # Identity-selected G4 bases (#171): the ratified ASSUMED-C_SN row
        # (historical comparison, separately noted) and the 2026-11-20 EXTRACTED
        # row traced to the stamp-matched leakage job (the qualified basis). The
        # 2026-10-28 row prints the same retention time, so a value match cannot
        # select the qualified row; R.select_retention_row fails closed.
        for r, note in ((h, NOTE_HISTORICAL), (q, NOTE_QUALIFIED)):
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
                    "notes": note})
                added += 1
    print(f"appended {added} rows to {a.measured_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
