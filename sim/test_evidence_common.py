#!/usr/bin/env python3
"""Unit tests for the shared SPICE/waveform helpers in _evidence_common.py
(issue #58). Run: python3 sim/test_evidence_common.py"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # `python -I` safe
import _evidence_common as C  # noqa: E402


class SpiceNumber(unittest.TestCase):
    def test_suffixes(self):
        self.assertEqual(C.spice_number("1k"), 1e3)
        self.assertEqual(C.spice_number("1meg"), 1e6)
        self.assertAlmostEqual(C.spice_number("100p"), 1e-10, places=22)
        self.assertEqual(C.spice_number("1.8"), 1.8)
        self.assertEqual(C.spice_number("1e-9"), 1e-9)

    def test_bad(self):
        with self.assertRaises(ValueError):
            C.spice_number("1x")
        with self.assertRaises(ValueError):
            C.spice_number("@@VRBL@@")


class Interp(unittest.TestCase):
    def test_basic_and_clamp(self):
        t, y = [0.0, 1.0, 2.0], [0.0, 10.0, 20.0]
        self.assertEqual(C.interp_at(t, y, 0.5), 5.0)
        self.assertEqual(C.interp_at(t, y, -1), 0.0)
        self.assertEqual(C.interp_at(t, y, 9), 20.0)

    def test_duplicate_timestamp(self):
        t, y = [0.0, 1.0, 1.0, 2.0], [0.0, 1.0, 5.0, 6.0]
        self.assertEqual(C.interp_at(t, y, 1.0), 5.0)
        self.assertEqual(C.interp_at(t, y, 1.5), 5.5)


class Crossings(unittest.TestCase):
    t, y = [0.0, 1.0, 2.0, 3.0], [1.0, 1.0, 0.5, 0.0]

    def test_semantics_differ(self):
        # absolute vs relative to t0
        self.assertAlmostEqual(C.first_crossing_below(self.t, self.y, 0.25, 1.0), 2.5)
        self.assertAlmostEqual(C.first_below(self.t, self.y, 1.0, 0.25), 1.5)
        # already below at start: first sample time vs 0.0
        self.assertEqual(C.first_crossing_below(self.t, self.y, 2.0, 0.5), 1.0)
        self.assertEqual(C.first_below(self.t, self.y, 0.5, 2.0), 0.0)
        self.assertIsNone(C.first_below(self.t, self.y, 0.0, -1.0))
        self.assertIsNone(C.first_crossing_below(self.t, self.y, -1.0, 0.0))


class ReadWrdata(unittest.TestCase):
    def test_layout_and_min_points(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "w.dat"
            p.write_text("junk\n" + "".join(
                f"{i} {i*2} {i} {i*3}\n" for i in range(5)))
            cols = C.read_wrdata(p, 3)
            self.assertEqual(cols, [[0, 1, 2, 3, 4], [0, 2, 4, 6, 8], [0, 3, 6, 9, 12]])
            with self.assertRaises(RuntimeError):
                C.read_wrdata(p, 10)


if __name__ == "__main__":
    unittest.main()
