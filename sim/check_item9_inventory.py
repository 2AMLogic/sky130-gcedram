#!/usr/bin/env python3
"""Completeness check for attest/item9.json (issue #371).

``klt signoff --attest 9`` grades only the paths listed in the inventory, so a
committed bench missing from the list is invisible to the gate. This check
compares the list against the tracked tree. Stdlib only; needs ``git``.

Candidate rule: a tracked file under ``sim/`` with no ``results`` path
component that is a ``*.spice`` deck or a ``request*.json`` klt sim request.
Fails (exit 1) naming every candidate absent from ``testbenches`` (unless
listed in ``EXCLUDE``) and every inventoried path that is no longer tracked.
Exit 2 if git cannot be queried; failure is never reported as success.

Usage::

    python3 -I sim/check_item9_inventory.py [--repo DIR]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

INVENTORY = "attest/item9.json"

# Candidates deliberately outside item 9. Empty at landing: every committed
# deck and request, including the frozen extracted-crbl decks, is citable by a
# recorded result. Adding an entry is a reviewed, one-line scope decision.
EXCLUDE: frozenset[str] = frozenset()


def is_candidate(path: str) -> bool:
    parts = path.split("/")
    if parts[0] != "sim" or "results" in parts[:-1]:
        return False
    name = parts[-1]
    return name.endswith(".spice") or (name.startswith("request") and name.endswith(".json"))


def tracked_files(repo: str) -> set[str]:
    try:
        proc = subprocess.run(
            ["git", "-C", repo, "ls-files", "-z"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
    except OSError as exc:
        raise RuntimeError(f"cannot run git: {exc}") from exc
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "backslashreplace").strip()
        raise RuntimeError(f"`git ls-files` failed (exit {proc.returncode}): {err}")
    return {p.decode("utf-8", "surrogateescape") for p in proc.stdout.split(b"\0") if p}


def check(tracked: set[str], inventory: set[str]) -> tuple[list[str], list[str]]:
    missing = sorted(p for p in tracked if is_candidate(p) and p not in inventory and p not in EXCLUDE)
    stale = sorted(p for p in inventory if p not in tracked)
    return missing, stale


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=".")
    args = ap.parse_args(argv)
    try:
        tracked = tracked_files(args.repo)
        with open(f"{args.repo}/{INVENTORY}", encoding="utf-8") as fh:
            inventory = set(json.load(fh)["testbenches"])
    except (RuntimeError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"item9 inventory check could not run: {exc}", file=sys.stderr)
        return 2
    missing, stale = check(tracked, inventory)
    for p in missing:
        print(f"not inventoried in {INVENTORY}: {p}")
    for p in stale:
        print(f"inventoried but not tracked: {p}")
    if missing or stale:
        print(f"FAIL: {len(missing)} uninventoried bench(es), {len(stale)} stale entr(ies). "
              f"Add/remove them in {INVENTORY}, or add a reviewed EXCLUDE entry.")
        return 1
    print(f"OK: every sim/ bench is inventoried in {INVENTORY}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
