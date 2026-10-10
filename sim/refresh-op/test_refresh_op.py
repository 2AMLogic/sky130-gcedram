#!/usr/bin/env python3
"""Stdlib-only checks for sim/refresh-op/ (issue #110). No ngspice, PDK or klt.

Run: python3 -I sim/refresh-op/test_refresh_op.py
"""
from __future__ import annotations

import csv
import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analyze_refresh_op as A  # noqa: E402
import gen_refresh_op as G  # noqa: E402

RESULTS = HERE / "results"


def reports() -> list[Path]:
    return sorted(RESULTS.glob("klt_report_*.json*"))


def rid(p: Path) -> str:
    n = p.name
    n = n[:-len(".json.gz")] if n.endswith(".gz") else n[:-len(".json")]
    return n.split("klt_report_")[1]


class Generated(unittest.TestCase):
    def test_committed_files_not_stale(self):
        net, req = G.render()
        self.assertEqual(net, G.NETLIST_PATH.read_text(), "run gen_refresh_op.py")
        self.assertEqual(req, G.REQUEST_PATH.read_text(), "run gen_refresh_op.py")

    def test_scope_is_exactly_the_proposed_restricted_range(self):
        r = json.loads(G.REQUEST_PATH.read_text())
        self.assertEqual(r["corners"]["process"], ["tt", "ss", "ff", "sf", "fs"])
        self.assertEqual(r["corners"]["temperature_c"], [27, 125])
        self.assertNotIn("supply_v", r["corners"])
        self.assertNotIn("monte_carlo", r)
        self.assertEqual(r["backend"], "batch")
        self.assertEqual(G.VDD_V, 1.8)

    def test_body_has_no_control_or_end_or_include(self):
        for line in G.NETLIST_PATH.read_text().splitlines():
            self.assertFalse(line.lower().startswith((".control", ".end", ".include", ".lib")), line)

    def test_names_lowercase_unique_and_measured(self):
        names = [i["name"] for i in G.instances()]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(n == n.lower() for n in names))
        r = json.loads(G.REQUEST_PATH.read_text())
        meas = {m["name"] for m in r["measurements"]}
        self.assertEqual(len(meas), 3 * len(names))
        self.assertTrue(all(m == m.lower() for m in meas))

    def test_phase_timing_and_total(self):
        p = {i["name"]: i for i in G.instances()}
        i = p["op1_0900_s10_w5"]
        self.assertAlmostEqual(i["t_en"], 14e-9)
        self.assertAlmostEqual(i["t_on"], 15e-9)
        self.assertAlmostEqual(i["t_off"], 20e-9)
        self.assertAlmostEqual(i["t_rel"], 22e-9)
        # 2 precharge + 2 gap + 10 sense + 1 latch + 5 pulse + 2 guard
        self.assertAlmostEqual(G.t_row_refresh_op_s(10e-9, 5e-9), 22e-9)
        self.assertGreater(G.t_stop_s(), max(x["t_meas"] for x in G.instances()))

    def test_negative_control_and_reference_present(self):
        self.assertIn(G.NEG_CONTROL_WB_S, G.wb_grid())
        self.assertNotIn(G.NEG_CONTROL_WB_S, G.WB_S)
        self.assertLess(G.NEG_CONTROL_WB_S, min(G.WB_S))
        self.assertEqual(sum(1 for i in G.instances() if i["kind"] == "ref"), 1)

    def test_prereads_below_restore_threshold(self):
        # a no-write must not pass: pre-read '1' levels stay well under 0.9 x any plausible reference level
        self.assertTrue(all(v <= 1.0 for v in G.SN1_PRE_V))

    def test_bitcell_cards_inlined_verbatim(self):
        (wm, wp), (rm, rp) = G.S.design_cell_cards()
        net = G.NETLIST_PATH.read_text()
        self.assertIn(f"{wm} {wp}", net)
        self.assertIn(f"{rm} {rp}", net)


class AnalyzerLogic(unittest.TestCase):
    REF = 1.3

    def test_negative_control_unrestored(self):
        # correct decision but SN barely moved off the pre-read level -> NOT restored
        self.assertFalse(A.restored("op1", -1.75, 0.95, self.REF, A.PRIMARY_FRAC))
        # pulse long enough -> restored
        self.assertTrue(A.restored("op1", -1.75, 1.28, self.REF, A.PRIMARY_FRAC))

    def test_wrong_or_missing_decision_is_unrestored(self):
        self.assertFalse(A.restored("op1", +1.75, 1.4, self.REF, 0.95))
        self.assertFalse(A.restored("op1", -0.3, 1.4, self.REF, 0.95))
        self.assertFalse(A.restored("op1", None, 1.4, self.REF, 0.95))
        self.assertFalse(A.restored("op0", -1.75, 0.0, self.REF, 0.95))

    def test_zero_restore(self):
        self.assertTrue(A.restored("op0", 1.75, 0.01, self.REF, 0.95))
        self.assertFalse(A.restored("op0", 1.75, 0.2, self.REF, 0.95))

    def test_fraction_monotone(self):
        v = 1.2
        flags = [A.restored("op1", -1.75, v, self.REF, f) for f in sorted(A.FRACS)]
        self.assertEqual(flags, sorted(flags, reverse=True))

    def test_min_pass_is_monotone_from_above(self):
        w = [1, 2, 3, 5, 10]
        self.assertEqual(A.min_pass_from_above(w, [False, True, False, True, True]), (3, True))
        self.assertEqual(A.min_pass_from_above(w, [True] * 5), (0, True))
        self.assertEqual(A.min_pass_from_above(w, [True, True, True, True, False]), (None, False))

    def test_synthetic_corner_flags_negative_control(self):
        meas = {"snend_refw": 1.3}
        for i in G.instances():
            if i["kind"] == "ref":
                continue
            n = i["name"]
            if i["kind"] == "op1":
                short = i["wb"] < 1e-9
                meas[f"dec_{n}"] = -1.75
                meas[f"snend_{n}"] = i["sn"] + 0.05 if short else 1.25
            else:
                meas[f"dec_{n}"] = 1.75
                meas[f"snend_{n}"] = 0.0
            meas[f"snrd_{n}"] = i["sn"]
        corner = dict(process="tt", temperature_c=27, status="pass",
                      measurements=[dict(name=k, value=v) for k, v in meas.items()])
        _rows, res = A.summarize_corner(corner, {})
        self.assertTrue(res["negative_control_ok"])
        self.assertFalse(any(res["negative_control_restored_flags"].values()))
        # every grid width with wb >= 1 ns passes; 0.5 ns is flagged -> min pass is the 1 ns point
        e = res["by_fraction"]["0.95"]["per_sense"][f"{G.SENSE_S[0] * 1e9:g}ns"]
        self.assertEqual(e["min_pass_pulse_ns"], 1.0)
        self.assertEqual(e["highest_failing_pulse_below_ns"], 0.5)


class Analysis(unittest.TestCase):
    def test_committed_summary_reproduces_from_committed_report(self):
        done = [p for p in reports() if (RESULTS / f"refresh_op_summary_{rid(p)}.json").exists()]
        if not reports():
            self.skipTest("no klt report committed (results pending)")
        self.assertTrue(done, "no analysed klt report committed")
        for rep in done:
            r = rid(rep)
            with tempfile.TemporaryDirectory() as td:
                tp = Path(td) / rep.name
                tp.write_bytes(rep.read_bytes())
                self.assertEqual(A.main([str(tp)]), 0)
                for name in (f"refresh_op_summary_{r}.json", f"refresh_op_points_{r}.csv"):
                    self.assertEqual((Path(td) / name).read_text(), (RESULTS / name).read_text(), name)

    def test_refuses_to_overwrite(self):
        sums = sorted(RESULTS.glob("refresh_op_summary_*.json"))
        if not sums:
            self.skipTest("results pending")
        r = sums[0].stem.split("refresh_op_summary_")[1]
        rep = next(p for p in reports() if rid(p) == r)
        self.assertEqual(A.main([str(rep)]), 2)

    def test_failed_report_produces_no_results(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "klt_report_X.json"
            p.write_text(json.dumps({"status": "error", "errored": 10, "corners": []}))
            self.assertEqual(A.main([str(p)]), 1)
            self.assertEqual(list(Path(td).glob("refresh_op_*")), [])

    def test_summary_scope_claims_and_negative_control(self):
        for s in RESULTS.glob("refresh_op_summary_*.json"):
            d = json.loads(s.read_text())
            self.assertEqual({(c["corner"], c["temp_c"]) for c in d["corners"]},
                             {(p, t) for p in G.PROCESS_CORNERS for t in G.TEMPS_C})
            self.assertFalse(d["claims"]["spec_changed"])
            self.assertFalse(d["claims"]["mismatch_or_offset_yield_validated"])
            self.assertEqual(d["status"], "PROPOSED_OPERATING_RANGE_NOT_RATIFIED")
            self.assertTrue(d["negative_control_ok_all_corners"])
            rows = list(csv.DictReader((RESULTS / s.name.replace("summary", "points").replace(".json", ".csv")).open()))
            self.assertEqual(len(rows), len(d["corners"]) * (len(G.instances()) - 1))


if __name__ == "__main__":
    unittest.main()
