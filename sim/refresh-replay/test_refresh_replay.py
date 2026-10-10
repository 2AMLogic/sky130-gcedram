#!/usr/bin/env python3
"""Stdlib-only checks for sim/refresh-replay/ (issue #128). No ngspice, PDK or klt. The RTL-export test
runs only when iverilog is on PATH (skipped otherwise).

Run: python3 -I sim/refresh-replay/test_refresh_replay.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analyze_refresh_replay as A  # noqa: E402
import export_rtl_trace as X  # noqa: E402
import gen_refresh_replay as G  # noqa: E402
import replay_lib as L  # noqa: E402

E = L.edge
# the anchored 2/10/20/2 REFRESH schedule from CONTRACT.md Sec. 2 (independent of the RTL run)
EXPECTED = [E(0, "pre_en", 1), E(0, "busy", 1), E(2, "pre_en", 0), E(2, "rwl_sel", 1), E(11, "sense_en", 1),
            E(12, "rwl_sel", 0), E(12, "sense_en", 0), E(12, "wwl_en", 1), E(12, "bl_drive", 1), E(32, "wwl_en", 0),
            E(34, "bl_drive", 0), E(34, "busy", 0), E(34, "done", 1), E(35, "done", 0)]


def golden() -> dict:
    return dict(initial={s: 0 for s in L.SIGNALS}, edges=L.sorted_edges(EXPECTED), pins={})


class Converter(unittest.TestCase):
    def test_rtl_export_matches_contract_schedule(self):
        if not shutil.which("iverilog") or not shutil.which("vvp"):
            self.skipTest("iverilog not available")
        tr = X.export()
        self.assertEqual(L.check_trace_consistency(golden(), tr), [])
        self.assertEqual(tr["initial"], {s: 0 for s in L.SIGNALS})

    def test_rwl_is_inverted_and_enable_pulse_is_not_stretched(self):
        init, ed = 0, L.trace_signal_edges(golden(), "rwl_sel")
        pts = L.edges_to_pwl(init, ed, True)
        self.assertEqual(pts[0], (0.0, "{VDD}"))                 # deasserted = high at the active-low pin
        self.assertEqual(pts[1:3], [(2.0, "{VDD}"), (2.1, "0")])  # assert pulls the pin to 0 V
        en = L.edges_to_pwl(0, L.trace_signal_edges(golden(), "sense_en"), False)
        self.assertEqual(en, [(0.0, "0"), (11.0, "0"), (11.1, "{VDD}"), (12.0, "{VDD}"), (12.1, "0")])

    def test_t0_edge_sets_initial_value_and_conversion_is_deterministic(self):
        e = L.trace_signal_edges(golden(), "pre_en")
        self.assertEqual(L.edges_to_pwl(0, e, False)[0], (0.0, "{VDD}"))
        self.assertEqual(L.pwl_text(L.edges_to_pwl(0, e, False)), L.pwl_text(L.edges_to_pwl(0, list(e), False)))

    def test_bad_edges_rejected(self):
        with self.assertRaises(ValueError):
            L.edges_to_pwl(0, [(5.0, 1), (5.05, 0)], False)   # closer than TEDGE
        with self.assertRaises(ValueError):
            L.edges_to_pwl(0, [(5.0, 0)], False)              # repeated value

    def test_pwl_roundtrip_all_pins(self):
        for sig, pm in L.PIN_MAP.items():
            init, ed = L.absorb_t0(0, L.trace_signal_edges(golden(), sig))
            txt = L.pwl_text(L.edges_to_pwl(0, L.trace_signal_edges(golden(), sig), pm["invert"]))
            self.assertEqual(L.pwl_to_edges(txt, pm["invert"]), (init, ed), sig)

    def test_latch_hold_adapter_is_explicit_and_bounded(self):
        ad = L.latch_hold_adapter(golden())
        self.assertEqual(ad["edges"], [(11.0, 1), (34.0, 0)])


class ConsistencyCheck(unittest.TestCase):
    def kinds(self, mut):
        return {f["kind"] for f in L.check_trace_consistency(golden(), L.mutate_trace(golden(), mut))}

    def test_identical_has_no_findings(self):
        self.assertEqual(L.check_trace_consistency(golden(), golden()), [])

    def test_omitted_edges_caught(self):
        self.assertIn("omitted", self.kinds("missing_wb"))

    def test_shifted_edge_caught(self):
        self.assertIn("shifted", self.kinds("short_wb"))
        self.assertIn("shifted", self.kinds("shift_wwl"))

    def test_reordered_edges_caught(self):
        self.assertIn("reordered", self.kinds("reorder"))

    def test_extra_and_value_mismatch(self):
        g = golden()
        extra = dict(g, edges=L.sorted_edges(g["edges"] + [E(20, "rwl_sel", 1)]))
        self.assertIn("extra", {f["kind"] for f in L.check_trace_consistency(g, extra)})
        flipped = dict(g, edges=[dict(e, value=1 - e["value"]) if e["signal"] == "wwl_en" else e for e in g["edges"]])
        self.assertIn("value_mismatch", {f["kind"] for f in L.check_trace_consistency(g, flipped)})


class Deck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = golden()
        cls.insts = G.build_instances(cls.g)
        c_sn_ff, _ = G.S.load_extracted_c_sn(G.S.EXTRACT_JSON, "sn")
        cls.deck = G.build_netlist(c_sn_ff * 1e-15, cls.insts)

    def test_deck_is_deterministic(self):
        c_sn_ff, _ = G.S.load_extracted_c_sn(G.S.EXTRACT_JSON, "sn")
        self.assertEqual(self.deck, G.build_netlist(c_sn_ff * 1e-15, G.build_instances(golden())))

    def test_deck_sources_reproduce_traces_and_negatives_deviate_from_golden(self):
        chk = G.verify_deck(self.deck, self.insts, self.g)
        for n, c in chk.items():
            self.assertTrue(c["deck_matches_trace"], n)
            neg = c["variant"] in G.NEGATIVE
            self.assertEqual(c["trace_matches_golden_rtl"], not neg, n)

    def test_deck_tamper_detected(self):
        bad = self.deck.replace("1.2000e-08 {VDD} 1.2100e-08 0", "1.3000e-08 {VDD} 1.3100e-08 0", 1)
        self.assertNotEqual(bad, self.deck)
        chk = G.verify_deck(bad, self.insts, self.g)
        self.assertTrue(any(not c["deck_matches_trace"] for c in chk.values()))

    def test_same_circuit_every_variant(self):
        # for each stored pattern, every non-source line is identical across variants once the instance name is masked
        srcs = ("vctl_", "vrs_", "ven_", "venb_", "vww_", "vwc_")
        groups = {}
        for p in self.insts:
            if p["kind"] == "ref":
                continue
            body = [ln.replace(p["name"], "X") for ln in self.deck.splitlines()
                    if f"_{p['name']}" in ln and not ln.startswith(srcs) and not ln.startswith(("*", ".ic"))]
            groups.setdefault((p["kind"], p["sn"]), []).append(body)
        self.assertEqual(len(groups), 4)
        for k, bodies in groups.items():
            self.assertEqual(len(bodies), len(G.VARIANTS), k)
            self.assertTrue(all(b == bodies[0] and b for b in bodies), k)

    def test_request_covers_ten_corners_and_probes(self):
        req = G.build_request(self.insts)
        self.assertEqual(len(req["corners"]["process"]) * len(req["corners"]["temperature_c"]), 10)
        self.assertEqual(req["backend"], "batch")
        names = {m["name"] for m in req["measurements"]}
        for p in self.insts:
            for k in ("snend", "snrd", "dec"):
                self.assertIn(f"{k}_{p['name']}", names)

    def test_baseline_is_prior_refresh_op_sequence(self):
        t = G.G.times(10e-9, 20e-9)
        b = next(p for p in self.insts if p["variant"] == "baseline_analog")
        self.assertAlmostEqual(b["t_release_ns"], t["t_rel"] * 1e9, places=6)
        self.assertAlmostEqual(b["t_meas_ns"], t["t_meas"] * 1e9, places=6)


def synth_corner(man, restored_rtl: bool, bad_decision: bool = False, status="pass"):
    """Synthetic klt corner: the baseline restores; the RTL variants restore only if restored_rtl; the
    negative controls never restore."""
    ms = []
    ref = 1.3
    ms.append(dict(name="snend_refw", value=ref))
    for mi in man["instances"]:
        if mi["kind"] == "ref":
            continue
        n, v = mi["name"], mi["variant"]
        good = v == "baseline_analog" or (v in ("rtl_raw", "rtl_hold") and restored_rtl)
        one = mi["kind"] == "op1"
        dec = (-1.7 if one else 1.7)
        if bad_decision and v == "rtl_raw":
            dec = 0.2
        sn = (ref if good else 0.9) if one else 0.0
        ms += [dict(name=f"dec_{n}", value=dec), dict(name=f"snend_{n}", value=sn), dict(name=f"snrd_{n}", value=1.0)]
    return dict(process="tt", temperature_c=27, status=status, measurements=ms)


class Analysis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        g = golden()
        insts = G.build_instances(g)
        c_sn_ff, _ = G.S.load_extracted_c_sn(G.S.EXTRACT_JSON, "sn")
        deck = G.build_netlist(c_sn_ff * 1e-15, insts)
        cls.check = G.verify_deck(deck, insts, g)
        cls.man = dict(variants=G.VARIANTS, negative_controls=G.NEGATIVE, instances=[
            dict(name=p["name"], kind=p["kind"], sn_v=p["sn"], variant=p["variant"], t_release_ns=p["t_release_ns"],
                 t_meas_ns=p["t_meas_ns"],
                 digital=L.digital_duration(p["trace"]) if p["variant"] not in ("baseline_analog", "reference_write") else None)
            for p in insts])

    def res(self, **kw):
        _, results = A.corner_results(synth_corner(self.man, **kw), self.man, self.check, None)
        return {r["variant"]: r for r in results}

    def test_simulator_success_is_not_a_restoration_pass(self):
        r = self.res(restored_rtl=False)
        self.assertTrue(r["rtl_hold"]["simulator_ok"] and r["rtl_hold"]["conversion_valid"] and r["rtl_hold"]["sense_correct"])
        self.assertFalse(r["rtl_hold"]["restore_success"])
        self.assertFalse(r["rtl_hold"]["overall_pass"])

    def test_pass_requires_all_four_verdicts(self):
        r = self.res(restored_rtl=True)
        self.assertTrue(r["rtl_hold"]["overall_pass"] and r["baseline_analog"]["overall_pass"])
        r = self.res(restored_rtl=True, bad_decision=True)
        self.assertFalse(r["rtl_raw"]["sense_correct"])
        self.assertFalse(r["rtl_raw"]["overall_pass"])
        self.assertTrue(r["rtl_hold"]["overall_pass"])
        r = self.res(restored_rtl=True, status="fail")
        self.assertFalse(r["rtl_hold"]["overall_pass"])

    def test_negative_controls_detected_and_fail_restoration(self):
        r = self.res(restored_rtl=True)
        for v in ("neg_missing_wb", "neg_short_wb"):
            self.assertTrue(r[v]["negative_control_detected"], v)
            self.assertFalse(r[v]["restore_success"], v)
            self.assertTrue(r[v]["negative_control_ok"], v)
            self.assertFalse(r[v]["overall_pass"], v)

    def test_negative_control_that_restores_is_flagged(self):
        c = synth_corner(self.man, True)
        for m in c["measurements"]:
            if "neg_missing_wb" in m["name"] and m["name"].startswith("snend_op1"):
                m["value"] = 1.3     # a "missing write-back" that still restores => check must fail
        _, results = A.corner_results(c, self.man, self.check, None)
        r = {x["variant"]: x for x in results}
        self.assertFalse(r["neg_missing_wb"]["negative_control_ok"])

    def test_duration_vs_budget(self):
        r = self.res(restored_rtl=True)
        d = r["rtl_hold"]["duration"]
        self.assertEqual((d["op_end_ns"], d["completion_observed_ns"], d["slack_op_end_ns"]), (34.0, 35.0, 0.0))
        self.assertTrue(d["fits_budget_op_end"])
        self.assertFalse(d["fits_budget_completion_observed"])
        self.assertFalse(d["fits_budget_settled_measurement"])
        self.assertFalse(r["baseline_analog"]["duration"]["fits_budget_op_end"])    # 37 ns


class Committed(unittest.TestCase):
    def test_committed_runs_are_self_consistent(self):
        for rd in sorted((HERE / "results").glob("*/")):
            man = json.loads((rd / "manifest.json").read_text())
            deck = (rd / "refresh_replay.spice").read_text()
            import hashlib
            self.assertEqual(hashlib.sha256(deck.encode()).hexdigest(), man["deck_sha256"], rd.name)
            chk = json.loads((rd / "consistency_check.json").read_text())
            self.assertTrue(all(c["deck_matches_trace"] for c in chk.values()), rd.name)
            if (rd / "summary.json").exists():
                s = json.loads((rd / "summary.json").read_text())
                self.assertEqual(s["generated_deck_sha256"], man["deck_sha256"])
                self.assertEqual(s["corner_count"], 10)
                for r in s["results"]:
                    if r["variant"] in man["negative_controls"]:
                        self.assertTrue(r["negative_control_ok"], (rd.name, r["corner"], r["temp_c"], r["variant"]))
                    # simulator success is never the restoration verdict
                    self.assertEqual(r["overall_pass"], r["variant"] not in man["negative_controls"] and r["simulator_ok"]
                                     and r["conversion_valid"] and r["sense_correct"] and r["restore_success"])


if __name__ == "__main__":
    unittest.main()
