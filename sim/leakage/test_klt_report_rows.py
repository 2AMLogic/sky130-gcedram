#!/usr/bin/env python3
"""Stdlib-only checks for the klt-report row reducer (issue #377). No
ngspice, PDK or klt needed: `rows_from_klt_report` must fail closed unless
the report's worker PDK stamp comparison is "match".

Run: python3 -I sim/leakage/test_klt_report_rows.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_leakage_sweep as S  # noqa: E402

RES = HERE / "results"
COMMITTED_MISMATCHED_REPORT = RES / "klt_report_20261016T0731Z.json"
OLD_PIN = "c6d73a35f524070e85faff4a6a9eef49553ebc2b"  # the issue #168 worker revision


def synth_report(stamp_status, stamp_text=None):
    """Minimal report shaped like sim/leakage/results/klt_report_*.json.

    `stamp_status` is the `pdk_stamp_comparison.status` to embed; None
    omits the block entirely (the fail-closed "absent" case).
    `stamp_text` is the worker's PDK stamp; it defaults to the repo pin
    (as in a genuine stamp-matched report) and can name another revision
    to exercise the stamp-text clause of the gate."""
    corners = []
    for process in S.DEFAULT_CORNERS:
        for temp_c in S.DEFAULT_TEMPS_C:
            corners.append(
                {
                    "corner_id": f"{process}/novdd/{temp_c}C",
                    "process": process,
                    "temperature_c": temp_c,
                    "status": "pass",
                    "measurements": [
                        {
                            "name": "ileak_a",
                            "value": 1.0e-12,
                            "unit": "A",
                            "status": "pass",
                        }
                    ],
                }
            )
    worker_env = {
        "pdk": {"stamp_text": stamp_text or f"open_pdks {S.PDK_OPEN_PDKS_COMMIT}"},
    }
    if stamp_status is not None:
        worker_env["pdk_stamp_comparison"] = {"status": stamp_status}
    return {
        "status": "pass",
        "failed": 0,
        "errored": 0,
        "corners": corners,
        "environment": {
            "engine_version": "47",
            "remote": {
                "job_id": "klt-sim-testjob000001",
                "worker_environment": worker_env,
            },
        },
    }


def write_report(report, suffix=".json"):
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=suffix, prefix="klt_report_test_", delete=False
    )
    with f:
        json.dump(report, f)
    return Path(f.name)


class StampMatchGuard(unittest.TestCase):
    def test_match_appends(self):
        rows = S.rows_from_klt_report(write_report(synth_report("match")))
        self.assertEqual(len(rows), 15)
        for row in rows:
            self.assertIn("klt sim batch job klt-sim-testjob000001", row["notes"])
            self.assertEqual(row["pdk_open_pdks_commit"], S.PDK_OPEN_PDKS_COMMIT)
            self.assertEqual(row["ileak_a"], "1.000000e-12")

    def test_mismatch_refused(self):
        path = write_report(synth_report("mismatch"))
        with self.assertRaises(RuntimeError) as ctx:
            S.rows_from_klt_report(path)
        self.assertIn("mismatch", str(ctx.exception))

    def test_absent_comparison_refused(self):
        # Fail closed: no pdk_stamp_comparison block at all.
        with self.assertRaises(RuntimeError) as ctx:
            S.rows_from_klt_report(write_report(synth_report(None)))
        self.assertIn("stamp comparison", str(ctx.exception))

    def test_absent_worker_environment_refused(self):
        report = synth_report("match")
        del report["environment"]["remote"]["worker_environment"]
        with self.assertRaises(RuntimeError):
            S.rows_from_klt_report(write_report(report))

    def test_other_status_refused(self):
        with self.assertRaises(RuntimeError):
            S.rows_from_klt_report(write_report(synth_report("unknown")))

    def test_match_against_another_revision_refused(self):
        # A status of "match" only proves the worker's PDK equals the
        # submitter's local PDK (issue #439): a submitter on a stale PDK
        # gets "match" against a worker on that same stale revision. The
        # worker stamp text must also name the repo pin before rows may
        # carry it.
        report = synth_report("match", stamp_text=f"open_pdks {OLD_PIN}")
        with self.assertRaises(RuntimeError) as ctx:
            S.rows_from_klt_report(write_report(report))
        self.assertIn("does not name the pinned commit", str(ctx.exception))

    def test_committed_mismatched_report_refused(self):
        # The real issue #168 report (job klt-sim-c2ed3f15ab70, worker
        # resolved c6d73a3... while the CSV rows say f6eeac7...) must now
        # be refused by the reducer that originally appended it.
        self.assertTrue(COMMITTED_MISMATCHED_REPORT.is_file())
        with self.assertRaises(RuntimeError) as ctx:
            S.rows_from_klt_report(COMMITTED_MISMATCHED_REPORT)
        self.assertIn("mismatch", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
