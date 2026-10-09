#!/usr/bin/env python3
"""Reduce a `klt sim` Monte Carlo report of sim/sense-mismatch/ to statistics (issue #81).

Stdlib only. Reads a committed ``results/klt_report_<RUN_ID>.json[.gz]``
(stage-only offset study, ``request.json``) or
``results/klt_report_cell_<RUN_ID>.json[.gz]`` (end-to-end variant,
``request_cell.json``; ``.gz`` = the klt JSON output gzip-compressed because
the per-sample report is tens of MB) and writes NEW files next to it
(never overwrites; refuses if they exist):

* stage: ``mismatch_points_<RUN_ID>.csv`` + ``mismatch_summary_<RUN_ID>.json``
* cell:  ``mismatch_cell_points_<RUN_ID>.csv`` + ``mismatch_cell_summary_<RUN_ID>.json``

Every Monte Carlo sample of every corner is one row group in the CSV,
including samples klt reports as failed (values empty) -- failed points are
kept and counted, never dropped silently.

Definitions (ASSUMPTIONS unless stated; parameters at the top):

* d = V(rbl) - V(ref). '0' decision: final d >= +RESOLVE_V; '1': <= -RESOLVE_V.
  Stage-only: correct decision is '0' for d > 0 and '1' for d < 0 (d = 0 has
  no correct answer; it is reported as P(decide '0')).
* resolves = correct decision AND tdec <= T_WINDOW_S (same rule as
  sim/sense-stage/analyze_sense_stage.py).
* Offset model (probit): P(decide '0' | x) = Phi((x - mu) / sigma), fitted by
  maximum likelihood over every trial that reached a definite polarity.
  sigma is the input-referred offset standard deviation, mu its mean
  (systematic offset). Primary x = nominal d (precharge differential, what the
  column delivers); secondary x = din (differential at the enable instant,
  binned to 0.1 mV for the fit).
  95 % confidence interval on sigma and mu: profile likelihood
  (2 * delta logL = chi2_1(0.95) = 3.841). The usual chi-square interval on a
  sample standard deviation does NOT apply here: the latch offset is never
  observed directly, only binary decisions.
* Differential at an error-rate target p (two-sided Gaussian extrapolation):
  d_p = |mu| + z(1-p) * sigma, with an upper value using the sigma upper CI.
  This is an EXTRAPOLATION of the fitted normal model; the data alone support
  only error rates down to about 3 / (trials per point) (rule of three).
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import sys
from pathlib import Path
from statistics import NormalDist

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gen_sense_mismatch as M  # noqa: E402
import analyze_sense_stage as SS  # noqa: E402  (sim/sense-stage, on sys.path via gen_sense_mismatch)

SENSE_STAGE_SUMMARY = M.REPO / "sim/sense-stage/results/sense_summary_20261009T131831Z.json"


def _nominal_min_resolvable(base: str, temp_c: int) -> dict:
    """min resolvable stored-'1' level per reference at the global (no-mismatch) corner, from the
    committed sense-stage summary (issue #60), for comparison only."""
    d = json.loads(SENSE_STAGE_SUMMARY.read_text())
    for c in d["corners"]:
        if c["corner"] == base and c["temp_c"] == temp_c:
            return {k: e["sn1_min_resolvable_upper_bound_v"] for k, e in c["end_to_end"].items()}
    return {}

T_WINDOW_S = 5e-9              # ASSUMPTION (as sense-stage): decision within 5 ns of enable
RESOLVE_V = 0.9                # |d| >= VDD/2 counts as decided
ERROR_RATE_TARGETS = [1e-3, 1e-6]   # ASSUMPTION: no ratified per-decision error-rate target exists
ALPHA = 0.05                   # 95 % intervals
CHI2_1_95 = 3.841458820694124  # chi-square(1 dof) 0.95 quantile
N01 = NormalDist()


# ----------------------------------------------------------------- statistics
def wilson(k: int, n: int, z: float = 1.959963984540054) -> list[float] | None:
    """Wilson score 95 % interval for a binomial proportion."""
    if n == 0:
        return None
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [round(max(0.0, c - h), 6), round(min(1.0, c + h), 6)]


def rule_of_three_upper(n: int) -> float | None:
    """Exact one-sided 95 % upper bound on p when 0 of n trials fail."""
    return None if n == 0 else 1 - ALPHA ** (1 / n)


SQRT2 = math.sqrt(2.0)
SQRT2PI = math.sqrt(2.0 * math.pi)


def _phi(z: float) -> float:
    return 0.5 * math.erfc(-z / SQRT2)


def _terms(eta: float, k: int, n: int) -> tuple[float, float, float]:
    """(log-likelihood, score d/deta, Fisher weight) of one (k of n) group at eta.

    p and q = 1 - p are both computed with erfc so neither tail loses precision
    (statistics.NormalDist.cdf underflows to 0 below about -8)."""
    p = 0.5 * math.erfc(-eta / SQRT2)
    q = 0.5 * math.erfc(eta / SQRT2)
    f = math.exp(-0.5 * eta * eta) / SQRT2PI
    if p <= 0.0 or q <= 0.0:                     # |eta| > ~38: outcome is certain
        ll = 0.0 if (k == n and q <= 0.0) or (k == 0 and p <= 0.0) else -1e300
        return ll, 0.0, 0.0
    ll = (k * math.log(p) if k else 0.0) + ((n - k) * math.log(q) if n - k else 0.0)
    return ll, f * (k - n * p) / (p * q), n * f * f / (p * q)


def _ll(g: list[tuple[float, int, int]], a: float, b: float) -> float:
    return sum(_terms(a + b * x, k, n)[0] for x, k, n in g)


def _mle(g: list[tuple[float, int, int]], fix_b: float | None = None, fix_mu: float | None = None,
         a: float = 0.0, b: float = 1 / 30) -> tuple[float, float, float]:
    """Fisher scoring for P = Phi(a + b x); optionally with b fixed (profile in sigma)
    or with mu = -a/b fixed (profile in mu). Returns (a, b, logL)."""
    if fix_b is not None:
        b = fix_b
    for _ in range(200):
        if fix_mu is not None:
            a = -b * fix_mu
        ll0 = _ll(g, a, b)
        s0 = s1 = w00 = w01 = w11 = 0.0
        for x, k, n in g:
            _, sc, w = _terms(a + b * x, k, n)
            xx = x if fix_mu is None else x - fix_mu
            s0 += sc
            s1 += sc * xx
            w00 += w
            w01 += w * xx
            w11 += w * xx * xx
        if fix_b is not None:
            da, db = (s0 / w00 if w00 else 0.0), 0.0
        elif fix_mu is not None:
            da, db = 0.0, (s1 / w11 if w11 else 0.0)
        else:
            det = w00 * w11 - w01 * w01
            if det <= 0:
                break
            da, db = (w11 * s0 - w01 * s1) / det, (w00 * s1 - w01 * s0) / det
        step, accepted = 1.0, False
        while step > 1e-9:                      # damped step: never decrease logL, keep b > 0
            na, nb = a + step * da, b + step * db
            if fix_mu is not None:
                na = -nb * fix_mu
            if nb > 0 and _ll(g, na, nb) >= ll0 - 1e-12:
                accepted = True
                break
            step /= 2
        if not accepted:
            break
        a, b = na, nb
        if abs(da) < 1e-10 and abs(db) < 1e-12:   # full scoring step negligible: converged
            break
    if fix_mu is not None:
        a = -b * fix_mu
    return a, b, _ll(g, a, b)


def probit_fit(xs_mv: list[float], ys: list[int]) -> dict:
    """ML probit fit P(y=1) = Phi((x - mu)/sigma), x in mV, with profile-likelihood 95 % CIs."""
    n = len(xs_mv)
    if n < 3 or all(ys) or not any(ys):
        return dict(n=n, fit="not_identifiable")
    grp: dict[float, list[int]] = {}
    for x, y in zip(xs_mv, ys):
        kn = grp.setdefault(round(x, 6), [0, 0])
        kn[0] += y
        kn[1] += 1
    g = [(x, k, m) for x, (k, m) in sorted(grp.items())]
    a, b, llmax = _mle(g)
    sigma, mu = 1 / b, -a / b
    cut = llmax - CHI2_1_95 / 2
    span = max(xs_mv) - min(xs_mv)

    def root(f, inside: float, outside: float) -> float | None:
        if f(outside) > cut:
            return None                      # not closed inside the search range
        for _ in range(50):
            m = (inside + outside) / 2
            if f(m) > cut:
                inside = m
            else:
                outside = m
        return (inside + outside) / 2

    f_sig = lambda s: _mle(g, fix_b=1 / s, a=a)[2]  # noqa: E731
    f_mu = lambda m: _mle(g, fix_mu=m, b=b)[2]  # noqa: E731
    r = lambda v: None if v is None else round(v, 4)  # noqa: E731
    return dict(
        n=n, fit="ok", sigma_mv=r(sigma),
        sigma_ci95_mv=[r(root(f_sig, sigma, sigma / 50)), r(root(f_sig, sigma, sigma * 50))],
        mu_mv=r(mu), mu_ci95_mv=[r(root(f_mu, mu, mu - span)), r(root(f_mu, mu, mu + span))],
        loglik=round(llmax, 6),
    )


def gof(groups: list[tuple[float, int, int]], mu_mv: float, sigma_mv: float) -> dict:
    """Pearson chi-square of observed '0' counts vs the fitted probit, per swept point."""
    chi2, used = 0.0, 0
    for x_mv, k, n in groups:
        p = _phi((x_mv - mu_mv) / sigma_mv)
        e = n * p
        v = n * p * (1 - p)
        if v > 1e-9:
            chi2 += (k - e) ** 2 / v
            used += 1
    return dict(pearson_chi2=round(chi2, 4), points_used=used, dof=max(used - 2, 0))


# --------------------------------------------------------------- report I/O
def decided(dend: float | None) -> str:
    if dend is None:
        return "none"
    if dend <= -RESOLVE_V:
        return "1"
    if dend >= RESOLVE_V:
        return "0"
    return "unresolved"


def sample_rows(rep: dict, kind: str) -> list[dict]:
    insts = M.stage_instances() if kind == "stage" else M.cell_instances()
    rows = []
    for c in rep["corners"]:
        mc = c.get("monte_carlo") or {}
        meas = {m["name"]: m.get("value") for m in c.get("measurements") or []}
        for i in insts:
            n = i["name"]
            din, dend, tdec = meas.get(f"din_{n}"), meas.get(f"dend_{n}"), meas.get(f"tdec_{n}")
            if kind == "stage":
                expect = "" if i["d_mv"] == 0 else ("0" if i["d_mv"] > 0 else "1")
            else:
                expect = "1" if i["kind"] == "cell1" else "0"
            dec = decided(dend)
            rows.append(dict(
                corner=c["process"], temp_c=c["temperature_c"], sample_index=mc.get("sample_index"),
                mc_seed=mc.get("seed"), klt_status=c["status"], instance=n, kind=i["kind"],
                ref_offset_v=i["dref"], nominal_d_mv=i.get("d_mv", ""), sn_level_v=i.get("sn", ""),
                replica=i["rep"], din_v=din, dend_v=dend, tdec_s=tdec, expected=expect, decided=dec,
                correct="" if not expect else dec == expect,
                resolves_in_window="" if not expect else (dec == expect and tdec is not None and tdec <= T_WINDOW_S)))
    return rows


def _corner_key(r: dict) -> tuple[str, int]:
    return (r["corner"], r["temp_c"])


def _std(v: list[float]) -> float | None:
    if len(v) < 2:
        return None
    m = sum(v) / len(v)
    return math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))


def _sample_counts(rows: list[dict]) -> dict:
    samples = {(r["sample_index"], r["klt_status"]) for r in rows}
    seeds = {r["sample_index"]: r["mc_seed"] for r in rows}
    failed = sorted(s for s, st in samples if st != "pass")
    return dict(n_samples=len({s for s, _ in samples}), n_failed_samples=len(failed),
                failed_sample_indices=failed, distinct_seeds=len(set(seeds.values())),
                missing_values=sum(1 for r in rows if r["dend_v"] is None or r["tdec_s"] is None or r["din_v"] is None))


def summarize_stage_corner(rows: list[dict]) -> dict:
    res: dict = dict(corner=rows[0]["corner"], temp_c=rows[0]["temp_c"])
    res.update(_sample_counts(rows))
    res["n_trials"] = len(rows)
    res["n_no_definite_polarity"] = sum(1 for r in rows if r["decided"] in ("none", "unresolved"))
    per_d = []
    groups_nom = []
    for d in sorted(set(M.D_MV)):
        rr = [r for r in rows if r["nominal_d_mv"] == d]
        n = len(rr)
        k0 = sum(1 for r in rr if r["decided"] == "0")
        k1 = sum(1 for r in rr if r["decided"] == "1")
        dins = [r["din_v"] * 1e3 for r in rr if r["din_v"] is not None]
        e = dict(nominal_d_mv=d, trials=n, decided_0=k0, decided_1=k1, no_definite_polarity=n - k0 - k1,
                 din_mean_mv=None if not dins else round(sum(dins) / len(dins), 4),
                 din_std_mv=None if _std(dins) is None else round(_std(dins), 4))
        if d == 0:
            e["p_decide_0"] = round(k0 / n, 6) if n else None
            e["p_decide_0_ci95"] = wilson(k0, n)
        else:
            kc = sum(1 for r in rr if r["correct"] is True)
            kr = sum(1 for r in rr if r["resolves_in_window"] is True)
            e.update(p_correct=round(kc / n, 6) if n else None, p_correct_ci95=wilson(kc, n),
                     p_resolves_in_window=round(kr / n, 6) if n else None,
                     p_resolves_in_window_ci95=wilson(kr, n), errors=n - kc)
            if n and kc == n:
                e["error_rate_upper95_zero_errors"] = round(rule_of_three_upper(n), 6)
        per_d.append(e)
        if k0 + k1:
            groups_nom.append((float(d), k0, k0 + k1))
    res["per_differential"] = per_d
    defin = [r for r in rows if r["decided"] in ("0", "1")]
    fit_nom = probit_fit([float(r["nominal_d_mv"]) for r in defin], [1 if r["decided"] == "0" else 0 for r in defin])
    dd = [r for r in defin if r["din_v"] is not None]
    fit_din = probit_fit([round(r["din_v"] * 1e3, 1) for r in dd], [1 if r["decided"] == "0" else 0 for r in dd])
    if fit_nom.get("fit") == "ok":
        fit_nom["goodness_of_fit"] = gof(groups_nom, fit_nom["mu_mv"], fit_nom["sigma_mv"])
        targets = []
        for p in ERROR_RATE_TARGETS:
            z = N01.inv_cdf(1 - p)
            s_hi = fit_nom["sigma_ci95_mv"][1]
            m_hi = max(abs(v) for v in fit_nom["mu_ci95_mv"] if v is not None) if all(
                v is not None for v in fit_nom["mu_ci95_mv"]) else None
            targets.append(dict(
                error_rate_target_ASSUMPTION=p, z=round(z, 4),
                differential_mv_point=round(abs(fit_nom["mu_mv"]) + z * fit_nom["sigma_mv"], 3),
                differential_mv_upper95=None if s_hi is None or m_hi is None else round(m_hi + z * s_hi, 3),
                basis="Gaussian extrapolation of the probit fit (not observed at this rate)"))
        fit_nom["differential_at_error_rate"] = targets
    res["probit_fit_nominal_d"] = fit_nom
    res["probit_fit_din"] = fit_din
    trials_per_point = min(e["trials"] for e in per_d)
    res["empirical_resolution"] = dict(
        trials_per_point=trials_per_point,
        smallest_error_rate_resolvable_upper95=None if not trials_per_point else round(rule_of_three_upper(trials_per_point), 6),
        smallest_differential_mv_with_zero_errors_both_polarities=next(
            (d for d in sorted({abs(e["nominal_d_mv"]) for e in per_d if e["nominal_d_mv"]})
             if all(e.get("errors") == 0 and e["no_definite_polarity"] == 0 for e in per_d if abs(e["nominal_d_mv"]) >= d)), None),
    )
    # controls: mismatch must actually act (replicas at one point disagree somewhere)
    disagree = 0
    for d in M.D_MV:
        for s in {r["sample_index"] for r in rows}:
            decs = {r["decided"] for r in rows if r["nominal_d_mv"] == d and r["sample_index"] == s and r["decided"] in ("0", "1")}
            disagree += len(decs) > 1
    res["control_replica_disagreements"] = disagree
    return res


def summarize_cell(rows: list[dict]) -> dict:
    res: dict = dict(corner=rows[0]["corner"], temp_c=rows[0]["temp_c"])
    res.update(_sample_counts(rows))
    res["n_trials"] = len(rows)
    out = []
    for dref in M.CELL_DVREF_V:
        for kind, levels in (("cell0", M.CELL_SN0_LEVELS_V), ("cell1", M.CELL_SN1_LEVELS_V)):
            for lvl in levels:
                rr = [r for r in rows if r["kind"] == kind and r["ref_offset_v"] == dref and r["sn_level_v"] == lvl]
                n = len(rr)
                kc = sum(1 for r in rr if r["correct"] is True)
                kr = sum(1 for r in rr if r["resolves_in_window"] is True)
                dins = [r["din_v"] * 1e3 for r in rr if r["din_v"] is not None]
                q = sorted(dins)
                out.append(dict(
                    kind=kind, ref_offset_mv=round(dref * 1000), sn_level_v=lvl, trials=n,
                    p_correct=round(kc / n, 6) if n else None, p_correct_ci95=wilson(kc, n),
                    p_resolves_in_window=round(kr / n, 6) if n else None, p_resolves_in_window_ci95=wilson(kr, n),
                    din_mean_mv=None if not dins else round(sum(dins) / len(dins), 4),
                    din_std_mv=None if _std(dins) is None else round(_std(dins), 4),
                    din_min_mv=None if not q else round(q[0], 4), din_max_mv=None if not q else round(q[-1], 4)))
    res["per_level"] = out
    # per reference: lowest stored-'1' level from which EVERY swept level at or above it had
    # zero errors (resolves in window, all trials), and the empirical bound that zero errors supports
    base = res["corner"].removesuffix("_mm")
    written = SS.load_phase3_writes().get((base, res["temp_c"]))
    nominal = _nominal_min_resolvable(base, res["temp_c"])
    per_ref = {}
    for dref in M.CELL_DVREF_V:
        lv = sorted((e for e in out if e["kind"] == "cell1" and e["ref_offset_mv"] == round(dref * 1000)),
                    key=lambda e: e["sn_level_v"])
        k = len(lv)
        while k > 0 and lv[k - 1]["p_resolves_in_window"] == 1.0:
            k -= 1
        lo = lv[k]["sn_level_v"] if k < len(lv) else None
        at_half = next((e for e in lv if abs(e["sn_level_v"] - 0.9) < 1e-9), None)
        z = [e for e in out if e["kind"] == "cell0" and e["ref_offset_mv"] == round(dref * 1000)]
        per_ref[f"{round(dref * 1000)}mV"] = dict(
            sn1_lowest_level_all_higher_zero_errors_v=lo,
            sn1_highest_level_with_errors_v=lv[k - 1]["sn_level_v"] if 0 < k <= len(lv) else None,
            zero_error_bound_upper95=None if lo is None else round(rule_of_three_upper(lv[k]["trials"]), 6),
            nominal_global_corner_min_resolvable_v=nominal.get(f"{round(dref * 1000)}mV"),
            phase2_written_1_min_v=written,
            # [pessimistic, optimistic] usable droop at this error resolution (0.05 V level grid)
            usable_droop_v=None if lo is None or written is None else [
                round(written - lo, 4),
                round(written - (lv[k - 1]["sn_level_v"] if k > 0 else lo), 4)],
            p_resolves_at_sn_0p9v=None if at_half is None else at_half["p_resolves_in_window"],
            p_resolves_at_sn_0p9v_ci95=None if at_half is None else at_half["p_resolves_in_window_ci95"],
            stored0_all_resolve=all(e["p_resolves_in_window"] == 1.0 for e in z))
    res["per_reference"] = per_ref
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("report", type=Path, help="results/klt_report_[cell_]<RUN_ID>.json[.gz]")
    a = ap.parse_args(argv)
    stem = a.report.name.removesuffix(".gz").removesuffix(".json")
    kind = "cell" if stem.startswith("klt_report_cell_") else "stage"
    run_id = stem.split("klt_report_cell_" if kind == "cell" else "klt_report_", 1)[1]
    prefix = "mismatch_cell" if kind == "cell" else "mismatch"
    pts_csv = a.report.with_name(f"{prefix}_points_{run_id}.csv")
    sum_json = a.report.with_name(f"{prefix}_summary_{run_id}.json")
    for p in (pts_csv, sum_json):
        if p.exists():
            print(f"refusing to overwrite existing evidence file {p}", file=sys.stderr)
            return 2
    try:
        raw = a.report.read_bytes()
        rep = json.loads(gzip.decompress(raw) if a.report.name.endswith(".gz") else raw)
    except (OSError, ValueError, EOFError) as e:
        print(f"unreadable report {a.report}: {e}: results not produced", file=sys.stderr)
        return 1
    corners = rep.get("corners") or []
    if "error" in rep or not corners or all(c.get("status") != "pass" for c in corners):
        print(f"report has no passing sample (status {rep.get('status')!r}): results not produced", file=sys.stderr)
        return 1
    if not all(c.get("monte_carlo") for c in corners):
        print("report is not a Monte Carlo report: results not produced", file=sys.stderr)
        return 1
    rows = sample_rows(rep, kind)
    with pts_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    by: dict[tuple[str, int], list[dict]] = {}
    for r in rows:
        by.setdefault(_corner_key(r), []).append(r)
    env = rep.get("environment", {})
    remote = env.get("remote", {})
    cs = M.STAGE_CORNERS if kind == "stage" else M.CELL_CORNERS
    order = {k: i for i, k in enumerate(cs)}
    summ = [summarize_stage_corner(v) if kind == "stage" else summarize_cell(v)
            for k, v in sorted(by.items(), key=lambda kv: order.get(kv[0], 99))]
    summary = dict(
        run_id=run_id, study=kind,
        status="PROPOSED_OPERATING_RANGE_NOT_RATIFIED",
        scope=("latch input-referred offset, stage-only, at " if kind == "stage" else
               "end-to-end cell+column+latch at the least-margin corner ")
        + ", ".join(f"{p}/{t}C" for p, t in cs) + ", VDD=1.8 V, sky130 *_mm sections (MC_MM_SWITCH=1)",
        klt_status=rep.get("status"), corner_count=rep.get("corner_count"),
        klt_errored=rep.get("errored"),
        monte_carlo=env.get("monte_carlo"),
        batch_job_id=remote.get("job_id"), batch_instance_type=remote.get("instance_type"),
        netlist_sha256=env.get("netlist_sha256"), models_lib_sha256=env.get("models_lib_sha256"),
        engine_version=env.get("engine_version"),
        assumptions=dict(t_window_s=T_WINDOW_S, resolve_v=RESOLVE_V, c_rbl_f=M.G.C_RBL_F, vrbl_v=M.G.VRBL_V,
                         t_en_after_select_s=M.G.T_EN_S - M.G.T_READ_S, t_stop_s=M.T_STOP_S,
                         error_rate_targets_ASSUMPTION=ERROR_RATE_TARGETS,
                         mismatch_on_all_fets="PDK switch is global per *_mm section: latch, footer/header"
                                              + ("" if kind == "stage" else ", write and read devices") + " all carry Vth mismatch"),
        claims=dict(offset_yield_validated=False, array_level_yield=False, spec_changed=False,
                    supply_tolerance_studied=False, extracted_c_rbl=False,
                    read_device_spread_folded_into_latch_sigma=False),
        corners=summ,
    )
    sum_json.write_text(json.dumps(summary, indent=1) + "\n")
    print(f"wrote {pts_csv.name} and {sum_json.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
