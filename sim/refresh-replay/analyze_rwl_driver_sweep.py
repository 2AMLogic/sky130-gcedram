#!/usr/bin/env python3
"""Reduce a `klt sim` report of an RWL-driver sensitivity run into points.csv + summary.json (issue #134). Stdlib only.

Writes NEW files into the run directory (refuses to overwrite). Verdicts are kept SEPARATE and never merged:

* ``simulator_ok``      klt corner status pass and measurements present
* ``declared_changes_only``  the generated deck differs from the parent control only in the declared driver parameters /
                        release time (consistency_check.json)
* ``sense_correct``     latch decision correct for all four patterns (sim/refresh-op criterion)
* ``restore_success``   sim/refresh-op criterion at the FIXED gating probe (never moved): stored '1' SN >= FRAC x SN_ref,
                        stored '0' <= 50 mV; FRAC 0.90/0.95/0.98, headline 0.95
* ``time budget``       reported on its own (source-edge op end, cell-pin 90 % crossing, completion, gating probe) against the
                        provisional 34-cycle budget; a restoration verdict is NEVER derived from it or vice versa

The robustness envelope is computed on the TESTED grid only (contiguous from the ideal point along one axis); it is a
bound on the tested points, not a continuous claim. "Absent" envelopes are reported explicitly.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "sim" / "refresh-op"))
sys.path.insert(0, str(REPO / "sim" / "sense-stage"))
import analyze_refresh_op as AR  # noqa: E402

BUDGET_NS = 34.0
CYCLE_NS = 1.0
FRACS = AR.FRACS
PRIMARY = AR.PRIMARY_FRAC
PRIOR_SUMMARY = HERE / "results" / "20261010T130000Z" / "summary.json"
REPRO_TOL_V = 0.005         # control SN_end reproduction vs the recorded #131 run (same circuit; different deck size -> solver step choice)
N_TRAJ = 7


def load_json(p: Path):
    opener = gzip.open if p.name.endswith(".gz") else open
    with opener(p, "rt") as fh:
        return json.load(fh)


def ns(x):
    return None if x is None else x * 1e9


def interp_crossing(samples: list[tuple[float, float | None]], thr: float):
    """First rising crossing of ``thr`` by linear interpolation between consecutive (t_ns, v) samples; None if never reached.
    A sample already >= thr at the first point means the crossing happened before the window (reported as that first time)."""
    prev = None
    for t, v in samples:
        if v is None:
            return None
        if v >= thr:
            if prev is None:
                return t
            (t0, v0) = prev
            return t if v == v0 else round(t0 + (thr - v0) * (t - t0) / (v - v0), 4)
        prev = (t, v)
    return None


def pat(r):
    return f"{r['kind']}_{r['sn_pre_v']:g}"


def duration(mi: dict, pin90_ns, pin50_ns) -> dict:
    dg = mi.get("digital")
    rel = mi["t_release_ns"]
    end = max(dg["busy_fall_ns"], rel) if dg else rel
    src_end = mi.get("t_src_release_end_ns")
    src_end = rel if src_end is None else src_end
    # pin_release_90_ns None = the cell pin did not reach 90 % within the window: completion is then UNKNOWN (never counted as fitting)
    completes = None if pin90_ns is None else max(end, src_end, pin90_ns)
    done_seen = None if completes is None else (completes + CYCLE_NS if dg else completes)
    return dict(budget_ns=BUDGET_NS, op_end_source_start_ns=end, slack_op_end_source_start_ns=round(BUDGET_NS - end, 6),
                fits_op_end_source_start=end <= BUDGET_NS + 1e-9,
                source_edge_end_ns=src_end, fits_source_edge_end=src_end <= BUDGET_NS + 1e-9,
                pin_release_50_ns=pin50_ns, pin_release_90_ns=pin90_ns,
                slack_pin_release_90_ns=None if pin90_ns is None else round(BUDGET_NS - pin90_ns, 4),
                fits_pin_release_90=None if pin90_ns is None else pin90_ns <= BUDGET_NS + 1e-9,
                completion_observed_ns=None if done_seen is None else round(done_seen, 4),
                slack_completion_observed_ns=None if done_seen is None else round(BUDGET_NS - done_seen, 4),
                fits_completion_observed=False if done_seen is None else done_seen <= BUDGET_NS + 1e-9,
                gating_probe_ns=mi["t_meas_ns"], fits_gating_probe=mi["t_meas_ns"] <= BUDGET_NS + 1e-9)


def reason(sim_ok, sense, r1_ok, r0_ok) -> str:
    if not sim_ok:
        return "simulator_error"
    if not sense:
        return "sense_incorrect"
    if not r1_ok:
        return "stored1_below_threshold"
    if not r0_ok:
        return "stored0_above_50mV"
    return "pass"


def corner_results(corner: dict, man: dict, check: dict) -> tuple[list[dict], list[dict]]:
    meas = {m["name"]: m["value"] for m in corner["measurements"]}
    sim_ok = corner["status"] == "pass" and bool(meas)
    sn_ref = meas.get("snend_refw")
    by_var: dict[str, list[dict]] = {}
    rows = []
    for mi in man["instances"]:
        if mi["kind"] == "ref":
            continue
        n = mi["name"]
        dec, sn = meas.get(f"dec_{n}"), meas.get(f"snend_{n}")
        pt = mi.get("point") or {}
        psamp = [(mi["t_rwl_release_ns"] + o, meas.get(f"pins{k}_{n}")) for k, o in enumerate(man["pin_offsets_ns"])]
        pin50 = ns(meas.get(f"tp50r_{n}")) if meas.get(f"tp50r_{n}") is not None else interp_crossing(psamp, 0.5 * 1.8)
        pin90 = ns(meas.get(f"tp90r_{n}")) if meas.get(f"tp90r_{n}") is not None else interp_crossing(psamp, 0.9 * 1.8)
        row = dict(corner=corner["process"], temp_c=corner["temperature_c"], instance=n, variant=mi["variant"], group=mi["group"],
                   slew_ns=pt.get("slew_ns"), r_ohm=pt.get("r_ohm"), release_delay_ns=pt.get("release_delay_ns"), kind=mi["kind"], sn_pre_v=mi["sn_v"],
                   pin_ic=pt.get("pin_ic", False), snpre_v=meas.get(f"snpre_{n}"), dec_v=dec, decided=AR.decided(dec), snend_v=sn, sn_ref_v=sn_ref, snend_over_sn_ref=(sn / sn_ref if sn is not None and sn_ref else None),
                   snrd_v=meas.get(f"snrd_{n}"), sn_before_wwl_fall_v=meas.get(f"snwf_{n}"), sn_after_wwl_fall_v=meas.get(f"snwa_{n}"),
                   sn_before_rwl_release_v=meas.get(f"snrb_{n}"), sn_after_rwl_release_v=meas.get(f"snra_{n}"), sn_settle_v=meas.get(f"snset_{n}"),
                   pin_v_at_gating_probe=meas.get(f"pinm_{n}"), pin_v_at_release_plus_0p2ns=meas.get(f"pina_{n}"),
                   pin_release_50_ns=pin50, pin_release_90_ns=pin90, pin_crossing_method="exact_meas_when" if meas.get(f"tp50r_{n}") is not None else "interpolated_samples",
                   pin_assert_50_ns=ns(meas.get(f"tpa50_{n}")), **{f"pins{k}_v": meas.get(f"pins{k}_{n}") for k in range(len(man["pin_offsets_ns"]))},
                   wwl_fall_50_ns=ns(meas.get(f"twf50_{n}")), t_src_release_start_ns=mi.get("t_src_release_start_ns"),
                   t_src_release_50_ns=mi.get("t_src_release_50_ns"), t_gating_probe_ns=mi["t_meas_ns"],
                   sense_correct=dec is not None and AR.decided(dec) == mi["kind"][-1],
                   **{f"snt{k}_v": meas.get(f"snt{k}_{n}") for k in range(N_TRAJ)},
                   **{f"restored_{int(f * 100)}": AR.restored(mi["kind"], dec, sn, sn_ref, f) for f in FRACS})
        rows.append(row)
        by_var.setdefault(mi["variant"], []).append(row)
    results = []
    for v, rs in by_var.items():
        mi0 = next(i for i in man["instances"] if i["variant"] == v)
        ck = [check[r["instance"]] for r in rs]
        declared_ok = all(c.get("declared_changes_only", False) for c in ck)
        deck_ok = all(c.get("deck_matches_trace", True) for c in ck)
        pt = mi0.get("point") or {}
        neg = (pt.get("group") == "negative_control") or v in man["control_negatives"]
        restore = {f"{f:g}": bool(sim_ok and all(r[f"restored_{int(f * 100)}"] for r in rs)) for f in FRACS}
        op1 = [r for r in rs if r["kind"] == "op1"]
        op0 = [r for r in rs if r["kind"] == "op0"]
        sense = bool(sim_ok and all(r["sense_correct"] for r in rs))
        r1_ok = bool(sim_ok and all(r[f"restored_{int(PRIMARY * 100)}"] for r in op1))
        r0_ok = bool(sim_ok and all(r[f"restored_{int(PRIMARY * 100)}"] for r in op0))
        ref_row = next(r for r in op1 if r["sn_pre_v"] == 0.9)
        pin50, pin90 = ref_row["pin_release_50_ns"], ref_row["pin_release_90_ns"]
        # quantized time-to-restore: earliest sampled time (gating probe or trajectory) at which every pattern meets the criterion
        t_traj = mi0["traj_times_ns"]
        samples = sorted(set([(mi0["t_meas_ns"], "gating")] + [(t, f"snt{k}") for k, t in enumerate(t_traj)]))
        first = None
        for t, tag in samples:
            ok = sim_ok
            for r in rs:
                sv = r["snend_v"] if tag == "gating" else r[f"{tag}_v"]
                ok = ok and AR.restored(r["kind"], r["dec_v"], sv, sn_ref, PRIMARY)
            if ok:
                first = t
                break
        res = dict(
            corner=corner["process"], temp_c=corner["temperature_c"], variant=v, group=mi0["group"], point=pt or None,
            klt_corner_status=corner["status"], simulator_ok=sim_ok, declared_changes_only=declared_ok, deck_matches_trace=deck_ok,
            sense_correct=sense, sense_correct_by_pattern={pat(r): r["sense_correct"] for r in rs},
            restore_success=restore[f"{PRIMARY:g}"], restore_success_by_fraction=restore,
            restored_by_pattern={pat(r): r[f"restored_{int(PRIMARY * 100)}"] for r in rs},
            failure_reason=reason(sim_ok, sense, r1_ok, r0_ok),
            snend_by_pattern_v={pat(r): r["snend_v"] for r in rs},
            snend_over_sn_ref_by_pattern={pat(r): r["snend_over_sn_ref"] for r in rs},
            sn_before_wwl_fall_by_pattern_v={pat(r): r["sn_before_wwl_fall_v"] for r in rs},
            sn_after_wwl_fall_by_pattern_v={pat(r): r["sn_after_wwl_fall_v"] for r in rs},
            sn_before_rwl_release_by_pattern_v={pat(r): r["sn_before_rwl_release_v"] for r in rs},
            sn_after_rwl_release_by_pattern_v={pat(r): r["sn_after_rwl_release_v"] for r in rs},
            sn_settle_by_pattern_v={pat(r): r["sn_settle_v"] for r in rs},
            sn_trajectory_ns_v={pat(r): [[t, r[f"snt{k}_v"]] for k, t in enumerate(t_traj)] for r in rs},
            min_op1_fraction=min((r["snend_over_sn_ref"] for r in op1 if r["snend_over_sn_ref"] is not None), default=None),
            stored_zero_signed_levels_v=sorted(r["snend_v"] for r in op0 if r["snend_v"] is not None),
            sn_ref_v=sn_ref, pin_ic=bool(pt.get("pin_ic")), snpre_by_pattern_v={pat(r): r["snpre_v"] for r in rs},
            first_restored_sample_ns=first,          # quantized UPPER bound on time-to-restore (probe grid); None = never in the window
            pin=dict(v_at_gating_probe=ref_row["pin_v_at_gating_probe"], v_at_release_plus_0p2ns=ref_row["pin_v_at_release_plus_0p2ns"],
                     source_release_start_ns=mi0.get("t_src_release_start_ns"), source_release_50_ns=mi0.get("t_src_release_50_ns"),
                     pin_crossing_method=ref_row["pin_crossing_method"], pin_release_50_ns=pin50, pin_release_90_ns=pin90,
                     samples_ns_v=[[mi0["t_rwl_release_ns"] + o, ref_row[f"pins{k}_v"]] for k, o in enumerate(man["pin_offsets_ns"])],
                     pin_minus_source_50_ns=None if pin50 is None or mi0.get("t_src_release_50_ns") is None else round(pin50 - mi0["t_src_release_50_ns"], 4),
                     wwl_fall_50_ns=ref_row["wwl_fall_50_ns"],
                     pin_release_90_minus_wwl_fall_50_ns=None if pin90 is None or ref_row["wwl_fall_50_ns"] is None else round(pin90 - ref_row["wwl_fall_50_ns"], 4),
                     pin_release_50_minus_wwl_fall_50_ns=None if pin50 is None or ref_row["wwl_fall_50_ns"] is None else round(pin50 - ref_row["wwl_fall_50_ns"], 4)),
            time_budget=duration(mi0, pin90, pin50))
        res["overall_pass"] = bool(sim_ok and declared_ok and deck_ok and sense and res["restore_success"]) and not neg
        if neg:
            res["negative_control_ok"] = all(not r[f"restored_{int(PRIMARY * 100)}"] for r in op1)
        results.append(res)
    return rows, results


# ---- aggregation ---------------------------------------------------------------------------------------------
def point_summary(results: list[dict], pid: str) -> dict:
    rs = [r for r in results if r["variant"] == pid]
    mf = [r["min_op1_fraction"] for r in rs if r["min_op1_fraction"] is not None]
    tb = [r["time_budget"] for r in rs]
    pin90 = [r["pin"]["pin_release_90_ns"] for r in rs if r["pin"]["pin_release_90_ns"] is not None]
    d50 = [r["pin"]["pin_release_50_minus_wwl_fall_50_ns"] for r in rs if r["pin"]["pin_release_50_minus_wwl_fall_50_ns"] is not None]
    z = [x for r in rs for x in r["stored_zero_signed_levels_v"]]
    firsts = [r["first_restored_sample_ns"] for r in rs]
    return dict(
        variant=pid, group=rs[0]["group"], point=rs[0]["point"], corners=len(rs),
        simulator_ok=sum(r["simulator_ok"] for r in rs), declared_changes_only=all(r["declared_changes_only"] for r in rs),
        sense_correct=sum(r["sense_correct"] for r in rs),
        restore_success_by_fraction={f"{f:g}": sum(r["restore_success_by_fraction"][f"{f:g}"] for r in rs) for f in FRACS},
        restore_success_0_95=sum(r["restore_success"] for r in rs),
        failed_corners_0_95=[dict(corner=f"{r['corner']}/{r['temp_c']}C", reason=r["failure_reason"]) for r in rs if not r["restore_success"]],
        failure_reasons={k: sum(1 for r in rs if r["failure_reason"] == k) for k in sorted({r["failure_reason"] for r in rs})},
        worst_min_op1_fraction=min(mf) if mf else None, mean_min_op1_fraction=(sum(mf) / len(mf) if mf else None),
        stored_zero_signed_range_v=[min(z), max(z)] if z else None,
        restoration_pass_all_corners=all(r["restore_success"] and r["sense_correct"] and r["simulator_ok"] for r in rs),
        time_budget=dict(
            op_end_source_start_ns=sorted({t["op_end_source_start_ns"] for t in tb}), fits_op_end_source_start=all(t["fits_op_end_source_start"] for t in tb),
            worst_pin_release_90_ns=max(pin90) if pin90 else None, min_slack_pin_release_90_ns=min((t["slack_pin_release_90_ns"] for t in tb if t["slack_pin_release_90_ns"] is not None), default=None),
            fits_pin_release_90=all(bool(t["fits_pin_release_90"]) for t in tb),
            pin_release_90_reached_corners=len(pin90),
            min_slack_completion_observed_ns=min((t["slack_completion_observed_ns"] for t in tb if t["slack_completion_observed_ns"] is not None), default=None), fits_completion_observed=all(t["fits_completion_observed"] for t in tb),
            fits_gating_probe=all(t["fits_gating_probe"] for t in tb)),
        pin_release_50_minus_wwl_fall_50_ns_range=[min(d50), max(d50)] if d50 else None,
        worst_first_restored_sample_ns=(None if any(f is None for f in firsts) else max(firsts)))


def contiguous_from(ref_index: int, passes: list[bool]) -> tuple[int, int]:
    """Largest [lo, hi] index interval containing ref_index in which every tested point passes (ref must pass)."""
    if not passes[ref_index]:
        return (-1, -1)
    lo = hi = ref_index
    while lo - 1 >= 0 and passes[lo - 1]:
        lo -= 1
    while hi + 1 < len(passes) and passes[hi + 1]:
        hi += 1
    return lo, hi


def axis_envelope(name: str, entries: list[tuple[float, dict]], ref_label: str, key_pass, ref_idx: int) -> dict:
    """entries: ordered (axis value, point summary). ``ref_idx`` is the entry with the ideal / reference setting."""
    passes = [bool(key_pass(e)) for _, e in entries]
    lo, hi = contiguous_from(ref_idx, passes)
    out = dict(axis=name, reference=ref_label, passing_values=[v for (v, _), p in zip(entries, passes) if p],
               failing_values=[v for (v, _), p in zip(entries, passes) if not p], tested=[dict(value=v, passes=p, restore_success_0_95=e["restore_success_0_95"],
                                                                 worst_min_op1_fraction=e["worst_min_op1_fraction"],
                                                                 failure_reasons=e["failure_reasons"]) for (v, e), p in zip(entries, passes)])
    if lo < 0:
        out.update(status="reference_point_fails", passing_interval=None)
        return out
    vals = [v for v, _ in entries]
    out["passing_interval"] = [vals[lo], vals[hi]]
    out["lower_bounded_by_failing_tested_point"] = vals[lo - 1] if lo > 0 else None
    out["upper_bounded_by_failing_tested_point"] = vals[hi + 1] if hi + 1 < len(entries) else None
    out["status"] = ("bounded_on_both_sides" if lo > 0 and hi + 1 < len(entries) else
                     "bounded_above_only" if hi + 1 < len(entries) else
                     "bounded_below_only" if lo > 0 else "no_failure_within_tested_range")
    out["non_contiguous_passes_outside_interval"] = [vals[i] for i, p in enumerate(passes) if p and not (lo <= i <= hi)]
    return out


def envelope(points: dict, ctl: dict) -> dict:
    """Per base (an/rh/rl), per axis. A point 'passes' = restoration pass at ALL 10 corners (sense correct, simulator ok, 0.95);
    the time-budget flags are carried alongside and also give a second, stricter envelope that is NOT the same as restoration."""
    ideal_of = {"an": "baseline_analog", "rh": "rtl_hold", "rl": "rwl_late_hold"}
    out = {}
    rest = lambda e: e["restoration_pass_all_corners"] and e["declared_changes_only"]       # noqa: E731
    rest_and_pin = lambda e: rest(e) and bool(e["time_budget"]["fits_pin_release_90"])        # noqa: E731
    for base, cv in ideal_of.items():
        ideal = ctl[cv]
        ax = {}
        slew = [(0.1, ideal)] + [(p["point"]["slew_ns"], p) for p in points.values() if p["variant"].startswith(base + "_") and p["group"] == "slew_only"]
        r = [(0.0, ideal)] + [(p["point"]["r_ohm"], p) for p in points.values() if p["variant"].startswith(base + "_") and p["group"] == "r_only"]
        slew.sort(key=lambda x: x[0])
        r.sort(key=lambda x: x[0])
        for label, key in (("restoration_only", rest), ("restoration_and_pin_release_90_within_budget", rest_and_pin)):
            ax[label] = dict(
                slew_ns_at_R0=axis_envelope("slew_ns (R = 0)", slew, "ideal control 0.1 ns", key, 0),
                r_ohm_at_ideal_slew=axis_envelope("series R ohm (slew 0.1 ns)", r, "ideal control R = 0", key, 0),
                combined=[dict(slew_ns=p["point"]["slew_ns"], r_ohm=p["point"]["r_ohm"], passes=bool(key(p)),
                               restore_success_0_95=p["restore_success_0_95"], failure_reasons=p["failure_reasons"])
                          for p in points.values() if p["variant"].startswith(base + "_") and p["group"] == "combined"])
        out[base] = dict(control=cv, **ax)
    # release-delay envelope per driver (rl only)
    rd = {}
    for p in points.values():
        if p["group"] == "release_delay":
            rd.setdefault((p["point"]["slew_ns"], p["point"]["r_ohm"]), []).append(p)
    out["release_delay"] = {}
    for (sl, rr), ps in sorted(rd.items()):
        ps.sort(key=lambda p: p["point"]["release_delay_ns"])
        ref_idx = next((i for i, p in enumerate(ps) if p["point"]["release_delay_ns"] == 2.0), None)
        if ref_idx is None:
            out["release_delay"][f"slew{sl:g}_R{rr:g}"] = dict(status="reference_point_missing")
            continue
        out["release_delay"][f"slew{sl:g}_R{rr:g}"] = {
            label: axis_envelope("RWL release start minus WWL fall start (ns)", [(p["point"]["release_delay_ns"], p) for p in ps],
                                 "d = +2 ns (the #131 rwl_late_hold release at 34 ns)", key, ref_idx)
            for label, key in (("restoration_only", rest), ("restoration_and_pin_release_90_within_budget", rest_and_pin))}
    return out


BINS = [(-1e9, -10.0), (-10.0, -4.0), (-4.0, 0.0), (0.0, 2.0), (2.0, 4.0), (4.0, 1e9)]   # ns, pin 50 % release minus WWL 50 % fall


def restoration_vs_pin_crossing(results: list[dict], man: dict) -> dict:
    """Restoration vs the MEASURED cell-pin release crossings (10/50/90 %) relative to the WWL fall -- not the programmed source edge.
    Only sense-correct (corner, point) records of non-negative-control points; a record is one corner of one point."""
    views = {}
    for key, label in (("pin_release_50_minus_wwl_fall_50_ns", "pin 50 % release crossing minus WWL 50 % fall"),
                       ("pin_release_90_minus_wwl_fall_50_ns", "pin 90 % release crossing minus WWL 50 % fall")):
        recs = [r for r in results if r["sense_correct"] and r["simulator_ok"] and r["group"] not in ("negative_control", "ic_artifact_check")
                and r["variant"] not in man["control_negatives"] and r["pin"][key] is not None]
        out = []
        for lo, hi in BINS:
            b = [r for r in recs if lo < r["pin"][key] <= hi]
            if not b:
                continue
            s1 = [all(v for k, v in r["restored_by_pattern"].items() if k.startswith("op1")) for r in b]
            s0 = [all(v for k, v in r["restored_by_pattern"].items() if k.startswith("op0")) for r in b]
            out.append(dict(range_ns=[None if lo < -1e8 else lo, None if hi > 1e8 else hi], records=len(b), stored1_restored=sum(s1),
                            stored0_ok=sum(s0), restore_success_all_patterns=sum(r["restore_success"] for r in b),
                            observed_ns=[min(r["pin"][key] for r in b), max(r["pin"][key] for r in b)]))
        views[key] = dict(definition=label, bins=out)
    return dict(views=views, note="association over this stimulus model only; bins are (lo, hi] in ns; the gating probe is fixed")


def start_regime_check(results: list[dict], man: dict) -> dict:
    """Every non-`pin_ic` sweep instance must start in the SAME effective regime as its parent legacy control: SN just before the
    RWL assert (`snpre`) equal to the control's. `pin_ic` points (ic_artifact_check) are expected to differ; the offset is the artifact."""
    ctl = {(r["corner"], r["temp_c"], r["variant"]): r for r in results if r["variant"] in man["control_variants"]}
    dev, ic_off, bad = [], [], []
    for r in results:
        pt = r.get("point")
        if not pt:
            continue
        par = ctl.get((r["corner"], r["temp_c"], pt["parent"]))
        if par is None:
            continue
        for k, v in r["snpre_by_pattern_v"].items():
            pv = par["snpre_by_pattern_v"].get(k)
            if v is None or pv is None:
                continue
            (ic_off if r["pin_ic"] else dev).append(v - pv)
            if not r["pin_ic"] and abs(v - pv) > 0.005:
                bad.append(dict(variant=r["variant"], corner=f"{r['corner']}/{r['temp_c']}", pattern=k, delta_v=round(v - pv, 4)))
    return dict(tolerance_v=0.005, non_ic_points_max_abs_delta_v=max((abs(x) for x in dev), default=None), non_ic_points_outside_tolerance=bad,
                same_effective_start_regime=not bad and bool(dev),
                pin_ic_points_delta_v_range=[min(ic_off), max(ic_off)] if ic_off else None,
                note="delta = SN at 1.9 ns (before the RWL assert) minus the parent legacy control's; the pin_ic delta quantifies the legacy startup charge injection")


def controls_reproduction(results: list[dict], man: dict) -> dict:
    if not PRIOR_SUMMARY.exists():
        return dict(checked=False, reason="recorded #131 summary not found")
    prior = {(r["corner"], r["temp_c"], r["variant"]): r for r in load_json(PRIOR_SUMMARY)["results"]}
    mism, maxdiff, n = [], 0.0, 0
    for r in results:
        if r["variant"] not in man["control_variants"]:
            continue
        pr = prior.get((r["corner"], r["temp_c"], r["variant"]))
        n += 1
        if pr is None:
            mism.append(dict(corner=f"{r['corner']}/{r['temp_c']}", variant=r["variant"], what="missing_in_recorded_run"))
            continue
        for what in ("restore_success", "sense_correct", "simulator_ok"):
            if r[what] != pr[what]:
                mism.append(dict(corner=f"{r['corner']}/{r['temp_c']}", variant=r["variant"], what=what, now=r[what], recorded=pr[what]))
        if r["restore_success_by_fraction"] != pr["restore_success_by_fraction"]:
            mism.append(dict(corner=f"{r['corner']}/{r['temp_c']}", variant=r["variant"], what="restore_success_by_fraction"))
        if "negative_control_ok" in pr and r.get("negative_control_ok") != pr["negative_control_ok"]:
            mism.append(dict(corner=f"{r['corner']}/{r['temp_c']}", variant=r["variant"], what="negative_control_ok"))
        for k, v in r["snend_by_pattern_v"].items():
            pv = pr["snend_by_pattern_v"].get(k)
            if pv is not None and v is not None:
                maxdiff = max(maxdiff, abs(pv - v))
    return dict(checked=True, recorded_run="20261010T130000Z", control_results_compared=n, verdict_mismatches=mism,
                all_verdicts_reproduce=not mism, max_abs_snend_diff_v=round(maxdiff, 6), snend_tolerance_v=REPRO_TOL_V,
                snend_within_tolerance=maxdiff <= REPRO_TOL_V)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--report", type=Path, default=None, help="default: <run_dir>/klt_report.json.gz")
    a = ap.parse_args(argv)
    rd = a.run_dir
    report = a.report or rd / "klt_report.json.gz"
    pts, summ = rd / "points.csv", rd / "summary.json"
    for p in (pts, summ):
        if p.exists():
            print(f"refusing to overwrite existing evidence file {p}", file=sys.stderr)
            return 2
    man, check, rep = load_json(rd / "manifest.json"), load_json(rd / "consistency_check.json"), load_json(report)
    rows, results = [], []
    for c in rep["corners"]:
        r, s = corner_results(c, man, check)
        rows += r
        results += s
    with pts.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    env = rep["environment"]
    remote = env.get("remote", {})
    ids = list(dict.fromkeys(r["variant"] for r in results))
    psum = {i: point_summary(results, i) for i in ids}
    ctl = {i: psum[i] for i in man["control_variants"] if i in psum}
    sweep = {i: p for i, p in psum.items() if i not in ctl}
    negs = {i: p for i, p in sweep.items() if p["group"] == "negative_control"}
    neg_detail = {i: dict(negative_control_ok_corners=sum(1 for r in results if r["variant"] == i and r.get("negative_control_ok")),
                          corners=p["corners"], restore_success_0_95=p["restore_success_0_95"]) for i, p in {**{k: ctl[k] for k in man["control_negatives"] if k in ctl}, **negs}.items()}
    failed = [dict(variant=i, group=p["group"], point=p["point"], restore_success_0_95=p["restore_success_0_95"], sense_correct=p["sense_correct"],
                   failed_corners=p["failed_corners_0_95"], failure_reasons=p["failure_reasons"])
              for i, p in sweep.items() if p["group"] != "negative_control" and not p["restoration_pass_all_corners"]]
    summary = dict(
        run_id=man["run_id"], issue=man["issue"], status=man["status"],
        framing="EXPERIMENTAL stimulus model (ideal PWL source with a declared ramp time + series resistor to the cell pin); NOT a designed physical driver; "
                "loads, write pulse, initial levels and thresholds identical to #131; sweep values are ASSUMPTIONS",
        scope="27 C and 125 C, tt/ss/ff/sf/fs global corners, VDD 1.8 V, no mismatch (PROPOSED range, not ratified)",
        klt_status=rep["status"], corner_count=rep["corner_count"], batch_job_id=remote.get("job_id"), batch_instance_type=remote.get("instance_type"),
        report_netlist_sha256=env.get("netlist_sha256"), report_models_lib_sha256=env.get("models_lib_sha256"), engine=env.get("engine"),
        engine_version=env.get("engine_version"), report_provenance=rep.get("provenance"),
        analyzer_sha256_at_analysis=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        generated_deck_sha256=man["deck_sha256"], request_sha256=man["request_sha256"], pins=man["pins"],
        sweep_values_assumptions=man["sweep_values_assumptions"], probe_definitions=man["probe_definitions"],
        criteria=dict(decide_v=AR.DECIDE_V, fracs=FRACS, primary_frac=PRIMARY, zero_max_v=AR.ZERO_MAX_V, budget_cycles=int(BUDGET_NS), gating_probe="fixed (not moved with release delay, slew or R)"),
        assumptions=man["assumptions"],
        claims=dict(physical_rwl_driver_validated=False, mismatch_or_offset_yield_validated=False, extracted_c_rbl=False, extracted_c_wbl=False,
                    extracted_rwl_load=False, spec_changed=False, scheduler_timing_changed=False, contract_changed=False, overlap_rule_changed=False),
        controls_reproduction=controls_reproduction(results, man),
        start_regime_check=start_regime_check(results, man),
        negative_controls=dict(detail=neg_detail, all_remain_failures=all(d["negative_control_ok_corners"] == d["corners"] for d in neg_detail.values())),
        control_points={i: p for i, p in ctl.items()},
        sweep_points=sweep,
        failed_sweep_points=failed,
        robustness_envelope=envelope(sweep, ctl),
        restoration_vs_pin_crossing=restoration_vs_pin_crossing(results, man),
        envelope_note="Computed on the TESTED grid only: contiguous from the ideal/reference point along ONE axis; the combined points are listed, not interpolated. "
                      "'restoration_only' ignores the time budget; 'restoration_and_pin_release_90_within_budget' additionally requires the cell-pin 90 % release "
                      "crossing to be <= the provisional 34 ns budget. The two are reported separately and are not the same claim.",
        results=results)
    summ.write_text(json.dumps(summary, indent=1) + "\n")
    print(f"wrote {pts.name} and {summ.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
