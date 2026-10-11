#!/usr/bin/env python3
"""Reduce the issue #88 loaded-column `klt sim` reports (stdlib only).

Two modes:

  --ingest REPORT... --campaign RUN_ID
      Copy raw `klt sim --format json` reports into results/<RUN_ID>/ as
      klt_report_<variant>_<age>.json.gz (gzip, mtime 0), with the batch
      bucket name redacted (`<redacted-bucket>`); refuses to overwrite.

  results/<RUN_ID>   (positional)
      Reads every klt_report_*.json.gz in that directory and writes, NEW files
      only (refuses to overwrite):
        cases.csv.gz  one row per (variant, corner, temp, age, sel_row, pattern),
                      Phase 2 field names (run_loaded_column.FIELDS subset)
        summary.json  per-point evaluation with the cold-corner study's own
                      criteria (cold-corner/analyze_variants.evaluate_point,
                      imported, not copied), the reproduction check of the
                      10 fF reference against the committed Phase 2 run, the
                      negative-control check and the old-vs-new comparison.

Exit: 0 = coverage, reproduction and negative control OK; 1 = any of those
failed (the files are still written: failures are evidence); 2 = refused.

Criteria (study ASSUMPTIONS, cold-corner/variants.py, NOT spec values):
separation >= 0.1 V, every stored-'1' case reaches the 0.1 V droop by
t_sense = 10 ns, |read disturb| <= 0.1 V, 64/64 cases.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LC_DIR = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(LC_DIR))
sys.path.insert(0, str(LC_DIR / "cold-corner"))
import analyze_variants as AV  # noqa: E402  (cold-corner criteria + evaluate_point)
import gen_column_klt as G  # noqa: E402
import run_loaded_column as R  # noqa: E402
import variants as VV  # noqa: E402

RESULTS = HERE / "results"
PHASE2_CSV = LC_DIR / "results" / "loaded_column_results.csv"
PHASE2_RUN_ID = AV.PHASE2_RUN_ID
REF_ID = "ref_crbl_10f"
NC_ID = "nc_write_disabled_ext4row"
# Reproduction acceptance, declared before the fleet results were read: the
# 10 fF reference through this harness must give the committed Phase 2
# worst-case separation within 1 mV at every grid point, and the same PASS/FAIL
# verdict at every point.
REPRO_SEP_TOL_V = 1e-3
KEY = ("corner", "temp_c", "age_label", "sel_row", "pattern_rows3210")
EXTRA = ["variant_id", "variant_class", "c_rbl_ff", "c_rbl_label", "cell_card", "klt_job_id",
         "netlist_sha256", "klt_version", "corner_status", "v_sn_sel_sense_v"]
FIELDS = EXTRA + list(R.FIELDS)


def write_gz(path: Path, text: str) -> None:
    """Deterministic gzip (no name, mtime 0) so a re-run reproduces the bytes."""
    with path.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
        gz.write(text.encode())


def read_gz(path: Path) -> str:
    with gzip.open(path, "rt") as fh:
        return fh.read()


def report_name(rep: dict) -> tuple[str, str]:
    path = rep["netlist"]["path"] if isinstance(rep.get("netlist"), dict) else str(rep.get("netlist", ""))
    m = re.fullmatch(r"(.+)_(fresh|refresh_bound)\.spice", Path(path).name)
    if not m or m.group(1) not in G.variants():
        raise ValueError(f"not an issue #88 loaded-column report: {path}")
    return m.group(1), m.group(2)


def ingest(paths: list[str], campaign: str) -> int:
    out = RESULTS / campaign
    out.mkdir(parents=True, exist_ok=True)
    for p in paths:
        text = Path(p).read_text()
        rep = json.loads(text)
        vid, age = report_name(rep)
        bucket = (rep.get("environment", {}).get("remote") or {}).get("bucket")
        if bucket and bucket != "<redacted-bucket>":
            text = text.replace(bucket, "<redacted-bucket>")
        dst = out / f"klt_report_{vid}_{age}.json.gz"
        if dst.exists():
            print(f"refusing to overwrite {dst}", file=sys.stderr)
            return 2
        write_gz(dst, text if text.endswith("\n") else text + "\n")
        print(f"ingested {dst}")
    return 0


def case_rows(rep: dict, run_id: str) -> list[dict]:
    vid, age = report_name(rep)
    V = G.variants()[vid]
    P = G.timing()
    tr, t_late = G.t_read(P, age), G.t_late(P, age)
    env = rep.get("environment", {})
    remote = env.get("remote") or {}
    rows = []
    for c in rep["corners"]:
        meas = {m["name"]: m["value"] for m in c["measurements"]}
        for k in G.cases():
            t, sel, pattern = k["tag"], k["sel"], k["pattern"]
            bits = [(pattern >> r) & 1 for r in range(G.N_ROWS)]
            row = {f: "" for f in FIELDS}
            row.update({
                "variant_id": vid, "variant_class": V["cls"], "c_rbl_ff": f"{V['c_rbl_f'] * 1e15:.6f}",
                "c_rbl_label": V["c_rbl_label"], "cell_card": V["card"],
                "klt_job_id": remote.get("job_id", ""), "netlist_sha256": env.get("netlist_sha256", ""),
                "klt_version": rep.get("provenance", {}).get("klt_version", ""),
                "corner_status": c["status"],
                "run_id": run_id, "timestamp_utc": run_id,
                "repo_git_sha": f"deck sha256 {env.get('netlist_sha256', '')[:16]}",
                "pdk_open_pdks_commit": R.PDK_OPEN_PDKS_COMMIT,
                "ngspice_version": f"ngspice-{env.get('engine_version', '')}",
                "corner": c["process"], "temp_c": str(c["temperature_c"]), "age_label": age,
                "sel_row": str(sel), "stored_value": str(bits[sel]),
                "pattern_rows3210": "".join(str(bits[r]) for r in reversed(range(G.N_ROWS))),
                "other_rows_pattern": "".join(str(bits[r]) for r in reversed(range(G.N_ROWS)) if r != sel),
                "c_sn_ff": "0.605354", "c_rbl_ff_ASSUMPTION": f"{V['c_rbl_f'] * 1e15:.6f}",
                "vdd_v": R.VDD, "vrbl_precharge_v": P["VRBL"], "t_read_s": f"{tr:.9e}",
                "t_sense_s_ASSUMPTION": G.T_SENSE_S, "dv_latency_v_ASSUMPTION": G.DV_LATENCY_V,
                "sel_row_age_at_read_s": f"{tr - (P['TW0'] + sel * P['TWSTEP'] + P['TWPULSE']):.6e}",
                "max_row_age_at_read_s": f"{tr - (P['TW0'] + P['TWPULSE']):.6e}",
                "notes": f"issue #88 klt parallel-instance harness; C_RBL {V['c_rbl_label']}; "
                         "per-row rwl currents not measured",
            })
            names = ["wo", "aw", "ss", "rf", "rs", "re", "lat"] + [f"pr{r}" for r in range(4)] + [f"en{r}" for r in range(4)]
            v = {n: meas.get(f"{n}_{t}") for n in names}
            missing = [n for n, x in v.items() if x is None]
            if c["status"] != "pass" or missing:
                row["status"] = "sim_failed"
                row["reason"] = f"klt corner status {c['status']}; missing {missing}"[:400]
                rows.append(row)
                continue
            row[f"v_sn_r{sel}_wl_off_v"] = f"{v['wo']:.6e}"
            row[f"v_sn_r{sel}_after_write_v"] = f"{v['aw']:.6e}"
            for r in range(G.N_ROWS):
                row[f"v_sn_r{r}_preread_v"] = f"{v[f'pr{r}']:.6e}"
            row["v_rbl_preread_float_v"] = f"{v['rf']:.6e}"
            row["v_rbl_sense_v"] = f"{v['rs']:.6e}"
            row["v_rbl_end_v"] = f"{v['re']:.6e}"
            row["dv_rbl_sense_v"] = f"{v['rs'] - v['rf']:.6e}"
            row["v_sn_sel_sense_v"] = f"{v['ss']:.6e}"
            if v["lat"] < t_late:
                row["latency_s"] = f"{v['lat'] - tr:.6e}"
            else:
                row["latency_reason"] = (f"rbl never fell {G.DV_LATENCY_V} V below its held pre-read level "
                                         f"before {t_late - tr:.4e} s after the select edge")
            row["dv_sn_sel_read_disturb_v"] = f"{v[f'en{sel}'] - v[f'pr{sel}']:.6e}"
            d = [v[f"en{r}"] - v[f"pr{r}"] for r in range(G.N_ROWS) if r != sel]
            row["dv_sn_unsel_worst_signed_v"] = f"{max(d, key=abs):.6e}"
            row["status"] = "ok"
            rows.append(row)
    return rows


def expected_points(vid: str, age: str) -> list[tuple[str, int]]:
    scope = next(s for (v, a, s) in G.REQUESTS if v == vid and a == age)
    sc = G.SCOPES[scope]
    return [(c, t) for c in sc["process"] for t in sc["temperature_c"]]


def evaluate(rows: list[dict]) -> dict:
    out: dict = {}
    for vid in G.variants():
        pts = []
        for age in G.AGES:
            if not any((v, a) == (vid, age) for (v, a, _s) in G.REQUESTS):
                continue
            for c, t in expected_points(vid, age):
                rs = [r for r in rows if (r["variant_id"], r["corner"], r["temp_c"], r["age_label"])
                      == (vid, c, str(t), age)]
                e = AV.evaluate_point(vid, rs, G.T_SENSE_S, 0.0)
                pts.append({"corner": c, "temp_c": t, "age": age, **e})
        seps = [p["worst_case_separation_v"] for p in pts if p["worst_case_separation_v"] is not None]
        out[vid] = {"variant": {k: v for k, v in G.variants()[vid].items()},
                    "n_points": len(pts), "n_points_pass": sum(p["PASS"] for p in pts),
                    "min_point_separation_v": min(seps) if seps else None,
                    "points": pts}
    return out


def phase2_points() -> dict:
    s = json.loads((LC_DIR / "cold-corner" / "results" / "summary_20261005T145658Z.json").read_text())
    return {(p["corner"], p["temp_c"], p["age"]): p for p in s["variants"]["phase2_baseline"]["points"]}


def reproduction(ev: dict, rows: list[dict]) -> dict:
    p2 = phase2_points()
    ref = {(p["corner"], p["temp_c"], p["age"]): p for p in ev[REF_ID]["points"]}
    worst_sep = 0.0
    verdict_mismatch = []
    for k, p in ref.items():
        q = p2[k]
        if p["worst_case_separation_v"] is None or q["worst_case_separation_v"] is None:
            verdict_mismatch.append(list(k) + ["separation missing"])
            continue
        worst_sep = max(worst_sep, abs(p["worst_case_separation_v"] - q["worst_case_separation_v"]))
        if p["PASS"] != q["PASS"]:
            verdict_mismatch.append(list(k))
    # per-case field differences against the committed Phase 2 rows
    with PHASE2_CSV.open() as fh:
        ph = {tuple(r[x] for x in KEY): r for r in csv.DictReader(fh) if r["run_id"] == PHASE2_RUN_ID}
    fields = ["v_rbl_sense_v", "v_rbl_preread_float_v", "v_rbl_end_v", "dv_sn_sel_read_disturb_v",
              "dv_sn_unsel_worst_signed_v"] + [f"v_sn_r{r}_preread_v" for r in range(4)]
    worst = {f: 0.0 for f in fields + ["after_write_sel", "latency_s"]}
    lat_presence_mismatch = 0
    n = 0
    for r in rows:
        if r["variant_id"] != REF_ID or r["status"] != "ok":
            continue
        q = ph.get(tuple(r[x] for x in KEY))
        if q is None:
            continue
        n += 1
        for f in fields:
            worst[f] = max(worst[f], abs(float(r[f]) - float(q[f])))
        s = r["sel_row"]
        worst["after_write_sel"] = max(worst["after_write_sel"], abs(float(r[f"v_sn_r{s}_after_write_v"])
                                                                    - float(q[f"v_sn_r{s}_after_write_v"])))
        if bool(r["latency_s"]) != bool(q["latency_s"]):
            lat_presence_mismatch += 1
        elif r["latency_s"]:
            worst["latency_s"] = max(worst["latency_s"], abs(float(r["latency_s"]) - float(q["latency_s"])))
    ok = (n == 1920 and worst_sep <= REPRO_SEP_TOL_V and not verdict_mismatch and lat_presence_mismatch == 0)
    return {"reference_variant": REF_ID, "against": f"committed Phase 2 run {PHASE2_RUN_ID}",
            "sep_tol_v": REPRO_SEP_TOL_V, "points_compared": len(ref), "cases_compared": n,
            "worst_point_separation_abs_diff_v": worst_sep, "verdict_mismatch_points": verdict_mismatch,
            "latency_reached_mismatch_cases": lat_presence_mismatch,
            "worst_case_field_abs_diff": worst, "ok": ok}


def negative_control(ev: dict) -> dict:
    pts = ev[NC_ID]["points"]
    seps = [p["worst_case_separation_v"] for p in pts]
    ok = bool(pts) and all(not p["PASS"] for p in pts) and all(s is not None and s < 0 for s in seps)
    return {"variant": NC_ID, "all_points_fail": all(not p["PASS"] for p in pts),
            "all_separations_negative": all(s is not None and s < 0 for s in seps),
            "separations_v": {f"{p['corner']}/{p['temp_c']}/{p['age']}": p["worst_case_separation_v"] for p in pts},
            "behaves_as_expected": ok}


def comparison(ev: dict) -> dict:
    """Old (committed Phase 2, 10 fF) vs new, per grid point."""
    p2 = phase2_points()
    new_ids = [v for v in G.variants() if v != NC_ID]
    table = []
    for (c, t, a), q in sorted(p2.items(), key=lambda kv: (kv[0][2], kv[0][0], kv[0][1])):
        row = {"corner": c, "temp_c": t, "age": a,
               "phase2_committed": {"sep_v": q["worst_case_separation_v"], "PASS": q["PASS"],
                                    "latency_max_s": (q["latency_stored1_s"] or {}).get("max"),
                                    "n_latency_missing": q["n_latency_missing_stored1"]}}
        for vid in new_ids:
            p = next((p for p in ev[vid]["points"] if (p["corner"], p["temp_c"], p["age"]) == (c, t, a)), None)
            if p is not None:
                row[vid] = {"sep_v": p["worst_case_separation_v"], "PASS": p["PASS"],
                            "criteria": p["criteria"],
                            "latency_max_s": (p["latency_stored1_s"] or {}).get("max"),
                            "n_latency_missing": p["n_latency_missing_stored1"],
                            "read_disturb_max_v": max(x for x in (p["read_disturb_sel_abs_max_v"],
                                                                  p["read_disturb_unsel_abs_max_v"]) if x is not None)}
        table.append(row)
    verdict = {}
    for vid in new_ids:
        flips = [[r["corner"], r["temp_c"], r["age"], r["phase2_committed"]["PASS"], r[vid]["PASS"]]
                 for r in table if vid in r and r[vid]["PASS"] != r["phase2_committed"]["PASS"]]
        seps = [r[vid]["sep_v"] for r in table if vid in r and r[vid]["sep_v"] is not None]
        mins = min(((r[vid]["sep_v"], r["corner"], r["temp_c"], r["age"]) for r in table
                    if vid in r and r[vid]["sep_v"] is not None), default=None)
        verdict[vid] = {"points_pass": sum(1 for r in table if vid in r and r[vid]["PASS"]),
                        "points": sum(1 for r in table if vid in r),
                        "min_separation_over_grid": None if mins is None else
                        {"sep_v": mins[0], "corner": mins[1], "temp_c": mins[2], "age": mins[3]},
                        "verdict_flips_vs_phase2": flips, "n_seps": len(seps)}
    return {"per_point": table, "per_variant": verdict}


def sha256(p: Path) -> str:
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()


def analyze(run_dir: Path) -> int:
    run_id = run_dir.name
    out_csv, out_json = run_dir / "cases.csv.gz", run_dir / "summary.json"
    for p in (out_csv, out_json):
        if p.exists():
            print(f"refusing to overwrite existing evidence file {p}", file=sys.stderr)
            return 2
    reports = sorted(run_dir.glob("klt_report_*.json.gz"))
    rows, jobs, errors = [], {}, []
    for p in reports:
        rep = json.loads(read_gz(p))
        vid, age = report_name(rep)
        remote = rep.get("environment", {}).get("remote") or {}
        jobs[f"{vid}_{age}"] = {"file": p.name, "klt_status": rep.get("status"),
                                "corners": rep.get("corner_count"), "errored": rep.get("errored"),
                                "job_id": remote.get("job_id"), "instance_type": remote.get("instance_type"),
                                "elapsed_seconds": remote.get("elapsed_seconds"),
                                "netlist_sha256": rep.get("environment", {}).get("netlist_sha256"),
                                "engine_version": rep.get("environment", {}).get("engine_version"),
                                "klt_version": rep.get("provenance", {}).get("klt_version")}
        deck = G.DECKS / f"{vid}_{age}.spice"
        if not deck.is_file() or sha256(deck) != jobs[f"{vid}_{age}"]["netlist_sha256"]:
            errors.append(f"{vid}_{age}: report netlist_sha256 does not match committed decks/{deck.name}")
        rows += case_rows(rep, run_id)
    want = {f"{v}_{a}" for (v, a, _s) in G.REQUESTS}
    if set(jobs) != want:
        errors.append(f"reports missing for {sorted(want - set(jobs))}")
    for (v, a, _s) in G.REQUESTS:
        n = sum(1 for r in rows if (r["variant_id"], r["age_label"]) == (v, a))
        exp = 64 * len(expected_points(v, a))
        if n != exp:
            errors.append(f"{v}/{a}: {n} case rows, expected {exp}")
    bad = sum(1 for r in rows if r["status"] != "ok")
    if bad:
        errors.append(f"{bad} case rows sim_failed")
    ev = evaluate(rows)
    repro = reproduction(ev, rows) if f"{REF_ID}_fresh" in jobs else {"ok": False, "reason": "no reference"}
    nc = negative_control(ev) if f"{NC_ID}_fresh" in jobs else {"behaves_as_expected": False}
    if not repro["ok"]:
        errors.append("reproduction of the committed Phase 2 run failed")
    if not nc["behaves_as_expected"]:
        errors.append("negative control did not fail as required")
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    write_gz(out_csv, buf.getvalue())
    summary = {
        "run_id": run_id, "issue": 88,
        "deck_provenance": "each report's netlist_sha256 equals sha256 of the committed decks/<variant>_<age>.spice "
                           "(checked; generated by gen_column_klt.py, `--check` detects drift)",
        "baseline_periphery": "IDEAL (ideal drivers and precharge switch; PR #118 / issue #114 real periphery not merged)",
        "c_rbl_source": G.extracted_provenance(),
        "c_rbl_interpretation": ("the lumped C_RBL is the WHOLE read-bitline load in these decks; the "
                                 "extracted value is used INSTEAD of 10 fF, not added to it. With the "
                                 "extracted 0.859 fF the sense-input load share of the 10 fF is removed: "
                                 "a bounding (lightest-load) case. 2 fF is an ASSUMPTION mid-point."),
        "criteria_ASSUMPTIONS": {"sep_min_v": VV.SEP_MIN_V, "disturb_max_v": VV.DISTURB_MAX_V,
                                 "t_sense_s": G.T_SENSE_S, "dv_latency_v": G.DV_LATENCY_V},
        "claims": {"spec_changed": False, "n_rows_ratified": False, "sense_decision_implemented": False,
                   "offset_yield_validated": False, "extracted_c_rbl_used": True,
                   "real_periphery_used": False},
        "fleet_jobs": jobs, "errors": errors, "reproduction": repro, "negative_control": nc,
        "comparison_vs_phase2": comparison(ev), "variants": ev,
    }
    out_json.write_text(json.dumps(summary, indent=1) + "\n")
    print(f"wrote {out_csv.name} ({len(rows)} rows) and {out_json.name}")
    for vid, e in ev.items():
        print(f"  {vid:28s} {e['n_points_pass']:2d}/{e['n_points']:2d} PASS, min sep {e['min_point_separation_v']}")
    print(f"  reproduction ok={repro['ok']}  negative control ok={nc['behaves_as_expected']}")
    for e in errors:
        print("ERROR:", e, file=sys.stderr)
    return 1 if errors else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("run_dir", nargs="?", type=Path)
    ap.add_argument("--ingest", nargs="+")
    ap.add_argument("--campaign")
    a = ap.parse_args(argv)
    if a.ingest:
        if not a.campaign:
            ap.error("--ingest needs --campaign RUN_ID")
        return ingest(a.ingest, a.campaign)
    if a.run_dir is None:
        ap.error("give results/<RUN_ID> or --ingest")
    return analyze(a.run_dir)


if __name__ == "__main__":
    raise SystemExit(main())
