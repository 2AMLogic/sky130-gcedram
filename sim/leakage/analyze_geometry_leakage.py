#!/usr/bin/env python3
"""Reduce a `klt sim` report of the geometry-matched leakage study (issue #149).

Stdlib only. Reads a committed ``geometry-matched/results/klt_report_<RUN_ID>.json`` and writes
NEW files next to it (refuses to overwrite):

* ``geom_leakage_points_<RUN_ID>.csv``   one row per PVT point: extracted-geometry current,
  same-batch legacy-geometry control, the historical ``leakage_results.csv`` row (identity + sha256),
  and ratios computed from those numbers
* ``geom_leakage_summary_<RUN_ID>.json`` provenance, geometry, measured maximum and its PVT

Comparison labels: "legacy testbench geometry" = the card in tb_access_leakage.spice.tmpl (no
ad/as/pd/ps). ``ratio_vs_historical`` divides by the committed CSV row (different engine/date, see
``engine_confound``); ``ratio_vs_control`` divides by the legacy-geometry DUT in the SAME batch
request and so isolates geometry. Nothing is hardcoded: the worst case is whatever the data says.
A failed/incomplete report, a missing/duplicate/unexpected PVT key, a non-finite current, an
ambiguous baseline or a non-positive denominator is an error, never a zero.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gen_geometry_leakage as G  # noqa: E402

LEGACY_CSV = HERE / "results" / "leakage_results.csv"
BIAS = {"vgs_v": 0.0, "vds_v": G.VDD_V, "vbs_v": 0.0}


class AnalysisError(ValueError):
    pass


def _finite_pos(x, what):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x <= 0:
        raise AnalysisError(f"{what}: need a finite positive current, got {x!r}")
    return float(x)


def extract_points(report: dict, request: dict | None = None) -> dict:
    """{(corner, temp_c): (i_ext, i_leg)} -- exactly the request's Cartesian product."""
    request = request or G.build_request()
    if report.get("status") != "pass" or report.get("errored") or report.get("failed"):
        raise AnalysisError(f"report not successful: status={report.get('status')!r} "
                            f"failed={report.get('failed')} errored={report.get('errored')}")
    want = {(p, t) for p in request["corners"]["process"] for t in request["corners"]["temperature_c"]}
    out: dict = {}
    for c in report.get("corners") or []:
        key = (c.get("process"), c.get("temperature_c"))
        if key in out:
            raise AnalysisError(f"duplicate PVT point {key}")
        if c.get("status") != "pass":
            raise AnalysisError(f"corner {key} status {c.get('status')!r}")
        m = {}
        for e in c.get("measurements") or []:
            if e["name"] in m:
                raise AnalysisError(f"corner {key}: duplicate measurement {e['name']}")
            if e.get("status") != "pass":
                raise AnalysisError(f"corner {key}: measurement {e['name']} status {e.get('status')!r}")
            m[e["name"]] = e.get("value")
        for n in (G.MEAS_EXT, G.MEAS_LEG):
            if n not in m:
                raise AnalysisError(f"corner {key}: missing measurement {n}")
        out[key] = (_finite_pos(m[G.MEAS_EXT], f"{key} {G.MEAS_EXT}"),
                    _finite_pos(m[G.MEAS_LEG], f"{key} {G.MEAS_LEG}"))
    if set(out) != want:
        raise AnalysisError(f"PVT set mismatch: missing {sorted(want - set(out))}, unexpected {sorted(set(out) - want)}")
    return out


def load_legacy(path: Path = LEGACY_CSV) -> list[dict]:
    raw = Path(path).read_text().splitlines()
    rows = list(csv.DictReader(raw))
    for i, r in enumerate(rows):
        r["_line"] = i + 2
        r["_row_sha256"] = hashlib.sha256(raw[i + 1].encode()).hexdigest()
    return rows


def select_baseline(rows: list[dict], corner: str, temp_c: int, geometry: dict, timestamp: str | None = None) -> dict:
    hits = []
    for r in rows:
        try:
            ok = (r["corner"] == corner and int(float(r["temp_c"])) == temp_c and r["device"] == G.DEVICE
                  and math.isclose(float(r["w_um"]), G.LEGACY_W_UM) and math.isclose(float(r["l_um"]), G.LEGACY_L_UM)
                  and all(math.isclose(float(r[k]), v) for k, v in BIAS.items()))
        except (KeyError, ValueError):
            continue
        if ok and (timestamp is None or r["timestamp_utc"] == timestamp):
            hits.append(r)
    if not hits:
        raise AnalysisError(f"no historical row for {corner}/{temp_c}C")
    if len(hits) > 1:
        raise AnalysisError(f"ambiguous baseline for {corner}/{temp_c}C ({len(hits)} rows); pass --baseline-timestamp")
    return hits[0]


def build_rows(points: dict, legacy: list[dict], geometry: dict, timestamp: str | None = None) -> list[dict]:
    rows = []
    for (corner, temp) in sorted(points, key=lambda k: (G.PROCESS_CORNERS.index(k[0]), k[1])):
        i_ext, i_leg = points[(corner, temp)]
        b = select_baseline(legacy, corner, temp, geometry, timestamp)
        i_hist = _finite_pos(float(b["ileak_a"]), f"historical {corner}/{temp}")
        rows.append({
            "corner": corner, "temp_c": temp,
            "i_extracted_a": f"{i_ext:.9e}", "i_control_legacy_geom_a": f"{i_leg:.9e}",
            "i_historical_legacy_geom_a": b["ileak_a"],
            "ratio_vs_control": f"{i_ext / i_leg:.6f}", "ratio_vs_historical": f"{i_ext / i_hist:.6f}",
            "control_vs_historical": f"{i_leg / i_hist:.6f}",
            "historical_csv_line": b["_line"], "historical_row_sha256": b["_row_sha256"],
            "historical_timestamp_utc": b["timestamp_utc"], "historical_ngspice": b["ngspice_version"],
        })
    return rows


def summarize(rows: list[dict], report: dict, geom_info: dict, paths: dict) -> dict:
    def num(r, k): return float(r[k])
    wmax = max(rows, key=lambda r: num(r, "i_extracted_a"))
    rmax = max(rows, key=lambda r: num(r, "ratio_vs_control"))
    rmin = min(rows, key=lambda r: num(r, "ratio_vs_control"))
    env = report.get("environment", {})
    return {
        "issue": 149,
        "comparison_label": "extracted drawn diffusion vs LEGACY TESTBENCH geometry (no ad/as/pd/ps)",
        "n_points": len(rows),
        "geometry": geom_info["geometry"], "geometry_units": {"l,w,pd,ps": "um", "ad,as": "um^2"},
        "extraction_input": {k: geom_info[k] for k in ("input_path", "input_sha256", "device_names")},
        "worst_case_extracted": {"corner": wmax["corner"], "temp_c": wmax["temp_c"],
                                 "i_extracted_a": num(wmax, "i_extracted_a"),
                                 "i_historical_legacy_geom_a": num(wmax, "i_historical_legacy_geom_a"),
                                 "ratio_vs_control": num(wmax, "ratio_vs_control"),
                                 "ratio_vs_historical": num(wmax, "ratio_vs_historical")},
        "max_ratio_vs_control": {"corner": rmax["corner"], "temp_c": rmax["temp_c"], "ratio": num(rmax, "ratio_vs_control")},
        "min_ratio_vs_control": {"corner": rmin["corner"], "temp_c": rmin["temp_c"], "ratio": num(rmin, "ratio_vs_control")},
        "engine_confound": {"report_engine": env.get("engine"), "report_engine_version": env.get("engine_version"),
                            "historical_ngspice": sorted({r["historical_ngspice"] for r in rows}),
                            "note": "ratio_vs_control isolates geometry (same batch, same engine/PDK); "
                                    "ratio_vs_historical additionally includes any engine-version difference"},
        "pdk_open_pdks_commit": G_pin(),
        "batch": env.get("remote"), "models_lib_sha256": env.get("models_lib_sha256"),
        "netlist_sha256_reported": env.get("netlist_sha256"),
        "klt_provenance": report.get("provenance"),
        "files": paths,
    }


def G_pin() -> str:
    sys.path.insert(0, str(HERE.parent))
    from _evidence_common import PDK_OPEN_PDKS_COMMIT
    return PDK_OPEN_PDKS_COMMIT


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("report", type=Path, help="geometry-matched/results/klt_report_<RUN_ID>.json")
    ap.add_argument("--baseline-timestamp", default=None, help="select the historical run when rows are ambiguous")
    a = ap.parse_args(argv)
    run_id = a.report.stem.split("klt_report_", 1)[1]
    pts = a.report.with_name(f"geom_leakage_points_{run_id}.csv")
    summ = a.report.with_name(f"geom_leakage_summary_{run_id}.json")
    for p in (pts, summ):
        if p.exists():
            print(f"refusing to overwrite existing evidence file {p}", file=sys.stderr)
            return 2
    rep = json.loads(a.report.read_text())
    try:
        points = extract_points(rep)
        info = G.load_geometry()
        rows = build_rows(points, load_legacy(), info["geometry"], a.baseline_timestamp)
    except (AnalysisError, G.GeometryError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    with pts.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    def rel(p): return str(p.resolve().relative_to(G.REPO))
    paths = {"deck_sha256": G.sha256_file(G.DECK_PATH), "request_sha256": G.sha256_file(G.REQUEST_PATH),
             "report": rel(a.report), "report_sha256": G.sha256_file(a.report), "points_csv": rel(pts),
             "legacy_csv": rel(LEGACY_CSV), "legacy_csv_sha256": G.sha256_file(LEGACY_CSV)}
    summ.write_text(json.dumps(summarize(rows, rep, info, paths), indent=2) + "\n")
    print(f"wrote {pts} and {summ}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
