#!/usr/bin/env python3
"""check_extra_rules.py -- gate-level sky130 spacing/enclosure rules that
neither deck used in this repo checks (issue #100).

`klt drc --deck sky130` is a curated width/space/enclosure subset and the
open_pdks `sky130A_mr.drc` runset has no poly-to-diff spacing, gate endcap,
licon-to-gate spacing, licon spacing or licon enclosure rule. Compaction
moves exactly those dimensions, so this script re-checks them on the
drawn GDS with KLayout regions. Values are the public SkyWater sky130 design
rules (poly.4, poly.7, licon.2, licon.5, licon.8, licon.11, licon.14):

  poly.4   poly to unrelated diff spacing        >= 0.075
  poly.7   gate endcap past diff                  >= 0.13
  licon.2  licon spacing                          >= 0.17
  licon.5  diff enclosure of a diff licon         >= 0.04  (0.06 along y)
  licon.8  poly enclosure of a poly licon         >= 0.08 on an opposite pair
  licon.11 diff-licon to gate spacing             >= 0.055
  licon.14 poly-licon to diff spacing             >= 0.19

It does NOT check implant/npc/nsdm/psdm/well layers (not drawn, same
simplification as the committed mos_array layout) and is not a foundry
sign-off. Exit status 0 = no violations.

    python3 -I layout/compact/check_extra_rules.py GDS [--top CELL] [--json OUT]
"""
from __future__ import annotations

import argparse
import json
import sys

import klayout.db as db

U = 1000  # dbu per um


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("gds")
    ap.add_argument("--top")
    ap.add_argument("--json")
    a = ap.parse_args()
    ly = db.Layout()
    ly.read(a.gds)
    top = ly.cell(a.top) if a.top else ly.top_cell()

    def reg(l, d):
        i = ly.find_layer(l, d)
        return db.Region(top.begin_shapes_rec(i)).merged() if i is not None else db.Region()

    diff, poly, licon = reg(65, 20), reg(66, 20), reg(66, 44)
    tap = reg(65, 44)
    gate = poly & diff
    licon_tap = licon & tap          # substrate-tap licons: not subject to the gate rules
    licon_diff = (licon & diff) - licon_tap
    licon_poly = licon & poly
    stray = licon - licon_diff - licon_poly - licon_tap
    out = {}

    def count(name, r):
        out[name] = r if isinstance(r, int) else r.count()

    def sep(a, b, d):
        """separation violations, ignoring zero-distance (collinear / touching)
        edge pairs, which are not spacing violations."""
        return sum(1 for ep in a.separation_check(b, d).each() if ep.distance() > 0)

    count("licon.stray (licon on neither diff nor poly)", stray)
    # poly.4: field poly vs the S/D diffusion (channel excluded)
    count("poly.4 poly-diff spacing < 0.075", sep(poly - diff, diff - poly, 75))
    # poly.7: every gate must have >= 0.13 of poly past the diff at both ends
    nbad = 0
    for g in gate.each():
        bb = g.bbox()
        if bb.width() > bb.height():     # gate runs along x; endcaps left/right
            ends = (db.Box(bb.left - 130, bb.bottom, bb.left, bb.top),
                    db.Box(bb.right, bb.bottom, bb.right + 130, bb.top))
        else:
            ends = (db.Box(bb.left, bb.bottom - 130, bb.right, bb.bottom),
                    db.Box(bb.left, bb.top, bb.right, bb.top + 130))
        nbad += sum(1 for e in ends if not (db.Region(e) - poly).is_empty())
    out["poly.7 gate endcap < 0.13"] = nbad
    count("licon.2 licon spacing < 0.17", licon.space_check(170))
    count("licon.5 diff enclosure of licon < 0.04", licon_diff.sized(40) - diff)
    count("licon.5c diff end enclosure (y) < 0.06", licon_diff.sized(0, 60, 2) - diff)
    # licon.8: poly licon enclosed >= 0.08 on both left/right or both top/bottom
    bad8 = 0
    for p in licon_poly.each():
        r = db.Region(p)
        if not (r.sized(80, 0, 2) - poly).is_empty() and not (r.sized(0, 80, 2) - poly).is_empty():
            bad8 += 1
    out["licon.8 poly enclosure of poly licon < 0.08 (opposite pair)"] = bad8
    count("licon.11 diff-licon to gate spacing < 0.055", sep(licon_diff, gate, 55))
    count("licon.14 poly-licon to diff spacing < 0.19", sep(licon_poly, diff, 190))
    total = sum(out.values())
    for k, v in out.items():
        print(f"{'FAIL' if v else 'ok  '} {k}: {v}")
    print(f"{'FAIL' if total else 'PASS'}: {total} violation(s)")
    if a.json:
        with open(a.json, "w") as fh:
            json.dump({"gds": a.gds, "violations": out, "total": total}, fh, indent=2)
            fh.write("\n")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
