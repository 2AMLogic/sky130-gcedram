#!/usr/bin/env python3
"""Compact-layout C_SN and retention-budget re-check (issue #161).

CAPACITANCE-ONLY SENSITIVITY WITH GEOMETRY-MATCHED LEAKAGE -- NOT MEASURED ARRAY
RETENTION, NOT A RATIFIED VALUE, NOT A SPEC CHANGE.

Re-runs the evidence chain of ``compare_array_c_sn.py`` (issue #89) for the compact
bitcell layouts of issue #100 (v2 = density-relevant, v1 for reference), with the three
links kept explicit and each tied to committed inputs:

  1. LEAKAGE   worst-case (``sf`` / 125 C) access-device off-state current measured with
               each layout's EXTRACTED drawn diffusion, from the ``klt sim`` batch report
               reduced by ``sim/leakage/compact_geometry_leakage.py``
               (``--leakage-summary``);
  2. C_SN      wiring storage-node capacitance per node (ground + all coupling, the same
               convention as ``derive_retention.load_extracted_c_sn``; ASSUMPTION-LABELLED
               as a total because device gate/junction capacitance is excluded) from the
               committed ``klt extract --parasitics`` reports;
  3. DERIVATION ``t = C_SN * delta_V / I_leak`` with the existing delta_V = VDD/2 ASSUMPTION,
               compared with the ratified Section 5 retention (``retention_results.csv``)
               and its 2x-safety refresh interval (``spec/retention-refresh-budget.md`` Section 7).

It never writes ``retention_results.csv`` and never edits the spec: whether the ratified
budget holds is REPORTED (``budget_check``); a failure is an operator decision.
Output: a NEW ``results/compact_c_sn_<UTC>.json`` (an existing file is never overwritten).

Usage (repo root; stdlib only):

    python3 -I sim/retention/compare_compact_c_sn.py --leakage-summary FILE            # print
    python3 -I sim/retention/compare_compact_c_sn.py --leakage-summary FILE --write
    python3 -I sim/retention/compare_compact_c_sn.py --check results/compact_c_sn_<ts>.json
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import compare_array_c_sn as CA  # noqa: E402
import derive_retention as DR  # noqa: E402

REPO_ROOT = DR.REPO_ROOT
sys.path.insert(0, str(REPO_ROOT / "layout"))
import compact_parasitics as CP  # noqa: E402

RESULTS_DIR = HERE / "results"
OUTPUT_PREFIX = "compact_c_sn_"
SCHEMA = "gcedram.compact_c_sn/1"
LABEL = (
    "CAPACITANCE-ONLY SENSITIVITY at GEOMETRY-MATCHED leakage and the unchanged delta_V = VDD/2 "
    "ASSUMPTION. Wiring C_SN only (device gate/junction capacitance excluded). Not measured array "
    "retention, not dynamic, not a ratified value, not an array guarantee."
)
WORST_CASE = {"corner": "sf", "temp_c": 125}
# spec/retention-refresh-budget.md Section 7: refresh_interval = t_retention / 2 (ASSUMED 2x margin).
SAFETY_FACTOR = 2.0
LAYOUT_KEYS = (("uniform_grid", "base"), ("compact_v2", "v2"), ("compact_v1", "v1"))
VOLATILE_KEYS = ("generated_utc", "repo_git_sha")


def rel(p: Path) -> str:
    return CA.rel(p)


def load_leakage(path: Path) -> dict:
    s = json.loads(Path(path).read_text())
    if s.get("issue") != 161 or "worst_case" not in s:
        raise CA.ComparisonError(f"{path} is not a compact-geometry leakage summary (issue 161)")
    for _, tag in LAYOUT_KEYS:
        wc = s["worst_case"].get(tag)
        if not wc or (wc["corner"], wc["temp_c"]) != (WORST_CASE["corner"], WORST_CASE["temp_c"]):
            raise CA.ComparisonError(
                f"{path}: worst case of {tag!r} is {wc}, not {WORST_CASE}; retention claims are made at the "
                "worst-case corner, re-read the study before comparing")
        if not (wc["i_a"] > 0):
            raise CA.ComparisonError(f"{path}: non-positive leakage for {tag!r}")
    return s


def layout_inputs() -> dict:
    return {"uniform_grid": CP.LAYOUTS["uniform_grid"][0], "compact_v2": CP.LAYOUTS["compact_v2"][0],
            "compact_v1": CP.LAYOUTS["compact_v1"][0]}


def node_table(report_path: Path) -> list[dict]:
    """Per storage node: ground / coupling / total, cross-checked against the default reader."""
    data = json.loads(Path(report_path).read_text())
    entries = CP.sn_entries(data)
    nodes = []
    for name, e in entries.items():
        total, _ = DR.load_extracted_c_sn(Path(report_path), name)
        if abs(total - e["total_ff"]) > 1e-5:
            raise CA.ComparisonError(f"{name}: default reader {total} disagrees with reduction {e['total_ff']}")
        nodes.append({"net": name, "ground_ff": e["ground_ff"], "coupling_ff": e["coupling_ff"],
                      "total_ff": e["total_ff"], "coupled_ff": e["coupled_ff"]})
    return sorted(nodes, key=lambda n: (n["total_ff"], n["net"]))


def retention_s(c_ff: float, dv: float, i_a: float) -> float:
    return CA.retention_s(c_ff, dv, i_a)


def point(c_ff: float, dv: float, i_a: float, t_ratified: float) -> dict:
    t = retention_s(c_ff, dv, i_a)
    return {"c_sn_ff": round(c_ff, 6), "retention_time_us": round(t * 1e6, 4),
            "refresh_interval_us_at_2x_safety": round(t / SAFETY_FACTOR * 1e6, 4),
            "ratio_t_over_ratified": round(t / t_ratified, 6)}


def build(leakage_summary: Path, retention_csv: Path = CA.RETENTION_CSV, retention_as_of: str | None = None) -> dict:
    leak = load_leakage(leakage_summary)
    single_path = Path(DR.EXTRACTED_C_SN_SOURCES[CA.SINGLE_GEOMETRY]["extract_json"])
    single_net = DR.EXTRACTED_C_SN_SOURCES[CA.SINGLE_GEOMETRY]["net"]
    single_data = CA.load_report(single_path)
    single = CA.node_capacitance(single_path, single_data, single_net)
    single_prov = CA.report_provenance(single_path, single_data)
    base = CA.baseline_rows(retention_csv, single["total_ff"], single_prov["input_content_hash"], retention_as_of)
    ratified, isolated = CA.describe_row(retention_csv, base["ratified"]), CA.describe_row(retention_csv, base["isolated"])
    dv = isolated["delta_v_sense_margin_v_ASSUMPTION"]
    t_rat = ratified["retention_time_s"]
    c_gate_ff = float(base["ratified"][2]["c_gate_read_transistor_ff"])

    layouts = {}
    for name, tag in LAYOUT_KEYS:
        path = layout_inputs()[name]
        nodes = node_table(path)
        data = json.loads(path.read_text())
        i_a = leak["worst_case"][tag]["i_a"]
        lo, hi = nodes[0], nodes[-1]
        tied = [n["net"] for n in nodes if round(n["total_ff"], CA.TIE_DECIMALS) == round(lo["total_ff"], CA.TIE_DECIMALS)]
        c_req = t_rat * i_a / dv * 1e15
        layouts[name] = {
            "extraction": {**CA.report_provenance(path, data)},
            "node_count": len(nodes),
            "limiting_node": lo["net"], "nodes_tied_at_minimum": tied,
            "c_sn_total_ff": {"min": lo["total_ff"], "max": hi["total_ff"],
                              "mean": round(sum(n["total_ff"] for n in nodes) / len(nodes), 6)},
            "c_sn_ground_ff": {"min": min(n["ground_ff"] for n in nodes), "max": max(n["ground_ff"] for n in nodes)},
            "c_sn_coupling_ff": {"min": min(n["coupling_ff"] for n in nodes), "max": max(n["coupling_ff"] for n in nodes)},
            "ratio_min_c_sn_over_isolated_cell": round(lo["total_ff"] / single["total_ff"], 6),
            "leakage": {"ileak_a": i_a, **WORST_CASE, "geometry_matched": True,
                        "source": rel(Path(leakage_summary)), "leakage_tag": tag},
            "at_limiting_node": point(lo["total_ff"], dv, i_a, t_rat),
            "at_max_node": point(hi["total_ff"], dv, i_a, t_rat),
            "c_sn_required_for_ratified_retention_ff": round(c_req, 6),
            "shortfall_vs_required_ff": round(c_req - lo["total_ff"], 6),
            "per_node": {n["net"]: round(n["total_ff"], 6) for n in nodes},
            "bounding_scenario_wiring_plus_full_cgate": {
                "note": ("UPPER-BOUND-STYLE scenario, not a result: adds the computed C_gate of the read transistor "
                         f"({c_gate_ff} fF, retention_results.csv) on top of the wiring C_SN. May count the poly term "
                         "twice (the extractor's poly area may overlap the channel; unchecked, spec Section 9.6 item 2) "
                         "and still omits the write-device drain-junction capacitance."),
                **point(lo["total_ff"] + c_gate_ff, dv, i_a, t_rat)},
        }

    v2 = layouts["compact_v2"]
    holds = v2["at_limiting_node"]["retention_time_us"] * 1e-6 >= t_rat
    holds_generous = v2["bounding_scenario_wiring_plus_full_cgate"]["retention_time_us"] * 1e-6 >= t_rat
    budget = {
        "ratified_retention_s": t_rat, "ratified_retention_source": ratified["source"],
        "ratified_c_sn_ff_ASSUMPTION": ratified["c_storage_node_ff"],
        "ratified_refresh_interval_us": round(t_rat / SAFETY_FACTOR * 1e6, 4),
        "safety_factor_ASSUMPTION": SAFETY_FACTOR,
        "safety_factor_source": "spec/retention-refresh-budget.md Section 7 (ASSUMED 2x margin)",
        "delta_v_v_ASSUMPTION": dv,
        "criterion": ("the ratified ~5.03 us refresh interval stays valid iff t_retention >= the ratified 10.06 us at "
                      "the same 2x margin, i.e. iff C_SN >= the 'c_sn_required_for_ratified_retention_ff' of the layout"),
        "compact_v2_wiring_only_holds": holds,
        "compact_v2_wiring_plus_full_cgate_holds": holds_generous,
        "finding": (
            "HOLDS on the evidence" if holds else
            "DOES NOT HOLD on extracted wiring C_SN at geometry-matched worst-case leakage"
            + ("; also does not hold with the full read-gate capacitance added (bounding scenario)"
               if not holds_generous else
               "; would hold only if the full read-gate capacitance is added (bounding scenario, may double-count)")),
        "action": ("Not a spec edit. The ratified pre-layout C_SN is an ASSUMPTION (2.0x C_gate); the extraction does not "
                   "support it. Report as an operator decision (see sim/retention/README.md)."
                   if not holds else "No action."),
    }
    return {
        "schema": SCHEMA, "issue": 161, "label": LABEL,
        "generated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "repo_git_sha": DR.repo_git_sha(HERE),
        "convention": ("total_ff = ground_ff + sum(coupled[].capacitance_ff), as derive_retention.load_extracted_c_sn(). "
                       "Storage nodes of the compact layouts are anonymous nets identified from device connectivity "
                       "(layout/compact_parasitics.py storage_nodes). Wiring only."),
        "inputs": {"leakage_summary": {"path": rel(Path(leakage_summary)), "sha256": CA.sha256_file(Path(leakage_summary))},
                   "single_cell_report": single_prov, "retention_csv_rows": [ratified["source"], isolated["source"]]},
        "single_cell": single,
        "retention_baselines": {"ratified_prelayout": ratified, "isolated_cell_extracted": isolated},
        "layouts": layouts,
        "budget_check": budget,
        "limitations": [
            "Wiring-only C_SN: device gate and junction capacitance are excluded (spec Section 9.6 item 2 remains open); the bounding scenario is not a measurement.",
            "Leakage is the SN-side-junction DC off-state current of ONE write device (drain at VDD, bit line at 0 V), as in #2/#149; the read device and hold-state dynamics are not included.",
            "Quiet-neighbour coupling counted as load; dynamic neighbour switching is #94.",
            "4x4 arrays only; boundary nodes limit. Constant-current decay, delta_V = VDD/2 and no mismatch are the existing ASSUMPTIONS.",
            "Worst-case corner only (sf / 125 C); the leakage study confirms it is the worst for all three geometries.",
        ],
    }


def strip(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k not in VOLATILE_KEYS}


def summary_lines(doc: dict) -> list[str]:
    out = [f"[{doc['label']}]"]
    for name, l in doc["layouts"].items():
        a = l["at_limiting_node"]
        out.append(f"{name}: C_SN {l['c_sn_total_ff']['min']:.6f}..{l['c_sn_total_ff']['max']:.6f} fF (limiting {l['limiting_node']}), "
                   f"I_leak {l['leakage']['ileak_a']:.4e} A -> t {a['retention_time_us']} us, refresh<= {a['refresh_interval_us_at_2x_safety']} us "
                   f"(need C >= {l['c_sn_required_for_ratified_retention_ff']} fF)")
    b = doc["budget_check"]
    out.append(f"ratified: t {b['ratified_retention_s']:.6e} s, refresh {b['ratified_refresh_interval_us']} us -> {b['finding']}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--leakage-summary", type=Path, help="sim/leakage/compact-geometry/results/compact_leakage_summary_<RUN>.json")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--write", action="store_true")
    g.add_argument("--check", metavar="FILE")
    a = ap.parse_args(argv)
    try:
        if a.check:
            committed = json.loads(Path(a.check).read_text())
            leak = REPO_ROOT / committed["inputs"]["leakage_summary"]["path"]
            doc = build(leak, retention_as_of=committed["generated_utc"])
            if strip(committed) != json.loads(json.dumps(strip(doc))):
                print(f"DRIFT: {a.check} does not match a recomputation from the committed inputs", file=sys.stderr)
                return 1
            print(f"OK: {a.check} reproduces from the committed inputs")
            return 0
        if not a.leakage_summary:
            ap.error("--leakage-summary is required (except with --check)")
        doc = build(a.leakage_summary)
    except (CA.ComparisonError, CP.CompactError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    for line in summary_lines(doc):
        print(line)
    if a.write:
        stamp = doc["generated_utc"].replace("-", "").replace(":", "").replace("+0000", "Z")
        out = RESULTS_DIR / f"{OUTPUT_PREFIX}{stamp}.json"
        if out.exists():
            print(f"ERROR: {out} exists; results are append-only", file=sys.stderr)
            return 1
        out.write_text(json.dumps(doc, indent=1) + "\n")
        print(f"wrote {rel(out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
