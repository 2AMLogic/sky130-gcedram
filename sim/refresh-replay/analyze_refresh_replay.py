#!/usr/bin/env python3
"""Reduce a `klt sim` report of a refresh-replay run into per-corner x variant results (issues #128, #131).

Stdlib only. Writes NEW files into the run directory (refuses to overwrite):
``points.csv`` (one row per corner, instance) and ``summary.json``.

Four separate verdicts per (corner, variant) -- simulator success alone is NEVER a restoration pass:

* ``conversion_valid``  the generated deck's PWL sources reproduce the variant's edge list exactly
  (deck_vs_trace) and, for the RTL variants, that edge list equals the golden RTL export. The two negative
  controls are DESIGNED to differ from the golden trace: ``negative_control_detected`` records that the
  consistency check caught it.
* ``sense_correct``     the latch decision d = V(rbl) - V(ref) just before WWL rise is correct for all
  four patterns (|d| >= 0.9 V; stored '1' -> negative, '0' -> positive).
* ``restore_success``   every pattern restored (sim/refresh-op criterion: '1' needs the correct decision and
  SN(end) >= FRAC x SN_ref of the in-deck reference write at the same corner, FRAC 0.90/0.95/0.98, headline
  0.95; '0' needs the correct decision and SN(end) <= 50 mV).
* ``duration``          operation end, completion observation and fit against the provisional 34-cycle budget.

``overall_pass`` = simulator ok AND conversion_valid AND sense_correct AND restore_success (0.95).
Negative controls: ``negative_control_ok`` = detected by the consistency check AND every stored-'1' pattern
flagged NOT restored.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "sim" / "refresh-op"))
sys.path.insert(0, str(REPO / "sim" / "sense-stage"))
import analyze_refresh_op as AR  # noqa: E402

BUDGET_CYCLES = 34             # provisional scheduler T_ROW (digital/refresh-scheduler), ASSUMPTION
CYCLE_NS = 1.0
FRACS = AR.FRACS
PRIMARY = AR.PRIMARY_FRAC
PRIOR_REPORT = REPO / "sim" / "refresh-op" / "results" / "klt_report_20261010T005003Z.json.gz"
EXPERIMENT_NAMES = ("rwl_late_raw", "rwl_late_hold", "latch_early_hold", "latch_late_hold", "combined_hold")  # == gen EXPERIMENTS
PRIOR_TOL_V = 0.01             # baseline vs prior sim/refresh-op report agreement (same circuit, same point)


def load_json(p: Path):
    opener = gzip.open if p.name.endswith(".gz") else open
    with opener(p, "rt") as fh:
        return json.load(fh)


def duration_record(man_inst: dict, variant: str) -> dict:
    """Operation timing for a variant (ns from the launch edge, t = 0)."""
    dg = man_inst.get("digital")
    rel = man_inst["t_release_ns"]
    if dg and variant in EXPERIMENT_NAMES:
        # #131 retimed release edge(s): the op ends at the LAST control edge; `done` is ASSUMED one cycle later
        end = max(dg["busy_fall_ns"], rel)
        done_seen = end + CYCLE_NS
    elif dg:
        end = dg["busy_fall_ns"]
        done_seen = dg["done_rise_ns"] + CYCLE_NS if dg["done_rise_ns"] is not None else None
    else:
        end, done_seen = rel, rel          # analog baseline: no digital completion strobe
    rec = dict(last_control_edge_ns=rel, op_end_ns=end, completion_observed_ns=done_seen,
               settled_measurement_ns=man_inst["t_meas_ns"], budget_ns=BUDGET_CYCLES * CYCLE_NS)
    rec["fits_budget_op_end"] = end <= rec["budget_ns"] + 1e-9
    rec["slack_op_end_ns"] = round(rec["budget_ns"] - end, 6)
    rec["fits_budget_completion_observed"] = None if done_seen is None else done_seen <= rec["budget_ns"] + 1e-9
    rec["fits_budget_settled_measurement"] = man_inst["t_meas_ns"] <= rec["budget_ns"] + 1e-9
    return rec


def corner_results(corner: dict, man: dict, check: dict, prior: dict | None) -> tuple[list[dict], list[dict]]:
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
        ck = check[n]
        row = dict(corner=corner["process"], temp_c=corner["temperature_c"], instance=n, variant=mi["variant"], kind=mi["kind"],
                   sn_pre_v=mi["sn_v"], dec_v=dec, decided=AR.decided(dec), snrd_v=meas.get(f"snrd_{n}"), snend_v=sn,
                   sn_before_wwl_fall_v=meas.get(f"snwf_{n}"), wbl_before_wwl_fall_v=meas.get(f"wblp_{n}"), sn_ref_v=sn_ref,
                   sn_after_wwl_fall_v=meas.get(f"snwa_{n}"), wbl_after_wwl_fall_v=meas.get(f"wbla_{n}"),
                   dec_after_wwl_fall_v=meas.get(f"dla_{n}"), sn_before_rwl_release_v=meas.get(f"snrb_{n}"),
                   sn_after_rwl_release_v=meas.get(f"snra_{n}"), sn_settle_v=meas.get(f"snset_{n}"), dec_end_v=meas.get(f"dend_{n}"),
                   t_rwl_release_ns=mi.get("t_rwl_release_ns"), t_latch_release_ns=mi.get("t_latch_release_ns"),
                   t_wwl_fall_ns=mi.get("t_wwl_fall_ns"),
                   deck_matches_trace=ck["deck_matches_trace"], trace_matches_golden_rtl=ck["trace_matches_golden_rtl"],
                   sense_correct=dec is not None and AR.decided(dec) == mi["kind"][-1],
                   **{f"restored_{int(f * 100)}": AR.restored(mi["kind"], dec, sn, sn_ref, f) for f in FRACS})
        rows.append(row)
        by_var.setdefault(mi["variant"], []).append(row)
    results = []
    for v in man["variants"]:
        rs = by_var[v]
        mi0 = next(i for i in man["instances"] if i["variant"] == v)
        neg = v in man["negative_controls"]
        deck_ok = all(r["deck_matches_trace"] for r in rs)
        golden_ok = all(r["trace_matches_golden_rtl"] for r in rs)
        rtl = v not in ("baseline_analog",)
        exp = v in man.get("experiments", {})
        # experiments differ from the golden trace by design: they must differ from their PARENT in exactly the intended edges
        exp_ok = all(check[r_["instance"]]["experiment_diff"]["only_intended_edges"] for r_ in rs) if exp else None
        conv = deck_ok and (exp_ok if exp else (golden_ok if (rtl and not neg) else True))
        restore = {f"{f:g}": sim_ok and all(r[f"restored_{int(f * 100)}"] for r in rs) for f in FRACS}
        res = dict(
            corner=corner["process"], temp_c=corner["temperature_c"], variant=v, klt_corner_status=corner["status"], simulator_ok=sim_ok,
            conversion_valid=conv, deck_matches_trace=deck_ok, trace_matches_golden_rtl=golden_ok if rtl else None,
            sense_correct=sim_ok and all(r["sense_correct"] for r in rs),
            sense_correct_by_pattern={f"{r['kind']}_{r['sn_pre_v']:g}": r["sense_correct"] for r in rs},
            restore_success=restore[f"{PRIMARY:g}"], restore_success_by_fraction=restore,
            restored_by_pattern={f"{r['kind']}_{r['sn_pre_v']:g}": r[f"restored_{int(PRIMARY * 100)}"] for r in rs},
            experiment=exp, only_intended_edges_changed=exp_ok,
            snend_by_pattern_v={f"{r['kind']}_{r['sn_pre_v']:g}": r["snend_v"] for r in rs},
            snset_by_pattern_v={f"{r['kind']}_{r['sn_pre_v']:g}": r["sn_settle_v"] for r in rs},
            sn_before_wwl_fall_by_pattern_v={f"{r['kind']}_{r['sn_pre_v']:g}": r["sn_before_wwl_fall_v"] for r in rs},
            sn_after_wwl_fall_by_pattern_v={f"{r['kind']}_{r['sn_pre_v']:g}": r["sn_after_wwl_fall_v"] for r in rs},
            sn_before_rwl_release_by_pattern_v={f"{r['kind']}_{r['sn_pre_v']:g}": r["sn_before_rwl_release_v"] for r in rs},
            sn_after_rwl_release_by_pattern_v={f"{r['kind']}_{r['sn_pre_v']:g}": r["sn_after_rwl_release_v"] for r in rs},
            wbl_before_wwl_fall_by_pattern_v={f"{r['kind']}_{r['sn_pre_v']:g}": r["wbl_before_wwl_fall_v"] for r in rs},
            wbl_after_wwl_fall_by_pattern_v={f"{r['kind']}_{r['sn_pre_v']:g}": r["wbl_after_wwl_fall_v"] for r in rs},
            dec_after_wwl_fall_by_pattern_v={f"{r['kind']}_{r['sn_pre_v']:g}": r["dec_after_wwl_fall_v"] for r in rs},
            min_op1_fraction=min((r["snend_v"] / sn_ref for r in rs if r["kind"] == "op1" and r["snend_v"] is not None and sn_ref), default=None),
            stored_zero_signed_levels_v=sorted(r["snend_v"] for r in rs if r["kind"] == "op0" and r["snend_v"] is not None),
            sn_ref_v=sn_ref, duration=duration_record(mi0, v))
        res["overall_pass"] = bool(sim_ok and conv and res["sense_correct"] and res["restore_success"]) and not neg
        if neg:
            res["negative_control_detected"] = not golden_ok
            res["negative_control_ok"] = (not golden_ok) and all(not r[f"restored_{int(PRIMARY * 100)}"] for r in rs if r["kind"] == "op1")
        results.append(res)
    if prior is not None:
        pm = {m["name"]: m["value"] for c in prior["corners"] if (c["process"], c["temperature_c"]) == (corner["process"], corner["temperature_c"])
              for m in c["measurements"]}
        diffs = {}
        for r in by_var["baseline_analog"]:
            k = {"op1": "op1", "op0": "op0"}[r["kind"]]
            tag = ("n%03d" % round(-r["sn_pre_v"] * 1000)) if r["sn_pre_v"] < 0 else ("%04d" % round(r["sn_pre_v"] * 1000))
            pv = pm.get(f"snend_{k}_{tag}_s10_w20")
            if pv is not None and r["snend_v"] is not None:
                diffs[f"{k}_{tag}"] = abs(pv - r["snend_v"])
        for res in results:
            if res["variant"] == "baseline_analog":
                res["baseline_vs_prior_refresh_op_max_abs_diff_v"] = max(diffs.values()) if diffs else None
                res["baseline_matches_prior_refresh_op"] = bool(diffs) and max(diffs.values()) <= PRIOR_TOL_V
    return rows, results


# ---- causal attribution (issue #131) -------------------------------------------------------------------
EFFECT_MIN_V = 0.02    # ASSUMPTION: a mean change of the worst stored-'1' fraction below 0.02 of SN_ref is "no resolvable effect"

# (name, variant with the factor, variant without it, what is toggled, what is held)
CONTRASTS = [
    ("rwl_release_late | no latch hold", "rwl_late_raw", "rtl_raw", "RWL release 12->34 ns", "raw 1-cycle sample pulse"),
    ("rwl_release_late | latch hold", "rwl_late_hold", "rtl_hold", "RWL release 12->34 ns", "latch held to 34 ns"),
    ("latch_hold | RWL early", "rtl_hold", "rtl_raw", "latch enable held 11->34 ns", "RWL release 12 ns"),
    ("latch_hold | RWL late", "rwl_late_hold", "rwl_late_raw", "latch enable held 11->34 ns", "RWL release 34 ns"),
    ("latch_release_early (30) | RWL early", "latch_early_hold", "rtl_hold", "latch release 34->30 ns", "RWL release 12 ns"),
    ("latch_release_late (36) | RWL early", "latch_late_hold", "rtl_hold", "latch release 34->36 ns", "RWL release 12 ns"),
    ("combined (RWL 34 + latch 36) vs hold control", "combined_hold", "rtl_hold", "both release edges", "latch held"),
    ("combined vs rwl_late_hold (added latch release 36)", "combined_hold", "rwl_late_hold", "latch release 34->36 ns", "RWL release 34 ns"),
    ("RTL hold + both late vs analog baseline", "combined_hold", "baseline_analog", "everything else (sense/WWL timing, hold/BL/RWL join times)", "-"),
]


def attribution(results: list[dict]) -> dict:
    """Per contrast: the change in the worst stored-'1' fraction (SN_end / SN_ref) and in restoration, over all corners.
    Classification is mechanical (see ``label``); it is evidence of association within the ideal-driver circuit,
    not a physical-macro claim."""
    by = {(r["corner"], r["temp_c"], r["variant"]): r for r in results}
    corners = sorted({(r["corner"], r["temp_c"]) for r in results})
    out = {}
    for name, a, b, toggled, held in CONTRASTS:
        deltas, flips_up, flips_down, a_ok, b_ok = [], 0, 0, 0, 0
        for c in corners:
            ra, rb = by.get((*c, a)), by.get((*c, b))
            if not ra or not rb or ra["min_op1_fraction"] is None or rb["min_op1_fraction"] is None:
                continue
            deltas.append(ra["min_op1_fraction"] - rb["min_op1_fraction"])
            a_ok += ra["restore_success"]
            b_ok += rb["restore_success"]
            flips_up += ra["restore_success"] and not rb["restore_success"]
            flips_down += rb["restore_success"] and not ra["restore_success"]
        if not deltas:
            continue
        mean = sum(deltas) / len(deltas)
        if len(deltas) == a_ok and b_ok == 0:
            label = "isolated_sufficient_restores_everywhere"
        elif mean >= EFFECT_MIN_V and all(d > 0 for d in deltas):
            label = "improves_all_corners_not_sufficient" if a_ok < len(deltas) else "improves_restores"
        elif mean <= -EFFECT_MIN_V and all(d < 0 for d in deltas):
            label = "degrades_all_corners"
        elif abs(mean) < EFFECT_MIN_V and max(abs(d) for d in deltas) < 2 * EFFECT_MIN_V:
            label = "no_resolvable_effect"
        else:
            label = "mixed_or_corner_dependent"
        out[name] = dict(with_factor=a, without_factor=b, toggled=toggled, held=held, corners=len(deltas),
                         mean_delta_min_op1_fraction=round(mean, 4), min_delta=round(min(deltas), 4), max_delta=round(max(deltas), 4),
                         restored_corners_with=a_ok, restored_corners_without=b_ok, corners_fail_to_pass=flips_up,
                         corners_pass_to_fail=flips_down, label=label)
    return out


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
    prior = load_json(PRIOR_REPORT) if PRIOR_REPORT.exists() else None
    rows, results = [], []
    for c in rep["corners"]:
        r, s = corner_results(c, man, check, prior)
        rows += r
        results += s
    with pts.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    env = rep["environment"]
    remote = env.get("remote", {})
    by_variant = {}
    for v in man["variants"]:
        rs = [r for r in results if r["variant"] == v]
        by_variant[v] = dict(
            corners=len(rs), simulator_ok=sum(r["simulator_ok"] for r in rs), conversion_valid=sum(r["conversion_valid"] for r in rs),
            sense_correct=sum(r["sense_correct"] for r in rs), restore_success_0_95=sum(r["restore_success"] for r in rs),
            overall_pass=sum(r["overall_pass"] for r in rs),
            only_intended_edges_changed=(all(r["only_intended_edges_changed"] for r in rs) if rs[0]["experiment"] else None),
            mean_min_op1_fraction=(sum(r["min_op1_fraction"] for r in rs) / len(rs) if all(r["min_op1_fraction"] is not None for r in rs) else None),
            restore_success_by_fraction={f"{f:g}": sum(r["restore_success_by_fraction"][f"{f:g}"] for r in rs) for f in FRACS},
            failed_corners_0_95=[f"{r['corner']}/{r['temp_c']}C" for r in rs if not r["restore_success"]],
            op_end_ns=sorted({r["duration"]["op_end_ns"] for r in rs}),
            completion_observed_ns=sorted({r["duration"]["completion_observed_ns"] for r in rs if r["duration"]["completion_observed_ns"] is not None}),
            fits_budget_op_end=all(r["duration"]["fits_budget_op_end"] for r in rs),
            fits_budget_completion_observed=all(bool(r["duration"]["fits_budget_completion_observed"]) for r in rs if r["duration"]["completion_observed_ns"] is not None),
            fits_budget_settled_measurement=all(r["duration"]["fits_budget_settled_measurement"] for r in rs))
        if v in man["negative_controls"]:
            by_variant[v]["negative_control_ok_corners"] = sum(r["negative_control_ok"] for r in rs)
    summary = dict(
        run_id=man["run_id"], issue=man["issue"], status=man["status"],
        scope="27 C and 125 C, tt/ss/ff/sf/fs global corners, VDD 1.8 V, no mismatch, ideal drivers (PROPOSED range, not ratified)",
        klt_status=rep["status"], corner_count=rep["corner_count"], batch_job_id=remote.get("job_id"),
        batch_instance_type=remote.get("instance_type"), report_netlist_sha256=env.get("netlist_sha256"),
        report_models_lib_sha256=env.get("models_lib_sha256"), engine=env.get("engine"), engine_version=env.get("engine_version"),
        report_provenance=rep.get("provenance"), report_klt_client_note="klt_version in report_provenance is the client that produced the report; pins.klt_client is the generator-time default client",
        generated_deck_sha256=man["deck_sha256"], request_sha256=man["request_sha256"], pins=man["pins"],
        criteria=dict(decide_v=AR.DECIDE_V, fracs=FRACS, primary_frac=PRIMARY, zero_max_v=AR.ZERO_MAX_V, budget_cycles=BUDGET_CYCLES,
                      prior_report=str(PRIOR_REPORT.relative_to(REPO)), prior_tolerance_v=PRIOR_TOL_V),
        assumptions=man["assumptions"],
        claims=dict(mismatch_or_offset_yield_validated=False, physical_column_driver_validated=False, extracted_c_rbl=False,
                    extracted_c_wbl=False, spec_changed=False, scheduler_timing_changed=False, contract_changed=False),
        by_variant=by_variant,
        causal_attribution=attribution(results),
        causal_attribution_threshold_v=EFFECT_MIN_V,
        baseline_matches_prior_all_corners=all(r.get("baseline_matches_prior_refresh_op", False) for r in results if r["variant"] == "baseline_analog"),
        results=results)
    summ.write_text(json.dumps(summary, indent=1) + "\n")
    print(f"wrote {pts.name} and {summ.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
