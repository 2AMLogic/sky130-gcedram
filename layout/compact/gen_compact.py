#!/usr/bin/env python3
"""gen_compact.py -- reproducible hand-parametrised layout of the ratified 2T
gain cell in compacted forms (issue #100, bitcell-compaction research).

Why this exists: `klt gen mos_array` places identical, fully isolated unit
devices on a uniform grid and exposes no pitch / diffusion-sharing knob (see
layout/compact/README.md), so no `klt gen` parameter set can compact the
committed 4x4 array. These variants are generated *from this script* with
KLayout's Python API (`klayout.db`), so every committed GDS is reproducible
from source (no hand-drawn GDS).

Topology is unchanged: two `sky130_fd_pr__nfet_01v8`, W=0.42 um, L=0.15 um,
M_WR (gate=WL, source=BL, drain=SN) and M_RD (gate=SN, drain=RBL,
source=RWL). Only drawn geometry changes.

The dimension set is the public sky130 design-rule set (SkyWater sky130 DRM /
open_pdks `sky130A_mr.drc`), restated in `RULES` below. Layers are the same
ones the committed array already uses (diff 65/20, tap 65/44, poly 66/20,
licon 66/44, li1 67/20, mcon 67/44, met1 68/20, via 68/44, met2 69/20).
Like the committed `mos_array` layout, no implant/npc/nsdm layers are drawn
(the klt sky130 deck recognises an nfet from diff x poly); that simplification
is shared with the baseline so the comparison is like for like.

Usage:
    python3 -I layout/compact/gen_compact.py --variant v1 --out DIR
        writes DIR/gain_cell_2t_<variant>_array.gds (+ .layout.json,
        _mos.json, .lvs.request.json, .lvs_reference.spice)

Stdlib + klayout only. Run with a venv that has klayout==0.30.12
(the pinned generation/check toolchain venvs both qualify).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import klayout.db as db

# --- public sky130 rules / dimensions used (um) -----------------------------
W = 0.42            # nfet width (ratified)
L = 0.15            # nfet length (ratified)
LICON = 0.17
MCON = 0.17
VIA1 = 0.15
EXT = 0.285         # diff beyond gate edge: 0.055 licon-gate + 0.17 licon + 0.06 enc
GATE_GAP = 0.28     # gate-to-gate diff run holding one shared licon (0.055*2+0.17)
DIFF_SPACE = 0.27
ENDCAP = 0.13       # poly past diff
POLY_SPACE = 0.21
POLY_DIFF = 0.075
POLYLICON_DIFF = 0.19  # poly-contact licon edge to diff (licon.14)
LI_PAD = 0.33       # li1 pad over a licon: 0.08 enclosure all round
LI_SPACE = 0.17
POLY_PAD = 0.33     # poly landing pad for a licon on poly: 0.08 enclosure
M1_PAD = 0.29       # met1 over mcon / via: >= met1 area 0.083
M1_W = 0.17
M2_W = 0.26         # met2 wire wide enough to enclose a via by 0.055
M2_END = 0.16       # met2 end past a via centre: 0.075 half-via + 0.085 (m2.5)
TAP_RING_PAD = 0.5  # same ring clearance as the committed mos_array ring

LAYERS = {
    "diff": (65, 20), "tap": (65, 44), "poly": (66, 20), "licon": (66, 44),
    "li1": (67, 20), "mcon": (67, 44), "met1": (68, 20), "via": (68, 44),
    "met2": (69, 20),
    "poly_lbl": (66, 5), "li1_lbl": (67, 5), "met1_lbl": (68, 5),
    "met2_lbl": (69, 5),
}


def nm(v: float) -> int:
    return int(round(v * 1000))


class Builder:
    def __init__(self, name: str):
        self.ly = db.Layout()
        self.ly.dbu = 0.001
        self.top = self.ly.create_cell(name)
        self.li = {k: self.ly.layer(*v) for k, v in LAYERS.items()}

    def rect(self, layer: str, x0: float, y0: float, x1: float, y1: float):
        self.top.shapes(self.li[layer]).insert(
            db.Box(nm(x0), nm(y0), nm(x1), nm(y1)))

    def sq(self, layer: str, cx: float, cy: float, s: float):
        h = s / 2
        self.rect(layer, cx - h, cy - h, cx + h, cy + h)

    def lipad(self, cx: float, cy: float, vertical: bool = False):
        """li1 pad over a licon. sky130 li.5 fails any corner where two
        ADJACENT edges both enclose the licon by < 0.08, so the pad is
        enclosed by 0.08 on an OPPOSITE pair of edges (left/right, or
        top/bottom when `vertical`) and 0 on the other pair: 0.33 x 0.17 um,
        area 0.0561 = the li.6 minimum."""
        h = LICON / 2
        dx, dy = (0.0, 0.08) if vertical else (0.08, 0.0)
        self.rect("li1", cx - h - dx, cy - h - dy, cx + h + dx, cy + h + dy)

    def via_pad(self, cx: float, cy: float):
        """met1 pad under a 0.15 via: 0.085 left/right (via.5a opposite
        pair), 0.055 top/bottom (via.4a); 0.32 x 0.26 = 0.0832 >= m1.6."""
        self.rect("met1", cx - 0.16, cy - 0.13, cx + 0.16, cy + 0.13)

    def text(self, layer: str, s: str, x: float, y: float):
        self.top.shapes(self.li[layer]).insert(db.Text(s, nm(x), nm(y)))


# --- variant geometry -------------------------------------------------------
class V1:
    """Stacked, unshared: WR and RD each get their own isolated vertical
    diffusion in one column, RD below WR. Word line is one continuous poly
    line per row (crosses only WR diffusion); the RD gate is a short poly
    stub with a landing pad beside the column. Row pitch = two isolated
    devices + two diff spaces; column pitch set by the poly-pad / endcap /
    li1 clearances."""
    name = "v1"
    X = 0.985
    DEV = EXT + L + EXT                       # 0.72 isolated device diff length
    Y = DEV + DIFF_SPACE + DEV + DIFF_SPACE   # 1.98

    @classmethod
    def build(cls, b: Builder, rows: int, cols: int):
        X, Y, DEV = cls.X, cls.Y, cls.DEV
        for r in range(rows):
            ry = r * Y
            yw = ry + DEV + DIFF_SPACE              # WR diff bottom
            for c in range(cols):
                cx = c * X
                xm = cx + W / 2
                # --- RD device (bottom): RBL end at bottom, RWL end at top
                b.rect("diff", cx, ry, cx + W, ry + DEV)
                gy0, gy1 = ry + EXT, ry + EXT + L
                rbl_y = ry + EXT - 0.055 - LICON / 2
                rwl_y = ry + DEV - EXT + 0.055 + LICON / 2
                # gate strip to the right, then pad above it
                sx1 = cx + W + POLY_DIFF + L          # 0.645
                b.rect("poly", cx - ENDCAP, gy0, sx1, gy1)
                px0 = sx1 - L                                  # riser, flush with strip end
                py0 = gy1 + POLY_SPACE
                b.rect("poly", px0, gy0, px0 + L, py0)                   # riser
                pcx = cx + W + POLYLICON_DIFF + LICON / 2         # licon.14
                pcy = py0 + POLY_PAD / 2
                b.rect("poly", px0, py0, pcx + POLY_PAD / 2, py0 + POLY_PAD)  # pad (flush with riser)
                b.sq("licon", pcx, pcy, LICON)
                b.lipad(pcx, pcy, vertical=True)
                # --- WR device (top): SN end at bottom, BL end at top
                b.rect("diff", cx, yw, cx + W, yw + DEV)
                sn_y = yw + EXT - 0.055 - LICON / 2
                bl_y = yw + DEV - EXT + 0.055 + LICON / 2
                # --- contacts on diffusion
                for yy in (rbl_y, rwl_y, sn_y, bl_y):
                    b.sq("licon", xm, yy, LICON)
                    b.lipad(xm, yy)
                # --- SN link: SN pad -> right -> down to the RD poly pad
                lane_x = pcx
                # lane is exactly as wide as the poly-pad li1 (one merged polygon)
                b.rect("li1", xm - LICON / 2 - 0.08, sn_y - 0.085,
                       lane_x + 0.085, sn_y + 0.085)
                b.rect("li1", lane_x - 0.085, pcy, lane_x + 0.085, sn_y + 0.085)
                # --- RWL (met1 line across the row) at RD top contact
                b.sq("mcon", xm, rwl_y, MCON)
                b.sq("met1", xm, rwl_y, M1_PAD)
                # --- RBL: mcon, met1 jog to x_rbl, via, met2 column wire
                x_rbl = cx + 0.66
                b.sq("mcon", xm, rbl_y, MCON)
                b.rect("met1", xm - M1_PAD / 2, rbl_y - M1_W / 2,
                       x_rbl + M1_PAD / 2, rbl_y + M1_W / 2)
                b.via_pad(x_rbl, rbl_y)
                b.sq("met1", xm, rbl_y, M1_PAD)
                b.sq("via", x_rbl, rbl_y, VIA1)
                # --- BL: mcon, met1 pad, via, met2 column wire
                b.sq("mcon", xm, bl_y, MCON)
                b.via_pad(xm, bl_y)
                b.sq("via", xm, bl_y, VIA1)
            # --- row lines
            gx1 = (cols - 1) * X + W + ENDCAP
            wl_y0 = yw + EXT
            b.rect("poly", -ENDCAP, wl_y0, gx1, wl_y0 + L)       # WL
            rwl_y = ry + DEV - EXT + 0.055 + LICON / 2
            b.rect("met1", -M1_PAD / 2, rwl_y - M1_W / 2,
                   (cols - 1) * X + W / 2 + M1_PAD / 2, rwl_y + M1_W / 2)
            b.text("poly_lbl", f"wl_{r}", -ENDCAP + 0.02, wl_y0 + L / 2)
            b.text("met1_lbl", f"rwl_{r}", 0.0, rwl_y)
        # --- column wires on met2
        # each wire spans its first..last via centre +- M2_END (0.085 end enclosure + 0.075 half via)
        bl_y = lambda r: r * Y + DEV + DIFF_SPACE + DEV - EXT + 0.055 + LICON / 2
        rbl_y = lambda r: r * Y + EXT - 0.055 - LICON / 2
        for c in range(cols):
            cx = c * X
            bl_x, rbl_x = cx + W / 2, cx + 0.66
            b.rect("met2", bl_x - M2_W / 2, bl_y(0) - M2_END, bl_x + M2_W / 2, bl_y(rows - 1) + M2_END)
            b.rect("met2", rbl_x - M2_W / 2, rbl_y(0) - M2_END, rbl_x + M2_W / 2, rbl_y(rows - 1) + M2_END)
            b.text("met2_lbl", f"bl_{c}", bl_x, bl_y(rows - 1))
            b.text("met2_lbl", f"rbl_{c}", rbl_x, rbl_y(rows - 1))

    @classmethod
    def device_ports(cls, rows: int, cols: int):
        """Reference points per device (um), following the `U<idx>_S`
        naming of layout/gain_cell_2t_array_mos.json so area_density.py can
        derive the pitch: the BL (source) licon of M_WR."""
        out = []
        per_row = 2 * cols
        for r in range(rows):
            yw = r * cls.Y + cls.DEV + DIFF_SPACE
            for c in range(cols):
                x = c * cls.X + W / 2
                yb = yw + cls.DEV - EXT + 0.055 + LICON / 2
                out.append({"name": f"U{r * per_row + 2 * c}_S",
                            "x_um": round(x, 6), "y_um": round(yb, 6)})
        return out


class V2:
    """V1 plus vertical diffusion sharing. Rows are taken in pairs: the two
    M_WR of a row pair share ONE bit-line contact (WR pair: SN | WL | BL |
    WL | SN) and the two M_RD that sit between two WR pairs share ONE read
    bit-line contact (RD pair: RWL | gate | RBL | gate | RWL). Stack, bottom
    to top, for 4 rows: RD(row0) WR(rows0,1) RD(rows1,2) WR(rows2,3)
    RD(row3). Every RD gate faces the WR end that holds its storage node, so
    each SN link is a short li1 jog and the two RD poly pads of a pair point
    away from each other. Periodic pitch: one 2-row period is
    WR pair + RD pair + 2 diff spaces = 2.84 um = 2 x 1.42."""
    name = "v2"
    X = 0.985
    PAIR = EXT + L + GATE_GAP + L + EXT            # 1.15 shared-contact diff run
    DEV = EXT + L + EXT                            # 0.72 isolated device
    PERIOD = PAIR + DIFF_SPACE + PAIR + DIFF_SPACE  # 2 rows
    Y = PERIOD / 2

    @classmethod
    def plan(cls, rows: int):
        """Bottom-to-top stack of diffusion runs: (kind, y0, gate_rows)."""
        assert rows % 2 == 0 and rows >= 2, "V2 needs an even row count"
        stack, y = [], 0.0
        stack.append(("rd1_up", y, [0])); y += cls.DEV + DIFF_SPACE
        for k in range(rows // 2):
            stack.append(("wr2", y, [2 * k, 2 * k + 1])); y += cls.PAIR + DIFF_SPACE
            if k < rows // 2 - 1:
                stack.append(("rd2", y, [2 * k + 1, 2 * k + 2]))
                y += cls.PAIR + DIFF_SPACE
        stack.append(("rd1_dn", y, [rows - 1]))
        return stack, y + cls.DEV

    @classmethod
    def build(cls, b: Builder, rows: int, cols: int):
        X = cls.X
        stack, ytop = cls.plan(rows)
        sn_of_row = {}      # row -> y of the WR SN licon centre
        wl_y, rwl_y = {}, {}
        bl_pts, rbl_pts = [], []
        # first pass: WR runs (SN licon heights, WL gate heights, BL contact)
        for kind, y0, gate_rows in stack:
            if kind != "wr2":
                continue
            lo, hi = gate_rows
            sn_of_row[lo] = y0 + EXT - 0.055 - LICON / 2
            sn_of_row[hi] = y0 + cls.PAIR - EXT + 0.055 + LICON / 2
            wl_y[lo], wl_y[hi] = y0 + EXT, y0 + EXT + L + GATE_GAP
            bl_pts.append(y0 + EXT + L + GATE_GAP / 2)
        for c in range(cols):
            cx = c * X
            xm = cx + W / 2
            x_rbl = cx + 0.66
            for kind, y0, gate_rows in stack:
                if kind == "wr2":
                    b.rect("diff", cx, y0, cx + W, y0 + cls.PAIR)
                    for r in gate_rows:
                        b.sq("licon", xm, sn_of_row[r], LICON)
                        b.lipad(xm, sn_of_row[r])
                    yb = y0 + EXT + L + GATE_GAP / 2
                    b.sq("licon", xm, yb, LICON); b.lipad(xm, yb)
                    b.sq("mcon", xm, yb, MCON); b.via_pad(xm, yb)
                    b.sq("via", xm, yb, VIA1)
                    continue
                n = 2 if kind == "rd2" else 1
                length = cls.PAIR if n == 2 else cls.DEV
                b.rect("diff", cx, y0, cx + W, y0 + length)
                # gate rows, bottom to top; pad points toward the row's WR
                gates = []
                if n == 2:
                    gates = [(gate_rows[0], y0 + EXT, -1),
                             (gate_rows[1], y0 + EXT + L + GATE_GAP, +1)]
                    contacts = [(y0 + EXT - 0.055 - LICON / 2, "rwl", gate_rows[0]),
                                (y0 + EXT + L + GATE_GAP / 2, "rbl", None),
                                (y0 + length - EXT + 0.055 + LICON / 2, "rwl", gate_rows[1])]
                elif kind == "rd1_up":      # bottom edge of the stack: WR above
                    gates = [(gate_rows[0], y0 + EXT, +1)]
                    contacts = [(y0 + EXT - 0.055 - LICON / 2, "rbl", None),
                                (y0 + length - EXT + 0.055 + LICON / 2, "rwl", gate_rows[0])]
                else:                       # rd1_dn: top edge of the stack, WR below
                    gates = [(gate_rows[0], y0 + EXT, -1)]
                    contacts = [(y0 + EXT - 0.055 - LICON / 2, "rwl", gate_rows[0]),
                                (y0 + length - EXT + 0.055 + LICON / 2, "rbl", None)]
                for (row, gy0, d) in gates:
                    gy1 = gy0 + L
                    sx1 = cx + W + POLY_DIFF + L
                    b.rect("poly", cx - ENDCAP, gy0, sx1, gy1)
                    px0 = sx1 - L
                    if d > 0:
                        py0 = gy1 + POLY_SPACE
                        b.rect("poly", px0, gy0, px0 + L, py0)
                    else:
                        py0 = gy0 - POLY_SPACE - POLY_PAD
                        b.rect("poly", px0, py0 + POLY_PAD, px0 + L, gy1)
                    pcx = cx + W + POLYLICON_DIFF + LICON / 2     # licon.14
                    pcy = py0 + POLY_PAD / 2
                    b.rect("poly", px0, py0, pcx + POLY_PAD / 2, py0 + POLY_PAD)   # pad (flush with riser)
                    b.sq("licon", pcx, pcy, LICON)
                    b.lipad(pcx, pcy, vertical=True)
                    sny = sn_of_row[row]
                    b.rect("li1", xm - LICON / 2 - 0.08, sny - 0.085,
                           pcx + 0.085, sny + 0.085)
                    lo_, hi_ = sorted((pcy, sny))
                    b.rect("li1", pcx - 0.085, lo_, pcx + 0.085, hi_ + 0.085)
                for (yy, net, row) in contacts:
                    b.sq("licon", xm, yy, LICON)
                    b.lipad(xm, yy)
                    b.sq("mcon", xm, yy, MCON)
                    if net == "rwl":
                        b.sq("met1", xm, yy, M1_PAD)
                        rwl_y[row] = yy
                    else:
                        b.rect("met1", xm - M1_PAD / 2, yy - M1_W / 2,
                               x_rbl + M1_PAD / 2, yy + M1_W / 2)
                        b.via_pad(x_rbl, yy)
                        b.sq("met1", xm, yy, M1_PAD)
                        b.sq("via", x_rbl, yy, VIA1)
                        if c == 0:
                            rbl_pts.append(yy)
        # --- row lines
        gx1 = (cols - 1) * X + W + ENDCAP
        for r in range(rows):
            b.rect("poly", -ENDCAP, wl_y[r], gx1, wl_y[r] + L)
            b.rect("met1", -M1_PAD / 2, rwl_y[r] - M1_W / 2,
                   (cols - 1) * X + W / 2 + M1_PAD / 2, rwl_y[r] + M1_W / 2)
            b.text("poly_lbl", f"wl_{r}", -ENDCAP + 0.02, wl_y[r] + L / 2)
            b.text("met1_lbl", f"rwl_{r}", 0.0, rwl_y[r])
        for c in range(cols):
            cx = c * X
            bl_x, rbl_x = cx + W / 2, cx + 0.66
            b.rect("met2", bl_x - M2_W / 2, min(bl_pts) - M2_END,
                   bl_x + M2_W / 2, max(bl_pts) + M2_END)
            b.rect("met2", rbl_x - M2_W / 2, min(rbl_pts) - M2_END,
                   rbl_x + M2_W / 2, max(rbl_pts) + M2_END)
            b.text("met2_lbl", f"bl_{c}", bl_x, max(bl_pts))
            b.text("met2_lbl", f"rbl_{c}", rbl_x, max(rbl_pts))

    @classmethod
    def device_ports(cls, rows: int, cols: int):
        """Nominal per-cell reference points on the periodic 2-row grid
        (mirrored pairs share contacts, so no single licon repeats at a
        uniform row stride): (c*X, r*Y). See 'cell_pitch_um'."""
        out, per_row = [], 2 * cols
        for r in range(rows):
            for c in range(cols):
                out.append({"name": f"U{r * per_row + 2 * c}_S",
                            "x_um": round(c * cls.X, 6), "y_um": round(r * cls.Y, 6)})
        return out


VARIANTS = {"v1": V1, "v2": V2}


def add_tap_ring(b: Builder, bbox, label="GND"):
    """Substrate tap ring around the array, drawn directly (same style as the
    klt guard_ring: 0.42 tap ring on diff-tap 65/44 + licon + li1 ring)."""
    x0, y0, x1, y1 = bbox
    pad, rw = TAP_RING_PAD, 0.42
    ix0, iy0, ix1, iy1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
    ox0, oy0, ox1, oy1 = ix0 - rw, iy0 - rw, ix1 + rw, iy1 + rw
    strips = [(ox0, oy0, ox1, iy0), (ox0, iy1, ox1, oy1),
              (ox0, iy0, ix0, iy1), (ix1, iy0, ox1, iy1)]
    for s in strips:
        b.rect("tap", *s)
        b.rect("li1", *s)
    # licons along each strip centre line, pitch 0.34
    def line(xa, ya, xb, yb):
        n = int(max(abs(xb - xa), abs(yb - ya)) / 0.34)
        for i in range(n + 1):
            t = i / max(n, 1)
            gx = round((xa + (xb - xa) * t) / 0.005) * 0.005
            gy = round((ya + (yb - ya) * t) / 0.005) * 0.005
            b.sq("licon", gx, gy, LICON)
    cy = rw / 2
    line(ox0 + cy, oy0 + cy, ox1 - cy, oy0 + cy)
    line(ox0 + cy, oy1 - cy, ox1 - cy, oy1 - cy)
    line(ox0 + cy, oy0 + cy, ox0 + cy, oy1 - cy)
    line(ox1 - cy, oy0 + cy, ox1 - cy, oy1 - cy)
    b.text("li1_lbl", label, ox0 + cy, (oy0 + oy1) / 2)
    return (ox0, oy0, ox1, oy1)


def lvs_reference(rows: int, cols: int, top: str) -> str:
    pins = ([f"wl_{r}" for r in range(rows)] + [f"rwl_{r}" for r in range(rows)]
            + [f"bl_{c}" for c in range(cols)] + [f"rbl_{c}" for c in range(cols)])
    lines = [f"* GENERATED by layout/compact/gen_compact.py ({rows}x{cols}); "
             "same device set as layout/gain_cell_2t_array.lvs_reference.spice",
             f".SUBCKT {top} " + " ".join(pins)]
    for r in range(rows):
        for c in range(cols):
            lines.append(f"M_WR_{r}_{c} sn_{r}_{c} wl_{r} bl_{c} GND nfet L=0.15U W=0.42U")
            lines.append(f"M_RD_{r}_{c} rbl_{c} sn_{r}_{c} rwl_{r} GND nfet L=0.15U W=0.42U")
    lines.append(f".ENDS {top}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--variant", required=True, choices=sorted(VARIANTS))
    ap.add_argument("--rows", type=int, default=4)
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--no-ring", action="store_true")
    a = ap.parse_args()
    V = VARIANTS[a.variant]
    stem = f"gain_cell_2t_{a.variant}_array"
    top = f"{stem}_{a.rows}x{a.cols}_layout_0"
    b = Builder(top)
    V.build(b, a.rows, a.cols)
    core = b.top.bbox()
    core_um = (core.left / 1000, core.bottom / 1000, core.right / 1000, core.top / 1000)
    if not a.no_ring:
        add_tap_ring(b, core_um)
    bb = b.top.bbox()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    opts = db.SaveLayoutOptions()          # byte-reproducible: no write date
    opts.format = "GDS2"
    opts.gds2_write_timestamps = False
    b.ly.write(str(out / f"{stem}.gds"), opts)
    bbox = {"x0": bb.left / 1000, "y0": bb.bottom / 1000,
            "x1": bb.right / 1000, "y1": bb.top / 1000}
    (out / f"{stem}.layout.json").write_text(json.dumps({
        "schema_version": 1, "generator": "layout/compact/gen_compact.py",
        "variant": a.variant, "cell_name": top, "gds_path": f"{stem}.gds",
        "pdk": {"name": "sky130A", "variant": "sky130A"},
        "bbox_um": bbox, "core_bbox_um": dict(zip(("x0", "y0", "x1", "y1"), core_um)),
        "ring": not a.no_ring,
    }, indent=2) + "\n")
    (out / f"{stem}_mos.json").write_text(json.dumps({
        "schema_version": 1, "generator": "layout/compact/gen_compact.py",
        "device_count": 2 * a.rows * a.cols,
        "cell_pitch_um": {"x": V.X, "y": round(V.Y, 6),
                          "basis": V.__doc__.split("\n")[0].strip()},
        "ports": V.device_ports(a.rows, a.cols),
    }, indent=2) + "\n")
    (out / f"{stem}.lvs_reference.spice").write_text(
        lvs_reference(a.rows, a.cols, f"{stem}_{a.rows}x{a.cols}"))
    (out / f"{stem}.lvs.request.json").write_text(json.dumps({
        "layout": {"file": f"{stem}.gds", "deck": "sky130", "top": top},
        "reference": {"netlist": f"{stem}.lvs_reference.spice",
                      "top": f"{stem}_{a.rows}x{a.cols}"},
    }, indent=2) + "\n")
    print(f"wrote {out / (stem + '.gds')}  bbox {bbox['x1']-bbox['x0']:.3f} x "
          f"{bbox['y1']-bbox['y0']:.3f} um")
    return 0


if __name__ == "__main__":
    sys.exit(main())
