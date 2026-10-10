#!/usr/bin/env python3
"""Stdlib-only checks for the matched initialization-control study (issue #139). No ngspice, PDK or klt.

Run: python3 -I sim/refresh-replay/test_init_control.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analyze_init_control as A  # noqa: E402
import gen_init_control as C  # noqa: E402
import gen_refresh_replay as GR  # noqa: E402
import replay_lib as L  # noqa: E402
from test_refresh_replay import golden  # noqa: E402


def build():
    g = golden()
    insts = C.build_instances(g)
    c_sn_ff, _ = GR.S.load_extracted_c_sn(GR.S.EXTRACT_JSON, "sn")
    deck = C.build_deck(c_sn_ff * 1e-15, insts)
    return g, insts, c_sn_ff * 1e-15, deck


def man_of(insts):
    return dict(instances=[dict(name=p["name"], kind=p["kind"], sn_v=p["sn"], variant=p["variant"], regime=p["regime"], base=p["base"],
                                init_negative=p["init_negative"], pin_ic=p["pin_ic"], sn_ic_row0_v=p["sn_ic_row0_v"], t_prep_ns=p["t_prep_ns"],
                                t_pre_read_ns=p["t_pre_read_ns"]) for p in insts])


class Generator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g, cls.insts, cls.c_sn, cls.deck = build()
        cls.check = C.verify(cls.deck, cls.insts)
        cls.by = {i["name"]: i for i in cls.insts}

    def pick(self, variant, kind="op1", sn=0.9):
        return next(i for i in self.insts if i["variant"] == variant and i["kind"] == kind and i["sn"] == sn)

    def test_enumeration_is_the_curated_set(self):
        self.assertEqual(GR.PATTERNS, [("op1", 0.9), ("op1", 1.0), ("op0", -0.1), ("op0", 0.0)])
        self.assertEqual(C.BASE_VARIANTS, ["baseline_analog", "rtl_hold", "rwl_late_hold", "neg_missing_wb"])
        live = [i for i in self.insts if i["kind"] != "ref"]
        self.assertEqual(len(live), (3 * 4 + 1) * 4)
        self.assertEqual(sorted({i["regime"] for i in live}), ["legacy", "physical", "pin_ic"])
        self.assertEqual(sum(1 for i in live if i["init_negative"]), 4)
        self.assertEqual(len({i["name"] for i in self.insts}), len(self.insts))

    def test_legacy_instances_are_the_131_control_lines(self):
        leg = [i for i in GR.build_instances(self.g) if i["variant"] in C.BASE_VARIANTS + ["reference_write"]]
        orig = GR.build_netlist(self.c_sn, leg).splitlines()
        new = set(self.deck.splitlines())
        self.assertEqual([ln for ln in orig if ln not in new and not ln.startswith((".ic", "* ---- instance"))], [])   # instance index comments renumber
        for i in self.insts:
            if i["regime"] == "legacy" and i["kind"] != "ref":
                self.assertEqual(C.ic_tokens(self.deck, i["name"]).get("rwls_@"), None, i["name"])     # legacy: NO pin IC
                self.assertEqual(C.ic_tokens(self.deck, i["name"])["sn_@_0"], GR.S._fmt(i["sn"]))

    def test_every_instance_changes_only_its_regime_declared_items(self):
        for n, c in self.check.items():
            self.assertTrue(c["declared_changes_only"], (n, c["findings"]))
        legacy = [i for i in self.insts if i["regime"] == "legacy"]
        for n, c in GR.verify_deck(self.deck, legacy, self.g).items():
            self.assertTrue(c["deck_matches_trace"], n)

    def _flagged(self, name, bad_deck):
        self.assertNotEqual(bad_deck, self.deck)
        self.assertFalse(C.verify(bad_deck, self.insts)[name]["declared_changes_only"], name)

    def test_tampering_is_flagged(self):
        pic = self.pick("pic_rtl_hold")["name"]
        pw = self.pick("pw_rtl_hold")["name"]
        nw = self.pick("pwnw_rwl_late_hold")["name"]
        lines = self.deck.splitlines()
        # pin_ic: a shifted WWL source (any source change is undeclared in this regime)
        self._flagged(pic, "\n".join(ln.replace("1.2000e-08", "1.3000e-08") if ln.startswith(f"vww_{pic} ") else ln for ln in lines))
        # pin_ic: the declared pin IC missing
        self._flagged(pic, self.deck.replace(f" v(rwls_{pic})=1.8", ""))
        # physical: the row-0 SN starts at the LABEL instead of the opposite level (a write that is not needed = IC-based prep)
        self._flagged(pw, self.deck.replace(f"v(sn_{pw}_0)=0 ", f"v(sn_{pw}_0)=0.9 "))
        # physical: prep write pulse widened by 1 ns
        self._flagged(pw, "\n".join(ln.replace("2.1000e-08 {VDD} 2.1100e-08 0", "2.2000e-08 {VDD} 2.2100e-08 0") if ln.startswith(f"vww_{pw} ") else ln
                                    for ln in lines))
        # physical: an op edge moved by an extra 1 ns (not the declared T_PREP shift)
        self._flagged(pw, "\n".join(ln.replace("3.5000e-08 0 3.5100e-08 {VDD}", "3.6500e-08 0 3.6600e-08 {VDD}") if ln.startswith(f"ven_{pw} ") else ln
                                    for ln in lines))
        # physical: a different prep data level (tuning the written target)
        self._flagged(pw, self.deck.replace(f"vpw_{pw} wpd_{pw} 0 pwl(0 0.9 2.2000e-08 0.9", f"vpw_{pw} wpd_{pw} 0 pwl(0 1.0 2.2000e-08 1.0"))
        # init negative control: a prep write sneaking back in
        self._flagged(nw, "\n".join(ln.replace("pwl(0.0000e+00 0 ", "pwl(0.0000e+00 0 1.0000e-09 0 1.1000e-09 {VDD} 2.1000e-08 {VDD} 2.1100e-08 0 ")
                                    if ln.startswith(f"vww_{nw} ") else ln for ln in lines))
        # physical: ONLY the latch-header enable (venb_) edge moved -- ven_ and every NODE_OF source untouched
        venb = next(ln for ln in lines if ln.startswith(f"venb_{pw} "))
        pts = venb.split(None, 3)[3]
        self._flagged(pw, "\n".join(venb.replace(pts, pts.replace("3.5000e-08", "3.6500e-08", 1)) if ln == venb else ln for ln in lines))
        # physical: ONLY a venb_ level changed (no longer the complement of ven_)
        self._flagged(pw, "\n".join(venb.replace(pts, pts.replace("{VDD}", "0", 1)) if ln == venb else ln for ln in lines))
        # physical: venb_ source terminals rewired (enb node tied elsewhere)
        self._flagged(pw, "\n".join(venb.replace(f"enb_{pw} 0", f"enbx_{pw} 0", 1) if ln == venb else ln for ln in lines))
        # an undeclared element in an instance
        self._flagged(pic, self.deck + f"\nrextra_{pic} sn_{pic}_0 0 1k\n")

    def test_physical_timing_is_the_legacy_op_shifted_by_t_prep(self):
        for i in self.insts:
            if i["regime"] != "physical":
                continue
            leg = self.by[i["legacy_name"]]
            for k in ("t_dec_ns", "t_meas_ns", "t_release_ns", "t_settle_ns", "t_wwl_rise_ns", "t_wwl_fall_ns"):
                if leg[k] is None:
                    self.assertIsNone(i[k], (i["name"], k))
                else:
                    self.assertAlmostEqual(i[k], leg[k] + C.T_PREP_NS, places=6, msg=(i["name"], k))
            self.assertAlmostEqual(i["t_pre_read_ns"], leg["t_pre_read_ns"] + C.T_PREP_NS, places=6)
            if i["t_wwl_fall_ns"] is not None:
                self.assertEqual(i["t_wwl_fall_ns"] - i["t_wwl_rise_ns"], 20.0)
        # preparation sequence ordering: write pulse, WBL return, switch open, all before the op starts; zero hold
        self.assertEqual(C.PREP_WWL_FALL_NS - C.PREP_WWL_RISE_NS, 20.0)
        self.assertLess(C.PREP_WWL_FALL_NS, C.POST_WRITE_PROBE_NS)
        self.assertLess(C.POST_WRITE_PROBE_NS, C.PREP_WBL_RETURN_NS)
        self.assertLess(C.PREP_WBL_RETURN_NS + L.T_EDGE_NS, C.PREP_SW_OPEN_NS)
        self.assertLess(C.PREP_SW_OPEN_NS + L.T_EDGE_NS, C.OP_START_PROBE_NS)
        self.assertLess(C.OP_START_PROBE_NS, C.T_PREP_NS)

    def test_pre_read_probe_precedes_the_read_select_assert(self):
        for i in self.insts:
            if i["kind"] == "ref":
                continue
            assert_t = [t for t, v in L.trace_signal_edges(i["trace"], "rwl_sel") if v == 1][0]
            self.assertAlmostEqual(i["t_pre_read_ns"], assert_t - C.PRE_READ_LEAD_NS, places=6)
            self.assertLess(i["t_pre_read_ns"], i["t_dec_ns"])

    def test_request_probes_and_names(self):
        req = C.build_request(self.insts)
        names = {m["name"] for m in req["measurements"]}
        self.assertEqual(len(req["corners"]["process"]) * len(req["corners"]["temperature_c"]), 10)
        self.assertEqual(req["backend"], "batch")
        self.assertEqual(req["netlist"], "init_control.spice")
        for i in self.insts:
            if i["kind"] == "ref":
                continue
            for k in ("snpre", "snini", "dec", "snend", "snrd"):
                self.assertIn(f"{k}_{i['name']}", names)
            self.assertEqual(f"snos_{i['name']}" in names, i["regime"] == "physical")
        self.assertEqual([n for n in names if n != n.lower()], [])       # klayout-tools#2914: lower case only
        t_stop = float(req["analysis"]["args"].split()[1].rstrip("n"))
        self.assertGreater(t_stop, max(i["t_settle_ns"] for i in self.insts))


def synth(man, pre=None, dec=None, snend=None, status="pass", sn_ref=1.3):
    """Synthetic klt corner. Defaults: correct decisions, pre-read = label, '1' restored to SN_ref, '0' to 0 V."""
    ms = [dict(name="snend_refw", value=sn_ref)]
    for mi in man["instances"]:
        if mi["kind"] == "ref":
            continue
        n = mi["name"]
        one = mi["kind"] == "op1"
        ms += [dict(name=f"snpre_{n}", value=(pre or {}).get(n, mi["sn_v"])), dict(name=f"snini_{n}", value=mi["sn_v"]),
               dict(name=f"dec_{n}", value=(dec or {}).get(n, -1.7 if one else 1.7)),
               dict(name=f"snend_{n}", value=(snend or {}).get(n, sn_ref if one else 0.0))]
    return dict(process="tt", temperature_c=27, status=status, measurements=ms)


class Analysis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, insts, _, deck = build()
        cls.man = man_of(insts)
        cls.check = C.verify(deck, insts)
        cls.n = {(i["variant"], i["kind"], i["sn"]): i["name"] for i in insts}

    def run_(self, **kw):
        rows, res = A.corner_results(synth(self.man, **kw), self.man, self.check)
        return {r["instance"]: r for r in rows}, {r["variant"]: r for r in res}

    def test_records_separate_label_post_write_pre_read_decision_and_fraction(self):
        rows, _ = self.run_()
        r = rows[self.n[("pw_rtl_hold", "op1", 0.9)]]
        for k in ("intended_level_v", "achieved_post_write_v", "pre_read_v", "dec_v", "decided", "sense_correct", "restore_fraction", "outcome"):
            self.assertIn(k, r)
        self.assertIsNone(rows[self.n[("rtl_hold", "op1", 0.9)]]["achieved_post_write_v"])     # IC regime: no write exists
        self.assertEqual(r["intended_level_v"], 0.9)

    def test_mislabeled_pre_read_is_detected(self):
        n = self.n[("rtl_hold", "op1", 0.9)]
        rows, res = self.run_(pre={n: 1.024})          # the documented legacy uplift
        self.assertFalse(rows[n]["label_matches_pre_read"])
        self.assertAlmostEqual(rows[n]["pre_read_minus_label_v"], 0.124, places=6)
        self.assertFalse(res["rtl_hold"]["label_matches_pre_read_all"])
        rows, _ = self.run_(pre={n: 0.9 + A.LABEL_TOL_V / 2})
        self.assertTrue(rows[n]["label_matches_pre_read"])

    def test_incorrect_sense_is_never_hidden_by_a_restore_ratio(self):
        n = self.n[("rwl_late_hold", "op1", 0.9)]
        rows, res = self.run_(dec={n: +1.7}, snend={n: 1.35})      # read as '0' but SN ends above SN_ref (ratio 1.04)
        r = rows[n]
        self.assertFalse(r["sense_correct"])
        self.assertGreater(r["restore_fraction"], A.PRIMARY)
        self.assertFalse(r["restored_95"] or r["restored_90"] or r["restored_98"])
        self.assertEqual(r["outcome"], "sense_incorrect")
        v = res["rwl_late_hold"]
        self.assertTrue(v["simulator_ok"])
        self.assertFalse(v["sense_correct"] or v["restore_success"] or v["overall_pass"])
        self.assertEqual(v["failure_reason"], "sense_incorrect")
        self.assertNotIn("op1_0.9", v["restore_among_sense_correct_patterns"])
        self.assertEqual(A.ratio_hides_sense(list(rows.values())), [n + "@tt/27"])

    def test_unresolved_decision_is_not_correct_and_simulator_error_never_passes(self):
        n = self.n[("rtl_hold", "op0", 0.0)]
        rows, res = self.run_(dec={n: 0.2})
        self.assertEqual(rows[n]["decided"], "unresolved")
        self.assertFalse(rows[n]["sense_correct"] or rows[n]["restored_95"])
        _, res = self.run_(status="fail")
        self.assertTrue(all(not r["overall_pass"] and r["failure_reason"] == "simulator_error" for r in res.values()))

    def test_pass_requires_sense_and_restore(self):
        _, res = self.run_()
        self.assertTrue(res["pw_rwl_late_hold"]["overall_pass"])
        self.assertFalse(res["neg_missing_wb"]["overall_pass"])            # negative controls never pass
        self.assertFalse(res["pwnw_rwl_late_hold"]["overall_pass"])

    def nowrite(self, ok=True):
        pre, dec, snend = {}, {}, {}
        for kind, sn in GR.PATTERNS:
            n = self.n[("pwnw_rwl_late_hold", kind, sn)]
            pre[n] = -0.07 if kind == "op1" else 1.12          # opposite level (no write)
            dec[n] = 1.8 if kind == "op1" else -1.8
            snend[n] = 0.0 if kind == "op1" else 1.33
        return pre, dec, snend

    def test_init_negative_control_detected(self):
        pre, dec, snend = self.nowrite()
        _, res = self.run_(pre=pre, dec=dec, snend=snend)
        self.assertTrue(res["pwnw_rwl_late_hold"]["init_negative_control_ok"])
        # a no-write control whose read LOOKS right (pre-read at its label, decision correct) is a failed control
        _, res = self.run_()
        self.assertFalse(res["pwnw_rwl_late_hold"]["init_negative_control_ok"])
        n = self.n[("pwnw_rwl_late_hold", "op0", -0.1)]
        dec2 = dict(dec, **{n: 1.7})                         # one pattern sensed 'correctly' by accident
        _, res = self.run_(pre=pre, dec=dec2, snend=snend)
        self.assertFalse(res["pwnw_rwl_late_hold"]["init_negative_control_ok"])

    def test_restoration_negative_control(self):
        snend = {self.n[("neg_missing_wb", "op1", s)]: 0.9 for s in (0.9, 1.0)}
        _, res = self.run_(snend=snend)
        self.assertTrue(res["neg_missing_wb"]["negative_control_ok"])
        _, res = self.run_()                                   # a missing write-back that restores = failed control
        self.assertFalse(res["neg_missing_wb"]["negative_control_ok"])

    def test_sense_vs_pre_read_monotone_and_violation(self):
        def row(base, pre, d, c="tt"):
            return dict(corner=c, temp_c=27, base=base, pre_read_v=pre, decided=d, instance=f"x{pre}", dec_v=0)
        ok = [row("rtl_hold", 0.62, "0"), row("rtl_hold", 0.83, "1"), row("rwl_late_hold", 1.02, "1"), row("rtl_hold", -0.1, "0")]
        s = A.sense_vs_pre_read(ok)
        self.assertTrue(s["all_monotone"])
        self.assertEqual((s["rows"][0]["max_pre_read_decided_0_v"], s["rows"][0]["min_pre_read_decided_1_v"]), (0.62, 0.83))
        bad = ok + [row("rwl_late_hold", 0.9, "0")]           # a higher level read as '0' than one read as '1': sensing differs
        self.assertFalse(A.sense_vs_pre_read(bad)["all_monotone"])
        self.assertFalse(A.sense_vs_pre_read(ok + [row("rtl_hold", 0.7, "unresolved")])["all_monotone"])
        # families are separate: the analog baseline's sense timing is not pooled with the RTL one
        self.assertTrue(A.sense_vs_pre_read(ok + [row("baseline_analog", 0.9, "0")])["all_monotone"])

    def test_restore_counted_only_among_sense_correct_records(self):
        n = self.n[("rwl_late_hold", "op1", 0.9)]
        rows, _ = self.run_(dec={n: +1.7}, snend={n: 1.35})
        e = A.restore_among_sense_correct_records(list(rows.values()))["legacy|rwl_late_hold|op1"]
        self.assertEqual((e["records"], e["sense_correct"], e["sense_incorrect"], e["restored_among_sense_correct"]), (2, 1, 1, 1))

    def test_documented_claims_check(self):
        rows, results = [], []
        for c, t in [("tt", 27), ("ss", 27), ("fs", 27), ("ff", 125)]:
            for b in ("baseline_analog", "rtl_hold", "rwl_late_hold"):
                fail = (c, t) in A.DOCUMENTED_PIC_SENSE_FAIL
                rows.append(dict(corner=c, temp_c=t, regime="pin_ic", base=b, pattern="op1_0.9", restoration_negative=False, sense_correct=not fail,
                                 pre_read_v=0.83, init_negative=False, pre_read_minus_label_v=-0.07))
                rows.append(dict(corner=c, temp_c=t, regime="legacy", base=b, pattern="op1_0.9", restoration_negative=False, sense_correct=True,
                                 pre_read_v=1.02, init_negative=False, pre_read_minus_label_v=0.12))
                results.append(dict(variant="pic_" + b, sense_correct=not fail))
        d = A.documented_claims(rows, results)
        self.assertTrue(d["pin_ic_stored1_0p9_sense_failures"]["reproduced"])
        self.assertTrue(d["startup_uplift"]["reproduced"])
        self.assertTrue(d["pin_ic_minus_legacy_pre_read"]["within_documented"])
        rows[0]["sense_correct"] = False                      # an extra failure at tt/27 -> no longer the documented set
        self.assertFalse(A.documented_claims(rows, results)["pin_ic_stored1_0p9_sense_failures"]["reproduced"])


class Committed(unittest.TestCase):
    def test_committed_init_control_runs_are_self_consistent(self):
        for rd in sorted((HERE / "init_control_results").glob("*/")):
            man = json.loads((rd / "manifest.json").read_text())
            self.assertEqual(hashlib.sha256((rd / "init_control.spice").read_text().encode()).hexdigest(), man["deck_sha256"], rd.name)
            chk = json.loads((rd / "consistency_check.json").read_text())
            self.assertTrue(all(c["declared_changes_only"] for c in chk.values()), rd.name)
            for k in ("source_sha256", "git_head", "pdk_open_pdks_commit"):
                self.assertIn(k, man["pins"])
            if not (rd / "summary.json").exists():
                continue
            s = json.loads((rd / "summary.json").read_text())
            self.assertEqual(s["generated_deck_sha256"], man["deck_sha256"])
            self.assertEqual(s["report_netlist_sha256"], man["deck_sha256"])
            self.assertEqual(s["corner_count"], 10)
            for r in s["results"]:
                neg = "negative_control_ok" in r or "init_negative_control_ok" in r
                self.assertEqual(r["overall_pass"], (not neg) and r["simulator_ok"] and r["declared_changes_only"] and r["sense_correct"]
                                 and r["restore_success"], (r["variant"], r["corner"]))
                for p, ok in r["sense_correct_by_pattern"].items():
                    if not ok:
                        self.assertFalse(r["restored_by_pattern"][p], (r["variant"], r["corner"], p))   # restore never passes a wrong read
            self.assertTrue(s["negative_controls"]["restoration_all_ok"])
            self.assertTrue(s["negative_controls"]["initialization_all_ok"])
            import csv
            with (rd / "points.csv").open() as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(len(rows), 10 * 52)
            for r in rows:
                for k in ("intended_level_v", "achieved_post_write_v", "pre_read_v", "dec_v", "sense_correct", "restore_fraction"):
                    self.assertIn(k, r)
                if r["regime"] == "physical":
                    self.assertNotEqual(r["achieved_post_write_v"], "")


if __name__ == "__main__":
    unittest.main()
