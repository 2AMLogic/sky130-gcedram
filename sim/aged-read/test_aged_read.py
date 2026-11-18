#!/usr/bin/env python3
"""Stdlib-only checks for sim/aged-read/ (issue #94). No ngspice, PDK or klt.

Run: python3 -I sim/aged-read/test_aged_read.py
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
import analyze_aged_read as A  # noqa: E402
import gen_aged_read as G  # noqa: E402

RESULTS = HERE / "results"


def synthetic_report(fail_age_ns: int | None = None, control_resolves: bool = False) -> dict:
    """A klt-style report: every main point reads correctly except stored-'1' at/after fail_age_ns."""
    meas = []
    for p in G.instances():
        n, v = p["name"], p["value"]
        good = not p["weak"] and not (fail_age_ns is not None and v == 1 and p["age_ns"] >= fail_age_ns)
        if p["weak"] and control_resolves:
            good = True
        dend = (-1.8 if v == 1 else 1.8) if good else (1.8 if v == 1 else -1.8)
        for k, val in (("wr", 1.1 if v else 0.0), ("pre", 1.0 if v else 0.0), ("post", 0.95 if v else 0.0),
                       ("din", -0.5 if v else 0.5), ("dend", dend), ("tdec", 4e-11)):
            meas.append({"name": f"{k}_{n}", "value": val})
    corners = [{"process": pr, "temperature_c": t, "status": "pass", "measurements": meas}
               for pr in G.PROCESS_CORNERS for t in G.TEMPS_C]
    return {"status": "pass", "errored": 0, "corner_count": len(corners), "corners": corners,
            "environment": {"netlist_sha256": "x", "models_lib_sha256": "y", "engine_version": "47", "remote": {}}}


class TdecGuard(unittest.TestCase):
    def _row(self, tdec):
        corner = {"process": "tt", "temperature_c": 27}
        p = next(q for q in G.instances() if not q["weak"] and q["value"] == 1)
        n = p["name"]
        m = {f"dend_{n}": -1.8, f"tdec_{n}": tdec}
        return A.point_row(corner, p, m)

    def test_negative_tdec_does_not_resolve(self):
        r = self._row(-1e-12)
        self.assertTrue(r["correct"])
        self.assertFalse(r["resolves"])

    def test_tdec_window_edges(self):
        self.assertFalse(self._row(None)["resolves"])
        self.assertFalse(self._row(0.0)["resolves"])
        self.assertTrue(self._row(A.T_WINDOW_S)["resolves"])
        self.assertFalse(self._row(A.T_WINDOW_S * 1.001)["resolves"])


class Generated(unittest.TestCase):
    def test_committed_files_not_stale(self):
        net, req = G.render()
        self.assertEqual(net, G.NETLIST_PATH.read_text(), "run gen_aged_read.py")
        self.assertEqual(req, G.REQUEST_PATH.read_text(), "run gen_aged_read.py")

    def test_scope_is_exactly_the_proposed_restricted_range(self):
        r = json.loads(G.REQUEST_PATH.read_text())
        self.assertEqual(r["corners"]["process"], ["tt", "ss", "ff", "sf", "fs"])
        self.assertEqual(r["corners"]["temperature_c"], [27, 125])
        self.assertNotIn("monte_carlo", r)
        self.assertEqual(G.VDD_V, 1.8)

    def test_body_has_no_control_or_end_and_lowercase_names(self):
        for line in G.NETLIST_PATH.read_text().splitlines():
            self.assertFalse(line.lower().startswith((".control", ".end")), line)
        r = json.loads(G.REQUEST_PATH.read_text())
        self.assertTrue(all(m["name"] == m["name"].lower() for m in r["measurements"]))
        names = [p["name"] for p in G.instances()]
        self.assertEqual(len(names), len(set(names)))

    def test_coverage_both_values_every_row_every_age_every_pattern(self):
        main = [p for p in G.instances() if p["kind"] == "main"]
        self.assertEqual(len(main), len(G.AGES_NS) * G.N_ROWS * len(G.VALUES) * len(G.NEIGHBOUR_PATTERNS))
        self.assertEqual({p["row"] for p in main}, set(range(G.N_ROWS)))
        self.assertEqual({p["value"] for p in main}, {0, 1})
        # a mixed-value pattern exists, and a zero-hold age and ages on both sides of the bound
        self.assertTrue(any(set(p["data"].values()) == {0, 1} for p in main))
        self.assertEqual(min(G.AGES_NS), 5)
        self.assertTrue(any(a * 1e-9 < G.REFRESH_BOUND_S for a in G.AGES_NS))
        self.assertTrue(any(a * 1e-9 > G.REFRESH_BOUND_S for a in G.AGES_NS))
        self.assertIn(5030, G.AGES_NS)

    def test_selected_row_written_last_and_cells_start_opposite(self):
        net = G.NETLIST_PATH.read_text()
        for p in G.instances():
            self.assertEqual(p["order"][-1], p["row"])
            self.assertEqual(sorted(p["order"]), list(range(G.N_ROWS)))
        p = next(q for q in G.instances() if q["name"] == "m_a00005_r2_v1_sos")
        self.assertEqual(p["order"], [0, 1, 3, 2])
        self.assertEqual(p["slot_bits"], "1011")                  # rows 0,1,3 = s,o,s then selected row 2 = 1
        self.assertIn("v(sn_m_a00005_r2_v1_sos_2)=0", net)       # data 1 starts at 0
        self.assertIn("v(sn_m_a00005_r2_v1_sos_1)=1.8", net)     # opposite neighbour data 0 starts at VDD

    def test_ratified_bound_matches_spec(self):
        spec = (G.REPO / "spec" / "retention-refresh-budget.md").read_text()
        self.assertIn("5.03", spec)
        self.assertEqual(G.REFRESH_BOUND_S, 5.03e-6)

    def test_inputs_come_from_committed_extraction_and_corrected_latch(self):
        net = G.NETLIST_PATH.read_text()
        self.assertIn(f".param C_RBL   = {G.fmt_g6(G.S.extracted_c_rbl_ff() * 1e-15)}", net)
        self.assertIn(f".param C_SN    = {G.fmt_g6(G.array_c_sn_ff() * 1e-15)}", net)
        self.assertIn("ad=0.1974", net)
        self.assertIn("nrd=0.29", net)      # latch cards carry the schematic-derived nrd (issue #293)


class Analyzer(unittest.TestCase):
    def reduce(self, rep):
        pts = G.instances()
        rows, corners = [], []
        for c in rep["corners"]:
            r, s = A.summarize_corner(c, pts)
            rows += r
            corners.append(s)
        return rows, corners

    def test_clean_report_meets_bound_and_control_detected(self):
        rows, corners = self.reduce(synthetic_report())
        self.assertTrue(all(c["all_within_bound_resolve"] and c["negative_control_detected"] and c["zero_hold_all_resolve"]
                            for c in corners))
        self.assertTrue(all(abs(r["droop_v"] - 0.1) < 1e-9 for r in rows if r["kind"] == "main" and r["value"] == 1))

    def test_failure_is_kept_and_boundary_bracketed(self):
        rows, corners = self.reduce(synthetic_report(fail_age_ns=6500))
        c = corners[0]
        self.assertTrue(c["all_within_bound_resolve"])     # 6.5 us is beyond the 5.03 us bound
        self.assertGreater(c["failing_points_total"], 0)
        b = c["failure_boundary_by_case"]["v1_r0_sss"]
        self.assertEqual((b["last_resolving_age_ns"], b["first_failing_age_ns"]), (5030, 6500))
        self.assertIsNone(c["failure_boundary_by_case"]["v0_r0_sss"]["first_failing_age_ns"])
        self.assertTrue(any(not r["meets_refresh_bound"] for r in rows if r["age_ns"] == 6500))

    def test_failure_inside_bound_flagged(self):
        _, corners = self.reduce(synthetic_report(fail_age_ns=3000))
        self.assertFalse(corners[0]["all_within_bound_resolve"])
        self.assertGreater(corners[0]["failing_points_within_bound"], 0)

    def test_non_discriminating_negative_control_is_flagged(self):
        _, corners = self.reduce(synthetic_report(control_resolves=True))
        self.assertFalse(corners[0]["negative_control_detected"])

    def test_cli_writes_new_files_only_and_refuses_failed_report(self):
        with tempfile.TemporaryDirectory() as d:
            rep = Path(d) / "klt_report_T1.json"
            rep.write_text(json.dumps(synthetic_report()))
            self.assertEqual(A.main([str(rep)]), 0)
            self.assertEqual(A.main([str(rep)]), 2)           # refuses to overwrite
            bad = Path(d) / "klt_report_T2.json"
            r = synthetic_report()
            r["status"], r["errored"] = "fail", 1
            bad.write_text(json.dumps(r))
            self.assertEqual(A.main([str(bad)]), 1)
            self.assertFalse((Path(d) / "aged_points_T2.csv").exists())
            with (Path(d) / "aged_points_T1.csv").open() as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(len(rows), 10 * len(G.instances()))


class Committed(unittest.TestCase):
    def test_committed_summaries_reproduce_from_reports(self):
        reports = sorted(RESULTS.glob("klt_report_*.json"))
        for rep in reports:
            rid = rep.stem.split("klt_report_", 1)[1]
            if not (RESULTS / f"aged_summary_{rid}.json").exists():
                continue            # failed-attempt record
            with tempfile.TemporaryDirectory() as d:
                tmp = Path(d) / rep.name
                tmp.write_text(rep.read_text())
                self.assertEqual(A.main([str(tmp)]), 0)
                for stem in ("aged_points", "aged_summary"):
                    ext = "csv" if stem == "aged_points" else "json"
                    self.assertEqual((Path(d) / f"{stem}_{rid}.{ext}").read_text(),
                                     (RESULTS / f"{stem}_{rid}.{ext}").read_text(), f"{rep.name}: {stem} not reproducible")


if __name__ == "__main__":
    unittest.main()
