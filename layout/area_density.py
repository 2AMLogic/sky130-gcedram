#!/usr/bin/env python3
"""area_density.py -- area per bit of the committed 4x4 shared-tap 2T array
(issue #97), compared against quoted public 6T SRAM bitcell sizes.

Reads ONLY committed layout artifacts (stdlib only, no klt/klayout/ngspice):

  layout/gain_cell_2t_array.layout.json   composed bbox, block list
  layout/gain_cell_2t_array_mos.json      per-device port coordinates (pitch)
  layout/gain_cell_2t_array.gds           extents cross-check + sha256

and reports three separately-labelled figures:

  (a) drawn bitcell pitch area      = pitch_x * pitch_y   (tap-free cell)
  (b) array area per bit            = composed bbox area / bits  (4x4,
                                      INCLUDING the one shared tap ring)
  (c) extrapolated macro area/bit   = (a)-based array area / (1 - periphery
                                      fraction); periphery fraction is an
                                      ASSUMPTION swept over a range.

SRAM comparators are QUOTED from public sources, NOT measured here.

Writes layout/results/density_<UTC date>.json. Existing result files are
never overwritten (append-only evidence); pass a new
--tag to produce another file the same day.

    python3 -I layout/area_density.py [--tag NAME] [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import struct
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
N_ROWS, N_COLS = 4, 4  # layout/array_topology.py defaults (checked below)

# --- ASSUMPTIONS (labelled; not measured) -----------------------------------
# Fraction of macro area that is NOT bitcell array (sense amps, row drivers,
# refresh controller, decoders, routing channels). No periphery is designed.
PERIPHERY_FRACTION_NOMINAL = 0.30
PERIPHERY_FRACTION_RANGE = (0.10, 0.20, 0.30, 0.40, 0.50)
# Large-array tap model: the committed layout has ONE tap ring around the
# whole 4x4 grid. A real macro needs periodic taps; the bounds below bracket
# that (see write-up): ring-free limit = (a); worst = (b) at 4x4 density.

# --- QUOTED public SRAM comparators (quoted-not-measured) -------------------
SRAM_SOURCE_REPO = "https://github.com/google/skywater-pdk-libs-sky130_fd_bd_sram"
SRAM_SOURCE_COMMIT = "be33adbcf188fdeab5c061699847d9d440f7a084 (2021-10-20)"
SRAM_COMPARATORS = [
    {
        "id": "sky130_fd_bd_sram__sram_sp_cell_opt1",
        "role": "primary: the single-port 6T cell OpenRAM's sky130 port "
                "instantiates (technology/sky130/custom/sky130_bitcell.py, "
                "version='opt1')",
        "width_um": 1.31, "height_um": 1.58,
        "source_url": SRAM_SOURCE_REPO + "/blob/main/cells/sram_sp_cell_opt1/"
                      "sky130_fd_bd_sram__sram_sp_cell_opt1.magic.lef (SIZE line)",
        "openram_ref": "https://github.com/VLSIDA/OpenRAM/blob/stable/"
                       "technology/sky130/custom/sky130_bitcell.py "
                       "(OpenRAM v1.2.48 release 2024-01-21; stable branch "
                       "checked 2026-10-09)",
        "process_rules": "SRAM-specific (foundry-special SRAM design rules)",
    },
    {
        "id": "sky130_fd_bd_sram__openram_sp_cell",
        "role": "smaller variant of the same family (no extra dummy-edge width)",
        "width_um": 1.20, "height_um": 1.58,
        "source_url": SRAM_SOURCE_REPO + "/blob/main/cells/openram_sp_cell/"
                      "sky130_fd_bd_sram__openram_sp_cell.magic.lef (SIZE line)",
        "openram_ref": None,
        "process_rules": "SRAM-specific (foundry-special SRAM design rules)",
    },
]
for _c in SRAM_COMPARATORS:
    _c["area_um2"] = round(_c["width_um"] * _c["height_um"], 6)
    _c["kind"] = "quoted-not-measured"
    _c["retrieved"] = "2026-10-09"
    _c["source_commit"] = SRAM_SOURCE_COMMIT


def gds_extents(path: Path) -> dict:
    """Min/max of every BOUNDARY/PATH/BOX XY over all structures (um)."""
    data = path.read_bytes()
    i, dbu_um = 0, None
    xs, ys = [], []
    while i + 4 <= len(data):
        n, rtype, dtype = struct.unpack(">HBB", data[i:i + 4])
        body = data[i + 4:i + n]
        if rtype == 0x03 and dbu_um is None:  # UNITS: (db/user, db/m)
            dbu_um = _real8(body[8:16]) * 1e6
        elif rtype == 0x10:  # XY
            vals = struct.unpack(">%di" % (len(body) // 4), body)
            xs += vals[0::2]
            ys += vals[1::2]
        i += n
        if n == 0:
            break
    return {"x0": min(xs) * dbu_um, "y0": min(ys) * dbu_um,
            "x1": max(xs) * dbu_um, "y1": max(ys) * dbu_um}


def _real8(b: bytes) -> float:
    sign = -1 if b[0] & 0x80 else 1
    exp = (b[0] & 0x7F) - 64
    mant = int.from_bytes(b[1:], "big") / float(1 << 56)
    return sign * mant * 16.0 ** exp


def derive_pitch(mos: dict) -> tuple[float, float]:
    """Bitcell pitch from the device-port grid: bitcell (r,c) = devices
    U(2*(r*N_COLS*... )) -- see array_topology.idx: M_WR = row*2*N_COLS+2*c."""
    p = {x["name"]: x for x in mos["ports"]}
    per_row = 2 * N_COLS
    px = p["U2_S"]["x_um"] - p["U0_S"]["x_um"]          # cell c -> c+1
    py = p[f"U{per_row}_S"]["y_um"] - p["U0_S"]["y_um"]  # row r -> r+1
    # uniformity check across the whole grid
    for r in range(N_ROWS):
        for c in range(N_COLS):
            u = p[f"U{r * per_row + 2 * c}_S"]
            assert abs(u["x_um"] - (p["U0_S"]["x_um"] + c * px)) < 1e-6, (r, c)
            assert abs(u["y_um"] - (p["U0_S"]["y_um"] + r * py)) < 1e-6, (r, c)
    return round(px, 6), round(py, 6)


def klt_version() -> str:
    try:
        return subprocess.run(["klt", "--version"], capture_output=True,
                              text=True, timeout=20).stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "klt not on PATH (not needed to compute; version not recorded)"


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tag", default="", help="suffix for the result file name")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    lay = json.loads((HERE / "gain_cell_2t_array.layout.json").read_text())
    mos = json.loads((HERE / "gain_cell_2t_array_mos.json").read_text())
    gds = HERE / "gain_cell_2t_array.gds"
    assert mos["device_count"] == 2 * N_ROWS * N_COLS, "array size mismatch"
    bits = N_ROWS * N_COLS

    px, py = derive_pitch(mos)
    cell_area = px * py                                            # (a)
    b = lay["bbox_um"]
    w, h = b["x1"] - b["x0"], b["y1"] - b["y0"]
    array_area = w * h
    per_bit_array = array_area / bits                              # (b)
    ext = gds_extents(gds)
    gw, gh = ext["x1"] - ext["x0"], ext["y1"] - ext["y0"]
    gds_matches = abs(gw - w) < 0.01 and abs(gh - h) < 0.01

    # tap overhead of the single ring around the grid
    ring_um2 = array_area - bits * cell_area

    def macro(frac: float, base: float) -> float:
        return base / (1.0 - frac)

    sens = [{"periphery_fraction": f,
             "macro_um2_per_bit_ring_free_limit": round(macro(f, cell_area), 4),
             "macro_um2_per_bit_4x4_with_ring": round(macro(f, per_bit_array), 4)}
            for f in PERIPHERY_FRACTION_RANGE]
    nom = {"periphery_fraction": PERIPHERY_FRACTION_NOMINAL,
           "macro_um2_per_bit_ring_free_limit":
               round(macro(PERIPHERY_FRACTION_NOMINAL, cell_area), 4),
           "macro_um2_per_bit_4x4_with_ring":
               round(macro(PERIPHERY_FRACTION_NOMINAL, per_bit_array), 4)}

    comps = []
    for c in SRAM_COMPARATORS:
        comps.append(dict(c, ratios={
            "drawn_pitch_2T_over_sram": round(cell_area / c["area_um2"], 3),
            "array_4x4_with_ring_2T_over_sram": round(per_bit_array / c["area_um2"], 3),
            "note": ">1 means the 2T cell is LARGER than the SRAM cell",
        }))
    primary = comps[0]["area_um2"]
    result = {
        "schema_version": 1,
        "issue": 97,
        "generated_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "klt_version_on_host": klt_version(),
        "inputs": {
            "layout_json_sha256": sha256(HERE / "gain_cell_2t_array.layout.json"),
            "mos_json_sha256": sha256(HERE / "gain_cell_2t_array_mos.json"),
            "gds_sha256": sha256(gds),
            "pdk": lay["pdk"],
            "note": "areas are computed from committed artifacts; klt is not "
                    "invoked. If the array GDS is regenerated (issue #91), "
                    "re-run into a new result file.",
        },
        "array": {"rows": N_ROWS, "cols": N_COLS, "bits": bits,
                  "bbox_um": [round(w, 4), round(h, 4)],
                  "gds_extents_um": [round(gw, 4), round(gh, 4)],
                  "gds_extents_match_layout_json": gds_matches},
        "a_drawn_bitcell_pitch": {"pitch_x_um": px, "pitch_y_um": py,
                                  "area_um2": round(cell_area, 4)},
        "b_array_per_bit_with_shared_tap": {
            "array_area_um2": round(array_area, 4),
            "um2_per_bit": round(per_bit_array, 4),
            "tap_ring_area_um2": round(ring_um2, 4),
            "note": "one tap ring around a 16-bit array is a worst-case "
                    "overhead that shrinks with array size; the ring-free "
                    "limit is (a)"},
        "c_extrapolated_macro_per_bit": {
            "kind": "ASSUMPTION-driven extrapolation, not a layout",
            "assumption": "periphery (sense/drivers/refresh/decode/routing) "
                          "occupies a fraction f of macro area; no periphery "
                          "is designed. macro/bit = array/bit / (1 - f)",
            "nominal": nom, "sensitivity": sens},
        "sram_comparators": comps,
        "verdict": {
            "primary_comparator_um2": primary,
            "drawn_pitch_ratio": round(cell_area / primary, 3),
            "array_4x4_ratio": round(per_bit_array / primary, 3),
            "macro_nominal_ratio_ring_free": round(
                nom["macro_um2_per_bit_ring_free_limit"] / primary, 3),
            "2T_beats_sram_cell_on_area": cell_area < primary,
            "caveat": "SRAM figures use SRAM-specific rules; the 2T cell is "
                      "drawn in plain logic rules. No public logic-rule 6T "
                      "sky130 figure was verified, so none is quoted. "
                      "SRAM is static; this cell needs refresh "
                      "(sim/refresh-overhead/README.md).",
        },
    }
    out = HERE / "results" / ("density_%s%s.json" % (
        datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d"),
        ("_" + re.sub(r"[^A-Za-z0-9_-]", "", a.tag)) if a.tag else ""))
    text = json.dumps(result, indent=2) + "\n"
    if a.dry_run:
        print(text)
        return 0
    if out.exists():
        print(f"refusing to overwrite append-only result {out}; use --tag",
              file=sys.stderr)
        return 1
    out.parent.mkdir(exist_ok=True)
    out.write_text(text)
    print(f"wrote {out}")
    print(f"(a) pitch {px} x {py} = {cell_area:.4f} um2 | (b) {per_bit_array:.4f} um2/bit"
          f" | SRAM {primary:.4f} um2 | GDS extents match: {gds_matches}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
