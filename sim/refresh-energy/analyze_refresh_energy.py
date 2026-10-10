#!/usr/bin/env python3
"""Reduce the sim/refresh-energy/ `klt sim` reports to array-boundary refresh energy (issue #115).

Stdlib only. Reads the committed main report ``results/klt_report_<RUN_ID>.json[.gz]`` and the
finer-step convergence repeat ``results/klt_report_fine_<RUN_ID_F>.json[.gz]`` and writes NEW
files next to the main report (never overwrites; refuses if any exists):

* ``refresh_energy_sources_<RUN_ID>.csv``  one row per (corner, instance, boundary source)
* ``refresh_energy_points_<RUN_ID>.csv``   one row per (corner, pattern): active/idle energy,
  incremental energy, restore classification, disturbance, convergence
* ``refresh_energy_scaling_<RUN_ID>.csv``  scoped power scaling (ASSUMPTION: linear in rows)
* ``refresh_energy_summary_<RUN_ID>.json`` maxima, 125 C list, controls, boundary inventory,
  provenance, assumptions, claims flags

What the number is: the IDEAL-DRIVER ARRAY-BOUNDARY ENERGY ESTIMATE of one row refresh of the
extracted 4x4 array -- a partial cost under stated assumptions. It excludes sense-latch /
reference-circuit dissipation, the controller, real driver losses and distribution circuitry.
It is not complete row-refresh energy and not a physical lower bound (ideal sources recover
charge that a real circuit would dissipate).

Conventions (all in README.md):

* Source power p_s(t) = -v_s(t) * i_s(t) in W (v: positive minus negative terminal; SPICE
  current positive INTO the positive terminal). Every boundary source has its negative
  terminal on the common ground node 0, which is not itself a source, so each port is
  counted exactly once. Net E = integral(p), gross = integral(max(p,0)), recovered =
  integral(max(-p,0)); net = gross - recovered is checked, never clipped.
* E_refresh_incremental = E_active_net - E_idle_net (same corner, pattern, window).
* Restore (ASSUMPTIONS from #110): read decision = sign(V(RBL) - VREF) at the sense instant;
  '1' restored if read correct and SN(end) >= 0.95 x SN_ref (same corner, same column, #110
  reference write); '0' restored if read correct and SN(end) <= 50 mV. A point is a
  successful refresh only if all four refreshed cells are restored; failed points keep their
  energies but are excluded from successful-cost maxima and from the scaling.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "sim" / "refresh-overhead"))
import gen_refresh_energy as G  # noqa: E402
import refresh_overhead as RO  # noqa: E402

FRAC_1 = 0.95                  # ASSUMPTION (#110 headline): restored '1' >= FRAC_1 x SN_ref
ZERO_MAX_V = 0.05              # ASSUMPTION (#110): restored '0' <= 50 mV
VREF_V = G.VRBL_V - G.DREF_V   # ASSUMPTION (#110): sense reference = VRBL - 100 mV
CONV_TOL = 0.01                # convergence target: <= 1 % between main and finer-step run
IDENTITY_REL = 1e-3            # net vs gross - recovered consistency (relative to gross)
IDENTITY_ABS_J = 1e-21
DC_CHECK_REL = 2e-3            # DC source: E_net vs -V * Q (independent charge integral)
DC_CHECK_ABS_J = 1e-21
INTERVALS = [  # (label, retention row basis) -- read from the retention CSV, not retyped
    ("ratified_assumed_csn", 0),
    ("extracted_csn_unratified", 1),
]
N_ROWS_GRID = RO.N_ROWS_GRID   # 4 .. 1024 powers of two (refresh-overhead ASSUMPTION grid)
ROW_WIDTH = G.N_COLS           # fixed four-column row (ASSUMPTION)
CELLS_REF_ARRAY = G.N_ROWS * G.N_COLS


# ---------------------------------------------------------------------------
# pure calculation (also used by the analytic controls in the tests)
# ---------------------------------------------------------------------------
def energy_from_trace(t: list[float], v: list[float], i: list[float]) -> dict:
    """Trapezoidal energy of one source from sampled (t, v, i); p = -v * i.

    Gross/recovered split p at its zero crossings (linear interpolation), so they are exact
    for piecewise-linear p. Rejects malformed input (lengths, < 2 points, non-finite values,
    non-strictly-increasing time) with ValueError rather than integrating it.
    """
    if not (len(t) == len(v) == len(i)):
        raise ValueError("t, v and i must have the same length")
    if len(t) < 2:
        raise ValueError("need at least two time points")
    for seq, nm in ((t, "t"), (v, "v"), (i, "i")):
        if any(x is None or not math.isfinite(x) for x in seq):
            raise ValueError(f"missing or non-finite {nm} sample")
    if any(b <= a for a, b in zip(t, t[1:])):
        raise ValueError("time must be strictly increasing")
    p = [-a * b for a, b in zip(v, i)]
    net = gross = rec = 0.0
    for k in range(len(t) - 1):
        t0, t1, p0, p1 = t[k], t[k + 1], p[k], p[k + 1]
        dt = t1 - t0
        net += 0.5 * (p0 + p1) * dt
        if p0 * p1 < 0:
            tc = dt * p0 / (p0 - p1)
            parts = [(p0, tc), (p1, dt - tc)]
            for pp, d in parts:
                if pp > 0:
                    gross += 0.5 * pp * d
                else:
                    rec += -0.5 * pp * d
        else:
            seg = 0.5 * (p0 + p1) * dt
            if seg >= 0:
                gross += seg
            else:
                rec += -seg
    return dict(net=net, gross=gross, rec=rec)


def identity_ok(net: float, gross: float, rec: float) -> bool:
    return abs(net - (gross - rec)) <= IDENTITY_ABS_J + IDENTITY_REL * abs(gross)


def dc_check_ok(net: float, v_dc: float, q: float) -> bool:
    """For a constant-voltage source E = integral(-V i) = -V * Q exactly."""
    return abs(net - (-v_dc * q)) <= DC_CHECK_ABS_J + DC_CHECK_REL * max(abs(net), abs(v_dc * q))


def rel_diff(a: float, b: float) -> float:
    d = max(abs(a), abs(b))
    return 0.0 if d == 0 else abs(a - b) / d


def p_refresh_w(n_rows: int, e_row_incr_j: float, interval_s: float) -> float:
    """P_refresh = N_rows * E_row_incremental / refresh_interval  (J / s = W)."""
    return n_rows * e_row_incr_j / interval_s


def duty_factor(n_rows: int, t_row_s: float, interval_s: float) -> float:
    """Fraction of the interval spent refreshing (rows refreshed back to back, one at a time)."""
    return n_rows * t_row_s / interval_s


# ---------------------------------------------------------------------------
# isolation check of the generated deck
# ---------------------------------------------------------------------------
def check_isolation(netlist_text: str) -> list[str]:
    """Every element's nodes must belong to ONE instance (suffix) or be ground '0'.

    Returns a list of offending element lines (empty when isolated). A source or device
    bridging two instances would let one instance's current contaminate another's.
    """
    suffixes = sorted((i["name"] for i in G.instances()), key=len, reverse=True)
    bad = []
    for ln in netlist_text.splitlines():
        s = ln.split("$")[0].strip()
        if not s or s.startswith(("*", ".", "+")):
            continue
        tok = s.split()
        name = tok[0].lower()
        nnodes = {"x": 4, "v": 2, "b": 2, "c": 2, "r": 2, "s": 4}.get(name[0])
        if nnodes is None:
            bad.append(ln)
            continue
        owner = next((x for x in suffixes if name.endswith("_" + x)), None)
        for node in tok[1:1 + nnodes]:
            if node == "0":
                continue
            nsuf = next((x for x in suffixes if node.endswith("_" + x)), None)
            if owner is None or nsuf != owner:
                bad.append(ln)
                break
    return bad


# ---------------------------------------------------------------------------
# report reduction
# ---------------------------------------------------------------------------
def load_report(path: Path) -> dict:
    opener = gzip.open if path.name.endswith(".gz") else open
    with opener(path, "rt") as fh:
        return json.load(fh)


def run_id_of(path: Path) -> str:
    n = path.name
    n = n[:-len(".json.gz")] if n.endswith(".json.gz") else n[:-len(".json")]
    return n.split("klt_report_", 1)[1]


def corner_meas(corner: dict) -> dict:
    return {m["name"]: m.get("value") for m in corner["measurements"]}


def need(m: dict, name: str) -> float:
    v = m.get(name)
    if v is None or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError(f"required measurement {name!r} missing or non-finite")
    return float(v)


def source_energies(m: dict, inst: dict) -> list[dict]:
    """Per-source energies of one instance; raises if any required channel is missing."""
    rows = []
    for stem, role, idx in G.source_roles():
        s = G.src_name(stem, inst["name"])
        net, gross, rec, q = (need(m, f"{k}_{s}") for k in ("en", "eg", "er", "q"))
        dc = G.is_dc(inst, stem)
        vdc = G.dc_value(inst, stem) if dc else None
        rows.append(dict(source=s, stem=stem, role=role, index="" if idx is None else idx,
                         waveform="dc" if dc else "pwl", v_dc="" if vdc is None else vdc,
                         e_net_J=net, e_gross_J=gross, e_rec_J=rec, q_C=q,
                         identity_ok=identity_ok(net, gross, rec),
                         dc_check_ok=(dc_check_ok(net, vdc, q) if dc else "")))
    return rows


def totals(rows: list[dict]) -> dict:
    return dict(net=sum(r["e_net_J"] for r in rows), gross=sum(r["e_gross_J"] for r in rows),
                rec=sum(r["e_rec_J"] for r in rows))


def classify_cells(m: dict, inst_name: str, pattern: str, sn_ref: list[float]) -> list[dict]:
    out = []
    for c in range(G.N_COLS):
        b = G.PATTERNS[pattern][G.SEL_ROW][c]
        rbs = need(m, f"rbs_{inst_name}_{c}")
        end = need(m, f"snb_{inst_name}_{G.SEL_ROW}{c}")
        start = need(m, f"sna_{inst_name}_{G.SEL_ROW}{c}")
        rd = need(m, f"snr_{inst_name}_{c}")
        margin = (VREF_V - rbs) if b == 1 else (rbs - VREF_V)
        read_ok = margin > 0
        if b == 1:
            restored = read_ok and end >= FRAC_1 * sn_ref[c]
        else:
            restored = read_ok and end <= ZERO_MAX_V
        out.append(dict(col=c, bit=b, v_rbl_sense=rbs, read_margin_v=margin, read_ok=read_ok,
                        sn_start=start, sn_pre_write=rd, sn_end=end, sn_ref=sn_ref[c],
                        restore_ratio=(end / sn_ref[c]) if b == 1 else None, restored=restored))
    return out


def sn_stored_delta_j(m: dict, inst_name: str, c_sn_f: float) -> float:
    """Approximate change of storage-node electrostatic energy over the window,
    sum 1/2 C_SN (V_end^2 - V_start^2) over all 16 cells (linear C_SN ASSUMPTION)."""
    tot = 0.0
    for r in range(G.N_ROWS):
        for c in range(G.N_COLS):
            a = need(m, f"sna_{inst_name}_{r}{c}")
            b = need(m, f"snb_{inst_name}_{r}{c}")
            tot += 0.5 * c_sn_f * (b * b - a * a)
    return tot


def reduce_corner(corner: dict, c_sn_f: float) -> tuple[list[dict], list[dict], dict]:
    m = corner_meas(corner)
    proc, temp = corner["process"], corner["temperature_c"]
    sn_ref = [need(m, f"snref_{c}") for c in range(G.N_COLS)]
    insts = {i["name"]: i for i in G.instances()}
    src_rows, energy = [], {}
    for inst in insts.values():
        if not inst["energy"]:
            continue
        rows = source_energies(m, inst)
        for r in rows:
            src_rows.append(dict(process=proc, temp_c=temp, instance=inst["name"], mode=inst["mode"],
                                 pattern=inst["pattern"], **r))
        energy[inst["name"]] = dict(rows=rows, tot=totals(rows))
    dur = G.T_END_S - G.T_START_S
    pts = []
    for pat, code in G.PAT_CODE.items():
        act, idl = f"act_{code}", f"idl_{code}"
        ea, ei = energy[act]["tot"], energy[idl]["tot"]
        cells = classify_cells(m, act, pat, sn_ref)
        dist_vs_idle = max(abs(need(m, f"snb_{act}_{r}{c}") - need(m, f"snb_{idl}_{r}{c}"))
                           for r in range(G.N_ROWS) if r != G.SEL_ROW for c in range(G.N_COLS))
        dist_vs_start = max(abs(need(m, f"snb_{act}_{r}{c}") - need(m, f"sna_{act}_{r}{c}"))
                            for r in range(G.N_ROWS) if r != G.SEL_ROW for c in range(G.N_COLS))
        ok = all(x["restored"] for x in cells)
        reasons = [f"col{x['col']}:{'read' if not x['read_ok'] else 'restore'}" for x in cells if not x["restored"]]
        pts.append(dict(
            process=proc, temp_c=temp, pattern=pat, row0_bits="".join(str(x["bit"]) for x in cells),
            t_start_s=G.T_START_S, t_end_s=G.T_END_S, duration_s=dur,
            e_active_net_J=ea["net"], e_active_gross_J=ea["gross"], e_active_rec_J=ea["rec"],
            e_idle_net_J=ei["net"], e_idle_gross_J=ei["gross"], e_idle_rec_J=ei["rec"],
            e_row_incr_J=ea["net"] - ei["net"],
            p_idle_net_W=ei["net"] / dur, p_idle_gross_W=ei["gross"] / dur,
            identity_ok=all(r["identity_ok"] for r in energy[act]["rows"] + energy[idl]["rows"]),
            dc_check_ok=all(r["dc_check_ok"] is not False for r in energy[act]["rows"] + energy[idl]["rows"]),
            status="restored" if ok else "FAILED",
            fail_reasons=";".join(reasons),
            min_read_margin_v=min(x["read_margin_v"] for x in cells),
            min_restore_ratio_1=min((x["restore_ratio"] for x in cells if x["bit"] == 1), default=None),
            max_sn_end_0_v=max((x["sn_end"] for x in cells if x["bit"] == 0), default=None),
            sn_end_row0="|".join(f"{x['sn_end']:.6g}" for x in cells),
            sn_ref_row0="|".join(f"{x:.6g}" for x in sn_ref),
            unselected_max_dv_vs_idle_v=dist_vs_idle,
            unselected_max_dv_vs_start_v=dist_vs_start,
            sn_stored_delta_active_J=sn_stored_delta_j(m, act, c_sn_f),
            sn_stored_delta_idle_J=sn_stored_delta_j(m, idl, c_sn_f),
        ))
    nop = f"nop_{G.PAT_CODE[G.NOP_PATTERN]}"
    idl_n = f"idl_{G.PAT_CODE[G.NOP_PATTERN]}"
    act_n = f"act_{G.PAT_CODE[G.NOP_PATTERN]}"
    nop_cells = classify_cells(m, nop, G.NOP_PATTERN, sn_ref)
    controls = dict(
        process=proc, temp_c=temp,
        nop_minus_idle_net_J=energy[nop]["tot"]["net"] - energy[idl_n]["tot"]["net"],
        nop_minus_idle_rel_to_active=(abs(energy[nop]["tot"]["net"] - energy[idl_n]["tot"]["net"])
                                      / abs(energy[act_n]["tot"]["net"])) if energy[act_n]["tot"]["net"] else None,
        nop_flagged_unrestored=not all(x["restored"] for x in nop_cells),
        identity_all=all(r["identity_ok"] for v in energy.values() for r in v["rows"]),
        dc_check_all=all(r["dc_check_ok"] is not False for v in energy.values() for r in v["rows"]),
        sn_ref=sn_ref,
    )
    return src_rows, pts, controls


def reduce_report(rep: dict, c_sn_f: float) -> tuple[list[dict], list[dict], list[dict]]:
    if rep.get("errored"):
        raise ValueError(f"{rep.get('errored')} errored corners in report")
    src, pts, ctl = [], [], []
    for c in rep["corners"]:
        if c.get("status") == "error":
            raise ValueError(f"corner {c.get('corner_id')} errored")
        s, p, k = reduce_corner(c, c_sn_f)
        src += s
        pts += p
        ctl.append(k)
    return src, pts, ctl


def add_convergence(pts: list[dict], fine_pts: list[dict]) -> None:
    fine = {(p["process"], p["temp_c"], p["pattern"]): p for p in fine_pts}
    for p in pts:
        f = fine.get((p["process"], p["temp_c"], p["pattern"]))
        if f is None:
            raise ValueError(f"fine run lacks point {p['process']}/{p['temp_c']}/{p['pattern']}")
        for k in ("e_active_net_J", "e_idle_net_J", "e_row_incr_J"):
            p[k.replace("_J", "_fine_J")] = f[k]
            p[k.replace("_J", "_conv_rel")] = rel_diff(p[k], f[k])
        p["status_fine"] = f["status"]
        p["converged_1pct"] = (p["e_row_incr_conv_rel"] <= CONV_TOL and p["e_active_net_conv_rel"] <= CONV_TOL
                               and p["status"] == f["status"])
        p["idle_converged_1pct"] = p["e_idle_net_conv_rel"] <= CONV_TOL


# ---------------------------------------------------------------------------
# maxima and scaling
# ---------------------------------------------------------------------------
def argmax(pts: list[dict], key: str) -> dict | None:
    return max(pts, key=lambda p: p[key]) if pts else None


def maxima(pts: list[dict]) -> dict:
    ok = [p for p in pts if p["status"] == "restored"]
    out = {}
    for key in ("e_row_incr_J", "e_active_net_J", "e_active_gross_J", "p_idle_net_W", "p_idle_gross_W"):
        pool = pts if key.startswith("p_idle") else ok
        b = argmax(pool, key)
        out[key] = None if b is None else dict(value=b[key], process=b["process"], temp_c=b["temp_c"],
                                                pattern=b["pattern"])
    hot = [p for p in ok if p["temp_c"] == max(G.TEMPS_C)]
    bh = argmax(hot, "e_row_incr_J")
    out["max_e_row_incr_is_at_hottest_temp"] = (out["e_row_incr_J"] is not None
                                               and out["e_row_incr_J"]["temp_c"] == max(G.TEMPS_C))
    out["hottest_temp_max_e_row_incr"] = None if bh is None else dict(
        value=bh["e_row_incr_J"], process=bh["process"], temp_c=bh["temp_c"], pattern=bh["pattern"])
    return out


def intervals() -> list[dict]:
    rows = RO.load_worst_case_retention()
    out = []
    for label, k in INTERVALS:
        r = rows[k]
        t_ret = float(r["retention_time_s"])
        out.append(dict(label=label, interval_s=t_ret / RO.SAFETY_MARGIN_ASSUMPTION,
                        retention_row_timestamp_utc=r["timestamp_utc"], retention_time_s=t_ret,
                        c_sn_ff=float(r["c_storage_node_ff_ASSUMPTION"]), c_sn_basis=RO.c_sn_basis(r),
                        leakage_ileak_a=float(r["leakage_ileak_a"]),
                        delta_v_v=float(r["delta_v_sense_margin_v_ASSUMPTION"]),
                        safety_margin=RO.SAFETY_MARGIN_ASSUMPTION))
    return out


def scaling_rows(pts: list[dict], ivs: list[dict]) -> list[dict]:
    ok = [p for p in pts if p["status"] == "restored"]
    t_row = G.t_row_refresh_op_s()
    bases = []
    if ok:
        be, bi = argmax(ok, "e_row_incr_J"), argmax(pts, "p_idle_net_W")
        bases.append(("envelope_grid_max", "grid", "", "", be["e_row_incr_J"], bi["p_idle_net_W"],
                      f"E from {be['process']}/{be['temp_c']}C/{be['pattern']}; idle from "
                      f"{bi['process']}/{bi['temp_c']}C/{bi['pattern']} (envelope; may be different points)"))
    for proc in G.PROCESS_CORNERS:
        for t in G.TEMPS_C:
            cp = [p for p in ok if p["process"] == proc and p["temp_c"] == t]
            ci = [p for p in pts if p["process"] == proc and p["temp_c"] == t]
            if not cp:
                continue
            be, bi = argmax(cp, "e_row_incr_J"), argmax(ci, "p_idle_net_W")
            bases.append(("corner_worst_pattern", proc, t, be["pattern"], be["e_row_incr_J"], bi["p_idle_net_W"],
                          f"idle pattern {bi['pattern']}"))
    out = []
    for basis, proc, t, pat, e_row, p_idle16, note in bases:
        p_idle_row = p_idle16 / G.N_ROWS          # ASSUMPTION: idle power linear in rows
        for iv in ivs:
            for n in N_ROWS_GRID:
                duty = duty_factor(n, t_row, iv["interval_s"])
                pr = p_refresh_w(n, e_row, iv["interval_s"])
                pi = n * p_idle_row
                out.append(dict(
                    basis=basis, process=proc, temp_c=t, pattern=pat, interval_label=iv["label"],
                    interval_s=iv["interval_s"], n_rows_ASSUMPTION=n, row_width_cols=ROW_WIDTH,
                    n_cells=n * ROW_WIDTH, e_row_incr_J=e_row, t_row_refresh_op_s=t_row,
                    p_refresh_W=pr, p_idle_W=pi, p_total_W=pr + pi, duty_factor=duty,
                    schedule_feasible=duty < 1.0,
                    notes=("INFEASIBLE: refresh operations would overlap (duty >= 1); not a feasible schedule. "
                           if duty >= 1.0 else "") + note +
                          "; LINEAR SCALING ASSUMPTION (height-dependent bitline loading ignored); not macro power"))
    return out


# ---------------------------------------------------------------------------
# provenance
# ---------------------------------------------------------------------------
def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def boundary_inventory() -> dict:
    srcs = []
    for stem, role, idx in G.source_roles():
        srcs.append(dict(source_stem=stem, role=role, index=idx,
                         positive_node=G.src_pos_node(stem, "<inst>"), negative_node="0",
                         waveform={m: ("dc %g" % G.dc_value(dict(mode=m, pattern="one", name="x"), stem)
                                       if G.is_dc(dict(mode=m, pattern="one", name="x"), stem) else "pwl")
                                   for m in ("active", "idle")}))
    return dict(
        measured_sources_per_instance=srcs,
        excluded_sources=[dict(source_stem=s, reason=r) for s, r in G.EXCLUDED_SOURCES],
        return_path=("every boundary source's negative terminal is ground node 0; node 0 is not a source; "
                     "array GND (body) and vsubs (substrate) return through their own 0 V sources, which "
                     "exchange no energy (p = -0 * i) but whose charge is reported; each port is counted once"),
        sign_convention="p_s = -v_s * i_s (W); SPICE i positive into the positive terminal; positive = delivered to the array",
        not_in_boundary=["sense latch / reference circuit", "controller", "real driver losses",
                         "distribution circuitry", "precharge switch control"],
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("report", type=Path, help="results/klt_report_<RUN_ID>.json[.gz] (main, TMAX 20 ps)")
    ap.add_argument("fine", type=Path, help="results/klt_report_fine_<RUN_ID_F>.json[.gz] (TMAX 5 ps)")
    a = ap.parse_args(argv)
    run_id = run_id_of(a.report)
    outs = {k: a.report.with_name(f"refresh_energy_{k}_{run_id}.{ext}")
            for k, ext in (("sources", "csv"), ("points", "csv"), ("scaling", "csv"), ("summary", "json"))}
    for p in outs.values():
        if p.exists():
            print(f"refusing to overwrite existing evidence file {p}", file=sys.stderr)
            return 2
    rep, rep_f = load_report(a.report), load_report(a.fine)
    c_sn_ff, c_sn_prov = G.G.S.load_extracted_c_sn(G.G.S.EXTRACT_JSON, "sn")
    src, pts, ctl = reduce_report(rep, c_sn_ff * 1e-15)
    _src_f, pts_f, ctl_f = reduce_report(rep_f, c_sn_ff * 1e-15)
    add_convergence(pts, pts_f)
    ivs = intervals()
    scal = scaling_rows(pts, ivs)
    for key, rows in (("sources", src), ("points", pts), ("scaling", scal)):
        with outs[key].open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    env, env_f = rep["environment"], rep_f["environment"]
    hot = max(G.TEMPS_C)
    summary = dict(
        run_id=run_id, fine_run_id=run_id_of(a.fine),
        what=("IDEAL-DRIVER ARRAY-BOUNDARY ENERGY ESTIMATE of one row refresh (partial cost under stated "
              "assumptions); NOT complete row-refresh energy, NOT a physical lower bound, NOT macro power, "
              "NOT an SRAM comparison"),
        status="PROPOSED_OPERATING_RANGE_NOT_RATIFIED",
        scope="27 C and 125 C, tt/ss/ff/sf/fs global corners, VDD=1.8 V, per spec/operating-range-decision-PROPOSED.md",
        window=dict(t_start_s=G.T_START_S, t_end_s=G.T_END_S, duration_s=G.T_END_S - G.T_START_S,
                    phases_s={k: v for k, v in G.T.items()},
                    integration=".meas tran INTEG (trapezoidal over accepted time points), method=trap",
                    tran_max_step_s=G.TRAN_MAX_S, tran_max_step_fine_s=G.TRAN_MAX_FINE_S),
        t_row_refresh_op_s=G.t_row_refresh_op_s(),
        klt=dict(main=dict(status=rep["status"], corner_count=rep["corner_count"],
                           klt_version=rep.get("provenance", {}).get("klt_version"),
                           batch_job_id=env.get("remote", {}).get("job_id"),
                           batch_instance_type=env.get("remote", {}).get("instance_type"),
                           netlist_sha256=env.get("netlist_sha256"), models_lib_sha256=env.get("models_lib_sha256"),
                           engine_version=env.get("engine_version")),
                 fine=dict(status=rep_f["status"], corner_count=rep_f["corner_count"],
                           klt_version=rep_f.get("provenance", {}).get("klt_version"),
                           batch_job_id=env_f.get("remote", {}).get("job_id"),
                           batch_instance_type=env_f.get("remote", {}).get("instance_type"),
                           netlist_sha256=env_f.get("netlist_sha256"), models_lib_sha256=env_f.get("models_lib_sha256"),
                           engine_version=env_f.get("engine_version"))),
        input_hashes={str(p.relative_to(REPO)): sha256_file(p) for p in (
            G.ARRAY_NETLIST, G.NETLIST_PATH, G.REQUEST_PATH, G.REQUEST_FINE_PATH, HERE / "gen_refresh_energy.py",
            HERE / "analyze_refresh_energy.py", REPO / "sim" / "refresh-op" / "gen_refresh_op.py",
            RO.RETENTION_CSV)},
        boundary=boundary_inventory(),
        adaptations=G.ADAPTATIONS,
        patterns={k: v for k, v in G.PATTERNS.items()},
        evidence_chain=dict(
            leakage_to_retention_to_interval=ivs,
            c_sn_used_for_stored_energy_disclosure_ff=c_sn_ff, c_sn_provenance=c_sn_prov,
            note=("leakage (sim/leakage) -> C_SN (ASSUMED margin factor, ratified; or layout-extracted, unratified) "
                  "-> retention (sim/retention) -> interval = t_ret / 2 (ASSUMED margin) -> P_refresh = "
                  "N_rows * E_row_incr / interval")),
        maxima_all_points=maxima(pts),
        results_125C=[{k: p[k] for k in ("process", "pattern", "status", "e_row_incr_J", "e_active_net_J",
                                         "e_idle_net_J", "p_idle_net_W", "converged_1pct")}
                      for p in pts if p["temp_c"] == hot],
        failed_points=[{k: p[k] for k in ("process", "temp_c", "pattern", "fail_reasons", "e_row_incr_J",
                                          "min_read_margin_v", "min_restore_ratio_1", "max_sn_end_0_v")}
                       for p in pts if p["status"] != "restored"],
        negative_incremental_points=[{k: p[k] for k in ("process", "temp_c", "pattern", "e_row_incr_J")}
                                     for p in pts if p["e_row_incr_J"] < 0],
        controls=dict(
            per_corner=ctl, per_corner_fine=ctl_f,
            nop_flagged_unrestored_all=all(k["nop_flagged_unrestored"] for k in ctl),
            identity_all=all(k["identity_all"] for k in ctl + ctl_f),
            dc_charge_check_all=all(k["dc_check_all"] for k in ctl + ctl_f),
            max_nop_minus_idle_rel_to_active=max(k["nop_minus_idle_rel_to_active"] or 0.0 for k in ctl),
        ),
        convergence=dict(
            target_rel=CONV_TOL,
            all_points_converged=all(p["converged_1pct"] for p in pts),
            idle_all_converged=all(p["idle_converged_1pct"] for p in pts),
            max_rel_e_row_incr=max(p["e_row_incr_conv_rel"] for p in pts),
            max_rel_e_active_net=max(p["e_active_net_conv_rel"] for p in pts),
            max_rel_e_idle_net=max(p["e_idle_net_conv_rel"] for p in pts),
            restore_status_agrees=all(p["status"] == p["status_fine"] for p in pts)),
        scaling=dict(
            formula="P_total = N_rows * E_row_incr / refresh_interval + N_rows * (P_idle_16 / 4)",
            n_rows_grid_ASSUMPTION=N_ROWS_GRID, row_width_cols=ROW_WIDTH,
            infeasible_configurations=sorted({(r["interval_label"], r["n_rows_ASSUMPTION"])
                                              for r in scal if not r["schedule_feasible"]}),
            reference_array_16_cells={iv["label"]: dict(
                p_refresh_W=(p_refresh_w(G.N_ROWS, maxima(pts)["e_row_incr_J"]["value"], iv["interval_s"])
                             if maxima(pts)["e_row_incr_J"] else None),
                p_idle_W=maxima(pts)["p_idle_net_W"]["value"]) for iv in ivs},
            note="linear ASSUMPTION; height-dependent loading ignored; not simulated geometry; not macro power"),
        assumptions=dict(frac_1=FRAC_1, zero_max_v=ZERO_MAX_V, vref_v=VREF_V, v_sn1_v=G.V_SN1_V, v_sn0_v=G.V_SN0_V,
                         wbl_idle_v=G.WBL_IDLE_V, sense_s=G.SENSE_S, wb_s=G.WB_S, ref_wb_s=G.REF_WB_S,
                         t_init_s=G.T_INIT_S, r_pre_sw_ohm=G.R_PRE_SW, sim_options=G.SIM_OPTIONS,
                         conv_tol=CONV_TOL, identity_rel=IDENTITY_REL, dc_check_rel=DC_CHECK_REL),
        claims=dict(complete_row_refresh_energy=False, physical_lower_bound=False, macro_power=False,
                    sram_comparison=False, statistical_yield=False, spec_changed=False,
                    larger_array_geometry_simulated=False),
    )
    outs["summary"].write_text(json.dumps(summary, indent=1) + "\n")
    print("wrote " + ", ".join(p.name for p in outs.values()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
