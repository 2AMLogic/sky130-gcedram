#!/usr/bin/env python3
"""Run the evidence-check suites and standalone checks (issue #277).

Single runner shared by the ``evidence-checks`` CI job and ``npm test``.
From the repository root it discovers every Git-tracked file whose basename
matches ``test_*.py``, excluding the top-level ``.loom/``, ``.claude/`` and
``.agents/`` trees, and runs each suite exactly once in its own
``python3 -I`` process. It then runs the three standalone checks: the
cold-corner evidence-index consistency check (offline, no ``--online``),
the item-9 inventory completeness check, and the artifact manifest checker.

A failed suite or checker does not stop the remaining checks: every command
is printed before it runs, every failure is named again at the end, and the
exit code is nonzero when discovery fails, zero suites are found, or any
check fails. A clean run exits zero. stdlib plus ``git`` only, like the
checks it runs: no ngspice, no klt, no network.

Usage: python3 -I scripts/run_evidence_checks.py
"""
from __future__ import annotations

import fnmatch
import os
import subprocess
import sys

EXCLUDED_TOP_LEVEL = (".loom", ".claude", ".agents")
SUITE_PATTERN = "test_*.py"
STANDALONE_CHECKS = [
    ["sim/loaded-column/cold-corner/check_evidence_index.py"],
    ["sim/check_item9_inventory.py"],
    ["scripts/check_artifact_manifests.py", "check"],
]


def repo_root() -> str | None:
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True
    )
    if proc.returncode != 0:
        sys.stderr.write(
            "discovery failed: git rev-parse --show-toplevel exited"
            f" {proc.returncode}: {proc.stderr.decode('utf-8', 'replace').strip()}\n"
        )
        return None
    out = proc.stdout.decode("utf-8", "surrogateescape")
    # Remove exactly the newline git appends; the path may end in whitespace.
    return out[:-1] if out.endswith("\n") else out


def discover_suites() -> list[str] | None:
    proc = subprocess.run(["git", "ls-files", "-z"], capture_output=True)
    if proc.returncode != 0:
        sys.stderr.write(
            "discovery failed: git ls-files exited"
            f" {proc.returncode}: {proc.stderr.decode('utf-8', 'replace').strip()}\n"
        )
        return None
    suites = []
    seen = set()
    for raw in proc.stdout.split(b"\0"):
        # ls-files emits one entry per index stage of a conflicted path.
        if not raw or raw in seen:
            continue
        seen.add(raw)
        path = raw.decode("utf-8", "surrogateescape")
        if path.split("/", 1)[0] in EXCLUDED_TOP_LEVEL:
            continue
        if fnmatch.fnmatchcase(path.rsplit("/", 1)[-1], SUITE_PATTERN):
            suites.append(path)
    return suites


def run_check(argv: list[str]) -> int:
    print(" ".join(argv), flush=True)
    return subprocess.run(["python3", "-I", "--", *argv]).returncode


def main() -> int:
    root = repo_root()
    if root is None:
        return 1
    os.chdir(root)
    suites = discover_suites()
    if suites is None:
        return 1
    if not suites:
        sys.stderr.write(
            "discovery failed: zero tracked test_*.py suites found"
            f" outside {list(EXCLUDED_TOP_LEVEL)}\n"
        )
        return 1
    commands = [[path] for path in suites] + STANDALONE_CHECKS
    failures = []
    for argv in commands:
        rc = run_check(argv)
        if rc != 0:
            failures.append((" ".join(argv), rc))
    if failures:
        print(
            f"\n{len(failures)} of {len(commands)} evidence checks failed:",
            flush=True,
        )
        for label, rc in failures:
            print(f"  {label} (exit {rc})")
        return 1
    print(f"\nAll {len(commands)} evidence checks passed ({len(suites)} suites).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
