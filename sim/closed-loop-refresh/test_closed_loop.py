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
        self.assertTrue(all(v["cycles"] >= 2 for v in G.VARIANTS))

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
            self.assertEqual(len(s["corners"]), 10, f.name)


if __name__ == "__main__":
    unittest.main()
