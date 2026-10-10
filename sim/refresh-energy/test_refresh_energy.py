#!/usr/bin/env python3
"""Stdlib-only checks for sim/refresh-energy/ (issue #115). No ngspice, PDK or klt.

Run: python3 -I sim/refresh-energy/test_refresh_energy.py
"""
from __future__ import annotations

import copy
import csv
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analyze_refresh_energy as A  # noqa: E402
import gen_refresh_energy as G  # noqa: E402

RESULTS = HERE / "results"


def main_reports() -> list[Path]:
    return sorted(p for p in RESULTS.glob("klt_report_*.json*") if not p.name.startswith("klt_report_fine_"))


# ---------------------------------------------------------------------------
# synthetic report (analytic fixture for the reduction controls)
# ---------------------------------------------------------------------------
def synth_corner(process="tt", temp=27, e_pwl=1e-13, e_idle_dc=1e-20, sn1_end=1.30, rbs1=0.2, rbs0=0.88):
    """A self-consistent corner: DC sources obey E = -V*Q, PWL sources net = gross - rec."""
    m = {f"snref_{c}": 1.35 for c in range(G.N_COLS)}
    for inst in G.instances():
        n = inst["name"]
        if not inst["energy"]:
            continue
        for stem, _role, _i in G.source_roles():
            s = G.src_name(stem, n)
            if G.is_dc(inst, stem):
                v = G.dc_value(inst, stem)
                q = -e_idle_dc / v if v else 1e-16     # 0 V sources: charge but no energy
                net = -v * q
                m.update({f"en_{s}": net, f"eg_{s}": max(net, 0.0), f"er_{s}": max(-net, 0.0), f"q_{s}": q})
            else:
                gross, rec = 1.5 * e_pwl, 0.5 * e_pwl
                m.update({f"en_{s}": gross - rec, f"eg_{s}": gross, f"er_{s}": rec, f"q_{s}": -1e-15})
        for r in range(G.N_ROWS):
            for c in range(G.N_COLS):
                b = G.bit(inst, r, c)
                v0 = G.V_SN1_V if b else G.V_SN0_V
                m[f"sna_{n}_{r}{c}"] = v0
                end = v0
                if inst["mode"] == "active" and r == G.SEL_ROW:
                    end = sn1_end if b else 0.02
                m[f"snb_{n}_{r}{c}"] = end
        if inst["mode"] in ("active", "nop"):
            for c in range(G.N_COLS):
                b = G.PATTERNS[inst["pattern"]][G.SEL_ROW][c]
                active = inst["mode"] == "active"
                m[f"rbs_{n}_{c}"] = (rbs1 if b else rbs0) if active else G.VRBL_V
                m[f"snr_{n}_{c}"] = G.V_SN1_V if b else G.V_SN0_V
    return dict(process=process, temperature_c=temp, status="pass", corner_id=f"{process}/{temp}C",
                measurements=[dict(name=k, value=v) for k, v in m.items()])


def synth_report(**kw) -> dict:
    return dict(status="pass", errored=0, corner_count=10,
                corners=[synth_corner(p, t, **kw) for p in G.PROCESS_CORNERS for t in G.TEMPS_C])


def set_meas(corner: dict, name: str, value) -> None:
    for x in corner["measurements"]:
        if x["name"] == name:
            x["value"] = value
            return
    raise KeyError(name)


def get_meas(corner: dict, name: str):
    return next(x["value"] for x in corner["measurements"] if x["name"] == name)


C_SN = 0.605354e-15


# ---------------------------------------------------------------------------
class Generated(unittest.TestCase):
    def test_committed_files_not_stale(self):
        net, req, req_fine = G.render()
        self.assertEqual(net, G.NETLIST_PATH.read_text(), "run gen_refresh_energy.py")
        self.assertEqual(req, G.REQUEST_PATH.read_text(), "run gen_refresh_energy.py")
        self.assertEqual(req_fine, G.REQUEST_FINE_PATH.read_text(), "run gen_refresh_energy.py")

    def test_scope_is_exactly_the_ten_point_grid(self):
        for p in (G.REQUEST_PATH, G.REQUEST_FINE_PATH):
            r = json.loads(p.read_text())
            self.assertEqual(r["corners"]["process"], ["tt", "ss", "ff", "sf", "fs"])
            self.assertEqual(r["corners"]["temperature_c"], [27, 125])
            self.assertNotIn("supply_v", r["corners"])
            self.assertNotIn("monte_carlo", r)
            self.assertEqual(r["backend"], "batch")
            self.assertEqual(r["netlist"], "refresh_energy.spice")
        self.assertEqual(G.VDD_V, 1.8)

    def test_fine_request_differs_only_in_max_step(self):
        a, b = json.loads(G.REQUEST_PATH.read_text()), json.loads(G.REQUEST_FINE_PATH.read_text())
        ta, tb = a.pop("analysis")["args"].split(), b.pop("analysis")["args"].split()
        self.assertEqual(a, b)
        self.assertEqual(ta[:3] + ta[4:], tb[:3] + tb[4:])
        self.assertEqual((ta[3], tb[3]), ("20p", "5p"))
        self.assertLess(G.TRAN_MAX_FINE_S, G.TRAN_MAX_S)

    def test_body_has_no_control_end_include_or_lib(self):
        for line in G.NETLIST_PATH.read_text().splitlines():
            self.assertFalse(line.lower().startswith((".control", ".end", ".include", ".lib")), line)

    def test_extracted_array_reemitted_per_instance(self):
        arr = G.WD.parse_array(G.ARRAY_NETLIST)
        net = G.NETLIST_PATH.read_text().splitlines()
        for inst in G.instances():
            n = inst["name"]
            mos = [ln for ln in net if ln.startswith("xm") and ln.split()[0].endswith("_" + n)]
            self.assertEqual(len(mos), 32)
            self.assertTrue(all("sky130_fd_pr__nfet_01v8" in ln for ln in mos))
            caps = {ln.split()[0]: float(ln.split()[3]) for ln in net if ln.startswith("c") and ln.split()[0].endswith("_" + n)}
            self.assertEqual(len(caps), len(arr["cap"]))
            for nm, _a, _b, f in arr["cap"]:
                self.assertAlmostEqual(caps[f"{nm.lower()}_{n}"], f, delta=1e-6 * f)
            res = [ln for ln in net if ln.startswith("r") and ln.split()[0].endswith("_" + n)]
            self.assertEqual(len(res), len(arr["res"]) - 1)        # Rvsubs_dctie replaced by vsub

    def test_instances_isolated(self):
        self.assertEqual(A.check_isolation(G.NETLIST_PATH.read_text()), [])

    def test_isolation_negative_control_detects_bridging(self):
        bad = G.NETLIST_PATH.read_text() + "\nrbridge_act_z rbl_0_act_z rbl_0_idl_z 1\nvshared_act_o bl_0_act_o bl_0_act_c dc 0\n"
        found = A.check_isolation(bad)
        self.assertEqual(len(found), 2)

    def test_every_boundary_source_present_and_measured(self):
        net = G.NETLIST_PATH.read_text()
        r = json.loads(G.REQUEST_PATH.read_text())
        names = [m["name"] for m in r["measurements"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(x == x.lower() for x in names))
        meas = set(names)
        roles = G.source_roles()
        self.assertEqual(len(roles), 4 + 4 + 4 + 4 + 2)
        for inst in G.instances():
            for stem, _r, _i in roles:
                s = G.src_name(stem, inst["name"])
                self.assertIn(f"\n{s} {G.src_pos_node(stem, inst['name'])} 0 ", net)
                for k in ("en", "eg", "er", "q"):
                    self.assertEqual(f"{k}_{s}" in meas, inst["energy"], f"{k}_{s}")

    def test_windows_and_phases_follow_110(self):
        t = G.T
        self.assertAlmostEqual(t["t_start"], 5e-9)
        self.assertAlmostEqual(t["t_pre_off"] - t["t_start"], G.G.T_PRE_ON_S)
        self.assertAlmostEqual(t["t_sel"] - t["t_pre_off"], G.G.T_PRE_GAP_S)
        self.assertAlmostEqual(t["t_en"] - t["t_sel"], 10e-9)
        self.assertAlmostEqual(t["t_on"] - t["t_en"], G.G.T_LATCH_S)
        self.assertAlmostEqual(t["t_off"] - t["t_on"], 10e-9)
        self.assertAlmostEqual(t["t_rel"] - t["t_off"], G.G.T_GUARD_S)
        self.assertAlmostEqual(t["t_end"] - t["t_rel"], G.G.T_MEAS_S)
        self.assertAlmostEqual(G.T_END_S, 34e-9)
        self.assertAlmostEqual(G.t_row_refresh_op_s(), 27e-9)
        self.assertGreater(G.T_STOP_S, G.T_REF["t_end"])
        r = json.loads(G.REQUEST_PATH.read_text())
        for m in r["measurements"]:
            if m["name"].startswith(("en_", "eg_", "er_", "q_")):
                self.assertIn("FROM=5n TO=34n", m["spice"])

    def test_patterns_explicit_and_complementary(self):
        P = G.PATTERNS
        self.assertEqual(set(P), {"zero", "one", "checker", "inv_checker"})
        for r in range(4):
            for c in range(4):
                self.assertEqual(P["zero"][r][c], 0)
                self.assertEqual(P["one"][r][c], 1)
                self.assertEqual(P["checker"][r][c] + P["inv_checker"][r][c], 1)
                if c:
                    self.assertNotEqual(P["checker"][r][c], P["checker"][r][c - 1])
        self.assertEqual(P["checker"][0], [1, 0, 1, 0])

    def test_writeback_drives_stored_bit_and_idle_has_no_pulses(self):
        for inst in G.instances():
            for stem, _r, _i in G.source_roles():
                d = G.drive(inst, stem)
                if inst["mode"] in ("idle", "nop"):
                    self.assertTrue(d.startswith("dc "), (inst["name"], stem))
                if inst["mode"] == "active" and stem.startswith("vwbl"):
                    b = G.PATTERNS[inst["pattern"]][G.SEL_ROW][int(stem[4:])]
                    self.assertEqual(d.startswith("pwl"), b == 1)
            if inst["mode"] in ("idle", "nop"):
                self.assertTrue(G.ctl_drive(inst).startswith("dc "))
        idl = {i["name"]: i for i in G.instances()}
        for stem, _r, _i in G.source_roles():
            self.assertEqual(G.drive(idl["nop_c"], stem), G.drive(idl["idl_c"], stem))


class Calculation(unittest.TestCase):
    """Analytic positive / negative controls of the energy arithmetic."""

    T = [0.0, 1e-9, 1.5e-9, 4e-9, 1e-8]       # non-uniform grid

    def test_positive_control_resistor_load(self):
        V, R = 1.8, 10e3
        e = A.energy_from_trace(self.T, [V] * 5, [-V / R] * 5)
        exp = V * V / R * self.T[-1]
        self.assertAlmostEqual(e["net"], exp, delta=1e-12 * exp)
        self.assertAlmostEqual(e["gross"], exp, delta=1e-12 * exp)
        self.assertEqual(e["rec"], 0.0)

    def test_recovery_control(self):
        # source delivers V*I for 4 ns then absorbs V*I/2 for 6 ns (exact step at 4 ns via duplicate-free grid)
        V, I = 1.0, 1e-6
        t = [0.0, 4e-9, 4e-9 + 1e-18, 1e-8]
        i = [-I, -I, I / 2, I / 2]
        e = A.energy_from_trace(t, [V] * 4, i)
        delivered, recovered = V * I * 4e-9, V * I / 2 * 6e-9
        self.assertAlmostEqual(e["gross"], delivered, delta=1e-6 * delivered)
        self.assertAlmostEqual(e["rec"], recovered, delta=1e-6 * recovered)
        self.assertAlmostEqual(e["net"], e["gross"] - e["rec"], delta=1e-25)
        self.assertAlmostEqual(e["net"], delivered - recovered, delta=1e-6 * delivered)

    def test_zero_crossing_split_exact(self):
        # p ramps linearly from +P to -P: gross = rec = P*T/4, net = 0
        P, T = 2e-6, 1e-8
        e = A.energy_from_trace([0.0, T], [1.0, 1.0], [-P, P])
        self.assertAlmostEqual(e["gross"], P * T / 4, delta=1e-24)
        self.assertAlmostEqual(e["rec"], P * T / 4, delta=1e-24)
        self.assertAlmostEqual(e["net"], 0.0, delta=1e-24)

    def test_negative_control_inverted_polarity_detected(self):
        V, R = 1.8, 10e3
        exp = V * V / R * self.T[-1]
        e = A.energy_from_trace(self.T, [V] * 5, [+V / R] * 5)    # current sign inverted
        self.assertFalse(math.isclose(e["net"], exp, rel_tol=1e-3))
        self.assertFalse(A.dc_check_ok(exp, V, (+V / R) * self.T[-1]))  # DC charge check catches it
        self.assertTrue(A.dc_check_ok(exp, V, (-V / R) * self.T[-1]))

    def test_negative_control_malformed_traces_rejected(self):
        with self.assertRaises(ValueError):
            A.energy_from_trace([0.0, 2e-9, 1e-9], [1, 1, 1], [0, 0, 0])      # non-monotonic
        with self.assertRaises(ValueError):
            A.energy_from_trace([0.0, 1e-9, 1e-9], [1, 1, 1], [0, 0, 0])      # repeated time
        with self.assertRaises(ValueError):
            A.energy_from_trace([0.0, 1e-9], [1, 1], [0])                      # missing current sample
        with self.assertRaises(ValueError):
            A.energy_from_trace([0.0, None], [1, 1], [0, 0])                   # missing time
        with self.assertRaises(ValueError):
            A.energy_from_trace([0.0, 1e-9], [1, float("nan")], [0, 0])
        with self.assertRaises(ValueError):
            A.energy_from_trace([0.0], [1], [0])

    def test_identity_check(self):
        self.assertTrue(A.identity_ok(1e-13, 1.5e-13, 0.5e-13))
        self.assertFalse(A.identity_ok(1e-13, 1.5e-13, 0.0))
        self.assertTrue(A.identity_ok(-2e-14, 1e-14, 3e-14))      # negative net kept, not clipped

    def test_scaling_units_and_duty(self):
        self.assertAlmostEqual(A.p_refresh_w(1, 1e-12, 1e-6), 1e-6)    # 1 pJ per 1 us = 1 uW
        self.assertAlmostEqual(A.p_refresh_w(1024, 1e-12, 5e-6), 1024 * 1e-12 / 5e-6)
        self.assertAlmostEqual(A.duty_factor(100, 27e-9, 2.7e-6), 1.0)
        self.assertGreater(A.duty_factor(1024, G.t_row_refresh_op_s(), 5.029945e-6), 1.0)
        self.assertLess(A.duty_factor(4, G.t_row_refresh_op_s(), 2.7519205e-6), 1.0)

    def test_intervals_read_from_retention_chain(self):
        ivs = A.intervals()
        self.assertEqual([i["label"] for i in ivs], ["ratified_assumed_csn", "extracted_csn_unratified"])
        self.assertAlmostEqual(ivs[0]["interval_s"], 5.029945e-6, delta=1e-12)
        self.assertAlmostEqual(ivs[1]["interval_s"], 2.7519205e-6, delta=1e-12)
        self.assertEqual(ivs[0]["c_sn_basis"], "ASSUMED margin factor")
        self.assertEqual(ivs[1]["c_sn_basis"], "EXTRACTED (layout)")


class Reduction(unittest.TestCase):
    def reduce(self, rep):
        return A.reduce_report(rep, C_SN)

    def test_synthetic_report_reduces_consistently(self):
        src, pts, ctl = self.reduce(synth_report())
        self.assertEqual(len(pts), 10 * 4)
        self.assertEqual({(p["process"], p["temp_c"]) for p in pts},
                         {(p, t) for p in G.PROCESS_CORNERS for t in G.TEMPS_C})
        self.assertTrue(all(p["status"] == "restored" for p in pts))
        self.assertTrue(all(k["identity_all"] and k["dc_check_all"] for k in ctl))
        self.assertTrue(all(k["nop_flagged_unrestored"] for k in ctl))    # nop must not count as a refresh
        n_energy = sum(1 for i in G.instances() if i["energy"])
        self.assertEqual(len(src), 10 * n_energy * len(G.source_roles()))

    def test_incremental_is_active_minus_idle(self):
        _s, pts, _c = self.reduce(synth_report())
        for p in pts:
            self.assertAlmostEqual(p["e_row_incr_J"], p["e_active_net_J"] - p["e_idle_net_J"], delta=1e-30)
            self.assertAlmostEqual(p["p_idle_net_W"], p["e_idle_net_J"] / (G.T_END_S - G.T_START_S), delta=1e-30)

    def test_no_pulse_pair_gives_zero_increment(self):
        _s, _p, ctl = self.reduce(synth_report())
        for k in ctl:
            self.assertAlmostEqual(k["nop_minus_idle_net_J"], 0.0, delta=1e-30)

    def test_negative_increment_retained(self):
        rep = synth_report()
        c0 = rep["corners"][0]
        # make idle more expensive than active for pattern 'zero' at the first corner
        s = G.src_name("vrwl1", "idl_z")
        q = -1e-11 / 1.8                          # idle draws 10 pJ: more than the synthetic active op
        set_meas(c0, f"q_{s}", q)
        set_meas(c0, f"en_{s}", -1.8 * q)
        set_meas(c0, f"eg_{s}", max(-1.8 * q, 0))
        _s, pts, _c = self.reduce(rep)
        p = next(x for x in pts if x["process"] == c0["process"] and x["temp_c"] == c0["temperature_c"] and x["pattern"] == "zero")
        self.assertLess(p["e_row_incr_J"], 0)
        self.assertTrue(p["identity_ok"] and p["dc_check_ok"])

    def test_missing_channel_rejected(self):
        rep = synth_report()
        c0 = rep["corners"][3]
        c0["measurements"] = [x for x in c0["measurements"] if x["name"] != "q_vbody_act_o"]
        with self.assertRaises(ValueError):
            self.reduce(rep)
        rep = synth_report()
        set_meas(rep["corners"][1], "en_vwbl0_act_o", None)
        with self.assertRaises(ValueError):
            self.reduce(rep)

    def test_inverted_polarity_detected(self):
        rep = synth_report()
        c0 = rep["corners"][0]
        s = G.src_name("vrwl2", "act_c")           # DC deselected RWL source
        e = get_meas(c0, f"en_{s}")
        set_meas(c0, f"en_{s}", -e)
        set_meas(c0, f"eg_{s}", get_meas(c0, f"er_{s}"))
        set_meas(c0, f"er_{s}", e if e > 0 else 0.0)
        _s, pts, ctl = self.reduce(rep)
        self.assertFalse(ctl[0]["dc_check_all"])
        self.assertFalse(next(p for p in pts if p["process"] == c0["process"] and p["temp_c"] == 27
                              and p["pattern"] == "checker")["dc_check_ok"])

    def test_mixed_instance_currents_detected(self):
        # an active-instance energy replaced by a different instance's value
        rep = synth_report()
        c0 = rep["corners"][0]
        set_meas(c0, "en_vrwl1_act_o", get_meas(c0, "en_vpre0_act_o") * 3 + 1e-15)
        _s, _p, ctl = self.reduce(rep)
        self.assertFalse(ctl[0]["dc_check_all"])

    def test_restore_and_read_failures_visible_and_excluded(self):
        rep = synth_report()
        bad = synth_corner("ss", 125, sn1_end=1.0)            # '1' restored to 1.0 < 0.95 x 1.35
        rbad = synth_corner("fs", 27, rbs1=0.85)              # '1' read above VREF = 0.8 -> read failure
        rep["corners"] = [c for c in rep["corners"] if (c["process"], c["temperature_c"]) not in
                          {("ss", 125), ("fs", 27)}] + [bad, rbad]
        _s, pts, _c = self.reduce(rep)
        f = [p for p in pts if p["status"] != "restored"]
        self.assertEqual({(p["process"], p["temp_c"]) for p in f}, {("ss", 125), ("fs", 27)})
        self.assertTrue(all("restore" in p["fail_reasons"] for p in f if p["process"] == "ss"))
        self.assertTrue(all("read" in p["fail_reasons"] for p in f if p["process"] == "fs"))
        self.assertFalse(any(p["pattern"] == "zero" for p in f))   # all-zero has no '1' to fail
        # make a failing point the most expensive: it must not become the successful maximum
        for p in pts:
            if p["status"] != "restored":
                p["e_row_incr_J"] = 1.0
        mx = A.maxima(pts)
        self.assertLess(mx["e_row_incr_J"]["value"], 1.0)
        scal = A.scaling_rows(pts, A.intervals())
        self.assertFalse(any(r["e_row_incr_J"] == 1.0 for r in scal))

    def test_hottest_is_not_assumed_maximum(self):
        rep = synth_report()
        rep["corners"] = [synth_corner(p, t, e_pwl=(5e-13 if (p, t) == ("ff", 27) else 1e-13))
                          for p in G.PROCESS_CORNERS for t in G.TEMPS_C]
        _s, pts, _c = self.reduce(rep)
        mx = A.maxima(pts)
        self.assertEqual((mx["e_row_incr_J"]["process"], mx["e_row_incr_J"]["temp_c"]), ("ff", 27))
        self.assertFalse(mx["max_e_row_incr_is_at_hottest_temp"])
        self.assertEqual(mx["hottest_temp_max_e_row_incr"]["temp_c"], 125)

    def test_scaling_adds_idle_exactly_once_and_flags_infeasible(self):
        _s, pts, _c = self.reduce(synth_report())
        scal = A.scaling_rows(pts, A.intervals())
        mx = A.maxima(pts)
        env = [r for r in scal if r["basis"] == "envelope_grid_max"]
        self.assertEqual(len(env), 2 * len(A.N_ROWS_GRID))
        for r in env:
            n = r["n_rows_ASSUMPTION"]
            self.assertAlmostEqual(r["p_refresh_W"], n * mx["e_row_incr_J"]["value"] / r["interval_s"], delta=1e-30)
            self.assertAlmostEqual(r["p_idle_W"], n * mx["p_idle_net_W"]["value"] / G.N_ROWS, delta=1e-30)
            self.assertAlmostEqual(r["p_total_W"], r["p_refresh_W"] + r["p_idle_W"], delta=1e-30)
            self.assertEqual(r["schedule_feasible"], r["duty_factor"] < 1)
            if not r["schedule_feasible"]:
                self.assertIn("INFEASIBLE", r["notes"])
        self.assertTrue(any(not r["schedule_feasible"] for r in env))
        self.assertTrue(all(r["n_cells"] == r["n_rows_ASSUMPTION"] * 4 for r in scal))

    def test_convergence_flags(self):
        _s, pts, _c = self.reduce(synth_report())
        fine = copy.deepcopy(pts)
        A.add_convergence(pts, fine)
        self.assertTrue(all(p["converged_1pct"] for p in pts))
        pts2 = [{k: v for k, v in p.items() if "fine" not in k and "conv" not in k} for p in pts]
        fine[0]["e_active_net_J"] *= 1.05
        fine[0]["e_row_incr_J"] = fine[0]["e_active_net_J"] - fine[0]["e_idle_net_J"]
        A.add_convergence(pts2, fine)
        self.assertFalse(pts2[0]["converged_1pct"])
        with self.assertRaises(ValueError):
            A.add_convergence(pts2, fine[1:])

    def test_resolution_sensitive_status_is_unresolved_and_excluded(self):
        _s, pts, _c = self.reduce(synth_report())
        fine = copy.deepcopy(pts)
        fine[0]["status"] = "FAILED"
        pts[0]["e_row_incr_J"] = 10.0                 # would be the maximum if it counted
        A.add_convergence(pts, fine)
        self.assertEqual(pts[0]["status"], "UNRESOLVED")
        self.assertEqual((pts[0]["status_main"], pts[0]["status_fine"]), ("restored", "FAILED"))
        self.assertFalse(pts[0]["converged_1pct"])
        self.assertLess(A.maxima(pts)["e_row_incr_J"]["value"], 10.0)
        self.assertTrue(all(p["status"] == "restored" for p in pts[1:]))

    def test_idle_gmin_floor_flag(self):
        self.assertAlmostEqual(A.GMIN_FLOOR_W, 64 * 1e-15 * 1.8 ** 2, delta=1e-20)
        for e_idle, flagged in ((1e-22, True), (1e-15, False)):
            _s, pts, _c = self.reduce(synth_report(e_idle_dc=e_idle))
            self.assertTrue(all(p["idle_at_gmin_floor"] is flagged for p in pts), e_idle)

    def test_errored_report_rejected(self):
        with self.assertRaises(ValueError):
            A.reduce_report(dict(status="error", errored=3, corners=[]), C_SN)


class Evidence(unittest.TestCase):
    """Committed results reproduce from the committed raw reports (skipped while pending)."""

    def summaries(self) -> list[Path]:
        return sorted(RESULTS.glob("refresh_energy_summary_*.json"))

    def test_committed_results_reproduce(self):
        if not self.summaries():
            self.skipTest("no reduced results committed (batch evidence pending)")
        for s in self.summaries():
            d = json.loads(s.read_text())
            rid, frid = d["run_id"], d["fine_run_id"]
            main = next(RESULTS.glob(f"klt_report_{rid}.json*"))
            fine = next(RESULTS.glob(f"klt_report_{frid}.json*"))
            with tempfile.TemporaryDirectory() as td:
                tm, tf = Path(td) / main.name, Path(td) / fine.name
                tm.write_bytes(main.read_bytes())
                tf.write_bytes(fine.read_bytes())
                self.assertEqual(A.main([str(tm), str(tf)]), 0)
                for k in ("sources", "points", "scaling"):
                    name = f"refresh_energy_{k}_{rid}.csv"
                    self.assertEqual((Path(td) / name).read_text(), (RESULTS / name).read_text(), name)
                new = json.loads((Path(td) / s.name).read_text())
                old = dict(d)
                for x in (new, old):
                    x.pop("input_hashes")       # hashes the deck/scripts as they are at analysis time
                self.assertEqual(new, old)
            self.assertEqual(d["input_hashes"]["sim/refresh-energy/refresh_energy.spice"],
                             d["klt"]["main"]["netlist_sha256"])
            self.assertEqual(d["klt"]["main"]["netlist_sha256"], d["klt"]["fine"]["netlist_sha256"])

    def test_summary_scope_claims_and_controls(self):
        for s in self.summaries():
            d = json.loads(s.read_text())
            self.assertEqual(d["status"], "PROPOSED_OPERATING_RANGE_NOT_RATIFIED")
            for k in ("complete_row_refresh_energy", "physical_lower_bound", "macro_power", "sram_comparison",
                      "spec_changed", "larger_array_geometry_simulated"):
                self.assertFalse(d["claims"][k], k)
            self.assertTrue(d["controls"]["nop_flagged_unrestored_all"])
            self.assertTrue(d["controls"]["identity_all"])
            self.assertTrue(d["controls"]["dc_charge_check_all"])
            self.assertEqual(len(d["results_125C"]), 5 * 4)
            with (RESULTS / f"refresh_energy_points_{d['run_id']}.csv").open(newline="") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual({(r["process"], int(r["temp_c"]), r["pattern"]) for r in rows},
                             {(p, t, q) for p in G.PROCESS_CORNERS for t in G.TEMPS_C for q in G.PATTERNS})
            self.assertEqual(d["klt"]["main"]["corner_count"], 10)

    def test_refuses_to_overwrite(self):
        if not self.summaries():
            self.skipTest("results pending")
        d = json.loads(self.summaries()[0].read_text())
        main = next(RESULTS.glob(f"klt_report_{d['run_id']}.json*"))
        fine = next(RESULTS.glob(f"klt_report_{d['fine_run_id']}.json*"))
        self.assertEqual(A.main([str(main), str(fine)]), 2)


if __name__ == "__main__":
    unittest.main()
