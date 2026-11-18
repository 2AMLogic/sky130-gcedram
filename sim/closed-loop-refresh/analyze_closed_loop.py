#!/usr/bin/env python3
"""Reduce a `klt sim` report of one sim/closed-loop-refresh/ variant (issue #147).

Stdlib only. ``python3 -I analyze_closed_loop.py <variant> results/klt_report_<variant>_<RUN_ID>.json``
writes NEW files next to the report (never overwrites):
``closed_loop_points_<variant>_<RUN_ID>.csv`` (one row per corner x instance x row x cycle) and
``closed_loop_summary_<variant>_<RUN_ID>.json``.

Per row and cycle n the CSV links: ``written_v`` (post-initial-write level), ``pre_read_v`` (just before the
select edge), ``dec_v`` and the signed ``decision`` (d = V(rbl) - V(ref) at the instant before the write-back
WWL rises; a stored '1' must go <= -VDD/2, a '0' >= +VDD/2), ``correct`` (against the ORIGINAL data, never
against a later converged value), ``post_refresh_v`` (SN after the op settles) and ``restore_fraction``
(stored '1': post_refresh / the refresh-op in-deck reference SN_ref, also vs the deck's own written level, gated at the 0.90/0.95/0.98 gates of sim/refresh-op; stored '0':
|post_refresh| <= 50 mV). Restoration is ALWAYS reported beside sense correctness and the actual voltage.

``first_failure_cycle`` = first cycle whose READ is wrong (this stays a failure even if later write-backs converge
to the wrong value); ``first_unrestored_cycle`` = first cycle whose post-refresh level fails the 0.95 gate.
Failed corners and trajectories are kept. Controls: missing write-back (``nowb``) and excessive dwell must be
DETECTED (any row read wrong or unrestored), else the analyzer/chain is not trusted.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from _evidence_common import DELTA_V_V, PROPOSED_RANGE_SCOPE, PROPOSED_RANGE_STATUS  # noqa: E402
from _evidence_common import decided, klt_provenance, measurements_of  # noqa: E402
import gen_closed_loop as G  # noqa: E402

RESOLVE_V = DELTA_V_V                  # VDD/2, as sim/sense-stage / sim/aged-read
FRACTIONS = (0.90, 0.95, 0.98)
GATE = 0.95
# Restoration gates are taken against the SAME per-corner in-deck reference write the single-operation studies use
# (sn_ref_v: ideal 1.8 V WBL, 20 ns WWL, from 0 V; committed sim/refresh-replay run), so 0.90/0.95/0.98 mean here
# what they mean there. The fraction against THIS deck's own post-write level is reported too (restore_fraction_vs_written).
REFOP_REF_RUN = G.REPO / "sim" / "refresh-replay" / "results" / "20261115T120746Z" / "points.csv"


def refop_refs() -> dict[tuple[str, int], float]:
    out: dict[tuple[str, int], float] = {}
    with REFOP_REF_RUN.open() as f:
        for r in csv.DictReader(f):
            if r["variant"] == "baseline_analog" and r["kind"] == "op1" and r["sn_pre_v"] == "0.9":
                out[(r["corner"], int(r["temp_c"]))] = float(r["sn_ref_v"])
    return out


REFS = refop_refs()
ZERO_MAX_V = 0.05


def cycle_row(corner: dict, v: dict, p: dict, r: int, c: int, m: dict) -> dict:
    n = p["name"]
    g = lambda k: m.get(f"{k}_{n}_r{r}_c{c}")
    wr = m.get(f"wr_{n}_r{r}")
    pre, dec_v, post = g("pre"), g("dec"), g("post")
    data = p["data"][r]
    dec = decided(dec_v, RESOLVE_V)
    correct = dec == str(data)
    ref = REFS[(corner["process"], int(corner["temperature_c"]))]
    frac_w = post / wr if data == 1 and wr and post is not None else None
    frac = post / ref if data == 1 and post is not None else None
    if data == 1:
        restored = {f: bool(frac is not None and frac >= f) for f in FRACTIONS}
    else:
        ok = post is not None and post <= ZERO_MAX_V   # signed, as sim/refresh-op: an undershoot below 0 V is not a failure
        restored = {f: bool(ok) for f in FRACTIONS}
    return dict(
        corner=corner["process"], temperature_c=int(corner["temperature_c"]), variant=v["name"], dwell_ns=v["dwell_ns"],
        kind=p["kind"], waveform=p["wf"], case=n, row=r, data=data, cycle=c, written_v=wr, refop_sn_ref_v=ref if data == 1 else None, pre_read_v=pre, dec_v=dec_v,
        decision=dec, correct=correct, post_refresh_v=post, restore_fraction=frac, restore_fraction_vs_written=frac_w,
        restored_090=restored[0.90], restored_095=restored[0.95], restored_098=restored[0.98],
        interval_loss_v=None)


def reduce_corner(corner: dict, v: dict) -> tuple[list[dict], dict]:
    m = measurements_of(corner)
    rows: list[dict] = []
    for p in G.instances(v):
        for r in range(G.N_ROWS):
            series = [cycle_row(corner, v, p, r, c, m) for c in range(1, v["cycles"] + 1)]
            prev = m.get(f"wr_{p['name']}_r{r}")
            for s in series:     # loss during the dwell = level after the previous write - level before this read
                if prev is not None and s["pre_read_v"] is not None:
                    s["interval_loss_v"] = prev - s["pre_read_v"]
                prev = s["post_refresh_v"]
            rows += series
    summ = dict(process=corner["process"], temperature_c=int(corner["temperature_c"]), by_kind={}, instances={})
    kinds = sorted({p["kind"] for p in G.instances(v)})
    for kind in kinds:
        kr = [x for x in rows if x["kind"] == kind]
        per_row: dict[str, dict] = {}
        for x in kr:
            per_row.setdefault(f"{x['case']}_r{x['row']}", dict(data=x["data"], series=[]))["series"].append(x)
        bad_read = {k: next((s["cycle"] for s in d["series"] if not s["correct"]), None) for k, d in per_row.items()}
        bad_rest = {k: next((s["cycle"] for s in d["series"] if not s["restored_095"]), None) for k, d in per_row.items()}
        s1 = [x for x in kr if x["data"] == 1 and x["post_refresh_v"] is not None]
        loss1 = [x["interval_loss_v"] for x in kr if x["data"] == 1 and x["interval_loss_v"] is not None and x["cycle"] > 1]
        drift = []
        for d in per_row.values():
            if d["data"] == 1 and len(d["series"]) > 1 and None not in (d["series"][0]["post_refresh_v"], d["series"][-1]["post_refresh_v"]):
                drift.append(d["series"][-1]["post_refresh_v"] - d["series"][0]["post_refresh_v"])
        summ["by_kind"][kind] = dict(
            rows=len(per_row), cycles=v["cycles"],
            all_reads_correct=all(c is None for c in bad_read.values()),
            rows_with_wrong_read=sum(c is not None for c in bad_read.values()),
            first_failure_cycle_by_row={k: c for k, c in bad_read.items() if c is not None},
            all_restored_095=all(c is None for c in bad_rest.values()),
            rows_unrestored_095=sum(c is not None for c in bad_rest.values()),
            first_unrestored_cycle_by_row={k: c for k, c in bad_rest.items() if c is not None},
            failures_detected=any(c is not None for c in list(bad_read.values()) + list(bad_rest.values())),
            min_post_refresh_stored1_v=min((x["post_refresh_v"] for x in s1), default=None),
            min_restore_fraction_stored1=min((x["restore_fraction"] for x in s1 if x["restore_fraction"] is not None), default=None),
            min_pre_read_stored1_v=min((x["pre_read_v"] for x in kr if x["data"] == 1 and x["pre_read_v"] is not None), default=None),
            max_interval_loss_stored1_v=max(loss1, default=None),
            max_stored1_post_refresh_drift_first_to_last_cycle_v=max(drift, key=abs, default=None),
            min_abs_decision_v=min((abs(x["dec_v"]) for x in kr if x["dec_v"] is not None), default=None))
    return rows, summ


def verdicts(corners: list[dict], v: dict) -> dict:
    """Flags that never treat simulator completion as success."""
    def bk(c, k):
        return c["by_kind"].get(k)
    out: dict = {}
    main = [bk(c, "main") for c in corners if bk(c, "main")]
    if main:
        out["main_all_reads_correct_all_corners"] = all(b["all_reads_correct"] for b in main)
        out["main_all_restored_095_all_corners"] = all(b["all_restored_095"] for b in main)
        out["main_corners_with_any_failure"] = sorted(f"{c['process']}/{c['temperature_c']}" for c in corners
                                                      if bk(c, "main") and bk(c, "main")["failures_detected"])
    nowb = [(c, bk(c, "control_missing_writeback")) for c in corners if bk(c, "control_missing_writeback")]
    if nowb:
        out["missing_writeback_control_detected_all_corners"] = all(b["failures_detected"] for _, b in nowb)
    ex = [(c, bk(c, "control_excessive_dwell")) for c in corners if bk(c, "control_excessive_dwell")]
    if ex:
        out["excessive_dwell_corners_detected"] = sorted(f"{c['process']}/{c['temperature_c']}" for c, b in ex if b["failures_detected"])
        out["excessive_dwell_detected_any_corner"] = bool(out["excessive_dwell_corners_detected"])
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("variant")
    ap.add_argument("report", type=Path)
    a = ap.parse_args(argv)
    v = G.variant(a.variant)
    name = a.report.name[:-3] if a.report.name.endswith(".gz") else a.report.name   # reports are committed gzipped
    stem = name[:-len(".json")] if name.endswith(".json") else name
    prefix = f"klt_report_{a.variant}_"
    if not stem.startswith(prefix):
        print(f"report name must be {prefix}<RUN_ID>.json", file=sys.stderr)
        return 2
    run_id = stem[len(prefix):]
    pts_csv = a.report.with_name(f"closed_loop_points_{a.variant}_{run_id}.csv")
    sum_json = a.report.with_name(f"closed_loop_summary_{a.variant}_{run_id}.json")
    for p in (pts_csv, sum_json):
        if p.exists():
            print(f"refusing to overwrite existing evidence file {p}", file=sys.stderr)
            return 2
    rep = json.loads(gzip.open(a.report, "rt").read() if a.report.suffix == ".gz" else a.report.read_text())
    if rep.get("status") != "pass" or rep.get("errored"):
        print(f"report status {rep.get('status')!r}, {rep.get('errored')} errored corners: results not produced", file=sys.stderr)
        return 1
    rows, corners = [], []
    for c in rep["corners"]:
        r, s = reduce_corner(c, v)
        rows += r
        corners.append(s)
    with pts_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    summary = dict(
        run_id=run_id, variant=v["name"], dwell_ns=v["dwell_ns"], cycles=v["cycles"], role=v["role"],
        status=PROPOSED_RANGE_STATUS, scope=PROPOSED_RANGE_SCOPE, **klt_provenance(rep),
        batch_fleet_jobs=sorted({f.get("job_id") for f in rep.get("environment", {}).get("remote", {}).get("fleet", []) if f.get("job_id")}),
        sources=dict(deck=G.paths(v)[0].name, latch="design/sense_latch.spice (corrected, issue #293 provenance)",
                     cell="design/gain_cell_2t.spice with layout-drawn AD/AS/PD/PS",
                     rtl_trace=str(G.TRACE_PATH.relative_to(G.REPO)), waveforms={k: w[0] for k, w in G.WAVEFORMS.items()}),
        assumptions=dict(
            restore_reference=str(REFOP_REF_RUN.relative_to(G.REPO)) + " sn_ref_v (baseline_analog, op1, 0.9 V rows)",
            c_rbl_ff=G.S.extracted_c_rbl_ff(), c_sn_ff_array_min_wiring=G.A.array_c_sn_ff(), c_wbl_ff_not_extracted=G.C_WBL_F * 1e15,
            vrbl_v=G.VRBL_V, dvref_v=G.DREF_V, resolve_v=RESOLVE_V, restore_fractions=list(FRACTIONS), stored0_max_v=ZERO_MAX_V,
            refresh_bound_s_ratified_read_only=G.REFRESH_BOUND_S, patterns=G.PATTERNS_ALL,
            horizon_cycles=v["cycles"], horizon_is_finite_not_indefinite_stability=True,
            drivers="ideal wordline/bitline-init/precharge drivers and 100 ohm switches; no physical column or row driver",
            mismatch="none (global corners only)", pattern_enumeration="starting point, not proven worst case"),
        claims=dict(full_macro_or_yield_claim=False, mismatch_or_offset_yield_validated=False, spec_changed=False,
                    refresh_bound_signed_off=False, global_corner_evidence_only=True,
                    indefinite_stability_claimed=False),
        verdicts=verdicts(corners, v),
        corners=corners)
    sum_json.write_text(json.dumps(summary, indent=1) + "\n")
    print(f"wrote {pts_csv.name} and {sum_json.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
