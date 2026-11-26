#!/usr/bin/env python3
"""Tests for analyze_loaded_column.py (issue #45). Run:
    python3 sim/loaded-column/test_analysis.py
Synthetic cases always run; the committed-results cases run when
results/loaded_column_results.csv exists."""

import contextlib
import csv
import io
import itertools
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # `python -I` drops the script dir from sys.path
import analyze_loaded_column as A  # noqa: E402
sys_path = None


def synth(path, drop=None, sep=0.3):
    import run_loaded_column as R
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=R.FIELDS)
        w.writeheader()
        for s, p in itertools.product(range(4), range(16)):
            if drop == (s, p):
                continue
            bit = (p >> s) & 1
            row = {k: "x" for k in R.FIELDS}
            row.update(run_id="T", corner="tt", temp_c="27", age_label="fresh", sel_row=s,
                       stored_value=bit, pattern_rows3210=format(p, "04b"), status="ok",
                       reason="", v_rbl_sense_v=(0.1 if bit else 0.1 + sep), latency_s="1e-9",
                       latency_reason="", c_rbl_ff_ASSUMPTION="10", t_sense_s_ASSUMPTION="1e-8",
                       dv_latency_v_ASSUMPTION="0.1", c_sn_ff="0.6")
            for k in R.FIELDS:
                if k.startswith(("v_sn_", "i_into", "dv_sn", "dv_rbl")):
                    row[k] = "0.0"
            w.writerow(row)


def run(args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = A.main(args)
    return rc


SCOPE = ["--corners", "tt", "--temps-c", "27", "--ages", "fresh", "--no-summary"]


class Synthetic(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.csv = Path(self.d.name) / "r.csv"

    def tearDown(self):
        self.d.cleanup()

    def test_pass(self):
        synth(self.csv)
        self.assertEqual(run(["--results-csv", str(self.csv)] + SCOPE), 0)
        self.assertEqual(run(["--results-csv", str(self.csv), "--min-separation-v", "0.25"] + SCOPE), 0)

    def test_impossible_threshold_fails(self):
        synth(self.csv)
        self.assertEqual(run(["--results-csv", str(self.csv), "--min-separation-v", "50"] + SCOPE), 2)

    def test_missing_point_fails_coverage(self):
        synth(self.csv, drop=(2, 5))
        self.assertEqual(run(["--results-csv", str(self.csv)] + SCOPE), 1)

    def test_negative_separation_visible(self):
        synth(self.csv, sep=-0.2)
        self.assertEqual(run(["--results-csv", str(self.csv), "--min-separation-v", "0"] + SCOPE), 2)


class RunnerScratchCleanup(unittest.TestCase):
    def _batch_args(self, patterns=(0, 1)):
        prov = {
            "timestamp_utc": "2026-10-05T00:00:00+00:00",
            "repo_git_sha": "abc1234",
            "pdk_open_pdks_commit": "f6eeac7",
            "ngspice_version": "ngspice-47",
        }
        return (
            Path("/nonexistent/sky130.lib.spice"),
            "tt",
            27,
            "fresh",
            0,
            list(patterns),
            6.0e-16,
            "T_RUN",
            prov,
            0.5e-9,
        )

    def test_missing_case_output_returns_sim_failed_after_cleanup(self):
        import run_loaded_column as R

        seen_decks = []

        def stub_run(cmd, **_kwargs):
            deck = Path(cmd[2])
            seen_decks.append(deck.is_file())
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="missing wrdata output\n")

        with tempfile.TemporaryDirectory() as root:
            with (
                mock.patch.object(tempfile, "tempdir", root),
                mock.patch.object(R.subprocess, "run", side_effect=stub_run),
            ):
                rows = R.run_batch(self._batch_args(patterns=[0]))
            self.assertEqual(seen_decks, [True])
            self.assertEqual(list(Path(root).iterdir()), [])
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "sim_failed")
            self.assertIn("ngspice produced no output for this case", rows[0]["reason"])
            self.assertIn("missing wrdata output", rows[0]["reason"])

    def test_unhandled_base_exception_and_cleanup_oserror_handling(self):
        import run_loaded_column as R

        class _Abort(BaseException):
            pass

        with tempfile.TemporaryDirectory() as root:
            with (
                mock.patch.object(tempfile, "tempdir", root),
                mock.patch.object(R.subprocess, "run", side_effect=_Abort("stop")),
            ):
                with self.assertRaises(_Abort):
                    R.run_batch(self._batch_args(patterns=[0]))
            self.assertEqual(list(Path(root).iterdir()), [])

            real_rmdir = os.rmdir
            with (
                mock.patch.object(tempfile, "tempdir", root),
                mock.patch.object(
                    R.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess(["ngspice"], 1, stdout="", stderr="err"),
                ),
                mock.patch("os.rmdir", side_effect=OSError("simulated busy scratch dir")),
            ):
                rows = R.run_batch(self._batch_args(patterns=[0]))
            self.assertEqual(rows[0]["status"], "sim_failed")
            self.assertTrue(rows[0]["reason"])
            for leftover in Path(root).iterdir():
                for child in leftover.iterdir():
                    child.unlink()
                real_rmdir(leftover)


class SenseInstant(unittest.TestCase):
    """measure() takes the sense instant as an argument (a cold-corner variant
    passes its own t_sense); omitted, it is the module's T_SENSE_S."""

    SENSE_KEYS = {f"i_into_rbl_r{r}_sense_a" for r in range(4)} | {
        "i_desel_sum_sense_a", "v_rbl_sense_v", "dv_rbl_sense_v"}

    def measure(self, **kwargs):
        """R.measure() on a waveform whose every vector IS time (t + 4 sn + rbl + 4 rwl)."""
        import run_loaded_column as R
        t = [i * 1e-9 for i in range(200)]
        cols = [t] + [list(t) for _ in range(9)]
        P = R.parse_params(R.TEMPLATE.read_text())
        t_read = R.read_time(P, "fresh")
        return R, t_read, R.measure(cols, P, t_read, 2, **kwargs)

    def test_an_explicit_sense_instant_moves_only_the_sense_readings(self):
        R, t_read, default = self.measure()
        _, _, at_15ns = self.measure(t_sense_s=15e-9)
        self.assertEqual(set(at_15ns), set(default))
        for key in default:
            if key not in self.SENSE_KEYS:
                self.assertEqual(at_15ns[key], default[key], key)
        self.assertAlmostEqual(float(default["v_rbl_sense_v"]), t_read + R.T_SENSE_S, places=12)
        self.assertAlmostEqual(float(at_15ns["v_rbl_sense_v"]), t_read + 15e-9, places=12)
        self.assertAlmostEqual(float(default["i_into_rbl_r1_sense_a"]), -(t_read + R.T_SENSE_S), places=12)
        self.assertAlmostEqual(float(at_15ns["i_into_rbl_r1_sense_a"]), -(t_read + 15e-9), places=12)

    def test_the_default_sense_instant_is_the_module_value_at_call_time(self):
        R, t_read, _ = self.measure()
        with mock.patch.object(R, "T_SENSE_S", 3e-9):
            m = self.measure()[2]
        self.assertAlmostEqual(float(m["v_rbl_sense_v"]), t_read + 3e-9, places=12)


@unittest.skipUnless(A.RESULTS_CSV.exists(), "no committed campaign results")
class Committed(unittest.TestCase):
    def test_coverage_and_provenance(self):
        self.assertEqual(run(["--no-summary"]), 0)

    def test_impossible_threshold_fails(self):
        self.assertEqual(run(["--no-summary", "--min-separation-v", "50"]), 2)


if __name__ == "__main__":
    unittest.main()
