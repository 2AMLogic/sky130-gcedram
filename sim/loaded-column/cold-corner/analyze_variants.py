#!/usr/bin/env python3
"""Analyze the cold-corner variant study (issue #47).

Inputs (all committed, append-only):
  results/variant_results.csv          run_variants.py output (latest run per variant)
  results/phase2_reproduction.csv      the UNCHANGED Phase 2 runner re-run at fs/ss -40 C
  ../results/loaded_column_results.csv the committed Phase 2 campaign (run 20261005T102906Z),
                                       evaluated here as pseudo-variant `phase2_baseline`

What it does:
  1. Coverage + provenance per variant against its declared scope (variants.py).
  2. Reproduction: the re-run Phase 2 points and the harness `baseline` variant
     must equal the committed Phase 2 values (every measured field).
  3. Per (variant, corner, temp, age) point: column-wide signed worst-case
     separation, worst-case patterns, latency, read disturb, stored-level
     decomposition, and PASS/FAIL against the declared criteria:
        separation >= SEP_MIN_V, every stored-'1' latency reached by t_sense,
        |read disturb| <= DISTURB_MAX_V (selected and unselected rows),
        all 64 cases simulated.
     The criteria are study ASSUMPTIONS (variants.py), not spec values.
  4. Negative control `nc_write_disabled` must FAIL with negative separation.
  5. Writes results/summary_<stamp>.json and results/pass_fail_<stamp>.csv
     (refuses to overwrite).

Exit codes:
  0  coverage, provenance, reproduction and negative-control checks OK
     (and optional gates met)
  1  coverage/provenance/reproduction failure, or a negative control passed
  2  an optional gate failed: --min-separation-v (every evaluated point of
     the --gate-variants) or --require-pass VARIANT (all points PASS).
     A deliberately impossible --min-separation-v 50 must exit 2.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import itertools
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import analyze_loaded_column as A  # noqa: E402  (Phase 2 analyzer: group_summary)
import variants as V  # noqa: E402

VARIANT_CSV = HERE / "results" / "variant_results.csv"
REPRO_CSV = HERE / "results" / "phase2_reproduction.csv"
PHASE2_CSV = HERE.parent / "results" / "loaded_column_results.csv"
PHASE2_RUN_ID = "20261005T102906Z"
PHASE2_ID = "phase2_baseline"
NC_IDS = [v["id"] for v in V.VARIANTS if v["class"] == "negative_control"]
PROVENANCE = A.PROVENANCE
KEY = ("corner", "temp_c", "age_label", "sel_row", "pattern_rows3210")
# Every measured (non-provenance) field compared in the reproduction check.
MEASURED = (
    [f"v_sn_r{r}_{k}_v" for k in ("wl_off", "after_write", "preread") for r in range(4)]
    + ["v_rbl_preread_float_v"] + [f"i_into_rbl_r{r}_preread_a" for r in range(4)]
    + ["i_desel_sum_preread_a"] + [f"i_into_rbl_r{r}_sense_a" for r in range(4)]
    + ["i_desel_sum_sense_a", "v_rbl_sense_v", "v_rbl_end_v", "dv_rbl_sense_v", "latency_s",
       "dv_sn_sel_read_disturb_v", "dv_sn_unsel_worst_signed_v", "status"]
)


def f(x):
    return A.f(x)


def read_csv(path: Path):
    if not path.is_file():
        return []
    with path.open() as fh:
        return list(csv.DictReader(fh))


def latest_per_variant(rows):
    """{variant_id: rows of the latest run_id that contains that variant}."""
    by = {}
    for r in rows:
        by.setdefault(r["variant_id"], []).append(r)
    out = {}
    for vid, rs in by.items():
        rid = max(r["run_id"] for r in rs)
        out[vid] = [r for r in rs if r["run_id"] == rid]
    return out


def expected_points(vid):
    if vid == PHASE2_ID:
        return V.points_for_scope("grid_both")
    return V.points(vid)


def coverage(vid, rows):
    pts = expected_points(vid)
    expected = {(c, str(t), a, str(s), format(p, "04b"))
                for (c, t, a) in pts for s in range(4) for p in range(16)}
    seen = {}
    for r in rows:
        k = tuple(r[x] for x in KEY)
        seen[k] = seen.get(k, 0) + 1
    prov_bad = sum(1 for r in rows if any(not r.get(p) for p in PROVENANCE))
    knob_bad = 0
    if vid != PHASE2_ID:
        sha = V.variant_sha(vid) if vid in V.BY_ID else None
        knob_bad = sum(1 for r in rows if r.get("variant_sha") != sha)
    return {
        "expected_points": len(expected), "present_points": len(seen),
        "missing": len(expected - set(seen)), "duplicates": sum(1 for n in seen.values() if n > 1),
        "unexpected": len(set(seen) - expected), "missing_provenance": prov_bad,
        "variant_sha_mismatch": knob_bad,
        "ok": not (expected - set(seen)) and all(n == 1 for n in seen.values())
        and not (set(seen) - expected) and prov_bad == 0 and knob_bad == 0,
    }


REL_TOL = 2e-6  # values are written with 7 significant digits ("%.6e")


def reproduce(rows, ref_by_key, rel_tol=REL_TOL):
    """Compare every MEASURED field of rows against the committed Phase 2 run.
    Values are written with 7 significant digits, so the tolerance is one to
    two units in the last written digit (relative). Bit-identical rows are
    counted separately: the unchanged Phase 2 runner reproduces every string
    exactly, while the re-rendered harness deck differs from it only in
    last-digit rounding (different but equal-valued parameter expressions)."""
    n = n_exact = 0
    worst = {"field": None, "abs_diff": 0.0, "rel_diff": 0.0, "key": None}
    missing_ref = 0
    for r in rows:
        k = tuple(r[x] for x in KEY)
        ref = ref_by_key.get(k)
        if ref is None:
            missing_ref += 1
            continue
        n += 1
        exact = True
        for fld in MEASURED:
            a, b = r.get(fld, ""), ref.get(fld, "")
            if a == b:
                continue
            fa, fb = f(a), f(b)
            if fa is None or fb is None:
                d = rel = float("inf")
            else:
                d = abs(fa - fb)
                rel = d / max(abs(fa), abs(fb))
            exact = False
            if rel > worst["rel_diff"]:
                worst = {"field": fld, "abs_diff": d, "rel_diff": rel, "key": list(k)}
        n_exact += exact
    ok = n > 0 and missing_ref == 0 and worst["rel_diff"] <= rel_tol
    return {"n_compared": n, "n_bit_identical": n_exact, "missing_reference": missing_ref,
            "rel_tol": rel_tol, "worst": worst, "ok": ok}


def worst_patterns(rs):
    ok = [r for r in rs if r["status"] == "ok" and f(r["v_rbl_sense_v"]) is not None]
    s1 = [r for r in ok if r["stored_value"] == "1"]
    s0 = [r for r in ok if r["stored_value"] == "0"]
    w1 = max(s1, key=lambda r: f(r["v_rbl_sense_v"])) if s1 else None
    w0 = min(s0, key=lambda r: f(r["v_rbl_sense_v"])) if s0 else None
    pick = lambda r: None if r is None else {
        "sel_row": int(r["sel_row"]), "pattern_rows3210": r["pattern_rows3210"],
        "other_rows_pattern": r["other_rows_pattern"], "v_rbl_sense_v": f(r["v_rbl_sense_v"])}
    return {"stored1_highest_rbl": pick(w1), "stored0_lowest_rbl": pick(w0)}


def level_chain(rs, vrwl_sel):
    """Stored-'1' level chain on the selected cell, minimum over patterns:
    end of write pulse -> after wordline fall -> pre-read -> at sense instant,
    and the read device's gate-source voltage at the sense instant."""
    ok = [r for r in rs if r["status"] == "ok" and r["stored_value"] == "1"]
    if not ok:
        return None
    sel = lambda r, k: f(r[f"v_sn_r{r['sel_row']}_{k}_v"])
    out = {k: min(sel(r, k) for r in ok) for k in ("wl_off", "after_write", "preread")}
    out = {f"v_sn1_{k}_min_v": v for k, v in out.items()}
    sense = [f(r.get("v_sn_sel_sense_v")) for r in ok if f(r.get("v_sn_sel_sense_v")) is not None]
    out["v_sn1_at_sense_min_v"] = min(sense) if sense else None
    out["vgs_rd_at_sense_min_v"] = (min(sense) - vrwl_sel) if sense else None
    return out


def evaluate_point(vid, rs, t_sense, vrwl_sel):
    g = A.group_summary(rs)
    sep = g["worst_case_separation_v"]
    dis_sel = [abs(f(r["dv_sn_sel_read_disturb_v"])) for r in rs if f(r["dv_sn_sel_read_disturb_v"]) is not None]
    dis_uns = [abs(f(r["dv_sn_unsel_worst_signed_v"])) for r in rs if f(r["dv_sn_unsel_worst_signed_v"]) is not None]
    lat = g["latency_stored1_s"]
    crit = {
        "complete": g["n_ok"] == 64 and g["n_points"] == 64,
        "separation": sep is not None and sep >= V.SEP_MIN_V,
        "latency": not g["latency_missing_stored1"] and lat is not None and lat["max"] <= t_sense,
        "read_disturb": bool(dis_sel) and max(dis_sel + dis_uns) <= V.DISTURB_MAX_V,
    }
    return {
        "worst_case_separation_v": sep,
        "v_rbl_sense_stored1_v": g["v_rbl_sense_stored1_v"],
        "v_rbl_sense_stored0_v": g["v_rbl_sense_stored0_v"],
        "worst_patterns": worst_patterns(rs),
        "latency_stored1_s": lat, "n_latency_missing_stored1": len(g["latency_missing_stored1"]),
        "read_disturb_sel_abs_max_v": max(dis_sel) if dis_sel else None,
        "read_disturb_unsel_abs_max_v": max(dis_uns) if dis_uns else None,
        "stored1_after_write_v": g["stored1_after_write_v"], "stored0_after_write_v": g["stored0_after_write_v"],
        "stored1_preread_v": g["stored1_preread_v"],
        "level_chain": level_chain(rs, vrwl_sel),
        "deselected_current_sense_a_signed_per_row": g["deselected_current_sense_a_signed_per_row"],
        "n_points": g["n_points"], "n_ok": g["n_ok"],
        "criteria": crit, "PASS": all(crit.values()),
    }


def evaluate_variant(vid, rows):
    if vid == PHASE2_ID:
        k = dict(V.BASELINE)
        info = {"class": "phase2_committed", "scope": "grid_both", "why": f"committed Phase 2 run {PHASE2_RUN_ID}",
                "changes": {}}
    else:
        k = V.knobs(vid)
        info = {x: V.BY_ID[vid][x] for x in ("class", "scope", "why", "changes")}
    pts = []
    for c, t, a in expected_points(vid):
        rs = [r for r in rows if (r["corner"], r["temp_c"], r["age_label"]) == (c, str(t), a)]
        e = evaluate_point(vid, rs, k["t_sense_s"], k["vrwl_sel_v"])
        pts.append({"corner": c, "temp_c": t, "age": a, **e})
    s1 = [f(r["v_rbl_sense_v"]) for r in rows if r["status"] == "ok" and r["stored_value"] == "1"]
    s0 = [f(r["v_rbl_sense_v"]) for r in rows if r["status"] == "ok" and r["stored_value"] == "0"]
    common = (min(s0) - max(s1)) if s1 and s0 else None
    seps = [p["worst_case_separation_v"] for p in pts if p["worst_case_separation_v"] is not None]
    return {
        "variant_id": vid, **info, "knobs": k, "run_id": rows[0]["run_id"] if rows else None,
        "n_points_evaluated": len(pts), "n_points_pass": sum(p["PASS"] for p in pts),
        "all_points_pass": bool(pts) and all(p["PASS"] for p in pts),
        "covers_full_grid_both_ages": set(expected_points(vid)) == set(V.points_for_scope("grid_both")),
        "min_point_separation_v": min(seps) if seps else None,
        "common_reference_window_v": common,
        "common_reference_v_UNVALIDATED": ((min(s0) + max(s1)) / 2 if common is not None and common > 0 else None),
        "points": pts,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variant-csv", default=str(VARIANT_CSV))
    ap.add_argument("--repro-csv", default=str(REPRO_CSV))
    ap.add_argument("--phase2-csv", default=str(PHASE2_CSV))
    ap.add_argument("--variants", nargs="+", help="restrict to these variant ids")
    ap.add_argument("--no-phase2", action="store_true", help="skip the phase2_baseline pseudo-variant")
    ap.add_argument("--min-separation-v", type=float)
    ap.add_argument("--gate-variants", nargs="+", help="variants the separation gate applies to (default: all evaluated except negative controls)")
    ap.add_argument("--require-pass", nargs="+", default=[])
    ap.add_argument("--summary-dir", default=str(HERE / "results"))
    ap.add_argument("--no-summary", action="store_true")
    a = ap.parse_args(argv)

    by_v = latest_per_variant(read_csv(Path(a.variant_csv)))
    if a.variants:
        by_v = {k: v for k, v in by_v.items() if k in a.variants}
    phase2_all = read_csv(Path(a.phase2_csv))
    phase2 = [r for r in phase2_all if r["run_id"] == PHASE2_RUN_ID]
    if phase2 and not a.no_phase2 and (not a.variants or PHASE2_ID in a.variants):
        by_v = {PHASE2_ID: phase2, **by_v}
    if not by_v:
        print("no variant rows found", file=sys.stderr)
        return 1
    errors = []
    unknown = [vid for vid in by_v if vid != PHASE2_ID and vid not in V.BY_ID]
    if unknown:
        errors.append(f"rows for undeclared variants: {unknown}")
        for vid in unknown:
            by_v.pop(vid)

    cov = {vid: coverage(vid, rs) for vid, rs in by_v.items()}
    errors += [f"coverage/provenance failed for {vid}: {c}" for vid, c in cov.items() if not c["ok"]]

    ref = {tuple(r[x] for x in KEY): r for r in phase2}
    repro = {}
    rr = read_csv(Path(a.repro_csv))
    if rr and phase2:
        rid = max(r["run_id"] for r in rr)
        repro["phase2_runner_rerun"] = reproduce([r for r in rr if r["run_id"] == rid], ref) | {"run_id": rid}
    if "baseline" in by_v and phase2:
        repro["variant_harness_baseline"] = reproduce(by_v["baseline"], ref) | {"run_id": by_v["baseline"][0]["run_id"]}
    errors += [f"reproduction failed: {k}: {v}" for k, v in repro.items() if not v["ok"]]

    ev = {vid: evaluate_variant(vid, rs) for vid, rs in by_v.items()}
    nc = {}
    for vid in NC_IDS:
        if vid in ev:
            seps = [p["worst_case_separation_v"] for p in ev[vid]["points"]]
            ok = all(not p["PASS"] for p in ev[vid]["points"]) and all(s is not None and s < 0 for s in seps)
            nc[vid] = {"all_points_fail": all(not p["PASS"] for p in ev[vid]["points"]),
                       "all_separations_negative": all(s is not None and s < 0 for s in seps),
                       "behaves_as_expected": ok}
            if not ok:
                errors.append(f"negative control {vid} did not fail as required")

    gated = []
    if a.min_separation_v is not None:
        gv = a.gate_variants or [v for v in ev if v not in NC_IDS]
        for vid in gv:
            for p in ev.get(vid, {"points": []})["points"]:
                s = p["worst_case_separation_v"]
                if s is None or s < a.min_separation_v:
                    gated.append([vid, p["corner"], p["temp_c"], p["age"], s])
    req_fail = [vid for vid in a.require_pass if vid not in ev or not ev[vid]["all_points_pass"]]

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    summary = {
        "generated_utc": stamp,
        "sign_convention": "separation = V(rbl|stored0) - V(rbl|stored1) at t_sense (column-wide worst case "
                           "over all 4 selected rows x 8 other-row patterns); positive = '1' discharged rbl further",
        "criteria_ASSUMPTIONS": {"sep_min_v": V.SEP_MIN_V, "latency": "every stored-1 point reaches the 0.1 V "
                                 "droop no later than t_sense", "disturb_max_v": V.DISTURB_MAX_V,
                                 "complete": "64/64 cases simulated"},
        "claims": {"sense_decision_implemented": False, "offset_yield_validated": False,
                   "spec_value_ratified": False, "extracted_parasitics_used": False},
        "coverage": cov, "reproduction": repro, "negative_controls": nc,
        "gate": {"min_separation_v": a.min_separation_v, "failing": gated, "require_pass": a.require_pass,
                 "require_pass_failing": req_fail},
        "errors": errors,
        "variants": ev,
    }
    if not a.no_summary:
        d = Path(a.summary_dir)
        js, pc = d / f"summary_{stamp}.json", d / f"pass_fail_{stamp}.csv"
        if js.exists() or pc.exists():
            print(f"ERROR: refusing to overwrite existing evidence {js}", file=sys.stderr)
            return 1
        js.write_text(json.dumps(summary, indent=1) + "\n")
        cols = ["variant_id", "class", "corner", "temp_c", "age", "PASS", "complete", "separation_ok",
                "latency_ok", "read_disturb_ok", "worst_case_separation_v", "stored1_highest_rbl_v",
                "stored1_worst_sel_row", "stored1_worst_pattern_rows3210", "stored0_lowest_rbl_v",
                "latency_stored1_max_s", "n_latency_missing_stored1", "read_disturb_sel_abs_max_v",
                "read_disturb_unsel_abs_max_v", "v_sn1_after_write_min_v", "v_sn1_preread_min_v",
                "v_sn1_at_sense_min_v"]
        with pc.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
            w.writeheader()
            for vid, e in ev.items():
                for p in e["points"]:
                    w1 = p["worst_patterns"]["stored1_highest_rbl"] or {}
                    w0 = p["worst_patterns"]["stored0_lowest_rbl"] or {}
                    lc = p["level_chain"] or {}
                    w.writerow({
                        "variant_id": vid, "class": e["class"], "corner": p["corner"], "temp_c": p["temp_c"],
                        "age": p["age"], "PASS": p["PASS"], "complete": p["criteria"]["complete"],
                        "separation_ok": p["criteria"]["separation"], "latency_ok": p["criteria"]["latency"],
                        "read_disturb_ok": p["criteria"]["read_disturb"],
                        "worst_case_separation_v": p["worst_case_separation_v"],
                        "stored1_highest_rbl_v": w1.get("v_rbl_sense_v"), "stored1_worst_sel_row": w1.get("sel_row"),
                        "stored1_worst_pattern_rows3210": w1.get("pattern_rows3210"),
                        "stored0_lowest_rbl_v": w0.get("v_rbl_sense_v"),
                        "latency_stored1_max_s": (p["latency_stored1_s"] or {}).get("max"),
                        "n_latency_missing_stored1": p["n_latency_missing_stored1"],
                        "read_disturb_sel_abs_max_v": p["read_disturb_sel_abs_max_v"],
                        "read_disturb_unsel_abs_max_v": p["read_disturb_unsel_abs_max_v"],
                        "v_sn1_after_write_min_v": lc.get("v_sn1_after_write_min_v"),
                        "v_sn1_preread_min_v": lc.get("v_sn1_preread_min_v"),
                        "v_sn1_at_sense_min_v": lc.get("v_sn1_at_sense_min_v"),
                    })
        print(f"wrote {js}\nwrote {pc}")

    for vid, e in ev.items():
        print(f"{vid:28s} {e['n_points_pass']:2d}/{e['n_points_evaluated']:2d} PASS  "
              f"min sep {e['min_point_separation_v'] if e['min_point_separation_v'] is None else round(e['min_point_separation_v'], 4)} V")
    for k, v in repro.items():
        print(f"reproduction {k}: {v['n_bit_identical']}/{v['n_compared']} bit-identical, ok={v['ok']}")
    if errors:
        for e in errors:
            print("ERROR:", e, file=sys.stderr)
        return 1
    if gated or req_fail:
        print(f"GATE FAIL: {len(gated)} points below --min-separation-v; require-pass failing: {req_fail}",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
