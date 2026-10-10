#!/usr/bin/env python3
"""Reduce a `klt sim` report of the matched initialization-control study (issue #139) into points.csv + summary.json. Stdlib only.

Per (corner, regime, variant, pattern) record, kept SEPARATE and never merged into one verdict:

* ``intended_level_v``        the nominal label (the data target); NEVER used as the level that was read
* ``achieved_post_write_v``   physical regime: SN after the preparation write (WWL fall); None in the IC regimes (no write exists)
* ``sn_post_init_v``          IC regimes: SN after the t = 0 start-up steps; physical: = achieved_post_write_v
* ``pre_read_v``              MEASURED SN just before the read-select assert; ``pre_read_minus_label_v``, ``label_matches_pre_read``
* ``dec_v`` / ``decided``     SIGNED latch decision d = V(rbl) - V(ref) ('1' if d <= -0.9 V, '0' if >= +0.9 V, else unresolved)
* ``sense_correct``           decided == intended data
* ``restore_fraction``        SN_end / SN_ref (in-deck reference write); ``restored_90/95/98`` = sim/refresh-op criterion, which
                              ALREADY requires the correct decision -- a restore ratio can never pass an incorrect sense decision
* ``outcome``                 simulator_error > sense_incorrect > stored1_below_threshold > stored0_above_50mV > pass (first failing)

Writes NEW files (refuses to overwrite); ``--out-dir`` re-analyses a recorded run append-only into a new directory.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "sim" / "refresh-op"))
sys.path.insert(0, str(REPO / "sim" / "sense-stage"))
import analyze_refresh_op as AR  # noqa: E402

FRACS = AR.FRACS
PRIMARY = AR.PRIMARY_FRAC
LABEL_TOL_V = 0.025          # ASSUMPTION: |pre-read - label| above this = the label does not describe the level that was read
REPRO_TOL_V = 0.005          # recorded-run reproduction tolerance on SN levels (same circuit; deck size changes solver steps)
PRIOR_131 = HERE / "results" / "20261010T130000Z" / "summary.json"
PRIOR_134 = HERE / "driver_sweep_results" / "20261010T141816Z" / "summary.json"
PIC_TO_134 = {"pic_baseline_analog": "an_s0p1_r0_ic", "pic_rtl_hold": "rh_s0p1_r0_ic", "pic_rwl_late_hold": "rl_s0p1_r0_ic"}
SENSE_FAMILY = {"baseline_analog": "analog_sense_timing"}      # every other base shares the RTL sense timing up to the decision probe
DOCUMENTED_PIC_SENSE_FAIL = {("ss", 27), ("fs", 27)}           # README #134: stored-'1' 0.9 V sensed wrongly with the pin IC
DOCUMENTED_UPLIFT_V = (0.07, 0.12)                             # README #134: legacy pre-read 'about 0.07-0.12 V above its label'
DOCUMENTED_PIC_DROP_V = (-0.26, -0.12)                         # README #134: pin-IC pre-read minus legacy


def load_json(p: Path):
    opener = gzip.open if p.name.endswith(".gz") else open
    with opener(p, "rt") as fh:
        return json.load(fh)


def pat(kind: str, sn: float) -> str:
    return f"{kind}_{sn:g}"


def outcome(sim_ok: bool, sense: bool, r1_ok: bool, r0_ok: bool) -> str:
    if not sim_ok:
        return "simulator_error"
    if not sense:
        return "sense_incorrect"
    if not r1_ok:
        return "stored1_below_threshold"
    if not r0_ok:
        return "stored0_above_50mV"
    return "pass"


def record(meas: dict, mi: dict, corner: dict, sim_ok: bool) -> dict:
    n = mi["name"]
    sn_ref = meas.get("snend_refw")
    dec, sn, pre = meas.get(f"dec_{n}"), meas.get(f"snend_{n}"), meas.get(f"snpre_{n}")
    ini = meas.get(f"snini_{n}")
    intended = mi["kind"][-1]
    d = AR.decided(dec)
    sense = bool(sim_ok and dec is not None and d == intended)
    r = {f"restored_{int(f * 100)}": bool(sim_ok and AR.restored(mi["kind"], dec, sn, sn_ref, f)) for f in FRACS}
    rec = dict(corner=corner["process"], temp_c=corner["temperature_c"], instance=n, regime=mi["regime"], base=mi["base"], variant=mi["variant"],
               init_negative=mi["init_negative"], restoration_negative=mi["base"] == "neg_missing_wb", pattern=pat(mi["kind"], mi["sn_v"]),
               kind=mi["kind"], intended_data=intended, intended_level_v=mi["sn_v"], sn_ic_row0_v=mi["sn_ic_row0_v"], pin_ic=mi["pin_ic"],
               t_prep_ns=mi["t_prep_ns"], sn_post_init_v=ini, achieved_post_write_v=ini if mi["regime"] == "physical" else None,
               sn_op_start_v=meas.get(f"snos_{n}"), pre_read_v=pre, t_pre_read_ns=mi["t_pre_read_ns"],
               pre_read_minus_label_v=None if pre is None else round(pre - mi["sn_v"], 6),
               label_matches_pre_read=None if pre is None else abs(pre - mi["sn_v"]) <= LABEL_TOL_V,
               sn_during_sense_v=meas.get(f"snrd_{n}"), dec_v=dec, decided=d, sense_correct=sense, snend_v=sn, sn_ref_v=sn_ref,
               restore_fraction=None if sn is None or not sn_ref else round(sn / sn_ref, 6), **r)
    rec["outcome"] = outcome(sim_ok, sense, rec[f"restored_{int(PRIMARY * 100)}"] or mi["kind"] != "op1",
                             rec[f"restored_{int(PRIMARY * 100)}"] or mi["kind"] != "op0")
    return rec


def corner_results(corner: dict, man: dict, check: dict) -> tuple[list[dict], list[dict]]:
    meas = {m["name"]: m["value"] for m in corner["measurements"]}
    sim_ok = corner["status"] == "pass" and bool(meas)
    rows = [record(meas, mi, corner, sim_ok) for mi in man["instances"] if mi["kind"] != "ref"]
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["variant"], []).append(r)
    results = []
    for v, rs in by.items():
        op1 = [r for r in rs if r["kind"] == "op1"]
        op0 = [r for r in rs if r["kind"] == "op0"]
        k = f"restored_{int(PRIMARY * 100)}"
        sense = bool(sim_ok and all(r["sense_correct"] for r in rs))
        declared = all(check[r["instance"]]["declared_changes_only"] for r in rs)
        res = dict(corner=corner["process"], temp_c=corner["temperature_c"], variant=v, regime=rs[0]["regime"], base=rs[0]["base"],
                   klt_corner_status=corner["status"], simulator_ok=sim_ok, declared_changes_only=declared,
                   sense_correct=sense, sense_correct_by_pattern={r["pattern"]: r["sense_correct"] for r in rs},
                   decided_by_pattern={r["pattern"]: r["decided"] for r in rs}, dec_by_pattern_v={r["pattern"]: r["dec_v"] for r in rs},
                   restore_success=bool(sim_ok and all(r[k] for r in rs)),
                   restore_success_by_fraction={f"{f:g}": bool(sim_ok and all(r[f"restored_{int(f * 100)}"] for r in rs)) for f in FRACS},
                   restored_by_pattern={r["pattern"]: r[k] for r in rs},
                   restore_fraction_by_pattern={r["pattern"]: r["restore_fraction"] for r in rs},
                   intended_level_by_pattern_v={r["pattern"]: r["intended_level_v"] for r in rs},
                   achieved_post_write_by_pattern_v={r["pattern"]: r["achieved_post_write_v"] for r in rs},
                   sn_post_init_by_pattern_v={r["pattern"]: r["sn_post_init_v"] for r in rs},
                   pre_read_by_pattern_v={r["pattern"]: r["pre_read_v"] for r in rs},
                   pre_read_minus_label_by_pattern_v={r["pattern"]: r["pre_read_minus_label_v"] for r in rs},
                   label_matches_pre_read_all=all(r["label_matches_pre_read"] for r in rs),
                   snend_by_pattern_v={r["pattern"]: r["snend_v"] for r in rs},
                   min_op1_fraction=min((r["restore_fraction"] for r in op1 if r["restore_fraction"] is not None), default=None),
                   stored_zero_signed_levels_v=sorted(r["snend_v"] for r in op0 if r["snend_v"] is not None),
                   sn_ref_v=rs[0]["sn_ref_v"],
                   failure_reason=outcome(sim_ok, sense, all(r[k] for r in op1), all(r[k] for r in op0)),
                   # restoration verdict of a record whose sense decision is wrong is NOT a restore result: report it as such
                   restore_among_sense_correct_patterns={r["pattern"]: r[k] for r in rs if r["sense_correct"]})
        neg_restore = rs[0]["restoration_negative"]
        neg_init = rs[0]["init_negative"]
        res["overall_pass"] = bool(sim_ok and declared and sense and res["restore_success"]) and not (neg_restore or neg_init)
        if neg_restore:
            res["negative_control_ok"] = all(not r[k] for r in op1)
        if neg_init:
            res["init_negative_control_ok"] = init_negative_ok(rs)
        results.append(res)
    return rows, results


def init_negative_ok(rs: list[dict]) -> bool:
    """The no-write preparation must be CAUGHT: every pre-read level flagged as not the label AND every sense decision wrong
    (and therefore nothing restored). A no-write control whose read happens to look right is a failed control."""
    return bool(rs) and all(r["label_matches_pre_read"] is False and not r["sense_correct"] and not r[f"restored_{int(PRIMARY * 100)}"] for r in rs)


def ratio_hides_sense(rows: list[dict]) -> list[str]:
    """Stored-'1' records whose restore RATIO alone would pass but whose sense decision is wrong: they must be (and are) NOT restored."""
    k = f"restored_{int(PRIMARY * 100)}"
    bad = [r for r in rows if not r["sense_correct"] and r["kind"] == "op1" and (r["restore_fraction"] or 0) >= PRIMARY]
    assert not any(r[k] for r in bad), "a restore verdict passed an incorrect sense decision"
    return [r["instance"] + f"@{r['corner']}/{r['temp_c']}" for r in bad]


# ---- cross-regime views ------------------------------------------------------------------------------------------------------
def family(base: str) -> str:
    return SENSE_FAMILY.get(base, "rtl_sense_timing")


def sense_vs_pre_read(rows: list[dict]) -> dict:
    """Per corner and sense-timing family, over ALL regimes/variants/patterns: is the signed decision a monotone function of the
    MEASURED pre-read level? If every record decided '0' has a lower pre-read than every record decided '1' (and none is unresolved),
    a decision difference between regimes is attributable to the PREPARATION (the level presented to the unchanged sense path), not to
    a change in sensing. The bracket [max pre-read decided '0', min pre-read decided '1'] locates the effective threshold."""
    out = []
    keys = sorted({(r["corner"], r["temp_c"], family(r["base"])) for r in rows})
    for c, t, fam in keys:
        rs = [r for r in rows if (r["corner"], r["temp_c"], family(r["base"])) == (c, t, fam) and r["pre_read_v"] is not None]
        d0 = [r["pre_read_v"] for r in rs if r["decided"] == "0"]
        d1 = [r["pre_read_v"] for r in rs if r["decided"] == "1"]
        un = [dict(instance=r["instance"], pre_read_v=r["pre_read_v"], dec_v=r["dec_v"]) for r in rs if r["decided"] not in ("0", "1")]
        hi0, lo1 = (max(d0) if d0 else None), (min(d1) if d1 else None)
        mono = not un and (hi0 is None or lo1 is None or hi0 < lo1)
        out.append(dict(corner=c, temp_c=t, family=fam, records=len(rs), decided_0=len(d0), decided_1=len(d1), unresolved=un,
                        max_pre_read_decided_0_v=hi0, min_pre_read_decided_1_v=lo1, decision_monotone_in_pre_read=mono,
                        attribution="preparation (pre-read level)" if mono else "NOT explained by the pre-read level alone (sensing differs)"))
    return dict(rows=out, all_monotone=all(x["decision_monotone_in_pre_read"] for x in out),
                note="all regimes share the circuit and the sense waveform of their family; the label is not used here, only the measured pre-read")


def regime_comparison(rows: list[dict]) -> list[dict]:
    """Per (corner, base variant, pattern): measured pre-read, signed decision and restore per regime side by side."""
    idx = {(r["corner"], r["temp_c"], r["base"], r["pattern"], r["regime"]): r for r in rows if not r["init_negative"]}
    out = []
    for c, t, b, p in sorted({k[:4] for k in idx}):
        e = dict(corner=c, temp_c=t, base=b, pattern=p)
        for reg in ("legacy", "pin_ic", "physical"):
            r = idx.get((c, t, b, p, reg))
            e[reg] = None if r is None else dict(pre_read_v=r["pre_read_v"], achieved_post_write_v=r["achieved_post_write_v"], dec_v=r["dec_v"],
                                                 decided=r["decided"], sense_correct=r["sense_correct"], restore_fraction=r["restore_fraction"],
                                                 restored_95=r["restored_95"], outcome=r["outcome"])
        lg = e["legacy"]
        for reg in ("pin_ic", "physical"):
            x = e[reg]
            e[f"{reg}_minus_legacy_pre_read_v"] = (None if not lg or not x or lg["pre_read_v"] is None or x["pre_read_v"] is None
                                                   else round(x["pre_read_v"] - lg["pre_read_v"], 6))
            e[f"{reg}_sense_changed_vs_legacy"] = None if not lg or not x else x["decided"] != lg["decided"]
        out.append(e)
    return out


def survival(results: list[dict]) -> dict:
    """Per base variant and regime: corners sense-correct, corners restored (0.95), and restore AMONG sense-correct corners."""
    out = {}
    for b in sorted({r["base"] for r in results}):
        out[b] = {}
        for v in sorted({r["variant"] for r in results if r["base"] == b}):
            rs = [r for r in results if r["variant"] == v]
            sc = [r for r in rs if r["sense_correct"]]
            out[b][v] = dict(regime=rs[0]["regime"], corners=len(rs), simulator_ok=sum(r["simulator_ok"] for r in rs),
                             sense_correct_corners=len(sc), sense_incorrect_corners=[f"{r['corner']}/{r['temp_c']}" for r in rs if not r["sense_correct"]],
                             restore_success_0_95=sum(r["restore_success"] for r in rs),
                             restore_by_fraction={f"{f:g}": sum(r["restore_success_by_fraction"][f"{f:g}"] for r in rs) for f in FRACS},
                             restore_among_sense_correct_corners=f"{sum(r['restore_success'] for r in sc)}/{len(sc)}",
                             overall_pass_corners=sum(r["overall_pass"] for r in rs),
                             failure_reasons={k: sum(1 for r in rs if r["failure_reason"] == k) for k in sorted({r["failure_reason"] for r in rs})})
    return out


def restore_among_sense_correct_records(rows: list[dict]) -> dict:
    """Record-level view per (regime, base, pattern kind): restoration (0.95) counted ONLY over records whose sense decision is correct,
    next to how many records were sense-incorrect (those are never restore results). Separates 'does the write-back restore what was
    read correctly' from 'was it read correctly'."""
    k = f"restored_{int(PRIMARY * 100)}"
    out = {}
    for r in rows:
        key = f"{r['regime']}|{r['variant']}|{r['kind']}"
        e = out.setdefault(key, dict(regime=r["regime"], variant=r["variant"], kind=r["kind"], records=0, sense_correct=0, restored_among_sense_correct=0,
                                     sense_incorrect=0, restore_fraction_range_sense_correct=None))
        e["records"] += 1
        if r["sense_correct"]:
            e["sense_correct"] += 1
            e["restored_among_sense_correct"] += bool(r[k])
            if r["restore_fraction"] is not None and r["kind"] == "op1":
                lo, hi = e["restore_fraction_range_sense_correct"] or (r["restore_fraction"], r["restore_fraction"])
                e["restore_fraction_range_sense_correct"] = (min(lo, r["restore_fraction"]), max(hi, r["restore_fraction"]))
        else:
            e["sense_incorrect"] += 1
    return out


def documented_claims(rows: list[dict], results: list[dict]) -> dict:
    """Check the #134 README statements against this controlled run (reported, never forced)."""
    rtl = [r for r in rows if r["regime"] == "legacy" and family(r["base"]) == "rtl_sense_timing" and not r["init_negative"]]
    up = [r["pre_read_minus_label_v"] for r in rtl if r["pre_read_minus_label_v"] is not None]
    leg = {(r["corner"], r["temp_c"], r["base"], r["pattern"]): r for r in rows if r["regime"] == "legacy"}
    drop = []
    for r in rows:
        if r["regime"] == "pin_ic" and family(r["base"]) == "rtl_sense_timing":
            lg = leg.get((r["corner"], r["temp_c"], r["base"], r["pattern"]))
            if lg and lg["pre_read_v"] is not None and r["pre_read_v"] is not None:
                drop.append(r["pre_read_v"] - lg["pre_read_v"])
    fails = {}
    for r in rows:
        if r["regime"] == "pin_ic" and r["pattern"] == "op1_0.9" and not r["restoration_negative"] and not r["sense_correct"]:
            fails.setdefault(r["base"], set()).add((r["corner"], r["temp_c"]))
    pic_bases = sorted({r["base"] for r in rows if r["regime"] == "pin_ic" and not r["restoration_negative"]})
    sc = {b: sum(1 for x in results if x["variant"] == "pic_" + b and x["sense_correct"]) for b in pic_bases}
    return dict(
        startup_uplift=dict(documented_v=list(DOCUMENTED_UPLIFT_V), measured_legacy_pre_read_minus_label_v=[round(min(up), 4), round(max(up), 4)] if up else None,
                            reproduced=bool(up) and min(up) > 0,
                            note="sign reproduced = every legacy RTL-timing pre-read lies ABOVE its label; the documented range was 'about'"),
        pin_ic_minus_legacy_pre_read=dict(documented_v=list(DOCUMENTED_PIC_DROP_V), measured_v=[round(min(drop), 4), round(max(drop), 4)] if drop else None,
                                          within_documented=bool(drop) and DOCUMENTED_PIC_DROP_V[0] - REPRO_TOL_V <= min(drop) and max(drop) <= DOCUMENTED_PIC_DROP_V[1] + REPRO_TOL_V),
        pin_ic_stored1_0p9_sense_failures=dict(documented=sorted(f"{c}/{t}" for c, t in DOCUMENTED_PIC_SENSE_FAIL),
                                               measured_by_base={b: sorted(f"{c}/{t}" for c, t in fails.get(b, set())) for b in pic_bases},
                                               reproduced=all(fails.get(b, set()) == DOCUMENTED_PIC_SENSE_FAIL for b in pic_bases),
                                               sense_correct_corners_by_base=sc))


def reproduction(results: list[dict], rows: list[dict]) -> dict:
    out = {}
    if PRIOR_131.exists():
        prior = {(r["corner"], r["temp_c"], r["variant"]): r for r in load_json(PRIOR_131)["results"]}
        mism, md, n = [], 0.0, 0
        for r in results:
            if r["regime"] != "legacy":
                continue
            p = prior.get((r["corner"], r["temp_c"], r["variant"]))
            n += 1
            if p is None:
                mism.append(dict(corner=f"{r['corner']}/{r['temp_c']}", variant=r["variant"], what="missing"))
                continue
            for w in ("sense_correct", "restore_success", "simulator_ok", "restore_success_by_fraction"):
                if r[w] != p[w]:
                    mism.append(dict(corner=f"{r['corner']}/{r['temp_c']}", variant=r["variant"], what=w, now=r[w], recorded=p[w]))
            for k, v in r["snend_by_pattern_v"].items():
                pv = p["snend_by_pattern_v"].get(k)
                if pv is not None and v is not None:
                    md = max(md, abs(pv - v))
        out["legacy_vs_131"] = dict(recorded_run="results/20261010T130000Z", compared=n, verdict_mismatches=mism, all_verdicts_reproduce=not mism,
                                    max_abs_snend_diff_v=round(md, 6), snend_within_tolerance=md <= REPRO_TOL_V)
    else:
        out["legacy_vs_131"] = dict(checked=False)
    if PRIOR_134.exists():
        prior = {(r["corner"], r["temp_c"], r["variant"]): r for r in load_json(PRIOR_134)["results"] if r["variant"] in PIC_TO_134.values()}
        mism, md, mp, n = [], 0.0, 0.0, 0
        for r in results:
            if r["variant"] not in PIC_TO_134:
                continue
            p = prior.get((r["corner"], r["temp_c"], PIC_TO_134[r["variant"]]))
            n += 1
            if p is None:
                mism.append(dict(corner=f"{r['corner']}/{r['temp_c']}", variant=r["variant"], what="missing"))
                continue
            for w in ("sense_correct", "restore_success", "simulator_ok", "restore_success_by_fraction", "sense_correct_by_pattern"):
                if r[w] != p[w]:
                    mism.append(dict(corner=f"{r['corner']}/{r['temp_c']}", variant=r["variant"], what=w, now=r[w], recorded=p[w]))
            for k, v in r["snend_by_pattern_v"].items():
                pv = p["snend_by_pattern_v"].get(k)
                if pv is not None and v is not None:
                    md = max(md, abs(pv - v))
            if r["base"] != "baseline_analog":        # #134 snpre was at 1.9 ns = the RTL pre-read probe (the analog baseline asserts at 4 ns)
                for k, v in r["pre_read_by_pattern_v"].items():
                    pv = p["snpre_by_pattern_v"].get(k)
                    if pv is not None and v is not None:
                        mp = max(mp, abs(pv - v))
        out["pin_ic_vs_134_ic_artifact_check"] = dict(recorded_run="driver_sweep_results/20261010T141816Z", mapping=PIC_TO_134, compared=n,
                                                       verdict_mismatches=mism, all_verdicts_reproduce=not mism, max_abs_snend_diff_v=round(md, 6),
                                                       max_abs_pre_read_diff_v=round(mp, 6), within_tolerance=md <= REPRO_TOL_V and mp <= REPRO_TOL_V)
    else:
        out["pin_ic_vs_134_ic_artifact_check"] = dict(checked=False)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--report", type=Path, default=None, help="default: <run_dir>/klt_report.json.gz")
    ap.add_argument("--out-dir", type=Path, default=None, help="default: run_dir; use a NEW directory to re-analyse append-only")
    a = ap.parse_args(argv)
    rd = a.run_dir
    out = a.out_dir or rd
    out.mkdir(parents=True, exist_ok=True)
    pts, summ = out / "points.csv", out / "summary.json"
    for p in (pts, summ):
        if p.exists():
            print(f"refusing to overwrite existing evidence file {p}", file=sys.stderr)
            return 2
    man, check, rep = load_json(rd / "manifest.json"), load_json(rd / "consistency_check.json"), load_json(a.report or rd / "klt_report.json.gz")
    rows, results = [], []
    for c in rep["corners"]:
        r, s = corner_results(c, man, check)
        rows += r
        results += s
    with pts.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    env = rep["environment"]
    remote = env.get("remote", {})
    summary = dict(
        run_id=man["run_id"], issue=man["issue"], status=man["status"],
        framing="matched initialization controls of the unchanged refresh-replay circuit (ideal drivers); the physical regime is a zero-hold "
                "preparation control, not a retention/hold study (#94)",
        scope="27 C and 125 C, tt/ss/ff/sf/fs global corners, VDD 1.8 V, no mismatch (PROPOSED range, not ratified)",
        klt_status=rep["status"], corner_count=rep["corner_count"], batch_job_id=remote.get("job_id"), batch_instance_type=remote.get("instance_type"),
        report_netlist_sha256=env.get("netlist_sha256"), report_models_lib_sha256=env.get("models_lib_sha256"), engine=env.get("engine"),
        engine_version=env.get("engine_version"), report_provenance=rep.get("provenance"),
        analyzer_sha256_at_analysis=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        generated_deck_sha256=man["deck_sha256"], request_sha256=man["request_sha256"], pins=man["pins"], regimes=man["regimes"],
        preparation_assumptions=man["preparation_assumptions"], probe_definitions=man["probe_definitions"],
        criteria=dict(decide_v=AR.DECIDE_V, fracs=FRACS, primary_frac=PRIMARY, zero_max_v=AR.ZERO_MAX_V, label_tolerance_v=LABEL_TOL_V,
                      restore_requires_correct_decision=True),
        claims=dict(spec_changed=False, sense_threshold_changed=False, interval_changed=False, topology_changed=False, overlap_rule_changed=False,
                    physical_driver_validated=False, mismatch_validated=False, retention_hold_studied=False),
        declared_changes_only_all=all(c["declared_changes_only"] for c in check.values()),
        reproduction=reproduction(results, rows),
        documented_claims=documented_claims(rows, results),
        survival=survival(results),
        restore_among_sense_correct_records=restore_among_sense_correct_records(rows),
        sense_vs_pre_read=sense_vs_pre_read(rows),
        negative_controls=dict(
            restoration={r["variant"] + f"@{r['corner']}/{r['temp_c']}": r["negative_control_ok"] for r in results if "negative_control_ok" in r},
            restoration_all_ok=all(r["negative_control_ok"] for r in results if "negative_control_ok" in r),
            initialization={r["variant"] + f"@{r['corner']}/{r['temp_c']}": r["init_negative_control_ok"] for r in results if "init_negative_control_ok" in r},
            initialization_all_ok=all(r["init_negative_control_ok"] for r in results if "init_negative_control_ok" in r)),
        mislabeled_pre_read_records=sum(1 for r in rows if r["label_matches_pre_read"] is False),
        sense_incorrect_records=[dict(corner=f"{r['corner']}/{r['temp_c']}", variant=r["variant"], pattern=r["pattern"], pre_read_v=r["pre_read_v"],
                                      dec_v=r["dec_v"], restore_fraction=r["restore_fraction"]) for r in rows
                                 if not r["sense_correct"] and not r["init_negative"]],
        restore_ratio_high_but_sense_wrong=ratio_hides_sense(rows),
        regime_comparison=regime_comparison(rows),
        results=results)
    summ.write_text(json.dumps(summary, indent=1) + "\n")
    print(f"wrote {pts} and {summ}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
