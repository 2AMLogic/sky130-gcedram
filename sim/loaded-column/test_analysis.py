#!/usr/bin/env python3
"""Tests for analyze_loaded_column.py (issue #45). Run:
    python3 sim/loaded-column/test_analysis.py
Synthetic cases always run; the committed-results cases run when
results/loaded_column_results.csv exists."""

import contextlib
import csv
import io
import itertools
import tempfile
import unittest
from pathlib import Path

import analyze_loaded_column as A
HERE = Path(__file__).resolve().parent
sys_path = None


def synth(path, drop=None, sep=0.3):
    import sys
    sys.path.insert(0, str(HERE))
    import run_loaded_column as R
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=R.FIELDS)
        w.writeheader()
        for s, p in itertools.product(range(4), range(16)):
            if drop == (s, p):
                continue
            bit = (p >> s) & 1
            row = {k: "x" for k in R.FIELDS}
            row.update(run_id="T", corner="tt", temp_c="27", age_label="fresh", sel_row=s,
                       stored_value=bit, pattern_rows3210=format(p, "04b"), status="ok",
                       reason="", v_rbl_sense_v=(0.1 if bit else 0.1 + sep), latency_s="1e-9",
                       latency_reason="", c_rbl_ff_ASSUMPTION="10", t_sense_s_ASSUMPTION="1e-8",
                       dv_latency_v_ASSUMPTION="0.1", c_sn_ff="0.6")
            for k in R.FIELDS:
                if k.startswith(("v_sn_", "i_into", "dv_sn", "dv_rbl")):
                    row[k] = "0.0"
            w.writerow(row)


def run(args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = A.main(args)
    return rc


SCOPE = ["--corners", "tt", "--temps-c", "27", "--ages", "fresh", "--no-summary"]


class Synthetic(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.csv = Path(self.d.name) / "r.csv"

    def tearDown(self):
        self.d.cleanup()

    def test_pass(self):
        synth(self.csv)
        self.assertEqual(run(["--results-csv", str(self.csv)] + SCOPE), 0)
        self.assertEqual(run(["--results-csv", str(self.csv), "--min-separation-v", "0.25"] + SCOPE), 0)

    def test_impossible_threshold_fails(self):
        synth(self.csv)
        self.assertEqual(run(["--results-csv", str(self.csv), "--min-separation-v", "50"] + SCOPE), 2)

    def test_missing_point_fails_coverage(self):
        synth(self.csv, drop=(2, 5))
        self.assertEqual(run(["--results-csv", str(self.csv)] + SCOPE), 1)

    def test_negative_separation_visible(self):
        synth(self.csv, sep=-0.2)
        self.assertEqual(run(["--results-csv", str(self.csv), "--min-separation-v", "0"] + SCOPE), 2)


@unittest.skipUnless(A.RESULTS_CSV.exists(), "no committed campaign results")
class Committed(unittest.TestCase):
    def test_coverage_and_provenance(self):
        self.assertEqual(run(["--no-summary"]), 0)

    def test_impossible_threshold_fails(self):
        self.assertEqual(run(["--no-summary", "--min-separation-v", "50"]), 2)


if __name__ == "__main__":
    unittest.main()
