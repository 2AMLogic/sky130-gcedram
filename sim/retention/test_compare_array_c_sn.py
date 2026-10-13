#!/usr/bin/env python3
"""Stdlib-only checks for sim/retention/compare_array_c_sn.py (issue #89).
No ngspice, PDK or klt.

Run: python3 -I sim/retention/test_compare_array_c_sn.py
"""
from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import compare_array_c_sn as C  # noqa: E402
import derive_retention as DR  # noqa: E402

RESULTS = HERE / "results"


def committed_comparisons() -> list[Path]:
    return sorted(RESULTS.glob(f"{C.OUTPUT_PREFIX}*.json"))


def net(name, ground, coupled=(), **extra):
    return {"net": name, "capacitance_ff": ground,
            "coupled": [{"net": n, "capacitance_ff": c} for n, c in coupled], **extra}


def synth_report(nets, devices=None):
    return {"top": "synth", "provenance": {"klt_version": "test", "input": {"content_hash": "sha256:synth"}},
            "devices": devices or [], "parasitics": {"nets": nets}}


class Tmp(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.dir = Path(self._d.name)

    def tearDown(self):
        self._d.cleanup()

    def write(self, name, obj):
        p = self.dir / name
        p.write_text(obj if isinstance(obj, str) else json.dumps(obj))
        return p


class NodeCapacitance(Tmp):
    def test_ground_plus_multiple_couplings(self):
        p = self.write("r.json", synth_report([net("sn_0_0", 0.4, [("bl_0", 0.01), ("rwl_0", 0.02), ("wl_0", 0.03)])]))
        data = C.load_report(p)
        node = C.node_capacitance(p, data, "sn_0_0")
        self.assertAlmostEqual(node["ground_ff"], 0.4)
        self.assertAlmostEqual(node["coupling_ff"], 0.06)
        self.assertAlmostEqual(node["total_ff"], 0.46)
        # identical to the default retention reader
        total, _ = DR.load_extracted_c_sn(p, "sn_0_0")
        self.assertAlmostEqual(node["total_ff"], total, places=9)
        self.assertEqual(list(node["coupled_ff"]), ["bl_0", "rwl_0", "wl_0"])

    def test_no_coupling(self):
        p = self.write("r.json", synth_report([net("sn_0_0", 0.5)]))
        self.assertAlmostEqual(C.node_capacitance(p, C.load_report(p), "sn_0_0")["total_ff"], 0.5)

    def test_missing_report(self):
        with self.assertRaises(C.ComparisonError):
            C.load_report(self.dir / "absent.json")

    def test_invalid_json(self):
        with self.assertRaises(C.ComparisonError):
            C.load_report(self.write("bad.json", "{not json"))

    def test_missing_parasitics_block(self):
        with self.assertRaises(C.ComparisonError):
            C.load_report(self.write("np.json", {"provenance": {}}))

    def test_missing_net(self):
        p = self.write("r.json", synth_report([net("sn_0_0", 0.5)]))
        with self.assertRaises(C.ComparisonError):
            C.node_capacitance(p, C.load_report(p), "sn_9_9")

    def test_duplicate_net(self):
        p = self.write("r.json", synth_report([net("sn_0_0", 0.5), net("sn_0_0", 0.6)]))
        with self.assertRaises(C.ComparisonError):
            C.node_capacitance(p, C.load_report(p), "sn_0_0")

    def test_invalid_and_nonpositive_capacitance(self):
        bad = [
            [net("sn_0_0", 0.0)],
            [net("sn_0_0", -0.1)],
            [net("sn_0_0", "abc")],
            [net("sn_0_0", None)],
            [net("sn_0_0", float("nan"))],
            [net("sn_0_0", True)],
            [net("sn_0_0", 0.4, [("bl_0", -0.01)])],
            [net("sn_0_0", 0.4, [("bl_0", "x")])],
            [net("sn_0_0", 0.4, [(None, 0.01)])],
            [{"net": "sn_0_0", "coupled": []}],
        ]
        for nets in bad:
            with self.subTest(nets=nets):
                p = self.write("r.json", synth_report(nets))
                with self.assertRaises(C.ComparisonError):
                    C.node_capacitance(p, C.load_report(p), "sn_0_0")

    def test_zero_coupling_is_allowed(self):
        p = self.write("r.json", synth_report([net("sn_0_0", 0.4, [("bl_0", 0.0)])]))
        self.assertAlmostEqual(C.node_capacitance(p, C.load_report(p), "sn_0_0")["total_ff"], 0.4)


class Reduction(Tmp):
    def grid(self, totals):
        nets = [net(f"sn_{r}_{c}", t) for (r, c), t in totals.items()]
        nets.append(net("bl_0", 9.0))  # non-storage nets are ignored
        return self.write("a.json", synth_report(nets))

    def test_all_nodes_and_minimum(self):
        totals = {(0, 0): 0.50, (0, 1): 0.48, (1, 0): 0.47, (1, 1): 0.52, (10, 2): 0.49}
        _, nodes = C.reduce_array(self.grid(totals))
        self.assertEqual([n["net"] for n in nodes], ["sn_0_0", "sn_0_1", "sn_1_0", "sn_1_1", "sn_10_2"])
        d = C.distribution(nodes)
        self.assertEqual(d["node_count"], 5)
        self.assertEqual(d["limiting_node"], "sn_1_0")
        self.assertEqual(d["max_node"], "sn_1_1")
        self.assertAlmostEqual(d["total_ff"]["min"], 0.47)

    def test_deterministic_ties(self):
        totals = {(2, 1): 0.47, (0, 3): 0.47, (1, 0): 0.47, (0, 0): 0.6, (3, 3): 0.6}
        _, nodes = C.reduce_array(self.grid(totals))
        for order in (nodes, list(reversed(nodes))):
            d = C.distribution(order)
            self.assertEqual(d["limiting_node"], "sn_0_3")
            self.assertEqual(d["nodes_tied_at_minimum"], ["sn_0_3", "sn_1_0", "sn_2_1"])
            self.assertEqual(d["max_node"], "sn_0_0")
            self.assertEqual(d["nodes_tied_at_maximum"], ["sn_0_0", "sn_3_3"])

    def test_tie_within_rounding(self):
        # 0.1 + 0.2 != 0.3 in binary; equal reported values must still tie
        p = self.write("a.json", synth_report([net("sn_1_0", 0.1, [("x", 0.2)]), net("sn_0_1", 0.3)]))
        _, nodes = C.reduce_array(p)
        self.assertEqual(C.distribution(nodes)["nodes_tied_at_minimum"], ["sn_0_1", "sn_1_0"])

    def test_no_storage_nets(self):
        with self.assertRaises(C.ComparisonError):
            C.reduce_array(self.write("a.json", synth_report([net("bl_0", 1.0)])))

    def test_device_storage_net_missing_from_parasitics(self):
        devices = [{"nets": {"d": "sn_0_0", "g": "wl_0", "s": "bl_0"}, "params": {}},
                   {"nets": {"d": "sn_0_1", "g": "wl_0", "s": "bl_1"}, "params": {}}]
        p = self.write("a.json", synth_report([net("sn_0_0", 0.5)], devices))
        with self.assertRaises(C.ComparisonError):
            C.reduce_array(p)


class RetentionUnits(unittest.TestCase):
    def test_formula_units(self):
        # 1 fF * 1 V / 1 pA = 1e-3 s
        self.assertAlmostEqual(C.retention_s(1.0, 1.0, 1e-12), 1e-3)
        with self.assertRaises(C.ComparisonError):
            C.retention_s(0.0, 0.9, 1e-10)

    def test_sensitivity_ratio_scales_linearly(self):
        iso = {"leakage_ileak_a": 1e-10, "delta_v_sense_margin_v_ASSUMPTION": 0.9,
               "retention_time_s": C.retention_s(0.6, 0.9, 1e-10), "leakage_source_row": "x", "source": "x"}
        nodes = [{"net": "sn_0_0", "total_ff": 0.3, "ground_ff": 0.25, "coupling_ff": 0.05},
                 {"net": "sn_0_1", "total_ff": 0.45, "ground_ff": 0.4, "coupling_ff": 0.05}]
        s = C.sensitivity(0.6, iso, nodes, C.distribution(nodes))
        self.assertEqual(s["limiting_node"], "sn_0_0")
        self.assertAlmostEqual(s["at_limiting_node"]["ratio_c_array_over_c_single"], 0.5)
        self.assertAlmostEqual(s["at_limiting_node"]["relative_delta"], -0.5)
        self.assertAlmostEqual(s["at_limiting_node"]["retention_time_s"], iso["retention_time_s"] * 0.5, delta=1e-12)
        self.assertAlmostEqual(s["at_limiting_node"]["retention_time_us"], 2.7)
        self.assertAlmostEqual(s["at_max_node"]["ratio_c_array_over_c_single"], 0.75)

    def test_sensitivity_rejects_inconsistent_baseline(self):
        iso = {"leakage_ileak_a": 1e-10, "delta_v_sense_margin_v_ASSUMPTION": 0.9,
               "retention_time_s": 1.0, "leakage_source_row": "x", "source": "x"}
        nodes = [{"net": "sn_0_0", "total_ff": 0.3, "ground_ff": 0.3, "coupling_ff": 0.0}]
        with self.assertRaises(C.ComparisonError):
            C.sensitivity(0.6, iso, nodes, C.distribution(nodes))


class Baselines(Tmp):
    HEADER = ",".join(DR.CSV_FIELDS)

    def row(self, mf, c, t, notes=""):
        vals = ["2026-01-01T00:00:00+00:00", "abc", "2T-min", "2T", '"corner=sf,temp_c=125"', "1e-10",
                "dev", "0.42", "0.15", "4e-09", "3.9", "8.7", "0.55", mf, c, "0.9", t, notes]
        return ",".join(vals)

    def test_selects_ratified_and_matching_extracted(self):
        p = self.write("r.csv", "\n".join([
            self.HEADER,
            self.row("2.0", "1.1", "9.9e-06"),
            self.row("", "0.6", "5.4e-06", "hash sha256:other"),
            self.row("", "0.6", "5.4e-06", "hash sha256:want"),
        ]) + "\n")
        b = C.baseline_rows(p, 0.6, "sha256:want")
        self.assertEqual(b["ratified"][0], 2)
        self.assertEqual(b["isolated"][0], 4)

    def test_missing_rows_and_mismatch(self):
        p = self.write("r.csv", self.HEADER + "\n" + self.row("2.0", "1.1", "9.9e-06") + "\n")
        with self.assertRaises(C.ComparisonError):
            C.baseline_rows(p, 0.6, "sha256:want")
        p = self.write("r2.csv", self.HEADER + "\n" + self.row("", "0.6", "5e-06", "sha256:want") + "\n")
        with self.assertRaises(C.ComparisonError):
            C.baseline_rows(p, 0.6, "sha256:want")  # no ratified row
        p = self.write("r3.csv", "\n".join([self.HEADER, self.row("2.0", "1.1", "9.9e-06"),
                                            self.row("", "0.7", "5e-06", "sha256:want")]) + "\n")
        with self.assertRaises(C.ComparisonError):
            C.baseline_rows(p, 0.6, "sha256:want")  # C_SN disagrees with the report
        with self.assertRaises(C.ComparisonError):
            C.baseline_rows(self.dir / "absent.csv", 0.6, "x")


class CommittedInputs(unittest.TestCase):
    """Recompute from the committed reports: a snapshot of those inputs."""

    @classmethod
    def setUpClass(cls):
        cls.doc = C.build()

    def test_covers_all_sixteen_nodes(self):
        a = self.doc["array"]
        self.assertEqual(a["node_count"], 16)
        self.assertEqual(sorted(n["net"] for n in a["nodes"]),
                         sorted(f"sn_{r}_{c}" for r in range(4) for c in range(4)))

    def test_recorded_range_and_limiting_node(self):
        a = self.doc["array"]
        self.assertAlmostEqual(a["total_ff"]["min"], 0.47362, places=6)
        self.assertAlmostEqual(a["total_ff"]["max"], 0.502, places=6)
        self.assertEqual(a["limiting_node"], "sn_3_3")
        self.assertEqual(a["nodes_tied_at_minimum"], ["sn_3_3"])

    def test_matches_issue80_summary(self):
        summary = json.loads((C.REPO_ROOT / "layout" / "gain_cell_2t_array.parasitics.summary.json").read_text())
        cmp_ = summary["comparison"]["c_sn"]
        s = self.doc["retention"]["array_capacitance_only_sensitivity"]
        self.assertAlmostEqual(self.doc["single_cell"]["total_ff"], cmp_["single_cell_ff"], places=6)
        self.assertAlmostEqual(s["at_limiting_node"]["relative_delta"], cmp_["array_relative_delta_min"], places=6)
        self.assertAlmostEqual(s["at_max_node"]["relative_delta"], cmp_["array_relative_delta_max"], places=6)
        per_cell = summary["per_cell_sn"]
        for n in self.doc["array"]["nodes"]:
            self.assertAlmostEqual(n["total_ff"], per_cell[n["net"]]["total_ff"], places=6)

    def test_baselines_kept_distinct(self):
        r = self.doc["retention"]
        self.assertAlmostEqual(r["ratified_prelayout"]["retention_time_s"], 1.005989e-05)
        self.assertAlmostEqual(r["isolated_cell_extracted"]["retention_time_s"], 5.503841e-06)
        s = r["array_capacitance_only_sensitivity"]
        self.assertIn("CAPACITANCE-ONLY SENSITIVITY", s["label"])
        self.assertIn("not an array guarantee", s["label"])
        # ratio derived, then applied to the extracted (not the ratified) estimate
        ratio = s["at_limiting_node"]["ratio_c_array_over_c_single"]
        self.assertAlmostEqual(s["at_limiting_node"]["retention_time_s"],
                               r["isolated_cell_extracted"]["retention_time_s"] * ratio, delta=1e-11)

    def test_geometry_trace(self):
        g = self.doc["leakage_geometry_trace"]
        self.assertEqual(g["leakage_testbench"]["diffusion_geometry_passed"], [])
        self.assertEqual(g["schematic_netlist"]["XM_WR"], {"ad": 0.1218, "as": 0.1218, "pd": 1.42, "ps": 1.42})
        self.assertEqual(g["extracted_array"]["write_device_drain_on_sn"],
                         [{"ad": 0.1974, "as": 0.1974, "pd": 1.78, "ps": 1.78}])
        self.assertFalse(g["geometry_matched_leakage_evidence_committed"])

    def test_committed_comparison_reproduces(self):
        files = committed_comparisons()
        self.assertTrue(files, "no committed array_c_sn_comparison_*.json")
        for f in files:
            with self.subTest(f=f.name):
                committed = json.loads(f.read_text())
                self.assertEqual(C.strip_volatile(committed), json.loads(json.dumps(C.strip_volatile(self.doc))))

    def test_check_cli(self):
        files = committed_comparisons()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(C.main(["--check", str(files[-1])]), 0)
        with tempfile.TemporaryDirectory() as d:
            bad = copy.deepcopy(json.loads(files[-1].read_text()))
            bad["array"]["limiting_node"] = "sn_0_0"
            p = Path(d) / "bad.json"
            p.write_text(json.dumps(bad))
            with redirect_stderr(io.StringIO()):
                self.assertEqual(C.main(["--check", str(p)]), 1)


class DefaultPathUntouched(unittest.TestCase):
    def test_default_source_is_isolated_cell(self):
        src = DR.EXTRACTED_C_SN_SOURCES["2T-min"]
        self.assertEqual(src["extract_json"].name, "gain_cell_2t.extract.parasitics.json")
        self.assertEqual(src["net"], "sn")
        total, _ = DR.load_extracted_c_sn(src["extract_json"], src["net"])
        self.assertAlmostEqual(total, 0.605354, places=6)


if __name__ == "__main__":
    unittest.main(verbosity=1)
