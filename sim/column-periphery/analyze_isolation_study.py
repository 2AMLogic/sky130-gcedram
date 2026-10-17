#!/usr/bin/env python3
"""Reduce a `klt sim` report of the issue-#117 isolation study into findings.

Stdlib only. Two report kinds, told apart by file name, both read from ``results/``
(``.json`` or ``.json.gz``) and both producing NEW files next to the report (never
overwrites; refuses if they exist):

* ``isolation_klt_report_<RUN>.json``     global-corner sweep (request_isolation.json)
    -> ``isolation_points_<RUN>.csv`` + ``isolation_summary_<RUN>.json``
* ``isolation_mc_klt_report_<RUN>.json[.gz]``  Monte Carlo (request_isolation_mc.json)
    -> ``isolation_mc_points_<RUN>.csv`` + ``isolation_mc_summary_<RUN>.json``

Definitions (all ASSUMPTIONS, parameters at the top; the timeline is gen_column_periphery's):

* din  = V(sbl) - V(sref) at the latch-enable instant (negative = stored '1'); dpre the same just
  before the isolation gates start to close; dpost = V(rbl) 0.1 ns before the read select edge.
* shortfall (stored '1') = din_variant - din_ideal at the same corner (positive = a smaller input to the
  latch than the ideal-source setup). The acceptance bar of issue #117 is shortfall <= 0 at fs/27 C
  and ss/27 C; every corner is reported.
* write-'0' level: sn (row 0, 45 ns) and snmin (minimum of row 0 between the wordline fall and 45 ns).
  The sub-ground floor of SENSE_INPUT_CONTRACT.md is -0.135 V (stored '0' after write, min);
  a level below it (more negative) is a violation.
* periphery capacitance C_p = I*dt/(v(5 ns) - v(15 ns)) of a probe instance (precharge device + isolation
  gate on an rbl node with no array load and no latch, gates idle, discharged at 0.1 uA).
* compliance gates are #114's (settle <= 2 ns, |vrel - 0.9| <= 10 mV, correct decision with
  |d| >= 0.9 V, within 5 ns of the enable), per corner, both data values.
* ddin = din - dpre (the change from just before the isolation gates close to the enable instant: the
  closing disturbance plus the little signal movement in the lead time); its spread is insensitive to
  the cell's read-device mismatch for a stored '0' (read device off).
* Monte Carlo: per (corner, kind, data) the sample standard deviation of din over
  samples x replicas (independent mismatch draws per instance); the isolation pair's contribution is
  sqrt(max(0, var_kind - var_ideal)), i.e. the extra spread over the ideal-source column that has the same
  cell and latch mismatch. A normal-theory 95 % interval on sigma uses the Wilson-Hilferty chi-square
  approximation.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path
from statistics import NormalDist

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from _evidence_common import decided as _decided  # noqa: E402
from _evidence_common import load_json as read_json  # noqa: E402
import gen_isolation_study as S  # noqa: E402
import gen_column_periphery as G  # noqa: E402

SETTLE_BUDGET_S = G.T_PRE_BUDGET_S
RELEASE_TOL_V = G.SETTLE_V
RESOLVE_V = 0.9
T_WINDOW_S = 5e-9
FLOOR_V = -0.135
T_PRE_MID_S = G.T_PRE_ON_S + G.T_EDGE_S / 2
T_EN_MID_S = G.T_EN_S + G.T_EDGE_S / 2
N01 = NormalDist()


def corner_key(c: dict) -> tuple[str, int]:
    return c["process"], int(c["temperature_c"])


def meas_of(c: dict) -> dict[str, float | None]:
    return {m["name"]: m.get("value") for m in c["measurements"]}


def load(report: Path) -> dict[tuple[str, int], dict[str, float | None]]:
    out = {}
    for c in read_json(report)["corners"]:
        if c.get("status") != "pass":
            raise SystemExit(f"corner {corner_key(c)} status {c.get('status')}: not a clean run")
        out[corner_key(c)] = meas_of(c)
    return out


def decided(dend: float | None) -> str:
    return _decided(dend, RESOLVE_V)


def inst_metrics(m: dict, n: str) -> dict:
    g = lambda k: m.get(f"{k}_{n}")
    tpre, tdec = g("tpre"), g("tdec")
    return dict(
        settle_s=None if tpre is None else tpre - T_PRE_MID_S,
        vrel_v=g("vrel"), dpost_v=g("dpost"), dpre_v=g("dpre"), din_v=g("din"), dend_v=g("dend"),
        tdec_s=None if tdec is None else tdec - T_EN_MID_S, sn_v=g("sn"), snmin_v=g("snmin"))


def compliance(r1: dict, r0: dict) -> dict:
    ok_a = all(x["settle_s"] is not None and x["settle_s"] <= SETTLE_BUDGET_S for x in (r1, r0))
    ok_b = all(x["vrel_v"] is not None and abs(x["vrel_v"] - G.VRBL_V) <= RELEASE_TOL_V for x in (r1, r0))
    ok_c = decided(r1["dend_v"]) == "1" and decided(r0["dend_v"]) == "0"
    ok_d = all(x["tdec_s"] is not None and 0 <= x["tdec_s"] <= T_WINDOW_S for x in (r1, r0))
    return dict(settle_within_budget=ok_a, release_level_within_tol=ok_b, correct_decision=ok_c,
                decision_within_window=ok_d, compliant=ok_a and ok_b and ok_c and ok_d)


def periphery_cap_f(m: dict, tag: str) -> float | None:
    v1, v2 = m.get(f"vcp1_cp_{tag}"), m.get(f"vcp2_cp_{tag}")
    if v1 is None or v2 is None or v1 == v2:
        return None
    return S.I_PROBE_A * (S.T_PROBE_2 - S.T_PROBE_1) / (v1 - v2)


def probe_tag_for(v: dict) -> str | None:
    """Tag of the capacitance probe with the same rbl-side geometry as variant v (the probe only
    contains the precharge device, the isolation gate, an optional dummy switch and hold cap)."""
    key = lambda x: (x["wn"], x["wp"], x["wpre"], x["pdum"], x["csb"])
    allv = {x["tag"]: x for x in S.ISO_VARIANTS + S.PRE_VARIANTS + S.COMBO_VARIANTS + [S.FINAL] + S.FINAL_VARIANTS}
    for t in S.PROBE_TAGS:
        if key(allv[t]) == key(v):
            return t
    return None


def variants() -> list[dict]:
    seen, out = set(), []
    for v in (S.ISO_VARIANTS + S.MATCHED_VARIANTS + S.PRE_VARIANTS + S.COMBO_VARIANTS
              + [S.FINAL] + S.FINAL_VARIANTS):
        if v["tag"] not in seen:
            seen.add(v["tag"])
            out.append(v)
    return out


def summarize(data: dict) -> dict:
    corners = {}
    for (proc, temp), m in sorted(data.items()):
        k = f"{proc}/{temp}C"
        ideal = {d: inst_metrics(m, f"ideal_w{d}") for d in (1, 0)}
        rows = {}
        for v in variants():
            r1, r0 = inst_metrics(m, f"{v['tag']}_w1"), inst_metrics(m, f"{v['tag']}_w0")
            rows[v["tag"]] = dict(
                w1=r1, w0=r0, compliance=compliance(r1, r0),
                shortfall1_v=r1["din_v"] - ideal[1]["din_v"],          # > 0: smaller '1' input than ideal
                shortfall0_v=ideal[0]["din_v"] - r0["din_v"],          # > 0: smaller '0' input than ideal
                snmin0_margin_to_floor_v=r0["snmin_v"] - FLOOR_V,      # < 0: violates the floor
                cap_f=(periphery_cap_f(m, probe_tag_for(v)) if probe_tag_for(v) else None))
        drv = {}
        for v in S.DRV_VARIANTS:
            r0 = inst_metrics(m, f"{v['tag']}_w0")
            drv[v["tag"]] = dict(w0=r0, snmin0_margin_to_floor_v=r0["snmin_v"] - FLOOR_V,
                                 d_snmin_vs_ideal_v=r0["snmin_v"] - ideal[0]["snmin_v"])
        corners[k] = dict(ideal=ideal, ideal_snmin0_margin_to_floor_v=ideal[0]["snmin_v"] - FLOOR_V,
                          variants=rows, drivers=drv)
    agg = {}
    for v in variants():
        t = v["tag"]
        cs = corners.values()
        agg[t] = dict(
            desc=v["desc"],
            din1_fs27_v=corners["fs/27C"]["variants"][t]["w1"]["din_v"],
            din1_ss27_v=corners["ss/27C"]["variants"][t]["w1"]["din_v"],
            shortfall1_fs27_v=corners["fs/27C"]["variants"][t]["shortfall1_v"],
            shortfall1_ss27_v=corners["ss/27C"]["variants"][t]["shortfall1_v"],
            worst_shortfall1_v=max(c["variants"][t]["shortfall1_v"] for c in cs),
            worst_shortfall0_v=max(c["variants"][t]["shortfall0_v"] for c in cs),
            min_abs_din1_v=min(abs(c["variants"][t]["w1"]["din_v"]) for c in cs),
            min_abs_din0_v=min(abs(c["variants"][t]["w0"]["din_v"]) for c in cs),
            all_compliant=all(c["variants"][t]["compliance"]["compliant"] for c in cs),
            worst_settle_s=max(c["variants"][t]["w1"]["settle_s"] for c in cs),
            worst_snmin0_v=min(c["variants"][t]["w0"]["snmin_v"] for c in cs),
            corners_below_floor=sorted(k for k, c in corners.items()
                                       if c["variants"][t]["snmin0_margin_to_floor_v"] < 0),
            cap_f_fs27=corners["fs/27C"]["variants"][t]["cap_f"])
    dagg = {}
    for v in S.DRV_VARIANTS:
        t = v["tag"]
        dagg[t] = dict(
            desc=v["desc"],
            worst_snmin0_v=min(c["drivers"][t]["w0"]["snmin_v"] for c in corners.values()),
            corners_below_floor=sorted(k for k, c in corners.items()
                                       if c["drivers"][t]["snmin0_margin_to_floor_v"] < 0),
            worst_d_snmin_vs_ideal_v=min(c["drivers"][t]["d_snmin_vs_ideal_v"] for c in corners.values()))
    dagg["ideal"] = dict(
        worst_snmin0_v=min(c["ideal"][0]["snmin_v"] for c in corners.values()),
        corners_below_floor=sorted(k for k, c in corners.items() if c["ideal_snmin0_margin_to_floor_v"] < 0))
    return dict(corners=corners, aggregate=dict(variants=agg, drivers=dagg, floor_v=FLOOR_V))


# ------------------------------------------------------------------ Monte Carlo
def chi2_q(p: float, dof: int) -> float:
    """Wilson-Hilferty approximation of the chi-square quantile."""
    z = N01.inv_cdf(p)
    a = 2.0 / (9.0 * dof)
    return dof * (1 - a + z * math.sqrt(a)) ** 3


def sd_ci(sd: float, n: int) -> list[float]:
    return [sd * math.sqrt((n - 1) / chi2_q(0.975, n - 1)), sd * math.sqrt((n - 1) / chi2_q(0.025, n - 1))]


def mean_sd(xs: list[float]) -> tuple[float, float]:
    mu = sum(xs) / len(xs)
    return mu, math.sqrt(sum((x - mu) ** 2 for x in xs) / (len(xs) - 1))


def load_mc(report: Path):
    rep = read_json(report)
    rows = []
    for c in rep["corners"]:
        mc = c.get("monte_carlo") or {}
        m = meas_of(c) if c.get("status") == "pass" else {}
        rows.append((c["process"], int(c["temperature_c"]), mc.get("sample_index"), c.get("status"), m))
    return rep, rows


def kind_of(name: str) -> tuple[str, int, int]:
    mm = re.fullmatch(r"(\w+?)_w(\d)_r(\d+)", name)
    return mm.group(1), int(mm.group(2)), int(mm.group(3))


def summarize_mc(rows) -> dict:
    pts = S.mc_points()
    by: dict[tuple, dict[tuple, list]] = {}
    failed = 0
    for proc, temp, idx, status, m in rows:
        if status != "pass":
            failed += 1
            continue
        for p in pts:
            tag, d, _ = kind_of(p["name"])
            x = inst_metrics(m, p["name"])
            by.setdefault((proc, temp), {}).setdefault((tag, d), []).append(x)
    out = {}
    for (proc, temp), kinds in sorted(by.items()):
        k = f"{proc}/{temp}C"
        e = {}
        for (tag, d), xs in sorted(kinds.items()):
            dins = [x["din_v"] for x in xs if x["din_v"] is not None]
            dpre = [x["dpre_v"] for x in xs if x["dpre_v"] is not None]
            dd = [x["din_v"] - x["dpre_v"] for x in xs if x["din_v"] is not None and x["dpre_v"] is not None]
            mu, sd = mean_sd(dins)
            want = "1" if d == 1 else "0"
            e[f"{tag}_w{d}"] = dict(
                n=len(dins), din_mean_v=mu, din_sd_v=sd, din_sd_ci95_v=sd_ci(sd, len(dins)),
                dpre_sd_v=mean_sd(dpre)[1] if len(dpre) > 1 else None,
                ddin_mean_v=mean_sd(dd)[0], ddin_sd_v=mean_sd(dd)[1], ddin_sd_ci95_v=sd_ci(mean_sd(dd)[1], len(dd)),
                din_min_v=min(dins), din_max_v=max(dins),
                wrong_polarity_din=sum(1 for v in dins if (v > 0) != (d == 0)),
                wrong_decision=sum(1 for x in xs if decided(x["dend_v"]) != want),
                undecided_in_window=sum(1 for x in xs if x["tdec_s"] is None or x["tdec_s"] > T_WINDOW_S))
        contrib = {}
        for d in (1, 0):
            vi = e[f"ideal_w{d}"]["din_sd_v"] ** 2
            for tag in sorted({kind_of(p["name"])[0] for p in pts} - {"ideal"}):
                key = f"{tag}_w{d}"
                vr = e[key]["din_sd_v"] ** 2
                vdi, vdr = e[f"ideal_w{d}"]["ddin_sd_v"] ** 2, e[key]["ddin_sd_v"] ** 2
                contrib[key] = dict(
                    extra_sd_v=math.sqrt(max(0.0, vr - vi)), var_ratio_to_ideal=vr / vi,
                    extra_ddin_sd_v=math.sqrt(max(0.0, vdr - vdi)), ddin_var_ratio_to_ideal=vdr / vdi,
                    d_mean_vs_ideal_v=e[key]["din_mean_v"] - e[f"ideal_w{d}"]["din_mean_v"])
        out[k] = dict(instances=e, isolation_contribution=contrib)
    return dict(corners=out, n_failed_samples=failed)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("report", type=Path, help="results/isolation[_mc]_klt_report_<RUN>.json[.gz]")
    a = ap.parse_args(argv)
    name = a.report.name
    mm = re.fullmatch(r"isolation_(mc_)?klt_report_(\w+?)\.json(\.gz)?", name)
    if not mm:
        raise SystemExit(f"unrecognised report name {name}")
    mc, run_id = bool(mm.group(1)), mm.group(2)
    stem = "isolation_mc" if mc else "isolation"
    csv_path = a.report.with_name(f"{stem}_points_{run_id}.csv")
    sum_path = a.report.with_name(f"{stem}_summary_{run_id}.json")
    for p in (csv_path, sum_path):
        if p.exists():
            raise SystemExit(f"{p} exists; results are append-only -- use a new run id")
    rep = read_json(a.report)
    env = rep.get("environment", {})
    run = dict(run_id=run_id, netlist_sha256=env.get("netlist_sha256"), models_lib_sha256=env.get("models_lib_sha256"),
               remote_job_id=(env.get("remote") or {}).get("job_id"),
               klt_version=rep.get("provenance", {}).get("klt_version"),
               scope=("PROPOSED restricted range: 27/125 C, " + ("PDK _mm corners (tt/27, fs/27, ss/125, sf/125), "
                      "per-instance mismatch; " if mc else "tt/ss/ff/sf/fs global corners; ") + "VDD 1.8 V"))
    if mc:
        _, rows = load_mc(a.report)
        summ = summarize_mc(rows)
        summ["run"] = run
        summ["monte_carlo"] = env.get("monte_carlo")
        with csv_path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["corner", "temp_c", "sample", "status", "instance", "dpre_v", "din_v", "dend_v", "tdec_s"])
            for proc, temp, idx, status, m in rows:
                for p in S.mc_points():
                    x = inst_metrics(m, p["name"]) if status == "pass" else {}
                    w.writerow([proc, temp, idx, status, p["name"]] +
                               [x.get(h, "") for h in ("dpre_v", "din_v", "dend_v", "tdec_s")])
    else:
        data = load(a.report)
        summ = summarize(data)
        summ["run"] = run
        with csv_path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["corner", "temp_c", "instance", "settle_s", "vrel_v", "dpost_v", "dpre_v", "din_v", "dend_v",
                        "tdec_s", "sn_v", "snmin_v"])
            for (proc, temp), m in sorted(data.items()):
                for p in S.study_points():
                    if p["kind"] == "cprobe":
                        continue
                    x = inst_metrics(m, p["name"])
                    w.writerow([proc, temp, p["name"]] + [x[h] for h in (
                        "settle_s", "vrel_v", "dpost_v", "dpre_v", "din_v", "dend_v", "tdec_s", "sn_v", "snmin_v")])
    sum_path.write_text(json.dumps(summ, indent=1) + "\n")
    print(f"wrote {csv_path.name}, {sum_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
