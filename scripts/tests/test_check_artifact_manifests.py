#!/usr/bin/env python3
"""Fixtures for scripts/check_artifact_manifests.py (issue #218).

Each test builds a throwaway git repo and runs the checker as CI does.
Stdlib only; needs `git`. Run: python3 -I scripts/tests/test_check_artifact_manifests.py
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CHECKER = Path(__file__).resolve().parent.parent / "check_artifact_manifests.py"
GIT_ENV = {
    **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "fixture",
    "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
    "GIT_COMMITTER_NAME": "fixture",
    "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
}
BODY = b"stored object bytes\n"
SHA = hashlib.sha256(BODY).hexdigest()


def entry(name="b-r/out.csv", uri=None, sha=SHA, size=len(BODY)):
    return {"name": name, "sha256": sha, "size": size, "kind": "evidence",
            "uri": uri or f"artifact:evidence/x/{sha[:2]}/{sha}"}


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.repo = Path(self.td.name)
        self.git("init", "-q")

    def git(self, *a):
        subprocess.run(["git", "-C", str(self.repo), *a], check=True, env=GIT_ENV,
                       capture_output=True)

    def write(self, rel, data):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode())

    def commit_manifest(self, entries, extra=None, schema=1):
        doc = {"schema_version": schema, "entries": entries, **(extra or {})}
        self.write("manifests/artifacts/b-r.manifest.json", json.dumps(doc))
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "m")

    def run_check(self):
        r = subprocess.run([sys.executable, "-I", str(CHECKER), "check", "--repo", str(self.repo)],
                           capture_output=True, text=True, env=GIT_ENV)
        return r.returncode, r.stdout

    def test_valid_manifest_passes(self):
        self.commit_manifest([entry()])
        rc, out = self.run_check()
        self.assertEqual(rc, 0, out)

    def test_no_manifests_passes(self):
        self.write("README.md", "x")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "m")
        self.assertEqual(self.run_check()[0], 0)

    def test_non_artifact_uri_fails(self):
        self.commit_manifest([entry(uri="https://example.invalid/x")])
        rc, out = self.run_check()
        self.assertEqual(rc, 1)
        self.assertIn("artifact:", out)

    def test_bucket_string_fails(self):
        self.commit_manifest([entry()], extra={"note": "s3://bucket/key"})
        rc, out = self.run_check()
        self.assertEqual(rc, 1)
        self.assertIn("bucket", out)

    def test_duplicate_name_fails(self):
        self.commit_manifest([entry(), entry()])
        rc, out = self.run_check()
        self.assertEqual(rc, 1)
        self.assertIn("duplicate", out)

    def test_bad_sha_and_schema_fail(self):
        self.commit_manifest([entry(sha="abc")], schema=2)
        rc, out = self.run_check()
        self.assertEqual(rc, 1)
        self.assertIn("schema_version", out)
        self.assertIn("sha256", out)

    def test_tracked_path_name_fails(self):
        self.write("sim/x/out.csv", b"different bytes\n")
        self.commit_manifest([entry(name="sim/x/out.csv")])
        rc, out = self.run_check()
        self.assertEqual(rc, 1)
        self.assertIn("tracked path", out)

    def test_committed_bytes_under_other_name_fail(self):
        self.write("sim/x/renamed.csv", BODY)
        self.commit_manifest([entry()])
        rc, out = self.run_check()
        self.assertEqual(rc, 1)
        self.assertIn("also committed", out)

    def test_same_size_different_bytes_passes(self):
        self.write("sim/x/other.csv", b"X" * len(BODY))
        self.commit_manifest([entry()])
        self.assertEqual(self.run_check()[0], 0)


if __name__ == "__main__":
    unittest.main()
