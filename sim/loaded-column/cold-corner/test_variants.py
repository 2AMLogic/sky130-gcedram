#!/usr/bin/env python3
"""Tests for the cold-corner variant study (issue #47). Run:
    python3 sim/loaded-column/cold-corner/test_variants.py
Synthetic cases always run (no ngspice needed); the committed-evidence cases
run when results/variant_results.csv exists."""

import contextlib
import csv
import io
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analyze_variants as X  # noqa: E402
import run_variants as RV  # noqa: E402
import variants as V  # noqa: E402

VID = "attr_crbl_5f"  # any declared cold_fresh variant works for synthetic data
PROV = {"repo_git_sha": "abc1234", "pdk_open_pdks_commit": "c6d7", "ngspice_version": "ngspice-46",
        "timestamp_utc": "2026-10-05T00:00:00+00:00"}


def synth(path, vid=VID, sep=0.3, drop=None, latency="1e-9", disturb="0.01", sha=None,
          no_prov=False, run_id="T1"):
    k = V.knobs(vid)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=RV.FIELDS)
        w.writeheader()
        for c, t, a in V.points(vid):
            for s in range(4):
                for p in range(16):
                    if drop == (c, t, a, s, p):
                        continue
                    bit = (p >> s) & 1
                    row = {f: "0.0" for f in RV.FIELDS}
                    row.update(PROV)
                    if no_prov:
                        row["repo_git_sha"] = ""
                    row.update(
                        variant_id=vid, variant_sha=sha or V.variant_sha(vid), run_id=run_id,
                        corner=c, temp_c=t, age_label=a, sel_row=s, stored_value=bit,
                        pattern_rows3210=format(p, "04b"), other_rows_pattern="000", status="ok",
                        reason="", latency_reason="", v_rbl_sense_v=(0.5 if bit else 0.5 + sep),
                        latency_s=(latency if bit else ""), t_sense_s_ASSUMPTION=k["t_sense_s"],
                        dv_sn_sel_read_disturb_v=disturb, dv_sn_unsel_worst_signed_v=disturb,
                        v_sn_sel_sense_v="1.0")
                    w.writerow(row)


def run(args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = X.main(args)
    return rc


class Synthetic(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.csv = Path(self.d.name) / "v.csv"
        self.base = ["--variant-csv", str(self.csv), "--repro-csv", str(Path(self.d.name) / "none.csv"),
                     "--no-phase2", "--no-summary"]

    def tearDown(self):
        self.d.cleanup()

    def test_pass(self):
        synth(self.csv)
        self.assertEqual(run(self.base), 0)
        self.assertEqual(run(self.base + ["--min-separation-v", "0.25", "--require-pass", VID]), 0)

    def test_impossible_threshold_fails(self):
        synth(self.csv)
        self.assertEqual(run(self.base + ["--min-separation-v", "50"]), 2)

    def test_missing_point_fails_coverage(self):
        synth(self.csv, drop=("fs", -40, "fresh", 2, 5))
        self.assertEqual(run(self.base), 1)

    def test_missing_provenance_fails(self):
        synth(self.csv, no_prov=True)
        self.assertEqual(run(self.base), 1)

    def test_knob_drift_detected(self):
        synth(self.csv, sha="0000000000000000")
        self.assertEqual(run(self.base), 1)

    def test_small_separation_fails_criteria(self):
        synth(self.csv, sep=0.05)
        self.assertEqual(run(self.base), 0)  # reported, not a harness error
        self.assertEqual(run(self.base + ["--require-pass", VID]), 2)

    def test_slow_latency_fails(self):
        synth(self.csv, latency="2e-8")  # 20 ns > 10 ns t_sense
        self.assertEqual(run(self.base + ["--require-pass", VID]), 2)

    def test_missing_latency_fails(self):
        synth(self.csv, latency="")
        self.assertEqual(run(self.base + ["--require-pass", VID]), 2)

    def test_read_disturb_fails(self):
        synth(self.csv, disturb="-0.2")
        self.assertEqual(run(self.base + ["--require-pass", VID]), 2)

    def test_negative_control_that_passes_is_an_error(self):
        synth(self.csv, vid="nc_write_disabled", sep=0.3)
        self.assertEqual(run(self.base), 1)

    def test_negative_control_that_fails_is_ok(self):
        synth(self.csv, vid="nc_write_disabled", sep=-1.0)
        self.assertEqual(run(self.base), 0)

    def test_reproduction_detects_perturbation(self):
        synth(self.csv)
        rows = X.read_csv(self.csv)
        ref = {tuple(r[x] for x in X.KEY): dict(r) for r in rows}
        self.assertTrue(X.reproduce(rows, ref)["ok"])
        k = next(key for key, r in ref.items() if r["stored_value"] == "1")  # v_rbl 0.5
        ref[k]["v_rbl_sense_v"] = "5.000001e-01"  # one unit in the last written digit
        self.assertTrue(X.reproduce(rows, ref)["ok"])
        ref[k]["v_rbl_sense_v"] = "5.000500e-01"  # 1e-4 relative: a real difference
        self.assertFalse(X.reproduce(rows, ref)["ok"])
        ref[k]["v_rbl_sense_v"] = ""
        self.assertFalse(X.reproduce(rows, ref)["ok"])


class Harness(unittest.TestCase):
    def test_baseline_knobs_are_phase2(self):
        k = V.knobs("baseline")
        self.assertEqual(k["c_rbl_f"], RV.R.C_RBL_F)
        self.assertEqual(k["t_sense_s"], RV.R.T_SENSE_S)
        P = RV.params(k)
        P2 = RV.R.parse_params(RV.R.TEMPLATE.read_text())
        for key in ("TWPULSE", "TWSTEP", "THOLD0", "TEDGE", "TW0", "TBL_LAG", "TPRE_GAP",
                    "TREAD_PULSE", "TTAIL", "VRBL", "VDD"):
            self.assertAlmostEqual(P[key], P2[key], places=15, msg=key)
        self.assertAlmostEqual(RV.read_time(P, "fresh"), RV.R.read_time(P2, "fresh"), places=15)
        self.assertAlmostEqual(RV.read_time(P, "refresh_bound"), RV.R.read_time(P2, "refresh_bound"), places=15)

    def test_device_card_resize(self):
        _, p = RV.R.parse_design_devices()["M_RD"]
        self.assertEqual(RV.device_card(p, V.NFET, 0.42), f"{V.NFET} {p}")
        c = RV.device_card(p, V.NFET, 0.84)
        self.assertIn("W=0.84 ", c)
        self.assertIn("ad=0.2436 ", c)
        self.assertIn("pd=2.26 ", c)

    def test_every_variant_changes_at_most_declared_knobs(self):
        for v in V.VARIANTS:
            k = V.knobs(v["id"])
            diff = {x for x in k if k[x] != V.BASELINE[x]}
            self.assertEqual(diff, {x for x in v["changes"] if v["changes"][x] != V.BASELINE[x]})
            if v["class"].startswith("attribution:") and v["class"] != "attribution:forced_level":
                self.assertEqual(len(diff), 1, v["id"])


@unittest.skipUnless(X.VARIANT_CSV.exists(), "no committed variant results")
class Committed(unittest.TestCase):
    def test_coverage_provenance_reproduction_negative_control(self):
        self.assertEqual(run(["--no-summary"]), 0)

    def test_impossible_threshold_fails(self):
        self.assertEqual(run(["--no-summary", "--min-separation-v", "50"]), 2)

    def test_every_declared_variant_has_evidence(self):
        present = set(X.latest_per_variant(X.read_csv(X.VARIANT_CSV)))
        self.assertEqual({v["id"] for v in V.VARIANTS} - present, set())

    def test_phase2_cold_failure_stays_visible(self):
        p2 = [r for r in X.read_csv(X.PHASE2_CSV) if r["run_id"] == X.PHASE2_RUN_ID]
        e = X.evaluate_variant(X.PHASE2_ID, p2)
        cold = {(p["corner"], p["temp_c"], p["age"]): p for p in e["points"]}
        for age in V.AGES:
            self.assertFalse(cold[("fs", -40, age)]["PASS"])
        self.assertFalse(e["all_points_pass"])

    def test_remedy_verdicts_and_failed_variants_preserved(self):
        by = X.latest_per_variant(X.read_csv(X.VARIANT_CSV))
        ev = {v: X.evaluate_variant(v, by[v]) for v in ("rem_vwl_2p0", "rem_rwl_m0p2", "rem_wr_lvt",
                                                      "attr_rd_w_1p68", "nc_write_disabled")}
        for v in ("rem_vwl_2p0", "rem_rwl_m0p2"):
            self.assertTrue(ev[v]["covers_full_grid_both_ages"], v)
            self.assertTrue(ev[v]["all_points_pass"], v)
        for v in ("rem_wr_lvt", "attr_rd_w_1p68", "nc_write_disabled"):
            self.assertFalse(ev[v]["all_points_pass"], v)

    def test_reproduction_is_bit_identical(self):
        p2 = {tuple(r[x] for x in X.KEY): r for r in X.read_csv(X.PHASE2_CSV) if r["run_id"] == X.PHASE2_RUN_ID}
        rr = X.read_csv(X.REPRO_CSV)
        rep = X.reproduce([r for r in rr if r["run_id"] == max(x["run_id"] for x in rr)], p2)
        self.assertEqual(rep["n_bit_identical"], 256)
        self.assertTrue(rep["ok"])
        base = X.latest_per_variant(X.read_csv(X.VARIANT_CSV))["baseline"]
        rep = X.reproduce(base, p2)
        self.assertEqual(rep["n_compared"], 256)
        self.assertTrue(rep["ok"], rep)  # equal to the last written digit


if __name__ == "__main__":
    unittest.main()
