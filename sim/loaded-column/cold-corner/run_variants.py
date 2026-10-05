#!/usr/bin/env python3
"""Cold-corner variant runner for the loaded four-row 2T column (issue #47).

Re-runs the Phase 2 loaded-column measurement (sim/loaded-column/,
issue #45) with ONE declared knob changed per variant (variants.py), so that
the cold-corner stored-level / read-separation failure can be attributed and
candidate remedies compared on the same footing. It reuses the Phase 2
runner's waveform reader and measurement code unchanged (imported, not
copied) and adds one measurement: the selected storage node at the sense
instant (`v_sn_sel_sense_v`), which separates read-wordline coupling from the
written level.

This is characterization, NOT a sense amplifier or a spec change.

Usage:
    python3 sim/loaded-column/cold-corner/run_variants.py --check-env
    python3 sim/loaded-column/cold-corner/run_variants.py --list
    python3 sim/loaded-column/cold-corner/run_variants.py --variants baseline --jobs 8
    python3 sim/loaded-column/cold-corner/run_variants.py --variants attr_vwl_2p2 --dry-run

Results are APPENDED to results/variant_results.csv (never rewritten). One row
per simulation point, failed points included (status != ok, with reason).
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime
import hashlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
LC_DIR = HERE.parent
sys.path.insert(0, str(LC_DIR))
sys.path.insert(0, str(HERE))
import run_loaded_column as R  # noqa: E402  (Phase 2 runner; also sets up sim/ imports)
import variants as V  # noqa: E402
from _evidence_common import (  # noqa: E402
    DEFAULT_PDK_VARIANT,
    PDK_OPEN_PDKS_COMMIT,
    append_result,
    check_ngspice_available,
    ngspice_version,
    repo_git_sha,
    resolve_ngspice_lib,
    resolve_pdk_root,
)

TEMPLATE = HERE / "tb_cold_variant.spice.tmpl"
RESULTS_CSV = HERE / "results" / "variant_results.csv"
N_ROWS = R.N_ROWS
FRESH_READ_AFTER_HOLD_S = 10e-9  # Phase 2: THOLD0 100 ns -> fresh read at 110 ns

KNOB_FIELDS = [
    "variant_id", "variant_class", "variant_sha", "changed_knobs",
    "vwl_v", "twpulse_s", "vrwl_sel_v", "wr_model", "wr_w_um", "rd_model", "rd_w_um",
    "force_sn", "vsn1_v", "template_sha",
]
FIELDS = KNOB_FIELDS + list(R.FIELDS) + ["v_sn_sel_sense_v"]


def timing(k: dict) -> dict:
    """Write timing derived from the pulse width, identical to Phase 2 at 20 ns
    (TWSTEP 25 ns, THOLD0 100 ns)."""
    tw = k["twpulse_s"]
    twstep = tw + 5e-9
    thold0 = 1e-9 + 3 * twstep + tw + 4e-9
    return {"TWPULSE": tw, "TWSTEP": twstep, "THOLD0": thold0}


def params(k: dict) -> dict:
    P = R.parse_params(TEMPLATE.read_text())
    P.update(timing(k))
    return P


def read_time(P: dict, age: str) -> float:
    if age == "fresh":
        return P["THOLD0"] + FRESH_READ_AFTER_HOLD_S
    return P["TW0"] + P["TWPULSE"] + R.T_REFRESH_S


def device_card(base_params: str, model: str, w_um: float) -> str:
    """Re-size a parsed design/gain_cell_2t.spice device card to width w_um,
    keeping the design's own diffusion convention (ad = as = 0.29 um * W,
    pd = ps = 2 (W + 0.29 um), nrd = nrs = 0.29 um / W), which reproduces the
    committed card exactly at W = 0.42 um."""
    w0 = float(re.search(r"\bW=([0-9.]+)", base_params).group(1))
    if abs(w_um - w0) < 1e-12:
        return f"{model} {base_params}"
    sub = {
        "W": f"{w_um:g}", "ad": f"{0.29 * w_um:.6g}", "as": f"{0.29 * w_um:.6g}",
        "pd": f"{2 * (w_um + 0.29):.6g}", "ps": f"{2 * (w_um + 0.29):.6g}",
        "nrd": f"{0.29 / w_um:.12g}", "nrs": f"{0.29 / w_um:.12g}",
    }
    out = base_params
    for key, val in sub.items():
        out, n = re.subn(rf"\b{key}=[0-9.eE+-]+", f"{key}={val}", out)
        if n != 1:
            raise RuntimeError(f"device card has {n} '{key}=' fields: {base_params}")
    return f"{model} {out}"


def build_cells(k: dict) -> str:
    topo = R.build_topology(N_ROWS, R.N_COLS)
    devs = R.parse_design_devices()
    for name in ("M_WR", "M_RD"):
        if devs[name][0] != V.NFET:
            raise RuntimeError(f"design {name} model changed: {devs[name][0]}")
    wr = device_card(devs["M_WR"][1], k["wr_model"], k["wr_w_um"])
    rd = device_card(devs["M_RD"][1], k["rd_model"], k["rd_w_um"])
    lines = []
    for d in topo["devices"]:
        lines.append(f"X{d['wr_name']} {d['sn']} {d['wl']} {d['bl']} GND {wr}")
        lines.append(f"X{d['rd_name']} {d['rbl']} {d['sn']} {d['rwl']} GND {rd}")
    return "\n".join(lines)


def render(k, lib, corner, temp, cases, c_sn_f, outdir, tmax, P):
    """cases: [(pattern, sel_row, t_read)]; one ngspice process per batch."""
    tmpl = TEMPLATE.read_text()
    cells = (
        build_cells(k)
        + "\n* extracted per-cell storage-node capacitance (lumped)\n"
        + "\n".join(f"c_sn_{r} sn_{r}_0 0 {c_sn_f:.6e}" for r in range(N_ROWS))
    )
    ws, pw = [], ["0 0"]
    for r in range(N_ROWS):
        ws.append(
            f"vwl_{r} wl_{r} 0 pulse(0 {{VWL}} {{TW0+{r}*TWSTEP}} {{TEDGE}} {{TEDGE}} "
            f"{{TWPULSE-TEDGE}} 1)"
        )
        on = f"TW0+{r}*TWSTEP"
        off = f"TW0+{r}*TWSTEP+TWPULSE"
        pw += [
            f"{{{on}-TEDGE}} 0", f"{{{on}}} {{VDD*B{r}}}",
            f"{{{off}+TBL_LAG}} {{VDD*B{r}}}", f"{{{off}+TBL_LAG+TEDGE}} 0",
        ]
    ws.append("vbl bl_0 0 pwl(" + " ".join(pw) + ")")
    rs = [
        f"vrwl_{r} rwl_{r} 0 pwl(0 {{VDD}} {{T_READ}} {{VDD}} {{T_READ+TEDGE}} "
        f"{{VDD*(1-SL{r})+VRWL_SEL*SL{r}}} {{T_READ+TREAD_PULSE}} {{VDD*(1-SL{r})+VRWL_SEL*SL{r}}} "
        f"{{T_READ+TREAD_PULSE+TEDGE}} {{VDD}})"
        for r in range(N_ROWS)
    ]
    # Phase 2: each sn starts at the OPPOSITE of its data (genuine overwrite).
    # FORCE=1 (attribution only): sn starts AT its data, '1' = VSN1.
    ics = ".ic " + " ".join(
        f"v(sn_{r}_0)={{(1-FORCE)*VDD*(1-B{r})+FORCE*VSN1*B{r}}}" for r in range(N_ROWS)
    )
    ctl = []
    for j, (pattern, sel, t_read) in enumerate(cases):
        for r in range(N_ROWS):
            ctl.append(f"alterparam B{r} = {(pattern >> r) & 1}")
            ctl.append(f"alterparam SL{r} = {1 if r == sel else 0}")
        ctl.append(f"alterparam T_READ = {t_read:.9e}")
        ctl.append("reset")
        ctl.append("destroy all")
        ctl.append(f"tran 10p {R.case_tstop(P, t_read):.9e} 0 {tmax:.3e}")
        ctl.append(
            f"wrdata {outdir}/case{j}.dat v(sn_0_0) v(sn_1_0) v(sn_2_0) v(sn_3_0) v(rbl_0) "
            "i(vrwl_0) i(vrwl_1) i(vrwl_2) i(vrwl_3)"
        )
    subs = {
        "@@TWPULSE@@": f"{P['TWPULSE']:.6e}", "@@TWSTEP@@": f"{P['TWSTEP']:.6e}",
        "@@THOLD0@@": f"{P['THOLD0']:.6e}", "@@VWL@@": f"{k['vwl_v']:.6g}",
        "@@VRWL_SEL@@": f"{k['vrwl_sel_v']:.6g}", "@@FORCE@@": str(int(k["force"])),
        "@@VSN1@@": f"{k['vsn1_v']:.6g}", "@@T_READ_DEFAULT@@": f"{read_time(P, 'fresh'):.6e}",
        "@@C_RBL@@": f"{k['c_rbl_f']:.6e}",
        "@@PDK_NGSPICE_LIB@@": str(lib), "@@CORNER@@": corner, "@@TEMP_C@@": str(temp),
        "@@CELLS@@": cells, "@@WRITE_SOURCES@@": "\n".join(ws),
        "@@RWL_SOURCES@@": "\n".join(rs), "@@ICS@@": ics, "@@CASES@@": "\n".join(ctl),
    }
    for key, val in subs.items():
        tmpl = tmpl.replace(key, val)
    left = re.findall(r"@@[A-Z_0-9]+@@", tmpl)
    if left:
        raise RuntimeError(f"unsubstituted tokens {left}")
    return tmpl


def batches_for(vid: str):
    """(corner, temp, age, [(pattern, sel)]) batches. Fresh points run all 64
    cases in one process; aged points (5 us transients) one process per row."""
    out = []
    for c, t, a in V.points(vid):
        cases = [(p, s) for s in range(N_ROWS) for p in range(16)]
        if a == "fresh":
            out.append((c, t, a, cases))
        else:
            for s in range(N_ROWS):
                out.append((c, t, a, [x for x in cases if x[1] == s]))
    return out


def run_batch(args):
    vid, lib, corner, temp, age, cases, c_sn_f, run_id, prov, tmax = args
    k = V.knobs(vid)
    R.T_SENSE_S = k["t_sense_s"]  # module global read by R.measure (this worker only)
    R.C_RBL_F = k["c_rbl_f"]
    P = params(k)
    t_read = read_time(P, age)
    tmpl_sha = hashlib.sha256(TEMPLATE.read_bytes()).hexdigest()[:16]
    rows = []
    for pattern, sel in cases:
        bits = [(pattern >> r) & 1 for r in range(N_ROWS)]
        row = {f: "" for f in FIELDS}
        row.update(prov)
        row.update({
            "variant_id": vid, "variant_class": V.BY_ID[vid]["class"],
            "variant_sha": V.variant_sha(vid),
            "changed_knobs": ";".join(f"{a}={b}" for a, b in sorted(V.BY_ID[vid]["changes"].items())),
            "vwl_v": k["vwl_v"], "twpulse_s": k["twpulse_s"], "vrwl_sel_v": k["vrwl_sel_v"],
            "wr_model": k["wr_model"], "wr_w_um": k["wr_w_um"], "rd_model": k["rd_model"],
            "rd_w_um": k["rd_w_um"], "force_sn": k["force"], "vsn1_v": k["vsn1_v"],
            "template_sha": tmpl_sha,
            "run_id": run_id, "corner": corner, "temp_c": temp, "age_label": age,
            "sel_row": sel, "stored_value": bits[sel],
            "pattern_rows3210": "".join(str(bits[r]) for r in reversed(range(N_ROWS))),
            "other_rows_pattern": "".join(str(bits[r]) for r in reversed(range(N_ROWS)) if r != sel),
            "c_sn_ff": f"{c_sn_f * 1e15:.6f}",
            "c_rbl_ff_ASSUMPTION": f"{k['c_rbl_f'] * 1e15:.3f}", "vdd_v": R.VDD,
            "vrbl_precharge_v": P["VRBL"], "t_read_s": f"{t_read:.9e}",
            "t_sense_s_ASSUMPTION": k["t_sense_s"], "dv_latency_v_ASSUMPTION": R.DV_LATENCY_V,
            "sel_row_age_at_read_s": f"{t_read - (P['TW0'] + sel * P['TWSTEP'] + P['TWPULSE']):.6e}",
            "max_row_age_at_read_s": f"{t_read - (P['TW0'] + P['TWPULSE']):.6e}",
            "notes": f"issue #47 variant {vid}: {V.BY_ID[vid]['why']}; schematic-level ASSUMED "
                     "C_RBL, extracted C_SN, no extracted bitline parasitics",
        })
        rows.append(row)
    tmpdir = Path(tempfile.mkdtemp(prefix="gcedram_cold_"))
    deck = tmpdir / "tb.spice"
    err = None
    try:
        deck.write_text(render(k, lib, corner, temp, [(p, s, t_read) for p, s in cases],
                               c_sn_f, tmpdir, tmax, P))
        res = subprocess.run(["ngspice", "-b", str(deck)], capture_output=True, text=True, timeout=7200)
        err = (res.stdout + res.stderr)[-300:].replace("\n", " ")
    except Exception as e:  # recorded, never hidden
        err = str(e)[:300]
    for j, row in enumerate(rows):
        out = tmpdir / f"case{j}.dat"
        try:
            if not out.is_file():
                raise RuntimeError("ngspice produced no output for this case: " + str(err))
            cols = R.read_wrdata(out)
            R.check_complete(cols[0], R.case_tstop(P, t_read))
            sel = int(row["sel_row"])
            m = R.measure(cols, P, t_read, sel)
            m["v_sn_sel_sense_v"] = R.interp(cols[0], cols[1 + sel], t_read + k["t_sense_s"])
            for key, v in m.items():
                row[key] = "" if v is None else (v if isinstance(v, str) else f"{v:.6e}")
            row["status"] = "ok"
        except Exception as e:
            row["status"] = "sim_failed"
            row["reason"] = str(e)[:400]
    for p in tmpdir.glob("*"):
        try:
            p.unlink()
        except OSError:
            pass
    try:
        tmpdir.rmdir()
    except OSError:
        pass
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdk-root")
    ap.add_argument("--pdk", default=DEFAULT_PDK_VARIANT)
    ap.add_argument("--variants", nargs="+", default=None, help="variant ids (default: all)")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--tmax-ns", type=float, default=0.5)
    ap.add_argument("--results-csv", default=str(RESULTS_CSV))
    ap.add_argument("--check-env", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="render the first batch's deck and exit")
    a = ap.parse_args(argv)

    if a.list:
        for v in V.VARIANTS:
            print(f"{v['id']:28s} {v['class']:34s} {v['scope']:11s} {v['why']}")
        return 0
    vids = a.variants or [v["id"] for v in V.VARIANTS]
    for vid in vids:
        if vid not in V.BY_ID:
            print(f"unknown variant {vid}", file=sys.stderr)
            return 1
    lib = resolve_ngspice_lib(resolve_pdk_root(a.pdk_root), a.pdk)
    ok = check_ngspice_available(lib) and TEMPLATE.is_file() and R.DESIGN_NETLIST.is_file()
    if a.check_env:
        print("environment OK" if ok else "environment NOT OK")
        return 0 if ok else 1
    if not ok:
        return 1
    c_sn_ff, _ = R.load_extracted_c_sn(R.EXTRACT_JSON, "sn")
    c_sn_f = c_sn_ff * 1e-15
    if a.dry_run:
        vid = vids[0]
        k = V.knobs(vid)
        P = params(k)
        c, t, ag, cases = batches_for(vid)[0]
        tr = read_time(P, ag)
        print(render(k, lib, c, t, [(p, s, tr) for p, s in cases], c_sn_f, "/tmp/out", a.tmax_ns * 1e-9, P))
        return 0
    now = datetime.datetime.now(datetime.timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%SZ")
    prov = {
        "timestamp_utc": now.isoformat(timespec="seconds"),
        "repo_git_sha": repo_git_sha(R.REPO_ROOT), "pdk_open_pdks_commit": PDK_OPEN_PDKS_COMMIT,
        "ngspice_version": ngspice_version(),
    }
    jobs = [
        (vid, lib, c, t, ag, cases, c_sn_f, run_id, prov, a.tmax_ns * 1e-9)
        for vid in vids for (c, t, ag, cases) in batches_for(vid)
    ]
    # longest (aged) batches first so the pool tail is short
    jobs.sort(key=lambda j: j[4] != "refresh_bound")
    n_total = sum(len(j[5]) for j in jobs)
    csv_path = Path(a.results_csv)
    print(f"run_id={run_id}: {len(vids)} variants, {n_total} points, {len(jobs)} batches, "
          f"{a.jobs} jobs", file=sys.stderr)
    n_bad = n_done = 0
    with cf.ProcessPoolExecutor(max_workers=a.jobs) as ex:
        for rows in ex.map(run_batch, jobs, chunksize=1):
            for row in rows:
                append_result(csv_path, FIELDS, row)
                n_bad += row["status"] != "ok"
            n_done += len(rows)
            print(f"  {n_done}/{n_total} done ({n_bad} sim_failed) [{rows[0]['variant_id']} "
                  f"{rows[0]['corner']}/{rows[0]['temp_c']} {rows[0]['age_label']}]", file=sys.stderr)
    print(f"run_id={run_id} complete: {n_total} points, {n_bad} sim_failed -> {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
