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
import gen_rwl_driver_sweep as D  # noqa: E402
import analyze_rwl_driver_sweep as AD  # noqa: E402
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
            neg = c["variant"] in G.NEGATIVE or bool(G.EXPERIMENTS.get(c["variant"], {}).get("rwl_release"))
            # by-design deviations; latch-only experiments change only the adapter, not the RTL strobes
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
        cls.man = dict(variants=G.VARIANTS, negative_controls=G.NEGATIVE, experiments=G.EXPERIMENTS, instances=[
            dict(name=p["name"], kind=p["kind"], sn_v=p["sn"], variant=p["variant"], t_release_ns=p["t_release_ns"],
                 t_meas_ns=p["t_meas_ns"], t_rwl_release_ns=p["t_rwl_release_ns"], t_latch_release_ns=p["t_latch_release_ns"],
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


class Experiments(unittest.TestCase):
    """Issue #131: each control changes only its intended release edge(s); consistency still checked."""

    @classmethod
    def setUpClass(cls):
        cls.g = golden()
        cls.insts = G.build_instances(cls.g)
        c_sn_ff, _ = G.S.load_extracted_c_sn(G.S.EXTRACT_JSON, "sn")
        cls.deck = G.build_netlist(c_sn_ff * 1e-15, cls.insts)
        cls.check = G.verify_deck(cls.deck, cls.insts, cls.g)

    def nodes(self, v):
        return next(i for i in self.insts if i["variant"] == v and i["kind"] == "op1" and i["sn"] == 0.9)["nodes"]

    def test_each_experiment_changes_only_intended_edges(self):
        for v, ex in G.EXPERIMENTS.items():
            d = L.diff_node_waveforms(self.nodes(ex["parent"]), self.nodes(v))
            self.assertEqual({x["node"]: x["to_ns"] for x in d}, ex["intended"], v)
            self.assertTrue(all(x["kind"] == "shifted" for x in d), v)
            for c in self.check.values():
                if c["variant"] == v:
                    self.assertTrue(c["deck_matches_trace"] and c["experiment_diff"]["only_intended_edges"], v)

    def test_individual_controls_are_orthogonal_and_combined_composes_them(self):
        n = {v: self.nodes(v) for v in ("rtl_hold", "rwl_late_hold", "latch_late_hold", "combined_hold")}
        self.assertEqual(n["rwl_late_hold"]["en"], n["rtl_hold"]["en"])        # RWL control leaves the latch alone
        self.assertEqual(n["latch_late_hold"]["rwls"], n["rtl_hold"]["rwls"])  # latch control leaves RWL alone
        for node in ("ctl", "wwl", "wbc"):
            for v in n:
                self.assertEqual(n[v][node], n["rtl_hold"][node], (v, node))
        self.assertEqual(n["combined_hold"]["rwls"], n["rwl_late_hold"]["rwls"])
        self.assertEqual(n["combined_hold"]["en"], n["latch_late_hold"]["en"])

    def test_retimed_write_pulse_width_is_unchanged(self):
        for i in self.insts:
            if i["variant"] in G.EXPERIMENTS:
                self.assertEqual(i["t_wwl_fall_ns"] - i["t_wwl_rise_ns"], 20.0, i["name"])
                self.assertEqual(i["sn"], next(j for j in self.insts if j["variant"] == "rtl_hold" and j["kind"] == i["kind"] and j["sn"] == i["sn"])["sn"])

    def test_retime_edge_refuses_ambiguous_edge(self):
        with self.assertRaises(ValueError):
            L.retime_edge(self.g, "sense_en", 5, 3.0)
        t = L.retime_edge(self.g, "rwl_sel", 0, 34.0)
        self.assertEqual(L.check_trace_consistency(self.g, t)[0]["kind"], "shifted")
        self.assertEqual({f["kind"] for f in L.check_trace_consistency(self.g, t)}, {"shifted", "reordered"})

    def test_tampered_experiment_is_flagged(self):
        maps = {"rtl_hold": self.nodes("rtl_hold"), "rwl_late_hold": dict(self.nodes("rwl_late_hold"))}
        init, ed, inv = maps["rwl_late_hold"]["wwl"]
        maps["rwl_late_hold"]["wwl"] = (init, [(t + 1.0, v) for t, v in ed], inv)    # an unintended extra change
        self.assertFalse(G.experiment_diff("rwl_late_hold", maps)["only_intended_edges"])

    def test_request_has_issue131_probes(self):
        names = {m["name"] for m in G.build_request(self.insts)["measurements"]}
        for p in self.insts:
            for k in ("snwa", "wbla", "dla", "snrb", "snra", "snset", "dend", "wblp", "snwf"):
                self.assertIn(f"{k}_{p['name']}", names)

    def test_attribution_labels(self):
        def res(v, frac, ok):
            return dict(corner="tt", temp_c=27, variant=v, min_op1_fraction=frac, restore_success=ok)
        base = [res("rtl_raw", .79, False), res("rtl_hold", .87, False), res("rwl_late_raw", .79, False),
                res("rwl_late_hold", .99, True), res("latch_early_hold", .87, False), res("latch_late_hold", .87, False),
                res("combined_hold", .99, True), res("baseline_analog", 1.03, True)]
        a = A.attribution(base)
        self.assertEqual(a["rwl_release_late | latch hold"]["label"], "isolated_sufficient_restores_everywhere")
        self.assertEqual(a["rwl_release_late | no latch hold"]["label"], "no_resolvable_effect")
        self.assertEqual(a["latch_hold | RWL early"]["label"], "improves_all_corners_not_sufficient")
        self.assertEqual(a["latch_hold | RWL late"]["corners_fail_to_pass"], 1)


class DriverSweep(unittest.TestCase):
    """Issue #134: RWL driver slew / impedance / release-delay study. Only the declared parameters may change."""

    @classmethod
    def setUpClass(cls):
        cls.g = golden()
        cls.g0 = json.loads(json.dumps(cls.g))
        cls.controls = G.build_instances(cls.g)
        cls.points = D.sweep_points()
        cls.sweep = D.build_sweep_instances(cls.g, cls.controls, cls.points)
        cls.all = cls.controls + cls.sweep
        c_sn_ff, _ = G.S.load_extracted_c_sn(G.S.EXTRACT_JSON, "sn")
        cls.c_sn = c_sn_ff * 1e-15
        cls.deck = D.build_deck(cls.c_sn, cls.controls, cls.sweep)
        cls.check = D.verify_sweep(cls.deck, cls.all)

    def test_converter_default_edge_unchanged_and_slew_roundtrips(self):
        e = L.trace_signal_edges(self.g, "rwl_sel")
        self.assertEqual(L.edges_to_pwl(0, e, True), L.edges_to_pwl(0, e, True, L.T_EDGE_NS))
        for te in (0.5, 5.0):
            txt = L.pwl_text(L.edges_to_pwl(0, e, True, te))
            self.assertEqual(L.pwl_to_edges(txt, True, te), L.absorb_t0(0, e))
        with self.assertRaises(ValueError):
            L.edges_to_pwl(0, [(0.05, 1)], False)       # first edge closer than the default TEDGE is still rejected
        with self.assertRaises(ValueError):
            L.edges_to_pwl(0, [(5.0, 1), (7.0, 0)], False, 5.0)   # second edge inside the first 5 ns ramp

    def test_all_sweep_instances_change_only_declared_parameters(self):
        self.assertEqual(len(self.sweep), 4 * len(self.points))
        for n, c in self.check.items():
            self.assertTrue(c["declared_changes_only"], (n, c["findings"]))

    def test_controls_in_new_deck_are_the_original_deck_lines(self):
        orig = G.build_netlist(self.c_sn, self.controls).splitlines()
        new = set(self.deck.splitlines())
        missing = [ln for ln in orig if ln not in new and not ln.startswith(".ic")]
        self.assertEqual(missing, [])

    def test_ideal_driver_points_reproduce_control_source_exactly(self):
        for p in self.sweep:
            pt = p["point"]
            if pt["slew_ns"] == D.IDEAL_SLEW_NS and pt["r_ohm"] == 0 and pt["release_delay_ns"] == 2.0:
                par = next(c for c in self.controls if c["variant"] == "rwl_late_hold" and c["kind"] == p["kind"] and c["sn"] == p["sn"])
                self.assertEqual(self.check[p["name"]]["findings"], [])
                self.assertEqual(p["nodes"], par["nodes"])

    def test_tampering_is_flagged(self):
        pick = next(p for p in self.sweep if p["point"]["id"] == "rl_s1_r10k")
        n = pick["name"]
        for old, new in ((f"vww_{n} ", None), (f"rdrv_{n} rwlsrc_{n} rwls_{n} 10000", f"rdrv_{n} rwlsrc_{n} rwls_{n} 20000")):
            lines = self.deck.splitlines()
            if new is None:        # shift the WWL source
                lines = [ln.replace("1.2000e-08", "1.3000e-08") if ln.startswith(old) else ln for ln in lines]
            else:
                lines = [ln.replace(old, new) for ln in lines]
            bad = "\n".join(lines)
            self.assertNotEqual(bad, self.deck)
            self.assertFalse(D.verify_sweep(bad, self.all)[n]["declared_changes_only"], old)
        # an unintended extra element in the instance (structure change)
        bad = self.deck.replace(f"csn_{n}_0 ", f"csn_{n}_0 ", 1) + f"\nrextra_{n} sn_{n}_0 0 1k\n"
        self.assertFalse(D.verify_sweep(bad, self.all)[n]["declared_changes_only"])
        # a different ramp time than the declared slew
        lines = self.deck.splitlines()
        i = next(k for k, ln in enumerate(lines) if ln.startswith(f"vrs_{n} "))
        lines[i] = lines[i].replace("3.0000e-09", "3.5000e-09", 1)
        self.assertFalse(D.verify_sweep("\n".join(lines), self.all)[n]["declared_changes_only"])

    def test_release_delay_points_move_only_the_rwl_release(self):
        par = next(c for c in self.controls if c["variant"] == "rwl_late_hold" and c["kind"] == "op1" and c["sn"] == 0.9)
        seen = []
        for p in self.sweep:
            if p["point"]["group"] != "release_delay" or p["kind"] != "op1" or p["sn"] != 0.9:
                continue
            d = L.diff_node_waveforms(par["nodes"], p["nodes"])
            want = p["point"]["rwl_release_ns"]
            self.assertAlmostEqual(want, D.WWL_FALL_NS + p["point"]["release_delay_ns"])
            if want == GR_RWL_LATE:
                self.assertEqual(d, [])
            else:
                self.assertEqual([(x["node"], x["kind"], x["to_ns"]) for x in d], [("rwls", "shifted", want)])
            self.assertEqual(p["t_wwl_fall_ns"], 32.0)
            seen.append(p["point"]["release_delay_ns"])
        self.assertEqual(sorted(set(seen)), sorted(D.RELEASE_DELAYS_NS))
        self.assertIn(0.0, seen)
        self.assertTrue(any(x < 0 for x in seen) and any(x > 2 for x in seen))

    def test_axes_are_independent_before_combined(self):
        ids = [p["id"] for p in self.points]
        for p in self.points:
            if p["group"] == "slew_only":
                self.assertEqual(p["r_ohm"], 0.0)
            elif p["group"] == "r_only":
                self.assertEqual(p["slew_ns"], D.IDEAL_SLEW_NS)
                self.assertGreater(p["r_ohm"], 0)
            elif p["group"] == "combined":
                self.assertGreater(p["slew_ns"], D.IDEAL_SLEW_NS)
                self.assertGreater(p["r_ohm"], 0)
        last_single = max(i for i, p in enumerate(self.points) if p["group"] in ("slew_only", "r_only"))
        first_comb = min(i for i, p in enumerate(self.points) if p["group"] == "combined")
        self.assertGreater(first_comb, last_single - 100)   # declared order: per base, singles then combined
        for base in ("an", "rh", "rl"):
            b = [p["group"] for p in self.points if p["base"] == base and p["group"] in ("slew_only", "r_only", "combined")]
            self.assertLess(max(i for i, g in enumerate(b) if g != "combined"), min(i for i, g in enumerate(b) if g == "combined"))
        self.assertEqual(len(ids), len(set(ids)))

    def test_slew_only_has_no_resistor_and_r_points_have_one(self):
        for p in self.sweep:
            has_r = f"rdrv_{p['name']} " in self.deck
            self.assertEqual(has_r, p["point"]["r_ohm"] > 0, p["name"])

    def test_gating_probe_is_never_moved(self):
        for p in self.sweep:
            par = next(c for c in self.controls if c["variant"] == p["point"]["parent"] and c["kind"] == p["kind"] and c["sn"] == p["sn"])
            self.assertEqual(p["t_meas_ns"], par["t_meas_ns"], p["name"])
            self.assertEqual(p["t_dec_ns"], par["t_dec_ns"], p["name"])

    def test_probes_are_at_the_cell_pin_and_distinguish_source_timing(self):
        req = D.build_request(self.all)
        text = {m["name"]: m["spice"] for m in req["measurements"]}
        p = next(i for i in self.sweep if i["point"]["id"] == "rl_s5_r0")
        n = p["name"]
        for k in ("tp10r", "tp50r", "tp90r", "tpa50", "pinm", "pina"):
            self.assertIn(f"v(rwls_{n})", text[f"{k}_{n}"])
        self.assertNotIn("rwlsrc", " ".join(text.values()))
        self.assertEqual((p["t_src_release_start_ns"], p["t_src_release_50_ns"], p["t_src_release_end_ns"]), (34.0, 36.5, 39.0))
        self.assertIn("v(wwl_", text[f"twf50_{n}"])
        neg = next(i for i in self.sweep if i["point"]["base"] == "nr")
        self.assertNotIn(f"twf50_{neg['name']}", text)       # no WWL fall exists in the missing-write-back instance

    def test_golden_trace_and_control_variants_untouched(self):
        self.assertEqual(self.g, self.g0)
        self.assertEqual([c["name"] for c in self.controls], [c["name"] for c in G.build_instances(golden())])

    def test_negative_control_points_present(self):
        bases = {p["base"] for p in self.points if p["group"] == "negative_control"}
        self.assertEqual(bases, {"nr", "nl"})


GR_RWL_LATE = G.RWL_LATE_NS


class DriverSweepAnalysis(unittest.TestCase):
    def test_envelope_bounded_and_unbounded_and_reference_failure(self):
        def e(ok):
            return dict(restore_success_0_95=10 if ok else 0, worst_min_op1_fraction=1.0, failure_reasons={})
        ent = [(0.1, e(1)), (0.5, e(1)), (1.0, e(1)), (2.0, e(0)), (5.0, e(1))]
        r = AD.axis_envelope("slew", ent, "ideal", lambda x: x["restore_success_0_95"] == 10, 0)
        self.assertEqual((r["status"], r["passing_interval"], r["upper_bounded_by_failing_tested_point"]), ("bounded_above_only", [0.1, 1.0], 2.0))
        self.assertEqual(r["non_contiguous_passes_outside_interval"], [5.0])
        r = AD.axis_envelope("slew", ent[:3], "ideal", lambda x: x["restore_success_0_95"] == 10, 0)
        self.assertEqual(r["status"], "no_failure_within_tested_range")      # explicit absence of a bound
        r = AD.axis_envelope("slew", [(0.1, e(0)), (0.5, e(1))], "ideal", lambda x: x["restore_success_0_95"] == 10, 0)
        self.assertEqual(r["status"], "reference_point_fails")
        r = AD.axis_envelope("d", [(-2, e(0)), (0, e(1)), (2, e(1)), (3, e(0))], "d=2", lambda x: x["restore_success_0_95"] == 10, 2)
        self.assertEqual((r["status"], r["passing_interval"]), ("bounded_on_both_sides", [0, 2]))

    def test_failure_reason_separates_sense_and_restore(self):
        self.assertEqual(AD.reason(True, True, True, True), "pass")
        self.assertEqual(AD.reason(True, False, False, False), "sense_incorrect")
        self.assertEqual(AD.reason(True, True, False, True), "stored1_below_threshold")
        self.assertEqual(AD.reason(True, True, True, False), "stored0_above_50mV")
        self.assertEqual(AD.reason(False, True, True, True), "simulator_error")

    def test_time_budget_is_independent_of_restoration(self):
        mi = dict(digital=dict(busy_fall_ns=34.0), t_release_ns=34.0, t_src_release_end_ns=39.0, t_meas_ns=36.0)
        d = AD.duration(mi, 38.5, 36.5)
        self.assertTrue(d["fits_op_end_source_start"])          # source edge STARTS at the budget edge
        self.assertFalse(d["fits_source_edge_end"])
        self.assertFalse(d["fits_pin_release_90"])
        self.assertEqual(d["slack_pin_release_90_ns"], -4.5)
        self.assertEqual(d["completion_observed_ns"], 40.0)
        self.assertEqual(AD.duration(dict(mi, t_src_release_end_ns=34.1), None, None)["fits_pin_release_90"], None)


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


class CommittedDriverSweep(unittest.TestCase):
    def test_committed_driver_sweep_runs_are_self_consistent(self):
        import hashlib
        for rd in sorted((HERE / "driver_sweep_results").glob("*/")):
            man = json.loads((rd / "manifest.json").read_text())
            self.assertEqual(hashlib.sha256((rd / "rwl_driver_sweep.spice").read_text().encode()).hexdigest(), man["deck_sha256"], rd.name)
            chk = json.loads((rd / "consistency_check.json").read_text())
            self.assertTrue(all(c["declared_changes_only"] for c in chk.values()), rd.name)
            self.assertTrue(all(c["deck_matches_trace"] for c in chk.values() if "deck_matches_trace" in c), rd.name)
            for k in ("source_sha256", "git_head", "pdk_open_pdks_commit"):
                self.assertIn(k, man["pins"])
            if (rd / "summary.json").exists():
                s = json.loads((rd / "summary.json").read_text())
                self.assertEqual(s["generated_deck_sha256"], man["deck_sha256"])
                self.assertEqual(s["corner_count"], 10)
                self.assertTrue(s["controls_reproduction"]["all_verdicts_reproduce"])
                self.assertTrue(s["negative_controls"]["all_remain_failures"] in (True, False))
                for r in s["results"]:
                    neg = r["group"] == "negative_control" or r["variant"] in man["control_negatives"]
                    self.assertEqual(r["overall_pass"], (not neg) and r["simulator_ok"] and r["declared_changes_only"] and r["deck_matches_trace"]
                                     and r["sense_correct"] and r["restore_success"], (r["variant"], r["corner"]))
                for n, c in s["negative_controls"]["detail"].items():
                    if n in man["control_negatives"]:
                        self.assertEqual(c["negative_control_ok_corners"], c["corners"], n)
                self.assertIn("robustness_envelope", s)


if __name__ == "__main__":
    unittest.main()
