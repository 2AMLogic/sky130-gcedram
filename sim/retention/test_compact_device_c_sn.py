#!/usr/bin/env python3
"""Stdlib-only checks for sim/retention/compact_device_c_sn.py (issue #208). No ngspice, PDK or klt.

Run: python3 -I sim/retention/test_compact_device_c_sn.py
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
import compact_device_c_sn as M  # noqa: E402


def synth_times(c_ff: float, i_a: float) -> list[float]:
    """Crossing times of a LINEAR capacitor discharged by a constant current from 1.1 V (+ a fixed 1 ns lead)."""
    return [1e-9 + (M.LEVELS_V[0] - v) * c_ff * 1e-15 / i_a for v in M.LEVELS_V]


class Reducer(unittest.TestCase):
    def test_known_capacitor_recovered(self):
        for c in (0.3, 1.0, 2.5):
            t = synth_times(c, M.I_TEST_A)
            self.assertAlmostEqual(M.c_window_ff(t, M.I_TEST_A), c, places=9)
            for step in M.c_steps_ff(t, M.I_TEST_A):
                self.assertAlmostEqual(step, c, places=9)

    def test_nonlinear_window_is_charge_average(self):
        # C = 0.5 fF above 0.55 V, 1.0 fF below: the window value is the charge-weighted mean, 0.75 fF
        q = [0.0]
        for v0, v1 in zip(M.LEVELS_V, M.LEVELS_V[1:]):
            q.append(q[-1] + (v0 - v1) * (0.5 if v0 > 0.55 else 1.0) * 1e-15)
        t = [x / M.I_TEST_A for x in q]
        self.assertAlmostEqual(M.c_window_ff([x + 1e-9 for x in t], M.I_TEST_A), 0.5 * 5 / 9 + 1.0 * 4 / 9, places=6)

    def test_retention_formula(self):
        self.assertAlmostEqual(M.retention_us(0.317, 1.0595e-10) * 1.0, 0.317e-15 * 0.9 / 1.0595e-10 * 1e6, places=9)


class Generated(unittest.TestCase):
    def test_committed_deck_and_request_not_stale(self):
        self.assertEqual(M.check_generated(), 0)

    def test_request_covers_15_pvt_points_and_every_instance_level(self):
        req = json.loads(M.REQUEST_PATH.read_text())
        self.assertEqual(len(req["corners"]["process"]) * len(req["corners"]["temperature_c"]), 15)
        self.assertEqual(req["backend"], "batch")
        names = {m["name"] for m in req["measurements"]}
        self.assertEqual(len(names), 50 * len(M.LEVELS_V))   # 16 nodes x 3 variants + rate + ctl
        self.assertIn(M.meas_name("ctl", 1.0), names)

    def test_poly_variant_removes_exactly_the_poly_term_of_the_probed_node(self):
        deck = M.DECK_PATH.read_text()
        poly = M.storage(json.loads(M.V2_EXTRACT.read_text()))
        node = M.limiting_node(json.loads(M.V2_EXTRACT.read_text()))
        arr = M.parse_v2()
        full = next(f for nm, n1, n2, f in arr["cap"] if (n1, n2) == (node, "vsubs"))
        tag = f"c_{M.short(node)[1:]}_p_{M.short(node)}"
        line = next(ln for ln in deck.splitlines() if ln.startswith(tag + " "))
        self.assertAlmostEqual(float(line.split()[-1]), full - poly[node] * 1e-15, delta=1e-20)


class Committed(unittest.TestCase):
    def test_committed_results_reproduce_and_pass_their_controls(self):
        files = sorted((HERE / "results").glob(f"{M.RESULT_PREFIX}*.json"))
        self.assertTrue(files)
        for f in files:
            self.assertEqual(M.cmd_check(f), 0, f)
            d = json.loads(f.read_text())
            self.assertTrue(d["checks"]["control_ok"] and d["checks"]["rate_check_ok"])
            self.assertEqual(d["n_points"], 15)


if __name__ == "__main__":
    unittest.main()
