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


class Variants(unittest.TestCase):
    """Issue #88: C_RBL / device-card variants; the default deck is untouched."""

    def test_committed_variant_files_not_stale(self):
        for v in G.variants():
            net, req = G.render(v)
            npath, rpath = G.variant_paths(v)
            self.assertEqual(net, npath.read_text(), f"run gen_sense_stage.py --variant {v}")
            self.assertEqual(req, rpath.read_text(), f"run gen_sense_stage.py --variant {v}")
            self.assertEqual(json.loads(req)["netlist"], npath.name)

    def test_extracted_c_rbl_is_the_cited_json_value_on_rbl_and_reference(self):
        d = json.loads(G.PARASITICS_SUMMARY.read_text())
        want_ff = d["comparison"]["c_rbl"]["extracted_4row_worst_total_ff"]
        self.assertAlmostEqual(want_ff, 0.859179, places=6)
        self.assertEqual(d["comparison"]["c_rbl"]["extracted_4row_worst_total_ff"],
                         max(c["total_ff"] for c in d["per_column"]["rbl"].values()))
        for v in ("crbl_ext4row", "crbl_ext4row_layoutcard"):
            net, _ = G.render(v)
            self.assertIn(f".param C_RBL   = {G._fmt(want_ff * 1e-15)}   $ EXTRACTED-4-ROW", net)
            self.assertIn("STUDY-ASSUMPTION", net.split(".param C_RBL")[1].splitlines()[0])
            crbl = [ln for ln in net.splitlines() if ln.startswith("crbl_")]
            cref = [ln for ln in net.splitlines() if ln.startswith("cref_")]
            self.assertEqual(len(crbl), len(G.instances()))
            self.assertEqual(len(cref), len(G.instances()))
            self.assertTrue(all(ln.split()[3] == "{C_RBL}" for ln in crbl + cref))
            self.assertEqual(net.count(".param C_RBL"), 1)
            self.assertNotIn("1e-14", net.split(".param C_RBL")[1].splitlines()[0])

    def test_variant_changes_only_declared_lines(self):
        base = G.NETLIST_PATH.read_text().splitlines()
        for v, spec in G.variants().items():
            net = G.render(v)[0].splitlines()
            body_b, body_v = base[2:], net[3:]   # header comment lines differ by design
            self.assertEqual(len(body_b), len(body_v))
            diff = [(a, b) for a, b in zip(body_b, body_v) if a != b]
            for a, b in diff:
                if a.startswith(".param C_RBL"):
                    continue
                self.assertEqual(spec["card"], "layout", (a, b))
                self.assertTrue(a.startswith(("XMWR_", "XMRD_")), a)
                self.assertIn("ad=0.1974 as=0.1974 pd=1.78 ps=1.78", b)
                self.assertIn("ad=0.1218 as=0.1218 pd=1.42 ps=1.42", a)
            n_cell = sum(1 for ln in base if ln.startswith(("XMWR_", "XMRD_")))
            self.assertEqual(len(diff), 1 + (n_cell if spec["card"] == "layout" else 0))

    def test_default_output_unchanged_without_variant(self):
        self.assertEqual(G.render(), G.render(None))
        self.assertIn(".param C_RBL   = 1e-14   $ ASSUMPTION (contract; not extracted)", G.render()[0])
        self.assertEqual(G.C_RBL_F, 10e-15)

    def test_variant_summaries_ran_the_committed_variant_decks(self):
        import hashlib
        seen = set()
        for s in RESULTS.glob("sense_summary_*.json"):
            d = json.loads(s.read_text())
            if "variant" not in d:
                continue
            v = d["variant"]["id"]
            seen.add(v)
            deck = G.variant_paths(v)[0]
            self.assertEqual(hashlib.sha256(deck.read_bytes()).hexdigest(), d["netlist_sha256"], v)
            self.assertAlmostEqual(d["assumptions"]["c_rbl_f"], G.variants()[v]["c_rbl_f"], delta=1e-24)
            self.assertFalse(d["claims"]["n_rows_ratified"])
        self.assertEqual(seen, set(G.variants()))

    def test_analyzer_maps_report_netlist_to_variant(self):
        self.assertIsNone(A.report_variant({"netlist": {"path": "sim/sense-stage/sense_stage.spice"}}))
        self.assertIsNone(A.report_variant({}))
        self.assertEqual(A.report_variant({"netlist": {"path": "sim/sense-stage/sense_stage_crbl_2f.spice"}}), "crbl_2f")
        with self.assertRaises(ValueError):
            A.report_variant({"netlist": {"path": "sim/sense-stage/sense_stage_bogus.spice"}})


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
