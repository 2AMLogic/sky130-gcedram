#!/usr/bin/env python3
"""Reduce a `klt sim` report of sim/sense-stage/ into per-corner findings (issue #60).

Stdlib only. Reads a committed ``results/klt_report_<RUN_ID>.json`` and writes
NEW files next to it (never overwrites; refuses if they exist):

* ``sense_points_<RUN_ID>.csv``   one row per (corner, temperature, instance)
* ``sense_summary_<RUN_ID>.json`` per-corner metrics + the VDD/2 finding

Definitions (all ASSUMPTIONS, parameters at the top):

* d = V(rbl) - V(ref). A stored '1' pulls rbl DOWN, so the correct decision
  is d -> -VDD ("1"); a stored '0' decides d -> +VDD ("0").
* ``din``  = d at the enable instant (what the latch actually sees; it
  includes charge drift during the floating interval, so it differs a few mV
  from the nominal stage-only offset).
* a point RESOLVES when the final |d| >= RESOLVE_V of full swing, with the
  correct sign, and ``tdec`` (enable edge at 0.9 V -> |d| = 0.9 V) is within
  T_WINDOW_S. ``tdec`` is reported for every point so other windows can be
  applied.
* min resolvable SN level = lowest swept '1' level such that EVERY swept
  level at or above it resolves (monotone-from-above), reported with the
  highest failing level below it as a bracket. The grid step bounds the
  resolution of this number.
* The numeric floor of the stage-only sweep is the smallest swept |d| (1 mV);
  global corners carry no mismatch, so this is a SYSTEMATIC-only figure and
  says nothing about random offset (no Monte Carlo was run).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
import gen_sense_stage as G  # noqa: E402

T_WINDOW_S = 5e-9              # ASSUMPTION: decision must complete within 5 ns of enable
RESOLVE_V = 0.9                # |d| >= VDD/2 counts as decided (full swing is 1.8 V)
VDD_HALF_V = 0.9               # the retention study's delta_V ASSUMPTION (VDD/2)
PHASE3_PASS_FAIL = REPO / "sim/loaded-column/cold-corner/results/pass_fail_20261005T145658Z.csv"


def load_phase3_writes() -> dict[tuple[str, int], float]:
    """min stored-'1' level after write (V), baseline, per (corner, temp)."""
    out: dict[tuple[str, int], float] = {}
    with PHASE3_PASS_FAIL.open() as f:
        for r in csv.DictReader(f):
            if r["variant_id"] != "phase2_baseline":
                continue
            k = (r["corner"], int(float(r["temp_c"])))
            v = float(r["v_sn1_after_write_min_v"])
            out[k] = min(out.get(k, v), v)
    return out


def point(kind: str, meas: dict, name: str) -> dict:
    din, dend, tdec = meas.get(f"din_{name}"), meas.get(f"dend_{name}"), meas.get(f"tdec_{name}")
    want = "0" if kind == "cell0" else None
    return dict(din=din, dend=dend, tdec=tdec)


def decided(dend: float | None) -> str:
    if dend is None:
        return "none"
    if dend <= -RESOLVE_V:
        return "1"
    if dend >= RESOLVE_V:
        return "0"
    return "unresolved"


def resolves(p: dict, expect: str) -> bool:
    return (decided(p["dend"]) == expect and p["tdec"] is not None and p["tdec"] <= T_WINDOW_S)


def summarize_corner(corner: dict, writes: dict) -> tuple[list[dict], dict]:
    meas = {m["name"]: m["value"] for m in corner["measurements"]}
    rows, pts = [], {}
    for inst in G.instances():
        n = inst["name"]
        p = point(inst["kind"], meas, n)
        pts[n] = (inst, p)
        expect = "1" if (inst["kind"] == "cell1" or (inst["kind"] == "stage" and inst["d_mv"] < 0)) else "0"
        rows.append(dict(
            corner=corner["process"], temp_c=corner["temperature_c"], instance=n, kind=inst["kind"],
            ref_offset_v=inst["dref"], nominal_d_mv=inst.get("d_mv", ""), sn_level_v=inst.get("sn", ""),
            din_v=p["din"], dend_v=p["dend"], tdec_s=p["tdec"], expected=expect,
            decided=decided(p["dend"]), resolves_in_window=resolves(p, expect)))
    res: dict = {"corner": corner["process"], "temp_c": corner["temperature_c"], "klt_corner_status": corner["status"]}
    # stage-only: smallest correctly resolved |din| per polarity
    for sgn, label, expect in ((-1, "minus", "1"), (1, "plus", "0")):
        ok = [(abs(p["din"]), p["tdec"]) for (i, p) in pts.values()
              if i["kind"] == "stage" and (i["d_mv"] < 0) == (sgn < 0) and resolves(p, expect)]
        allp = [(i["d_mv"], p) for (i, p) in pts.values() if i["kind"] == "stage" and (i["d_mv"] < 0) == (sgn < 0)]
        res[f"stage_min_resolved_abs_din_mv_{label}"] = round(min(a for a, _ in ok) * 1e3, 4) if ok else None
        res[f"stage_all_{label}_points_resolve"] = len(ok) == len(allp)
        res[f"stage_tdec_at_1mv_ns_{label}"] = next((round(p["tdec"] * 1e9, 4) for d, p in allp
                                                    if abs(d) == 1 and p["tdec"] is not None), None)
    # end-to-end per reference offset
    res["end_to_end"] = {}
    for dref in G.DVREF_V:
        lv = sorted(((i["sn"], p) for (i, p) in pts.values() if i["kind"] == "cell1" and i["dref"] == dref))
        z = [(i["sn"], p) for (i, p) in pts.values() if i["kind"] == "cell0" and i["dref"] == dref]
        zero_ok = all(resolves(p, "0") for _, p in z)
        passing = [resolves(p, "1") for _, p in lv]
        # monotone-from-above threshold
        k = len(lv)
        while k > 0 and passing[k - 1]:
            k -= 1
        if k == len(lv):
            lo = hi = None
        else:
            hi = lv[k][0]                       # lowest level from which all higher levels resolve
            lo = lv[k - 1][0] if k > 0 else None  # highest failing level below it (None: all above sweep floor... )
        aw = writes.get((corner["process"], corner["temperature_c"]))
        tdec_hi = next((p["tdec"] for s, p in lv if s == hi), None) if k < len(lv) else None
        din_hi = next((p["din"] for s, p in lv if s == hi), None) if k < len(lv) else None
        entry = dict(
            stored0_all_resolve=zero_ok,
            sn1_min_resolvable_upper_bound_v=hi,
            sn1_highest_failing_level_below_v=lo,
            din_at_min_resolvable_v=din_hi,
            rbl_droop_below_precharge_at_min_resolvable_v=None if din_hi is None else round(dref - din_hi, 4),
            tdec_at_min_resolvable_ns=None if tdec_hi is None else round(tdec_hi * 1e9, 4),
            sense_time_ns_at_1p0V=next((round(p["tdec"] * 1e9, 4) for s, p in lv if s == 1.0 and p["tdec"]), None),
            phase3_stored1_after_write_min_v=aw,
        )
        if hi is not None and aw is not None:
            entry["usable_dv_sn_lower_bound_v"] = round(aw - hi, 4)           # pessimistic: true min level <= hi
            entry["usable_dv_sn_upper_bound_v"] = round(aw - (lo if lo is not None else hi), 4)
            entry["usable_dv_vs_vdd_half"] = (
                "met" if entry["usable_dv_sn_lower_bound_v"] >= VDD_HALF_V else "violated"
                if entry["usable_dv_sn_upper_bound_v"] < VDD_HALF_V else "indeterminate_on_this_grid")
            entry["stored1_at_vdd_half_resolves"] = bool(
                next((resolves(p, "1") for s, p in lv if abs(s - VDD_HALF_V) < 1e-9), False))
        res["end_to_end"][f"{round(dref * 1000)}mV"] = entry
    # best swept reference: stored '0' must still resolve; maximise the pessimistic usable swing
    cand = [(e["usable_dv_sn_lower_bound_v"], k) for k, e in res["end_to_end"].items()
            if e["stored0_all_resolve"] and "usable_dv_sn_lower_bound_v" in e]
    if cand:
        _, k = max(cand)
        e = res["end_to_end"][k]
        res["best_swept_reference"] = dict(
            reference_offset=k, usable_dv_sn_v=[e["usable_dv_sn_lower_bound_v"], e["usable_dv_sn_upper_bound_v"]],
            ratio_to_vdd_half=[round(e["usable_dv_sn_lower_bound_v"] / VDD_HALF_V, 3),
                               round(e["usable_dv_sn_upper_bound_v"] / VDD_HALF_V, 3)],
            verdict=e["usable_dv_vs_vdd_half"], stored1_at_vdd_half_resolves=e["stored1_at_vdd_half_resolves"])
    else:
        res["best_swept_reference"] = None
    return rows, res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("report", type=Path, help="results/klt_report_<RUN_ID>.json")
    a = ap.parse_args(argv)
    rep = json.loads(a.report.read_text())
    run_id = a.report.stem.split("klt_report_", 1)[1]
    pts_csv = a.report.with_name(f"sense_points_{run_id}.csv")
    sum_json = a.report.with_name(f"sense_summary_{run_id}.json")
    for p in (pts_csv, sum_json):
        if p.exists():
            print(f"refusing to overwrite existing evidence file {p}", file=sys.stderr)
            return 2
    if rep.get("status") != "pass" or rep.get("errored"):
        print(f"report status {rep.get('status')!r}, {rep.get('errored')} errored corners: results not produced", file=sys.stderr)
        return 1
    writes = load_phase3_writes()
    rows, corners = [], []
    for c in rep["corners"]:
        r, s = summarize_corner(c, writes)
        rows += r
        corners.append(s)
    with pts_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    remote = rep["environment"].get("remote", {})
    summary = dict(
        run_id=run_id,
        status="PROPOSED_OPERATING_RANGE_NOT_RATIFIED",
        scope="27 C and 125 C, tt/ss/ff/sf/fs global corners, VDD=1.8 V, per spec/operating-range-decision-PROPOSED.md",
        klt_status=rep["status"], corner_count=rep["corner_count"],
        batch_job_id=remote.get("job_id"), batch_instance_type=remote.get("instance_type"),
        netlist_sha256=rep["environment"].get("netlist_sha256"),
        models_lib_sha256=rep["environment"].get("models_lib_sha256"),
        engine_version=rep["environment"].get("engine_version"),
        assumptions=dict(t_window_s=T_WINDOW_S, resolve_v=RESOLVE_V, c_rbl_f=G.C_RBL_F, vrbl_v=G.VRBL_V,
                         dvref_v=G.DVREF_V, t_en_after_select_s=G.T_EN_S - G.T_READ_S, n_rows=G.N_ROWS),
        claims=dict(mismatch_or_offset_yield_validated=False, supply_tolerance_studied=False,
                    extracted_c_rbl=False, spec_changed=False),
        corners=corners,
    )
    sum_json.write_text(json.dumps(summary, indent=1) + "\n")
    print(f"wrote {pts_csv.name} and {sum_json.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
