#!/usr/bin/env python3
"""Reduce a `klt sim` report of sim/aged-read/ into per-point and per-corner findings (issue #94).

Stdlib only. Reads ``results/klt_report_<RUN_ID>.json``; writes NEW files next to it
(never overwrites): ``aged_points_<RUN_ID>.csv`` and ``aged_summary_<RUN_ID>.json``.

Per point the CSV links write -> aging -> decision: ``written_v`` (selected SN just after its
write), ``pre_read_v`` (SN just before the select edge), ``droop_v`` = written - pre_read,
``post_sense_v`` (SN at the enable instant) and ``read_disturb_v`` = post_sense - pre_read,
the latch input ``din_v`` and final ``dend_v``, the signed decision and its latency.

Definitions (ASSUMPTIONS, same as sim/sense-stage): d = V(rbl) - V(ref); a stored '1' must
decide d -> -VDD, a '0' d -> +VDD. A point RESOLVES when the decision has the stored value's
sign, |dend| >= VDD/2 and 0 < tdec <= 5 ns (a non-positive tdec is not a decision time). ``within_refresh_bound`` = age <= the ratified 5.03 us
bound (read only); ``meets_refresh_bound`` = within bound AND resolves. Failures are kept.

Negative control: the inadequate-write ('control_weak_write') points MUST NOT resolve; the
summary records ``negative_control_detected`` (True iff every control read is invalid) and
the zero-hold control (5 ns) of every corner must resolve, else the chain itself is broken.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from _evidence_common import DELTA_V_V, PROPOSED_RANGE_SCOPE, PROPOSED_RANGE_STATUS  # noqa: E402
from _evidence_common import decided, klt_provenance, measurements_of, tdec_in_window  # noqa: E402
import gen_aged_read as G  # noqa: E402

T_WINDOW_S = 5e-9
RESOLVE_V = DELTA_V_V


def point_row(corner: dict, p: dict, m: dict) -> dict:
    n = p["name"]
    g = lambda k: m.get(f"{k}_{n}")
    dend, tdec = g("dend"), g("tdec")
    dec = decided(dend, RESOLVE_V)
    wr, pre, post = g("wr"), g("pre"), g("post")
    correct = dec == str(p["value"])
    resolves = bool(correct and tdec_in_window(tdec, T_WINDOW_S))
    within = p["age_ns"] * 1e-9 <= G.REFRESH_BOUND_S
    return dict(
        corner=corner["process"], temperature_c=int(corner["temperature_c"]), kind=p["kind"], case=n,
        age_ns=p["age_ns"], selected_row=p["row"], value=p["value"], neighbour_pattern=p["pattern"],
        write_order="".join(map(str, p["order"])), written_v=wr, pre_read_v=pre, post_sense_v=post,
        droop_v=None if wr is None or pre is None else wr - pre,
        read_disturb_v=None if pre is None or post is None else post - pre,
        din_v=g("din"), dend_v=dend, tdec_s=tdec, decision=dec, correct=correct, resolves=resolves,
        within_refresh_bound=within, meets_refresh_bound=bool(within and resolves))


def summarize_corner(corner: dict, pts: list[dict]) -> tuple[list[dict], dict]:
    m = measurements_of(corner)
    rows = [point_row(corner, p, m) for p in pts]
    main = [r for r in rows if r["kind"] == "main"]
    ctl = [r for r in rows if r["kind"] != "main"]
    within = [r for r in main if r["within_refresh_bound"]]
    fails_within = [r for r in within if not r["resolves"]]
    fails_all = [r for r in main if not r["resolves"]]
    zero = [r for r in main if r["age_ns"] == min(G.AGES_NS)]
    # per (value,row,pattern) boundary: last resolving age below the first failing age
    boundary = {}
    for key in sorted({(r["value"], r["selected_row"], r["neighbour_pattern"]) for r in main}):
        series = sorted((r for r in main if (r["value"], r["selected_row"], r["neighbour_pattern"]) == key),
                        key=lambda r: r["age_ns"])
        bad = [r["age_ns"] for r in series if not r["resolves"]]
        first_bad = bad[0] if bad else None
        ok_below = [r["age_ns"] for r in series if r["resolves"] and (first_bad is None or r["age_ns"] < first_bad)]
        boundary[f"v{key[0]}_r{key[1]}_{key[2]}"] = dict(
            last_resolving_age_ns=ok_below[-1] if ok_below else None, first_failing_age_ns=first_bad)
    pre1 = [r["pre_read_v"] for r in main if r["value"] == 1 and r["age_ns"] == max(G.AGES_NS) and r["pre_read_v"] is not None]
    summ = dict(
        process=corner["process"], temperature_c=int(corner["temperature_c"]),
        points=len(rows), main_points=len(main),
        all_within_bound_resolve=not fails_within,
        failing_points_within_bound=len(fails_within),
        failing_points_total=len(fails_all),
        min_pre_read_stored1_within_bound_v=min((r["pre_read_v"] for r in within if r["value"] == 1 and r["pre_read_v"] is not None), default=None),
        min_pre_read_stored1_longest_age_v=min(pre1, default=None),
        max_droop_stored1_within_bound_v=max((r["droop_v"] for r in within if r["value"] == 1 and r["droop_v"] is not None), default=None),
        max_abs_read_disturb_v=max((abs(r["read_disturb_v"]) for r in main if r["read_disturb_v"] is not None), default=None),
        zero_hold_all_resolve=all(r["resolves"] for r in zero),
        failure_boundary_by_case=boundary,
        negative_control_detected=bool(ctl) and not any(r["resolves"] for r in ctl),
        negative_control_points=len(ctl),
    )
    return rows, summ


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("report", type=Path)
    a = ap.parse_args(argv)
    rep = json.loads(a.report.read_text())
    run_id = a.report.stem.split("klt_report_", 1)[1]
    pts_csv = a.report.with_name(f"aged_points_{run_id}.csv")
    sum_json = a.report.with_name(f"aged_summary_{run_id}.json")
    for p in (pts_csv, sum_json):
        if p.exists():
            print(f"refusing to overwrite existing evidence file {p}", file=sys.stderr)
            return 2
    if rep.get("status") != "pass" or rep.get("errored"):
        print(f"report status {rep.get('status')!r}, {rep.get('errored')} errored corners: results not produced", file=sys.stderr)
        return 1
    pts = G.instances()
    rows, corners = [], []
    for c in rep["corners"]:
        r, s = summarize_corner(c, pts)
        rows += r
        corners.append(s)
    with pts_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    summary = dict(
        run_id=run_id, status=PROPOSED_RANGE_STATUS, scope=PROPOSED_RANGE_SCOPE, **klt_provenance(rep),
        batch_fleet_jobs=sorted({f.get("job_id") for f in rep.get("environment", {}).get("remote", {}).get("fleet", []) if f.get("job_id")}),
        sources=dict(deck=G.NETLIST_PATH.name, latch="design/sense_latch.spice (corrected, issue #293 provenance)",
                     cell="design/gain_cell_2t.spice with layout-drawn AD/AS/PD/PS"),
        assumptions=dict(
            c_rbl_ff=G.S.extracted_c_rbl_ff(), c_sn_ff_array_min_wiring=G.array_c_sn_ff(), vrbl_v=G.VRBL_V,
            dvref_v=G.DREF_V, t_window_s=T_WINDOW_S, resolve_v=RESOLVE_V, ages_ns=G.AGES_NS,
            neighbour_patterns=G.NEIGHBOUR_PATTERNS, refresh_bound_s_ratified_read_only=G.REFRESH_BOUND_S,
            drivers="ideal write/wordline/bitline drivers, ideal 100 ohm precharge switch, ideal matched dummy reference load",
            mismatch="none (global corners only)", pattern_enumeration="starting point, not proven worst case",
            weak_write_control_wl_v=G.WEAK_WL_V),
        claims=dict(mismatch_or_offset_yield_validated=False, spec_changed=False, refresh_bound_signed_off=False,
                    global_corner_evidence_only=True),
        corners=corners,
        negative_control_detected_all_corners=all(c["negative_control_detected"] for c in corners),
        zero_hold_control_ok_all_corners=all(c["zero_hold_all_resolve"] for c in corners),
        all_corners_all_within_bound_resolve=all(c["all_within_bound_resolve"] for c in corners),
    )
    sum_json.write_text(json.dumps(summary, indent=1) + "\n")
    print(f"wrote {pts_csv.name} and {sum_json.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
