#!/usr/bin/env python3
"""Analyze loaded-column campaign results (issue #45).

Reads results/loaded_column_results.csv (one campaign run), checks expected
corner / temperature / age / selected-row / pattern coverage and provenance,
computes the signed read-bitline separation per group, and writes a
machine-readable summary JSON. It does NOT claim a sense decision, offset or
yield validation.

SIGN CONVENTION: separation = V(rbl | stored 0) - V(rbl | stored 1) at the
declared sense instant (t_sense after rwl-select fall). Positive = the '1'
discharged the bitline further than the '0'. Group worst-case separation =
min over all stored-0 cases of V(rbl) minus max over all stored-1 cases
(all 8 patterns of the other rows). A single fixed sense reference exists for
a group only if that worst-case separation is > 0 (window midpoint is then the
candidate reference -- an ASSUMPTION-level proposal, unvalidated).

Exit codes:
  0  coverage/provenance OK (and, if --min-separation-v given, all groups meet it)
  1  coverage or provenance check failed (campaign incomplete/unattributed)
  2  --min-separation-v given and at least one group is below it
     (a deliberately impossible threshold, e.g. 50 V, must therefore exit 2)
Failing engineering points never change exit code 0 unless a threshold is given.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS_CSV = HERE / "results" / "loaded_column_results.csv"
CORNERS = ["tt", "ss", "ff", "sf", "fs"]
TEMPS = [-40, 27, 125]
AGES = ["fresh", "refresh_bound"]
ROWS = [0, 1, 2, 3]
PROVENANCE = ["repo_git_sha", "pdk_open_pdks_commit", "ngspice_version", "timestamp_utc", "run_id"]


def f(x):
    try:
        return float(x) if x not in ("", None) else None
    except ValueError:
        return None


def load(path: Path, run_id: str | None):
    rows = list(csv.DictReader(path.open()))
    if not rows:
        raise SystemExit(f"no rows in {path}")
    run_id = run_id or max(r["run_id"] for r in rows)
    return run_id, [r for r in rows if r["run_id"] == run_id]


def check_coverage(rows, corners, temps, ages, sel_rows, patterns):
    expected = {
        (c, str(t), a, str(s), format(p, "04b"))
        for c, t, a, s, p in itertools.product(corners, temps, ages, sel_rows, patterns)
    }
    seen: dict = {}
    for r in rows:
        k = (r["corner"], r["temp_c"], r["age_label"], r["sel_row"], r["pattern_rows3210"])
        seen[k] = seen.get(k, 0) + 1
    missing = sorted(expected - set(seen))
    dup = sorted(k for k, n in seen.items() if n > 1)
    extra = sorted(set(seen) - expected)
    prov_bad = [
        (r["corner"], r["temp_c"], r["age_label"], r["sel_row"], r["pattern_rows3210"])
        for r in rows
        if any(not r.get(p) for p in PROVENANCE)
    ]
    return {"expected_points": len(expected), "present_points": len(seen),
            "missing": [list(m) for m in missing], "duplicates": [list(d) for d in dup],
            "unexpected": [list(e) for e in extra], "missing_provenance": [list(p) for p in prov_bad]}


def stats(vals):
    return {"min": min(vals), "max": max(vals)} if vals else None


def group_summary(rs):
    """rs: rows of one group (all selected-row/pattern points in scope)."""
    bad = [r for r in rs if r["status"] != "ok" or f(r["v_rbl_sense_v"]) is None]
    ok = [r for r in rs if r not in bad]
    v1 = [f(r["v_rbl_sense_v"]) for r in ok if r["stored_value"] == "1"]
    v0 = [f(r["v_rbl_sense_v"]) for r in ok if r["stored_value"] == "0"]
    out = {"n_points": len(rs), "n_ok": len(ok),
           "failed_points": [{"sel_row": r["sel_row"], "pattern": r["pattern_rows3210"],
                              "reason": r["reason"] or "v_rbl_sense_v missing"} for r in bad]}
    out["v_rbl_sense_stored1_v"] = stats(v1)
    out["v_rbl_sense_stored0_v"] = stats(v0)
    if v1 and v0 and not bad:
        sep = min(v0) - max(v1)
        out["worst_case_separation_v"] = sep
        out["single_reference_exists"] = sep > 0
        out["candidate_reference_v_UNVALIDATED"] = (min(v0) + max(v1)) / 2 if sep > 0 else None
        out["candidate_reference_half_window_v"] = sep / 2 if sep > 0 else None
    else:
        out["worst_case_separation_v"] = None
        out["single_reference_exists"] = None
        out["separation_missing_reason"] = (
            "incomplete group: %d failed/missing points" % len(bad) if bad
            else "no stored-1 or no stored-0 points in scope")
    lat1 = [f(r["latency_s"]) for r in ok if r["stored_value"] == "1"]
    out["latency_stored1_s"] = stats([x for x in lat1 if x is not None])
    out["latency_missing_stored1"] = [
        {"sel_row": r["sel_row"], "pattern": r["pattern_rows3210"], "reason": r["latency_reason"]}
        for r in ok if r["stored_value"] == "1" and f(r["latency_s"]) is None]
    sel_lv = lambda r, k: f(r[f"v_sn_r{r['sel_row']}_{k}_v"])
    out["stored1_after_write_v"] = stats([sel_lv(r, "after_write") for r in ok if r["stored_value"] == "1" and sel_lv(r, "after_write") is not None])
    out["stored0_after_write_v"] = stats([sel_lv(r, "after_write") for r in ok if r["stored_value"] == "0" and sel_lv(r, "after_write") is not None])
    out["stored1_preread_v"] = stats([sel_lv(r, "preread") for r in ok if r["stored_value"] == "1" and sel_lv(r, "preread") is not None])
    out["stored0_preread_v"] = stats([sel_lv(r, "preread") for r in ok if r["stored_value"] == "0" and sel_lv(r, "preread") is not None])
    out["read_disturb_sel_dv_sn_v"] = stats([f(r["dv_sn_sel_read_disturb_v"]) for r in ok if f(r["dv_sn_sel_read_disturb_v"]) is not None])
    out["deselected_current_preread_a_signed_per_row"] = stats(
        [f(r[f"i_into_rbl_r{k}_preread_a"]) for r in ok for k in ROWS
         if str(k) != r["sel_row"] and f(r[f"i_into_rbl_r{k}_preread_a"]) is not None])
    out["deselected_current_sense_a_signed_per_row"] = stats(
        [f(r[f"i_into_rbl_r{k}_sense_a"]) for r in ok for k in ROWS
         if str(k) != r["sel_row"] and f(r[f"i_into_rbl_r{k}_sense_a"]) is not None])
    return out


def analyze(rows, args):
    corners, temps = args.corners, args.temps_c
    cov = check_coverage(rows, corners, temps, args.ages, args.rows, range(16))
    groups = []
    for c, t, a in itertools.product(corners, temps, args.ages):
        pt = [r for r in rows if (r["corner"], r["temp_c"], r["age_label"]) == (c, str(t), a)]
        for s in args.rows:
            g = group_summary([r for r in pt if r["sel_row"] == str(s)])
            groups.append({"scope": "per_selected_row", "corner": c, "temp_c": t, "age": a, "sel_row": s, **g})
        g = group_summary(pt)
        groups.append({"scope": "column_all_rows", "corner": c, "temp_c": t, "age": a, "sel_row": None, **g})
    return cov, groups


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results-csv", default=str(RESULTS_CSV))
    ap.add_argument("--run-id")
    ap.add_argument("--corners", nargs="+", default=CORNERS)
    ap.add_argument("--temps-c", nargs="+", type=int, default=TEMPS)
    ap.add_argument("--ages", nargs="+", default=AGES)
    ap.add_argument("--rows", nargs="+", type=int, default=ROWS)
    ap.add_argument("--min-separation-v", type=float, default=None,
                    help="optional gate: every group's worst-case separation must be >= this")
    ap.add_argument("--summary-out", help="summary JSON path (default results/summary_<run_id>.json; never overwritten)")
    ap.add_argument("--no-summary", action="store_true")
    a = ap.parse_args(argv)

    run_id, rows = load(Path(a.results_csv), a.run_id)
    cov, groups = analyze(rows, a)
    cov_ok = not (cov["missing"] or cov["duplicates"] or cov["unexpected"] or cov["missing_provenance"])
    n_fail_pts = sum(1 for r in rows if r["status"] != "ok")
    gated = []
    if a.min_separation_v is not None:
        for g in groups:
            s = g["worst_case_separation_v"]
            if s is None or s < a.min_separation_v:
                gated.append({k: g[k] for k in ("scope", "corner", "temp_c", "age", "sel_row")} | {"worst_case_separation_v": s})
    first = rows[0]
    summary = {
        "run_id": run_id,
        "provenance": {k: first[k] for k in ("repo_git_sha", "pdk_open_pdks_commit", "ngspice_version", "timestamp_utc")},
        "sign_convention": "separation = V(rbl|stored0) - V(rbl|stored1) at t_sense; i_into_rbl positive = rwl -> M_RD -> rbl",
        "assumptions": {"c_rbl_ff": first["c_rbl_ff_ASSUMPTION"], "t_sense_s": first["t_sense_s_ASSUMPTION"],
                        "latency_dv_v": first["dv_latency_v_ASSUMPTION"], "c_sn_ff": first["c_sn_ff"],
                        "loading_basis": "schematic-level assumed rbl load; no extracted bitline parasitics"},
        "claims": {"sense_decision_implemented": False, "offset_yield_validated": False,
                   "all_corner_functional_pass": False},
        "coverage": cov, "coverage_ok": cov_ok, "n_points": len(rows), "n_sim_failed": n_fail_pts,
        "threshold_check": {"min_separation_v": a.min_separation_v, "n_groups_failing": len(gated), "failing": gated},
        "groups": groups,
    }
    if not a.no_summary:
        out = Path(a.summary_out) if a.summary_out else HERE / "results" / f"summary_{run_id}.json"
        if out.exists():
            print(f"ERROR: refusing to overwrite existing evidence {out}", file=sys.stderr)
            return 1
        out.write_text(json.dumps(summary, indent=1) + "\n")
        print(f"wrote {out}")
    ok_groups = [g for g in groups if g["worst_case_separation_v"] is not None]
    print(f"run {run_id}: {len(rows)} points, {n_fail_pts} sim_failed, coverage_ok={cov_ok}; "
          f"{sum(1 for g in ok_groups if g['single_reference_exists'])}/{len(groups)} groups have worst-case separation > 0")
    if not cov_ok:
        print(f"COVERAGE/PROVENANCE FAIL: missing={len(cov['missing'])} dup={len(cov['duplicates'])} "
              f"unexpected={len(cov['unexpected'])} no-provenance={len(cov['missing_provenance'])}", file=sys.stderr)
        return 1
    if gated:
        print(f"THRESHOLD FAIL: {len(gated)}/{len(groups)} groups below {a.min_separation_v} V", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
