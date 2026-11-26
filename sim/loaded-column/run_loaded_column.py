#!/usr/bin/env python3
"""Loaded four-row 2T gain-cell column campaign (issue #45, Epic #24 phase 2).

Characterizes -- it does NOT implement a sense amplifier -- the stored levels
and the loaded-read-bitline response of one 4-row column of the ratified 2T
bitcell, across the 15-point corner/temperature grid (5 MOS corners x
-40/27/125 C), for every selected row x all 2^3 patterns of the other three
rows x both stored values, at two read ages (fresh, and the ~5.03 us
refresh-interval bound from spec/retention-refresh-budget.md section 7).

Connectivity: layout/array_topology.py build_topology(4, 1).
Device cards:  parsed from design/gain_cell_2t.spice (not restated).
Models:        only the shipped sky130 combined ngspice library.

Usage:
    python3 sim/loaded-column/run_loaded_column.py --check-env
    python3 sim/loaded-column/run_loaded_column.py --dry-run --corners tt --temps-c 27 --rows 0 --patterns 0
    python3 sim/loaded-column/run_loaded_column.py            # full campaign
    python3 sim/loaded-column/run_loaded_column.py --corners sf --temps-c 125 --jobs 4

Results are APPENDED to results/loaded_column_results.csv (never rewritten;
CLAUDE.md "sim/ results are append-only evidence"). One row per simulation
point, including points that failed to simulate (status != ok, with reason).

SIGN CONVENTIONS (declared; also in README.md)
  i_into_rbl_r_*  : current flowing from rwl_r THROUGH M_RD_r INTO rbl_0.
                    Positive charges the read bitline, negative discharges it.
                    Computed as -i(vrwl_r) (ngspice reports the branch current
                    into the + terminal; a source delivering current reads
                    negative).
  v_rbl_*         : volts on rbl_0 (floating on C_RBL after precharge release).
  separation      : V_sep = V(rbl | stored 0) - V(rbl | stored 1) at the
                    declared sense instant. Positive = the '1' discharged the
                    bitline further than the '0' (the expected polarity).
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime
import itertools
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM_DIR = HERE.parent
REPO_ROOT = SIM_DIR.parent
sys.path.insert(0, str(SIM_DIR))
sys.path.insert(0, str(REPO_ROOT / "layout"))
from _evidence_common import (  # noqa: E402
    DEFAULT_PDK_VARIANT,
    PDK_OPEN_PDKS_COMMIT,
    VDD_V as VDD,
    append_result,
    check_ngspice_available,
    first_below,
    interp_at,
    read_wrdata,
    ngspice_version,
    repo_git_sha,
    resolve_ngspice_lib,
    resolve_pdk_root,
    spice_number,
)

sys.path.insert(0, str(SIM_DIR / "retention"))
from derive_retention import load_extracted_c_sn  # noqa: E402
from array_topology import build_topology  # noqa: E402

TEMPLATE = HERE / "tb_loaded_column.spice.tmpl"
RESULTS_CSV = HERE / "results" / "loaded_column_results.csv"
DESIGN_NETLIST = REPO_ROOT / "design" / "gain_cell_2t.spice"
EXTRACT_JSON = REPO_ROOT / "layout" / "gain_cell_2t.extract.parasitics.json"

N_ROWS, N_COLS = 4, 1
CORNERS = ["tt", "ss", "ff", "sf", "fs"]
TEMPS_C = [-40, 27, 125]
AGE_LABELS = ["fresh", "refresh_bound"]
MIN_TIMEPOINTS = 10  # fewer wrdata rows than this => sim failed

# ASSUMPTIONS (proposed engineering choices, NOT ratified spec values)
C_RBL_F = 10e-15  # declared schematic-level read-bitline load
T_SENSE_S = 10e-9  # sense instant after rwl-select fall begins
DV_LATENCY_V = 0.1  # droop on rbl_0 that defines "latency"
# Ratified bound (spec/retention-refresh-budget.md s7): t_ret 1.005989e-05 s / 2
T_REFRESH_S = 5.029945e-06
FRESH_T_READ_S = 110e-9

FIELDS = (
    [
        "run_id", "timestamp_utc", "repo_git_sha", "pdk_open_pdks_commit", "ngspice_version",
        "corner", "temp_c", "age_label", "sel_row", "stored_value", "pattern_rows3210",
        "other_rows_pattern", "status", "reason",
        "c_sn_ff", "c_rbl_ff_ASSUMPTION", "vdd_v", "vrbl_precharge_v", "t_read_s",
        "t_sense_s_ASSUMPTION", "dv_latency_v_ASSUMPTION", "sel_row_age_at_read_s",
        "max_row_age_at_read_s",
    ]
    + [f"v_sn_r{r}_wl_off_v" for r in range(N_ROWS)]
    + [f"v_sn_r{r}_after_write_v" for r in range(N_ROWS)]
    + [f"v_sn_r{r}_preread_v" for r in range(N_ROWS)]
    + ["v_rbl_preread_float_v"]
    + [f"i_into_rbl_r{r}_preread_a" for r in range(N_ROWS)]
    + ["i_desel_sum_preread_a"]
    + [f"i_into_rbl_r{r}_sense_a" for r in range(N_ROWS)]
    + [
        "i_desel_sum_sense_a", "v_rbl_sense_v", "v_rbl_end_v", "dv_rbl_sense_v",
        "latency_s", "latency_reason", "dv_sn_sel_read_disturb_v",
        "dv_sn_unsel_worst_signed_v", "notes",
    ]
)


def parse_params(tmpl: str) -> dict[str, float]:
    out = {}
    for m in re.finditer(r"^\.param\s+(\w+)\s*=\s*([^\s@{]+)\s*$", tmpl, re.M):
        try:
            out[m.group(1)] = spice_number(m.group(2))
        except ValueError:
            pass
    return out


def parse_design_devices() -> dict[str, tuple[str, str]]:
    """{'M_WR': (model, trailing params), 'M_RD': ...} parsed from the
    committed bitcell netlist (continuation lines joined)."""
    text = re.sub(r"\n\+", " ", DESIGN_NETLIST.read_text())
    devs = {}
    for line in text.splitlines():
        m = re.match(r"^X(M_WR|M_RD)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(.*)$", line)
        if m:
            devs[m.group(1)] = (m.group(6), m.group(7).strip())
    if set(devs) != {"M_WR", "M_RD"}:
        raise RuntimeError("could not parse M_WR/M_RD from design/gain_cell_2t.spice")
    return devs


def build_cells(wr_card: str | None = None, rd_card: str | None = None) -> str:
    """Cell instances from array_topology + committed device cards. Node
    order (design/gain_cell_2t.spice): M_WR sn wl bl GND; M_RD rbl sn rwl GND.
    `wr_card` / `rd_card` replace the design's own cards (the cold-corner
    runner passes a re-sized or re-flavoured one)."""
    topo = build_topology(N_ROWS, N_COLS)
    devs = parse_design_devices()
    wm, wp = devs["M_WR"]
    rm, rp = devs["M_RD"]
    wr = f"{wm} {wp}" if wr_card is None else wr_card
    rd = f"{rm} {rp}" if rd_card is None else rd_card
    lines = []
    for d in topo["devices"]:
        lines.append(f"X{d['wr_name']} {d['sn']} {d['wl']} {d['bl']} GND {wr}")
        lines.append(f"X{d['rd_name']} {d['rbl']} {d['sn']} {d['rwl']} GND {rd}")
    return "\n".join(lines)


def read_time(P: dict[str, float], age: str) -> float:
    if age == "fresh":
        return FRESH_T_READ_S
    # row 0 (written first) reaches exactly the refresh bound; later rows are younger
    return P["TW0"] + P["TWPULSE"] + T_REFRESH_S


def case_tstop(P: dict[str, float], t_read: float) -> float:
    """Planned .tran stop time of one case."""
    return t_read + P["TREAD_PULSE"] + P["TTAIL"]


def check_complete(t: list[float], tstop: float) -> None:
    """Reject a case whose waveform ends before its planned stop time (an
    aborted or truncated tran must never be recorded as status ok)."""
    tol = 1e-6 * tstop
    if t[-1] < tstop - tol:
        raise RuntimeError(
            f"incomplete transient: last timepoint {t[-1]:.6e} s < planned tstop {tstop:.6e} s"
        )


def wl_pulse(r: int, vwl: str) -> str:
    """Write-wordline source of row r: one pulse to the `vwl` expression at
    TW0 + r*TWSTEP, so rows are written 0..3 sequentially."""
    return (f"vwl_{r} wl_{r} 0 pulse(0 {vwl} {{TW0+{r}*TWSTEP}} {{TEDGE}} {{TEDGE}} "
            f"{{TWPULSE-TEDGE}} 1)")


def bl_pwl(levels: list[str]) -> str:
    """Write-bitline PWL of one column: row r's level `levels[r]` (a template
    expression) is held for row r's write pulse and returns to 0 TBL_LAG after
    the wordline is fully low."""
    pts = ["0 0"]
    for r in range(N_ROWS):
        on, off = f"TW0+{r}*TWSTEP", f"TW0+{r}*TWSTEP+TWPULSE"
        pts += [
            f"{{{on}-TEDGE}} 0", f"{{{on}}} {{{levels[r]}}}",
            f"{{{off}+TBL_LAG}} {{{levels[r]}}}", f"{{{off}+TBL_LAG+TEDGE}} 0",
        ]
    return "pwl(" + " ".join(pts) + ")"


def render(tmpl, lib, corner, temp, cases, c_sn_f, outdir, tmax, P):
    """Phase 2 deck: the design's own device cards, VDD write wordlines and
    every storage node starting at the opposite of its data."""
    return render_deck(
        tmpl, lib, corner, temp, cases, c_sn_f, outdir, tmax, P,
        cells_body=build_cells(), vwl="{VDD}",
        rwl_levels=[f"{{VDD*(1-SL{r})}}" for r in range(N_ROWS)],
        ic_levels=[f"{{VDD*(1-B{r})}}" for r in range(N_ROWS)],
        subs={"@@C_RBL@@": f"{C_RBL_F:.6e}"},
    )


def render_deck(tmpl, lib, corner, temp, cases, c_sn_f, outdir, tmax, P, *,
                cells_body: str, vwl: str, rwl_levels: list[str], ic_levels: list[str],
                subs: dict | None = None) -> str:
    """The deck both loaded-column runners render (Phase 2: render();
    cold-corner: run_variants.render()), i.e. one deck per (corner, temp,
    batch): the .lib parse dominates ngspice runtime, so the batch's cases
    (pattern, sel, t_read) run in ONE process, re-parameterized with
    alterparam + reset between cases.

    `cells_body` is the cell block (build_cells); `vwl` the expression the
    write wordlines pulse to; `rwl_levels[r]` the expression on rwl_r while
    its row is selected and `ic_levels[r]` the one sn_r_0 starts from. `subs`
    are the runner's own @@TOKEN@@ values, applied before the shared ones."""
    cells = (
        cells_body
        + "\n* extracted per-cell storage-node capacitance (lumped)\n"
        + "\n".join(f"c_sn_{r} sn_{r}_0 0 {c_sn_f:.6e}" for r in range(N_ROWS))
    )
    ws = [wl_pulse(r, vwl) for r in range(N_ROWS)]
    ws.append("vbl bl_0 0 " + bl_pwl([f"VDD*B{r}" for r in range(N_ROWS)]))
    rs = [
        f"vrwl_{r} rwl_{r} 0 pwl(0 {{VDD}} {{T_READ}} {{VDD}} {{T_READ+TEDGE}} {rwl_levels[r]} "
        f"{{T_READ+TREAD_PULSE}} {rwl_levels[r]} {{T_READ+TREAD_PULSE+TEDGE}} {{VDD}})"
        for r in range(N_ROWS)
    ]
    ics = ".ic " + " ".join(f"v(sn_{r}_0)={ic_levels[r]}" for r in range(N_ROWS))
    ctl = []
    for k, (pattern, sel, t_read) in enumerate(cases):
        for r in range(N_ROWS):
            ctl.append(f"alterparam B{r} = {(pattern >> r) & 1}")
            ctl.append(f"alterparam SL{r} = {1 if r == sel else 0}")
        ctl.append(f"alterparam T_READ = {t_read:.9e}")
        ctl.append("reset")
        # Drop every earlier plot: if this case's tran aborts, wrdata then has
        # no current plot and writes no file (-> sim_failed), instead of
        # silently re-writing the previous case's data.
        ctl.append("destroy all")
        ctl.append(f"tran 10p {case_tstop(P, t_read):.9e} 0 {tmax:.3e}")
        ctl.append(
            f"wrdata {outdir}/case{k}.dat v(sn_0_0) v(sn_1_0) v(sn_2_0) v(sn_3_0) v(rbl_0) "
            "i(vrwl_0) i(vrwl_1) i(vrwl_2) i(vrwl_3)"
        )
    subs = dict(subs or {})
    subs.update({
        "@@PDK_NGSPICE_LIB@@": str(lib), "@@CORNER@@": corner, "@@TEMP_C@@": str(temp),
        "@@CELLS@@": cells, "@@WRITE_SOURCES@@": "\n".join(ws),
        "@@RWL_SOURCES@@": "\n".join(rs), "@@ICS@@": ics, "@@CASES@@": "\n".join(ctl),
    })
    for key, val in subs.items():
        tmpl = tmpl.replace(key, val)
    left = re.findall(r"@@[A-Z_0-9]+@@", tmpl)
    if left:
        raise RuntimeError(f"unsubstituted tokens {left}")
    return tmpl


def measure(cols, P, t_read, sel, t_sense_s=None):
    """One case's fields from its wrdata columns. The sense readings are taken
    `t_sense_s` after the read begins: the module's T_SENSE_S when omitted."""
    t, sn, rbl = cols[0], cols[1:5], cols[5]
    irw = [[-x for x in c] for c in cols[6:10]]  # into rbl from rwl_r
    m = {}
    for r in range(N_ROWS):
        t_off = P["TW0"] + r * P["TWSTEP"] + P["TWPULSE"]
        m[f"v_sn_r{r}_wl_off_v"] = interp_at(t, sn[r], t_off)
        m[f"v_sn_r{r}_after_write_v"] = interp_at(t, sn[r], P["THOLD0"] - 0.5e-9)
    t_pre = t_read - P["TPRE_GAP"] - 0.5e-9
    for r in range(N_ROWS):
        m[f"v_sn_r{r}_preread_v"] = interp_at(t, sn[r], t_pre)
        m[f"i_into_rbl_r{r}_preread_a"] = interp_at(t, irw[r], t_pre)
    m["v_rbl_preread_float_v"] = interp_at(t, rbl, t_read - 0.2e-9)
    uns = [r for r in range(N_ROWS) if r != sel]
    m["i_desel_sum_preread_a"] = sum(m[f"i_into_rbl_r{r}_preread_a"] for r in uns)
    t_s = t_read + (T_SENSE_S if t_sense_s is None else t_sense_s)
    for r in range(N_ROWS):
        m[f"i_into_rbl_r{r}_sense_a"] = interp_at(t, irw[r], t_s)
    m["i_desel_sum_sense_a"] = sum(m[f"i_into_rbl_r{r}_sense_a"] for r in uns)
    m["v_rbl_sense_v"] = interp_at(t, rbl, t_s)
    m["v_rbl_end_v"] = interp_at(t, rbl, t_read + P["TREAD_PULSE"] - 5 * P["TEDGE"])
    m["dv_rbl_sense_v"] = m["v_rbl_sense_v"] - m["v_rbl_preread_float_v"]
    lat = first_below(t, rbl, t_read, m["v_rbl_preread_float_v"] - DV_LATENCY_V)
    m["latency_s"] = lat
    m["latency_reason"] = (
        ""
        if lat is not None
        else f"rbl_0 never fell {DV_LATENCY_V} V below its pre-read level within the "
        f"{P['TREAD_PULSE'] * 1e9:.0f} ns read window plus tail"
    )
    t_end = t_read + P["TREAD_PULSE"] + P["TTAIL"] - 0.5e-9
    m["dv_sn_sel_read_disturb_v"] = interp_at(t, sn[sel], t_end) - m[f"v_sn_r{sel}_preread_v"]
    d = [interp_at(t, sn[r], t_end) - m[f"v_sn_r{r}_preread_v"] for r in uns]
    m["dv_sn_unsel_worst_signed_v"] = max(d, key=abs)
    return m


NOTES = (
    "schematic-level ASSUMED rbl loading (C_RBL), extracted C_SN per cell, no "
    "extracted bitline parasitics; rows written 0..3 sequentially; read age "
    "measured from row write end"
)


def base_row(pattern, sel, P, t_read, c_sn_f, run_id, corner, temp, age, *,
             c_rbl_f=None, t_sense_s=None, notes=None) -> dict:
    """The fields every loaded-column runner records for one stored pattern
    with row `sel` selected. `c_rbl_f`, `t_sense_s` and `notes` default to the
    Phase 2 ASSUMPTIONs; a variant passes its own knob values."""
    bits = [(pattern >> r) & 1 for r in range(N_ROWS)]
    c_rbl_f = C_RBL_F if c_rbl_f is None else c_rbl_f
    t_sense_s = T_SENSE_S if t_sense_s is None else t_sense_s
    return {
        "run_id": run_id, "corner": corner, "temp_c": temp, "age_label": age,
        "sel_row": sel, "stored_value": bits[sel],
        "pattern_rows3210": "".join(str(bits[r]) for r in reversed(range(N_ROWS))),
        "other_rows_pattern": "".join(
            str(bits[r]) for r in reversed(range(N_ROWS)) if r != sel
        ),
        "c_sn_ff": f"{c_sn_f * 1e15:.6f}",
        "c_rbl_ff_ASSUMPTION": f"{c_rbl_f * 1e15:.3f}", "vdd_v": VDD,
        "vrbl_precharge_v": P["VRBL"], "t_read_s": f"{t_read:.9e}",
        "t_sense_s_ASSUMPTION": t_sense_s, "dv_latency_v_ASSUMPTION": DV_LATENCY_V,
        "sel_row_age_at_read_s": f"{t_read - (P['TW0'] + sel * P['TWSTEP'] + P['TWPULSE']):.6e}",
        "max_row_age_at_read_s": f"{t_read - (P['TW0'] + P['TWPULSE']):.6e}",
        "notes": NOTES if notes is None else notes,
    }


def execute_batch(rows, deck_text, P, t_read, tmax, *, run_cmd, t_sense_s=None,
                  extra_measure=None, prefix="gcedram_col_", timeout=3600):
    """Run one batch in a single `ngspice -b` and fill each row from its
    waveform. Row j is the jth case of the deck `deck_text(outdir)` renders
    into the scratch directory the cases are written to. `extra_measure(cols,
    sel)` may add fields to each row's measurements. A failure is recorded on
    the rows (status sim_failed), never hidden."""
    with tempfile.TemporaryDirectory(prefix=prefix, ignore_cleanup_errors=True) as td:
        tmpdir = Path(td)
        deck = tmpdir / "tb.spice"
        err = None
        try:
            deck.write_text(deck_text(tmpdir))
            res = run_cmd(["ngspice", "-b", str(deck)], capture_output=True, text=True, timeout=timeout)
            err = (res.stdout + res.stderr)[-300:].replace("\n", " ")
        except Exception as e:  # recorded, never hidden
            err = str(e)[:300]
        for j, row in enumerate(rows):
            out = tmpdir / f"case{j}.dat"
            try:
                if not out.is_file():
                    raise RuntimeError("ngspice produced no output for this case: " + str(err))
                cols = read_wrdata(out, MIN_TIMEPOINTS)
                check_complete(cols[0], case_tstop(P, t_read))
                sel = int(row["sel_row"])
                m = measure(cols, P, t_read, sel, t_sense_s)
                if extra_measure is not None:
                    m.update(extra_measure(cols, sel))
                for key, v in m.items():
                    row[key] = "" if v is None else (v if isinstance(v, str) else f"{v:.6e}")
                row["status"] = "ok"
            except Exception as e:
                row["status"] = "sim_failed"
                row["reason"] = str(e)[:400]
    return rows


def run_batch(args):
    """All cases of one (corner, temp, age, sel_row): 16 stored patterns."""
    lib, corner, temp, age, sel, patterns, c_sn_f, run_id, prov, tmax = args
    tmpl = TEMPLATE.read_text()
    P = parse_params(tmpl)
    t_read = read_time(P, age)
    cases = [(p, sel, t_read) for p in patterns]
    rows = []
    for pattern in patterns:
        row = {k: "" for k in FIELDS}
        row.update(prov)
        row.update(base_row(pattern, sel, P, t_read, c_sn_f, run_id, corner, temp, age))
        rows.append(row)
    return execute_batch(
        rows, lambda outdir: render(tmpl, lib, corner, temp, cases, c_sn_f, outdir, tmax, P),
        P, t_read, tmax, run_cmd=subprocess.run,
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdk-root")
    ap.add_argument("--pdk", default=DEFAULT_PDK_VARIANT)
    ap.add_argument("--corners", nargs="+", default=CORNERS)
    ap.add_argument("--temps-c", nargs="+", type=int, default=TEMPS_C)
    ap.add_argument("--ages", nargs="+", default=AGE_LABELS, choices=AGE_LABELS)
    ap.add_argument("--rows", nargs="+", type=int, default=list(range(N_ROWS)))
    ap.add_argument("--patterns", nargs="+", type=int, default=list(range(16)),
                    help="4-bit stored pattern, bit r = row r data")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--tmax-ns", type=float, default=0.5)
    ap.add_argument("--results-csv", default=str(RESULTS_CSV))
    ap.add_argument("--check-env", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="render one deck to stdout and exit")
    a = ap.parse_args(argv)

    lib = resolve_ngspice_lib(resolve_pdk_root(a.pdk_root), a.pdk)
    ok = check_ngspice_available(lib) and TEMPLATE.is_file() and DESIGN_NETLIST.is_file()
    if a.check_env:
        print("environment OK" if ok else "environment NOT OK")
        return 0 if ok else 1
    if not ok:
        return 1
    c_sn_ff, _prov = load_extracted_c_sn(EXTRACT_JSON, "sn")
    c_sn_f = c_sn_ff * 1e-15
    tmpl = TEMPLATE.read_text()
    P = parse_params(tmpl)
    if a.dry_run:
        cases = [(p, a.rows[0], read_time(P, a.ages[0])) for p in a.patterns]
        print(render(tmpl, lib, a.corners[0], a.temps_c[0], cases, c_sn_f, "/tmp/out", a.tmax_ns * 1e-9, P))
        return 0
    now = datetime.datetime.now(datetime.timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%SZ")
    prov = {
        "timestamp_utc": now.isoformat(timespec="seconds"),
        "repo_git_sha": repo_git_sha(REPO_ROOT), "pdk_open_pdks_commit": PDK_OPEN_PDKS_COMMIT,
        "ngspice_version": ngspice_version(),
    }
    pts = [
        (lib, c, t, ag, s, a.patterns, c_sn_f, run_id, prov, a.tmax_ns * 1e-9)
        for c, t, ag, s in itertools.product(a.corners, a.temps_c, a.ages, a.rows)
    ]
    n_total = len(pts) * len(a.patterns)
    csv_path = Path(a.results_csv)
    print(f"run_id={run_id}: {n_total} points in {len(pts)} batches, {a.jobs} jobs", file=sys.stderr)
    n_bad = n_done = 0
    with cf.ProcessPoolExecutor(max_workers=a.jobs) as ex:
        for rows in ex.map(run_batch, pts, chunksize=1):
            for row in rows:
                append_result(csv_path, FIELDS, row)
                n_bad += row["status"] != "ok"
            n_done += len(rows)
            print(f"  {n_done}/{n_total} done ({n_bad} sim_failed)", file=sys.stderr)
    print(f"run_id={run_id} complete: {n_total} points, {n_bad} sim_failed -> {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
