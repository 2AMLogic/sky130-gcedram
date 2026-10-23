#!/usr/bin/env python3
"""magic_drc.py -- run the sky130A `drc(full)` ruleset of the PDK's own magic
tech file over a drawn GDS (issue #100).

Why: `klt drc --deck sky130` is a curated width/space/enclosure subset and the
`sky130A_mr.drc` KLayout runset has no gate-level rules (poly-to-diff spacing,
gate endcap, S/D overhang, licon-to-gate...). The tech file shipped with the
pinned PDK (libs.tech/magic/sky130A.tech) does, so it is the strongest public
DRC reference available from a stock open_pdks install.

The GDS under test (like the committed `mos_array` layout) draws no
implant/npc layers, which magic needs to classify diffusion as n-type. A
CHECK-ONLY flattened copy gets synthetic nsdm (diff +0.125), psdm (tap +0.125)
and npc (poly licon +0.1) shapes before the run; the file under test is never
modified. Rules that exist only because of that synthetic implant geometry
are not expected; any rule that fires is reported verbatim.

    python3 -I layout/compact/magic_drc.py GDS TOPCELL [--json OUT]

Needs `magic` on PATH, PDK_ROOT and PDK=sky130A, and a Python with klayout.
Exit 0 = zero DRC errors.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import klayout.db as db

TCL = """\
drc off
gds readonly true
gds rescale false
gds read {gds}
load {top}
select top cell
expand
drc style drc(full)
drc on
drc catchup
puts "DRC_TOTAL [drc listall count]"
foreach {{why boxes}} [drc listall why] {{ puts "DRC_WHY [llength $boxes] :: $why" }}
quit -noprompt
"""


def add_check_implants(src: str, dst: str, top: str) -> None:
    ly = db.Layout()
    ly.read(src)
    c = ly.cell(top)
    c.flatten(True)

    def reg(l, d):
        i = ly.find_layer(l, d)
        return db.Region(c.begin_shapes_rec(i)).merged() if i is not None else db.Region()

    diff, tap, poly, licon = reg(65, 20), reg(65, 44), reg(66, 20), reg(66, 44)
    for (l, d), r in (((93, 44), diff.sized(125, 125, 2).merged()),           # nsdm
                      ((94, 20), tap.sized(125, 125, 2).merged()),            # psdm
                      ((95, 20), (licon & poly).sized(100, 100, 2).merged())):  # npc
        c.shapes(ly.layer(l, d)).insert(r)
    ly.write(dst)


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
    rc = Path(pdk_root) / pdk / "libs.tech/magic" / f"{pdk}.magicrc"
    with tempfile.TemporaryDirectory() as td:
        chk, tcl = Path(td, "check.gds"), Path(td, "drc.tcl")
        add_check_implants(a.gds, str(chk), a.top)
        tcl.write_text(TCL.format(gds=chk, top=a.top))
        proc = subprocess.run(
            ["magic", "-dnull", "-noconsole", "-T", pdk, "-rcfile", str(rc), str(tcl)],
            capture_output=True, text=True, timeout=600)
    out = proc.stdout + proc.stderr
    rules = {}
    for m in re.finditer(r"^DRC_WHY (\d+) :: (.*)$", out, re.M):
        rules[m.group(2).strip()] = int(m.group(1))
    if "DRC_TOTAL" not in out:
        print(out[-2000:], file=sys.stderr)
        print("FAIL: magic did not complete", file=sys.stderr)
        return 2
    total = sum(rules.values())
    for k, v in sorted(rules.items()):
        print(f"FAIL {k}: {v}")
    print(f"{'FAIL' if total else 'PASS'}: {total} magic drc(full) violation(s)")
    if a.json:
        Path(a.json).write_text(json.dumps({
            "tool": "magic drc(full), sky130A tech file from the pinned PDK",
            "gds": os.path.basename(a.gds), "top": a.top,
            "check_only_synthetic_layers": ["nsdm 93/44 = diff+0.125", "psdm 94/20 = tap+0.125",
                                            "npc 95/20 = poly licon+0.1"],
            "rules_fired": rules, "total": total}, indent=2) + "\n")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
