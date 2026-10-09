#!/usr/bin/env python3
"""Regression fixtures for sim/check_append_only.py (issue #67).

Each test builds a throwaway Git repository, commits a base and a head, and
runs the checker exactly as CI does (`python3 -I check_append_only.py --base
B --head H`, as a subprocess), asserting on the exit status and report.
Stdlib only; needs `git`. Run: python3 -I sim/test_append_only.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CHECKER = Path(__file__).resolve().parent / "check_append_only.py"

GIT_ENV = {
    **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "fixture",
    "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
    "GIT_COMMITTER_NAME": "fixture",
    "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
}

CSV = "sim/leakage/results/leakage_results.csv"
JSON = "sim/loaded-column/results/summary_x.json"


class Repo:
    def __init__(self, path: Path):
        self.path = path
        path.mkdir(parents=True)
        self.git("init", "-q", "-b", "main")

    def git(self, *args: str) -> str:
        out = subprocess.run(["git", "-C", str(self.path), *args], env=GIT_ENV,
                             check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return out.stdout.decode("utf-8", "replace").strip()

    def write(self, rel: str, data: bytes) -> None:
        p = self.path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def rm(self, rel: str) -> None:
        self.git("rm", "-q", "--", rel)

    def commit(self, msg: str = "c") -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "--no-verify", "-m", msg)
        return self.git("rev-parse", "HEAD")


def run_checker(repo_path: Path, base: str, head: str) -> subprocess.CompletedProcess:
    # Same invocation shape as the CI step: cwd = repository, explicit SHAs.
    return subprocess.run([sys.executable, "-I", str(CHECKER), "--base", base, "--head", head],
                          cwd=str(repo_path), env=GIT_ENV, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, encoding="utf-8",
                          errors="backslashreplace")


class AppendOnlyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="append-only-"))
        self.repo = Repo(self.tmp / "r")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def base_with(self, files: dict[str, bytes]) -> str:
        for rel, data in files.items():
            self.repo.write(rel, data)
        return self.repo.commit("base")

    def check(self, base: str, head: str, code: int, *needles: str) -> str:
        proc = run_checker(self.repo.path, base, head)
        out = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, code, out)
        for n in needles:
            self.assertIn(n, out)
        return out

    # --- passing cases -------------------------------------------------
    def test_unchanged(self) -> None:
        b = self.base_with({CSV: b"a,b\n1,2\n", JSON: b"{}\n"})
        self.repo.write("README.md", b"doc\n")
        self.check(b, self.repo.commit(), 0, "PASS")

    def test_new_files_pass(self) -> None:
        b = self.base_with({CSV: b"a\n"})
        self.repo.write("sim/new/results/new.csv", b"x\n")
        self.repo.write("sim/new/results/summary_new.json", b"{}")
        self.check(b, self.repo.commit(), 0, "new evidence file (allowed): sim/new/results/new.csv")

    def test_eof_append(self) -> None:
        b = self.base_with({CSV: b"a,b\n1,2\n"})
        self.repo.write(CSV, b"a,b\n1,2\n3,4\n")
        self.check(b, self.repo.commit(), 0)

    def test_empty_csv_gains_first_record(self) -> None:
        b = self.base_with({CSV: b""})
        self.repo.write(CSV, b"a,b\n")
        self.check(b, self.repo.commit(), 0)

    def test_crlf_preserved_append(self) -> None:
        b = self.base_with({CSV: b"a,b\r\n1,2\r\n"})
        self.repo.write(CSV, b"a,b\r\n1,2\r\n3,4\r\n")
        self.check(b, self.repo.commit(), 0)

    def test_crlf_normalised_fails(self) -> None:
        b = self.base_with({CSV: b"a,b\r\n1,2\r\n"})
        self.repo.write(CSV, b"a,b\n1,2\n3,4\n")
        self.check(b, self.repo.commit(), 1, "existing bytes changed")

    def test_missing_final_lf_identical_ok(self) -> None:
        b = self.base_with({CSV: b"a,b\n1,2"})
        self.repo.write("other.txt", b"x")
        self.check(b, self.repo.commit(), 0)

    def test_added_copy_with_original_preserved(self) -> None:
        b = self.base_with({CSV: b"a\n1\n"})
        self.repo.write("sim/leakage/results/copy.csv", b"a\n1\n")
        self.check(b, self.repo.commit(), 0)

    def test_non_results_files_unprotected(self) -> None:
        b = self.base_with({"sim/leakage/config.json": b"{}", "sim/leakage/run.py": b"x"})
        self.repo.write("sim/leakage/config.json", b'{"a":1}')
        self.repo.rm("sim/leakage/run.py")
        self.check(b, self.repo.commit(), 0)

    def test_results_outside_sim_unprotected(self) -> None:
        b = self.base_with({"layout/results/x.csv": b"a\n"})
        self.repo.write("layout/results/x.csv", b"b\n")
        self.check(b, self.repo.commit(), 0)

    # --- violations ----------------------------------------------------
    def test_middle_insertion(self) -> None:
        b = self.base_with({CSV: b"a,b\n1,2\n3,4\n"})
        self.repo.write(CSV, b"a,b\n1,2\n9,9\n3,4\n")
        out = self.check(b, self.repo.commit(), 1, CSV, "existing bytes changed", "line 3",
                         "append-only")
        self.assertIn("NEW evidence file", out)

    def test_rewrite(self) -> None:
        b = self.base_with({CSV: b"a,b\n1,2\n"})
        self.repo.write(CSV, b"a,b\n1,3\n")
        self.check(b, self.repo.commit(), 1, "existing bytes changed")

    def test_truncation(self) -> None:
        b = self.base_with({CSV: b"a,b\n1,2\n3,4\n"})
        self.repo.write(CSV, b"a,b\n1,2\n")
        self.check(b, self.repo.commit(), 1, "truncated")

    def test_truncation_to_empty(self) -> None:
        b = self.base_with({CSV: b"a,b\n"})
        self.repo.write(CSV, b"")
        self.check(b, self.repo.commit(), 1, "truncated")

    def test_missing_final_lf_append_fails(self) -> None:
        b = self.base_with({CSV: b"a,b\n1,2"})
        self.repo.write(CSV, b"a,b\n1,2\n3,4\n")
        self.check(b, self.repo.commit(), 1, "lacks a final LF", "new")

    def test_deletion(self) -> None:
        b = self.base_with({CSV: b"a\n"})
        self.repo.rm(CSV)
        self.check(b, self.repo.commit(), 1, CSV, "deleted or moved")

    def test_rename(self) -> None:
        b = self.base_with({CSV: b"a\n1\n"})
        self.repo.git("mv", CSV, "sim/leakage/results/renamed.csv")
        self.check(b, self.repo.commit(), 1, "deleted or moved")

    def test_delete_add_move_without_rename_detection(self) -> None:
        # Separate delete/add commits with different content: no rename
        # heuristic would pair them; the base path is still protected.
        b = self.base_with({CSV: b"a\n1\n"})
        self.repo.rm(CSV)
        self.repo.commit("delete")
        self.repo.write("sim/elsewhere/results/moved.csv", b"a\n1\n2\n")
        self.check(b, self.repo.commit("add"), 1, "deleted or moved")

    def test_summary_json_modification(self) -> None:
        b = self.base_with({JSON: b'{"t": 1}\n'})
        self.repo.write(JSON, b'{"t": 1}\n\n')
        self.check(b, self.repo.commit(), 1, "non-CSV evidence must be byte-identical")

    def test_non_csv_in_results_modification(self) -> None:
        b = self.base_with({"sim/x/results/log.txt": b"line\n"})
        self.repo.write("sim/x/results/log.txt", b"line\nmore\n")
        self.check(b, self.repo.commit(), 1, "byte-identical")

    def test_mode_change(self) -> None:
        b = self.base_with({CSV: b"a\n"})
        (self.repo.path / CSV).chmod(0o755)
        self.repo.git("update-index", "--chmod=+x", CSV)
        self.check(b, self.repo.commit(), 1, "mode changed")

    def test_unicode_and_space_paths(self) -> None:
        p = "sim/d é/results/résumé run.csv"
        b = self.base_with({p: b"a\n1\n"})
        self.repo.write(p, b"a\n2\n")
        self.check(b, self.repo.commit(), 1, "sim/d é/results/résumé run.csv")

    def test_inventory_path_protected(self) -> None:
        inv = "sim/append_only_inventory.txt"
        b = self.base_with({inv: b"# c\nsim/foo/summary.json\n", "sim/foo/summary.json": b"{}"})
        self.repo.write("sim/foo/summary.json", b'{"x":1}')
        self.check(b, self.repo.commit(), 1, "sim/foo/summary.json")

    def test_inventory_removal_does_not_unprotect(self) -> None:
        inv = "sim/append_only_inventory.txt"
        b = self.base_with({inv: b"sim/foo/summary.json\n", "sim/foo/summary.json": b"{}"})
        self.repo.write(inv, b"# emptied\n")
        self.repo.rm("sim/foo/summary.json")
        self.check(b, self.repo.commit(), 1, "sim/foo/summary.json", "deleted or moved")

    def test_inventory_lists_missing_path_fails_closed(self) -> None:
        b = self.base_with({"sim/append_only_inventory.txt": b"sim/nope.json\n"})
        self.check(b, b, 2, "not a file in the merge-base tree")

    def test_merge_base_used_not_base_tip(self) -> None:
        # Base branch appends after the fork; the PR head (forked earlier)
        # lacks those rows but must not be blamed for them.
        fork = self.base_with({CSV: b"a\n1\n"})
        self.repo.write(CSV, b"a\n1\n2\n")
        base_tip = self.repo.commit("main moves on")
        self.repo.git("checkout", "-q", "-b", "pr", fork)
        self.repo.write("doc.md", b"x")
        head = self.repo.commit("pr")
        self.check(base_tip, head, 0)
        # ...while a PR violation against the merge base is still caught.
        self.repo.write(CSV, b"a\n")
        self.check(base_tip, self.repo.commit("pr2"), 1, "truncated")

    # --- fail closed ---------------------------------------------------
    def test_missing_base_object(self) -> None:
        b = self.base_with({CSV: b"a\n"})
        self.check("0123456789abcdef0123456789abcdef01234567", b, 2, "not available",
                   "not a pass")

    def test_zero_sha(self) -> None:
        b = self.base_with({CSV: b"a\n"})
        self.check("0" * 40, b, 2, "all-zero")

    def test_no_merge_base(self) -> None:
        b = self.base_with({CSV: b"a\n"})
        self.repo.git("checkout", "-q", "--orphan", "other")
        self.repo.git("rm", "-rq", "--cached", ".")
        self.repo.write("x.txt", b"x")
        self.repo.git("add", "x.txt")
        h = self.repo.commit("orphan")
        self.check(b, h, 2, "no merge base")

    def test_shallow_clone(self) -> None:
        self.base_with({CSV: b"a\n"})
        self.repo.write(CSV, b"a\nb\n")
        self.repo.commit()
        self.repo.write(CSV, b"z\n")
        head = self.repo.commit()
        clone = self.tmp / "shallow"
        subprocess.run(["git", "clone", "-q", "--depth", "1", f"file://{self.repo.path}",
                        str(clone)], env=GIT_ENV, check=True)
        proc = run_checker(clone, head, head)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("shallow", proc.stderr)

    def test_blob_read_error(self) -> None:
        b = self.base_with({CSV: b"a\n1\n"})
        old_oid = self.repo.git("rev-parse", f"{b}:{CSV}")
        self.repo.write(CSV, b"a\n1\n2\n")
        h = self.repo.commit()
        obj = self.repo.path / ".git" / "objects" / old_oid[:2] / old_oid[2:]
        self.assertTrue(obj.exists())
        obj.chmod(0o644)
        obj.unlink()
        self.check(b, h, 2, "cat-file", "not a pass")

    def test_not_a_repository(self) -> None:
        empty = self.tmp / "empty"
        empty.mkdir()
        proc = run_checker(empty, "HEAD", "HEAD")
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
