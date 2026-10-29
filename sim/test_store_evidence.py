#!/usr/bin/env python3
"""Fail-closed and summary tests for sim/store_evidence.py (issue #218).

`klt` is replaced by a stub script, so no broker or network is touched.
Stdlib only. Run: python3 -I sim/test_store_evidence.py
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # `python -I` safe
import store_evidence as S  # noqa: E402

STUB = r'''#!/usr/bin/env python3
import hashlib, json, os, sys
a = sys.argv[1:]
if a[:2] != ["artifact", "put"]:
    sys.exit(2)
if "--help" in a:
    sys.exit(2 if os.environ.get("STUB_NO_PUT") else 0)
if os.environ.get("STUB_UNREACHABLE"):
    sys.exit(1)
m, name, f = a[a.index("--manifest") + 1], a[a.index("--name") + 1], a[-1]
body = open(f, "rb").read()
sha = hashlib.sha256(body).hexdigest()
try:
    d = json.load(open(m))
except OSError:
    d = {"schema_version": 1, "entries": []}
d["entries"].append({"sha256": sha, "size": len(body), "kind": "evidence", "name": name,
                     "uri": os.environ.get("STUB_URI_PREFIX", "artifact:") + "evidence/x/" + sha})
json.dump(d, open(m, "w"))
'''


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        root = Path(self.td.name)
        self.repo = root / "repo"
        (self.repo / "evidence-scratch" / "b-r1" / "sub").mkdir(parents=True)
        (self.repo / "evidence-scratch" / "b-r1" / "a.csv").write_bytes(b"x,y\n1,2\n")
        (self.repo / "evidence-scratch" / "b-r1" / "sub" / "b.log").write_bytes(b"log\n")
        self.klt = root / "klt"
        self.klt.write_text(STUB)
        self.klt.chmod(self.klt.stat().st_mode | stat.S_IXUSR)
        self.env = {"KLT_ARTIFACT_BROKER": "http://broker.invalid"}
        for k in ("KLT_ARTIFACT_BROKER", "STUB_NO_PUT", "STUB_UNREACHABLE", "STUB_URI_PREFIX"):
            self.addCleanup(self._restore, k, os.environ.get(k))
            os.environ.pop(k, None)
        os.environ.update(self.env)

    @staticmethod
    def _restore(k, v):
        os.environ.pop(k, None)
        if v is not None:
            os.environ[k] = v

    def run_store(self, run_id="r1"):
        return S.store("b", run_id, repo=self.repo, klt=str(self.klt))

    def assert_nothing_written(self):
        self.assertFalse((self.repo / S.MANIFEST_DIR).exists())

    def test_success_writes_manifest_and_summary(self):
        manifest, summary = self.run_store()
        data = json.loads(manifest.read_text())
        self.assertEqual([e["name"] for e in data["entries"]], ["b-r1/a.csv", "b-r1/sub/b.log"])
        self.assertTrue(all(e["uri"].startswith("artifact:") for e in data["entries"]))
        text = summary.read_text()
        sha = hashlib.sha256(b"x,y\n1,2\n").hexdigest()
        self.assertIn(f"| `b-r1/a.csv` | 8 | `{sha}` |", text)
        self.assertNotIn("broker.invalid", text + manifest.read_text())

    def test_broker_unset_fails_closed(self):
        del os.environ["KLT_ARTIFACT_BROKER"]
        with self.assertRaisesRegex(S.StoreError, "BROKER"):
            self.run_store()
        self.assert_nothing_written()

    def test_klt_without_artifact_put_fails_closed(self):
        os.environ["STUB_NO_PUT"] = "1"
        with self.assertRaisesRegex(S.StoreError, "unavailable"):
            self.run_store()
        self.assert_nothing_written()

    def test_klt_missing_fails_closed(self):
        self.klt.unlink()
        with self.assertRaisesRegex(S.StoreError, "not found"):
            self.run_store()
        self.assert_nothing_written()

    def test_unreachable_broker_fails_closed(self):
        os.environ["STUB_UNREACHABLE"] = "1"
        with self.assertRaisesRegex(S.StoreError, "failed"):
            self.run_store()
        self.assert_nothing_written()

    def test_non_artifact_uri_fails_closed(self):
        os.environ["STUB_URI_PREFIX"] = "s3://"
        with self.assertRaisesRegex(S.StoreError, "non-artifact"):
            self.run_store()
        self.assert_nothing_written()

    def test_existing_manifest_is_not_overwritten(self):
        self.run_store()
        with self.assertRaisesRegex(S.StoreError, "already exists"):
            self.run_store()

    def test_empty_scratch_and_bad_ids_rejected(self):
        with self.assertRaisesRegex(S.StoreError, "does not exist"):
            self.run_store("nope")
        with self.assertRaisesRegex(S.StoreError, "invalid"):
            S.store("../x", "r", repo=self.repo, klt=str(self.klt))


if __name__ == "__main__":
    unittest.main()
