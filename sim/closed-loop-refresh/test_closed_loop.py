#!/usr/bin/env python3
"""Stdlib-only checks for sim/closed-loop-refresh/ (issue #147). No ngspice, PDK or klt.

Run: python3 -I sim/closed-loop-refresh/test_closed_loop.py
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
import analyze_closed_loop as A  # noqa: E402
import gen_closed_loop as G  # noqa: E402

WAVES = G.trace_waves()


def synthetic_corner(v: dict, *, wrong_read: dict | None = None, no_restore: set | None = None,
                     decay_per_cycle: float = 0.0) -> dict:
    """klt-style corner. wrong_read: {(case,row): first wrong cycle}; no_restore: {kind} whose post level is not restored."""
    meas = []
    for p in G.instances(v):
        n = p["name"]
        for r in range(G.N_ROWS):
            d = p["data"][r]
            wr = 1.4 if d else 0.0
            meas.append({"name": f"wr_{n}_r{r}", "value": wr})
            bad_from = (wrong_read or {}).get((n, r))
            for c in range(1, v["cycles"] + 1):
                wrong = bad_from is not None and c >= bad_from
                bit = (1 - d) if wrong else d
                post = (1.45 if bit else -0.01)
                if p["kind"] in (no_restore or set()):
                    post = 0.9 if bit else 0.0
                pre = (1.2 - decay_per_cycle * c) if bit else 0.0
                meas += [{"name": f"pre_{n}_r{r}_c{c}", "value": pre},
                         {"name": f"dec_{n}_r{r}_c{c}", "value": -1.7 if bit else 1.7},
                         {"name": f"post_{n}_r{r}_c{c}", "value": post}]
    return {"process": "tt", "temperature_c": 125, "status": "pass", "measurements": meas}


class Generated(unittest.TestCase):
    def test_committed_files_not_stale(self):
        for v in G.VARIANTS:
            net, req = G.render(v, WAVES)
            np_, rp = G.paths(v)
            self.assertEqual(net, np_.read_text(), f"run gen_closed_loop.py ({v['name']})")
            self.assertEqual(req, rp.read_text(), f"run gen_closed_loop.py ({v['name']})")

    def test_scope_is_exactly_the_proposed_restricted_range(self):
        for v in G.VARIANTS:
            r = json.loads(G.paths(v)[1].read_text())
            if v.get("diagnostic"):
                # issue #373 diagnostic: the one recorded failing corner only
                self.assertEqual(r["corners"]["process"], ["sf"])
                self.assertEqual(r["corners"]["temperature_c"], [125])
            else:
                self.assertEqual(r["corners"]["process"], ["tt", "ss", "ff", "sf", "fs"])
                self.assertEqual(r["corners"]["temperature_c"], [27, 125])
            self.assertNotIn("monte_carlo", r)
        self.assertEqual(G.VDD_V, 1.8)

    def test_body_has_no_control_or_end_and_lowercase_names(self):
        for v in G.VARIANTS:
            for line in G.paths(v)[0].read_text().splitlines():
                self.assertFalse(line.lower().startswith((".control", ".end")), line)
            r = json.loads(G.paths(v)[1].read_text())
            self.assertTrue(all(m["name"] == m["name"].lower() for m in r["measurements"]))
            names = [m["name"] for m in r["measurements"]]
            self.assertEqual(len(names), len(set(names)))

    def test_ratified_interval_is_read_only_and_one_variant_is_exactly_it(self):
        self.assertEqual(G.REFRESH_BOUND_S, 5.03e-6)
        self.assertEqual(G.variant("d5030")["dwell_ns"] * 1e-9, G.REFRESH_BOUND_S)
        d = [x["dwell_ns"] for x in G.VARIANTS if x["name"] in ("d2500", "d5030", "d8000")]
        self.assertTrue(d[0] < 5030 < d[2], "shorter and longer dwell must bracket the ratified interval")
        self.assertGreater(G.variant("d60000")["dwell_ns"], 5030 * 10)
        self.assertTrue(all(v["cycles"] >= 2 for v in G.VARIANTS if not v.get("diagnostic")))
        # the paired diagnostic sits exactly on the ratified interval and covers its first read only
        self.assertEqual(G.variant("d5030nbr")["dwell_ns"] * 1e-9, G.REFRESH_BOUND_S)
        self.assertEqual(G.variant("d5030nbr")["cycles"], 1)

    def test_no_state_reset_between_cycles(self):
        """.ic lines appear once per node (t = 0 only) and no ideal source drives a storage node after the initial write."""
        v = G.variant("d5030")
        net = G.paths(v)[0].read_text()
        ics = [t for ln in net.splitlines() if ln.startswith(".ic ") for t in ln.split()[1:]]
        self.assertEqual(len(ics), len(set(ics)))
        for ln in net.splitlines():
            if ln.startswith("v") and not ln.startswith(("vdd", "vprea", "vpref", "vrwld")):
                self.assertNotRegex(ln.split()[1], r"^sn_", "no source may drive a storage node")
        self.assertIn("uic", json.loads(G.paths(v)[1].read_text())["analysis"]["args"])

    def test_cells_start_at_opposite_of_data_and_are_written_through_access_device(self):
        net = G.paths(G.variant("d5030"))[0].read_text()
        self.assertRegex(net, r"v\(sn_ana_1010_0\)=0\b")
        self.assertRegex(net, r"v\(sn_ana_1010_1\)=1\.8\b")
        self.assertRegex(net, r"XMWR_ana_1010_0 sn_ana_1010_0 wl0_ana wbl_ana_1010 0 ")

    def test_refresh_schedule_interval_and_no_overlap(self):
        for v in G.VARIANTS:
            sel = {(n, k): s for n, k, s in G.ops(v)}
            for k in range(G.N_ROWS):
                self.assertAlmostEqual(sel[(1, k)] - G.wl_fall_ns(k), v["dwell_ns"], places=6)
                for n in range(1, v["cycles"]):
                    self.assertAlmostEqual(sel[(n + 1, k)] - sel[(n, k)], v["dwell_ns"], places=6)
            times = sorted(sel.values())
            self.assertTrue(all(b - a >= G.SLOT_NS - 1e-9 for a, b in zip(times, times[1:])))
            for wf in WAVES:
                self.assertLess(G.op_shape(WAVES[wf]["nodes"])["end"], G.SLOT_NS, wf)

    def test_pwl_is_strictly_increasing_and_resolves_edges(self):
        for v in G.VARIANTS:
            net = G.paths(v)[0].read_text()
            for ln in net.splitlines():
                m = re.match(r"v\S+ \S+ 0 pwl\((.*)\)", ln)
                if not m:
                    continue
                ts = [float(x) for x in m.group(1).split()[0::2]]
                self.assertTrue(all(b > a for a, b in zip(ts, ts[1:])), ln[:60])

    def test_nowb_has_only_initial_write_pulses_and_waveforms_trace_back_to_committed_sources(self):
        net = G.paths(G.variant("d5030"))[0].read_text()
        n_ana = len(re.search(r"^vwl0_ana \S+ 0 pwl\((.*)\)", net, re.M).group(1).split()) // 2
        n_nowb = len(re.search(r"^vwl0_nowb \S+ 0 pwl\((.*)\)", net, re.M).group(1).split()) // 2
        self.assertEqual(n_nowb, 5)   # 0 V start + one initial write pulse (4 more points)
        self.assertGreater(n_ana, n_nowb + 4 * 10 - 1)
        self.assertEqual(G.WAVEFORMS["rtl"][0], "rtl_hold")   # unchanged committed RTL trace + latch-hold adapter
        self.assertTrue(G.TRACE_PATH.exists())

    def test_late_waveform_differs_from_rtl_only_in_rwl_release(self):
        a, b = WAVES["rtl"]["nodes"], WAVES["late"]["nodes"]
        self.assertEqual({k: x for k, x in a.items() if k != "rwls"}, {k: x for k, x in b.items() if k != "rwls"})
        self.assertNotEqual(a["rwls"], b["rwls"])


class Analyzer(unittest.TestCase):
    V = G.variant("d5030")

    def reduce(self, **kw):
        rows, s = A.reduce_corner(synthetic_corner(self.V, **kw), self.V)
        return rows, s

    def test_healthy_run_has_no_failures(self):
        rows, s = self.reduce()
        for kind in ("main", "control_rtl_unchanged", "experimental_unapproved"):
            self.assertTrue(s["by_kind"][kind]["all_reads_correct"], kind)
            self.assertTrue(s["by_kind"][kind]["all_restored_095"], kind)
        self.assertEqual(len(rows), sum(len(G.instances(self.V)) for _ in [0]) * G.N_ROWS * self.V["cycles"])

    def test_first_failure_cycle_is_the_first_wrong_read_even_if_later_cycles_converge(self):
        key = ("ana_1111", 2)
        rows, s = self.reduce(wrong_read={key: 4})
        m = s["by_kind"]["main"]
        self.assertEqual(m["first_failure_cycle_by_row"], {"ana_1111_r2": 4})
        self.assertFalse(m["all_reads_correct"])
        # every cycle from 4 on stays a failure: the wrong value being rewritten does not turn it into a pass
        bad = [r["cycle"] for r in rows if r["case"] == "ana_1111" and r["row"] == 2 and not r["correct"]]
        self.assertEqual(bad, list(range(4, self.V["cycles"] + 1)))

    def test_unrestored_waveform_is_detected_even_when_reads_are_correct(self):
        _, s = self.reduce(no_restore={"control_missing_writeback"})
        b = s["by_kind"]["control_missing_writeback"]
        self.assertTrue(b["all_reads_correct"])
        self.assertTrue(b["failures_detected"])
        self.assertEqual(set(b["first_unrestored_cycle_by_row"].values()), {1})
        self.assertTrue(A.verdicts([s], self.V)["missing_writeback_control_detected_all_corners"])

    def test_missing_writeback_control_not_detected_when_everything_looks_healthy(self):
        _, s = self.reduce()
        self.assertFalse(A.verdicts([s], self.V)["missing_writeback_control_detected_all_corners"])

    def test_restore_fraction_is_reported_with_voltage_and_sense(self):
        rows, _ = self.reduce()
        r = next(x for x in rows if x["case"] == "ana_1111" and x["row"] == 0 and x["cycle"] == 1)
        self.assertAlmostEqual(r["restore_fraction_vs_written"], 1.45 / 1.4)
        self.assertAlmostEqual(r["restore_fraction"], 1.45 / A.REFS[("tt", 125)])
        self.assertIn(("sf", 125), A.REFS)
        self.assertEqual(len(A.REFS), 10)
        for k in ("post_refresh_v", "pre_read_v", "dec_v", "decision", "correct", "written_v"):
            self.assertIn(k, r)
        z = next(x for x in rows if x["case"] == "ana_0000" and x["cycle"] == 1)
        self.assertTrue(z["restored_095"])

    def test_missing_measurement_is_a_failure_not_a_pass(self):
        c = synthetic_corner(self.V)
        c["measurements"] = [m for m in c["measurements"] if not m["name"].startswith("dec_ana_1111_r0_c3")]
        _, s = A.reduce_corner(c, self.V)
        self.assertFalse(s["by_kind"]["main"]["all_reads_correct"])
        self.assertEqual(s["by_kind"]["main"]["first_failure_cycle_by_row"]["ana_1111_r0"], 3)

    def test_excessive_dwell_verdict(self):
        v = G.variant("d60000")
        ok, s_ok = A.reduce_corner(synthetic_corner(v), v)
        self.assertFalse(A.verdicts([s_ok], v)["excessive_dwell_detected_any_corner"])
        _, s_bad = A.reduce_corner(synthetic_corner(v, wrong_read={("ana_1111", 0): 1}), v)
        self.assertTrue(A.verdicts([s_bad], v)["excessive_dwell_detected_any_corner"])

    def test_refuses_to_overwrite_and_writes_csv_and_summary(self):
        v = self.V
        corners = [dict(synthetic_corner(v), process=p, temperature_c=t) for p in G.PROCESS_CORNERS for t in G.TEMPS_C]
        rep = {"status": "pass", "errored": 0, "corner_count": 10, "corners": corners,
               "environment": {"netlist_sha256": "x", "models_lib_sha256": "y", "engine_version": "47", "remote": {}}}
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "klt_report_d5030_RUN.json"
            f.write_text(json.dumps(rep))
            self.assertEqual(A.main(["d5030", str(f)]), 0)
            s = json.loads((Path(d) / "closed_loop_summary_d5030_RUN.json").read_text())
            self.assertFalse(s["claims"]["indefinite_stability_claimed"])
            self.assertTrue(s["verdicts"]["main_all_reads_correct_all_corners"])
            with (Path(d) / "closed_loop_points_d5030_RUN.csv").open() as fh:
                self.assertEqual(len(list(csv.DictReader(fh))), 10 * len(G.instances(v)) * 4 * v["cycles"])
            self.assertEqual(A.main(["d5030", str(f)]), 2)


class Committed(unittest.TestCase):
    """Committed summaries (if any) are internally consistent and make no forbidden claim."""

    def test_committed_summaries(self):
        for f in sorted((HERE / "results").glob("closed_loop_summary_*.json")):
            s = json.loads(f.read_text())
            self.assertFalse(any(s["claims"][k] for k in ("full_macro_or_yield_claim", "spec_changed",
                                                           "refresh_bound_signed_off", "indefinite_stability_claimed")), f.name)
            self.assertEqual(len(s["corners"]), 1 if s.get("paired") else 10, f.name)


NETLIST_DIAG = G.paths(G.variant("d5030nbr"))[0].read_text()


class DiagnosticDeck(unittest.TestCase):
    """The issue-#373 paired diagnostic deck: arms differ by the clamp only; history preserved."""

    V = G.variant("d5030nbr")

    def test_two_paired_instances(self):
        pts = G.instances(self.V)
        self.assertEqual([(p["name"], p["kind"], p["wf"]) for p in pts],
                         [("ana_1111", "main", "ana"), ("anb_1111", G.KIND_DIAG, G.DIAG_WF)])
        self.assertEqual([p["data"] for p in pts], [[1, 1, 1, 1]] * 2)
        # the paired arm's waveform trace source is ana's: identical RWL/latch/write-back by construction
        self.assertEqual(G.WAVEFORMS[G.DIAG_WF], G.WAVEFORMS["ana"])

    def test_shared_control_waveforms_identical_between_arms(self):
        """RWL, latch-enable, write-back and precharge PWL point lists are identical for ana and anb."""
        comp = {wf: G._composite(self.V, wf, WAVES) for wf in ("ana", G.DIAG_WF)}
        for key in ("ctl", "en", "wbc"):
            self.assertEqual(comp["ana"][key], comp[G.DIAG_WF][key], key)
        for k in range(G.N_ROWS):
            self.assertEqual(comp["ana"][f"rwls{k}"], comp[G.DIAG_WF][f"rwls{k}"], f"rwls{k}")
            self.assertEqual(comp["ana"][f"wwl{k}"], comp[G.DIAG_WF][f"wwl{k}"], f"wwl{k}")

    def test_circuit_diff_is_clamp_and_ammeters_only(self):
        """Every ana_1111 card has an anb_1111 name-substituted counterpart, and the only extra anb cards
        are the clamp block; the extra shared cards are the 0 V ammeters present in BOTH arms."""
        lines = NETLIST_DIAG.splitlines()
        body = [l for l in lines if not l.startswith("*") and not l.startswith(".ic ")]
        lset = set(body)
        ana = [l for l in body if "ana_1111" in l]
        anb = [l for l in body if "anb_1111" in l]
        # arms differ by name substitution only (instance names AND the per-waveform control-node suffix);
        # the clamp switch cards additionally reference the clamped neighbours' SN nodes
        shared_anb = [l for l in anb if l.replace("_anb", "_ana") in lset]
        self.assertEqual(sorted(l.replace("_ana", "_anb") for l in ana), sorted(shared_anb))
        self.assertEqual(sorted(l.replace("_anb", "_ana") for l in shared_anb), sorted(ana))
        clamp_x = [l for l in anb if l.replace("_anb", "_ana") not in lset]
        self.assertEqual(len(clamp_x), 2)   # the two clamp switch cards (the only clamp cards naming instances)
        self.assertTrue(all(l.startswith("swc_") for l in clamp_x))
        clamp_aux = [l for l in body if l.startswith(("vclmp_", "vclp_", ".model swclamp"))]
        self.assertEqual(len(clamp_aux), 3)   # ideal clamp source, control PWL, switch model
        self.assertEqual([l for l in body if l.startswith(".model swclamp")],
                         [".model swclamp sw(vt=0.5 vh=0.1 ron=1 roff=1e12)"])
        # the victim's storage node is never clamped (clamp rows are 0 and 1 only)
        self.assertFalse(any("sn_anb_1111_2" in l and l.startswith("swc_") for l in lines))
        ics = [l for l in lines if l.startswith(".ic ")]
        tok = lambda arm: sorted(t for l in ics for t in l.split()[1:] if f"{arm}_1111" in t)
        self.assertEqual(len(tok("ana")), 9)
        self.assertEqual([t.replace("_ana", "_anb") for t in tok("ana")], tok("anb"))
        # both arms carry the same 8 ammeters; the baseline d5030 deck has neither ammeters nor clamp
        self.assertEqual(len([l for l in lines if l.startswith("vmeas")]), 8)
        for wf in ("ana", "anb"):
            for k in range(G.N_ROWS):
                drv = next(l for l in lines if l.startswith(f"vrws{k}_{wf} "))
                self.assertTrue(drv.startswith(f"vrws{k}_{wf} rwlsrc{k}_{wf} 0 pwl("))
        main_net = G.paths(G.variant("d5030"))[0].read_text()
        self.assertNotIn("vmeas", main_net)
        self.assertNotIn("swclamp", main_net)

    def test_clamp_window_preserves_history(self):
        """Clamp opens after row 1's op end + its post-refresh probe, settles before the victim's pre-read
        probe, closes at the victim's op end, and never touches row 3's op."""
        v = self.V
        d = v
        sh = G.op_shape(WAVES["ana"]["nodes"])
        waves = WAVES
        on, off, done = G.clamp_window_ns(v, waves)
        o_prev = G.select_ns(v, d["victim_row"] - 1, 1) - sh["sel"]
        self.assertGreaterEqual(on, o_prev + sh["last"] + G.T_MEAS_NS)     # history through row 1's write-back + probe
        vr_pre = G.probe_times(v, "ana", d["victim_row"], 1, waves)["pre"]
        self.assertLessEqual(on + d["ramp_ns"], vr_pre)                    # settled before the victim pre-read probe
        vr_sel, vr_en = G.sense_window_ns(v, "ana", d["victim_row"], 1, waves)
        self.assertLessEqual(on + d["ramp_ns"], vr_sel)                    # and before the victim select edge
        self.assertGreaterEqual(off, vr_en)                                # held through the victim's sensing
        o3 = G.select_ns(v, 3, 1) - sh["sel"]
        self.assertLessEqual(done, o3 + 2.0)                               # released before row 3's precharge drops
        pwl = next(l for l in NETLIST_DIAG.splitlines() if l.startswith(f"vclp_{G.DIAG_WF} "))
        for t in (on, on + d["ramp_ns"], off, done):
            self.assertIn(f"{t * 1e-9:.12g}", pwl)

    def test_request_probes_both_arms_equally(self):
        r = json.loads(G.paths(self.V)[1].read_text())
        names = [m["name"] for m in r["measurements"]]
        for stem in ("iavg", "imax", "imin", "ien", "npre", "rblsel", "rblen", "rblavg", "refen", "refavg", "den"):
            self.assertEqual(len([n for n in names if n.startswith(f"{stem}_ana_1111")]),
                             len([n for n in names if n.startswith(f"{stem}_anb_1111")]), stem)
        # the decision is read at the existing pre-write-back sample for both arms
        for arm in ("ana_1111", "anb_1111"):
            self.assertIn(f"dec_{arm}_r2_c1", names)
            self.assertIn(f"pre_{arm}_r2_c1", names)


def diag_measurements(v: dict, *, row2_clamped_dec: float | None, clamp_level: float = 1.36,
                      neighbour_i_a: float = 2.5e-6, victim_dec: float = 1.72257,
                      unclamped_shift_v: float = 0.0) -> list[dict]:
    """Synthetic instrumented measurements for the paired deck. Baseline arm always reproduces the
    recorded cycle-1 failure; the clamp arm's row-2 decision (and injection current) is the intervention.
    unclamped_shift_v moves the clamp arm's UNCLAMPED nodes (victim pre-read, row-3 npre) the way the real
    run shows the floating-RBL coupling does; 0.0 keeps both arms symmetric as the fixtures above assume."""
    meas = []
    for p in G.instances(v):
        n, clamped = p["name"], p["wf"] == G.DIAG_WF
        s = unclamped_shift_v if clamped else 0.0
        for r in range(G.N_ROWS):
            meas.append({"name": f"wr_{n}_r{r}", "value": 1.4})
        dec2 = (row2_clamped_dec if clamped and row2_clamped_dec is not None else victim_dec)
        meas += [
            {"name": f"pre_{n}_r2_c1", "value": 0.969999 + s}, {"name": f"dec_{n}_r2_c1", "value": dec2},
            {"name": f"post_{n}_r2_c1", "value": 1.45 if dec2 < 0 else -0.06},
        ]
        for r in (0, 1):
            meas += [{"name": f"pre_{n}_r{r}_c1", "value": 0.96}, {"name": f"dec_{n}_r{r}_c1", "value": -1.61829},
                     {"name": f"post_{n}_r{r}_c1", "value": 1.45}]
            lvl = clamp_level if clamped else (1.63393 if r == 0 else 1.61575)
            meas.append({"name": f"npre_{n}_r{r}", "value": lvl})
        meas.append({"name": f"pre_{n}_r3_c1", "value": 0.96})
        meas.append({"name": f"dec_{n}_r3_c1", "value": 1.72})
        meas.append({"name": f"post_{n}_r3_c1", "value": 1.45})
        meas.append({"name": f"npre_{n}_r3", "value": 0.9686 + s})
        for r in range(G.N_ROWS):
            mag = 1e-12 if (clamped and r in v["clamp_rows"]) else neighbour_i_a
            i = -mag if r == 2 else mag   # victim's RWL rail sinks its read discharge; neighbours inject
            meas += [{"name": f"iavg_{n}_r{r}", "value": i}, {"name": f"imax_{n}_r{r}", "value": i * 2},
                     {"name": f"imin_{n}_r{r}", "value": i / 2}, {"name": f"ien_{n}_r{r}", "value": i}]
        meas += [{"name": f"rblsel_{n}", "value": 0.9}, {"name": f"rblen_{n}", "value": 0.1 if dec2 < 0 else 0.89},
                 {"name": f"rblavg_{n}", "value": 0.5}, {"name": f"refen_{n}", "value": 0.8},
                 {"name": f"refavg_{n}", "value": 0.8}, {"name": f"den_{n}", "value": dec2}]
    return meas


class DiagnosticAnalyzer(unittest.TestCase):
    """The paired reduction: verdicts on synthetic reports, refutation included, preconditions enforced."""

    V = G.variant("d5030nbr")

    def paired(self, **kw) -> dict:
        corner = {"process": "sf", "temperature_c": 125, "status": "pass",
                  "measurements": diag_measurements(self.V, **kw)}
        rows, s = A.reduce_corner(corner, self.V)
        s["paired"] = A.paired_block(corner, self.V)
        return s["paired"]

    def test_supported_when_clamp_flips_the_decision(self):
        p = self.paired(row2_clamped_dec=-1.7)
        self.assertTrue(p["clean_comparison"])
        self.assertEqual(p["verdict"], "supported")
        self.assertTrue(p["decision_changed_by_clamp"])
        self.assertTrue(p["clamped_victim_correct"])
        self.assertAlmostEqual(p["neighbour_current_change_avg_a"][0], 1e-12 - 2.5e-6)
        self.assertAlmostEqual(p["d_at_enable_change_v"], -1.7 - 1.72257)
        # the instrumented baseline reproduces the recorded numbers it is paired against
        self.assertAlmostEqual(p["baseline"]["rows"][2]["dec_v"], A.RECORDED["row2"]["dec_v"], places=6)
        self.assertAlmostEqual(p["baseline"]["rows"][1]["dec_v"], A.RECORDED["row1"]["dec_v"], places=6)

    def test_refuted_when_clamp_leaves_the_decision(self):
        p = self.paired(row2_clamped_dec=1.72257)
        self.assertTrue(p["clean_comparison"])
        self.assertEqual(p["verdict"], "refuted")
        self.assertFalse(p["decision_changed_by_clamp"])

    def test_partial_when_clamp_changes_the_decision_but_not_to_correct(self):
        p = self.paired(row2_clamped_dec=0.2)   # unresolved band, no longer a clean '0' read
        self.assertTrue(p["clean_comparison"])
        self.assertTrue(p["decision_changed_by_clamp"])
        self.assertFalse(p["clamped_victim_correct"])
        self.assertEqual(p["verdict"], "partial")

    def test_inconclusive_when_the_clamp_misses_its_level(self):
        p = self.paired(row2_clamped_dec=-1.7, clamp_level=1.615)   # clamp did not take effect
        self.assertFalse(p["clean_comparison"])
        self.assertEqual(p["verdict"], "inconclusive")
        self.assertTrue(any("clamp did not hold" in x for x in p["limitations"]))

    def test_inconclusive_when_baseline_does_not_reproduce_the_record(self):
        corner = {"process": "sf", "temperature_c": 125, "status": "pass",
                  "measurements": diag_measurements(self.V, row2_clamped_dec=-1.7)}
        for m in corner["measurements"]:
            if m["name"] == "dec_ana_1111_r1_c1":
                m["value"] = 1.7          # the control row 1 wrongly fails in the baseline arm
        _, s = A.reduce_corner(corner, self.V)
        s["paired"] = A.paired_block(corner, self.V)
        p = s["paired"]
        self.assertEqual(p["verdict"], "inconclusive")
        self.assertTrue(any("baseline" in x for x in p["limitations"]))
        self.assertEqual(A.verdicts([s], self.V)["diagnostic_paired_verdict"], "inconclusive")

    def test_unclamped_node_shift_is_disclosed_not_silent(self):
        # The real run's floating-RBL coupling: the clamp arm's victim pre-read and row-3 npre sit lower.
        p = self.paired(row2_clamped_dec=-1.7, unclamped_shift_v=-0.0175)
        self.assertTrue(p["clean_comparison"])   # the four preconditions do not look at these nodes
        self.assertEqual(p["verdict"], "supported")   # the conservative direction keeps the verdict
        self.assertAlmostEqual(p["unclamped_node_change_v"]["victim_pre_read"], -0.0175, places=9)
        self.assertAlmostEqual(p["unclamped_node_change_v"]["neighbour_r3_pre_select"], -0.0175, places=9)
        limitation = next(x for x in p["limitations"] if "unclamped_node_change_v" in x)
        self.assertIn("victim_pre_read", limitation)
        self.assertIn("conservative", limitation)   # the direction argument is part of the record

    def test_symmetric_arms_report_no_limitation(self):
        p = self.paired(row2_clamped_dec=-1.7)   # fixtures hand both arms identical unclamped levels
        self.assertEqual(p["limitations"], [])
        self.assertEqual(p["unclamped_node_change_v"]["victim_pre_read"], 0.0)
        self.assertEqual(p["unclamped_node_change_v"]["neighbour_r3_pre_select"], 0.0)


if __name__ == "__main__":
    unittest.main()
