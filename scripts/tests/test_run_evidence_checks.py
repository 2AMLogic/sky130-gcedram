#!/usr/bin/env python3
"""Fixtures for scripts/run_evidence_checks.py (issue #415).

Each test builds a throwaway git repo seeded with tiny suite and standalone
stubs and runs the runner as CI does. Stdlib only; needs `git`.
Run: python3 -I scripts/tests/test_run_evidence_checks.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RUNNER = Path(__file__).resolve().parent.parent / "run_evidence_checks.py"
GIT_ENV = {
    **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "fixture",
    "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
    "GIT_COMMITTER_NAME": "fixture",
    "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
}


def stub_body(marker, rc=0):
    return (
        "import sys\n"
        "from pathlib import Path\n"
        f"Path({marker!r}).write_text(' '.join(sys.argv))\n"
        f"sys.exit({rc})\n"
    )


MANIFEST_STUB = (
    "import sys\n"
    "from pathlib import Path\n"
    "Path('manifest.ran').write_text(' '.join(sys.argv))\n"
    "sys.exit(0 if sys.argv[1:] == ['check'] else 7)\n"
)

STANDALONE_STUBS = {
    "sim/loaded-column/cold-corner/check_evidence_index.py": stub_body(
        "evidence_index.ran"
    ),
    "sim/check_item9_inventory.py": stub_body("item9.ran"),
    "scripts/check_artifact_manifests.py": MANIFEST_STUB,
}


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.repo = Path(self.td.name)

    def git(self, repo, *a, input=None):
        return subprocess.run(
            ["git", "-C", str(repo), *a], check=True, env=GIT_ENV,
            capture_output=True, input=input,
        )

    def write(self, repo, rel, data):
        p = Path(repo) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode())

    def seed_suite(self, repo, rel, rc=0):
        self.write(repo, rel, stub_body(Path(rel).stem + ".ran", rc))

    def seed_standalone(self, repo, overrides=None):
        for rel, body in STANDALONE_STUBS.items():
            self.write(repo, rel, (overrides or {}).get(rel, body))

    def run_runner(self, cwd, env=None):
        r = subprocess.run(
            [sys.executable, "-I", str(RUNNER)], cwd=str(cwd),
            env=env or GIT_ENV, capture_output=True, text=True,
        )
        return r.returncode, r.stdout, r.stderr

    def test_clean_repo_passes(self):
        self.git(self.repo, "init", "-q")
        self.seed_suite(self.repo, "test_nominal.py")
        self.seed_standalone(self.repo)
        self.git(self.repo, "add", "--", "test_nominal.py")
        rc, out, err = self.run_runner(self.repo)
        self.assertEqual(rc, 0, out + err)
        self.assertIn("All 4 evidence checks passed (1 suites).", out)
        self.assertTrue((self.repo / "test_nominal.ran").exists())

    def test_trailing_whitespace_checkout_is_not_trimmed(self):
        parent = self.repo / "checkouts"
        ws = parent / "repo "
        sib = parent / "repo"
        for repo in (ws, sib):
            repo.mkdir(parents=True)
            self.git(repo, "init", "-q")
        self.seed_suite(ws, "test_ws.py")
        self.seed_standalone(ws)
        self.git(ws, "add", "--", "test_ws.py")
        self.seed_suite(sib, "test_sib.py")
        self.git(sib, "add", "--", "test_sib.py")
        rc, out, err = self.run_runner(ws)
        self.assertEqual(rc, 0, out + err)
        self.assertTrue((ws / "test_ws.ran").exists())
        self.assertFalse((sib / "test_sib.ran").exists())

    def test_dash_prefixed_suite_path_runs(self):
        self.git(self.repo, "init", "-q")
        self.seed_suite(self.repo, "-variants/test_nominal.py")
        self.seed_standalone(self.repo)
        self.git(self.repo, "add", "--", "-variants/test_nominal.py")
        rc, out, err = self.run_runner(self.repo)
        self.assertEqual(rc, 0, out + err)
        self.assertTrue((self.repo / "test_nominal.ran").exists())

    def test_conflicted_index_stages_run_suite_once(self):
        self.git(self.repo, "init", "-q")
        rel = "test_conflicted.py"
        self.seed_suite(self.repo, rel)
        self.seed_standalone(self.repo)
        blob = subprocess.run(
            ["git", "-C", str(self.repo), "hash-object", "-w", "--stdin"],
            input=(self.repo / rel).read_bytes(), check=True, env=GIT_ENV,
            capture_output=True,
        ).stdout.decode().strip()
        info = "".join(f"100644 {blob} {stage}\t{rel}\n" for stage in (1, 2, 3))
        self.git(self.repo, "update-index", "--index-info", input=info.encode())
        rc, out, err = self.run_runner(self.repo)
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(out.count(f"{rel}\n"), 1)
        self.assertIn("(1 suites)", out)

    def test_excluded_trees_and_untracked_files_are_skipped(self):
        self.git(self.repo, "init", "-q")
        self.seed_suite(self.repo, "test_keep.py")
        for top in (".loom", ".claude", ".agents"):
            self.seed_suite(self.repo, f"{top}/test_excluded.py")
        self.seed_suite(self.repo, "test_untracked.py")
        self.seed_standalone(self.repo)
        self.git(
            self.repo, "add", "--", "test_keep.py", ".loom/test_excluded.py",
            ".claude/test_excluded.py", ".agents/test_excluded.py",
        )
        rc, out, err = self.run_runner(self.repo)
        self.assertEqual(rc, 0, out + err)
        self.assertIn("(1 suites)", out)
        self.assertTrue((self.repo / "test_keep.ran").exists())
        for skipped in (".loom/test_excluded.py", ".claude/test_excluded.py",
                        ".agents/test_excluded.py", "test_untracked.py"):
            self.assertNotIn(skipped, out)
        self.assertFalse((self.repo / "test_excluded.ran").exists())
        self.assertFalse((self.repo / "test_untracked.ran").exists())

    def test_suite_path_with_space_runs(self):
        self.git(self.repo, "init", "-q")
        self.seed_suite(self.repo, "dir with space/test_spaced.py")
        self.seed_standalone(self.repo)
        self.git(self.repo, "add", "--", "dir with space/test_spaced.py")
        rc, out, err = self.run_runner(self.repo)
        self.assertEqual(rc, 0, out + err)
        self.assertIn("(1 suites)", out)
        self.assertTrue((self.repo / "test_spaced.ran").exists())

    def test_outside_git_repo_fails_discovery(self):
        plain = self.repo / "plain"
        plain.mkdir()
        env = {**GIT_ENV, "GIT_CEILING_DIRECTORIES": str(self.repo)}
        rc, out, err = self.run_runner(plain, env=env)
        self.assertNotEqual(rc, 0)
        self.assertIn("discovery failed:", err)

    def test_zero_suites_fails_discovery(self):
        self.git(self.repo, "init", "-q")
        self.write(self.repo, "README.md", "x\n")
        self.seed_standalone(self.repo)
        self.git(self.repo, "add", "--", "README.md")
        rc, out, err = self.run_runner(self.repo)
        self.assertNotEqual(rc, 0)
        self.assertIn("discovery failed:", err)
        self.assertIn("zero tracked", err)

    def test_failing_checks_are_isolated_and_summarized(self):
        self.git(self.repo, "init", "-q")
        self.seed_suite(self.repo, "test_aaa_fail.py", rc=3)
        self.seed_suite(self.repo, "test_zzz_pass.py")
        self.seed_standalone(self.repo, overrides={
            "sim/check_item9_inventory.py": stub_body("item9.ran", rc=4)})
        self.git(self.repo, "add", "--", "test_aaa_fail.py", "test_zzz_pass.py")
        rc, out, err = self.run_runner(self.repo)
        self.assertEqual(rc, 1)
        for cmd in ("test_aaa_fail.py", "test_zzz_pass.py",
                    "sim/loaded-column/cold-corner/check_evidence_index.py",
                    "sim/check_item9_inventory.py",
                    "scripts/check_artifact_manifests.py check"):
            self.assertIn(cmd, out)
        for marker in ("test_zzz_pass.ran", "evidence_index.ran",
                       "item9.ran", "manifest.ran"):
            self.assertTrue((self.repo / marker).exists(), marker)
        self.assertIn("2 of 5 evidence checks failed:", out)
        self.assertIn("test_aaa_fail.py (exit 3)", out)
        self.assertIn("sim/check_item9_inventory.py (exit 4)", out)
        self.assertNotIn("test_zzz_pass.py (exit", out)
        self.assertNotIn("check_artifact_manifests.py (exit", out)
        self.assertEqual((self.repo / "manifest.ran").read_text(),
                         "scripts/check_artifact_manifests.py check")


if __name__ == "__main__":
    unittest.main()
