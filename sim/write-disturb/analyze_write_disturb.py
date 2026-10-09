#!/usr/bin/env python3
"""Reduce a `klt sim` report of sim/write-disturb/ into per-corner findings (issue #98).

Stdlib only. Reads a committed ``results/klt_report_<RUN_ID>.json`` and writes
NEW files next to it (never overwrites; refuses if they exist):

* ``disturb_points_<RUN_ID>.csv``   one row per (corner, temperature, kind, cell, checkpoint)
* ``disturb_summary_<RUN_ID>.json`` per-corner worst cases, fractions of delta_V, equivalent
  retention-time loss, and the negative-control verdict

Definitions (all ASSUMPTIONS, parameters at the top):

* A victim's *erosion* is the change of its storage node in the direction that
  destroys its stored data, relative to the **matching no-disturb control**
  sampled at the same instant on the same node:
  stored '1' -> ``sn_control - sn_toggled`` (extra droop);
  stored '0' -> ``sn_toggled - sn_control`` (extra gain).
  Negative erosion means the stimulus helped (benign), and is kept, not clipped.
  Matching control: ``rep1`` -> ``ctl0`` (write bitline idles at 0 V), ``rep0`` -> ``ctl1``
  (idles at VDD); the ``neg_`` family uses the ``neg_`` controls (same leaky devices).
* ``frac_delta_v`` = erosion / DELTA_V_V (0.9 V, the ratified retention derivation's
  assumed sense margin).
* ``t_loss_ratified_s`` = frac * T_RET_RATIFIED_S: the retention-time the ratified
  formula ``t = C_SN * delta_V / I_leak`` would lose if the same fraction of delta_V
  were consumed (uses the ratified 1.106463 fF C_SN, so it inherits that assumption).
* ``refresh_bound_derated_s`` = T_RET_RATIFIED_S * (1 - frac) / 2, i.e. the 2x-margin
  refresh interval recomputed with the disturb charged to the sense margin. First
  order, linear in the fraction. Nothing here changes the ratified bound.
* ``equiv_hold_time_s`` = erosion / (isolated-cell hold drift rate of the same node in the
  matching worst-case control, between the first and last checkpoint). Both numerator and
  denominator scale with 1/C_SN, so this ratio does not depend on the C_SN assumption.
* The target cell (row 0, TARGET_COL) is the intended write, not a victim: it is listed
  in the points CSV (class ``target_cell``) with ``flagged`` empty and never enters a worst case.
* A point is FLAGGED when frac > DISTURB_LIMIT_FRAC (an ASSUMPTION, not a spec value).
  Values with |erosion| below NOISE_FLOOR_V are reported but marked below resolution.
* The negative control (every write access device LEAKY_W_FACTOR times wider) is VALID
  at a corner when its worst erosion at the last checkpoint is above the noise floor and
  at least NEG_MIN_RATIO times the normal-device worst erosion (the analysis can tell a
  leaky device from the real one). It is FLAGGED at a corner when that erosion also
  exceeds DISTURB_LIMIT_FRAC. Validity is required at every hot (125 C) corner and the
  flag at the worst-case retention corner (sf/125 C); both are reported per corner, not
  tuned: a 10x device that stays under the limit at some corner is a recorded fact.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gen_write_disturb as G  # noqa: E402

DELTA_V_V = G.DELTA_V_V
T_RET_S = G.T_RET_RATIFIED_S
DISTURB_LIMIT_FRAC = 0.10      # ASSUMPTION: flag when disturb exceeds 10 % of delta_V
NOISE_FLOOR_V = 1e-3           # ASSUMPTION: below 1 mV is below the numerical resolution of this deck
NEG_MIN_RATIO = 1.5            # negative control must exceed the normal device by this factor
HOT_C = 125
WORST_CASE = ("sf", 125)       # ratified worst-case retention corner

# (family, matching control) per device kind
PAIRS = {"std": (("rep1", "ctl0"), ("rep0", "ctl1")),
         "neg": (("neg_rep1", "neg_ctl0"), ("neg_rep0", "neg_ctl1"))}
# worst-case isolated-hold control for a stored bit, per device kind
HOLD_CTL = {"std": {1: "ctl0", 0: "ctl1"}, "neg": {1: "neg_ctl0", 0: "neg_ctl1"}}


def sc_by_name() -> dict:
    return {s["name"]: s for s in G.scenarios()}


def erosion(bit: int, sn_ctl: float, sn_tog: float) -> float:
    return (sn_ctl - sn_tog) if bit == 1 else (sn_tog - sn_ctl)


def victim_class(r: int, c: int) -> str:
    if r == 0:
        return "target_cell" if c == G.TARGET_COL else "half_selected_row0"
    return "shared_wbl_column" if c == G.TARGET_COL else "neighbor_column"


def toggle_rows(kind: str, meas: dict, corner: dict) -> list[dict]:
    scs = sc_by_name()
    rows = []
    t_first, t_last = G.checkpoint_time_s(G.N_SET[0]), G.checkpoint_time_s(G.N_SET[-1])
    for fam, ctl in PAIRS[kind]:
        for r in range(G.N_ROWS):
            for c in range(G.N_COLS):
                bit = G.stored_bit(scs[fam], r, c)
                hold_ctl = HOLD_CTL[kind][bit]
                a0 = meas.get(G.meas_name("sn", hold_ctl, r, c, f"n{G.N_SET[0]}"))
                a1 = meas.get(G.meas_name("sn", hold_ctl, r, c, f"n{G.N_SET[-1]}"))
                rate = None
                if a0 is not None and a1 is not None:
                    rate = abs(a1 - a0) / (t_last - t_first)    # V/s, isolated worst-case hold drift
                for n in G.N_SET:
                    tog = meas.get(G.meas_name("sn", fam, r, c, f"n{n}"))
                    ref = meas.get(G.meas_name("sn", ctl, r, c, f"n{n}"))
                    cls = victim_class(r, c)
                    row = dict(corner=corner["process"], temp_c=corner["temperature_c"], device=kind,
                               family=fam, control=ctl, cell=f"{r}{c}", cls=cls, stored=bit, n_writes=n,
                               sn_toggled_v=tog, sn_control_v=ref)
                    if tog is None or ref is None:
                        row.update(erosion_v=None, frac_delta_v=None, t_loss_ratified_s=None,
                                   refresh_bound_derated_s=None, equiv_hold_time_s=None,
                                   below_resolution=None, flagged=None)
                    else:
                        e = erosion(bit, ref, tog)
                        fr = e / DELTA_V_V
                        row.update(
                            erosion_v=e, frac_delta_v=fr,
                            t_loss_ratified_s=fr * T_RET_S,
                            refresh_bound_derated_s=T_RET_S * (1 - fr) / 2,
                            equiv_hold_time_s=(e / rate) if (rate and rate > 0 and e > 0) else None,
                            below_resolution=abs(e) < NOISE_FLOOR_V,
                            flagged=(fr > DISTURB_LIMIT_FRAC) if cls != "target_cell" else None)
                    rows.append(row)
    return rows


def hs_rows(meas: dict, corner: dict) -> list[dict]:
    scs = sc_by_name()
    rows = []
    for fam in ("hs_p1", "hs_p0"):
        sc = scs[fam]
        for r in range(G.N_ROWS):
            for c in range(G.N_COLS):
                bit = G.stored_bit(sc, r, c)
                g = lambda tag: meas.get(G.meas_name("hs", fam, r, c, tag))   # noqa: E731
                pre, post, lo, hi = g("pre"), g("post"), g("min"), g("max")
                cls = victim_class(r, c)
                row = dict(corner=corner["process"], temp_c=corner["temperature_c"], family=fam,
                           cell=f"{r}{c}", cls=cls, stored=bit, pre_v=pre, min_during_wl_v=lo,
                           max_during_wl_v=hi, post_v=post)
                if pre is None or post is None:
                    row.update(shift_v=None, erosion_v=None, frac_delta_v=None, flagged=None)
                else:
                    shift = post - pre
                    e = (-shift) if bit == 1 else shift
                    row.update(shift_v=shift, erosion_v=e, frac_delta_v=e / DELTA_V_V,
                               flagged=(e / DELTA_V_V) > DISTURB_LIMIT_FRAC)
                rows.append(row)
    return rows


def worst(rows: list[dict], **flt) -> dict | None:
    sel = [r for r in rows if r["erosion_v"] is not None and all(r[k] == v for k, v in flt.items())]
    return max(sel, key=lambda r: r["erosion_v"]) if sel else None


def brief(r: dict | None) -> dict | None:
    if r is None:
        return None
    keys = ("family", "cell", "cls", "stored", "n_writes", "erosion_v", "frac_delta_v",
            "t_loss_ratified_s", "refresh_bound_derated_s", "equiv_hold_time_s", "flagged", "below_resolution",
            "shift_v", "pre_v", "post_v")
    return {k: r[k] for k in keys if k in r}


def summarize_corner(corner: dict) -> tuple[list[dict], list[dict], dict]:
    meas = {m["name"]: m["value"] for m in corner["measurements"]}
    tog = toggle_rows("std", meas, corner) + toggle_rows("neg", meas, corner)
    hs = hs_rows(meas, corner)
    n_last = G.N_SET[-1]
    res: dict = dict(corner=corner["process"], temp_c=corner["temperature_c"], klt_corner_status=corner["status"],
                     missing_values=sum(1 for r in tog if r["erosion_v"] is None)
                     + sum(1 for r in hs if r["erosion_v"] is None))
    victims = ("shared_wbl_column", "neighbor_column", "half_selected_row0")
    res["repeated_toggle"] = {}
    for kind in ("std", "neg"):
        for fam, _ctl in PAIRS[kind]:
            ent = {}
            for cls in victims:
                ent[cls] = {f"n{n}": brief(worst(tog, device=kind, family=fam, cls=cls, n_writes=n))
                            for n in G.N_SET}
            cand = [worst(tog, device=kind, family=fam, cls=cl, n_writes=n_last) for cl in victims]
            ent["worst_at_last_checkpoint"] = brief(max((x for x in cand if x), key=lambda x: x["erosion_v"],
                                                        default=None))
            res["repeated_toggle"][fam] = ent
    # the headline: worst normal-device erosion over both polarities and all non-target victims, at N_MAX
    cand = [worst(tog, device="std", family=f, cls=cl, n_writes=n_last)
            for f, _ in PAIRS["std"] for cl in victims]
    cand = [c for c in cand if c]
    head = max(cand, key=lambda r: r["erosion_v"]) if cand else None
    res["worst_normal_device"] = brief(head)
    res["flagged_normal_device"] = bool(head and head["flagged"])
    # negative control verdict
    ncand = [worst(tog, device="neg", family=f, cls=cl, n_writes=n_last)
             for f, _ in PAIRS["neg"] for cl in victims]
    ncand = [c for c in ncand if c]
    nhead = max(ncand, key=lambda r: r["erosion_v"]) if ncand else None
    res["worst_negative_control"] = brief(nhead)
    if nhead is None or head is None:
        valid = flagged = False
    else:
        flagged = nhead["frac_delta_v"] > DISTURB_LIMIT_FRAC
        discriminates = head["erosion_v"] < NOISE_FLOOR_V or nhead["erosion_v"] >= NEG_MIN_RATIO * head["erosion_v"]
        valid = bool(nhead["erosion_v"] >= NOISE_FLOOR_V and discriminates)
    res["negative_control_valid"] = valid
    res["negative_control_flagged"] = bool(flagged)
    # half-select
    res["half_select"] = {}
    for fam in ("hs_p1", "hs_p0"):
        rows = [r for r in hs if r["family"] == fam]
        res["half_select"][fam] = dict(
            worst_half_selected_row0=brief(worst(rows, cls="half_selected_row0")),
            worst_victim=brief(max((r for r in rows if r["cls"] in ("shared_wbl_column", "neighbor_column")
                                    and r["erosion_v"] is not None), key=lambda r: r["erosion_v"], default=None)),
            max_abs_shift_half_selected_v=max((abs(r["shift_v"]) for r in rows
                                               if r["cls"] == "half_selected_row0" and r["shift_v"] is not None),
                                              default=None))
    return tog, hs, res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("report", type=Path, help="results/klt_report_<RUN_ID>.json")
    a = ap.parse_args(argv)
    rep = json.loads(a.report.read_text())
    run_id = a.report.stem.split("klt_report_", 1)[1]
    pts_csv = a.report.with_name(f"disturb_points_{run_id}.csv")
    hs_csv = a.report.with_name(f"disturb_halfselect_{run_id}.csv")
    sum_json = a.report.with_name(f"disturb_summary_{run_id}.json")
    for p in (pts_csv, hs_csv, sum_json):
        if p.exists():
            print(f"refusing to overwrite existing evidence file {p}", file=sys.stderr)
            return 2
    if rep.get("status") != "pass" or rep.get("errored"):
        print(f"report status {rep.get('status')!r}, {rep.get('errored')} errored corners: results not produced",
              file=sys.stderr)
        return 1
    tog_all, hs_all, corners = [], [], []
    for c in rep["corners"]:
        t, h, s = summarize_corner(c)
        tog_all += t
        hs_all += h
        corners.append(s)
    for path, rows in ((pts_csv, tog_all), (hs_csv, hs_all)):
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
    env = rep["environment"]
    remote = env.get("remote", {})
    hot = [c for c in corners if c["temp_c"] == HOT_C]
    summary = dict(
        run_id=run_id,
        status="PROPOSED_OPERATING_RANGE_NOT_RATIFIED",
        scope="27 C and 125 C, tt/ss/ff/sf/fs global corners, VDD=1.8 V, per spec/operating-range-decision-PROPOSED.md",
        klt_status=rep["status"], corner_count=rep["corner_count"],
        batch_job_id=remote.get("job_id"), batch_instance_type=remote.get("instance_type"),
        netlist_sha256=env.get("netlist_sha256"), models_lib_sha256=env.get("models_lib_sha256"),
        engine_version=env.get("engine_version"),
        assumptions=dict(delta_v_v=DELTA_V_V, t_ret_ratified_s=T_RET_S, refresh_bound_s=G.REFRESH_BOUND_S,
                         disturb_limit_frac=DISTURB_LIMIT_FRAC, noise_floor_v=NOISE_FLOOR_V,
                         neg_min_ratio=NEG_MIN_RATIO, n_set=G.N_SET, t_cycle_s=G.T_CYC_S,
                         v_sn1_v=G.V_SN1_V, v_sn0_v=G.V_SN0_V, leaky_w_factor=G.LEAKY_W_FACTOR),
        negative_control_valid_at_all_hot_corners=bool(hot) and all(c["negative_control_valid"] for c in hot),
        negative_control_flagged_at_worst_case_corner=any(
            c["negative_control_flagged"] for c in corners if (c["corner"], c["temp_c"]) == WORST_CASE),
        negative_control_flagged_corners=sorted(f"{c['corner']}/{c['temp_c']}" for c in corners
                                                if c["negative_control_flagged"]),
        negative_control_valid_corners=sorted(f"{c['corner']}/{c['temp_c']}" for c in corners
                                              if c["negative_control_valid"]),
        flagged_normal_device_corners=sorted(f"{c['corner']}/{c['temp_c']}" for c in corners
                                             if c["flagged_normal_device"]),
        claims=dict(spec_changed=False, refresh_bound_changed=False, mismatch_studied=False,
                    array_c_sn_reconciled=False, read_activity_included=False,
                    macro_level_victim_count_covered=False),
        corners=corners,
    )
    sum_json.write_text(json.dumps(summary, indent=1) + "\n")
    print(f"wrote {pts_csv.name}, {hs_csv.name} and {sum_json.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
