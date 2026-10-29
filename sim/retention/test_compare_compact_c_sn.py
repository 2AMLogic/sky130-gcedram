#!/usr/bin/env python3
"""Stdlib-only checks for the compact-layout evidence chain (issue #161): layout/compact_parasitics.py,
sim/leakage/compact_geometry_leakage.py and sim/retention/compare_compact_c_sn.py. No ngspice, PDK or klt.

Run: python3 -I sim/retention/test_compare_compact_c_sn.py
"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "sim" / "leakage"))
import compare_compact_c_sn as R  # noqa: E402
import compact_geometry_leakage as L  # noqa: E402
import compact_parasitics as CP  # noqa: E402


def dev(name, g, s, d, **p):
    params = {"l_um": 0.15, "w_um": 0.42, "ad_um2": 0.12, "as_um2": 0.06, "pd_um": 1.4, "ps_um": 0.7, **p}
    return {"name": name, "class": "nfet", "nets": {"g": g, "s": s, "d": d, "b": "GND"}, "params": params}


def synth(**over):
    devs = [dev("$1", "wl_0", "bl_0", "\\$7"), dev("$2", "\\$7", "rbl_0", "rwl_0")]
    return {"devices": devs, "parasitics": {"nets": [{"net": "\\$7"}]}, **over}


class StorageNodes(unittest.TestCase):
    def test_anonymous_sn_found_from_connectivity(self):
        self.assertEqual(CP.storage_nodes(synth()), ["\\$7"])

    def test_sn_without_read_gate_is_rejected(self):
        r = synth()
        r["devices"][1]["nets"]["g"] = "other"
        with self.assertRaises(CP.CompactError):
            CP.storage_nodes(r)

    def test_missing_parasitics_entry_is_rejected(self):
        r = synth()
        r["parasitics"]["nets"] = []
        with self.assertRaises(CP.CompactError):
            CP.storage_nodes(r)


class Orientation(unittest.TestCase):
    def test_sn_side_is_drain_whichever_label_it_carries(self):
        a = L.access_geometry({"devices": [dev("$1", "wl_0", "bl_0", "sn_0_0", ad_um2=0.12, pd_um=1.4, as_um2=0.06, ps_um=0.7)]})
        b = L.access_geometry({"devices": [dev("$1", "wl_0", "sn_0_0", "bl_0", as_um2=0.12, ps_um=1.4, ad_um2=0.06, pd_um=0.7)]})
        self.assertEqual(a, b)
        self.assertEqual((a["ad_um2"], a["pd_um"], a["as_um2"], a["ps_um"]), (0.12, 1.4, 0.06, 0.7))

    def test_heterogeneous_geometry_is_rejected(self):
        with self.assertRaises(L.CompactError):
            L.access_geometry({"devices": [dev("$1", "wl_0", "bl_0", "x"), dev("$2", "wl_1", "bl_0", "y", ad_um2=0.2)]})


class Committed(unittest.TestCase):
    def test_deck_and_request_are_current(self):
        self.assertEqual(L.check_generated(), 0)

    def test_v2_geometry_is_the_extracted_one(self):
        g = L.load_all()["v2"]["geometry"]
        self.assertEqual((g["ad_um2"], g["pd_um"], g["as_um2"], g["ps_um"]), (0.1197, 1.41, 0.0588, 0.7))

    def test_every_committed_result_reproduces(self):
        parasitics = sorted((REPO / "layout" / "results").glob(f"{CP.PREFIX}*.json"))
        retention = sorted((HERE / "results").glob(f"{R.OUTPUT_PREFIX}*.json"))
        self.assertTrue(parasitics and retention)
        # Only the newest file of each kind reproduces from the current inputs; earlier ones
        # are append-only history of the pre-#244 uniform-grid layout.
        self.assertEqual(CP.main(["--check", str(parasitics[-1])]), 0, parasitics[-1])
        self.assertEqual(R.main(["--check", str(retention[-1])]), 0, retention[-1])

    def test_budget_verdict_is_derived_not_hardcoded(self):
        doc = json.loads(sorted((HERE / "results").glob(f"{R.OUTPUT_PREFIX}*.json"))[-1].read_text())
        v2 = doc["layouts"]["compact_v2"]
        t = v2["at_limiting_node"]["retention_time_us"] * 1e-6
        self.assertEqual(doc["budget_check"]["compact_v2_wiring_only_holds"], t >= doc["budget_check"]["ratified_retention_s"])
        c = v2["c_sn_total_ff"]["min"] + v2["shortfall_vs_required_ff"]
        self.assertAlmostEqual(c, v2["c_sn_required_for_ratified_retention_ff"], places=5)

    def test_wrong_corner_leakage_is_rejected(self):
        import tempfile
        doc = json.loads(next((REPO / "sim" / "leakage" / "compact-geometry" / "results").glob("compact_leakage_summary_*.json")).read_text())
        bad = copy.deepcopy(doc)
        bad["worst_case"]["v2"]["corner"] = "tt"
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.json"
            p.write_text(json.dumps(bad))
            with self.assertRaises(R.CA.ComparisonError):
                R.load_leakage(p)


if __name__ == "__main__":
    unittest.main(verbosity=1)
