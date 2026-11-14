#!/usr/bin/env python3
"""xor_layout_geometry.py -- flattened, hierarchy-insensitive per-layer
geometry-equivalence measurement between two GDS streams (issue #284).

Why this exists
---------------
`layout/compare_array_layout.py` (issue #91) is deliberately record-exact: it
compares every GDS element *and every structure name*, so a release that
renames an emitted sub-PCell fails it even when nothing drawn moved. That is
the right behaviour for `generate_array.sh --check`, which gates byte-for-byte
reproduction of the committed array -- and it is why that gate cannot answer a
different question:

    is the geometry the committed GDS holds still the geometry the newer
    generator would draw?

klt 0.9.1's `gen mos_array` emits its inner PCell structure as
`<cell-name>__core` where 0.8.0 emitted the library name `mos_array`, and adds
a `dogbone_terminals` PCell parameter to the `$$$CONTEXT_INFO$$$` record. The
bytes therefore differ; `generation-toolchain.json`'s `generation.verified`
claims the drawn geometry does not. This script is the testbench behind that
claim (CLAUDE.md: "Verification is the product: no claim without a testbench").

No `klt` verb performs this measurement: `klt diff` is shape-for-shape but
"never ignores ... cell names", so on the rename it reports `different` (exit 3)
with an empty `layers: []` -- it found no shape difference, and the whole
verdict rests on the instance target's name. There is no flatten-and-boolean
verb. Filed upstream as klayout-tools #5729 (a `klt diff --flatten` mode),
which is the tool gap this script hand-rolls around; distinct from #5627 (the
emitted inner-cell name is not pinnable) and from the declined #5489 (which
asked for order-insensitivity, something `klt diff` already does).

What it measures
----------------
Both streams' named top cell is flattened (full depth, instances pruned), then
for each drawn layer/datatype pair:

  * committed and regenerated polygon counts (after merge),
  * the symmetric difference `committed ^ regenerated`, merged, reported as a
    polygon count and an area in dbu^2 and um^2. An empty XOR is `0`, stated
    explicitly -- never an absent key.

Three things are reported *separately* from the per-pair XOR, because each is
a failure mode an XOR-empty result cannot rule out on its own:

  1. **The drawn-pair enumeration.** `--expect-drawn-layer` names the pairs the
     measurement is asserted over. A pair present in one stream and not the
     other, or present in neither but expected, fails -- a loop over only the
     committed layers would silently miss a layer the regenerated stream added.
  2. **The bounding box**, compared in dbu on the flattened top cell.
  3. **The label set** (layer/texttype, string, position). GDS `TEXT` records
     are not polygons, so no polygon XOR can see them. They are counted on
     their own layer/texttype pairs, which are kept out of the drawn set.

A note on `klt layers`: it folds `TEXT` records into its per-pair shape counts,
so on the committed array it reports 12 pairs where this script reports 10
drawn pairs plus 2 label-only pairs. Enumerate, never count.

Usage
-----
Requires `klayout` importable -- run it under a pinned toolchain venv's python
(`layout/generation_toolchain.py install --role <role>`), never a bare
`python3`, which has no `klayout` on the sweep hosts.

    <venv>/bin/python -I layout/xor_layout_geometry.py \
        --committed layout/gain_cell_2t_array.gds \
        --regenerated /path/to/scratch/gain_cell_2t_array.gds \
        --top gain_cell_2t_array_4x4_layout_0 \
        --committed-toolchain-python  <0.8.0 venv>/bin/python \
        --regenerated-toolchain-python <0.9.1 venv>/bin/python \
        --commands-file /path/to/commands.txt \
        -o layout/results/geometry_xor_<tag>.json

Controls (both reproducible from a stock PDK install; see layout/README.md
"Generation and check pins diverge at klt 0.9.1"):

  identity   --committed and --regenerated both the committed GDS: every
             drawn pair must report 0 XOR polygons.
  negative   feed a stream with a drawn layer added or dropped: the
             enumeration assertion must fail (exit 1), proving an
             XOR-empty result is not the only thing being checked.

Exit status: 0 = equivalent (enumeration, every per-pair XOR, bbox and labels
all agree), 1 = any difference or a measurement that could not be made.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

LAYOUT_DIR = Path(__file__).resolve().parent
REPO_ROOT = LAYOUT_DIR.parent
sys.path.insert(0, str(LAYOUT_DIR))
import generation_toolchain as T  # noqa: E402  (stdlib-only; no klayout needed)

RECORD_KIND = "gain_cell_2t_array flattened per-layer geometry XOR record (issue #284)"
SCHEMA_VERSION = 1

# The drawn (non-TEXT) layer/datatype pairs of the committed 4x4 array, by
# name. Asserted as an enumeration, not as a count -- see the module docstring.
DEFAULT_DRAWN_LAYERS = (
    "65/20",  # diff
    "65/44",  # tap
    "66/20",  # poly
    "66/44",  # licon1
    "67/20",  # li1
    "67/44",  # mcon
    "68/20",  # met1
    "93/44",  # nsdm
    "94/20",  # psdm
    "95/20",  # nsdm/npc
)


def die(msg: str) -> "NoReturn":  # noqa: F821
    print(f"FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def require_klayout() -> Any:
    """Import klayout.db, or fail naming the interpreter and the fix.

    Mirrors generation_toolchain.py's convention: never install implicitly, and
    fail with the exact command that provisions what is missing.
    """
    try:
        import klayout.db as kdb  # noqa: PLC0415
    except ImportError as exc:
        die(
            f"`import klayout.db` failed under {sys.executable}: {exc}\n"
            "  This script needs a KLayout-capable interpreter; a bare `python3` has none.\n"
            "  fix: run it under a pinned toolchain venv's python, e.g.\n"
            "    python3 layout/generation_toolchain.py install --role check\n"
            "    .toolchains/klt-check-v<ver>-klayout-<ver>/bin/python -I layout/xor_layout_geometry.py ...\n"
            "  or point it at any interpreter whose environment has: "
            f"klayout=={T.load_config()['toolchains']['check']['klayout']}"
        )
    return kdb


def layer_key(info: Any) -> str:
    return f"{info.layer}/{info.datatype}"


def flattened(kdb: Any, path: Path, top: str) -> dict[str, Any]:
    """Read `path`, flatten `top` full-depth, and split drawn shapes from TEXT.

    Returns {'layout', 'cell', 'dbu', 'drawn': {key: Region},
             'labels': {key: [(string, x, y), ...]}}.
    """
    if not path.is_file():
        die(f"stream not found: {path}")
    layout = kdb.Layout()
    try:
        layout.read(str(path))
    except Exception as exc:  # klayout raises its own error types
        die(f"could not read {path}: {exc}")
    cell = layout.cell(top)
    if cell is None:
        die(f"{path}: no cell named {top!r} (cells: "
            f"{', '.join(sorted(c.name for c in layout.each_cell()))})")
    cell.flatten(-1, True)  # full depth, prune the emptied instance tree

    drawn: dict[str, Any] = {}
    labels: dict[str, list[tuple[str, int, int]]] = {}
    for li in layout.layer_indexes():
        key = layer_key(layout.get_info(li))
        shapes = cell.shapes(li)
        texts = [s for s in shapes.each() if s.is_text()]
        if texts:
            labels.setdefault(key, []).extend(
                sorted((t.text.string, t.text.trans.disp.x, t.text.trans.disp.y) for t in texts)
            )
        region = kdb.Region(shapes)  # Region ignores TEXT; paths/boxes become polygons
        region.merge()
        if not region.is_empty():
            drawn[key] = region
    for key in labels:
        labels[key].sort()
    return {"layout": layout, "cell": cell, "dbu": layout.dbu, "drawn": drawn, "labels": labels}


def bbox_um(box: Any, dbu: float) -> dict[str, float]:
    return {"left_um": box.left * dbu, "bottom_um": box.bottom * dbu,
            "right_um": box.right * dbu, "top_um": box.top * dbu}


def measure(kdb: Any, committed: dict[str, Any], regenerated: dict[str, Any],
            expected: list[str]) -> dict[str, Any]:
    problems: list[str] = []

    if committed["dbu"] != regenerated["dbu"]:
        problems.append(f"database unit differs: committed {committed['dbu']} vs "
                        f"regenerated {regenerated['dbu']}; the XOR would be meaningless")
    dbu = committed["dbu"]
    scale = dbu * dbu  # dbu^2 -> um^2

    # ---- (1) the drawn-pair enumeration, asserted by name ----
    present = sorted(set(committed["drawn"]) | set(regenerated["drawn"]),
                     key=lambda k: tuple(int(x) for x in k.split("/")))
    enumeration = {
        "expected": list(expected),
        "in_committed": sorted(committed["drawn"], key=lambda k: tuple(int(x) for x in k.split("/"))),
        "in_regenerated": sorted(regenerated["drawn"], key=lambda k: tuple(int(x) for x in k.split("/"))),
        "unexpected_in_committed": sorted(set(committed["drawn"]) - set(expected)),
        "unexpected_in_regenerated": sorted(set(regenerated["drawn"]) - set(expected)),
        "expected_but_absent_in_committed": sorted(set(expected) - set(committed["drawn"])),
        "expected_but_absent_in_regenerated": sorted(set(expected) - set(regenerated["drawn"])),
    }
    for field, msg in (
        ("unexpected_in_committed", "drawn layer(s) in the committed stream not in --expect-drawn-layer"),
        ("unexpected_in_regenerated", "drawn layer(s) in the regenerated stream not in --expect-drawn-layer"),
        ("expected_but_absent_in_committed", "expected drawn layer(s) absent from the committed stream"),
        ("expected_but_absent_in_regenerated", "expected drawn layer(s) absent from the regenerated stream"),
    ):
        if enumeration[field]:
            problems.append(f"{msg}: {', '.join(enumeration[field])}")
    enumeration["match"] = not problems

    # ---- (2) per-pair XOR over the union of both streams' drawn pairs ----
    empty = kdb.Region()
    layers = []
    for key in present:
        a = committed["drawn"].get(key, empty)
        b = regenerated["drawn"].get(key, empty)
        x = (a ^ b)
        x.merge()
        area_dbu2 = x.area()
        entry = {
            "layer_datatype": key,
            "expected": key in expected,
            "committed_polygons": a.count(),
            "regenerated_polygons": b.count(),
            "committed_area_dbu2": a.area(),
            "regenerated_area_dbu2": b.area(),
            "xor_polygons": x.count(),
            "xor_area_dbu2": area_dbu2,
            "xor_area_um2": area_dbu2 * scale,
            "xor_empty": x.is_empty(),
        }
        if not entry["xor_empty"]:
            entry["xor_bbox_um"] = bbox_um(x.bbox(), dbu)
            problems.append(f"layer {key}: XOR is NOT empty -- {entry['xor_polygons']} polygon(s), "
                            f"{entry['xor_area_um2']:.6f} um^2")
        layers.append(entry)

    # ---- (3) bounding box of the flattened top cell ----
    cb, rb = committed["cell"].bbox(), regenerated["cell"].bbox()
    bbox = {
        "committed_dbu": [cb.left, cb.bottom, cb.right, cb.top],
        "regenerated_dbu": [rb.left, rb.bottom, rb.right, rb.top],
        "committed_um": bbox_um(cb, dbu),
        "regenerated_um": bbox_um(rb, dbu),
        "match": cb == rb,
    }
    if not bbox["match"]:
        problems.append(f"bounding box differs: committed {bbox['committed_um']} vs "
                        f"regenerated {bbox['regenerated_um']}")

    # ---- (4) labels, on their own layer/texttype pairs ----
    label_keys = sorted(set(committed["labels"]) | set(regenerated["labels"]),
                        key=lambda k: tuple(int(x) for x in k.split("/")))
    label_pairs = []
    label_total = 0
    for key in label_keys:
        ca = committed["labels"].get(key, [])
        rb_ = regenerated["labels"].get(key, [])
        label_total += len(ca)
        entry = {"layer_texttype": key, "committed_labels": len(ca), "regenerated_labels": len(rb_),
                 "match": ca == rb_}
        if not entry["match"]:
            only_c = [x for x in ca if x not in rb_]
            only_r = [x for x in rb_ if x not in ca]
            entry["only_in_committed"] = [{"string": s, "x_dbu": x, "y_dbu": y} for s, x, y in only_c[:20]]
            entry["only_in_regenerated"] = [{"string": s, "x_dbu": x, "y_dbu": y} for s, x, y in only_r[:20]]
            problems.append(f"label pair {key}: {len(only_c)} label(s) only in committed, "
                            f"{len(only_r)} only in regenerated")
        label_pairs.append(entry)
    labels = {
        "pairs": label_pairs,
        "committed_total": label_total,
        "regenerated_total": sum(len(v) for v in regenerated["labels"].values()),
        "overlap_with_drawn_layers": sorted(set(label_keys) & set(expected)),
        "match": all(p["match"] for p in label_pairs),
    }
    if labels["overlap_with_drawn_layers"]:
        problems.append("label layer/texttype pair(s) collide with the drawn enumeration: "
                        f"{', '.join(labels['overlap_with_drawn_layers'])}")

    return {
        "database_unit_um": dbu,
        "enumeration": enumeration,
        "layers": layers,
        "bbox": bbox,
        "labels": labels,
        "problems": problems,
        "xor_empty_on_every_drawn_layer": all(e["xor_empty"] for e in layers),
        "result": "equivalent" if not problems else "not-equivalent",
    }


def repo_relative(p: Path) -> str:
    """Repo-root-relative, or `<outside-repo>/<name>` for anything else.

    A committed record must not embed host paths (the existing
    generation_reproduction_*.json records do, which is part of what `klt
    env-provenance` exists to lint). A scratch GDS lives outside the repo by
    construction, so its path carries no reproducible information -- the
    recorded sha256 is its identity. Reduce it to its basename rather than
    stamping somebody's `/tmp` and home directory into evidence.
    """
    p = p.resolve()
    try:
        return str(p.relative_to(REPO_ROOT))
    except ValueError:
        return f"<outside-repo>/{p.name}"


def sha256_file(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def toolchain_stamp(python: str | None) -> dict[str, Any] | None:
    """Probe an interpreter for its klayout-tools/klayout identity, or None."""
    if not python:
        return None
    ident, error = T.probe(python)
    if error:
        die(f"could not probe the toolchain interpreter {python}: {error}")
    return {
        "python_version": ident.get("python_version"),
        "klayout_tools_version": ident.get("klayout_tools_version"),
        "klayout_tools_commit": ident.get("klayout_tools_commit"),
        "klayout_version": ident.get("klayout_version"),
    }


def git_source() -> dict[str, Any]:
    def run(*a):
        p = subprocess.run(["git", "-C", str(REPO_ROOT), *a], capture_output=True, text=True)
        return p.stdout.strip() if p.returncode == 0 else None
    status = run("status", "--porcelain")
    return {"commit": run("rev-parse", "HEAD"), "dirty": bool(status) if status is not None else None}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--committed", required=True, type=Path, help="the committed GDS (reference)")
    ap.add_argument("--regenerated", required=True, type=Path, help="the regenerated GDS under test")
    ap.add_argument("--top", required=True, help="top cell name; must exist in both streams")
    ap.add_argument("--expect-drawn-layer", action="append", metavar="L/D", default=None,
                    help=f"drawn layer/datatype pair to assert over, repeatable "
                         f"(default: the committed 4x4 set, {', '.join(DEFAULT_DRAWN_LAYERS)})")
    ap.add_argument("--committed-toolchain-python", help="interpreter whose klt produced --committed")
    ap.add_argument("--regenerated-toolchain-python", help="interpreter whose klt produced --regenerated")
    ap.add_argument("--commands-file", type=Path,
                    help="file of commands that produced --regenerated, recorded verbatim")
    ap.add_argument("--note", help="free-text note stored in the record")
    ap.add_argument("-o", "--output", type=Path, help="write the JSON evidence record here")
    args = ap.parse_args(argv)

    kdb = require_klayout()
    expected = list(args.expect_drawn_layer) if args.expect_drawn_layer else list(DEFAULT_DRAWN_LAYERS)

    committed = flattened(kdb, args.committed, args.top)
    regenerated = flattened(kdb, args.regenerated, args.top)
    m = measure(kdb, committed, regenerated, expected)

    cfg = T.load_config()
    commands = []
    if args.commands_file and args.commands_file.is_file():
        commands = args.commands_file.read_text().splitlines()
    record = {
        "schema_version": SCHEMA_VERSION,
        "kind": RECORD_KIND,
        "recorded_at_utc": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "script": "layout/xor_layout_geometry.py",
        "measurement": "flattened per-layer-datatype XOR, bounding box and label set of one top cell "
                       "in two GDS streams; hierarchy- and structure-name-insensitive by construction",
        "note": args.note,
        "source": git_source(),
        "top_cell": args.top,
        "streams": {
            "committed": {"path": repo_relative(args.committed), "sha256": sha256_file(args.committed)},
            "regenerated": {"path": repo_relative(args.regenerated), "sha256": sha256_file(args.regenerated)},
        },
        "toolchains": {
            # Pin IDENTITY only, not generation-toolchain.json's `verified` prose:
            # that field cites this record, so copying it in here would make the
            # record quote the sentence it is the evidence for.
            "pins": {role: {"klayout_tools_version": rc["klayout_tools"]["package_version"],
                            "klayout": rc["klayout"]}
                     for role, rc in cfg["toolchains"].items()},
            "committed": toolchain_stamp(args.committed_toolchain_python),
            "regenerated": toolchain_stamp(args.regenerated_toolchain_python),
            "measurement_klayout_version": getattr(__import__("klayout"), "__version__", None),
        },
        "pdk": {"pin": cfg["pdk"]},
        "commands": commands,
        **m,
    }

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(record, indent=2) + "\n")

    print(f"   top cell: {args.top}   dbu: {m['database_unit_um']} um")
    print(f"   drawn-layer enumeration ({len(expected)} expected): "
          f"{'MATCH' if m['enumeration']['match'] else 'MISMATCH'}")
    for e in m["layers"]:
        flag = "XOR EMPTY" if e["xor_empty"] else f"XOR {e['xor_polygons']} poly / {e['xor_area_um2']:.6f} um^2"
        star = " " if e["expected"] else "!"
        print(f"   {star} {e['layer_datatype']:<8} committed {e['committed_polygons']:>4} poly  "
              f"regenerated {e['regenerated_polygons']:>4} poly   {flag}")
    print(f"   bbox: {'MATCH' if m['bbox']['match'] else 'MISMATCH'}  "
          f"({m['bbox']['committed_um']['left_um']},{m['bbox']['committed_um']['bottom_um']} ; "
          f"{m['bbox']['committed_um']['right_um']},{m['bbox']['committed_um']['top_um']}) um")
    print(f"   labels: {'MATCH' if m['labels']['match'] else 'MISMATCH'}  "
          f"{m['labels']['committed_total']} committed / {m['labels']['regenerated_total']} regenerated on "
          f"{', '.join(p['layer_texttype'] for p in m['labels']['pairs']) or '(none)'}")
    for p in m["problems"]:
        print(f"   FAIL: {p}", file=sys.stderr)
    print(f"   geometry equivalence: {m['result']}")
    if args.output:
        print(f"   evidence record: {repo_relative(args.output)}")
    return 0 if m["result"] == "equivalent" else 1


if __name__ == "__main__":
    sys.exit(main())
