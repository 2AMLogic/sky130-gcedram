#!/usr/bin/env python3
"""Reduce `klt sim` batch reports for the bitcell-transient requests into CSV rows (issue #182).

Stdlib only; runs no simulation. Inputs are the klt reports for the requests written by
``gen_bitcell_transient.py`` (stored '1': one per corner x temp; stored '0': one per temp; read
phase: one per stored value). Appends one row per (corner, temp) to
``results/bitcell_transient_results.csv`` with the SAME columns as the local driver, and never
rewrites existing rows.

Usage:
    python3 -I sim/bitcell-transient/reduce_bitcell_transient.py --reports-dir DIR [--dry-run]
where DIR holds ``request_<...>.json`` -> ``<name>/report.json`` (klt's ``.klt/sim`` layout) or
``klt_report_<request-stem>*.json`` files, i.e. the committed ``results/klt_report_*`` copies.

``t_ret_tran_s`` comes from the fixed level ladder (a `.meas` card cannot read another `.meas`
result, so the data-dependent threshold ``v_sn_hold_start_v - delta_V`` cannot be a WHEN target):
the first falling-crossing time of each ladder level is recorded and the crossing at the
threshold is a cubic (4 nearest rungs) interpolation. Rows whose threshold falls outside the
ladder, or whose rungs were not crossed inside the window, leave ``t_ret_tran_s`` blank with a note.

PDK stamp: a row is stamped with the repo pin only when the report's
``pdk_stamp_comparison.status`` is ``match``; otherwise it is stamped ``fleet-stamp:<worker commit>``
and the note says so (the fleet's PDK is a worker-spec matter, not worked around here).
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM = HERE.parent
sys.path.insert(0, str(SIM))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SIM / "retention"))
from _evidence_common import PDK_OPEN_PDKS_COMMIT, append_result, measurements_of, repo_git_sha  # noqa: E402
from derive_retention import load_extracted_c_sn  # noqa: E402
import gen_bitcell_transient as G  # noqa: E402
import run_bitcell_transient as R  # noqa: E402


class ReduceError(RuntimeError):
    pass


def lagrange(xs: list[float], ys: list[float], x: float) -> float:
    total = 0.0
    for i, (xi, yi) in enumerate(zip(xs, ys)):
        term = yi
        for j, xj in enumerate(xs):
            if j != i:
                term *= (x - xj) / (xi - xj)
        total += term
    return total


def ladder_crossing(thr: float, ladder: dict[float, float | None]) -> float | None:
    """Time of the first falling crossing of `thr` (V) from the ladder {level_V: t_s | None}.
    Cubic through the 4 nearest rungs that were crossed; None if thr is outside the crossed rungs."""
    pts = sorted((lv, t) for lv, t in ladder.items() if t is not None)
    if len(pts) < 4 or thr < pts[0][0] or thr > pts[-1][0]:
        return None
    k = max(i for i, (lv, _) in enumerate(pts) if lv <= thr)
    lo = min(max(k - 1, 0), len(pts) - 4)
    sel = pts[lo:lo + 4]
    return lagrange([p[0] for p in sel], [p[1] for p in sel], thr)


def stamp_of(report: dict) -> tuple[str, str]:
    w = (report.get("environment", {}).get("remote") or {}).get("worker_environment") or {}
    status = (w.get("pdk_stamp_comparison") or {}).get("status", "unknown")
    text = (w.get("pdk") or {}).get("stamp_text", "unknown")
    return status, text


def load_report(path: Path) -> dict:
    rep = json.loads(Path(path).read_text())
    if rep.get("status") != "pass" or rep.get("errored") or rep.get("failed"):
        raise ReduceError(f"{path}: status={rep.get('status')!r} errored={rep.get('errored')} failed={rep.get('failed')}")
    return rep


def find_report(root: Path, stem: str) -> Path:
    for cand in (root / stem / "report.json", root / f"klt_report_{stem}.json"):
        if cand.is_file():
            return cand
    hits = sorted(root.glob(f"klt_report_{stem.removeprefix('request_')}_*.json"))
    if len(hits) == 1:
        return hits[0]
    raise ReduceError(f"no unique report for {stem} under {root}")


def by_point(rep: dict) -> dict[tuple[str, int], dict]:
    return {(c["process"], int(c["temperature_c"])): measurements_of(c, strict=True) for c in rep["corners"]}


def build_rows(root: Path, delta_v: float = R.DEFAULT_DELTA_V) -> tuple[list[dict], list[str]]:
    p = G.params()
    c_sn_ff, _ = load_extracted_c_sn(R.EXTRACT_JSON, "sn")
    reports, hold, read = {}, {1: {}, 0: {}}, {}
    for d in (1, 0):
        name = G.read_name(d)[:-5]
        rp = find_report(root, name)
        reports[name] = (rp, load_report(rp))
        read[d] = by_point(reports[name][1])
        for t in G.TEMPS_C:
            for c in (G.PROCESS_CORNERS if d == 1 else [None]):
                name = G.hold_name(d, t, c)[:-5]
                rp = find_report(root, name)
                reports[name] = (rp, load_report(rp))
                for key, m in by_point(reports[name][1]).items():
                    hold[d][key] = (m, name)
    stamps = {stamp_of(r) for _, r in reports.values()}
    if len(stamps) != 1:
        raise ReduceError(f"reports disagree on the worker PDK stamp: {sorted(stamps)}")
    status, text = stamps.pop()
    pin_ok = status == "match"
    commit = PDK_OPEN_PDKS_COMMIT if pin_ok else "fleet-stamp:" + text.replace("open_pdks ", "")
    sha = repo_git_sha(HERE)
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    first = next(iter(reports.values()))[1]
    env = first["environment"]
    ver = f"ngspice-{env.get('engine_version', 'unknown')} (klt sim batch)"
    leak = G.load_leakage_current_pin()
    warn: list[str] = []
    rows = []
    for t in G.TEMPS_C:
        for c in G.PROCESS_CORNERS:
            m1, n1 = hold[1][(c, t)]
            m0, n0 = hold[0][(c, t)]
            r1, r0 = read[1][(c, t)], read[0][(c, t)]
            window1 = G.hold_tstop(G.hold_window_s(leak, t, c_sn_ff, delta_v, corner=c)) - p["THOLD_START"]
            tstop1 = p["THOLD_START"] + window1
            tstop0 = G.hold_tstop(G.hold_window_s(leak, t, c_sn_ff, delta_v))
            window0 = tstop0 - p["THOLD_START"]
            i_read1, i_read0 = abs(r1["i_read_raw_a"]), abs(r0["i_read_raw_a"])
            ratio = i_read1 / i_read0 if i_read0 > 0 else None
            vhs = m1["v_sn_hold_start_v"]
            thr = vhs - delta_v
            ladder = {mv / 1000: m1.get(G.ladder_name(mv)) for mv in G.LADDER_MV}
            reachable = thr > R.THRESHOLD_FLOOR_V
            t_ret = ladder_crossing(thr, ladder) if reachable else None
            for d, m, w, tstop, nm in ((1, m1, window1, tstop1, n1), (0, m0, window0, tstop0, n0)):
                rr = r1 if d == 1 else r0
                ir = i_read1 if d == 1 else i_read0
                idesel = abs(rr["i_rbl_deselect_raw_a"])
                vhs_d = m["v_sn_hold_start_v"]
                dvdt = (m["v_sn_slope_end_v"] - vhs_d) / (0.02 * w)
                notes = [f"extracted C_SN {c_sn_ff:.6f} fF (layout/gain_cell_2t.extract.parasitics.json)",
                         f"klt sim batch jobs: hold {nm} ; read {G.read_name(d)[:-5]}",
                         f"run under the fleet's stamped PDK ({text}); pdk_stamp_comparison={status}"
                         + ("" if pin_ok else f"; repo pin {PDK_OPEN_PDKS_COMMIT[:7]} NOT confirmed on the worker")]
                if d == 1:
                    if not reachable:
                        notes.append(f"t_ret_tran_s BLANK: threshold {thr:.6f} V at or below the {R.THRESHOLD_FLOOR_V} V floor "
                                     "(write-margin failure, not a retention result); t_ret_linear_extrap_s still recorded")
                    elif t_ret is None:
                        notes.append(f"t_ret_tran_s BLANK: threshold {thr:.6f} V outside the crossed .meas ladder "
                                     f"({G.LADDER_MV[0]}-{G.LADDER_MV[-1]} mV) or not crossed within the {w:.6e} s window")
                    else:
                        notes.append("t_ret_tran_s: cubic interpolation of .meas level-crossing ladder (25 mV rungs)")
                        if t_ret > w:
                            warn.append(f"{c}/{t}C: t_ret {t_ret:.3e} s exceeds window {w:.3e} s")
                else:
                    notes.append("stored '0': hold window is the per-temperature maximum over corners (one request per temp); "
                                 "t_ret_* undefined for a cell written low")
                rows.append({
                    "timestamp_utc": ts, "repo_git_sha": sha, "pdk_open_pdks_commit": commit, "ngspice_version": ver,
                    "corner": c, "temp_c": t, "stored_value": d,
                    "c_sn_ff": f"{c_sn_ff:.6f}", "c_sn_source": "extracted", "vdd_v": p["VDD"], "vrbl_bias_v": p["VDD"] / 2.0,
                    "t_edge_ns": round(p["TEDGE"] * 1e9, 6),
                    "t_wl_pulse_ns": round((p["TWL_OFF"] - p["TWL_ON"]) * 1e9, 6),
                    "t_rwl_pulse_ns": round((p["TRWL_OFF"] - p["TRWL_ON"]) * 1e9, 6),
                    "tmax_s": f"{G.tmax_for(w):.6e}", "tstop_s": f"{tstop:.6e}",
                    "v_sn_end_wl_pulse_v": f"{m['v_sn_end_wl_pulse_v']:.6f}",
                    "v_sn_after_write_settled_v": f"{m['v_sn_after_write_settled_v']:.6f}",
                    "v_sn_read_gate_v": f"{m['v_sn_read_gate_v']:.6f}",
                    "i_read_a": f"{ir:.6e}", "i_rbl_deselect_a": f"{idesel:.6e}",
                    "i_read_ratio_1_over_0": R.fmt(ratio),
                    "v_sn_read_disturb_v": f"{vhs_d - m['v_sn_after_write_settled_v']:.6f}",
                    "v_sn_hold_start_v": f"{vhs_d:.6f}", "v_sn_hold_end_v": f"{m['v_sn_hold_end_v']:.6f}",
                    "hold_window_s": f"{w:.6e}", "dvdt_hold_start_v_per_s": f"{dvdt:.6e}",
                    "delta_v_sense_margin_v_ASSUMPTION": delta_v,
                    "t_ret_tran_s": f"{t_ret:.6e}" if (d == 1 and t_ret is not None) else "",
                    "t_ret_linear_extrap_s": (f"{delta_v / abs(dvdt):.6e}" if d == 1 and abs(dvdt) > 1e-3 else ""),
                    "notes": "; ".join(notes),
                })
    return rows, warn


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reports-dir", required=True, type=Path)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    rows, warn = build_rows(a.reports_dir)
    for w in warn:
        print("WARNING:", w)
    if a.dry_run:
        print(f"dry-run: {len(rows)} rows (pdk column {rows[0]['pdk_open_pdks_commit']})")
        return 0
    for r in rows:
        append_result(R.RESULTS_CSV, R.CSV_FIELDS, r)
    print(f"Appended {len(rows)} rows to {R.RESULTS_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
