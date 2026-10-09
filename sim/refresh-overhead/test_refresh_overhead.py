#!/usr/bin/env python3
"""Tests for refresh_overhead.py (issue #59). Run:
    python3 -I sim/refresh-overhead/test_refresh_overhead.py"""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # `python -I` safe

import refresh_overhead as R


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


if __name__ == "__main__":
    unittest.main()
