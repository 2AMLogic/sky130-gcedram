#!/usr/bin/env python3
"""Stdlib-only checks for the geometry-matched leakage study (issue #149). No ngspice, PDK or klt.

Run: python3 -I sim/leakage/test_geometry_leakage.py
"""
from __future__ import annotations

import copy
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analyze_geometry_leakage as A  # noqa: E402
import gen_geometry_leakage as G  # noqa: E402

RES = G.OUT / "results"
P = {"l_um": 0.15, "w_um": 0.42, "ad_um2": 0.1974, "as_um2": 0.1974, "pd_um": 1.78, "ps_um": 1.78}


def dev(name, g, s, d, params=None, cls="nfet"):
    return {"name": name, "class": cls, "nets": {"g": g, "s": s, "d": d, "b": "GND"},
            "params": copy.deepcopy(P if params is None else params)}


def committed_report():
    return json.loads(sorted(RES.glob("klt_report_*.json"))[-1].read_text())


def synth_report(mut=None):
    corners = []
    for p in G.PROCESS_CORNERS:
        for t in G.TEMPS_C:
            corners.append({"process": p, "temperature_c": t, "status": "pass", "measurements": [
                {"name": G.MEAS_EXT, "value": 2e-11, "unit": "A", "status": "pass"},
                {"name": G.MEAS_LEG, "value": 1e-11, "unit": "A", "status": "pass"}]})
    ident = committed_report()
    rep = {"status": "pass", "failed": 0, "errored": 0, "corners": corners,
           "environment": {"netlist_sha256": ident["environment"]["netlist_sha256"]},
           "provenance": copy.deepcopy(ident["provenance"])}
    if mut:
        mut(rep)
    return rep


def legacy_rows(extra=None):
    rows = []
    for i, (p, t) in enumerate((p, t) for p in G.PROCESS_CORNERS for t in G.TEMPS_C):
        rows.append({"timestamp_utc": "T0", "corner": p, "temp_c": str(t), "device": G.DEVICE, "w_um": "0.42",
                     "l_um": "0.15", "vgs_v": "0.0", "vds_v": "1.8", "vbs_v": "0.0", "ileak_a": "1.0e-11",
                     "ngspice_version": "x", "_line": i + 2, "_row_sha256": "h"})
    return rows + (extra or [])


class Geometry(unittest.TestCase):
    def test_selects_access_not_read(self):
        ex = {"devices": [dev("rd", "sn_0_0", "rwl_0", "rbl_0"), dev("wr", "wl_0", "bl_0", "sn_0_0"),
                          dev("wr2", "wl", "bl", "sn")]}
        self.assertEqual([d["name"] for d in G.select_access_devices(ex)], ["wr", "wr2"])

    def test_no_access_device(self):
        with self.assertRaisesRegex(G.GeometryError, "no access device"):
            G.select_access_devices({"devices": [dev("rd", "sn_0_0", "rwl_0", "rbl_0")]})

    def test_asymmetric_ad_as_preserved_and_rendered(self):
        p = dict(P, ad_um2=0.30, as_um2=0.10, pd_um=2.0, ps_um=1.0)
        g = G.geometry_from_devices([dev("a", "wl_0", "bl_0", "sn_0_0", p)])
        deck = G.render_deck(g)
        self.assertIn("ad=0.3 as=0.1 pd=2.0 ps=1.0", deck)

    def test_heterogeneous_rejected(self):
        with self.assertRaisesRegex(G.GeometryError, "heterogeneous"):
            G.geometry_from_devices([dev("a", "wl_0", "bl_0", "sn_0_0"),
                                     dev("b", "wl_1", "bl_0", "sn_1_0", dict(P, w_um=0.5))])

    def test_missing_and_invalid(self):
        for bad in ({k: v for k, v in P.items() if k != "ad_um2"}, dict(P, pd_um=float("nan")),
                    dict(P, ps_um=-1.0), dict(P, w_um=0.0), dict(P, l_um="0.15"), dict(P, as_um2=float("inf"))):
            with self.assertRaises(G.GeometryError, msg=str(bad)):
                G.geometry_from_devices([dev("a", "wl_0", "bl_0", "sn_0_0", bad)])
        with self.assertRaises(G.GeometryError):
            G.geometry_from_devices([{"name": "x", "nets": {}}])

    def test_committed_extraction_geometry(self):
        info = G.load_geometry()
        self.assertEqual(len(info["device_names"]), 16)
        self.assertEqual(info["geometry"], P)
        self.assertTrue(info["input_sha256"].startswith("sha256:"))

    def test_rendered_bias_and_units(self):
        deck = G.render_deck(G.load_geometry()["geometry"])
        self.assertIn("vsn_ext sn_ext 0 dc {VDD}", deck)
        self.assertIn(f".param VDD = {G.VDD_V}", deck)
        self.assertIn("xext sn_ext 0 0 0 sky130_fd_pr__nfet_01v8 l=0.15 w=0.42 ad=0.1974 as=0.1974 pd=1.78 ps=1.78", deck)
        self.assertIn("xleg sn_leg 0 0 0 sky130_fd_pr__nfet_01v8 l=0.15 w=0.42\n", deck)
        body = "\n".join(l for l in deck.splitlines() if not l.startswith("*"))
        self.assertNotIn(".lib", body)   # klt appends the .lib/.temp
        self.assertNotIn(".end", body)

    def test_committed_files_not_stale(self):
        self.assertEqual(G.DECK_PATH.read_text(), G.render_deck(G.load_geometry()["geometry"]))
        self.assertEqual(G.REQUEST_PATH.read_text(), G.render_request())

    def test_request_scope(self):
        r = G.build_request()
        self.assertEqual(r["backend"], "batch")
        self.assertEqual(r["corners"]["process"], ["tt", "ss", "ff", "sf", "fs"])
        self.assertEqual(r["corners"]["temperature_c"], [-40, 27, 125])
        self.assertEqual(len(r["measurements"]), 2)

    def test_legacy_template_untouched_no_diffusion(self):
        t = (HERE / "tb_access_leakage.spice.tmpl").read_text()
        xdut = [l for l in t.splitlines() if l.startswith("xdut")][0]
        for k in ("ad=", "as=", "pd=", "ps="):
            self.assertNotIn(k, xdut)


def current_pin_report(rep):
    return (rep.get("provenance", {}).get("pdk", {}).get("version") == f"open_pdks {A.G_pin()}")


class Analysis(unittest.TestCase):
    def test_ok(self):
        pts = A.extract_points(synth_report())
        self.assertEqual(len(pts), 15)
        rows = A.build_rows(pts, legacy_rows(), P)
        self.assertEqual(len(rows), 15)
        self.assertAlmostEqual(float(rows[0]["ratio_vs_historical"]), 2.0)
        self.assertAlmostEqual(float(rows[0]["ratio_vs_control"]), 2.0)

    def test_rejections(self):
        def drop(r): r["corners"].pop()
        def dup(r): r["corners"].append(copy.deepcopy(r["corners"][0]))
        def failed(r): r["status"] = "error"
        def badstatus(r): r["corners"][3]["status"] = "error"
        def nan(r): r["corners"][2]["measurements"][0]["value"] = float("nan")
        def none(r): r["corners"][2]["measurements"][0]["value"] = None
        def zero(r): r["corners"][2]["measurements"][1]["value"] = 0.0
        def missing(r): r["corners"][2]["measurements"].pop()
        def extra(r): r["corners"][0]["temperature_c"] = 85
        for m in (drop, dup, failed, badstatus, nan, none, zero, missing, extra):
            with self.assertRaises(A.AnalysisError, msg=m.__name__):
                A.extract_points(synth_report(m))

    def test_identity_and_units_rejected(self):
        def deck(r): r["environment"]["netlist_sha256"] = "0" * 64
        def deck_gone(r): del r["environment"]["netlist_sha256"]
        def input_hash(r): r["provenance"]["input"]["content_hash"] = "sha256:" + "0" * 64
        def pdk_ver(r): r["provenance"]["pdk"]["version"] = "open_pdks WRONG_PIN"
        def pdk_name(r): r["provenance"]["pdk"]["name"] = "sky130B"
        def no_prov(r): del r["provenance"]
        def milli(r):
            for c in r["corners"]:
                for m in c["measurements"]: m["unit"] = "mA"
        def no_unit(r): del r["corners"][4]["measurements"][0]["unit"]
        for m in (deck, deck_gone, input_hash, pdk_ver, pdk_name, no_prov, milli, no_unit):
            with self.assertRaises(A.AnalysisError, msg=m.__name__):
                A.extract_points(synth_report(m))

    def test_stale_deck_rejected(self):
        g = dict(G.load_geometry()["geometry"], w_um=0.84)
        with self.assertRaisesRegex(A.AnalysisError, "stale"):
            A.check_deck_matches_geometry(g)
        A.check_deck_matches_geometry(G.load_geometry()["geometry"])

    def test_committed_report_passes_identity(self):
        # Reports from an earlier open_pdks revision (c6d73a3 batch) are append-only
        # evidence reduced under their own revision; only current-pin reports are re-bound.
        checked = 0
        for p in RES.glob("klt_report_*.json"):
            rep = json.loads(p.read_text())
            if rep.get("status") == "pass" and current_pin_report(rep):
                A.check_identity(rep)
                checked += 1
        self.assertTrue(checked, "no committed report under the current PDK pin")

    def test_baseline_ambiguity_and_selection(self):
        extra = [dict(legacy_rows()[0], timestamp_utc="T1", ileak_a="3.0e-11")]
        pts = A.extract_points(synth_report())
        with self.assertRaisesRegex(A.AnalysisError, "ambiguous"):
            A.build_rows(pts, legacy_rows(extra), P)
        b = A.select_baseline(legacy_rows(extra), "tt", -40, P, timestamp="T1")
        self.assertEqual(b["ileak_a"], "3.0e-11")

    def test_missing_baseline_and_bad_denominator(self):
        pts = A.extract_points(synth_report())
        with self.assertRaisesRegex(A.AnalysisError, "no historical row"):
            A.build_rows(pts, legacy_rows()[1:], P)
        rows = legacy_rows()
        rows[0]["ileak_a"] = "0"
        with self.assertRaisesRegex(A.AnalysisError, "positive"):
            A.build_rows(pts, rows, P)

    def test_worst_case_is_computed(self):
        def hot(r):
            for c in r["corners"]:
                if (c["process"], c["temperature_c"]) == ("ss", 27):
                    c["measurements"][0]["value"] = 5e-10
        rep = synth_report(hot)
        rows = A.build_rows(A.extract_points(rep), legacy_rows(), P)
        s = A.summarize(rows, rep, G.load_geometry(), {})
        self.assertEqual((s["worst_case_extracted"]["corner"], s["worst_case_extracted"]["temp_c"]), ("ss", 27))

    def test_committed_results_reproduce(self):
        reports = sorted(p for p in RES.glob("klt_report_*.json")
                         if (lambda r: r.get("status") == "pass" and current_pin_report(r))(json.loads(p.read_text())))
        self.assertTrue(reports, "no successful committed report under the current PDK pin")
        for rep_path in reports:
            run = rep_path.stem.split("klt_report_", 1)[1]
            rep = json.loads(rep_path.read_text())
            self.assertEqual(rep["corner_count"], 15)
            with (RES / f"geom_leakage_points_{run}.csv").open(newline="") as f:
                committed = list(csv.DictReader(f))
            baseline_ts = {r["historical_timestamp_utc"] for r in committed}
            self.assertEqual(len(baseline_ts), 1)
            rows = A.build_rows(A.extract_points(rep), A.load_legacy(), P, baseline_ts.pop())
            self.assertEqual([{k: str(v) for k, v in r.items()} for r in rows], committed)
            summ = json.loads((RES / f"geom_leakage_summary_{run}.json").read_text())
            self.assertEqual(summ["n_points"], 15)
            top = max(rows, key=lambda r: float(r["i_extracted_a"]))
            self.assertEqual((summ["worst_case_extracted"]["corner"], summ["worst_case_extracted"]["temp_c"]),
                             (top["corner"], top["temp_c"]))

    def test_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            rp = Path(d) / "klt_report_X.json"
            rp.write_text(json.dumps(synth_report()))
            (Path(d) / "geom_leakage_points_X.csv").write_text("keep")
            self.assertEqual(A.main([str(rp)]), 2)
            self.assertEqual((Path(d) / "geom_leakage_points_X.csv").read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
