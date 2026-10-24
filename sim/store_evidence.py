#!/usr/bin/env python3
"""Store a run's raw outputs in the fleet artifact store (issue #218).

Stage the run's raw files in a git-ignored scratch directory
(`evidence-scratch/<bench>-<run-id>/` by default), then:

    python3 -I sim/store_evidence.py --bench loaded-column --run-id 20261023a

This calls `klt artifact put` per file; the only output is a
manifest, `manifests/artifacts/<bench>-<run-id>.manifest.json`, plus a
Markdown summary (name, size, sha256 per object) next to it. The raw bytes
are never written into the repo.

Fails closed: if $KLT_ARTIFACT_BROKER is unset, `klt` lacks `artifact put`,
the scratch directory is empty, or any upload fails (broker unreachable), it
exits nonzero and writes no manifest and no summary. There is no fallback to
committing bytes. The broker URL is never written anywhere.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # `python -I` safe
import _evidence_common as C  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SCRATCH_ROOT = "evidence-scratch"
MANIFEST_DIR = "manifests/artifacts"
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class StoreError(Exception):
    pass


def preflight(klt: str) -> None:
    if not os.environ.get("KLT_ARTIFACT_BROKER"):
        raise StoreError("$KLT_ARTIFACT_BROKER is unset; nothing stored or written")
    if shutil.which(klt) is None:
        raise StoreError(f"`{klt}` not found on PATH; nothing stored or written")
    probe = subprocess.run(
        [klt, "artifact", "put", "--help"], capture_output=True, text=True
    )
    if probe.returncode != 0:
        raise StoreError(
            f"`{klt} artifact put` is unavailable (needs klayout-tools 7e3561f or later)"
        )


def put_all(klt: str, repo: Path, scratch: Path, prefix: str, tmp_manifest: Path):
    files = sorted(p for p in scratch.rglob("*") if p.is_file())
    if not files:
        raise StoreError(f"no files to store under {scratch}")
    for f in files:
        name = f"{prefix}/{f.relative_to(scratch).as_posix()}"
        res = subprocess.run(
            [klt, "artifact", "put", "--manifest", str(tmp_manifest),
             "--name", name, "--format", "json", str(f)],
            capture_output=True, text=True, cwd=repo,
        )
        if res.returncode != 0:
            raise StoreError(f"`klt artifact put` failed for {name} (rc={res.returncode}); "
                             "nothing written")


def render_summary(bench: str, run_id: str, entries: list[dict], sha: str) -> str:
    total = sum(e["size"] for e in entries)
    lines = [
        f"# Stored evidence: {bench} / {run_id}",
        "",
        f"Repo commit when stored: `{sha}`. {len(entries)} object(s), {total} bytes total.",
        "The bytes live in the fleet artifact store; see the manifest next to this file.",
        "",
        "| name | size (bytes) | sha256 |",
        "| --- | ---: | --- |",
    ]
    lines += [f"| `{e['name']}` | {e['size']} | `{e['sha256']}` |" for e in entries]
    return "\n".join(lines) + "\n"


def store(bench: str, run_id: str, scratch: Path | None = None, repo: Path = REPO,
          klt: str = "klt") -> tuple[Path, Path]:
    for label, v in (("bench", bench), ("run-id", run_id)):
        if not ID_RE.match(v):
            raise StoreError(f"invalid --{label} {v!r}")
    prefix = f"{bench}-{run_id}"
    scratch = scratch or repo / SCRATCH_ROOT / prefix
    manifest = repo / MANIFEST_DIR / f"{prefix}.manifest.json"
    summary = manifest.with_name(f"{prefix}.summary.md")
    if manifest.exists() or summary.exists():
        raise StoreError(f"{manifest.name} already exists; use a new run id")
    if not scratch.is_dir():
        raise StoreError(f"scratch directory {scratch} does not exist")
    preflight(klt)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "m.json"
        put_all(klt, repo, scratch, prefix, tmp)
        data = json.loads(tmp.read_text(encoding="utf-8"))
        entries = data["entries"]
        if not all(str(e.get("uri", "")).startswith("artifact:") for e in entries):
            raise StoreError("klt returned a non-artifact: URI; nothing written")
        manifest.parent.mkdir(parents=True, exist_ok=True)
        text = render_summary(bench, run_id, entries, C.repo_git_sha(repo))
        shutil.copyfile(tmp, manifest)
        summary.write_text(text, encoding="utf-8")
    return manifest, summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bench", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--scratch-dir", type=Path,
                    help=f"default: {SCRATCH_ROOT}/<bench>-<run-id>")
    args = ap.parse_args(argv)
    try:
        manifest, summary = store(args.bench, args.run_id, args.scratch_dir)
    except StoreError as exc:
        print(f"store_evidence: FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {manifest.relative_to(REPO)}\nwrote {summary.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
