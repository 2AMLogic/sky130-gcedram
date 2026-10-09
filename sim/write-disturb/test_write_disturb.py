#!/usr/bin/env python3
"""Stdlib-only checks for sim/write-disturb/ (issue #98). No ngspice, PDK or klt.

Run: python3 -I sim/write-disturb/test_write_disturb.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analyze_write_disturb as A  # noqa: E402
import gen_write_disturb as G  # noqa: E402

RESULTS = HERE / "results"


def synthetic_report(neg_leak: float = 0.30, std_leak: float = 0.02, hot_only_neg: bool = False) -> dict:
    """A klt-shaped report with a known, hand-built disturb.

    Controls hold their level (stored '1' droops 0.1 V, stored '0' gains 0.01 V over the run).
    Toggled rep1/rep0 shift the shared-WBL victims (column TARGET_COL, rows 1..3) by `std_leak`
    in the eroding direction at the last checkpoint (linear in checkpoint index); the neg family
    by `neg_leak`.
    """
    scs = {s["name"]: s for s in G.scenarios()}
    corners = []
    for p in G.PROCESS_CORNERS:
        for t in G.TEMPS_C:
            m: dict[str, float] = {}
            leak_n = neg_leak if (not hot_only_neg or t == 125) else 0.0
            for name, sc in scs.items():
                if sc["family"].startswith("hs_"):
                    for r in range(G.N_ROWS):
                        for c in range(G.N_COLS):
                            bit = G.stored_bit(sc, r, c)
                            lvl = G.V_SN1_V if bit else 0.0
                            m[G.meas_name("hs", name, r, c, "pre")] = lvl
                            m[G.meas_name("hs", name, r, c, "post")] = lvl + (0.05 if (r == 0 and c == 2) else 0.0)
                            if r == 0:
                                m[G.meas_name("hs", name, r, c, "min")] = lvl
                                m[G.meas_name("hs", name, r, c, "max")] = lvl + 0.3
                    continue
                neg = name.startswith("neg_")
                for r in range(G.N_ROWS):
                    for c in range(G.N_COLS):
                        bit = G.stored_bit(sc, r, c)
                        for k, n in enumerate(G.N_SET):
                            frac_t = (k + 1) / len(G.N_SET)
                            base = G.V_SN1_V - 0.1 * frac_t if bit else 0.0 + 0.01 * frac_t
                            v = base
                            if sc["family"].endswith("rep1") or sc["family"].endswith("rep0"):
                                if r >= 1 and c == G.TARGET_COL:
                                    d = (leak_n if neg else std_leak) * frac_t
                                    v = base - d if bit else base + d
                            m[G.meas_name("sn", name, r, c, f"n{n}")] = v
            corners.append({"process": p, "temperature_c": t, "status": "pass",
                            "measurements": [{"name": k, "value": v} for k, v in m.items()]})
    return {"status": "pass", "errored": 0, "corner_count": len(corners), "corners": corners,
            "environment": {"netlist_sha256": "x", "models_lib_sha256": "y", "engine_version": "ngspice-test",
                            "remote": {"job_id": "synthetic"}}}


class Generated(unittest.TestCase):
    def test_committed_files_not_stale(self):
        net, req = G.render()
        self.assertEqual(net, G.NETLIST_PATH.read_text(), "run gen_write_disturb.py")
        self.assertEqual(req, G.REQUEST_PATH.read_text(), "run gen_write_disturb.py")

    def test_scope_is_exactly_the_proposed_restricted_range(self):
        r = json.loads(G.REQUEST_PATH.read_text())
        self.assertEqual(r["corners"]["process"], ["tt", "ss", "ff", "sf", "fs"])
        self.assertEqual(r["corners"]["temperature_c"], [27, 125])
        self.assertNotIn("supply_v", r["corners"])
        self.assertNotIn("monte_carlo", r)
        self.assertEqual(r["backend"], "batch")
        self.assertEqual(G.VDD_V, 1.8)
        doc = (G.REPO / "spec" / "operating-range-decision-PROPOSED.md").read_text()
        self.assertIn("**Proposed interval: junction temperature 27 C to 125 C at `VDD` = 1.8 V.**", doc)

    def test_body_has_no_control_or_end_and_no_include(self):
        for line in G.NETLIST_PATH.read_text().splitlines():
            self.assertFalse(line.lower().startswith((".control", ".end", ".include", ".lib")), line)

    def test_names_lowercase_and_unique(self):
        r = json.loads(G.REQUEST_PATH.read_text())
        names = [m["name"] for m in r["measurements"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(n == n.lower() for n in names))
        inst = [s["name"] for s in G.scenarios()]
        self.assertEqual(len(inst), len(set(inst)))
        self.assertEqual(inst, G.STAGE_NAMES)

    def test_every_measured_node_exists_in_deck(self):
        net = G.NETLIST_PATH.read_text()
        r = json.loads(G.REQUEST_PATH.read_text())
        for m in r["measurements"]:
            node = re.search(r"v\((\w+)\)", m["spice"]).group(1)
            self.assertIn(f" {node} ", net.replace("\n", " ") + " ", node)

    @staticmethod
    def elem(line: str, prefix: str, inst: str) -> bool:
        tok = line.split()[0] if line.split() else ""
        guard = "" if inst.startswith("neg_") else "(?!.*neg_)"
        return bool(re.fullmatch(rf"{guard}{prefix}\S*_{inst}", tok))

    def test_extracted_array_inlined_faithfully(self):
        arr = G.parse_array()
        self.assertEqual(len(arr["mos"]), 32)
        self.assertEqual(sum(1 for m in arr["mos"] if G.is_write_device(m[2])), 16)
        net = G.NETLIST_PATH.read_text().splitlines()
        for sc in G.scenarios():
            inst = sc["name"]
            x = [ln for ln in net if self.elem(ln, "xm", inst)]
            self.assertEqual(len(x), 32, inst)
            rr = [ln for ln in net if self.elem(ln, "r", inst)]
            self.assertEqual(len(rr), len(arr["res"]) - 1, inst)         # Rvsubs_dctie replaced by ideal tie
            cc = [ln for ln in net if self.elem(ln, "c", inst)]
            self.assertEqual(len(cc), len(arr["cap"]), inst)
        # coupling capacitor bl_1 <-> sn_1_1 survives the translation with its value
        src = G.ARRAY_NETLIST.read_text()
        m = re.search(r"^Ccc_bl_1_sn_1_1 bl_1 sn_1_1 (\S+)$", src, re.M)
        if m:
            self.assertIn(f"ccc_bl_1_sn_1_1_ctl0 bl_1_ctl0 sn_1_1_ctl0 {G._fmt(float(m.group(1)))}", "\n".join(net))

    def test_negative_control_only_widens_write_devices(self):
        net = G.NETLIST_PATH.read_text().splitlines()
        std = {ln.split()[0][: -len("_ctl0")]: ln for ln in net if re.fullmatch(r"xm\d+_ctl0", ln.split()[0] if ln.split() else "")}
        neg = {ln.split()[0][: -len("_neg_ctl0")]: ln for ln in net if re.fullmatch(r"xm\d+_neg_ctl0", ln.split()[0] if ln.split() else "")}
        self.assertEqual(set(std), set(neg))
        widened = 0
        for k in std:
            ws = float(re.search(r" W=(\S+)", std[k]).group(1))
            wn = float(re.search(r" W=(\S+)", neg[k]).group(1))
            if wn != ws:
                widened += 1
                self.assertAlmostEqual(wn, ws * G.LEAKY_W_FACTOR, places=4)
        self.assertEqual(widened, 16)

    def test_stimulus_matches_documented_cadence(self):
        self.assertEqual(G.N_MAX, 147)         # floor(5.03 us / 34 ns)
        self.assertEqual(G.N_SET[-1], G.N_MAX)
        self.assertLess(G.checkpoint_time_s(G.N_MAX), G.T_STOP_S)
        self.assertAlmostEqual(G.REFRESH_BOUND_S, 5.029945e-06, places=11)
        pts = G.train(3, "wl")
        times = [t for t, _ in pts]
        self.assertEqual(times, sorted(times))
        # WL high exactly T_WL_W_S per cycle
        hi = [(t0, t1) for (t0, v0), (t1, v1) in zip(pts, pts[1:]) if v0 == G.VDD_V and v1 == G.VDD_V]
        self.assertEqual(len(hi), 3)
        self.assertTrue(all(abs((b - a) - G.T_WL_W_S + G.T_EDGE_S * 0) < 1e-12 + G.T_EDGE_S for a, b in hi))

    def test_ratified_constants_match_spec(self):
        doc = (G.REPO / "spec" / "retention-refresh-budget.md").read_text()
        self.assertIn("1.005989e-05", doc)
        self.assertAlmostEqual(G.T_RET_RATIFIED_S, 1.005989e-05)
        self.assertEqual(G.DELTA_V_V, 0.9)


class Analysis(unittest.TestCase):
    def run_synth(self, rep: dict):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        p = Path(td.name) / "klt_report_SYN.json"
        p.write_text(json.dumps(rep))
        self.assertEqual(A.main([str(p)]), 0)
        return Path(td.name), json.loads((Path(td.name) / "disturb_summary_SYN.json").read_text())

    def test_erosion_direction(self):
        self.assertAlmostEqual(A.erosion(1, 1.0, 0.8), 0.2)       # stored 1 drooped more than control
        self.assertAlmostEqual(A.erosion(0, 0.0, 0.05), 0.05)     # stored 0 gained more than control
        self.assertAlmostEqual(A.erosion(1, 0.8, 1.0), -0.2)      # helped -> negative, kept
        self.assertAlmostEqual(A.erosion(0, 0.05, 0.0), -0.05)

    def test_no_disturb_control_reads_zero(self):
        _d, s = self.run_synth(synthetic_report(neg_leak=0.30, std_leak=0.0))
        for c in s["corners"]:
            w = c["worst_normal_device"]
            self.assertAlmostEqual(w["erosion_v"], 0.0, places=12)
            self.assertFalse(w["flagged"])
            self.assertFalse(c["flagged_normal_device"])

    def test_known_disturb_is_reported_as_fraction_and_retention_loss(self):
        _d, s = self.run_synth(synthetic_report(std_leak=0.0585, neg_leak=0.30))
        w = s["corners"][0]["worst_normal_device"]
        self.assertAlmostEqual(w["erosion_v"], 0.0585, places=9)
        self.assertAlmostEqual(w["frac_delta_v"], 0.065, places=9)
        self.assertAlmostEqual(w["t_loss_ratified_s"], 0.065 * G.T_RET_RATIFIED_S, places=15)
        self.assertAlmostEqual(w["refresh_bound_derated_s"], G.T_RET_RATIFIED_S * (1 - 0.065) / 2, places=15)
        self.assertEqual(w["n_writes"], G.N_MAX)
        self.assertEqual(w["cls"], "shared_wbl_column")
        self.assertFalse(w["flagged"])
        self.assertIsNotNone(w["equiv_hold_time_s"])
        # hold drift of the control is 0.1 V / run for '1': 0.0585 V of disturb = 0.585 of the span
        t_span = G.checkpoint_time_s(G.N_SET[-1]) - G.checkpoint_time_s(G.N_SET[0])
        rate = (0.1 if w["stored"] == 1 else 0.01) * (1 - 1 / len(G.N_SET)) / t_span
        self.assertAlmostEqual(w["equiv_hold_time_s"], 0.0585 / rate, delta=1e-12)

    def test_over_limit_disturb_is_flagged_and_kept(self):
        _d, s = self.run_synth(synthetic_report(std_leak=0.18, neg_leak=0.45))
        for c in s["corners"]:
            self.assertTrue(c["worst_normal_device"]["flagged"])
            self.assertTrue(c["flagged_normal_device"])
        self.assertEqual(len(s["flagged_normal_device_corners"]), 10)

    def test_negative_control_is_flagged(self):
        _d, s = self.run_synth(synthetic_report(std_leak=0.02, neg_leak=0.30))
        self.assertTrue(s["negative_control_valid_at_all_hot_corners"])
        self.assertTrue(s["negative_control_flagged_at_worst_case_corner"])
        self.assertEqual(len(s["negative_control_flagged_corners"]), 10)
        for c in s["corners"]:
            self.assertTrue(c["negative_control_valid"])
            self.assertTrue(c["negative_control_flagged"])
            self.assertTrue(c["worst_negative_control"]["flagged"])

    def test_non_discriminating_negative_control_is_reported_invalid(self):
        # the "leaky" device is no worse than the normal one -> analysis must say so
        _d, s = self.run_synth(synthetic_report(std_leak=0.20, neg_leak=0.20))
        self.assertFalse(s["negative_control_valid_at_all_hot_corners"])
        self.assertEqual(s["negative_control_valid_corners"], [])
        # leaky device far above the normal one but still under the limit: valid, not flagged (recorded as is)
        _d, s = self.run_synth(synthetic_report(std_leak=0.0, neg_leak=0.05))
        self.assertTrue(s["negative_control_valid_at_all_hot_corners"])
        self.assertFalse(s["negative_control_flagged_at_worst_case_corner"])
        self.assertEqual(s["negative_control_flagged_corners"], [])
        # leaky device indistinguishable from nothing -> invalid
        _d, s = self.run_synth(synthetic_report(std_leak=0.0, neg_leak=0.0))
        self.assertFalse(s["negative_control_valid_at_all_hot_corners"])

    def test_cold_corner_only_invalidity_does_not_fail_hot_requirement(self):
        _d, s = self.run_synth(synthetic_report(std_leak=0.0, neg_leak=0.30, hot_only_neg=True))
        self.assertTrue(s["negative_control_valid_at_all_hot_corners"])
        self.assertEqual(len(s["negative_control_valid_corners"]), 5)

    def test_half_select_shift_is_signed_and_classified(self):
        d, s = self.run_synth(synthetic_report())
        rows = list(csv.DictReader((d / "disturb_halfselect_SYN.csv").open()))
        r = [x for x in rows if x["family"] == "hs_p1" and x["cell"] == "02"][0]
        self.assertEqual(r["cls"], "half_selected_row0")
        self.assertAlmostEqual(float(r["shift_v"]), 0.05)
        self.assertAlmostEqual(float(r["erosion_v"]), -0.05)      # stored '1' gaining is benign
        hs = s["corners"][0]["half_select"]["hs_p1"]
        self.assertAlmostEqual(hs["max_abs_shift_half_selected_v"], 0.05)

    def test_refuses_to_overwrite_and_failed_report(self):
        d, _s = self.run_synth(synthetic_report())
        self.assertEqual(A.main([str(d / "klt_report_SYN.json")]), 2)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "klt_report_X.json"
            p.write_text(json.dumps({"status": "error", "errored": 10, "corners": []}))
            self.assertEqual(A.main([str(p)]), 1)
            self.assertEqual(list(Path(td).glob("disturb_*")), [])

    def test_missing_values_are_counted_not_hidden(self):
        rep = synthetic_report()
        rep["corners"][0]["measurements"].pop(0)
        _d, s = self.run_synth(rep)
        self.assertGreaterEqual(s["corners"][0]["missing_values"] + sum(c["missing_values"] for c in s["corners"][1:]), 0)


class Committed(unittest.TestCase):
    def test_committed_summaries_reproduce_from_committed_reports(self):
        reports = sorted(RESULTS.glob("klt_report_*.json"))
        if not reports:
            self.skipTest("no klt report committed yet")
        for rep in reports:
            rid = rep.stem.split("klt_report_")[1]
            if not (RESULTS / f"disturb_summary_{rid}.json").exists():
                continue
            with tempfile.TemporaryDirectory() as td:
                (Path(td) / rep.name).write_text(rep.read_text())
                self.assertEqual(A.main([str(Path(td) / rep.name)]), 0)
                for name in (f"disturb_summary_{rid}.json", f"disturb_points_{rid}.csv",
                             f"disturb_halfselect_{rid}.csv"):
                    self.assertEqual((Path(td) / name).read_text(), (RESULTS / name).read_text(), name)

    def test_committed_summary_scope_and_claims(self):
        for s in RESULTS.glob("disturb_summary_*.json"):
            d = json.loads(s.read_text())
            self.assertEqual({(c["corner"], c["temp_c"]) for c in d["corners"]},
                             {(p, t) for p in G.PROCESS_CORNERS for t in G.TEMPS_C})
            self.assertFalse(d["claims"]["spec_changed"])
            self.assertFalse(d["claims"]["refresh_bound_changed"])
            self.assertEqual(d["status"], "PROPOSED_OPERATING_RANGE_NOT_RATIFIED")
            self.assertTrue(d["batch_job_id"])
            self.assertTrue(d["negative_control_valid_at_all_hot_corners"],
                            "negative control must be distinguishable at every 125 C corner")
            self.assertTrue(d["negative_control_flagged_at_worst_case_corner"],
                            "negative control must be flagged at sf/125 C")
            for c in d["corners"]:
                self.assertEqual(c["missing_values"], 0)


if __name__ == "__main__":
    unittest.main()
