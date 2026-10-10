#!/usr/bin/env python3
"""Reduce a `klt sim` report of a refresh-replay run into per-corner x variant results (issue #128).

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
PRIOR_TOL_V = 0.01             # baseline vs prior sim/refresh-op report agreement (same circuit, same point)


def load_json(p: Path):
    opener = gzip.open if p.name.endswith(".gz") else open
    with opener(p, "rt") as fh:
        return json.load(fh)


def duration_record(man_inst: dict, variant: str) -> dict:
    """Operation timing for a variant (ns from the launch edge, t = 0)."""
    dg = man_inst.get("digital")
    rel = man_inst["t_release_ns"]
    if dg:
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
        conv = deck_ok and (golden_ok if (rtl and not neg) else True)
        restore = {f"{f:g}": sim_ok and all(r[f"restored_{int(f * 100)}"] for r in rs) for f in FRACS}
        res = dict(
            corner=corner["process"], temp_c=corner["temperature_c"], variant=v, klt_corner_status=corner["status"], simulator_ok=sim_ok,
            conversion_valid=conv, deck_matches_trace=deck_ok, trace_matches_golden_rtl=golden_ok if rtl else None,
            sense_correct=sim_ok and all(r["sense_correct"] for r in rs),
            sense_correct_by_pattern={f"{r['kind']}_{r['sn_pre_v']:g}": r["sense_correct"] for r in rs},
            restore_success=restore[f"{PRIMARY:g}"], restore_success_by_fraction=restore,
            restored_by_pattern={f"{r['kind']}_{r['sn_pre_v']:g}": r[f"restored_{int(PRIMARY * 100)}"] for r in rs},
            snend_by_pattern_v={f"{r['kind']}_{r['sn_pre_v']:g}": r["snend_v"] for r in rs},
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
        baseline_matches_prior_all_corners=all(r.get("baseline_matches_prior_refresh_op", False) for r in results if r["variant"] == "baseline_analog"),
        results=results)
    summ.write_text(json.dumps(summary, indent=1) + "\n")
    print(f"wrote {pts.name} and {summ.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
