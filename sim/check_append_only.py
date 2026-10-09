#!/usr/bin/env python3
"""Enforce append-only simulation evidence between two commits (issue #67).

Compares *committed blobs* at ``git merge-base BASE HEAD`` against HEAD --
never worktree text. Stdlib only; needs ``git`` on PATH and nothing else
(no PDK, ngspice or klt).

Protection inventory (derived from the merge-base tree, so deleting a file
or editing the inventory on the head side can never remove protection):

* every tracked file under ``sim/`` that has a directory component named
  ``results`` (e.g. ``sim/leakage/results/leakage_results.csv``);
* every path listed in ``sim/append_only_inventory.txt`` as it exists in the
  merge-base tree (result-summary files that live outside a ``results``
  directory; configuration/input JSON is *not* protected by extension).

Rules for each protected path:

* it must still exist at HEAD, at the same path, with the same object type
  and mode -- deletion, rename and move fail, even when a copy is added
  elsewhere (Git rename detection is never consulted);
* ``*.csv``: the merge-base content must be an exact byte prefix of the HEAD
  content (rows may only be appended at EOF). A nonempty CSV whose last byte
  is not LF may not grow at all -- appending would alter its last record, so
  a new evidence file is required instead. An empty CSV may gain content;
* any other file: byte-identical.

Files that are new at HEAD always pass. There is no bypass (no label,
marker, flag or environment variable).

Exit status: 0 = all protected evidence preserved, 1 = violation(s),
2 = the check could not be performed (missing commit/object, shallow
history, no merge base, git failure). Failure is never reported as success.

Usage::

    python3 -I sim/check_append_only.py --base <BASE_SHA> --head <HEAD_SHA>
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

INVENTORY_PATH = b"sim/append_only_inventory.txt"
RULE_REF = (
    "Simulation evidence is append-only (CLAUDE.md, sim/README.md "
    "'Append-only evidence guard'): keep the existing file unchanged and "
    "commit the correction as a NEW evidence file with a correction record "
    "that cites the original."
)


class CheckError(Exception):
    """The comparison could not be carried out; fail closed (exit 2)."""


def git(repo: str, *args: str, ok_codes: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(
            ["git", "-C", repo, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:  # git missing / not executable
        raise CheckError(f"cannot run git: {exc}") from exc
    if proc.returncode not in ok_codes:
        err = proc.stderr.decode("utf-8", "backslashreplace").strip()
        raise CheckError(f"`git {' '.join(args)}` failed (exit {proc.returncode}): {err}")
    return proc


def show(path: bytes) -> str:
    return path.decode("utf-8", "backslashreplace")


def resolve_commit(repo: str, rev: str, label: str) -> str:
    if not rev or rev.strip("0") == "":
        raise CheckError(f"{label} commit is empty or all-zero: {rev!r}")
    proc = git(repo, "rev-parse", "--verify", "--quiet", "--end-of-options",
               f"{rev}^{{commit}}", ok_codes=(0, 1))
    if proc.returncode != 0:
        raise CheckError(f"{label} commit {rev!r} is not available in this repository "
                         "(fetch it, with full history, before running the check)")
    return proc.stdout.decode("ascii").strip()


def merge_base(repo: str, base: str, head: str) -> str:
    shallow = git(repo, "rev-parse", "--is-shallow-repository").stdout.strip()
    if shallow != b"false":
        raise CheckError("repository is shallow; the merge base cannot be trusted "
                         "(check out with full history, e.g. fetch-depth: 0)")
    proc = git(repo, "merge-base", base, head, ok_codes=(0, 1))
    out = proc.stdout.decode("ascii").strip()
    if proc.returncode != 0 or not out:
        raise CheckError(f"no merge base between {base} and {head}")
    return out


def ls_tree(repo: str, commit: str) -> dict[bytes, tuple[bytes, bytes, bytes]]:
    """Map path -> (mode, type, oid) for every entry of the commit's tree."""
    out = git(repo, "ls-tree", "-r", "-z", "--full-tree", commit).stdout
    entries: dict[bytes, tuple[bytes, bytes, bytes]] = {}
    for rec in out.split(b"\0"):
        if not rec:
            continue
        meta, sep, path = rec.partition(b"\t")
        fields = meta.split(b" ")
        if not sep or len(fields) != 3 or not path:
            raise CheckError(f"unparseable ls-tree record: {rec!r}")
        entries[path] = (fields[0], fields[1], fields[2])
    return entries


def read_blob(repo: str, oid: bytes) -> bytes:
    return git(repo, "cat-file", "blob", oid.decode("ascii")).stdout


def in_results_dir(path: bytes) -> bool:
    parts = path.split(b"/")
    return len(parts) >= 3 and parts[0] == b"sim" and b"results" in parts[1:-1]


def inventory_paths(repo: str, tree: dict[bytes, tuple[bytes, bytes, bytes]]) -> list[bytes]:
    entry = tree.get(INVENTORY_PATH)
    if entry is None:
        return []
    if entry[1] != b"blob":
        raise CheckError(f"{show(INVENTORY_PATH)} is not a regular file in the merge base")
    paths = []
    for raw in read_blob(repo, entry[2]).splitlines():
        line = raw.strip()
        if line and not line.startswith(b"#"):
            paths.append(line)
    return paths


def protected_paths(repo: str, tree: dict[bytes, tuple[bytes, bytes, bytes]]) -> list[bytes]:
    prot = {p for p in tree if in_results_dir(p)}
    for p in inventory_paths(repo, tree):
        if p not in tree:
            raise CheckError(f"{show(INVENTORY_PATH)} lists {show(p)!r}, which is not a "
                             "file in the merge-base tree")
        prot.add(p)
    return sorted(prot)


def compare(repo: str, path: bytes, old: tuple[bytes, bytes, bytes],
            new: tuple[bytes, bytes, bytes] | None) -> str | None:
    """Return a violation message, or None if the path is preserved."""
    if new is None:
        return "deleted or moved (protected evidence must stay at its path)"
    if old[1] != new[1]:
        return f"object type changed ({show(old[1])} -> {show(new[1])})"
    if old[0] != new[0]:
        return f"file mode changed ({show(old[0])} -> {show(new[0])})"
    if old[2] == new[2]:
        return None
    if old[1] != b"blob":
        return "content changed"
    if not path.lower().endswith(b".csv"):
        return "modified (non-CSV evidence must be byte-identical)"
    old_bytes = read_blob(repo, old[2])
    new_bytes = read_blob(repo, new[2])
    if old_bytes == new_bytes:
        return None
    if not old_bytes:
        return None  # empty CSV gaining its first content
    if not old_bytes.endswith(b"\n"):
        return ("existing CSV lacks a final LF, so appending would alter its last "
                "record; leave it byte-identical and write the new rows to a new "
                "evidence file")
    if len(new_bytes) < len(old_bytes) and old_bytes.startswith(new_bytes):
        return f"truncated ({len(old_bytes)} -> {len(new_bytes)} bytes)"
    if not new_bytes.startswith(old_bytes):
        n = next((i for i, (a, b) in enumerate(zip(old_bytes, new_bytes)) if a != b),
                 min(len(old_bytes), len(new_bytes)))
        line = old_bytes[:n].count(b"\n") + 1
        return (f"existing bytes changed (first difference at byte {n}, line {line}); "
                "CSV evidence may only grow by appending at EOF")
    return None


def run(repo: str, base_rev: str, head_rev: str) -> int:
    base = resolve_commit(repo, base_rev, "base")
    head = resolve_commit(repo, head_rev, "head")
    mb = merge_base(repo, base, head)
    old_tree = ls_tree(repo, mb)
    new_tree = ls_tree(repo, head)
    prot = protected_paths(repo, old_tree)
    print(f"append-only check: merge-base {mb} -> head {head}; "
          f"{len(prot)} protected evidence path(s)")
    violations = []
    for path in prot:
        msg = compare(repo, path, old_tree[path], new_tree.get(path))
        if msg:
            violations.append((path, msg))
    added = sorted(p for p in new_tree if p not in old_tree and in_results_dir(p))
    for p in added:
        print(f"  new evidence file (allowed): {show(p)}")
    if not violations:
        print("PASS: all protected evidence preserved")
        return 0
    for path, msg in violations:
        print(f"FAIL {show(path)}: {msg}")
    print(f"\n{len(violations)} append-only violation(s). {RULE_REF}")
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", required=True, help="base commit (e.g. PR base SHA)")
    ap.add_argument("--head", required=True, help="head commit (e.g. PR head SHA)")
    ap.add_argument("--repo", default=os.getcwd(), help="repository path (default: cwd)")
    args = ap.parse_args(argv)
    try:
        return run(args.repo, args.base, args.head)
    except CheckError as exc:
        print(f"ERROR: append-only check could not run: {exc}", file=sys.stderr)
        print("ERROR: failing closed -- this is not a pass.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
