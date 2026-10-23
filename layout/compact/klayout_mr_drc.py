#!/usr/bin/env python3
"""klayout_mr_drc.py -- run the `sky130A_mr.drc` KLayout runset that ships
with the pinned PDK (libs.tech/klayout/drc) over a GDS and summarise its
report (issue #100). Stricter than `klt drc --deck sky130` (a curated subset)
on li1/met1/met2/via enclosure and grid rules; like it, it has no gate-level
rules (those are covered by check_extra_rules.py and magic_drc.py).

    python3 -I layout/compact/klayout_mr_drc.py GDS TOPCELL [--json OUT]

Needs the `klayout` binary on PATH and PDK_ROOT/PDK. At most 2 threads.
Exit 0 = zero violations.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("gds")
    ap.add_argument("top")
    ap.add_argument("--json")
    a = ap.parse_args()
    pdk_root, pdk = os.environ.get("PDK_ROOT"), os.environ.get("PDK", "sky130A")
    if not pdk_root:
        print("FAIL: PDK_ROOT not set (source design/env.sh)", file=sys.stderr)
        return 2
    deck = Path(pdk_root) / pdk / "libs.tech/klayout/drc" / f"{pdk}_mr.drc"
    with tempfile.TemporaryDirectory() as td:
        rep = Path(td, "report.lyrdb")
        proc = subprocess.run(
            ["klayout", "-b", "-rd", f"input={Path(a.gds).resolve()}", "-rd", f"top_cell={a.top}",
             "-rd", f"report={rep}", "-rd", "thr=2", "-rd", "feol=true", "-rd", "beol=true",
             "-rd", "offgrid=true", "-r", str(deck)],
            capture_output=True, text=True, timeout=600)
        if proc.returncode != 0 or not rep.exists():
            print(proc.stdout[-1500:], proc.stderr[-1500:], file=sys.stderr)
            print("FAIL: klayout DRC did not complete", file=sys.stderr)
            return 2
        items = ET.parse(rep).getroot().find("items")
        counts = collections.Counter(it.find("category").text.strip("'") for it in (items or []))
    total = sum(counts.values())
    for k, v in sorted(counts.items()):
        print(f"FAIL {k}: {v}")
    print(f"{'FAIL' if total else 'PASS'}: {total} {deck.name} violation(s)")
    if a.json:
        Path(a.json).write_text(json.dumps({
            "tool": f"klayout -b -r {deck.name} (feol, beol, offgrid enabled)",
            "gds": os.path.basename(a.gds), "top": a.top,
            "rules_fired": dict(counts), "total": total}, indent=2) + "\n")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
