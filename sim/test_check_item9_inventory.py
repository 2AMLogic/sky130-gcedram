#!/usr/bin/env python3
"""Fixtures for sim/check_item9_inventory.py (issue #371).

Builds throwaway git repos and runs the checker as CI does. Stdlib only; needs
git. Run: python3 -I sim/test_check_item9_inventory.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CHECKER = Path(__file__).resolve().parent / "check_item9_inventory.py"
GIT_ENV = {
    **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


def make_repo(root: Path, files: list[str], inventory: list[str]) -> None:
    for f in files:
        p = root / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x\n")
    (root / "attest").mkdir(exist_ok=True)
    (root / "attest/item9.json").write_text(json.dumps({"testbenches": inventory}))
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True, env=GIT_ENV)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, env=GIT_ENV)


def run(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-I", str(CHECKER), "--repo", str(root)],
        capture_output=True, text=True, env=GIT_ENV,
    )


class Item9Inventory(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_all_present_passes(self):
        make_repo(self.root, ["sim/a/d.spice", "sim/a/request_x.json", "sim/a/d2.spice.tmpl"],
                  ["sim/a/d.spice", "sim/a/request_x.json", "sim/a/d2.spice.tmpl"])
        r = run(self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_missing_candidate_fails(self):
        make_repo(self.root, ["sim/a/d.spice", "sim/a/e.spice"], ["sim/a/d.spice"])
        r = run(self.root)
        self.assertEqual(r.returncode, 1)
        self.assertIn("sim/a/e.spice", r.stdout)

    def test_stale_entry_fails(self):
        make_repo(self.root, ["sim/a/d.spice"], ["sim/a/d.spice", "sim/a/gone.spice"])
        r = run(self.root)
        self.assertEqual(r.returncode, 1)
        self.assertIn("sim/a/gone.spice", r.stdout)

    def test_results_and_non_candidates_ignored(self):
        make_repo(self.root, ["sim/a/d.spice", "sim/a/results/r.spice",
                              "sim/a/results/request_r.json", "sim/a/config.json",
                              "other/z.spice"], ["sim/a/d.spice"])
        r = run(self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_excluded_path_ignored(self):
        sys.path.insert(0, str(CHECKER.parent))
        try:
            import check_item9_inventory as m
        finally:
            sys.path.pop(0)
        old = m.EXCLUDE
        m.EXCLUDE = frozenset({"sim/a/skip.spice"})
        try:
            missing, stale = m.check({"sim/a/skip.spice", "sim/a/d.spice"}, {"sim/a/d.spice"})
        finally:
            m.EXCLUDE = old
        self.assertEqual((missing, stale), ([], []))

    def test_git_failure_exit_2(self):
        r = run(self.root)  # not a git repo
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
