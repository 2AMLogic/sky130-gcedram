#!/usr/bin/env python3
"""compare_array_layout.py -- compare a regenerated array layout against the
committed one (issue #91).

`generate_array.sh --check` used to check only routing/DRC/LVS/ERC status, so
a layout that was electrically fine but geometrically different from the
committed GDS passed. This script makes the check compare the layout itself.

What is compared (BASELINE_ARTIFACTS):

  GDS files (gain_cell_2t_array_mos.gds, gain_cell_2t_array.gds) -- geometry
    and labels. Every BOUNDARY, PATH, BOX, NODE, TEXT, SREF and AREF element
    is compared record by record (layer, datatype/texttype, every XY vertex,
    path width/type, text string and presentation, transforms, properties),
    as is every structure name and the library header (name, units).
  Compose/generator reports (gain_cell_2t_array_mos.json,
    gain_cell_2t_array.layout.json) -- connectivity as the generator recorded
    it: per-net pins, legs, route status and route length, unrouted nets,
    ports and device count. Compared as parsed JSON, value for value.
  Request/reference files (gain_cell_2t_array.layout.request.json,
    gain_cell_2t_array.lvs_reference.spice, gain_cell_2t_array.lvs.request.json)
    -- the connectivity intent fed to gen-compose and LVS. Exact.

Normalization (the only things ignored):

  * GDS BGNLIB/BGNSTR payloads: creation/modification timestamps only.
  * Order of elements inside a GDS structure, and of structures in the file.
    Element order has no geometric meaning; elements are compared as a
    multiset, so a duplicated or missing element still fails.
  * Null padding after ENDLIB.
  * JSON whitespace/key order.

Nothing is merged, snapped or rounded: a polygon with the same area but
different vertices, a path 1 dbu wider, a moved or renamed label, or a pin
assigned to another net all fail.

Raw sha256 hashes are reported separately from the canonical comparison, so a
timestamp-only difference shows up as "raw differs, canonical identical".

Usage:
  python3 layout/compare_array_layout.py --committed layout --regenerated DIR [-o out.json]
  python3 layout/compare_array_layout.py ... --artifact gain_cell_2t_array.gds:gds

Exit status: 0 = every artifact matches, 1 = any mismatch or missing file.
Stdlib only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any

BASELINE_ARTIFACTS: list[tuple[str, str]] = [
    ("gain_cell_2t_array_mos.gds", "gds"),
    ("gain_cell_2t_array_mos.json", "json"),
    ("gain_cell_2t_array.layout.request.json", "json"),
    ("gain_cell_2t_array.gds", "gds"),
    ("gain_cell_2t_array.layout.json", "json"),
    ("gain_cell_2t_array.lvs_reference.spice", "text"),
    ("gain_cell_2t_array.lvs.request.json", "json"),
]
# The geometry/connectivity subset a scaling build (extract_array_parasitics.sh)
# produces with the same names.
GENERATION_ARTIFACTS = BASELINE_ARTIFACTS[:5]

NORMALIZATION = [
    "GDS BGNLIB/BGNSTR timestamp payloads ignored",
    "element order within a GDS structure and structure order ignored (multiset comparison)",
    "null padding after GDS ENDLIB ignored",
    "JSON compared as parsed values (whitespace/key order ignored)",
]

# GDSII record types (subset with names; unknown types are kept by number).
REC = {
    0x00: "HEADER", 0x01: "BGNLIB", 0x02: "LIBNAME", 0x03: "UNITS", 0x04: "ENDLIB",
    0x05: "BGNSTR", 0x06: "STRNAME", 0x07: "ENDSTR", 0x08: "BOUNDARY", 0x09: "PATH",
    0x0A: "SREF", 0x0B: "AREF", 0x0C: "TEXT", 0x0D: "LAYER", 0x0E: "DATATYPE",
    0x0F: "WIDTH", 0x10: "XY", 0x11: "ENDEL", 0x12: "SNAME", 0x13: "COLROW",
    0x15: "NODE", 0x16: "TEXTTYPE", 0x17: "PRESENTATION", 0x19: "STRING",
    0x1A: "STRANS", 0x1B: "MAG", 0x1C: "ANGLE", 0x21: "PATHTYPE", 0x2A: "NODETYPE",
    0x2B: "PROPATTR", 0x2C: "PROPVALUE", 0x2D: "BOX", 0x2E: "BOXTYPE",
    0x30: "BGNEXTN", 0x31: "ENDEXTN",
}
ELEMENT_START = {0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x15, 0x2D}
TIMESTAMP_RECORDS = {0x01, 0x05}


class GdsError(ValueError):
    pass


def gds_records(data: bytes):
    i, n = 0, len(data)
    while i < n:
        if i + 4 > n:
            raise GdsError(f"truncated record header at byte {i}")
        length, rtype, dtype = struct.unpack(">HBB", data[i:i + 4])
        if length < 4 or i + length > n:
            raise GdsError(f"bad record length {length} at byte {i}")
        yield rtype, dtype, data[i + 4:i + length]
        i += length
        if rtype == 0x04:  # ENDLIB
            rest = data[i:]
            if rest.strip(b"\x00"):
                raise GdsError(f"non-padding bytes after ENDLIB at byte {i}")
            return
    raise GdsError("no ENDLIB record")


def canonical_gds(data: bytes) -> dict[str, Any]:
    """{'header': [...], 'structures': {name: {'records': [...], 'elements': [...]}}}.
    Each record is 'TYPE:dtype:payloadhex'; timestamp payloads are dropped."""
    header: list[str] = []
    structures: dict[str, dict[str, Any]] = {}
    cur: dict[str, Any] | None = None
    cur_name: str | None = None
    elem: list[str] | None = None
    for rtype, dtype, payload in gds_records(data):
        name = REC.get(rtype, f"0x{rtype:02X}")
        rec = f"{name}:{dtype}:" + ("<timestamp>" if rtype in TIMESTAMP_RECORDS else payload.hex())
        if rtype == 0x05:
            cur, cur_name = {"records": [], "elements": []}, None
            continue
        if cur is None:
            header.append(rec)
            continue
        if rtype == 0x06:
            cur_name = payload.rstrip(b"\x00").decode("latin-1")
            if cur_name in structures:
                raise GdsError(f"duplicate structure {cur_name!r}")
            continue
        if rtype == 0x07:
            if cur_name is None:
                raise GdsError("structure without STRNAME")
            cur["elements"].sort()
            structures[cur_name] = cur
            cur, cur_name = None, None
            continue
        if rtype in ELEMENT_START:
            elem = [rec]
            continue
        if rtype == 0x11:
            if elem is None:
                raise GdsError("ENDEL outside an element")
            cur["elements"].append("|".join(elem))
            elem = None
            continue
        (elem if elem is not None else cur["records"]).append(rec)
    return {"header": header, "structures": dict(sorted(structures.items()))}


def canonical_hash(obj: Any) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def describe_element(elem: str) -> str:
    """Readable form of a canonical element string, for diagnostics."""
    parts = []
    for rec in elem.split("|"):
        name, _dtype, payload = rec.split(":", 2)
        raw = bytes.fromhex(payload) if payload not in ("", "<timestamp>") else b""
        if name in ("LAYER", "DATATYPE", "TEXTTYPE", "PATHTYPE", "BOXTYPE", "NODETYPE", "PRESENTATION",
                    "STRANS", "PROPATTR"):
            parts.append(f"{name}={struct.unpack('>h', raw[:2])[0] if len(raw) >= 2 else ''}")
        elif name in ("WIDTH",):
            parts.append(f"WIDTH={struct.unpack('>i', raw)[0]}")
        elif name == "XY":
            v = struct.unpack(f">{len(raw) // 4}i", raw)
            pts = [f"({v[k]},{v[k + 1]})" for k in range(0, len(v), 2)]
            parts.append("XY=" + "".join(pts[:8]) + ("..." if len(pts) > 8 else ""))
        elif name in ("STRING", "SNAME", "PROPVALUE"):
            text = raw.rstrip(b"\x00").decode("latin-1")
            parts.append(f"{name}={text!r}")
        elif name == "COLROW":
            parts.append(f"COLROW={struct.unpack('>hh', raw)}")
        else:
            parts.append(name if not raw else f"{name}=0x{raw.hex()}")
    return " ".join(parts)


def diff_gds(a: dict[str, Any], b: dict[str, Any], limit: int = 20) -> list[str]:
    out: list[str] = []
    if a["header"] != b["header"]:
        out.append(f"library header differs: committed {a['header']} vs regenerated {b['header']}")
    sa, sb = a["structures"], b["structures"]
    for name in sorted(set(sa) - set(sb)):
        out.append(f"structure {name!r} only in committed")
    for name in sorted(set(sb) - set(sa)):
        out.append(f"structure {name!r} only in regenerated")
    for name in sorted(set(sa) & set(sb)):
        if sa[name]["records"] != sb[name]["records"]:
            out.append(f"structure {name!r}: non-element records differ")
        ca, cb = Counter(sa[name]["elements"]), Counter(sb[name]["elements"])
        only_a, only_b = ca - cb, cb - ca
        if only_a or only_b:
            out.append(f"structure {name!r}: {sum(only_a.values())} element(s) only in committed, "
                       f"{sum(only_b.values())} only in regenerated")
            for e in sorted(only_a)[:limit]:
                out.append(f"  - committed:   {describe_element(e)}")
            for e in sorted(only_b)[:limit]:
                out.append(f"  + regenerated: {describe_element(e)}")
    return out


def diff_json(a: Any, b: Any, path: str = "$", out: list[str] | None = None, limit: int = 40) -> list[str]:
    out = [] if out is None else out
    if len(out) >= limit:
        return out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append(f"{path}.{k}: only in regenerated")
            elif k not in b:
                out.append(f"{path}.{k}: only in committed")
            else:
                diff_json(a[k], b[k], f"{path}.{k}", out, limit)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{path}: length {len(a)} (committed) vs {len(b)} (regenerated)")
        for i, (x, y) in enumerate(zip(a, b)):
            diff_json(x, y, f"{path}[{i}]", out, limit)
    elif a != b or type(a) is not type(b):
        out.append(f"{path}: committed {a!r} vs regenerated {b!r}")
    return out


def diff_text(a: str, b: str) -> list[str]:
    la, lb = a.splitlines(), b.splitlines()
    for i, (x, y) in enumerate(zip(la, lb)):
        if x != y:
            return [f"line {i + 1}: committed {x!r} vs regenerated {y!r}"]
    if len(la) != len(lb):
        return [f"line count {len(la)} (committed) vs {len(lb)} (regenerated)"]
    return ["byte-level difference (line endings/trailing newline)"] if a != b else []


def sha256_file(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def compare_artifact(committed: Path, regenerated: Path, kind: str) -> dict[str, Any]:
    res: dict[str, Any] = {"artifact": committed.name, "kind": kind}
    missing = [str(p) for p in (committed, regenerated) if not p.is_file()]
    if missing:
        res.update(match=False, differences=[f"missing file: {m}" for m in missing])
        return res
    ra, rb = committed.read_bytes(), regenerated.read_bytes()
    res["raw_sha256"] = {"committed": sha256_file(committed), "regenerated": sha256_file(regenerated)}
    res["raw_identical"] = ra == rb
    try:
        if kind == "gds":
            ca, cb = canonical_gds(ra), canonical_gds(rb)
            res["canonical_sha256"] = {"committed": canonical_hash(ca), "regenerated": canonical_hash(cb)}
            diffs = diff_gds(ca, cb)
        elif kind == "json":
            ja, jb = json.loads(ra), json.loads(rb)
            res["canonical_sha256"] = {"committed": canonical_hash(ja), "regenerated": canonical_hash(jb)}
            diffs = diff_json(ja, jb)
        elif kind == "text":
            diffs = diff_text(ra.decode(), rb.decode())
        else:
            raise ValueError(f"unknown artifact kind {kind!r}")
    except (GdsError, ValueError, UnicodeDecodeError) as exc:
        diffs = [f"could not parse: {exc}"]
    res["match"] = not diffs
    res["differences"] = diffs
    return res


def compare(committed_dir: Path, regenerated_dir: Path, artifacts: list[tuple[str, str]]) -> dict[str, Any]:
    results = [compare_artifact(committed_dir / n, regenerated_dir / n, k) for n, k in artifacts]
    return {
        "schema_version": 1,
        "committed_dir": str(committed_dir),
        "regenerated_dir": str(regenerated_dir),
        "normalization": NORMALIZATION,
        "artifacts": results,
        "result": "match" if all(r["match"] for r in results) else "mismatch",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--committed", required=True, type=Path)
    ap.add_argument("--regenerated", required=True, type=Path)
    ap.add_argument("--artifact", action="append", default=[], metavar="NAME:KIND",
                    help="compare only these (kind: gds|json|text); default: the full 4x4 baseline set")
    ap.add_argument("--generation-only", action="store_true",
                    help="compare only the generation outputs (no LVS reference/request)")
    ap.add_argument("-o", "--output", type=Path)
    args = ap.parse_args(argv)
    if args.artifact:
        artifacts = [tuple(a.rsplit(":", 1)) for a in args.artifact]
    else:
        artifacts = GENERATION_ARTIFACTS if args.generation_only else BASELINE_ARTIFACTS
    report = compare(args.committed, args.regenerated, artifacts)
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    for r in report["artifacts"]:
        raw = "raw identical" if r.get("raw_identical") else "raw differs"
        print(f"   {r['artifact']:<42} {'MATCH' if r['match'] else 'MISMATCH':<8} ({raw})")
        for d in r["differences"][:12]:
            print(f"      {d}")
    print(f"   baseline comparison: {report['result']}")
    return 0 if report["result"] == "match" else 1


if __name__ == "__main__":
    sys.exit(main())
