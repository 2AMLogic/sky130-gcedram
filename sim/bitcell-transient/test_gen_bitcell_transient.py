#!/usr/bin/env python3
"""Tests for gen_bitcell_transient.py / reduce_bitcell_transient.py (issue #182).
Run: python3 -I sim/bitcell-transient/test_gen_bitcell_transient.py"""
import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gen_bitcell_transient as G  # noqa: E402
import reduce_bitcell_transient as RED  # noqa: E402
import run_bitcell_transient as R  # noqa: E402
import _evidence_common as EC  # noqa: E402  # after R: R puts sim/ on sys.path


class Generator(unittest.TestCase):
    def test_committed_files_are_current_and_byte_identical_on_rerun(self):
        first, second = G.render_all(), G.render_all()
        self.assertEqual(first, second)
        for name, text in first.items():
            self.assertEqual((HERE / name).read_text(), text, f"{name} is stale: re-run gen_bitcell_transient.py")

    def test_no_absolute_include_or_control_block(self):
        for d in (1, 0):
            deck = (HERE / f"bitcell_d{d}.spice").read_text()
            self.assertNotIn(".include", deck)
            self.assertNotIn(".control", deck)
            self.assertNotIn("/home/", deck)

    def test_design_devices_inlined_verbatim(self):
        deck = (HERE / "bitcell_d1.spice").read_text()
        for line in G.design_device_lines():
            self.assertIn(line, deck)

    def test_read_request_uses_fine_tmax_not_hold_tmax(self):
        req = G.build_read(1)
        self.assertTrue(req["analysis"]["args"].endswith("1.000000e-11"))
        hold = G.build_hold(1, 125, 1e-4, "tt")
        self.assertNotEqual(hold["analysis"]["args"].split()[-1], "1.000000e-11")

    def test_pvt_coverage(self):
        self.assertEqual(len(G.PROCESS_CORNERS) * len(G.TEMPS_C), 15)
        self.assertEqual(G.build_read(1)["corners"]["temperature_c"], [-40, 27, 125])

    def test_leakage_loader_ignores_other_pin(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "l.csv"
            with p.open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["pdk_open_pdks_commit", "corner", "temp_c", "ileak_a"])
                w.writerow(["c6d73a35f524070e85faff4a6a9eef49553ebc2b", "tt", "27", "9e-9"])
                w.writerow([G.PIN, "tt", "27", "2e-12"])
            self.assertEqual(G.load_leakage_current_pin(p), {("tt", 27): 2e-12})

    def test_hold_end_instant_inside_tstop(self):
        req = G.build_hold(1, 27, 5e-3, "tt")
        stop = float(req["analysis"]["args"].split()[1])
        end = [m for m in req["measurements"] if m["name"] == "v_sn_hold_end_v"][0]["spice"]
        self.assertLess(float(end.split("AT=")[1]), stop)


class DeltaVSingleSource(unittest.TestCase):
    def test_default_delta_v_is_the_canonical_constant(self):
        # issue #314: DEFAULT_DELTA_V must be the single canonical DELTA_V_V
        # (sim/_evidence_common.py), not a hand-synchronized numeric copy.
        # Direct identity, not a monkeypatch -- the runner binds DELTA_V_V at
        # import time and gen_bitcell_transient binds the hold-window default
        # argument at def time, so patching module attributes reaches neither.
        self.assertEqual(R.DEFAULT_DELTA_V, EC.DELTA_V_V)
        self.assertEqual(R.DEFAULT_DELTA_V.hex(), EC.DELTA_V_V.hex())
        self.assertEqual(G.hold_window_s.__defaults__[0], EC.DELTA_V_V)


class Reducer(unittest.TestCase):
    def test_ladder_crossing_cubic_exact_on_cubic(self):
        f = lambda v: 3e-3 - 2e-3 * v + 1e-3 * v * v - 5e-4 * v ** 3
        ladder = {mv / 1000: f(mv / 1000) for mv in G.LADDER_MV}
        self.assertAlmostEqual(RED.ladder_crossing(0.1362, ladder), f(0.1362), places=12)

    def test_ladder_crossing_outside_or_uncrossed_is_none(self):
        ladder = {mv / 1000: 1e-3 for mv in G.LADDER_MV}
        self.assertIsNone(RED.ladder_crossing(0.9, ladder))
        self.assertIsNone(RED.ladder_crossing(0.1, {0.05: None, 0.075: None, 0.1: None, 0.125: None}))


class ReducerStampGate(unittest.TestCase):
    """Issue #439: `pdk_open_pdks_commit` may carry the repo pin only when
    the comparison status is "match" AND the worker stamp text names the
    pin. A "match" against another revision (a submitter on a stale PDK
    matched against a worker on that same stale PDK) must fall back to the
    fleet stamp, never record the pin. The committed 2026-11-02 reports
    (a real "mismatch" run on the old revision) are the fixture base."""

    RESULTS = HERE / "results"
    OLD_PIN = "c6d73a35f524070e85faff4a6a9eef49553ebc2b"

    def _copy_reports(self, stamp_status, stamp_text):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for src in self.RESULTS.glob("klt_report_*.json"):
            rep = json.loads(src.read_text())
            worker = rep["environment"]["remote"]["worker_environment"]
            worker["pdk_stamp_comparison"]["status"] = stamp_status
            worker["pdk"]["stamp_text"] = stamp_text
            (root / src.name).write_text(json.dumps(rep))
        return root

    def _commits(self, root):
        rows, _ = RED.build_rows(root)
        return {r["pdk_open_pdks_commit"] for r in rows}

    def test_match_on_the_pin_stamps_the_repo_pin(self):
        root = self._copy_reports("match", f"open_pdks {G.PIN}")
        self.assertEqual(self._commits(root), {G.PIN})

    def test_match_against_another_revision_falls_back_to_the_fleet_stamp(self):
        root = self._copy_reports("match", f"open_pdks {self.OLD_PIN}")
        self.assertEqual(self._commits(root), {f"fleet-stamp:{self.OLD_PIN}"})


class ScratchCleanup(unittest.TestCase):
    def _call_run_tran(self):
        return R.run_tran(
            Path("/nonexistent/sky130.lib.spice"),
            "tt",
            27,
            6.0e-16,
            0.9,
            1.8,
            0.0,
            1.0e-6,
            1.0e-9,
            "tt_27_d1",
        )

    def test_render_error_propagates_and_leaves_scratch_root_empty(self):
        bad_tmpl = R.TEMPLATE_PATH.read_text() + "\n* @@UNRESOLVED_TEST_TOKEN@@\n"
        stub = mock.MagicMock(side_effect=AssertionError("subprocess must not run on render failure"))
        with tempfile.TemporaryDirectory() as root:
            with (
                mock.patch.object(tempfile, "tempdir", root),
                mock.patch.object(R, "_TEMPLATE_TEXT", bad_tmpl),
                mock.patch.object(R.subprocess, "run", stub),
            ):
                with self.assertRaisesRegex(RuntimeError, "unsubstituted template tokens remain"):
                    self._call_run_tran()
            stub.assert_not_called()
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_subprocess_run_cleans_scratch_and_keeps_best_effort_cleanup(self):
        good_tmpl = R.TEMPLATE_PATH.read_text()

        def write_wrdata(cmd, **_kwargs):
            deck_path = Path(cmd[2])
            self.assertTrue(deck_path.is_file())
            (deck_path.parent / "tran.dat").write_text(
                "0.0 0.0 0.0 0.0\n"
                "5.0e-7 0.9 5.0e-7 -1.0e-6\n"
                "1.0e-6 0.8 1.0e-6 -1.0e-6\n"
            )
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as root:
            with (
                mock.patch.object(tempfile, "tempdir", root),
                mock.patch.object(R, "_TEMPLATE_TEXT", good_tmpl),
                mock.patch.object(R.subprocess, "run", side_effect=write_wrdata),
            ):
                t, vsn, irbl = self._call_run_tran()
            self.assertEqual(len(t), 3)
            self.assertEqual(vsn[1], 0.9)
            self.assertEqual(irbl[1], -1.0e-6)
            self.assertEqual(list(Path(root).iterdir()), [])

            real_rmdir = os.rmdir
            with (
                mock.patch.object(tempfile, "tempdir", root),
                mock.patch.object(R, "_TEMPLATE_TEXT", good_tmpl),
                mock.patch.object(R.subprocess, "run", side_effect=write_wrdata),
                mock.patch("os.rmdir", side_effect=OSError("simulated busy scratch dir")),
            ):
                t2, _, _ = self._call_run_tran()
            self.assertEqual(len(t2), 3)
            for leftover in Path(root).iterdir():
                for child in leftover.iterdir():
                    child.unlink()
                real_rmdir(leftover)


if __name__ == "__main__":
    unittest.main()
