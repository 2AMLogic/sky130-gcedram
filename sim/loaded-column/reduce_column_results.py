#!/usr/bin/env python3
"""Turn `klt sim` batch reports into loaded-column result rows (issue #169).

Stdlib only. Reads the reports produced from the requests
`gen_column_requests.py` writes and APPENDS one row per (corner, stored
pattern) to `results/loaded_column_results.csv`, in the schema
`run_loaded_column.py` already writes -- the same columns, so the `f6eeac7`
block sits beside the `c6d73a3` block in one file and `analyze_loaded_column.py`
reads both.

The gate this script enforces (issue #169 acceptance criteria): a report may be
recorded as `f6eeac7` evidence ONLY when the fleet worker's own PDK revision
stamp equals the repo pin AND the report's `pdk_stamp_comparison` is `match`.
Anything else (`mismatch`, `not_comparable`, a missing capture) is refused with
exit 2 and nothing is written -- a run against another PDK revision must never
be filed under this pin.

Derived quantities (`i_desel_sum_*`, `dv_rbl_sense_v`, `latency_s`,
`dv_sn_sel_read_disturb_v`, `dv_sn_unsel_worst_signed_v`) are computed here from
the measured scalars, exactly as `run_loaded_column.measure()` computes them
from a waveform.

Usage:
    python3 sim/loaded-column/reduce_column_results.py --run-id 20261114T0900Z \\
        results/klt_report_lc_fresh_sel0_20261114T0900Z.json ...
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM = HERE.parent
REPO = SIM.parent
sys.path.insert(0, str(SIM))
sys.path.insert(0, str(HERE))
import run_loaded_column as R  # noqa: E402
import gen_column_requests as G  # noqa: E402
from _evidence_common import (  # noqa: E402
    PDK_OPEN_PDKS_COMMIT, append_result, load_json, repo_git_sha,
)

N_ROWS = R.N_ROWS
RESULTS_CSV = R.RESULTS_CSV
JOB_RE = re.compile(r"^lc_(?P<age>fresh|refresh_bound)_sel(?P<sel>[0-3])$")


class GateError(RuntimeError):
    """The report may not be recorded under this PDK pin."""


# --------------------------------------------------------------------------- #
# the PDK / engine gate
# --------------------------------------------------------------------------- #
def gate(report: dict, *, pin: str = PDK_OPEN_PDKS_COMMIT) -> dict:
    """Refuse a report that was not produced by a worker on `pin`. Returns the
    provenance fields every row records about the run."""
    env = report.get("environment") or {}
    remote = env.get("remote") or {}
    worker = remote.get("worker_environment") or {}
    pdk = worker.get("pdk") or {}
    cmp_ = worker.get("pdk_stamp_comparison") or {}
    stamp = str(pdk.get("stamp_text") or "")
    status = str(cmp_.get("status") or "missing")
    if status != "match":
        raise GateError(
            f"pdk_stamp_comparison is {status!r} (not 'match'): "
            f"{json.dumps(cmp_)}; worker stamp {stamp!r}. Issue #169 allows a "
            "fleet report to be filed as f6eeac7 evidence only on 'match'."
        )
    if pin not in stamp:
        raise GateError(
            f"worker PDK stamp {stamp!r} does not name the repo pin {pin}"
        )
    banner = ((worker.get("simulator") or {}).get("version_banner") or "")
    ngs = next((ln.strip() for ln in banner.splitlines() if "ngspice" in ln.lower()),
               f"ngspice-{env.get('engine_version', 'unknown')}")
    return {
        "job_id": str(remote.get("job_id") or "unknown"),
        "runner_klt_version": str(remote.get("runner_klt_version") or "unknown"),
        "client_klt_version": str(remote.get("client_klt_version") or "unknown"),
        "ngspice_version": ngs,
        "pdk_stamp_text": stamp,
        "pdk_stamp_sha256": str(pdk.get("stamp_sha256") or ""),
        "engine_build_comparison": json.dumps(
            worker.get("engine_build_comparison") or {}, sort_keys=True),
    }


# --------------------------------------------------------------------------- #
# reduction
# --------------------------------------------------------------------------- #
def job_of(report: dict, override: str | None = None) -> tuple[str, int]:
    """(age, selected row) from the job name, taken from the report's netlist
    path unless overridden."""
    name = override or Path(str((report.get("netlist") or {}).get("path") or "")).stem
    m = JOB_RE.match(name)
    if not m:
        raise GateError(f"cannot read age/selected row from job name {name!r}")
    return m.group("age"), int(m.group("sel"))


def corner_measurements(corner: dict) -> dict[str, float | None]:
    return {m["name"]: m.get("value") for m in corner.get("measurements") or []}


def corner_failure(corner: dict) -> str:
    """A one-line reason for a corner that did not produce usable results."""
    diags = [d for d in corner.get("diagnostics") or []
             if d.get("severity") in ("error", "fatal")]
    if diags:
        return f"{corner.get('status')}: " + "; ".join(
            f"[{d.get('code', 'error')}] {str(d.get('message', ''))[:160]}"
            for d in diags[:3])
    return f"corner status {corner.get('status')!r}"


def rows_for_corner(corner: dict, *, age: str, sel: int, knobs: dict, c_sn_f: float,
                    prov: dict, run_id: str, deck: str, notes_extra: str = "") -> list[dict]:
    P = G.params(knobs)
    T = G.instants(P, knobs, age)
    t_read = T["t_read"]
    mv = corner_measurements(corner)
    corner_bad = None if corner.get("status") in ("pass", "fail") else corner_failure(corner)
    lat_threshold = P["VRBL"] - R.DV_LATENCY_V
    out = []
    for pattern in G.PATTERNS:
        g = G.tag(pattern)
        bits = [(pattern >> r) & 1 for r in range(N_ROWS)]
        row = {k: "" for k in R.FIELDS}
        row.update({
            "run_id": run_id,
            "timestamp_utc": prov["timestamp_utc"],
            "repo_git_sha": prov["repo_git_sha"],
            "pdk_open_pdks_commit": PDK_OPEN_PDKS_COMMIT,
            "ngspice_version": prov["ngspice_version"],
            "corner": corner["process"],
            "temp_c": corner["temperature_c"],
            "age_label": age,
            "sel_row": sel,
            "stored_value": bits[sel],
            "pattern_rows3210": "".join(str(bits[r]) for r in reversed(range(N_ROWS))),
            "other_rows_pattern": "".join(
                str(bits[r]) for r in reversed(range(N_ROWS)) if r != sel),
            "c_sn_ff": f"{c_sn_f * 1e15:.6f}",
            "c_rbl_ff_ASSUMPTION": f"{knobs['c_rbl_f'] * 1e15:.3f}",
            "vdd_v": R.VDD,
            "vrbl_precharge_v": P["VRBL"],
            "t_read_s": f"{t_read:.9e}",
            "t_sense_s_ASSUMPTION": knobs["t_sense_s"],
            "dv_latency_v_ASSUMPTION": R.DV_LATENCY_V,
            "sel_row_age_at_read_s":
                f"{t_read - (P['TW0'] + sel * P['TWSTEP'] + P['TWPULSE']):.6e}",
            "max_row_age_at_read_s": f"{t_read - (P['TW0'] + P['TWPULSE']):.6e}",
            "notes": (
                "issue #169 re-qualification under open_pdks f6eeac7: klt sim batch "
                f"job {prov['job_id']} (runner klt {prov['runner_klt_version']}, "
                f"worker {prov['pdk_stamp_text']}, pdk_stamp_comparison match), deck "
                f"{deck} with 16 independent column instances, .meas reductions, "
                f"latency threshold {lat_threshold:.6f} V absolute "
                "(run_loaded_column.py used the measured pre-read float level minus "
                "0.1 V; v_rbl_preread_float_v on this row shows the difference); "
                "schematic-level ASSUMED rbl loading (C_RBL), extracted C_SN per "
                "cell, no extracted bitline parasitics; rows written 0..3 "
                "sequentially; read age measured from row write end"
                + (f"; {notes_extra}" if notes_extra else "")
            ),
        })
        if corner_bad:
            row["status"], row["reason"] = "sim_failed", corner_bad[:400]
            out.append(row)
            continue
        missing = []

        def val(field):
            v = mv.get(f"{g}__{field}")
            if v is None:
                missing.append(field)
            return v

        sn_pre = [val(f"v_sn_r{r}_preread_v") for r in range(N_ROWS)]
        sn_end = [val(f"v_sn_r{r}_end_v") for r in range(N_ROWS)]
        i_pre = [val(f"i_into_rbl_r{r}_preread_a") for r in range(N_ROWS)]
        i_sense = [val(f"i_into_rbl_r{r}_sense_a") for r in range(N_ROWS)]
        v_rbl_pre = val("v_rbl_preread_float_v")
        v_rbl_sense = val("v_rbl_sense_v")
        v_rbl_end = val("v_rbl_end_v")
        for r in range(N_ROWS):
            row[f"v_sn_r{r}_wl_off_v"] = val(f"v_sn_r{r}_wl_off_v")
            row[f"v_sn_r{r}_after_write_v"] = val(f"v_sn_r{r}_after_write_v")
        if missing:
            row["status"] = "sim_failed"
            row["reason"] = ("measurements produced no value: " + ",".join(missing))[:400]
            for k in list(row):
                if row[k] is None:
                    row[k] = ""
            out.append(row)
            continue
        uns = [r for r in range(N_ROWS) if r != sel]
        for r in range(N_ROWS):
            row[f"v_sn_r{r}_wl_off_v"] = f"{row[f'v_sn_r{r}_wl_off_v']:.6e}"
            row[f"v_sn_r{r}_after_write_v"] = f"{row[f'v_sn_r{r}_after_write_v']:.6e}"
            row[f"v_sn_r{r}_preread_v"] = f"{sn_pre[r]:.6e}"
            row[f"i_into_rbl_r{r}_preread_a"] = f"{i_pre[r]:.6e}"
            row[f"i_into_rbl_r{r}_sense_a"] = f"{i_sense[r]:.6e}"
        row["v_rbl_preread_float_v"] = f"{v_rbl_pre:.6e}"
        row["i_desel_sum_preread_a"] = f"{sum(i_pre[r] for r in uns):.6e}"
        row["i_desel_sum_sense_a"] = f"{sum(i_sense[r] for r in uns):.6e}"
        row["v_rbl_sense_v"] = f"{v_rbl_sense:.6e}"
        row["v_rbl_end_v"] = f"{v_rbl_end:.6e}"
        row["dv_rbl_sense_v"] = f"{v_rbl_sense - v_rbl_pre:.6e}"
        t_abs = mv.get(f"{g}__t_latency_abs_s")
        if t_abs is None:
            row["latency_s"] = ""
            row["latency_reason"] = (
                f"rbl_{g} never fell to {lat_threshold:.6f} V "
                f"({R.DV_LATENCY_V} V below the VRBL precharge level) within the "
                f"{P['TREAD_PULSE'] * 1e9:.0f} ns read window plus tail"
            )
        else:
            row["latency_s"] = f"{t_abs - t_read:.6e}"
            row["latency_reason"] = ""
        row["dv_sn_sel_read_disturb_v"] = f"{sn_end[sel] - sn_pre[sel]:.6e}"
        row["dv_sn_unsel_worst_signed_v"] = (
            f"{max((sn_end[r] - sn_pre[r] for r in uns), key=abs):.6e}")
        row["status"] = "ok"
        out.append(row)
    return out


def reduce_report_dict(report: dict, *, run_id: str, knobs: dict, c_sn_f: float,
                       job: str | None = None, notes_extra: str = "") -> list[dict]:
    prov = gate(report)
    age, sel = job_of(report, job)
    now = datetime.datetime.now(datetime.timezone.utc)
    prov["timestamp_utc"] = now.isoformat(timespec="seconds")
    prov["repo_git_sha"] = repo_git_sha(REPO)
    deck = Path(str((report.get("netlist") or {}).get("path") or "")).name
    rows = []
    for corner in report.get("corners") or []:
        rows += rows_for_corner(corner, age=age, sel=sel, knobs=knobs, c_sn_f=c_sn_f,
                                prov=prov, run_id=run_id, deck=deck,
                                notes_extra=notes_extra)
    return rows


def reduce_report(path: Path, **kw) -> list[dict]:
    """`path` may be `.json` or `.json.gz` (committed reports are gzipped)."""
    return reduce_report_dict(load_json(Path(path)), **kw)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("reports", nargs="+")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--job", help="override the job name (default: from the report)")
    ap.add_argument("--results-csv", default=str(RESULTS_CSV))
    ap.add_argument("--notes-extra", default="")
    ap.add_argument("--dry-run", action="store_true",
                    help="reduce and summarise, write nothing")
    a = ap.parse_args(argv)
    c_sn_f = G.c_sn_farads()
    csv_path = Path(a.results_csv)
    total = bad = 0
    for p in a.reports:
        try:
            rows = reduce_report(Path(p), run_id=a.run_id, knobs=dict(G.BASELINE_KNOBS),
                                 c_sn_f=c_sn_f, job=a.job, notes_extra=a.notes_extra)
        except GateError as exc:
            print(f"REFUSED {p}: {exc}", file=sys.stderr)
            return 2
        n_bad = sum(r["status"] != "ok" for r in rows)
        print(f"{Path(p).name}: {len(rows)} rows, {n_bad} sim_failed")
        total += len(rows)
        bad += n_bad
        if not a.dry_run:
            for row in rows:
                append_result(csv_path, R.FIELDS, row)
    print(f"{'would append' if a.dry_run else 'appended'} {total} rows "
          f"({bad} sim_failed) -> {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
