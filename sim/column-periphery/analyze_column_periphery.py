#!/usr/bin/env python3
"""Reduce a `klt sim` report of sim/column-periphery/ into findings (issue #114).

Stdlib only. Reads a committed ``results/klt_report_<RUN_ID>.json`` and writes
NEW files next to it (never overwrites; refuses if they exist):

* ``periphery_points_<RUN_ID>.csv``   one row per (corner, temperature, instance)
* ``periphery_summary_<RUN_ID>.json`` per-corner metrics, ideal-vs-real delta,
  contract compliance flags, assumptions

Definitions (all ASSUMPTIONS, parameters at the top):

* settle time = (time rbl first reaches VRBL - 10 mV) - (50 % point of the
  precharge-assert edge). rbl starts fully discharged (0 V), the worst
  case after a stored-'1' read.
* write-'1' level = V(sn) of row 0, sampled 13 ns after the wordline fell.
* sense-input contract compliance for the real slice (every item must hold,
  per corner, for both data values):
    (a) settle time <= the 2 ns precharge phase of t_row_refresh_op `anchored`
    (b) |V(rbl) - 0.9 V| <= 10 mV when the precharge is released
    (c) the latch decides the correct polarity with |d| >= 0.9 V
    (d) within 5 ns of the enable (sense-stage criterion)
  The 0.1 V worst-case separation placeholder of SENSE_INPUT_CONTRACT.md is
  reported (``min_abs_din_v``) but NOT a gate here: it is defined for a
  rbl-to-rbl separation between stored values, not for din.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gen_column_periphery as G  # noqa: E402

SETTLE_BUDGET_S = G.T_PRE_BUDGET_S
RELEASE_TOL_V = G.SETTLE_V
RESOLVE_V = 0.9
T_WINDOW_S = 5e-9
T_PRE_MID_S = G.T_PRE_ON_S + G.T_EDGE_S / 2
T_EN_MID_S = G.T_EN_S + G.T_EDGE_S / 2


def corner_key(c: dict) -> tuple[str, int]:
    return c["process"], int(c["temperature_c"])


def load(report: Path) -> dict[tuple[str, int], dict[str, float | None]]:
    rep = json.loads(report.read_text())
    out = {}
    for c in rep["corners"]:
        if c.get("status") != "pass":
            raise SystemExit(f"corner {corner_key(c)} status {c.get('status')}: not a clean run")
        out[corner_key(c)] = {m["name"]: m.get("value") for m in c["measurements"]}
    return out


def derived(m: dict, n: str) -> dict:
    tpre, tdec = m.get(f"tpre_{n}"), m.get(f"tdec_{n}")
    d = dict(
        settle_s=None if tpre is None else tpre - T_PRE_MID_S,
        vrel_v=m.get(f"vrel_{n}"),
    )
    if f"sn_{n}" in m:
        d.update(sn_v=m[f"sn_{n}"], din_v=m[f"din_{n}"], dend_v=m[f"dend_{n}"],
                 tdec_s=None if tdec is None else tdec - T_EN_MID_S)
    return d


def decided(dend: float | None) -> str:
    if dend is None:
        return "none"
    return "1" if dend <= -RESOLVE_V else "0" if dend >= RESOLVE_V else "unresolved"


def compliance(r1: dict, r0: dict) -> dict:
    ok_a = all(x["settle_s"] is not None and x["settle_s"] <= SETTLE_BUDGET_S for x in (r1, r0))
    ok_b = all(x["vrel_v"] is not None and abs(x["vrel_v"] - G.VRBL_V) <= RELEASE_TOL_V for x in (r1, r0))
    ok_c = decided(r1["dend_v"]) == "1" and decided(r0["dend_v"]) == "0"
    ok_d = all(x["tdec_s"] is not None and 0 <= x["tdec_s"] <= T_WINDOW_S for x in (r1, r0))
    return dict(settle_within_budget=ok_a, release_level_within_tol=ok_b,
                correct_decision=ok_c, decision_within_window=ok_d,
                compliant=ok_a and ok_b and ok_c and ok_d)


def summarize(data: dict) -> dict:
    corners = {}
    for (proc, temp), m in sorted(data.items()):
        k = f"{proc}/{temp}C"
        inst = {p["name"]: derived(m, p["name"]) for p in G.instances()}
        delta = {}
        for d in (1, 0):
            i, r = inst[f"ideal_w{d}"], inst[f"real_w{d}"]
            delta[f"w{d}"] = dict(
                settle_s_ideal=i["settle_s"], settle_s_real=r["settle_s"],
                sn_v_ideal=i["sn_v"], sn_v_real=r["sn_v"], d_sn_v=r["sn_v"] - i["sn_v"],
                din_v_ideal=i["din_v"], din_v_real=r["din_v"], d_din_v=r["din_v"] - i["din_v"],
                tdec_s_ideal=i["tdec_s"], tdec_s_real=r["tdec_s"])
        comp = compliance(inst["real_w1"], inst["real_w0"])
        comp["min_abs_din_v"] = min(abs(inst["real_w1"]["din_v"]), abs(inst["real_w0"]["din_v"]))
        corners[k] = dict(instances=inst, delta=delta, compliance=comp)
    worst = lambda f: max(f(c) for c in corners.values())
    agg = dict(
        corners=len(corners),
        all_compliant=all(c["compliance"]["compliant"] for c in corners.values()),
        worst_settle_s_real=worst(lambda c: c["instances"]["real_w1"]["settle_s"]),
        worst_settle_s_ideal=worst(lambda c: c["instances"]["ideal_w1"]["settle_s"]),
        max_abs_d_sn_v=worst(lambda c: max(abs(c["delta"]["w1"]["d_sn_v"]), abs(c["delta"]["w0"]["d_sn_v"]))),
        min_abs_din_v_real=min(c["compliance"]["min_abs_din_v"] for c in corners.values()),
        sweep_worst_settle_s={f"W={w}um": worst(lambda c, w=w: c["instances"][f"sw_{round(w * 100):04d}"]["settle_s"])
                              for w in G.PRE_W_SWEEP_UM},
    )
    return dict(corners=corners, aggregate=agg)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("report", type=Path, help="results/klt_report_<RUN_ID>.json")
    a = ap.parse_args(argv)
    run_id = a.report.stem.removeprefix("klt_report_")
    rep = json.loads(a.report.read_text())
    summ = summarize(load(a.report))
    summ["run"] = dict(
        run_id=run_id, netlist_sha256=rep["environment"].get("netlist_sha256"),
        models_lib_sha256=rep["environment"].get("models_lib_sha256"),
        remote_job_id=(rep["environment"].get("remote") or {}).get("job_id"),
        klt_version=rep.get("provenance", {}).get("klt_version"),
        scope="PROPOSED restricted range: 27/125 C, tt/ss/ff/sf/fs, VDD 1.8 V; global corners only, no mismatch")
    summ["assumptions"] = dict(
        C_RBL_F=G.C_RBL_F, C_WBL_F=G.C_WBL_F, VRBL_V=G.VRBL_V, DREF_V=G.DREF_V,
        vpre_rail="ideal 0.9 V source", settle_tol_v=G.SETTLE_V, settle_budget_s=SETTLE_BUDGET_S,
        reference_side="ideal precharge switch and matched dummy cap (not part of the slice)")
    csv_path = a.report.with_name(f"periphery_points_{run_id}.csv")
    sum_path = a.report.with_name(f"periphery_summary_{run_id}.json")
    for p in (csv_path, sum_path):
        if p.exists():
            raise SystemExit(f"{p} exists; results are append-only -- use a new run id")
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["corner", "temp_c", "instance", "settle_s", "vrel_v", "sn_v", "din_v", "dend_v", "tdec_s"])
        for k, c in summ["corners"].items():
            proc, temp = k.split("/")
            for n, x in c["instances"].items():
                w.writerow([proc, temp.rstrip("C"), n] + [x.get(h, "") for h in
                           ("settle_s", "vrel_v", "sn_v", "din_v", "dend_v", "tdec_s")])
    sum_path.write_text(json.dumps(summ, indent=1) + "\n")
    print(f"wrote {csv_path.name}, {sum_path.name}; all_compliant={summ['aggregate']['all_compliant']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
