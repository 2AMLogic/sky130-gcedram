#!/usr/bin/env python3
"""Reduce a `klt sim` report of sim/refresh-op/ into per-corner t_row_refresh_op (issue #110).

Stdlib only. Reads a committed ``results/klt_report_<RUN_ID>.json[.gz]`` and writes NEW
files next to it (never overwrites; refuses if they exist):

* ``refresh_op_points_<RUN_ID>.csv``   one row per (corner, temperature, instance)
* ``refresh_op_summary_<RUN_ID>.json`` per-corner minimal passing phase durations,
  t_row_refresh_op, margins, negative-control result, assumptions

Definitions (all ASSUMPTIONS, parameters at the top):

* decision: d = V(rbl) - V(ref) just before WWL rises. Stored '1' must give d <= -DECIDE_V,
  stored '0' d >= +DECIDE_V. A wrong or undecided latch means the op is NOT restored.
* RESTORED '1': decision correct AND SN(end) >= FRAC x SN_ref, where SN_ref is the in-deck
  reference write (SN from 0 V, ideal 1.8 V WBL, 20 ns WWL) at the SAME corner. FRAC is
  reported for several values; PRIMARY_FRAC is the headline (ASSUMPTION).
* RESTORED '0': decision correct AND SN(end) <= ZERO_MAX_V (ASSUMPTION).
* a (sense, pulse) point PASSES when all four patterns (two '1' pre-read levels, two '0')
  are restored. Minimal passing pulse = lowest grid width such that EVERY wider grid width
  also passes (monotone-from-above), with the highest failing width below it as bracket.
* t_row_refresh_op = precharge-on + precharge gap + sense + latch delay + pulse + guard.
  Precharge-on, gap, latch delay and guard are FIXED assumptions of the deck (not minimised);
  only sense time and pulse width are searched, on the coarse grids of the generator.
* NEGATIVE CONTROL: the deliberately too-short pulse (generator NEG_CONTROL_WB_S) must be
  flagged unrestored for every stored-'1' pattern; ``negative_control_ok`` records that.
  (A stored '0' needs no write, so the '0' patterns are not discriminating there.)
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
sys.path.insert(0, str(REPO / "sim" / "sense-stage"))
import gen_refresh_op as G  # noqa: E402
import analyze_sense_stage as SS  # noqa: E402

DECIDE_V = 0.9                 # |d| >= VDD/2 counts as decided (sense-stage convention)
FRACS = [0.90, 0.95, 0.98]     # ASSUMPTION: restore fractions of the in-deck reference write level
PRIMARY_FRAC = 0.95            # ASSUMPTION: headline fraction
ZERO_MAX_V = 0.05              # ASSUMPTION: a restored '0' sits within 50 mV of 0 V
CONTRACT_SENSE_S = 10e-9       # sense-stage contract: latch enable 10 ns after the select edge
THRESHOLD_3C = 0.50            # 3c overhead limit (ASSUMPTION in spec/macro-pass-conditions-PROPOSED.md)


def decided(d: float | None) -> str:
    if d is None:
        return "none"
    if d <= -DECIDE_V:
        return "1"
    if d >= DECIDE_V:
        return "0"
    return "unresolved"


def restored(kind: str, dec: float | None, snend: float | None, sn_ref: float | None, frac: float) -> bool:
    """Pure restore test (unit-tested, incl. the negative control)."""
    if dec is None or snend is None:
        return False
    if kind == "op1":
        return decided(dec) == "1" and sn_ref is not None and snend >= frac * sn_ref
    if kind == "op0":
        return decided(dec) == "0" and snend <= ZERO_MAX_V
    raise ValueError(kind)


def min_pass_from_above(widths: list[float], ok: list[bool]) -> tuple[int | None, bool]:
    """Index of lowest width with all wider widths passing; (None, False) if even the widest fails."""
    k = len(widths)
    while k > 0 and ok[k - 1]:
        k -= 1
    if k == len(widths):
        return None, False
    return k, True


def summarize_corner(corner: dict, writes: dict) -> tuple[list[dict], dict]:
    meas = {m["name"]: m["value"] for m in corner["measurements"]}
    insts = G.instances()
    sn_ref = meas.get("snend_refw")
    rows = []
    by = {}
    for i in insts:
        if i["kind"] == "ref":
            continue
        n = i["name"]
        dec, sn = meas.get(f"dec_{n}"), meas.get(f"snend_{n}")
        by[(i["kind"], i["sn"], i["sense"], i["wb"])] = (dec, sn)
        rows.append(dict(
            corner=corner["process"], temp_c=corner["temperature_c"], instance=n, kind=i["kind"],
            sn_pre_v=i["sn"], sense_ns=round(i["sense"] * 1e9, 6), wb_ns=round(i["wb"] * 1e9, 6),
            t_row_refresh_op_ns=round(G.t_row_refresh_op_s(i["sense"], i["wb"]) * 1e9, 4),
            dec_v=dec, decided=decided(dec), snrd_v=meas.get(f"snrd_{n}"), snend_v=sn,
            sn_ref_v=sn_ref, negative_control=i["wb"] == G.NEG_CONTROL_WB_S,
            **{f"restored_{int(f * 100)}": restored(i["kind"], dec, sn, sn_ref, f) for f in FRACS}))
    patterns = [("op1", v) for v in G.SN1_PRE_V] + [("op0", v) for v in G.SN0_PRE_V]
    res: dict = dict(corner=corner["process"], temp_c=corner["temperature_c"], klt_corner_status=corner["status"],
                     sn_ref_v=sn_ref, phase3_ideal_write_min_v=writes.get((corner["process"], corner["temperature_c"])))
    widths = list(G.WB_S)
    res["by_fraction"] = {}
    for f in FRACS:
        per_sense = {}
        for s in G.SENSE_S:
            ok = [all(restored(k, *by[(k, v, s, w)], sn_ref, f) for k, v in patterns) for w in widths]
            idx, found = min_pass_from_above(widths, ok)
            e: dict = dict(sense_ns=round(s * 1e9, 6), pass_by_width_ns={f"{w * 1e9:g}": o for w, o in zip(widths, ok)},
                           found=found)
            if found:
                w = widths[idx]
                e["min_pass_pulse_ns"] = round(w * 1e9, 6)
                e["highest_failing_pulse_below_ns"] = round(widths[idx - 1] * 1e9, 6) if idx > 0 else None
                e["t_row_refresh_op_ns"] = round(G.t_row_refresh_op_s(s, w) * 1e9, 4)
                e["next_coarser_pulse_ns"] = round(widths[idx + 1] * 1e9, 6) if idx + 1 < len(widths) else None
                e["t_row_at_next_coarser_ns"] = (round(G.t_row_refresh_op_s(s, widths[idx + 1]) * 1e9, 4)
                                                 if idx + 1 < len(widths) else None)
                e["margin_to_failing_step_ratio"] = (round(w / widths[idx - 1], 3) if idx > 0 else None)
                e["sn1_end_at_min_pass_v"] = {f"{v:g}": by[("op1", v, s, w)][1] for v in G.SN1_PRE_V}
            per_sense[f"{s * 1e9:g}ns"] = e
        cand = [(e["t_row_refresh_op_ns"], k) for k, e in per_sense.items() if e["found"]]
        best = min(cand)[1] if cand else None
        res["by_fraction"][f"{f:g}"] = dict(
            per_sense=per_sense, best_sense=best,
            t_row_refresh_op_ns=per_sense[best]["t_row_refresh_op_ns"] if best else None,
            min_pass_pulse_ns=per_sense[best]["min_pass_pulse_ns"] if best else None)
    # negative control: too-short pulse must be unrestored for every stored-'1' pattern/sense
    neg = {}
    for s in G.SENSE_S:
        for v in G.SN1_PRE_V:
            neg[f"op1_{v:g}_s{s * 1e9:g}ns"] = restored("op1", *by[("op1", v, s, G.NEG_CONTROL_WB_S)], sn_ref, PRIMARY_FRAC)
    res["negative_control_restored_flags"] = neg
    res["negative_control_ok"] = not any(neg.values())
    # decision correctness at each sense time (all patterns, any pulse)
    res["decision_correct_by_sense"] = {
        f"{s * 1e9:g}ns": all(decided(by[(k, v, s, G.WB_S[0])][0]) == k[-1] for k, v in patterns)
        for s in G.SENSE_S}
    return rows, res


def overhead_vs_3c(corners: list[dict], sense_key: str | None = None) -> dict:
    """Slowest-corner t_row_refresh_op per restore fraction. sense_key None: best (searched) sense time
    per corner; else the named sense-grid entry (e.g. '10ns', the contract sense instant)."""
    out = {}
    for f in (f"{x:g}" for x in FRACS):
        vals = []
        for c in corners:
            b = c["by_fraction"][f]
            t = b["t_row_refresh_op_ns"] if sense_key is None else b["per_sense"][sense_key].get("t_row_refresh_op_ns")
            vals.append((t, c["corner"], c["temp_c"]))
        if any(v[0] is None for v in vals):
            out[f] = dict(slowest_corner=None, t_row_refresh_op_ns=None, note="no passing point at some corner")
        else:
            t, cn, tc = max(vals)
            out[f] = dict(slowest_corner=f"{cn}/{tc}C", t_row_refresh_op_ns=t)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("report", type=Path, help="results/klt_report_<RUN_ID>.json[.gz]")
    a = ap.parse_args(argv)
    name = a.report.name
    stem = name[:-len(".json.gz")] if name.endswith(".json.gz") else a.report.stem
    run_id = stem.split("klt_report_", 1)[1]
    opener = gzip.open if name.endswith(".gz") else open
    with opener(a.report, "rt") as fh:
        rep = json.load(fh)
    pts_csv = a.report.with_name(f"refresh_op_points_{run_id}.csv")
    sum_json = a.report.with_name(f"refresh_op_summary_{run_id}.json")
    for p in (pts_csv, sum_json):
        if p.exists():
            print(f"refusing to overwrite existing evidence file {p}", file=sys.stderr)
            return 2
    if rep.get("status") != "pass" or rep.get("errored"):
        print(f"report status {rep.get('status')!r}, {rep.get('errored')} errored corners: results not produced", file=sys.stderr)
        return 1
    writes = SS.load_phase3_writes()
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
        assumptions=dict(
            decide_v=DECIDE_V, fracs=FRACS, primary_frac=PRIMARY_FRAC, zero_max_v=ZERO_MAX_V,
            threshold_3c=THRESHOLD_3C, c_rbl_f=G.S.C_RBL_F, c_wbl_f=G.C_WBL_F, vrbl_v=G.VRBL_V, dref_v=G.DREF_V,
            n_rows_column=G.N_ROWS, precharge_on_s=G.T_PRE_ON_S, precharge_gap_s=G.T_PRE_GAP_S,
            latch_delay_s=G.T_LATCH_S, guard_s=G.T_GUARD_S, sense_grid_s=G.SENSE_S, wb_grid_s=G.WB_S,
            negative_control_wb_s=G.NEG_CONTROL_WB_S, ref_wb_s=G.REF_WB_S, sn1_pre_v=G.SN1_PRE_V, sn0_pre_v=G.SN0_PRE_V),
        claims=dict(mismatch_or_offset_yield_validated=False, supply_tolerance_studied=False,
                    extracted_c_rbl=False, extracted_c_wbl=False, spec_changed=False),
        negative_control_ok_all_corners=all(c["negative_control_ok"] for c in corners),
        slowest_corner_t_row_refresh_op=overhead_vs_3c(corners),
        slowest_corner_t_row_refresh_op_contract_sense_10ns=overhead_vs_3c(corners, f"{CONTRACT_SENSE_S * 1e9:g}ns"),
        corners=corners,
    )
    sum_json.write_text(json.dumps(summary, indent=1) + "\n")
    print(f"wrote {pts_csv.name} and {sum_json.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
