#!/usr/bin/env python3
"""Reduce the compact-layout array parasitics and compare with the uniform grid (issue #161).

Reads the COMMITTED ``klt extract --parasitics`` reports of

* the uniform-grid 4x4 array  ``layout/gain_cell_2t_array.extract.parasitics.json`` (issue #80),
* the compact v2 / v1 arrays  ``layout/compact/gain_cell_2t_{v2,v1}_array.extract.parasitics.json``,

and writes ONE NEW ``layout/results/compact_parasitics_<UTC>.json`` (never overwrites:
append-only evidence). The reduction reuses ``array_parasitics.net_entry`` / ``classify``
(total = lumped ground + every coupling capacitor on the net; wiring only -- diffusion
junction and gate capacitance are carried by the device cards, not these numbers).

Storage nodes: the uniform grid labels them ``sn_<r>_<c>``; the compact layouts do not
label them, so they extract as anonymous ``\\$N`` nets. ``storage_nodes()`` identifies them
STRUCTURALLY from the extracted devices: the non-bit-line source/drain net of every write
device (gate on ``wl_*``), which must also be the gate net of exactly one read device.

Word-line resistance (new for the compact layouts, where each row is one continuous poly
line) is recorded two ways, kept distinct:

* ``extractor_reported``: ``parasitics.nets[wl_*].resistance_ohm`` -- the klt lumped STAR
  model (sum of per-gate-terminal leg resistances to a hub). It is NOT an end-to-end line
  resistance.
* ``hand_end_to_end_poly``: rsh x (drawn length / drawn width) of the poly line read from
  the GDS (read with a minimal stdlib GDSII reader; flat compact layouts only), with rsh from the
  shipped PDK resistor-corner files (``rp1`` = 44 / 48.2 / 55.8 ohm/sq). A driver at one end
  sees this end-to-end value, ignoring contact and silicide effects the PDK ``rp1`` already
  folds in. It is a hand calculation, labelled as such.

Usage (repo root):
    python3 -I layout/compact_parasitics.py --write     # new layout/results/compact_parasitics_<ts>.json
    python3 -I layout/compact_parasitics.py --check FILE   # recompute and compare (ignoring generated_utc)
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "sim"))
import array_parasitics as AP  # noqa: E402
from _evidence_common import sha256_prefixed  # noqa: E402

RESULTS = HERE / "results"
PREFIX = "compact_parasitics_"
SCHEMA = "gcedram.compact_parasitics/1"
LAYOUTS = {
    "uniform_grid": (HERE / "gain_cell_2t_array.extract.parasitics.json", HERE / "gain_cell_2t_array.gds"),
    "compact_v2": (HERE / "compact" / "gain_cell_2t_v2_array.extract.parasitics.json",
                   HERE / "compact" / "gain_cell_2t_v2_array.gds"),
    "compact_v1": (HERE / "compact" / "gain_cell_2t_v1_array.extract.parasitics.json",
                   HERE / "compact" / "gain_cell_2t_v1_array.gds"),
}
WL_RE = re.compile(r"^wl_\d+$")
BL_RE = re.compile(r"^bl_\d+$")
POLY_LAYER = (66, 20)
POLY_LABEL_LAYER = (66, 5)
# rsh of poly (ohm/sq) from the shipped sky130A r+c corner files
# (libs.tech/ngspice/r+c/res_{low,typical,high}__cap_typical.spice -> rp1).
RP1_OHM_PER_SQ = {"low": 44.0, "typical": 48.2, "high": 55.8}
VOLATILE = ("generated_utc",)


class CompactError(RuntimeError):
    pass


def storage_nodes(report: dict) -> list[str]:
    """Net names of every storage node, found from device connectivity."""
    sn_of_write, gate_of_read = set(), []
    for d in report.get("devices") or []:
        n = d.get("nets") or {}
        if not WL_RE.match(str(n.get("g", ""))):
            continue
        s_bl, d_bl = bool(BL_RE.match(str(n.get("s")))), bool(BL_RE.match(str(n.get("d"))))
        if s_bl == d_bl:
            raise CompactError(f"write device {d.get('name')!r}: cannot tell bit line from storage node ({n})")
        sn_of_write.add(n["d"] if s_bl else n["s"])
    for d in report.get("devices") or []:
        g = (d.get("nets") or {}).get("g")
        if g in sn_of_write:
            gate_of_read.append(g)
    nodes = sorted(sn_of_write)
    if not nodes:
        raise CompactError("no storage nodes found")
    if sorted(gate_of_read) != nodes:
        raise CompactError("every storage node must be the gate of exactly one read device")
    names = {n["net"] for n in report["parasitics"]["nets"]}
    missing = [n for n in nodes if n not in names]
    if missing:
        raise CompactError(f"storage nets {missing} have no parasitics entry (not named --critical-net?)")
    return nodes


def sn_entries(report: dict) -> dict:
    by_name = {n["net"]: n for n in report["parasitics"]["nets"]}
    return {name: AP.net_entry(by_name[name]) for name in storage_nodes(report)}


def stats(entries: dict, key: str) -> dict:
    vals = [e[key] for e in entries.values()]
    worst = max(entries, key=lambda k: (entries[k][key], k))
    return {"min": min(vals), "max": max(vals), "mean": round(sum(vals) / len(vals), 6), "max_net": worst}


def bus_summary(group: dict) -> dict:
    return {"nets": len(group),
            "total_ff": stats(group, "total_ff"), "ground_ff": stats(group, "ground_ff"),
            "coupling_ff": stats(group, "coupling_ff"), "resistance_ohm": stats(group, "resistance_ohm"),
            "worst_by_layer_ground_ff": group[max(group, key=lambda k: (group[k]["total_ff"], k))]["by_layer_ground_ff"]}


def read_flat_gds(path: Path) -> dict | None:
    """Minimal GDSII reader for a FLAT single-structure file (the compact layouts).

    Returns {"dbu_um", "boundaries": [(layer, datatype, [(x, y)...])], "texts": [(layer, texttype, (x, y), str)]},
    or None if the file instantiates other structures (SREF/AREF) -- then no hand number is claimed.
    """
    data = Path(path).read_bytes()
    pos, out = 0, {"dbu_um": None, "boundaries": [], "texts": []}
    cur: dict = {}
    while pos + 4 <= len(data):
        n, rtype = int.from_bytes(data[pos:pos + 2], "big"), data[pos + 2]
        body = data[pos + 4:pos + n]
        pos += n
        if n < 4:
            return None
        if rtype == 0x03:  # UNITS: db unit in user units, db unit in metres
            out["dbu_um"] = _gds_real(body[8:16]) * 1e6
        elif rtype in (0x0A, 0x0B):  # SREF / AREF
            return None
        elif rtype in (0x08, 0x0C):  # BOUNDARY / TEXT
            cur = {"kind": rtype}
        elif rtype == 0x0D:
            cur["layer"] = int.from_bytes(body, "big")
        elif rtype in (0x0E, 0x16):  # DATATYPE / TEXTTYPE
            cur["dt"] = int.from_bytes(body, "big")
        elif rtype == 0x10:
            vals = [int.from_bytes(body[i:i + 4], "big", signed=True) for i in range(0, len(body), 4)]
            cur["xy"] = list(zip(vals[0::2], vals[1::2]))
        elif rtype == 0x19:
            cur["str"] = body.rstrip(b"\0").decode("ascii", "replace")
        elif rtype == 0x11 and cur:  # ENDEL
            if cur["kind"] == 0x08:
                out["boundaries"].append((cur["layer"], cur["dt"], cur["xy"]))
            else:
                out["texts"].append((cur["layer"], cur.get("dt", 0), cur["xy"][0], cur.get("str", "")))
            cur = {}
    return out if out["dbu_um"] else None


def _gds_real(b: bytes) -> float:
    """GDSII 8-byte excess-64 real."""
    sign = -1.0 if b[0] & 0x80 else 1.0
    mant = int.from_bytes(b[1:], "big") / float(1 << 56)
    return sign * mant * 16.0 ** ((b[0] & 0x7F) - 64)


def poly_wordline_geometry(gds: Path) -> dict | None:
    """Drawn poly line (length, width, squares) under each ``wl_<r>`` label when it is a single plain
    rectangle on the poly layer; None otherwise (no end-to-end hand number is then claimed)."""
    g = read_flat_gds(gds)
    if not g:
        return None
    dbu = g["dbu_um"]
    rects = []
    for layer, dt, xy in g["boundaries"]:
        if (layer, dt) != POLY_LAYER:
            continue
        pts = xy[:-1] if xy and xy[0] == xy[-1] else xy
        xs, ys = {x for x, _ in pts}, {y for _, y in pts}
        if len(pts) == 4 and len(xs) == 2 and len(ys) == 2:
            rects.append((min(xs), min(ys), max(xs), max(ys)))
    out = {}
    for layer, tt, (x, y), name in g["texts"]:
        if (layer, tt) != POLY_LABEL_LAYER or not WL_RE.match(name):
            continue
        hit = [r for r in rects if r[0] <= x <= r[2] and r[1] <= y <= r[3]]
        if len(hit) != 1:
            return None
        x0, y0, x1, y1 = hit[0]
        length, width = sorted(((x1 - x0) * dbu, (y1 - y0) * dbu), reverse=True)
        out[name] = {"length_um": round(length, 6), "width_um": round(width, 6), "squares": round(length / width, 6)}
    return dict(sorted(out.items())) or None


def wordline_resistance(rep: dict, gds: Path) -> dict:
    wl = {n["net"]: n for n in rep["parasitics"]["nets"] if WL_RE.match(n["net"])}
    star = {k: {"resistance_ohm": round(float(v["resistance_ohm"]), 6),
                "terminal_legs_ohm": [round(float(t["resistance_ohm"]), 4) for t in v.get("terminals", [])],
                "by_layer": [b["layer"] for b in v.get("by_layer", [])]} for k, v in sorted(wl.items())}
    geo = poly_wordline_geometry(gds)
    block = {"extractor_reported": {
        "model": "klt lumped STAR: resistance_ohm = sum of per-gate-terminal leg resistances to a hub "
                 "(rc_model=lumped); NOT an end-to-end line resistance",
        "nets": star}}
    if geo:
        sq = {k: v["squares"] for k, v in geo.items()}
        block["hand_end_to_end_poly"] = {
            "label": "HAND CALCULATION from drawn GDS geometry x PDK rp1; not an extractor output",
            "rsh_ohm_per_sq_source": "sky130A libs.tech/ngspice/r+c/res_{low,typical,high}__cap_typical.spice rp1",
            "rsh_ohm_per_sq": RP1_OHM_PER_SQ,
            "drawn_poly_line": geo,
            "end_to_end_ohm": {k: {c: round(RP1_OHM_PER_SQ[c] * s, 3) for c in RP1_OHM_PER_SQ} for k, s in sq.items()},
        }
    return block


def layout_block(name: str, report_path: Path, gds: Path) -> dict:
    rep = json.loads(report_path.read_text())
    if rep.get("status") != "extracted" or not rep.get("parasitics"):
        raise CompactError(f"{report_path}: not an extracted parasitics report")
    g = AP.classify(rep)
    sn = sn_entries(rep)
    prov = rep.get("provenance") or {}
    return {
        "source": {"extraction": str(report_path.relative_to(REPO)), "extraction_sha256": sha256_prefixed(report_path),
                   "gds": str(gds.relative_to(REPO)), "gds_sha256": sha256_prefixed(gds), "top": rep.get("top"),
                   "device_count": rep.get("device_count"), "klt_version": prov.get("klt_version"),
                   "klayout_version": prov.get("klayout_version"),
                   "critical_nets": rep["parasitics"].get("critical_nets"), "warnings": rep.get("warnings")},
        "rbl": bus_summary(g["rbl"]), "bl": bus_summary(g["bl"]),
        "wl": bus_summary(g["wl"]), "rwl": bus_summary(g["rwl"]),
        "storage_node": {"nets": sorted(sn), "total_ff": stats(sn, "total_ff"), "ground_ff": stats(sn, "ground_ff"),
                         "coupling_ff": stats(sn, "coupling_ff"), "per_node": sn},
        "wordline_resistance": wordline_resistance(rep, gds),
        "per_net": {k: g[k] for k in ("rbl", "bl", "wl", "rwl")},
    }


def ratio(a: float, b: float) -> float:
    return round(a / b, 6)


def build() -> dict:
    blocks = {n: layout_block(n, p, gds) for n, (p, gds) in LAYOUTS.items()}
    base = blocks["uniform_grid"]
    comparison = {}
    for name in ("compact_v2", "compact_v1"):
        b = blocks[name]
        comp = {}
        for bus in ("rbl", "bl", "wl", "rwl"):
            comp[f"{bus}_worst_total_ff"] = {"uniform_grid": base[bus]["total_ff"]["max"], name: b[bus]["total_ff"]["max"],
                                             "ratio": ratio(b[bus]["total_ff"]["max"], base[bus]["total_ff"]["max"])}
        comp["c_sn_min_total_ff"] = {"uniform_grid": base["storage_node"]["total_ff"]["min"],
                                     name: b["storage_node"]["total_ff"]["min"],
                                     "ratio": ratio(b["storage_node"]["total_ff"]["min"], base["storage_node"]["total_ff"]["min"])}
        comp["c_sn_max_total_ff"] = {"uniform_grid": base["storage_node"]["total_ff"]["max"],
                                     name: b["storage_node"]["total_ff"]["max"],
                                     "ratio": ratio(b["storage_node"]["total_ff"]["max"], base["storage_node"]["total_ff"]["max"])}
        comparison[name] = comp
    return {
        "schema": SCHEMA, "issue": 161,
        "label": ("Extracted WIRING parasitics of the 4-row x 4-column arrays, compact layouts (#100) vs the "
                  "uniform grid (#80). Wiring only: diffusion-junction and gate capacitance are not included. "
                  "Not a macro-level number; 4 rows only."),
        "generated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "convention": ("total_ff = ground_ff + sum(coupled[].capacitance_ff) per net, as "
                       "array_parasitics.net_entry / derive_retention.load_extracted_c_sn(). Lateral coupling covers "
                       "pairs touching a --critical-net; for the compact layouts that includes the anonymous "
                       "storage-node nets (--critical-net-pattern '\\$*'), so the comparison is like-for-like."),
        "klt_version_note": ("The uniform-grid extraction was made with klt 0.7.0; re-extracting it with the klt used "
                             "for the compact layouts reproduced every net's total capacitance and resistance exactly."),
        "layouts": blocks, "comparison_vs_uniform_grid": comparison,
        "c_rbl_assumption_ff": AP.C_RBL_ASSUMPTION_FF,
        "c_rbl_assumption_source": AP.C_RBL_ASSUMPTION_SOURCE,
    }


def strip(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k not in VOLATILE}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--write", action="store_true")
    g.add_argument("--check", metavar="FILE")
    a = ap.parse_args(argv)
    try:
        doc = build()
    except CompactError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    if a.check:
        want = json.loads(Path(a.check).read_text())
        if strip(want) != json.loads(json.dumps(strip(doc))):
            print(f"DRIFT: {a.check} does not match a recomputation from the committed inputs", file=sys.stderr)
            return 1
        print(f"OK: {a.check} reproduces from the committed inputs")
        return 0
    for name, c in doc["comparison_vs_uniform_grid"].items():
        print(name, {k: v["ratio"] for k, v in c.items()})
    if a.write:
        stamp = doc["generated_utc"].replace("-", "").replace(":", "").replace("+0000", "Z")
        out = RESULTS / f"{PREFIX}{stamp}.json"
        if out.exists():
            print(f"ERROR: {out} exists; results are append-only", file=sys.stderr)
            return 1
        out.write_text(json.dumps(doc, indent=1) + "\n")
        print(f"wrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
