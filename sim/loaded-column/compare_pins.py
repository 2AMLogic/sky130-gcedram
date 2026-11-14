#!/usr/bin/env python3
"""Tabulate the loaded-column deltas between two PDK pins (issue #169).

Stdlib only. Joins two run blocks of `results/loaded_column_results.csv` on
(corner, temp_c, age_label, sel_row, pattern_rows3210) and reports, per measured
field, the worst absolute and relative change and where it occurs; then the
group-level worst-case read separation from the two runs' committed summary
JSONs. Prints GitHub-flavoured Markdown, so the table in README.md is generated,
not hand-copied.

TOLERANCES (declared here, for THIS comparison only -- they are not spec
thresholds and nothing in spec/ is relaxed by them). A field passes when

    |head - base| <= max(atol(field), RTOL * |base|)

with RTOL 2% and per-class atol: 1 mV on a voltage, 1 pA on a current, 10 ps on
a time. The floors exist because several measured quantities sit at or below the
simulator's own noise (a deselected-row current of ~1e-11 A, an `rbl` level of
~1e-06 V): a bare relative test on those is meaningless.

Exit status: 0 = every field within tolerance, 1 = at least one field outside it
(which issue #169 requires be raised as a follow-up issue or a decision-record
row, not absorbed silently), 2 = the comparison could not be made.

Usage:
    python3 -I sim/loaded-column/compare_pins.py
    python3 -I sim/loaded-column/compare_pins.py --base-run-id 20261005T102906Z \\
        --head-run-id 20261114T0930Z
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS_CSV = HERE / "results" / "loaded_column_results.csv"
RESULTS_DIR = HERE / "results"

BASE_PIN = "c6d73a35f524070e85faff4a6a9eef49553ebc2b"
HEAD_PIN = "f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7"
KEY = ("corner", "temp_c", "age_label", "sel_row", "pattern_rows3210")

RTOL = 0.02
ATOL_V = 1e-3
ATOL_A = 1e-12
ATOL_S = 1e-11

#: Measured/derived numeric fields, in report order. Provenance, keys and the
#: declared-assumption columns are excluded: they are inputs, not results.
FIELDS = (
    [f"v_sn_r{r}_wl_off_v" for r in range(4)]
    + [f"v_sn_r{r}_after_write_v" for r in range(4)]
    + [f"v_sn_r{r}_preread_v" for r in range(4)]
    + ["v_rbl_preread_float_v"]
    + [f"i_into_rbl_r{r}_preread_a" for r in range(4)]
    + ["i_desel_sum_preread_a"]
    + [f"i_into_rbl_r{r}_sense_a" for r in range(4)]
    + ["i_desel_sum_sense_a", "v_rbl_sense_v", "v_rbl_end_v", "dv_rbl_sense_v",
       "latency_s", "dv_sn_sel_read_disturb_v", "dv_sn_unsel_worst_signed_v"]
)


def atol(field: str) -> float:
    if field.endswith("_a"):
        return ATOL_A
    if field.endswith("_s"):
        return ATOL_S
    return ATOL_V


def load(path: Path) -> list[dict]:
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def pick_run(rows: list[dict], pin: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    ids = sorted({r["run_id"] for r in rows if r["pdk_open_pdks_commit"] == pin})
    if not ids:
        raise SystemExit(f"no rows pinned to {pin[:7]} in the results CSV")
    return ids[-1]


def index(rows: list[dict], run_id: str) -> dict[tuple, dict]:
    out = {}
    for r in rows:
        if r["run_id"] != run_id:
            continue
        out[tuple(r[k] for k in KEY)] = r
    return out


def num(v):
    try:
        return float(v) if v not in ("", None) else None
    except ValueError:
        return None


def compare(base: dict[tuple, dict], head: dict[tuple, dict]) -> tuple[list[dict], dict]:
    """Per field: the worst absolute change, how many joined points fall outside
    the declared tolerance, and the worst violator (largest excess over its own
    tolerance). Tolerance is evaluated AT EACH POINT, not only at the worst
    absolute one -- a near-zero base value has a large relative change for a
    negligible absolute one, and the atol floors are what keep that honest."""
    shared = sorted(set(base) & set(head))
    out: list[dict] = []
    for field in FIELDS:
        n = n_only_base = n_only_head = n_outside = 0
        worst_abs = {"abs": 0.0, "rel": 0.0, "base": None, "head": None, "key": None}
        worst_bad = {"excess": 0.0, "abs": 0.0, "rel": 0.0, "base": None,
                     "head": None, "key": None}
        tol_floor = atol(field)
        for k in shared:
            b, h = num(base[k][field]), num(head[k][field])
            if b is None and h is None:
                continue
            if b is None or h is None:
                n_only_base += b is not None
                n_only_head += h is not None
                continue
            n += 1
            d = abs(h - b)
            rel = d / abs(b) if b else (float("inf") if d else 0.0)
            tol = max(tol_floor, RTOL * abs(b))
            if d > worst_abs["abs"]:
                worst_abs = {"abs": d, "rel": rel, "base": b, "head": h, "key": k}
            if d > tol:
                n_outside += 1
                if d / tol > worst_bad["excess"]:
                    worst_bad = {"excess": d / tol, "abs": d, "rel": rel,
                                 "base": b, "head": h, "key": k}
        out.append({"field": field, "n": n, "n_outside": n_outside,
                    "n_only_base": n_only_base, "n_only_head": n_only_head,
                    "ok": n_outside == 0, "worst_abs": worst_abs,
                    "worst_bad": worst_bad})
    meta = {
        "n_shared": len(shared),
        "n_base_only": len(set(base) - set(head)),
        "n_head_only": len(set(head) - set(base)),
    }
    return out, meta


def status_counts(rows: list[dict], run_id: str) -> dict:
    sel = [r for r in rows if r["run_id"] == run_id]
    return {"n": len(sel), "n_ok": sum(r["status"] == "ok" for r in sel),
            "n_failed": sum(r["status"] != "ok" for r in sel)}


def summary_groups(run_id: str) -> dict[tuple, float | None] | None:
    p = RESULTS_DIR / f"summary_{run_id}.json"
    if not p.is_file():
        return None
    s = json.loads(p.read_text())
    return {
        (g["scope"], g["corner"], g["temp_c"], g["age"], g["sel_row"]):
            g["worst_case_separation_v"]
        for g in s["groups"]
    }


def markdown(worst, meta, base_run, head_run, base_stat, head_stat, groups) -> str:
    L = [
        f"Base run `{base_run}` (open_pdks `{BASE_PIN[:7]}`): {base_stat['n']} rows, "
        f"{base_stat['n_failed']} sim_failed.",
        f"Head run `{head_run}` (open_pdks `{HEAD_PIN[:7]}`): {head_stat['n']} rows, "
        f"{head_stat['n_failed']} sim_failed.",
        f"Joined on {KEY}: {meta['n_shared']} shared points "
        f"({meta['n_base_only']} base-only, {meta['n_head_only']} head-only). "
        f"Tolerance: |head-base| <= max(atol, {RTOL:.0%} x |base|), atol "
        f"{ATOL_V:.0e} V / {ATOL_A:.0e} A / {ATOL_S:.0e} s.",
        "",
        "| Field | n | outside tol | worst abs delta | worst rel | base | head "
        "| at (corner/T/age/row/pattern) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for w in worst:
        a = w["worst_abs"]
        at = "/".join(str(x) for x in a["key"]) if a["key"] else "-"
        rel = "n/a" if a["abs"] == 0 else f"{a['rel']:.2e}"
        b = "" if a["base"] is None else f"{a['base']:+.6e}"
        h = "" if a["head"] is None else f"{a['head']:+.6e}"
        flag = f"**{w['n_outside']}**" if w["n_outside"] else "0"
        L.append(f"| `{w['field']}` | {w['n']} | {flag} | {a['abs']:.3e} | {rel} | "
                 f"{b} | {h} | {at} |")
    bad = [w for w in worst if w["n_outside"]]
    if bad:
        L += ["", "Worst tolerance violation per field (largest excess over that "
              "point's own tolerance):", "",
              "| Field | excess x tol | abs delta | rel | base | head | at |",
              "|---|---|---|---|---|---|---|"]
        for w in bad:
            v = w["worst_bad"]
            at = "/".join(str(x) for x in v["key"]) if v["key"] else "-"
            L.append(f"| `{w['field']}` | {v['excess']:.1f} | {v['abs']:.3e} | "
                     f"{v['rel']:.2e} | {v['base']:+.6e} | {v['head']:+.6e} | {at} |")
    missing = [w for w in worst if w["n_only_base"] or w["n_only_head"]]
    if missing:
        L += ["", "Points where only one run reported a value (an empty "
              "`latency_s` is the documented 'never crossed' result, not a failure):", ""]
        for w in missing:
            L.append(f"* `{w['field']}`: base-only {w['n_only_base']}, "
                     f"head-only {w['n_only_head']}")
    if groups:
        base_g, head_g = groups
        keys = sorted(set(base_g) & set(head_g))
        deltas = [(abs((head_g[k] or 0) - (base_g[k] or 0)), k) for k in keys
                  if base_g[k] is not None and head_g[k] is not None]
        deltas.sort(reverse=True)
        L += ["", f"Group worst-case separation (`analyze_loaded_column.py`), "
              f"{len(keys)} shared groups; largest changes:", "",
              "| scope/corner/T/age/row | base V | head V | delta V |", "|---|---|---|---|"]
        for d, k in deltas[:10]:
            L.append(f"| {'/'.join(str(x) for x in k)} | {base_g[k]:.6f} | "
                     f"{head_g[k]:.6f} | {head_g[k] - base_g[k]:+.2e} |")
    return "\n".join(L)


def compare_reports(path_a: str, path_b: str) -> int:
    """Measurement-by-measurement diff of two klt reports with the SAME deck and
    corner set. Used for the pin-attribution probe: two local runs that differ
    only in which open_pdks tree `$PDK_ROOT` resolved to. Prints Markdown and
    exits 0 when every shared measurement is bit-identical."""
    sys.path.insert(0, str(HERE.parent))
    from _evidence_common import load_json  # local import: stdlib-only module

    a, b = load_json(Path(path_a)), load_json(Path(path_b))

    def flat(rep):
        out = {}
        for c in rep.get("corners") or []:
            for m in c.get("measurements") or []:
                out[(c["process"], c["temperature_c"], m["name"])] = m.get("value")
        return out

    fa, fb = flat(a), flat(b)
    shared = sorted(set(fa) & set(fb), key=lambda k: (k[0], k[1], k[2]))
    same, diff, worst = 0, [], (0.0, None)
    for k in shared:
        x, y = fa[k], fb[k]
        if x is None or y is None:
            continue
        if x == y:
            same += 1
            continue
        d = abs(y - x) / max(abs(x), 1e-30)
        diff.append(k)
        if d > worst[0]:
            worst = (d, k, x, y)

    def pin(rep):
        return (rep.get("provenance", {}).get("pdk") or {}).get("version", "unknown")

    print(f"A `{Path(path_a).name}`: PDK {pin(a)}, ngspice "
          f"{a.get('environment', {}).get('engine_version')}")
    print(f"B `{Path(path_b).name}`: PDK {pin(b)}, ngspice "
          f"{b.get('environment', {}).get('engine_version')}")
    print(f"\n{len(shared)} shared measurements: **{same} bit-identical**, "
          f"{len(diff)} differ.")
    if diff:
        d, k, x, y = worst
        print(f"\nWorst: `{k[2]}` at {k[0]}/{k[1]} C -- {x!r} vs {y!r} "
              f"(rel {d:.3e}).")
        return 1
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results-csv", default=str(RESULTS_CSV))
    ap.add_argument("--base-run-id")
    ap.add_argument("--head-run-id")
    ap.add_argument("--compare-reports", nargs=2, metavar=("A", "B"),
                    help="diff two klt reports measurement-by-measurement instead "
                         "(the pin-attribution probe) and exit")
    a = ap.parse_args(argv)
    if a.compare_reports:
        return compare_reports(*a.compare_reports)
    rows = load(Path(a.results_csv))
    base_run = pick_run(rows, BASE_PIN, a.base_run_id)
    head_run = pick_run(rows, HEAD_PIN, a.head_run_id)
    if base_run == head_run:
        print("base and head resolve to the same run id", file=sys.stderr)
        return 2
    base, head = index(rows, base_run), index(rows, head_run)
    if not base or not head:
        print("one of the runs has no rows", file=sys.stderr)
        return 2
    worst, meta = compare(base, head)
    groups = None
    bg, hg = summary_groups(base_run), summary_groups(head_run)
    if bg and hg:
        groups = (bg, hg)
    print(markdown(worst, meta, base_run, head_run,
                   status_counts(rows, base_run), status_counts(rows, head_run), groups))
    bad = [w["field"] for w in worst if not w["ok"]]
    if bad:
        print(f"\nOUTSIDE TOLERANCE: {', '.join(bad)}", file=sys.stderr)
        return 1
    print("\nAll fields within the declared tolerance.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
