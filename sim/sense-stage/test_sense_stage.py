#!/usr/bin/env python3
"""Stdlib-only checks for sim/sense-stage/ (issue #60). No ngspice, PDK or klt.

Run: python3 -I sim/sense-stage/test_sense_stage.py
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
import analyze_sense_stage as A  # noqa: E402
import gen_sense_stage as G  # noqa: E402

RESULTS = HERE / "results"


class Generated(unittest.TestCase):
    def test_committed_files_not_stale(self):
        net, req = G.render()
        self.assertEqual(net, G.NETLIST_PATH.read_text(), "run gen_sense_stage.py")
        self.assertEqual(req, G.REQUEST_PATH.read_text(), "run gen_sense_stage.py")

    def test_scope_is_exactly_the_proposed_restricted_range(self):
        # spec/operating-range-decision-PROPOSED.md section 6/10: 27 C and 125 C, five global corners, 1.8 V
        r = json.loads(G.REQUEST_PATH.read_text())
        self.assertEqual(r["corners"]["process"], ["tt", "ss", "ff", "sf", "fs"])
        self.assertEqual(r["corners"]["temperature_c"], [27, 125])
        self.assertNotIn("supply_v", r["corners"])
        self.assertNotIn("exclude", r)
        self.assertEqual(G.VDD_V, 1.8)
        doc = (G.REPO / "spec" / "operating-range-decision-PROPOSED.md").read_text()
        self.assertIn("**Proposed interval: junction temperature 27 C to 125 C at `VDD` = 1.8 V.**", doc)
        self.assertNotIn("monte_carlo", r)

    def test_bitcell_cards_are_inlined_verbatim_from_design(self):
        (wm, wp), (rm, rp) = G.design_cell_cards()
        net = G.NETLIST_PATH.read_text()
        self.assertIn(f"XMWR_cell1_r100_0300_0 sn_cell1_r100_0300_0 0 0 0 {wm} {wp}", net)
        self.assertIn(f"{rm} {rp}", net)
        self.assertNotIn(".include", net.replace("* ", ""))

    def test_body_has_no_control_or_end(self):
        for line in G.NETLIST_PATH.read_text().splitlines():
            self.assertFalse(line.lower().startswith((".control", ".end")), line)

    def test_names_lowercase_and_unique(self):
        names = [i["name"] for i in G.instances()]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(n == n.lower() for n in names))
        r = json.loads(G.REQUEST_PATH.read_text())
        self.assertTrue(all(m["name"] == m["name"].lower() for m in r["measurements"]))


class Analysis(unittest.TestCase):
    def test_committed_summary_reproduces_from_committed_report(self):
        reports = sorted(RESULTS.glob("klt_report_*.json"))
        done = [p for p in reports if (RESULTS / f"sense_summary_{p.stem.split('klt_report_')[1]}.json").exists()]
        self.assertTrue(done, "no analysed klt report committed")
        for rep in done:
            rid = rep.stem.split("klt_report_")[1]
            with tempfile.TemporaryDirectory() as td:
                for f in (rep,):
                    (Path(td) / f.name).write_text(f.read_text())
                self.assertEqual(A.main([str(Path(td) / rep.name)]), 0)
                for name in (f"sense_summary_{rid}.json", f"sense_points_{rid}.csv"):
                    self.assertEqual((Path(td) / name).read_text(), (RESULTS / name).read_text(), name)

    def test_refuses_to_overwrite(self):
        rep = sorted(RESULTS.glob("sense_summary_*.json"))[0]
        rid = rep.stem.split("sense_summary_")[1]
        self.assertEqual(A.main([str(RESULTS / f"klt_report_{rid}.json")]), 2)

    def test_failed_report_produces_no_results(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "klt_report_X.json"
            p.write_text(json.dumps({"status": "error", "errored": 10, "corners": []}))
            self.assertEqual(A.main([str(p)]), 1)
            self.assertEqual(list(Path(td).glob("sense_*")), [])

    def test_summary_scope_and_claims(self):
        for s in RESULTS.glob("sense_summary_*.json"):
            d = json.loads(s.read_text())
            self.assertEqual({(c["corner"], c["temp_c"]) for c in d["corners"]},
                             {(p, t) for p in G.PROCESS_CORNERS for t in G.TEMPS_C})
            self.assertFalse(d["claims"]["spec_changed"])
            self.assertFalse(d["claims"]["mismatch_or_offset_yield_validated"])
            self.assertEqual(d["status"], "PROPOSED_OPERATING_RANGE_NOT_RATIFIED")
            rows = list(csv.DictReader((RESULTS / s.name.replace("summary", "points").replace(".json", ".csv")).open()))
            self.assertEqual(len(rows), len(d["corners"]) * len(G.instances()))


if __name__ == "__main__":
    unittest.main()
