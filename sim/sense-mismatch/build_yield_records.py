#!/usr/bin/env python3
"""Derive a `klt yield-threshold` records document from a stage-deck `klt sim` Monte Carlo report (issue #384).

Stdlib only. Reads a committed ``results/klt_report_row2e_<RUN_ID>.json[.gz]``
(the stage-only deck of this study, any run that used its measurement set) and
writes a NEW records document next to it (never overwrites; refuses if it
exists):

``results/yield_records_row2e_<RUN_ID>.json`` -- ``{"records": [...]}`` with
one record per non-null ``dend`` sample value:

* ``corner``: the sample's corner id with klt's ``/mc<i>`` suffix stripped
  (the pre-sampling corner, as ``klt yield`` itself reports it);
* ``stimulus``: the instance's nominal input differential in V, decoded from
  the measurement name (``dend_sp150_3`` -> +0.150; ``sm050`` -> -0.050);
* ``value``: the measured final differential (V).

``klt yield-threshold --threshold 0`` then derives the binary outcome
(decided '0' = value > 0) and fits the probit offset model per corner --
the same reduction ``analyze_sense_mismatch.py`` performs locally, run by the
pinned tool instead. This script invents no numbers: it re-formats committed
report values 1:1 and skips (and counts) samples whose value is null.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"

MEAS_RE = re.compile(r"^dend_s(?P<sign>[zpm])(?P<mv>\d{3})_(?P<rep>\d)$")


def stimulus_v(name: str) -> float | None:
    mo = MEAS_RE.match(name)
    if not mo:
        return None
    mv = int(mo.group("mv"))
    if mo.group("sign") == "z":
        return 0.0
    return mv * 1e-3 if mo.group("sign") == "p" else -mv * 1e-3


def load_report(path: Path) -> dict:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt") as fh:  # type: ignore[operator]
        return json.load(fh)


def build_records(report: dict) -> tuple[list[dict], int, dict[str, int]]:
    records: list[dict] = []
    skipped = 0
    per_corner: dict[str, int] = {}
    for corner in report.get("corners", []):
        base = corner["corner_id"].rsplit("/mc", 1)[0]
        for meas in corner.get("measurements", []):
            s = stimulus_v(meas.get("name", ""))
            if s is None:
                continue
            v = meas.get("value")
            if v is None:
                skipped += 1
                continue
            records.append({"corner": base, "stimulus": s, "value": v})
            per_corner[base] = per_corner.get(base, 0) + 1
    return records, skipped, per_corner


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("report", nargs="?", help="klt sim report (json or json.gz); default: newest klt_report_row2e_*.json*")
    ap.add_argument("out", nargs="?", help="output records document; default: yield_records_row2e_<RUN_ID>.json next to the report")
    args = ap.parse_args(argv)

    report_path = Path(args.report) if args.report else max(RESULTS.glob("klt_report_row2e_*.json*"))
    if not report_path.is_file():
        print(f"error: report not found: {report_path}", file=sys.stderr)
        return 1
    stem = report_path.name.removesuffix(".gz").removesuffix(".json")
    run_id = stem.split("klt_report_", 1)[1]
    out_path = Path(args.out) if args.out else RESULTS / f"yield_records_{run_id}.json"
    if out_path.exists():
        print(f"error: refusing to overwrite {out_path}", file=sys.stderr)
        return 1

    report = load_report(report_path)
    records, skipped, per_corner = build_records(report)
    if not records:
        print("error: no dend records derived", file=sys.stderr)
        return 1
    out_path.write_text(json.dumps({"records": records}) + "\n")
    print(f"wrote {out_path} ({len(records)} records, {skipped} null values skipped)")
    for corner in sorted(per_corner):
        print(f"  {corner}: {per_corner[corner]} records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
