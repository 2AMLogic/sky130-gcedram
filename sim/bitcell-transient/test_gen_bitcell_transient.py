#!/usr/bin/env python3
"""Tests for gen_bitcell_transient.py / reduce_bitcell_transient.py (issue #182).
Run: python3 -I sim/bitcell-transient/test_gen_bitcell_transient.py"""
import csv
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gen_bitcell_transient as G  # noqa: E402
import reduce_bitcell_transient as RED  # noqa: E402


class Generator(unittest.TestCase):
    def test_committed_files_are_current_and_byte_identical_on_rerun(self):
        first, second = G.render_all(), G.render_all()
        self.assertEqual(first, second)
        for name, text in first.items():
            self.assertEqual((HERE / name).read_text(), text, f"{name} is stale: re-run gen_bitcell_transient.py")

    def test_no_absolute_include_or_control_block(self):
        for d in (1, 0):
            deck = (HERE / f"bitcell_d{d}.spice").read_text()
            self.assertNotIn(".include", deck)
            self.assertNotIn(".control", deck)
            self.assertNotIn("/home/", deck)

    def test_design_devices_inlined_verbatim(self):
        deck = (HERE / "bitcell_d1.spice").read_text()
        for line in G.design_device_lines():
            self.assertIn(line, deck)

    def test_read_request_uses_fine_tmax_not_hold_tmax(self):
        req = G.build_read(1)
        self.assertTrue(req["analysis"]["args"].endswith("1.000000e-11"))
        hold = G.build_hold(1, 125, 1e-4, "tt")
        self.assertNotEqual(hold["analysis"]["args"].split()[-1], "1.000000e-11")

    def test_pvt_coverage(self):
        self.assertEqual(len(G.PROCESS_CORNERS) * len(G.TEMPS_C), 15)
        self.assertEqual(G.build_read(1)["corners"]["temperature_c"], [-40, 27, 125])

    def test_leakage_loader_ignores_other_pin(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "l.csv"
            with p.open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["pdk_open_pdks_commit", "corner", "temp_c", "ileak_a"])
                w.writerow(["c6d73a35f524070e85faff4a6a9eef49553ebc2b", "tt", "27", "9e-9"])
                w.writerow([G.PIN, "tt", "27", "2e-12"])
            self.assertEqual(G.load_leakage_current_pin(p), {("tt", 27): 2e-12})

    def test_hold_end_instant_inside_tstop(self):
        req = G.build_hold(1, 27, 5e-3, "tt")
        stop = float(req["analysis"]["args"].split()[1])
        end = [m for m in req["measurements"] if m["name"] == "v_sn_hold_end_v"][0]["spice"]
        self.assertLess(float(end.split("AT=")[1]), stop)


class Reducer(unittest.TestCase):
    def test_ladder_crossing_cubic_exact_on_cubic(self):
        f = lambda v: 3e-3 - 2e-3 * v + 1e-3 * v * v - 5e-4 * v ** 3
        ladder = {mv / 1000: f(mv / 1000) for mv in G.LADDER_MV}
        self.assertAlmostEqual(RED.ladder_crossing(0.1362, ladder), f(0.1362), places=12)

    def test_ladder_crossing_outside_or_uncrossed_is_none(self):
        ladder = {mv / 1000: 1e-3 for mv in G.LADDER_MV}
        self.assertIsNone(RED.ladder_crossing(0.9, ladder))
        self.assertIsNone(RED.ladder_crossing(0.1, {0.05: None, 0.075: None, 0.1: None, 0.125: None}))


if __name__ == "__main__":
    unittest.main()
