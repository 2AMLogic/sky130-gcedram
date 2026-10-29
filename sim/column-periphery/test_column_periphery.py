#!/usr/bin/env python3
"""Stdlib-only checks for sim/column-periphery/ (issue #114). No ngspice, PDK or klt.

Run: python3 -I sim/column-periphery/test_column_periphery.py
"""
from __future__ import annotations

import csv
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analyze_column_periphery as A  # noqa: E402
import analyze_isolation_study as AI  # noqa: E402
import gen_column_periphery as G  # noqa: E402
import gen_isolation_study as S  # noqa: E402

RESULTS = HERE / "results"
REPORTS = sorted(RESULTS.glob("klt_report_*.json"))


class Generated(unittest.TestCase):
    def test_committed_files_not_stale(self):
        net, req = G.render()
        self.assertEqual(net, G.NETLIST_PATH.read_text(), "run gen_column_periphery.py")
        self.assertEqual(req, G.REQUEST_PATH.read_text(), "run gen_column_periphery.py")

    def test_scope_is_exactly_the_proposed_restricted_range(self):
        r = json.loads(G.REQUEST_PATH.read_text())
        self.assertEqual(r["corners"]["process"], ["tt", "ss", "ff", "sf", "fs"])
        self.assertEqual(r["corners"]["temperature_c"], [27, 125])
        self.assertIn(125, r["corners"]["temperature_c"])
        self.assertNotIn("supply_v", r["corners"])
        self.assertNotIn("monte_carlo", r)
        self.assertEqual(r["backend"], "batch")

    def test_body_has_no_control_or_end(self):
        for line in G.NETLIST_PATH.read_text().splitlines():
            self.assertFalse(line.lower().startswith((".control", ".end")), line)

    def test_names_lowercase_and_unique(self):
        names = [i["name"] for i in G.instances()]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(n == n.lower() for n in names))
        r = json.loads(G.REQUEST_PATH.read_text())
        self.assertTrue(all(m["name"] == m["name"].lower() for m in r["measurements"]))

    def test_ideal_instances_have_ideal_sources_and_real_do_not(self):
        net = G.NETLIST_PATH.read_text()
        self.assertIn("spa_ideal_w1 prea rbl_ideal_w1 pca 0 swpre", net)
        self.assertIn("vwbl_ideal_w1 ", net)
        self.assertNotIn("spa_real_w1", net)
        self.assertNotIn("vwbl_real_w1", net)
        self.assertIn("XMPPRE_real_w1 ", net)


@unittest.skipUnless(REPORTS, "no committed klt report")
class Analysis(unittest.TestCase):
    def test_summary_reproduces_from_each_committed_report(self):
        for rep in REPORTS:
            run = rep.stem.removeprefix("klt_report_")
            with self.subTest(run=run):
                committed = json.loads((RESULTS / f"periphery_summary_{run}.json").read_text())
                fresh = A.summarize(A.load(rep))
                self.assertEqual(committed["corners"], fresh["corners"])
                self.assertEqual(committed["aggregate"], fresh["aggregate"])

    def test_csv_row_count(self):
        for rep in REPORTS:
            run = rep.stem.removeprefix("klt_report_")
            rows = list(csv.DictReader((RESULTS / f"periphery_points_{run}.csv").open()))
            self.assertEqual(len(rows), 10 * len(G.instances()))

    def test_report_is_fleet_run_with_redacted_bucket(self):
        for rep in REPORTS:
            r = json.loads(rep.read_text())
            self.assertEqual(r["corner_count"], 10)
            self.assertEqual(r["environment"]["remote"]["provider"], "aws-batch-fleet")
            # klt >= 0.8.0 no longer emits the bucket at all; older reports
            # carry it redacted. Either way no real bucket name may appear.
            self.assertIn(r["environment"]["remote"].get("bucket"), (None, "<redacted-bucket>"))

    def test_analyzer_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            rep = Path(d) / "klt_report_x.json"
            rep.write_text(REPORTS[0].read_text())
            self.assertEqual(A.main([str(rep)]), 0)
            with self.assertRaises(SystemExit):
                A.main([str(rep)])


class Compliance(unittest.TestCase):
    def inst(self, **kw):
        base = dict(settle_s=1e-9, vrel_v=0.9, dend_v=-1.8, tdec_s=1e-10)
        base.update(kw)
        return base

    def test_pass_case(self):
        c = A.compliance(self.inst(), self.inst(dend_v=1.8))
        self.assertTrue(c["compliant"])

    def test_each_gate_can_fail(self):
        ok0 = self.inst(dend_v=1.8)
        self.assertFalse(A.compliance(self.inst(settle_s=3e-9), ok0)["settle_within_budget"])
        self.assertFalse(A.compliance(self.inst(vrel_v=0.85), ok0)["release_level_within_tol"])
        self.assertFalse(A.compliance(self.inst(dend_v=-0.5), ok0)["correct_decision"])
        self.assertFalse(A.compliance(self.inst(dend_v=1.8), ok0)["correct_decision"])  # wrong polarity
        self.assertFalse(A.compliance(self.inst(tdec_s=6e-9), ok0)["decision_within_window"])
        self.assertFalse(A.compliance(self.inst(settle_s=None), ok0)["compliant"])


ISO_REPORTS = sorted(RESULTS.glob("isolation_klt_report_*.json"))
ISO_MC_REPORTS = sorted(RESULTS.glob("isolation_mc_klt_report_*.json*"))


class IsolationGenerated(unittest.TestCase):
    """Issue #117: the isolation / write-driver study decks and requests."""

    def test_committed_files_not_stale(self):
        for path, text in S.render().items():
            self.assertEqual(text, path.read_text(), f"run gen_isolation_study.py ({path.name})")

    def test_the_114_files_are_untouched_by_the_study_generator(self):
        net, req = G.render()
        self.assertEqual(net, G.NETLIST_PATH.read_text())
        self.assertEqual(req, G.REQUEST_PATH.read_text())

    def test_study_scope_is_the_proposed_restricted_range(self):
        r = json.loads(S.STUDY_REQUEST.read_text())
        self.assertEqual(r["corners"]["process"], ["tt", "ss", "ff", "sf", "fs"])
        self.assertEqual(r["corners"]["temperature_c"], [27, 125])
        self.assertEqual(r["backend"], "batch")
        self.assertNotIn("monte_carlo", r)

    def test_mc_scope_is_the_sense_mismatch_corner_set(self):
        r = json.loads(S.MC_REQUEST.read_text())
        self.assertEqual(r["backend"], "batch")
        self.assertEqual(r["monte_carlo"]["vary"], "mismatch")
        self.assertEqual(r["corners"]["process"], ["tt_mm", "fs_mm", "ss_mm", "sf_mm"])
        kept = {(p, t) for p in r["corners"]["process"] for t in r["corners"]["temperature_c"]} - \
               {(e["process"], e["temperature_c"]) for e in r["exclude"]}
        self.assertEqual(kept, {("tt_mm", 27), ("fs_mm", 27), ("ss_mm", 125), ("sf_mm", 125)})
        mm = json.loads((HERE.parent / "sense-mismatch" / "request.json").read_text())
        self.assertEqual(sorted(kept), sorted(
            {(p, t) for p in mm["corners"]["process"] for t in mm["corners"]["temperature_c"]} -
            {(e["process"], e["temperature_c"]) for e in mm["exclude"]}))
        self.assertGreaterEqual(r["monte_carlo"]["n"] * S.MC_REPLICAS, 160)

    def test_mc_compares_ideal_baseline_and_final(self):
        kinds = {S.mc_points()[i]["tag"] for i in range(len(S.mc_points()))}
        self.assertEqual(kinds, {"ideal", "i00", "f00"})
        self.assertEqual(S.CHOSEN, "f00")

    def test_names_lowercase_unique_and_requests_cover_every_instance(self):
        for pts, path in ((S.study_points(), S.STUDY_REQUEST), (S.mc_points(), S.MC_REQUEST)):
            names = [p["name"] for p in pts]
            self.assertEqual(len(names), len(set(names)))
            self.assertTrue(all(n == n.lower() for n in names))
            r = json.loads(path.read_text())
            mnames = [m["name"] for m in r["measurements"]]
            self.assertEqual(len(mnames), len(set(mnames)))
            self.assertTrue(all(n == n.lower() for n in mnames))
            for p in pts:
                if p["kind"] == "cprobe":
                    self.assertIn(f"vcp1_{p['name']}", mnames)
                else:
                    self.assertIn(f"din_{p['name']}", mnames)

    def test_variant_tags_unique(self):
        tags = [v["tag"] for v in AI.variants()] + [v["tag"] for v in S.DRV_VARIANTS]
        self.assertEqual(len(tags), len(set(tags)))

    def test_baseline_is_the_114_design_and_final_removes_the_pfet_isolation(self):
        base = S.baseline_cards()
        self.assertEqual(sorted(base), sorted(["MPPRE", "MPU1", "MPU2", "MND2", "MND1", "MNI", "MNS", "MPS", "MNSR", "MPSR"]))
        net = S.STUDY_NETLIST.read_text()
        self.assertIn("XMPS_i00_w1 ", net)
        self.assertNotIn("XMPS_f00_w1 ", net)
        self.assertIn("XMPPREF_f00_w1 ", net)
        self.assertNotIn("XMPPREF_i00_w1 ", net)

    def test_width_geometry_uses_xschem_precision(self):
        p = S.set_width("L=0.15 W=1 nf=1 ad=0.29 as=0.29 pd=2.58 ps=2.58 nrd=0.29 nrs=0.29 sa=0", 0.42)
        self.assertIn("nrd=0.69047619047619", p)
        self.assertIn("ad=0.1218", p)


@unittest.skipUnless(ISO_REPORTS, "no committed isolation-study report")
class IsolationAnalysis(unittest.TestCase):
    def test_summary_reproduces_from_each_committed_report(self):
        for rep in ISO_REPORTS:
            run = rep.name.removeprefix("isolation_klt_report_").removesuffix(".json")
            with self.subTest(run=run):
                committed = json.loads((RESULTS / f"isolation_summary_{run}.json").read_text())
                fresh = json.loads(json.dumps(AI.summarize(AI.load(rep))))
                self.assertEqual(committed["corners"], fresh["corners"])
                self.assertEqual(committed["aggregate"], fresh["aggregate"])

    def test_csv_row_count_and_ten_corners(self):
        for rep in ISO_REPORTS:
            run = rep.name.removeprefix("isolation_klt_report_").removesuffix(".json")
            rows = list(csv.DictReader((RESULTS / f"isolation_points_{run}.csv").open()))
            n = len([p for p in S.study_points() if p["kind"] != "cprobe"])
            self.assertEqual(len(rows), 10 * n)
            r = json.loads(rep.read_text())
            self.assertEqual(r["corner_count"], 10)
            self.assertEqual(r["environment"]["remote"]["provider"], "aws-batch-fleet")
            # klt >= 0.8.0 no longer emits the bucket at all; older reports
            # carry it redacted. Either way no real bucket name may appear.
            self.assertIn(r["environment"]["remote"].get("bucket"), (None, "<redacted-bucket>"))

    def test_analyzer_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            rep = Path(d) / "isolation_klt_report_x.json"
            rep.write_text(ISO_REPORTS[0].read_text())
            self.assertEqual(AI.main([str(rep)]), 0)
            with self.assertRaises(SystemExit):
                AI.main([str(rep)])


@unittest.skipUnless(ISO_MC_REPORTS, "no committed isolation Monte Carlo report")
class IsolationMonteCarlo(unittest.TestCase):
    def test_summary_reproduces_and_samples_all_pass(self):
        for rep in ISO_MC_REPORTS:
            run = rep.name.split("klt_report_")[1].split(".json")[0]
            with self.subTest(run=run):
                committed = json.loads((RESULTS / f"isolation_mc_summary_{run}.json").read_text())
                _, rows = AI.load_mc(rep)
                fresh = AI.summarize_mc(rows)
                self.assertEqual(committed["corners"], fresh["corners"])
                self.assertEqual(committed["n_failed_samples"], fresh["n_failed_samples"])
                self.assertEqual(len(rows), 4 * S.MC_N)
                self.assertEqual(set(c for c, _, _, _, _ in rows), {"tt_mm", "fs_mm", "ss_mm", "sf_mm"})


class IsolationStatistics(unittest.TestCase):
    def test_sd_interval_brackets_the_estimate_and_shrinks_with_n(self):
        lo, hi = AI.sd_ci(10.0, 160)
        self.assertLess(lo, 10.0)
        self.assertGreater(hi, 10.0)
        lo2, hi2 = AI.sd_ci(10.0, 1600)
        self.assertLess(hi2 - lo2, hi - lo)
        # known value: chi2_0.975(159) ~ 195.7, chi2_0.025(159) ~ 126.2 -> [8.99, 11.2]
        self.assertAlmostEqual(lo, 8.99, delta=0.05)
        self.assertAlmostEqual(hi, 11.2, delta=0.1)

    def test_mean_sd(self):
        mu, sd = AI.mean_sd([1.0, 2.0, 3.0, 4.0])
        self.assertAlmostEqual(mu, 2.5)
        self.assertAlmostEqual(sd, math.sqrt(5 / 3))

    def test_capacitance_probe_formula(self):
        # 0.1 uA for 10 ns on 5 fF drops 0.2 V
        m = {"vcp1_cp_i00": 0.9, "vcp2_cp_i00": 0.7}
        self.assertAlmostEqual(AI.periphery_cap_f(m, "i00"), 5e-15, delta=1e-18)


if __name__ == "__main__":
    unittest.main()
