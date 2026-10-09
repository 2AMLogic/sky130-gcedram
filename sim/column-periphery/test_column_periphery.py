#!/usr/bin/env python3
"""Stdlib-only checks for sim/column-periphery/ (issue #114). No ngspice, PDK or klt.

Run: python3 -I sim/column-periphery/test_column_periphery.py
"""
from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analyze_column_periphery as A  # noqa: E402
import gen_column_periphery as G  # noqa: E402

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
            self.assertEqual(r["environment"]["remote"]["bucket"], "<redacted-bucket>")

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


if __name__ == "__main__":
    unittest.main()
