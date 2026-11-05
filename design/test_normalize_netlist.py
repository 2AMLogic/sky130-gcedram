#!/usr/bin/env python3
"""Stdlib-only tests for ``normalize_netlist.py --check`` (issue #229).

Covers the raw -> normalized freshness leg of T1 item 1: the committed
netlists must equal normalize(raw) with a header whose schematic sha256 is
current, and a hand edit of either must make the check fail. No xschem,
ngspice or PDK needed.

Run: python3 -I design/test_normalize_netlist.py
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "normalize_netlist.py"
CELLS = ("gain_cell_2t", "sense_latch", "column_periphery")


def run_check(raw: Path, norm: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--check", str(raw), str(norm)],
        capture_output=True, text=True,
    )


class CommittedNetlists(unittest.TestCase):
    def test_committed_cells_are_fresh(self):
        for cell in CELLS:
            with self.subTest(cell=cell):
                r = run_check(HERE / f"{cell}.raw.spice", HERE / f"{cell}.spice")
                self.assertEqual(r.returncode, 0, r.stderr)

    def test_raw_has_repo_relative_sch_path(self):
        for cell in CELLS:
            first = (HERE / f"{cell}.raw.spice").read_text().split("\n", 1)[0]
            self.assertEqual(first, f"** sch_path: design/{cell}.sch")


class NegativeControls(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "design").mkdir()
        for cell in CELLS[:1]:
            for ext in ("raw.spice", "spice", "sch"):
                shutil.copy(HERE / f"{cell}.{ext}", self.tmp / "design")
        self.raw = self.tmp / "design" / "gain_cell_2t.raw.spice"
        self.norm = self.tmp / "design" / "gain_cell_2t.spice"
        self.sch = self.tmp / "design" / "gain_cell_2t.sch"

    def test_baseline_passes(self):
        self.assertEqual(run_check(self.raw, self.norm).returncode, 0)

    def test_hand_edited_normalized_body_fails(self):
        self.norm.write_text(self.norm.read_text().replace("W=0.42", "W=0.43", 1))
        r = run_check(self.raw, self.norm)
        self.assertEqual(r.returncode, 1)
        self.assertIn("stale against normalize", r.stderr)

    def test_edited_raw_fails(self):
        self.raw.write_text(self.raw.read_text().replace("W=0.42", "W=0.43", 1))
        self.assertEqual(run_check(self.raw, self.norm).returncode, 1)

    def test_edited_schematic_fails_header_hash(self):
        self.sch.write_text(self.sch.read_text() + "\n")
        r = run_check(self.raw, self.norm)
        self.assertEqual(r.returncode, 1)
        self.assertIn("sha256", r.stderr)

    def test_header_hash_matches_file(self):
        digest = hashlib.sha256(self.sch.read_bytes()).hexdigest()
        self.assertIn(f"sha256:{digest}", self.norm.read_text())


if __name__ == "__main__":
    unittest.main()
