#!/usr/bin/env python3
"""Compact-layout access-device leakage: deck/request generator + reducer (issue #161).

Stdlib only. Extends the geometry-matched study of issue #149
(``gen_geometry_leakage.py`` / ``analyze_geometry_leakage.py``) from the committed
uniform-grid array to the compact bitcell layouts of issue #100. Nothing is
hand-typed: the access-device geometry is read from the committed
``klt extract --parasitics`` reports of

* the uniform-grid 4x4 array  (``layout/gain_cell_2t_array.extract.parasitics.json``),
* the compact ``v2`` array    (``layout/compact/gain_cell_2t_v2_array.extract.parasitics.json``),
* the compact ``v1`` array    (``layout/compact/gain_cell_2t_v1_array.extract.parasitics.json``).

Why orientation matters here: in the compact layouts the storage node is an
anonymous net and the write device's drain/source labels are layout-dependent
(mirrored diffusion sharing), so the SN-side diffusion (the junction that leaks
the stored '1' away) is picked by connectivity -- the terminal that is NOT the
bit line -- and written as the DUT *drain* (held at VDD); the bit-line side is the
DUT source (0 V). Subthreshold current does not depend on AD/PD; the SN-side
junction term does.

``gen`` writes ``sim/leakage/compact-geometry/access_leakage_compact.spice`` and
``request.json`` (one ``klt sim`` corner request, 5 corners x 3 temperatures).
``reduce REPORT`` turns a committed ``results/klt_report_<RUN_ID>.json`` into NEW
``compact_leakage_points_<RUN_ID>.csv`` / ``compact_leakage_summary_<RUN_ID>.json``
files (refuses to overwrite: append-only evidence). ``--check-generated`` fails
when the committed deck/request are stale against the extractions.

Usage (repo root):

    python3 -I sim/leakage/compact_geometry_leakage.py gen
    klt sim sim/leakage/compact-geometry/request.json -o ... --report-out ...
    python3 -I sim/leakage/compact_geometry_leakage.py reduce REPORT
    python3 -I sim/leakage/compact_geometry_leakage.py --check-generated
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import gen_geometry_leakage as G  # noqa: E402
import analyze_geometry_leakage as AN  # noqa: E402
from klt_request import build_request as klt_request  # noqa: E402

OUT = HERE / "compact-geometry"
DECK_PATH = OUT / "access_leakage_compact.spice"
REQUEST_PATH = OUT / "request.json"

# (tag, extraction json) -- order is the deck/measurement order.
LAYOUTS = (
    ("base", REPO / "layout" / "gain_cell_2t_array.extract.parasitics.json"),
    ("v2", REPO / "layout" / "compact" / "gain_cell_2t_v2_array.extract.parasitics.json"),
    ("v1", REPO / "layout" / "compact" / "gain_cell_2t_v1_array.extract.parasitics.json"),
)
LEGACY = "leg"
TAGS = tuple(t for t, _ in LAYOUTS) + (LEGACY,)
BL_RE = G.BL_RE
WL_RE = G.WL_RE


def meas_name(tag: str) -> str:
    return f"ileak_{tag}_a"


class CompactError(ValueError):
    pass


def access_geometry(extraction: dict) -> dict:
    """The single access-device geometry of an extraction, SN side oriented as drain.

    Access device = gate on a wordline, one of drain/source on a bit line; the other
    terminal is the storage node (named ``sn_*`` in the uniform grid, anonymous in the
    compact layouts). Exactly one distinct oriented geometry must exist.
    """
    seen: dict[tuple, str] = {}
    for d in extraction.get("devices") or []:
        nets = d.get("nets") or {}
        if d.get("class") != "nfet" or not WL_RE.match(str(nets.get("g", ""))):
            continue
        p = d.get("params") or {}
        if BL_RE.match(str(nets.get("s", ""))) and not BL_RE.match(str(nets.get("d", ""))):
            sn, bl = "d", "s"
        elif BL_RE.match(str(nets.get("d", ""))) and not BL_RE.match(str(nets.get("s", ""))):
            sn, bl = "s", "d"
        else:
            raise CompactError(f"device {d.get('name')!r}: cannot orient bit line vs storage node ({nets})")
        try:
            vals = (float(p["l_um"]), float(p["w_um"]),
                    float(p[f"a{sn}_um2"]), float(p[f"p{sn}_um"]),
                    float(p[f"a{bl}_um2"]), float(p[f"p{bl}_um"]))
        except KeyError as e:
            raise CompactError(f"device {d.get('name')!r}: missing parameter {e}") from None
        if not all(math.isfinite(v) and v >= 0 for v in vals) or vals[0] <= 0 or vals[1] <= 0:
            raise CompactError(f"device {d.get('name')!r}: invalid geometry {vals}")
        seen.setdefault(vals, d.get("name"))
    if not seen:
        raise CompactError("no access device (gate=wl*, one terminal on bl*) in extraction")
    if len(seen) != 1:
        raise CompactError(f"heterogeneous access-device geometry ({len(seen)} distinct sets): {sorted(seen)}")
    (l, w, ad, pd, as_, ps), = seen
    return {"l_um": l, "w_um": w, "ad_um2": ad, "pd_um": pd, "as_um2": as_, "ps_um": ps}


def load_all() -> dict:
    out = {}
    for tag, path in LAYOUTS:
        ex = json.loads(path.read_text())
        out[tag] = {
            "geometry": access_geometry(ex),
            "input_path": str(path.relative_to(REPO)),
            "input_sha256": G.sha256_file(path),
            "top": ex.get("top"),
            "klt_version": (ex.get("provenance") or {}).get("klt_version"),
        }
    return out


def render_deck(info: dict) -> str:
    fmt = G.fmt
    lines = [
        "* access_leakage_compact.spice -- access-device off-state leakage with the extracted diffusion",
        "* geometry of the uniform-grid and compact bitcell layouts (issue #161).",
        "* GENERATED by compact_geometry_leakage.py from the committed klt extract --parasitics reports; do not edit.",
        "*",
        "* CIRCUIT BODY for `klt sim`: no .control/.end; the PDK .lib/.temp cards are appended per corner by klt.",
        "* Bias identical to sim/leakage/tb_access_leakage.spice.tmpl: drain (storage-node side) = VDD, gate = source",
        "* = body = 0 V. The DUT drain carries the STORAGE-NODE-side diffusion (ad/pd), the source the bit-line side",
        "* (as/ps); units um / um^2 via the PDK's .option scale=1u. DUTs (all in one batch, same engine/PDK):",
    ]
    for tag, _ in LAYOUTS:
        g = info[tag]["geometry"]
        lines.append(f"*   x{tag}: {info[tag]['input_path']}  ad={g['ad_um2']} pd={g['pd_um']} as={g['as_um2']} ps={g['ps_um']}")
    lines.append("*   xleg : legacy testbench card (l=0.15 w=0.42, no diffusion parameters) -- same-batch CONTROL")
    lines.append(f".param VDD = {G.VDD_V}")
    for tag, _ in LAYOUTS:
        g = info[tag]["geometry"]
        lines.append(f"vsn_{tag} sn_{tag} 0 dc {{VDD}}")
        lines.append(f"x{tag} sn_{tag} 0 0 0 {G.DEVICE} l={fmt(g['l_um'])} w={fmt(g['w_um'])} "
                     f"ad={fmt(g['ad_um2'])} as={fmt(g['as_um2'])} pd={fmt(g['pd_um'])} ps={fmt(g['ps_um'])}")
    lines.append(f"vsn_{LEGACY} sn_{LEGACY} 0 dc {{VDD}}")
    lines.append(f"x{LEGACY} sn_{LEGACY} 0 0 0 {G.DEVICE} l={fmt(G.LEGACY_L_UM)} w={fmt(G.LEGACY_W_UM)}")
    lines.append("* |I(vsn_*)| as a node voltage (1 V per A) so a .meas card can read it; the dc sweep steps vsn_base only")
    lines.append("* (1.8 -> 1.9 V); every observation is taken AT=1.8 V, the specified bias.")
    for tag in TAGS:
        lines.append(f"biabs_{tag} iabs_{tag} 0 v=abs(i(vsn_{tag}))")
    return "\n".join(lines) + "\n"


def build_request() -> dict:
    return klt_request(
        DECK_PATH.name, {"process": list(G.PROCESS_CORNERS), "temperature_c": list(G.TEMPS_C)},
        "vsn_base 1.8 1.9 0.1",
        [{"name": meas_name(t), "unit": "A", "spice": f".meas dc {meas_name(t)} FIND v(iabs_{t}) AT=1.8"}
         for t in TAGS],
        600, kind="dc", extra_options={"ngspice_init": ["set measureprec=12", "set numdgt=12"]})


def render_request() -> str:
    return json.dumps(build_request(), indent=2) + "\n"


def check_generated() -> int:
    info = load_all()
    bad = [p.name for p, want in ((DECK_PATH, render_deck(info)), (REQUEST_PATH, render_request()))
           if not p.is_file() or p.read_text() != want]
    if bad:
        print(f"STALE: {bad} do not match the committed extractions (re-run `gen`)", file=sys.stderr)
        return 1
    print("OK: committed deck/request match the extractions")
    return 0


def extract_points(report: dict) -> dict:
    """{(corner, temp_c): {tag: amps}} -- exactly the request's Cartesian product."""
    request = build_request()
    AN.check_identity(report, DECK_PATH)
    if report.get("status") != "pass" or report.get("errored") or report.get("failed"):
        raise AN.AnalysisError(f"report not successful: status={report.get('status')!r} "
                               f"failed={report.get('failed')} errored={report.get('errored')}")
    want = {(p, t) for p in request["corners"]["process"] for t in request["corners"]["temperature_c"]}
    out: dict = {}
    for c in report.get("corners") or []:
        key = (c.get("process"), c.get("temperature_c"))
        if key in out:
            raise AN.AnalysisError(f"duplicate PVT point {key}")
        if c.get("status") != "pass":
            raise AN.AnalysisError(f"corner {key} status {c.get('status')!r}")
        m = {}
        for e in c.get("measurements") or []:
            if e["name"] in m:
                raise AN.AnalysisError(f"corner {key}: duplicate measurement {e['name']}")
            if e.get("status") != "pass" or e.get("unit") != "A":
                raise AN.AnalysisError(f"corner {key}: measurement {e['name']} status/unit {e.get('status')!r}/{e.get('unit')!r}")
            m[e["name"]] = e.get("value")
        out[key] = {}
        for t in TAGS:
            if meas_name(t) not in m:
                raise AN.AnalysisError(f"corner {key}: missing measurement {meas_name(t)}")
            out[key][t] = AN._finite_pos(m[meas_name(t)], f"{key} {meas_name(t)}")
    if set(out) != want:
        raise AN.AnalysisError(f"PVT set mismatch: missing {sorted(want - set(out))}, unexpected {sorted(set(out) - want)}")
    return out


def build_rows(points: dict) -> list[dict]:
    rows = []
    for (corner, temp) in sorted(points, key=lambda k: (G.PROCESS_CORNERS.index(k[0]), k[1])):
        v = points[(corner, temp)]
        row = {"corner": corner, "temp_c": temp}
        for t in TAGS:
            row[f"i_{t}_a"] = f"{v[t]:.9e}"
        row["ratio_v2_over_base"] = f"{v['v2'] / v['base']:.6f}"
        row["ratio_v1_over_base"] = f"{v['v1'] / v['base']:.6f}"
        row["ratio_v2_over_legacy"] = f"{v['v2'] / v['leg']:.6f}"
        rows.append(row)
    return rows


def summarize(rows: list[dict], points: dict, report: dict, info: dict, paths: dict) -> dict:
    def worst(tag: str) -> dict:
        key = max(points, key=lambda k: (points[k][tag], k))
        return {"corner": key[0], "temp_c": key[1], "i_a": points[key][tag]}
    env = report.get("environment", {})
    return {
        "issue": 161,
        "comparison_label": ("access-device off-state leakage with the EXTRACTED drawn diffusion of each layout; "
                             "'base' = uniform-grid array (the #149 geometry), 'leg' = legacy testbench card "
                             "(no diffusion parameters). Leakage only: not a retention number."),
        "n_points": len(rows),
        "geometry": {t: info[t]["geometry"] for t in TAGS[:-1]},
        "geometry_units": {"l,w,pd,ps": "um", "ad,as": "um^2"},
        "orientation": "ad/pd = storage-node-side diffusion (DUT drain, held at VDD); as/ps = bit-line side (DUT source, 0 V)",
        "extraction_inputs": {t: {k: info[t][k] for k in ("input_path", "input_sha256", "top", "klt_version")}
                              for t in TAGS[:-1]},
        "worst_case": {t: worst(t) for t in TAGS},
        "worst_case_ratio_v2_over_base": round(worst("v2")["i_a"] / worst("base")["i_a"], 6),
        "worst_case_ratio_v1_over_base": round(worst("v1")["i_a"] / worst("base")["i_a"], 6),
        "pdk_open_pdks_commit": AN.G_pin(),
        "engine": {"engine": env.get("engine"), "engine_version": env.get("engine_version")},
        "batch": env.get("remote"), "models_lib_sha256": env.get("models_lib_sha256"),
        "netlist_sha256_reported": env.get("netlist_sha256"),
        "klt_provenance": report.get("provenance"),
        "files": paths,
    }


def cmd_reduce(report_path: Path) -> int:
    run_id = report_path.stem.split("klt_report_", 1)[1]
    pts = report_path.with_name(f"compact_leakage_points_{run_id}.csv")
    summ = report_path.with_name(f"compact_leakage_summary_{run_id}.json")
    for p in (pts, summ):
        if p.exists():
            print(f"refusing to overwrite existing evidence file {p}", file=sys.stderr)
            return 2
    rep = json.loads(report_path.read_text())
    try:
        info = load_all()
        if DECK_PATH.read_text() != render_deck(info):
            raise AN.AnalysisError("generated deck does not match the extractions (stale deck?)")
        points = extract_points(rep)
        rows = build_rows(points)
    except (AN.AnalysisError, CompactError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    with pts.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    rel = lambda p: str(Path(p).resolve().relative_to(REPO))  # noqa: E731
    paths = {"deck_sha256": G.sha256_file(DECK_PATH), "request_sha256": G.sha256_file(REQUEST_PATH),
             "report": rel(report_path), "report_sha256": G.sha256_file(report_path), "points_csv": rel(pts)}
    summ.write_text(json.dumps(summarize(rows, points, rep, info, paths), indent=2) + "\n")
    print(f"wrote {pts} and {summ}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("gen", help="write the deck and klt sim request")
    r = sub.add_parser("reduce", help="reduce a committed klt report into new points/summary files")
    r.add_argument("report", type=Path)
    ap.add_argument("--check-generated", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.check_generated:
            return check_generated()
        if a.cmd == "gen":
            info = load_all()
            OUT.mkdir(exist_ok=True)
            DECK_PATH.write_text(render_deck(info))
            REQUEST_PATH.write_text(render_request())
            print(f"wrote {DECK_PATH} and {REQUEST_PATH}")
            return 0
        if a.cmd == "reduce":
            return cmd_reduce(a.report)
    except CompactError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
