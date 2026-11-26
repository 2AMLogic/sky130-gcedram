#!/usr/bin/env python3
"""Stdlib-only checks for the retention derivation's worst-case leakage
selection (issue #377). No ngspice, PDK or klt needed: the selection must
only consider leakage rows traceable (via the batch job id in `notes`) to a
committed report whose worker PDK stamp comparison is "match", so the
mislabelled issue #168 rows (job klt-sim-c2ed3f15ab70) can never supply a
retention number -- including on an ileak_a tie, where file order would
otherwise let the older row win max(), or when the older row is strictly
larger.

Run: python3 -I sim/retention/test_derive_retention.py
"""
from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import derive_retention as D  # noqa: E402
from _evidence_common import PDK_OPEN_PDKS_COMMIT  # noqa: E402

OLD_PIN = "c6d73a35f524070e85faff4a6a9eef49553ebc2b"
OLD_JOB = "klt-sim-c2ed3f15ab70"  # the real mislabelled run (issue #168)
NEW_JOB = "klt-sim-65de062d8f5c"  # the real stamp-matched run (issue #377)
OLD_TS = "2026-10-16T07:43:01+00:00"
NEW_TS = "2026-11-20T00:31:00+00:00"


def write_report(dir_path, name, job_id, stamp_status):
    report = {
        "status": "pass",
        "failed": 0,
        "errored": 0,
        "corners": [],
        "environment": {
            "remote": {"job_id": job_id, "worker_environment": {}},
        },
    }
    if stamp_status is not None:
        report["environment"]["remote"]["worker_environment"][
            "pdk_stamp_comparison"
        ] = {"status": stamp_status}
    path = Path(dir_path) / name
    path.write_text(json.dumps(report))
    return path


def leak_row(ileak, job, ts, pin=PDK_OPEN_PDKS_COMMIT, corner="sf", temp_c="125"):
    notes = (
        f"klt sim batch job {job}; ngspice-47; report klt_report_x.json" if job else ""
    )
    return {
        "timestamp_utc": ts,
        "repo_git_sha": "deadbee",
        "pdk_open_pdks_commit": pin,
        "corner": corner,
        "temp_c": temp_c,
        "device": "sky130_fd_pr__nfet_01v8",
        "w_um": "0.42",
        "l_um": "0.15",
        "vgs_v": "0.0",
        "vds_v": "1.8",
        "vbs_v": "0.0",
        "ileak_a": ileak,
        "ngspice_version": "ngspice-47 (klt sim batch)",
        "notes": notes,
    }


LEAKAGE_HEADER = [
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


def write_leakage_csv(dir_path, rows):
    path = Path(dir_path) / "leakage_results.csv"
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LEAKAGE_HEADER, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


class StampMatchedSelection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.results = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_matched_batch_job_ids(self):
        write_report(self.results, "klt_report_old.json", OLD_JOB, "mismatch")
        write_report(self.results, "klt_report_new.json", NEW_JOB, "match")
        self.assertEqual(D.matched_batch_job_ids(self.results), {NEW_JOB})

    def test_tie_prefers_stamp_matched_row(self):
        # Equal ileak_a, the older mislabelled row first in file order:
        # Python max() would return it; it must be excluded instead.
        write_report(self.results, "klt_report_old.json", OLD_JOB, "mismatch")
        write_report(self.results, "klt_report_new.json", NEW_JOB, "match")
        csv_path = write_leakage_csv(
            self.results,
            [
                leak_row("9.898880e-11", OLD_JOB, OLD_TS),
                leak_row("9.898880e-11", NEW_JOB, NEW_TS),
            ],
        )
        worst = D.load_worst_case_leakage(csv_path, self.results)
        self.assertIn(f"batch job {NEW_JOB}", worst["notes"])
        self.assertEqual(worst["timestamp_utc"], NEW_TS)

    def test_strictly_larger_old_row_ignored(self):
        write_report(self.results, "klt_report_old.json", OLD_JOB, "mismatch")
        write_report(self.results, "klt_report_new.json", NEW_JOB, "match")
        csv_path = write_leakage_csv(
            self.results,
            [
                leak_row("1.200000e-10", OLD_JOB, OLD_TS),
                leak_row("9.898880e-11", NEW_JOB, NEW_TS),
                leak_row("9.898880e-11", NEW_JOB, NEW_TS, corner="tt", temp_c="27"),
            ],
        )
        worst = D.load_worst_case_leakage(csv_path, self.results)
        self.assertIn(f"batch job {NEW_JOB}", worst["notes"])
        self.assertEqual(worst["ileak_a"], "9.898880e-11")

    def test_no_matched_report_fails_closed(self):
        write_report(self.results, "klt_report_old.json", OLD_JOB, "mismatch")
        csv_path = write_leakage_csv(
            self.results,
            [leak_row("9.898880e-11", OLD_JOB, OLD_TS)],
        )
        with self.assertRaises(RuntimeError) as ctx:
            D.load_worst_case_leakage(csv_path, self.results)
        self.assertIn("stamp-matched", str(ctx.exception))

    def test_wrong_pin_row_not_traceable(self):
        # A row citing the matched job but stamped with the old pin stays
        # excluded by the pin filter (issue #168 behavior retained).
        write_report(self.results, "klt_report_new.json", NEW_JOB, "match")
        csv_path = write_leakage_csv(
            self.results,
            [
                leak_row("9.898880e-11", NEW_JOB, OLD_TS, pin=OLD_PIN),
            ],
        )
        with self.assertRaises(RuntimeError):
            D.load_worst_case_leakage(csv_path, self.results)


if __name__ == "__main__":
    unittest.main()
