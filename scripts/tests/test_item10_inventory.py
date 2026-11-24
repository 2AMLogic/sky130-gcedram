#!/usr/bin/env python3
"""Completeness check for attest/item10.json against the evidence runner (issue #414).

``klt signoff --attest 10`` grades only the commands the inventory lists, and
the item-10 grade is that list's own length, so a check the evidence runner
executes but the inventory omits is invisible to the gate. The runner,
``scripts/run_evidence_checks.py``, discovers its command list at run time,
which leaves the inventory as the only hand-kept copy. This suite imports the
runner's discovery and command-building code, enumerates the same list
without executing anything (so it can check its own entry without
recursion), and compares it with the inventory's ``python3`` entries by
argument vector, with multiplicity. It fails naming every command that is
missing, stale, duplicated or graded with different arguments. The
``klt drc/lvs --check`` entries and the content-hashed ``hygiene`` files are
outside the comparison.

Stdlib only; needs ``git``.
Run: python3 -I scripts/tests/test_item10_inventory.py [--repo DIR]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
INVENTORY = "attest/item10.json"
REPO = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
import run_evidence_checks as runner  # noqa: E402

GIT_ENV = {
    **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


def graded(script: str, *args: str) -> list[str]:
    """The inventory's form of one runner command."""
    return [*runner.INTERPRETER, script, *args]


def runner_commands(repo: Path) -> list[list[str]]:
    """Every command the evidence runner executes in ``repo``, in the form item 10
    grades it: ``python3 -I`` then the argv the runner hands its interpreter,
    without its ``--`` option terminator. Discovers suites the way the runner
    does, from the repository root, and executes nothing."""
    cwd = os.getcwd()
    os.chdir(repo)
    try:
        suites = runner.discover_suites()
    finally:
        os.chdir(cwd)
    if suites is None or not suites:
        raise RuntimeError(f"the evidence runner could not discover suites in {repo}")
    return [graded(*argv) for argv in runner.evidence_commands(suites)]


def graded_commands(inventory: dict) -> list[list[str]]:
    """The ``python3`` entries of an item-10 inventory document, in file order."""
    return [list(check["argv"]) for check in inventory["checks"]
            if check["argv"][0] == runner.INTERPRETER[0]]


def script(argv: tuple[str, ...]) -> str:
    """The script a ``python3 -I <script> [args...]`` vector runs; '' if none."""
    return argv[2] if len(argv) > 2 else ""


def compare(expected: list[list[str]], graded: list[list[str]]) -> list[str]:
    """Diagnose how ``graded`` differs from ``expected``; empty when they match.

    Both are multisets of ``python3`` argument vectors: ``expected`` is what
    the runner executes and ``graded`` what the inventory lists. A graded
    vector matches an expected one only when every argument agrees, and each
    vector matches at most as many times as it occurs.
    """
    leftover = Counter(tuple(argv) for argv in graded)
    missing = []
    for argv in expected:
        if leftover[tuple(argv)]:
            leftover[tuple(argv)] -= 1
        else:
            missing.append(tuple(argv))
    leftover = +leftover
    runs = Counter(tuple(argv) for argv in expected)
    grades = Counter(tuple(argv) for argv in graded)
    problems = []
    for key in missing:
        # Same script with different arguments is one edited entry, not one
        # command missing and another one stale.
        edited = next((k for k in leftover if script(k) == script(key)), None)
        if edited is not None:
            leftover.subtract([edited])
            problems.append(f"argument mismatch: {INVENTORY} grades `{' '.join(edited)}`, "
                            f"the evidence runner runs `{' '.join(key)}`")
        else:
            problems.append(f"not inventoried in {INVENTORY}: `{' '.join(key)}`")
    for key in +leftover:
        if runs[key]:
            problems.append(f"duplicated in {INVENTORY}: `{' '.join(key)}` is graded "
                            f"{grades[key]} times, run {runs[key]}")
        else:
            problems.append(f"inventoried but not run by the evidence runner: `{' '.join(key)}`")
    return problems


def make_repo(root: Path, suites: list[str], entries: list[list[str]]) -> None:
    """A throwaway git repo of empty suites whose item-10 inventory lists ``entries``."""
    for s in suites:
        p = root / s
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("import unittest\n")
    (root / INVENTORY).parent.mkdir()
    (root / INVENTORY).write_text(json.dumps(
        {"checks": [{"name": a[2], "argv": a} for a in entries]}))
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True, env=GIT_ENV)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, env=GIT_ENV)


def run_gate(repo: Path) -> subprocess.CompletedProcess:
    """Run this suite's gate test against ``repo``, as the runner does."""
    return subprocess.run(
        [sys.executable, "-I", str(Path(__file__).resolve()), "--repo", str(repo),
         Item10Inventory.__name__],
        capture_output=True, text=True, env=GIT_ENV)


STANDALONE = [graded(*argv) for argv in runner.STANDALONE_CHECKS]


class Compare(unittest.TestCase):
    def test_matching_multisets_pass(self):
        a, b = graded("sim/a/test_a.py"), graded("sim/b/test_b.py")
        c = graded("scripts/check_artifact_manifests.py", "check")
        self.assertEqual(compare([a, b, c], [c, a, b]), [])

    def test_ungraded_command_is_named_missing(self):
        a, new = graded("sim/a/test_a.py"), graded("sim/b/test_new.py")
        self.assertEqual(compare([a, new], [a]),
                         ["not inventoried in attest/item10.json: `python3 -I sim/b/test_new.py`"])

    def test_command_no_longer_run_is_named_stale(self):
        a, gone = graded("sim/a/test_a.py"), graded("sim/a/test_gone.py")
        self.assertEqual(compare([a], [a, gone]),
                         ["inventoried but not run by the evidence runner: `python3 -I sim/a/test_gone.py`"])

    def test_replaced_entry_is_named_duplicate_with_count_unchanged(self):
        a, b, c = graded("sim/a/test_a.py"), graded("sim/b/test_b.py"), graded("sim/c/test_c.py")
        self.assertEqual(compare([a, b, c], [a, a, c]), [
            "not inventoried in attest/item10.json: `python3 -I sim/b/test_b.py`",
            "duplicated in attest/item10.json: `python3 -I sim/a/test_a.py` is graded 2 times, run 1",
        ])

    def test_dropped_argument_is_named_a_mismatch(self):
        full = graded("scripts/check_artifact_manifests.py", "check")
        short = graded("scripts/check_artifact_manifests.py")
        self.assertEqual(compare([full], [short]), [
            "argument mismatch: attest/item10.json grades "
            "`python3 -I scripts/check_artifact_manifests.py`, the evidence runner runs "
            "`python3 -I scripts/check_artifact_manifests.py check`",
        ])

    def test_each_run_needs_its_own_entry(self):
        x = graded("sim/a/test_x.py", "fast")
        self.assertEqual(compare([x, x], [x]),
                         ["not inventoried in attest/item10.json: `python3 -I sim/a/test_x.py fast`"])


class GradedCommands(unittest.TestCase):
    def test_only_python_entries_are_compared(self):
        inventory = {"checks": [
            {"name": "a", "argv": graded("sim/a/test_a.py")},
            {"name": "drc", "argv": ["klt", "drc", "--check", "x.json"], "cwd": "layout"},
            {"name": "m", "argv": graded("scripts/check_artifact_manifests.py", "check")},
        ]}
        self.assertEqual(graded_commands(inventory),
                         [graded("sim/a/test_a.py"), graded("scripts/check_artifact_manifests.py", "check")])


class DisposableRepo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_synchronized_inventory_passes(self):
        suites = ["sim/a/test_a.py", "layout/test_b.py"]
        make_repo(self.root, suites, [graded(s) for s in suites] + STANDALONE)
        r = run_gate(self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_uninventoried_suite_fails_naming_it(self):
        suites = ["sim/a/test_a.py", "sim/b/test_new.py"]
        make_repo(self.root, suites, [graded(suites[0])] + STANDALONE)
        r = run_gate(self.root)
        self.assertEqual(r.returncode, 1)
        self.assertIn("not inventoried in attest/item10.json: `python3 -I sim/b/test_new.py`", r.stdout + r.stderr)

    def test_suites_under_excluded_trees_are_ignored(self):
        suites = ["sim/a/test_a.py", ".loom/b/test_x.py", ".claude/b/test_x.py", ".agents/b/test_x.py"]
        make_repo(self.root, suites, [graded(suites[0])] + STANDALONE)
        r = run_gate(self.root)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class Item10Inventory(unittest.TestCase):
    """The gate: the committed inventory against the runner's real command list."""

    def test_every_evidence_runner_command_is_graded_once(self):
        with open(REPO / INVENTORY, encoding="utf-8") as fh:
            inventory = json.load(fh)
        problems = compare(runner_commands(REPO), graded_commands(inventory))
        if problems:
            self.fail("\n".join(problems)
                      + f"\nSync the python3 entries in {INVENTORY} with scripts/run_evidence_checks.py, "
                      "then regenerate attest/item10.envelope.json with the pinned klt and refresh "
                      "the block-manifest.json pins (spec/t1-analog-attestation-decision.md).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--repo", help="repository to check (default: the one holding this file)")
    opts, rest = ap.parse_known_args()
    if opts.repo:
        REPO = Path(opts.repo).resolve()
    unittest.main(argv=[sys.argv[0], *rest])
