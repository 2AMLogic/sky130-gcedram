#!/usr/bin/env python3
"""Tests for gen_column_requests.py / reduce_column_results.py (issue #169).
Run: python3 -I sim/loaded-column/test_gen_column_requests.py

No ngspice, no klt, no network: these check that the committed decks/requests
are what the generator renders today, that the decks are relocatable (a batch
worker can read them), that the Phase 2 knob set has not drifted from the
cold-corner baseline, and that the reducer's PDK gate and derived quantities
behave.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "cold-corner"))
import gen_column_requests as G  # noqa: E402
import reduce_column_results as RED  # noqa: E402
import run_loaded_column as R  # noqa: E402
import variants as V  # noqa: E402

PIN = "f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7"


def fake_report(values: dict, *, stamp: str = f"open_pdks {PIN}", cmp_status: str = "match",
                netlist: str = "lc_fresh_sel0.spice", corner_status: str = "pass",
                diagnostics=()) -> dict:
    return {
        "netlist": {"path": f"sim/loaded-column/klt/{netlist}", "scope": "repo"},
        "status": corner_status,
        "environment": {
            "engine_version": "47",
            "remote": {
                "job_id": "klt-sim-test",
                "runner_klt_version": "0.9.0",
                "client_klt_version": "0.9.2",
                "worker_environment": {
                    "simulator": {"version_banner": "** ngspice-47 : Circuit level simulation program"},
                    "pdk": {"stamp_text": stamp, "stamp_sha256": "deadbeef"},
                    "pdk_stamp_comparison": {"status": cmp_status},
                    "engine_build_comparison": {"status": "match"},
                },
            },
        },
        "corners": [{
            "corner_id": "tt/novdd/27C", "process": "tt", "temperature_c": 27,
            "status": corner_status, "diagnostics": list(diagnostics),
            "measurements": [{"name": k, "value": v} for k, v in values.items()],
        }],
    }


class Generator(unittest.TestCase):
    def setUp(self):
        self.c_sn_f = G.c_sn_farads()

    def test_committed_decks_and_requests_are_current(self):
        for job in G.phase2_jobs():
            deck, reqp = G.job_paths(job)
            want_deck, want_req = G.render_job(job, self.c_sn_f)
            self.assertTrue(deck.is_file(), f"{deck} missing: run gen_column_requests.py")
            self.assertEqual(deck.read_text(), want_deck,
                             f"{deck.name} is stale: re-run gen_column_requests.py")
            self.assertEqual(reqp.read_text(), want_req,
                             f"{reqp.name} is stale: re-run gen_column_requests.py")

    def test_render_is_deterministic(self):
        job = G.phase2_jobs()[0]
        self.assertEqual(G.render_job(job, self.c_sn_f), G.render_job(job, self.c_sn_f))

    def test_decks_are_relocatable_and_have_no_control_block(self):
        for job in G.phase2_jobs():
            deck = G.job_paths(job)[0].read_text()
            for forbidden in (".include", ".control", ".lib", ".temp", ".end\n", "/home/",
                              "@@", "wrdata"):
                self.assertNotIn(forbidden, deck, f"{job['name']}: {forbidden!r} in deck")

    def test_design_device_cards_are_inlined_verbatim(self):
        wr, rd = G.device_cards(dict(G.BASELINE_KNOBS))
        deck = G.job_paths(G.phase2_jobs()[0])[0].read_text()
        self.assertIn(wr, deck)
        self.assertIn(rd, deck)
        # the design netlist's own hash is recorded, so a device change is visible
        self.assertIn(G.design_sha256(), deck)

    def test_phase2_knobs_match_the_cold_corner_baseline(self):
        self.assertEqual(G.BASELINE_KNOBS, V.BASELINE)

    def test_timing_reproduces_the_committed_template_at_the_baseline_pulse(self):
        P = G.params(dict(G.BASELINE_KNOBS))
        T = R.parse_params(R.TEMPLATE.read_text())
        for k in ("VDD", "VRBL", "TEDGE", "TW0", "TWSTEP", "TWPULSE", "TBL_LAG",
                  "THOLD0", "TPRE_GAP", "TREAD_PULSE", "TTAIL"):
            self.assertAlmostEqual(P[k], T[k], delta=abs(T[k]) * 1e-12,
                                   msg=f"{k} drifted from tb_loaded_column.spice.tmpl")
        self.assertAlmostEqual(G.read_time(P, "fresh"), R.FRESH_T_READ_S, places=15)
        self.assertAlmostEqual(G.read_time(P, "refresh_bound"),
                               P["TW0"] + P["TWPULSE"] + R.T_REFRESH_S, places=15)

    def test_every_pvt_point_is_covered_once_per_age_and_row(self):
        jobs = G.phase2_jobs()
        self.assertEqual(len(jobs), len(R.AGE_LABELS) * R.N_ROWS)
        for job in jobs:
            req = json.loads(G.job_paths(job)[1].read_text())
            self.assertEqual(req["corners"]["process"], R.CORNERS)
            self.assertEqual(req["corners"]["temperature_c"], R.TEMPS_C)
            self.assertNotIn("exclude", req)  # full cross product, nothing dropped
            self.assertIn(125, req["corners"]["temperature_c"])  # worst-case retention corner

    def test_measurements_are_unique_and_cover_every_pattern(self):
        req = json.loads(G.job_paths(G.phase2_jobs()[0])[1].read_text())
        names = [m["name"] for m in req["measurements"]]
        self.assertEqual(len(names), len(set(names)))
        for pattern in G.PATTERNS:
            self.assertTrue(any(n.startswith(f"{G.tag(pattern)}__") for n in names))

    def test_latency_measurement_opts_out_of_the_unreached_error(self):
        req = json.loads(G.job_paths(G.phase2_jobs()[0])[1].read_text())
        lat = [m for m in req["measurements"] if m["name"].endswith("__t_latency_abs_s")]
        self.assertEqual(len(lat), len(G.PATTERNS))
        for m in lat:
            self.assertEqual(m["on_unreached"], "null")

    def test_job_bound_stays_under_the_fleet_whole_job_ceiling(self):
        # klt warns, and the fleet kills the job, when timeout_s x units + 120 s
        # exceeds max_job_seconds (3600 s at the time of the run).
        units = len(R.CORNERS) * len(R.TEMPS_C)
        for age, timeout in G.TIMEOUT_S.items():
            self.assertLess(timeout * units + 120, 3600, f"{age} job bound too large")

    def test_selected_row_is_the_only_row_driven_to_vrwl_sel(self):
        for sel in range(R.N_ROWS):
            deck = G.deck_text(dict(G.BASELINE_KNOBS), "fresh", sel, 1e-15)
            for r in range(R.N_ROWS):
                line = next(l for l in deck.splitlines() if l.startswith(f"vrwl_{r} "))
                self.assertEqual("{VRWL_SEL}" in line, r == sel, f"sel={sel} row={r}")

    def test_an_out_of_range_selected_row_is_refused(self):
        with self.assertRaises(G.GenError):
            G.deck_text(dict(G.BASELINE_KNOBS), "fresh", 4, 1e-15)
        with self.assertRaises(G.GenError):
            G.deck_text(dict(G.BASELINE_KNOBS), "ancient", 0, 1e-15)


class ReducerGate(unittest.TestCase):
    def test_match_on_the_pin_is_accepted(self):
        prov = RED.gate(fake_report({}))
        self.assertEqual(prov["job_id"], "klt-sim-test")
        self.assertIn("ngspice-47", prov["ngspice_version"])

    def test_mismatch_is_refused(self):
        with self.assertRaises(RED.GateError):
            RED.gate(fake_report({}, cmp_status="mismatch"))

    def test_not_comparable_is_refused(self):
        with self.assertRaises(RED.GateError):
            RED.gate(fake_report({}, cmp_status="not_comparable"))

    def test_a_match_against_another_revision_is_refused(self):
        with self.assertRaises(RED.GateError):
            RED.gate(fake_report({}, stamp="open_pdks c6d73a35f524070e85faff4a6a9eef49553ebc2b"))

    def test_an_unreadable_job_name_is_refused(self):
        with self.assertRaises(RED.GateError):
            RED.job_of(fake_report({}, netlist="something_else.spice"))


class ReducerRows(unittest.TestCase):
    def values(self, pattern=1, *, latency=True):
        g = G.tag(pattern)
        P = G.params(dict(G.BASELINE_KNOBS))
        T = G.instants(P, dict(G.BASELINE_KNOBS), "fresh")
        v = {}
        for r in range(R.N_ROWS):
            v[f"{g}__v_sn_r{r}_wl_off_v"] = 0.1 * (r + 1)
            v[f"{g}__v_sn_r{r}_after_write_v"] = 0.2 * (r + 1)
            v[f"{g}__v_sn_r{r}_preread_v"] = 0.3 * (r + 1)
            v[f"{g}__v_sn_r{r}_end_v"] = 0.3 * (r + 1) + 0.01 * (r + 1)
            v[f"{g}__i_into_rbl_r{r}_preread_a"] = 1e-12 * (r + 1)
            v[f"{g}__i_into_rbl_r{r}_sense_a"] = 2e-12 * (r + 1)
        v[f"{g}__v_rbl_preread_float_v"] = 0.9
        v[f"{g}__v_rbl_sense_v"] = 0.4
        v[f"{g}__v_rbl_end_v"] = 0.3
        v[f"{g}__v_sn_sel_sense_v"] = 0.31
        if latency:
            v[f"{g}__t_latency_abs_s"] = T["t_read"] + 7.5e-10
        return v, T

    def rows(self, **kw):
        v, T = self.values(**kw)
        return RED.reduce_report_dict(fake_report(v), run_id="testrun",
                                      knobs=dict(G.BASELINE_KNOBS), c_sn_f=1e-15), T

    def test_derived_quantities(self):
        rows, T = self.rows()
        row = next(r for r in rows if r["pattern_rows3210"] == "0001")
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["sel_row"], 0)
        self.assertEqual(row["stored_value"], 1)
        # unselected rows are 1,2,3 -> preread currents 2e-12+3e-12+4e-12
        self.assertAlmostEqual(float(row["i_desel_sum_preread_a"]), 9e-12, places=18)
        self.assertAlmostEqual(float(row["i_desel_sum_sense_a"]), 18e-12, places=18)
        self.assertAlmostEqual(float(row["dv_rbl_sense_v"]), 0.4 - 0.9, places=9)
        self.assertAlmostEqual(float(row["latency_s"]), 7.5e-10, places=15)
        # selected row 0: 0.3 -> 0.31
        self.assertAlmostEqual(float(row["dv_sn_sel_read_disturb_v"]), 0.01, places=9)
        # unselected worst signed by |.| is row 3: +0.04
        self.assertAlmostEqual(float(row["dv_sn_unsel_worst_signed_v"]), 0.04, places=9)
        self.assertEqual(row["latency_reason"], "")
        self.assertEqual(row["pdk_open_pdks_commit"], PIN)

    def test_missing_latency_is_a_result_not_a_failure(self):
        rows, _ = self.rows(latency=False)
        row = next(r for r in rows if r["pattern_rows3210"] == "0001")
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["latency_s"], "")
        self.assertIn("never fell", row["latency_reason"])

    def test_a_missing_voltage_is_a_sim_failure(self):
        v, _ = self.values()
        del v[f"{G.tag(1)}__v_rbl_sense_v"]
        rows = RED.reduce_report_dict(fake_report(v), run_id="t",
                                      knobs=dict(G.BASELINE_KNOBS), c_sn_f=1e-15)
        row = next(r for r in rows if r["pattern_rows3210"] == "0001")
        self.assertEqual(row["status"], "sim_failed")
        self.assertIn("v_rbl_sense_v", row["reason"])

    def test_an_errored_corner_marks_every_pattern_failed(self):
        v, _ = self.values()
        rep = fake_report(v, corner_status="error",
                          diagnostics=[{"severity": "error", "code": "batch_job_timeout",
                                        "message": "job killed at the ceiling"}])
        rows = RED.reduce_report_dict(rep, run_id="t", knobs=dict(G.BASELINE_KNOBS),
                                      c_sn_f=1e-15)
        self.assertEqual(len(rows), len(G.PATTERNS))
        self.assertTrue(all(r["status"] == "sim_failed" for r in rows))
        self.assertTrue(all("batch_job_timeout" in r["reason"] for r in rows))

    def test_rows_use_the_committed_csv_schema_only(self):
        rows, _ = self.rows()
        for row in rows:
            self.assertEqual(set(row), set(R.FIELDS))

    def test_appending_preserves_existing_bytes(self):
        rows, _ = self.rows()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.csv"
            RED.append_result(p, R.FIELDS, rows[0])
            before = p.read_bytes()
            RED.append_result(p, R.FIELDS, rows[1])
            self.assertTrue(p.read_bytes().startswith(before))


if __name__ == "__main__":
    unittest.main(verbosity=2)
