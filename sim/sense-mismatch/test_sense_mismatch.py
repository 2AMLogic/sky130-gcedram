#!/usr/bin/env python3
"""Stdlib-only checks for sim/sense-mismatch/ (issue #81). No ngspice, PDK or klt.

Run: python3 -I sim/sense-mismatch/test_sense_mismatch.py
"""
from __future__ import annotations

import csv
import gzip
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analyze_sense_mismatch as A  # noqa: E402
import build_yield_records as Y  # noqa: E402
import gen_sense_mismatch as M  # noqa: E402

RESULTS = HERE / "results"
BASE_CORNERS = {"tt", "ss", "ff", "sf", "fs"}


def _analysed_reports() -> list[tuple[Path, str, str]]:
    """(report, run_id, output prefix) for every committed report that has a summary."""
    out = []
    for rep in sorted(RESULTS.glob("klt_report_*.json*")):
        stem = rep.name.removesuffix(".gz").removesuffix(".json")
        cell = stem.startswith("klt_report_cell_")
        rid = stem.split("klt_report_cell_" if cell else "klt_report_", 1)[1]
        prefix = "mismatch_cell" if cell else "mismatch"
        if (RESULTS / f"{prefix}_summary_{rid}.json").exists():
            out.append((rep, rid, prefix))
    return out


class Generated(unittest.TestCase):
    def test_committed_files_not_stale(self):
        for path, text in M.render().items():
            self.assertEqual(text, path.read_text(), f"{path.name}: run gen_sense_mismatch.py")

    def test_scope_is_inside_the_proposed_restricted_range(self):
        # spec/operating-range-decision-PROPOSED.md: 27 C and 125 C, VDD = 1.8 V; no -40 C, one supply
        doc = (M.G.REPO / "spec" / "operating-range-decision-PROPOSED.md").read_text()
        self.assertIn("**Proposed interval: junction temperature 27 C to 125 C at `VDD` = 1.8 V.**", doc)
        self.assertEqual(M.VDD_V, 1.8)
        self.assertEqual(M.STAGE_CORNERS, [("tt_mm", 27), ("fs_mm", 27), ("ss_mm", 125), ("sf_mm", 125)])
        self.assertEqual(M.CELL_CORNERS, [("fs_mm", 27)])
        for path, want in ((M.STAGE_REQUEST_PATH, M.STAGE_CORNERS), (M.CELL_REQUEST_PATH, M.CELL_CORNERS)):
            r = json.loads(path.read_text())
            self.assertNotIn("supply_v", r["corners"])
            self.assertTrue(set(r["corners"]["temperature_c"]) <= {27, 125})
            for p in r["corners"]["process"]:
                self.assertTrue(p.endswith("_mm") and p[:-3] in BASE_CORNERS, p)
            got = {(p, t) for p in r["corners"]["process"] for t in r["corners"]["temperature_c"]}
            got -= {(e["process"], e["temperature_c"]) for e in r.get("exclude", [])}
            self.assertEqual(got, set(want))
            self.assertEqual(r["backend"], "batch")

    def test_monte_carlo_recorded_in_request(self):
        for path, n in ((M.STAGE_REQUEST_PATH, M.MC_N_STAGE), (M.CELL_REQUEST_PATH, M.MC_N_CELL)):
            mc = json.loads(path.read_text())["monte_carlo"]
            self.assertEqual((mc["n"], mc["seed"], mc["vary"]), (n, M.MC_SEED, "mismatch"))

    def test_baseline_sense_stage_request_untouched(self):
        self.assertNotIn("monte_carlo", json.loads(M.G.REQUEST_PATH.read_text()))

    def test_latch_is_the_design_netlist_latch(self):
        # issue #293: the latch is emitted from design/sense_latch.spice via
        # parse_cards (full geometry, nrd/nrs/sa/sb/sd included), not retyped
        latch = M.parse_cards(M.G.REPO / "design" / "sense_latch.spice")
        net = M.STAGE_NETLIST_PATH.read_text()
        lmap = {"rbl": "rbl_sz000_0", "ref": "ref_sz000_0", "vn": "vn_sz000_0", "vp": "vp_sz000_0",
                "en": "en", "enb": "enb", "vdd": "vdd", "GND": "0", "0": "0"}
        nets, model, params = latch["MN1"]
        self.assertIn(f"XMN1_sz000_0 {' '.join(lmap[x] for x in nets)} {model} {params}", net)
        nets, model, params = latch["MP2"]
        self.assertIn(f"XMP2_sz000_0 {' '.join(lmap[x] for x in nets)} {model} {params}", net)
        self.assertNotIn("XMRD", net)               # stage-only deck has no cells

    def test_latch_carries_source_drain_parasitics(self):
        # issue #293 regression guard: every committed deck that emitters built
        # from design/sense_latch.spice must carry nrd/nrs/sa/sb/sd on every
        # latch device -- the truncated parameter list this issue fixed must
        # not come back. The four committed top-level decks, one per generator.
        decks = [
            M.STAGE_NETLIST_PATH, M.CELL_NETLIST_PATH,
            M.G.NETLIST_PATH, M.G.REPO / "sim" / "refresh-op" / "refresh_op.spice",
        ]
        for deck in decks:
            for line in deck.read_text().splitlines():
                if line.startswith(("XMN1_", "XMN2_", "XMP1_", "XMP2_", "XMNF_", "XMPH_")):
                    for tok in ("nrd=", "nrs=", "sa=", "sb=", "sd="):
                        self.assertIn(tok, line, f"{deck.name}: {line.split()[0]} missing {tok}")

    def test_cell_deck_inlines_design_cards(self):
        (wm, wp), (rm, rp) = M.G.design_cell_cards()
        net = M.CELL_NETLIST_PATH.read_text()
        self.assertIn(f"XMRD_c1_r100_0800_0_0 rbl_c1_r100_0800_0 sn_c1_r100_0800_0_0 rwl_sel 0 {rm} {rp}", net)
        self.assertIn(f"{wm} {wp}", net)
        self.assertNotIn(".include", net.replace("* ", ""))

    def test_body_has_no_control_or_end_and_names_lowercase(self):
        for path in (M.STAGE_NETLIST_PATH, M.CELL_NETLIST_PATH):
            for line in path.read_text().splitlines():
                self.assertFalse(line.lower().startswith((".control", ".end")), line)
        for path in (M.STAGE_REQUEST_PATH, M.CELL_REQUEST_PATH):
            names = [m["name"] for m in json.loads(path.read_text())["measurements"]]
            self.assertEqual(len(names), len(set(names)))
            self.assertTrue(all(n == n.lower() for n in names))

    def test_sweep_has_both_polarities(self):
        pos = sorted(d for d in M.D_MV if d > 0)
        self.assertEqual(pos, sorted(-d for d in M.D_MV if d < 0))
        self.assertIn(0, M.D_MV)


class Statistics(unittest.TestCase):
    def test_probit_recovers_known_offset_distribution(self):
        rng = random.Random(81)
        xs, ys = [], []
        for x in M.D_MV:
            for _ in range(200):
                xs.append(float(x))
                ys.append(1 if x - rng.gauss(4.0, 25.0) > 0 else 0)
        f = A.probit_fit(xs, ys)
        self.assertEqual(f["fit"], "ok")
        lo, hi = f["sigma_ci95_mv"]
        self.assertTrue(lo < 25.0 < hi, f)
        self.assertTrue(f["mu_ci95_mv"][0] < 4.0 < f["mu_ci95_mv"][1], f)

    def test_degenerate_data_is_not_fitted(self):
        self.assertEqual(A.probit_fit([1.0, 2.0, 3.0], [1, 1, 1])["fit"], "not_identifiable")

    def test_wilson_and_rule_of_three(self):
        lo, hi = A.wilson(0, 240)
        self.assertEqual(lo, 0.0)
        self.assertLess(hi, 0.02)
        self.assertAlmostEqual(A.rule_of_three_upper(240), 0.0124, places=3)


class Analysis(unittest.TestCase):
    def test_failed_report_produces_no_results(self):
        with tempfile.TemporaryDirectory() as td:
            for name, body in (("klt_report_X.json", {"status": "error", "errored": 4, "corners": []}),
                               ("klt_report_cell_Y.json", {"schema_version": 1, "error": {"message": "x"}})):
                p = Path(td) / name
                p.write_text(json.dumps(body))
                self.assertEqual(A.main([str(p)]), 1)
            self.assertEqual(list(Path(td).glob("mismatch_*")), [])

    def test_committed_summaries_reproduce_from_committed_reports(self):
        for rep, rid, prefix in _analysed_reports():
            with tempfile.TemporaryDirectory() as td:
                (Path(td) / rep.name).write_bytes(rep.read_bytes())
                self.assertEqual(A.main([str(Path(td) / rep.name)]), 0)
                for name in (f"{prefix}_summary_{rid}.json", f"{prefix}_points_{rid}.csv"):
                    self.assertEqual((Path(td) / name).read_text(), (RESULTS / name).read_text(), name)

    def test_refuses_to_overwrite(self):
        for rep, _rid, _prefix in _analysed_reports():
            self.assertEqual(A.main([str(rep)]), 2)

    def test_summary_scope_claims_and_failed_points_kept(self):
        for rep, rid, prefix in _analysed_reports():
            d = json.loads((RESULTS / f"{prefix}_summary_{rid}.json").read_text())
            want = M.STAGE_CORNERS if prefix == "mismatch" else M.CELL_CORNERS
            self.assertEqual([(c["corner"], c["temp_c"]) for c in d["corners"]], want)
            self.assertFalse(d["claims"]["offset_yield_validated"])
            self.assertFalse(d["claims"]["array_level_yield"])
            self.assertFalse(d["claims"]["spec_changed"])
            self.assertFalse(d["claims"]["read_device_spread_folded_into_latch_sigma"])
            self.assertEqual(d["status"], "PROPOSED_OPERATING_RANGE_NOT_RATIFIED")
            rows = list(csv.DictReader((RESULTS / f"{prefix}_points_{rid}.csv").open()))
            insts = M.stage_instances() if prefix == "mismatch" else M.cell_instances()
            raw = rep.read_bytes()
            report = json.loads(gzip.decompress(raw) if rep.name.endswith(".gz") else raw)
            # every sample of every corner is kept, failed ones included
            self.assertEqual(len(rows), len(report["corners"]) * len(insts))
            for c in d["corners"]:
                self.assertEqual(c["n_samples"], (M.MC_N_STAGE if prefix == "mismatch" else M.MC_N_CELL))
                self.assertEqual(c["distinct_seeds"], c["n_samples"])      # samples really differ
                if prefix == "mismatch":
                    self.assertGreater(c["control_replica_disagreements"], 0)  # mismatch really acts


class YieldEvidence(unittest.TestCase):
    """T1 item 6 / spec row 2e campaign artifacts (issue #384)."""

    def test_row2e_requests_recorded_and_in_scope(self):
        stage_req = json.loads(M.STAGE_REQUEST_PATH.read_text())
        for path, netlist in ((M.ROW2E_REQUEST_PATH, "sense_mismatch.spice"),
                              (M.CONTROL_REQUEST_PATH, "sense_mismatch_control.spice")):
            r = json.loads(path.read_text())
            self.assertEqual(r["netlist"], netlist)
            self.assertEqual(r["backend"], "batch")
            self.assertEqual((r["monte_carlo"]["n"], r["monte_carlo"]["seed"], r["monte_carlo"]["vary"]),
                             (M.ROW2E_MC_N, M.ROW2E_MC_SEED, "mismatch"))
            # same restricted corner set as the committed study (no supply axis)
            self.assertEqual(r["corners"]["process"], stage_req["corners"]["process"])
            self.assertEqual(r["corners"]["temperature_c"], stage_req["corners"]["temperature_c"])
            self.assertEqual(r["exclude"], stage_req["exclude"])
            # same measurement set as the study deck (nothing re-labelled)
            self.assertEqual([m["name"] for m in r["measurements"]],
                             [m["name"] for m in stage_req["measurements"]])

    def test_control_deck_differs_only_by_the_seeded_defect(self):
        stage = M.STAGE_NETLIST_PATH.read_text().splitlines()
        ctrl = M.CONTROL_NETLIST_PATH.read_text().splitlines()
        # every latch device card is byte-identical (the defect is stimulus-side only)
        self.assertEqual([l for l in ctrl if l.startswith("X")],
                         [l for l in stage if l.startswith("X")])
        ref = f"vref_{round(M.STAGE_DREF_V * 1000):03d}"
        self.assertIn(f"{ref} pref_{round(M.STAGE_DREF_V * 1000):03d} 0 dc 0.8 ", "\n".join(stage))
        self.assertIn(f"{ref} pref_{round(M.STAGE_DREF_V * 1000):03d} 0 dc 0.93 ",
                      "\n".join(ctrl))  # 0.8 + CONTROL_REF_OFFSET_V = 0.93
        self.assertEqual(round(0.8 + M.CONTROL_REF_OFFSET_V, 6), 0.93)
        # every instance's reference initial condition carries the same offset
        self.assertGreater("\n".join(ctrl).count(")=0.930000"), 100)
        self.assertNotIn(")=0.930000", "\n".join(stage))

    def test_yield_limits_row2e_shape(self):
        limits = json.loads((HERE / "yield_limits_row2e.json").read_text())
        self.assertEqual(sorted(limits["measurements"]),
                         sorted(f"dend_sp{M.ROW2E_MARGIN_D_MV:03d}_{r}" for r in range(M.N_REPLICAS)))
        for entry in limits["measurements"].values():
            self.assertEqual(entry, {"min": 0.9, "spec_row": "2e"})  # no invented target_yield
        self.assertNotIn("target_yield", json.dumps(limits))

    def test_build_yield_records_decodes_names_and_skips_nulls(self):
        report = {"corners": [
            {"corner_id": "tt_mm/novdd/27C/mc0", "measurements": [
                {"name": "dend_sp150_0", "value": 1.8},
                {"name": "dend_sm050_3", "value": -1.8},
                {"name": "dend_sz000_5", "value": None},
                {"name": "din_sp150_0", "value": 0.15},      # not a decision: ignored
            ]},
            {"corner_id": "fs_mm/novdd/27C/mc17", "measurements": [
                {"name": "dend_sp002_1", "value": -1.8},
            ]},
        ]}
        records, skipped, per_corner = Y.build_records(report)
        self.assertEqual(records, [
            {"corner": "tt_mm/novdd/27C", "stimulus": 0.15, "value": 1.8},
            {"corner": "tt_mm/novdd/27C", "stimulus": -0.05, "value": -1.8},
            {"corner": "fs_mm/novdd/27C", "stimulus": 0.002, "value": -1.8},
        ])
        self.assertEqual(skipped, 1)
        self.assertEqual(per_corner, {"tt_mm/novdd/27C": 2, "fs_mm/novdd/27C": 1})

    def _newest(self, pattern: str) -> Path:
        paths = sorted(RESULTS.glob(pattern))
        self.assertTrue(paths, pattern)
        return paths[-1]

    def test_committed_yield_records_reproduce_from_their_report(self):
        doc = self._newest("yield_records_row2e_*.json")
        rid = doc.name.removesuffix(".json").split("yield_records_", 1)[1]
        report = RESULTS / f"klt_report_{rid}.json"
        self.assertTrue(report.exists(), report)
        got, _skipped, _per = Y.build_records(Y.load_report(report))
        self.assertEqual({"records": got}, json.loads(doc.read_text()))

    def test_committed_yield_artifacts_carry_campaign_discipline(self):
        report = json.loads(self._newest("klt_yield_report_row2e_*.json").read_text())
        self.assertEqual(report["status"], "reported")  # no target_yield declared: never failed, never claimed
        self.assertEqual(len(report["measurements"]), M.N_REPLICAS)
        for m in report["measurements"]:
            self.assertEqual(m["spec_row"], "2e")
            self.assertEqual(m["limits"], {"min": 0.9})
            self.assertEqual(m["n"], 4 * M.ROW2E_MC_N)  # pooled over the four restricted corners
            self.assertEqual(len(m["source_corners"]), 4)
            self.assertEqual(m["sample_size"]["verdict"], "sufficient")
            self.assertEqual(m["negative_control"]["verdict"], "detected")

    def test_committed_threshold_report_fits_every_corner(self):
        report = json.loads(self._newest("klt_yield_threshold_row2e_*.json").read_text())
        self.assertEqual([c["name"] for c in report["corners"]],
                         [f"{p}/novdd/{t}C" for p, t in M.STAGE_CORNERS])
        for c in report["corners"]:
            self.assertEqual(c["fit"]["status"], "ok")
            self.assertLess(c["fit"]["sigma_ci"]["lower"], c["fit"]["sigma"])
            self.assertGreater(c["fit"]["sigma_ci"]["upper"], c["fit"]["sigma"])


if __name__ == "__main__":
    unittest.main()
