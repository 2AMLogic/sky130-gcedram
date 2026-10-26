#!/usr/bin/env python3
"""Validate manifests/artifacts/*.manifest.json (issue #218).

Evidence bytes for new sim/signoff runs live in the fleet artifact store; git
keeps only a manifest and a summary. This check is stdlib plus `git`, never
contacts the broker (`klt artifact verify` does that, on fleet workers), and
fails when a manifest:

  * is not valid JSON of the expected shape (schema_version 1, `entries` list
    of objects with string `name`/`uri`, 64-hex `sha256`, integer `size`);
  * has a `uri` that does not start with `artifact:`, or any string naming a
    bucket / cloud account (`s3://`, `arn:aws:`);
  * repeats an entry name;
  * names a tracked path, or a stored object's bytes (matched by size and
    sha256) are also committed anywhere in the tree.

Usage: python3 -I scripts/check_artifact_manifests.py check [--repo DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

MANIFEST_DIR = "manifests/artifacts"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_RE = re.compile(r"s3://|arn:aws:")


def _git(repo: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True
    ).stdout


def tracked_blobs(repo: Path) -> dict[str, tuple[int, str]]:
    """{path: (size, blob id)} for every file in the index."""
    out = _git(repo, "ls-files", "-z", "--stage")
    blobs = {}
    for rec in out.split(b"\0"):
        if not rec:
            continue
        meta, _, path = rec.partition(b"\t")
        blob = meta.split()[1].decode()
        size = int(_git(repo, "cat-file", "-s", blob))
        blobs[path.decode("utf-8", "surrogateescape")] = (size, blob)
    return blobs


def _walk_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from _walk_strings(k)
            yield from _walk_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_strings(v)


def check_manifest(path: Path, data, blobs, repo: Path) -> list[str]:
    errs: list[str] = []
    if not isinstance(data, dict):
        return ["top level is not a JSON object"]
    if data.get("schema_version") != 1:
        errs.append("schema_version must be 1")
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        return errs + ["`entries` must be a non-empty list"]
    for s in _walk_strings(data):
        if FORBIDDEN_RE.search(s):
            errs.append(f"names a bucket or cloud account: {s!r}")
    seen: set[str] = set()
    for i, e in enumerate(entries):
        tag = f"entries[{i}]"
        if not isinstance(e, dict):
            errs.append(f"{tag}: not an object")
            continue
        name, uri, sha, size = (e.get(k) for k in ("name", "uri", "sha256", "size"))
        if not isinstance(name, str) or not name:
            errs.append(f"{tag}: `name` must be a non-empty string")
            continue
        if name in seen:
            errs.append(f"{tag}: duplicate name {name!r}")
        seen.add(name)
        if not isinstance(uri, str) or not uri.startswith("artifact:"):
            errs.append(f"{tag} ({name}): `uri` must start with 'artifact:'")
        if not isinstance(sha, str) or not SHA_RE.match(sha):
            errs.append(f"{tag} ({name}): `sha256` must be 64 lowercase hex digits")
            continue
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            errs.append(f"{tag} ({name}): `size` must be a non-negative integer")
            continue
        if name in blobs:
            errs.append(f"{tag}: name {name!r} is a tracked path (bytes committed)")
        if size == 0:
            continue
        for tpath, (tsize, blob) in blobs.items():
            if tsize != size:
                continue
            body = _git(repo, "cat-file", "blob", blob)
            if hashlib.sha256(body).hexdigest() == sha:
                errs.append(
                    f"{tag} ({name}): stored object's bytes are also committed at {tpath!r}"
                )
    return errs


def run_check(repo: Path) -> int:
    tracked = tracked_blobs(repo)
    manifests = sorted(
        p
        for p in tracked
        if p.startswith(MANIFEST_DIR + "/") and p.endswith(".manifest.json")
    )
    # Also validate manifests present in the worktree but not yet staged.
    for p in sorted((repo / MANIFEST_DIR).glob("*.manifest.json")):
        rel = p.relative_to(repo).as_posix()
        if rel not in manifests:
            manifests.append(rel)
    bad = 0
    for rel in manifests:
        try:
            data = json.loads((repo / rel).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"FAIL {rel}: unreadable or invalid JSON: {exc}")
            bad += 1
            continue
        errs = check_manifest(repo / rel, data, tracked, repo)
        for msg in errs:
            print(f"FAIL {rel}: {msg}")
        bad += bool(errs)
    print(f"{len(manifests)} manifest(s) checked, {bad} failed")
    return 1 if bad else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="validate every manifest")
    c.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent)
    args = ap.parse_args(argv)
    return run_check(args.repo.resolve())


if __name__ == "__main__":
    sys.exit(main())
