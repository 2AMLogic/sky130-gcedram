#!/usr/bin/env python3
"""Stdlib-only checks for sim/loaded-column/extracted-crbl/ (issue #88).

No ngspice, PDK or klt. Run: python3 -I sim/loaded-column/extracted-crbl/test_column_klt.py
"""
from __future__ import annotations

import csv
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analyze_column_klt as X  # noqa: E402
import gen_column_klt as G  # noqa: E402

R = G.R
RUNS = sorted(p for p in (HERE / "results").glob("*") if p.is_dir()) if (HERE / "results").is_dir() else []


def lines(text: str, prefix: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.startswith(prefix)]


class Generator(unittest.TestCase):
    def test_committed_decks_not_stale(self):
        self.assertEqual(G.main(["--check"]), 0, "run gen_column_klt.py")

    def test_extracted_c_rbl_is_the_cited_json_value(self):
        d = json.loads(G.PARASITICS_SUMMARY.read_text())
        v = d["comparison"]["c_rbl"]["extracted_4row_worst_total_ff"]
        self.assertAlmostEqual(v, 0.859179, places=6)
        self.assertEqual(v, max(c["total_ff"] for c in d["per_column"]["rbl"].values()))
        self.assertEqual(G.extracted_provenance()["netlist_sha256"],
                         "dd2cca26de34d6b7cd39a0d794db64993d6440c5ca7f248cf4d657b6f6b88d33")
        for vid in ("crbl_ext4row", "crbl_ext4row_layoutcard", "nc_write_disabled_ext4row"):
            self.assertEqual(G.variants()[vid]["c_rbl_f"], v * 1e-15)
            self.assertEqual(G.variants()[vid]["c_rbl_label"], "EXTRACTED-4-ROW")

    def test_c_rbl_is_the_whole_bitline_load_not_additive(self):
        for vid, spec in G.variants().items():
            for age in G.AGES:
                net = G.build_netlist(vid, age)
                self.assertEqual(lines(net, ".param C_RBL"), [f".param C_RBL = {G._fmt(spec['c_rbl_f'])}"])
                crbl = lines(net, "crbl_")
                self.assertEqual(len(crbl), 64)
                self.assertTrue(all(ln.split()[2:] == ["0", "{C_RBL}"] for ln in crbl))
                # no other capacitor touches any rbl node
                for ln in net.splitlines():
                    if ln.lower().startswith("c") and not ln.startswith("crbl_"):
                        self.assertNotIn(" rbl_", ln)

    def test_each_case_is_the_phase2_column(self):
        devs = R.parse_design_devices()
        net = G.build_netlist("crbl_ext4row", "fresh")
        for c in G.cases():
            t = c["tag"]
            wr = [ln for ln in lines(net, "XM_WR_") if ln.split()[0].endswith("_" + t)]
            rd = [ln for ln in lines(net, "XM_RD_") if ln.split()[0].endswith("_" + t)]
            self.assertEqual(len(wr), 4)
            self.assertEqual(len(rd), 4)
            for r in range(4):
                w = next(ln.split() for ln in wr if ln.startswith(f"XM_WR_{r}_0_{t}"))
                d = next(ln.split() for ln in rd if ln.startswith(f"XM_RD_{r}_0_{t}"))
                self.assertEqual(w[1:5], [f"sn{r}_{t}", f"wl_{r}", f"blp{c['pattern']:02d}", "GND"])
                self.assertEqual(d[1:5], [f"rbl_{t}", f"sn{r}_{t}", "rwls" if r == c["sel"] else "rwld", "GND"])
                self.assertEqual(w[5:], " ".join(devs["M_WR"]).split())
                self.assertEqual(d[5:], " ".join(devs["M_RD"]).split())
        self.assertEqual(len(lines(net, "XM_")), 64 * 8)

    def test_layout_card_changes_only_diffusion_fields(self):
        a = G.build_netlist("crbl_ext4row", "fresh").splitlines()
        b = G.build_netlist("crbl_ext4row_layoutcard", "fresh").splitlines()
        self.assertEqual(len(a), len(b))
        diff = [(x, y) for x, y in zip(a, b) if x != y]
        self.assertEqual(len(diff), 64 * 8 + 2)  # every bitcell device + two header comment lines
        for x, y in diff:
            if x.startswith("*"):
                continue
            self.assertIn("ad=0.1218 as=0.1218 pd=1.42 ps=1.42", x)
            self.assertIn("ad=0.1974 as=0.1974 pd=1.78 ps=1.78", y)
            self.assertEqual(x.replace("ad=0.1218 as=0.1218 pd=1.42 ps=1.42", ""),
                             y.replace("ad=0.1974 as=0.1974 pd=1.78 ps=1.78", ""))

    def test_negative_control_disables_only_the_write(self):
        a = G.build_netlist("crbl_ext4row", "fresh").splitlines()
        b = G.build_netlist("nc_write_disabled_ext4row", "fresh").splitlines()
        diff = [(x, y) for x, y in zip(a, b) if x != y]
        self.assertIn((".param VWL = {VDD}", ".param VWL = 0"), diff)
        self.assertTrue(all(x.startswith("*") or x.startswith(".param VWL") for x, _ in diff))

    def test_reference_is_the_contract_value(self):
        self.assertEqual(G.variants()["ref_crbl_10f"]["c_rbl_f"], 10e-15)
        self.assertEqual(G.variants()["crbl_2f"]["c_rbl_label"], "ASSUMPTION (mid-point)")

    def test_measurement_instants_match_phase2_measure(self):
        P = G.timing()
        for age in G.AGES:
            tr = R.read_time(P, age)
            for sel in range(4):
                m = G.meas_points(P, age, sel)
                self.assertAlmostEqual(m["rs"][2], tr + R.T_SENSE_S, delta=1e-15)
                self.assertAlmostEqual(m["rf"][2], tr - 0.2e-9, delta=1e-15)
                self.assertAlmostEqual(m["pr0"][2], tr - P["TPRE_GAP"] - 0.5e-9, delta=1e-15)
                self.assertAlmostEqual(m["en0"][2], tr + P["TREAD_PULSE"] + P["TTAIL"] - 0.5e-9, delta=1e-15)
                self.assertAlmostEqual(m["aw"][2], P["THOLD0"] - 0.5e-9, delta=1e-15)
                self.assertAlmostEqual(m["wo"][2], P["TW0"] + sel * P["TWSTEP"] + P["TWPULSE"], delta=1e-15)
            self.assertLess(G.t_late(P, age), G.t_stop(P, age))

    def test_requests_are_batch_lowercase_and_scoped(self):
        for vid, age, scope in G.REQUESTS:
            r = G.build_request(vid, age, scope)
            self.assertEqual(r["backend"], "batch")
            self.assertEqual(r["corners"], G.SCOPES[scope])
            self.assertEqual(len(r["measurements"]), 64 * 15)
            self.assertTrue(all(m["name"] == m["name"].lower() for m in r["measurements"]))
            self.assertNotIn("uic", r["analysis"]["args"])  # Phase 2 used .ic with an op point
        self.assertIn(("fs", -40), [(c, t) for c in G.SCOPES["grid"]["process"] for t in G.SCOPES["grid"]["temperature_c"]])
        self.assertIn(("ss", -40), [(c, t) for c in G.SCOPES["grid"]["process"] for t in G.SCOPES["grid"]["temperature_c"]])


def fake_report(vid: str, age: str, lat_reached: bool = True, status: str = "pass") -> dict:
    P = G.timing()
    tr = G.t_read(P, age)
    meas = []
    for c in G.cases():
        t, s = c["tag"], (c["pattern"] >> c["sel"]) & 1
        for n, (_k, _r, _at) in G.meas_points(P, age, c["sel"]).items():
            val = 0.9
            if n == "rs":
                val = 0.5 if s else 0.85
            meas.append({"name": f"{n}_{t}", "value": val})
        meas.append({"name": f"lat_{t}", "value": (tr + 1e-9) if (lat_reached and s) else G.t_late(P, age) + 1e-11})
    return {"netlist": {"path": f"sim/loaded-column/extracted-crbl/decks/{vid}_{age}.spice"},
            "status": status, "corner_count": 1, "errored": 0,
            "environment": {"engine_version": "46", "netlist_sha256": "x",
                            "remote": {"job_id": "klt-sim-test", "bucket": "secret-bucket-name"}},
            "provenance": {"klt_version": "0.6.0"},
            "corners": [{"process": "fs", "temperature_c": -40, "status": status, "measurements": meas}]}


class Analyzer(unittest.TestCase):
    def test_case_rows_and_latency_not_reached(self):
        rows = X.case_rows(fake_report("crbl_ext4row", "fresh", lat_reached=False), "T")
        self.assertEqual(len(rows), 64)
        self.assertTrue(all(r["status"] == "ok" for r in rows))
        self.assertTrue(all(r["latency_s"] == "" and r["latency_reason"] for r in rows))
        e = X.AV.evaluate_point("x", rows, G.T_SENSE_S, 0.0)
        self.assertAlmostEqual(e["worst_case_separation_v"], 0.35)
        self.assertFalse(e["criteria"]["latency"])
        self.assertFalse(e["PASS"])
        rows = X.case_rows(fake_report("crbl_ext4row", "fresh", lat_reached=True), "T")
        e = X.AV.evaluate_point("x", rows, G.T_SENSE_S, 0.0)
        self.assertTrue(e["PASS"])
        self.assertAlmostEqual(e["latency_stored1_s"]["max"], 1e-9, delta=1e-15)

    def test_failed_corner_is_kept_as_sim_failed(self):
        rows = X.case_rows(fake_report("crbl_2f", "refresh_bound", status="error"), "T")
        self.assertTrue(all(r["status"] == "sim_failed" and r["reason"] for r in rows))
        e = X.AV.evaluate_point("x", rows, G.T_SENSE_S, 0.0)
        self.assertFalse(e["PASS"])

    def test_ingest_redacts_bucket_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "r.json"
            src.write_text(json.dumps(fake_report("crbl_2f", "fresh")))
            old = X.RESULTS
            X.RESULTS = Path(td) / "results"
            try:
                self.assertEqual(X.ingest([str(src)], "C"), 0)
                out = X.read_gz(X.RESULTS / "C" / "klt_report_crbl_2f_fresh.json.gz")
                self.assertNotIn("secret-bucket-name", out)
                self.assertIn("<redacted-bucket>", out)
                self.assertEqual(X.ingest([str(src)], "C"), 2)
            finally:
                X.RESULTS = old

    def test_unknown_report_rejected(self):
        with self.assertRaises(ValueError):
            X.report_name({"netlist": {"path": "x/sense_stage.spice"}})


@unittest.skipUnless(RUNS, "no committed fleet run yet")
class Committed(unittest.TestCase):
    def test_summary_reproduces_from_committed_reports(self):
        for run in RUNS:
            with tempfile.TemporaryDirectory() as td:
                d = Path(td) / run.name
                d.mkdir()
                for p in run.glob("klt_report_*.json.gz"):
                    shutil.copy(p, d / p.name)
                rc = X.analyze(d)
                want = json.loads((run / "summary.json").read_text())
                self.assertEqual(rc, 1 if want["errors"] else 0)
                for n in ("cases.csv.gz", "summary.json"):
                    self.assertEqual((d / n).read_bytes(), (run / n).read_bytes(), f"{run.name}/{n}")

    def test_refuses_to_overwrite(self):
        self.assertEqual(X.analyze(RUNS[-1]), 2)

    def test_claims_and_coverage(self):
        for run in RUNS:
            s = json.loads((run / "summary.json").read_text())
            self.assertFalse(s["claims"]["spec_changed"])
            self.assertFalse(s["claims"]["n_rows_ratified"])
            self.assertFalse(s["claims"]["real_periphery_used"])
            self.assertEqual(s["c_rbl_source"]["key"], "comparison.c_rbl.extracted_4row_worst_total_ff")
            self.assertTrue(s["negative_control"]["behaves_as_expected"])
            rows = list(csv.DictReader(X.read_gz(run / "cases.csv.gz").splitlines()))
            want = sum(64 * len(X.expected_points(v, a)) for (v, a, _s) in G.REQUESTS)
            self.assertEqual(len(rows), want)


if __name__ == "__main__":
    unittest.main()
