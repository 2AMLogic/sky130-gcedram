#!/usr/bin/env python3
"""Tests for refresh_overhead.py (issue #59). Run:
    python3 -I sim/refresh-overhead/test_refresh_overhead.py"""
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # `python -I` safe
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import refresh_overhead as R  # noqa: E402
import eval_measured_t_row as E  # noqa: E402


class FormulaUnits(unittest.TestCase):
    def test_dimensionless_fraction(self):
        # 100 rows x 50 ns = 5 us of work in a 5 us interval -> exactly 1.0
        self.assertAlmostEqual(R.overhead(100, 50e-9, 5e-6), 1.0)

    def test_linear_in_rows_and_time(self):
        a = R.overhead(8, 30e-9, 5.03e-6)
        self.assertAlmostEqual(R.overhead(16, 30e-9, 5.03e-6), 2 * a)
        self.assertAlmostEqual(R.overhead(8, 60e-9, 5.03e-6), 2 * a)

    def test_inverse_roundtrip(self):
        for f in R.THRESHOLDS:
            n = R.n_rows_at(f, 34e-9, 5.03e-6)
            self.assertTrue(math.isclose(R.overhead(n, 34e-9, 5.03e-6), f))

    def test_ns_vs_s_unit_slip_detected(self):
        # a ns-as-s slip would give ~1e9x; 34 ns x 64 rows / 5.03 us ~ 0.43
        self.assertTrue(0.1 < R.overhead(64, 34e-9, 5.03e-6) < 1.0)

    def test_max_pow2(self):
        self.assertEqual(R.max_pow2_le(0.5), 0)
        self.assertEqual(R.max_pow2_le(1), 1)
        self.assertEqual(R.max_pow2_le(147.9), 128)
        self.assertEqual(R.max_pow2_le(128), 128)


class Inputs(unittest.TestCase):
    def test_grid(self):
        self.assertEqual((R.N_ROWS_GRID[0], R.N_ROWS_GRID[-1]), (4, 1024))

    def test_ratified_interval_from_csv(self):
        rows = R.load_worst_case_retention()
        t = [float(r["retention_time_s"]) for r in rows]
        # spec Section 5/7: 10.06 us -> ~5.03 us interval, present in the CSV
        self.assertTrue(any(abs(x / 2 - 5.03e-6) < 0.01e-6 for x in t))

    def test_scenarios_sum(self):
        self.assertAlmostEqual(R.t_row_ns("anchored"), 34.0)


class QualifiedRetentionIdentity(unittest.TestCase):
    """G4 bases are selected by row identity, never position or value (#171):
    the 2026-10-28 row prints the same retention time as the qualified row,
    and the 3T-min row shares its timestamp. Only timestamp + geometry + the
    stamp-matched leakage job cited in the notes identify the qualified row."""

    def test_qualified_rows_are_the_two_identity_selected_bases(self):
        h, q = R.qualified_retention_rows()
        self.assertEqual(h["timestamp_utc"], R.HISTORICAL_ASSUMED_2T_TS)
        self.assertEqual(R.c_sn_basis(h), "ASSUMED margin factor")
        self.assertEqual(q["timestamp_utc"], R.QUALIFIED_EXTRACTED_2T_TS)
        self.assertEqual(q["geometry_name"], "2T-min")
        self.assertEqual(R.c_sn_basis(q), "EXTRACTED (layout)")
        self.assertIn(R.QUALIFIED_LEAKAGE_JOB_ID, q["notes"])

    def test_the_tied_october_row_cannot_occupy_the_qualified_slot(self):
        rows = R.load_worst_case_retention()
        tie = [r for r in rows if r["timestamp_utc"] == "2026-10-28T07:09:34+00:00"]
        _h, q = R.qualified_retention_rows()
        self.assertEqual(len(tie), 1)
        self.assertEqual(tie[0]["retention_time_s"], q["retention_time_s"])  # the value tie
        self.assertNotIn(R.QUALIFIED_LEAKAGE_JOB_ID, tie[0]["notes"])        # but not the identity
        with self.assertRaises(SystemExit):
            R.select_retention_row(rows, "2026-10-28T07:09:34+00:00", leakage_job=R.QUALIFIED_LEAKAGE_JOB_ID)

    def test_missing_qualified_row_fails_closed(self):
        rows = [r for r in R.load_worst_case_retention()
                if r["timestamp_utc"] != R.QUALIFIED_EXTRACTED_2T_TS]
        with self.assertRaises(SystemExit):
            R.select_retention_row(rows, R.QUALIFIED_EXTRACTED_2T_TS, leakage_job=R.QUALIFIED_LEAKAGE_JOB_ID)

    def test_same_timestamp_3t_row_is_not_the_qualified_2t_row(self):
        rows = R.load_worst_case_retention()
        all_rows_3t = [dict(r) for r in rows]
        all_rows_3t.append(dict(rows[0], geometry_name="3T-min",
                                timestamp_utc=R.QUALIFIED_EXTRACTED_2T_TS))
        picked = R.select_retention_row(all_rows_3t, R.QUALIFIED_EXTRACTED_2T_TS)
        self.assertEqual(picked["geometry_name"], "2T-min")


class EvalMeasuredGate(unittest.TestCase):
    """A measured-overhead record is a qualified result (#171): the
    refresh-op report behind the summary must carry a worker stamp
    comparison of 'match' (fail closed on mismatch / not_comparable /
    missing), and the appended rows must cover exactly the two
    identity-selected retention bases."""

    PIN_STAMP = "open_pdks f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7"

    @staticmethod
    def _summary():
        frac = {"slowest_corner": "fs/27C", "t_row_refresh_op_ns": 14.0}
        return {"run_id": "TEST", "batch_job_id": "klt-sim-test",
                "slowest_corner_t_row_refresh_op": {"0.9": frac, "0.95": frac, "0.98": frac},
                "slowest_corner_t_row_refresh_op_contract_sense_10ns": {
                    "0.9": frac, "0.95": frac, "0.98": frac}}

    @staticmethod
    def _report(status, stamp_text=PIN_STAMP):
        return {"status": "pass", "environment": {"remote": {"job_id": "klt-sim-test", "worker_environment": {
            "pdk": {"stamp_text": stamp_text}, "pdk_stamp_comparison": {"status": status}}}}}

    def _run(self, report_status, stamp_text=PIN_STAMP):
        """(rc, rows) of a gate run; rows is [] when nothing was appended."""
        import csv as _csv
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "refresh_op_summary_TEST.json").write_text(json.dumps(self._summary()))
            (d / "klt_report_TEST.json").write_text(json.dumps(self._report(report_status, stamp_text)))
            measured = d / "measured.csv"
            rc = E.main([str(d / "refresh_op_summary_TEST.json"), "--report", str(d / "klt_report_TEST.json"),
                         "--measured-csv", str(measured)])
            rows = list(_csv.DictReader(measured.open())) if measured.exists() else []
            return rc, rows

    def test_match_report_appends_identity_selected_bases_only(self):
        rc, rows = self._run("match")
        self.assertEqual(rc, 0)
        self.assertEqual({row["refresh_op_batch_job_id"] for row in rows}, {"klt-sim-test"})
        bases = {(r["retention_row_timestamp_utc"], r["retention_c_sn_basis"]) for r in rows}
        self.assertEqual(bases, {(R.HISTORICAL_ASSUMED_2T_TS, "ASSUMED margin factor"),
                                 (R.QUALIFIED_EXTRACTED_2T_TS, "EXTRACTED (layout)")})
        qualified = [r for r in rows if r["retention_row_timestamp_utc"] == R.QUALIFIED_EXTRACTED_2T_TS]
        self.assertTrue(qualified)
        self.assertIn(R.QUALIFIED_LEAKAGE_JOB_ID, qualified[0]["notes"])
        self.assertNotIn(R.QUALIFIED_EXTRACTED_2T_TS.replace("2026-11-20", "2026-10-28"),
                         {r["retention_row_timestamp_utc"] for r in rows})

    def test_job_ids_must_match_before_appending(self):
        with tempfile.TemporaryDirectory() as td:
            summary_path = Path(td) / "refresh_op_summary_TEST.json"
            report_path = Path(td) / "klt_report_TEST.json"
            measured = Path(td) / "measured.csv"
            with E.MEASURED_CSV.open("rb") as source:
                original = source.readline() + source.readline()  # header and one historical row
            args = [str(summary_path), "--measured-csv", str(measured)]
            summary = self._summary()
            report = self._report("match")
            for summary_job, report_job in (("klt-sim-old", "klt-sim-new"),
                                            ("klt-sim-test", None), (None, None),
                                            ("", ""), (" ", " ")):
                summary["batch_job_id"] = summary_job
                report["environment"]["remote"]["job_id"] = report_job
                summary_path.write_text(json.dumps(summary))
                report_path.write_text(json.dumps(report))
                for option in ([], ["--report", str(report_path)]):
                    with self.subTest(summary_job=summary_job, report_job=report_job, option=option):
                        measured.write_bytes(original)
                        self.assertEqual(E.main(args + option), 1)
                        self.assertEqual(measured.read_bytes(), original)

    def test_mismatch_report_appends_nothing(self):
        rc, rows = self._run("mismatch", "open_pdks c6d73a35f524070e85faff4a6a9eef49553ebc2b")
        self.assertEqual(rc, 1)
        self.assertEqual(rows, [])

    def test_not_comparable_report_appends_nothing(self):
        # the committed 2026-11-15 refresh-op report carries this status
        rc, rows = self._run("not_comparable")
        self.assertEqual(rc, 1)
        self.assertEqual(rows, [])

    def test_missing_report_refuses(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "refresh_op_summary_TEST.json").write_text(json.dumps(self._summary()))
            rc = E.main([str(d / "refresh_op_summary_TEST.json")])
            self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
