#!/usr/bin/env python3
"""Array-context storage-node capacitance comparison (issue #89).

CAPACITANCE-ONLY SENSITIVITY -- NOT MEASURED ARRAY RETENTION, NOT AN ARRAY
GUARANTEE, NOT A RATIFIED VALUE.

Reduces every storage node ``sn_<row>_<col>`` in the committed 4x4 array
parasitics extraction (``layout/gain_cell_2t_array.extract.parasitics.json``,
issue #80) with the *same* reader and convention the default retention path
uses for the isolated cell (``derive_retention.load_extracted_c_sn()``:
total = lumped ground capacitance + every coupling capacitor reported on the
net). It then compares, side by side and kept distinct:

  1. the RATIFIED pre-layout estimate (spec/retention-refresh-budget.md
     Section 5, the assumption-based ``2T-min`` row of retention_results.csv);
  2. the isolated-cell EXTRACTED estimate (the ``2T-min`` row whose C_SN came
     from ``layout/gain_cell_2t.extract.parasitics.json``, issue #7);
  3. the array CAPACITANCE-ONLY SENSITIVITY: the isolated-cell extracted
     estimate scaled by ``C_array / C_single`` at the *unchanged* leakage and
     sense margin of row 2 (``t = C * delta_V / I_leak`` is linear in C).

Every ratio is computed here from the committed reports and CSV rows; none is
hardcoded. The script also traces the drain/source diffusion geometry
(AD/AS/PD/PS) of the leakage testbench, the schematic netlist and the
extracted devices, so the geometry mismatch behind the leakage term is
recorded with source provenance (see the "leakage_geometry_trace" block).

This module does not change the default derivation: it imports
``derive_retention`` only to reuse ``load_extracted_c_sn()`` and
``EXTRACTED_C_SN_SOURCES``, and it never writes ``retention_results.csv``.
Its output is a separate, new, timestamped JSON file under ``results/``;
an existing output file is never overwritten (append-only evidence).

Usage (repo root; stdlib only -- no PDK, ngspice or klt needed):

    python3 -I sim/retention/compare_array_c_sn.py            # print summary
    python3 -I sim/retention/compare_array_c_sn.py --write    # new results JSON
    python3 -I sim/retention/compare_array_c_sn.py --check FILE
        # recompute from the committed inputs and compare with FILE
        # (everything except generated_utc / repo_git_sha); exit 1 on drift
"""

from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import json
import math
import re
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import derive_retention as DR  # noqa: E402  (reuse the default reader)

REPO_ROOT = DR.REPO_ROOT
RESULTS_DIR = HERE / "results"
OUTPUT_PREFIX = "array_c_sn_comparison_"

SCHEMA = "gcedram.array_c_sn_comparison/1"
LABEL = (
    "CAPACITANCE-ONLY SENSITIVITY: array-context C_SN at unchanged leakage "
    "(leakage testbench geometry) and unchanged sense-margin ASSUMPTION. Not "
    "measured array retention, not geometry-matched, not dynamic, not a "
    "ratified value, not an array guarantee."
)

ARRAY_REPORT = REPO_ROOT / "layout" / "gain_cell_2t_array.extract.parasitics.json"
SINGLE_GEOMETRY = "2T-min"
RETENTION_CSV = DR.RESULTS_CSV
LEAKAGE_TEMPLATE = HERE.parent / "leakage" / "tb_access_leakage.spice.tmpl"
SCHEMATIC_NETLIST = REPO_ROOT / "design" / "gain_cell_2t.spice"

SN_NET_RE = re.compile(r"^sn_(\d+)_(\d+)$")
GEOMETRY_KEYS = ("ad", "as", "pd", "ps")
# Tie tolerance for selecting the limiting node: the reports carry 6
# decimals in fF, so totals equal to 1e-9 fF are the same reported value.
TIE_DECIMALS = 9
# CSV C_SN column is written with 6 decimals; the recomputed single-cell
# total must agree with it to that precision.
CSV_C_TOL_FF = 5e-7
# retention_time_s is written with 7 significant digits.
CSV_T_REL_TOL = 1e-6

VOLATILE_KEYS = ("generated_utc", "repo_git_sha")


class ComparisonError(RuntimeError):
    """An input is missing, malformed or inconsistent; never silently skipped."""


# ---------------------------------------------------------------------------
# provenance helpers
# ---------------------------------------------------------------------------
def rel(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def sha256_file(path: Path) -> str:
    if not Path(path).is_file():
        raise ComparisonError(f"input not found: {path}")
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_report(path: Path) -> dict:
    path = Path(path)
    if not path.is_file():
        raise ComparisonError(f"parasitics extraction report not found: {path}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ComparisonError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not data.get("parasitics"):
        raise ComparisonError(
            f"{path} has no 'parasitics' block -- was it generated with --parasitics?"
        )
    return data


def report_provenance(path: Path, data: dict) -> dict:
    prov = data.get("provenance", {}) or {}
    return {
        "path": rel(path),
        "sha256": sha256_file(path),
        "top": data.get("top"),
        "klt_version": prov.get("klt_version", "unknown"),
        "klayout_version": prov.get("klayout_version", "unknown"),
        "deck_content_hash": (prov.get("deck") or {}).get("content_hash", "unknown"),
        "input_content_hash": (prov.get("input") or {}).get("content_hash", "unknown"),
        "netlist_sha256": data.get("netlist_sha256", "unknown"),
    }


# ---------------------------------------------------------------------------
# capacitance validation + reduction
# ---------------------------------------------------------------------------
def checked_cap(value, what: str, *, positive: bool) -> float:
    """A capacitance must be a finite number; a ground term or total must be
    > 0 fF, a coupling term >= 0 fF. Anything else is a malformed report."""
    if isinstance(value, bool):
        raise ComparisonError(f"{what}: capacitance is not a number ({value!r})")
    try:
        c = float(value)
    except (TypeError, ValueError) as exc:
        raise ComparisonError(f"{what}: capacitance is not a number ({value!r})") from exc
    if not math.isfinite(c):
        raise ComparisonError(f"{what}: capacitance is not finite ({value!r})")
    if positive and c <= 0.0:
        raise ComparisonError(f"{what}: capacitance must be > 0 fF, got {c!r}")
    if not positive and c < 0.0:
        raise ComparisonError(f"{what}: coupling capacitance must be >= 0 fF, got {c!r}")
    return c


def net_entry(data: dict, net: str, source: Path) -> dict:
    matches = [n for n in data["parasitics"].get("nets", []) if n.get("net") == net]
    if not matches:
        raise ComparisonError(f"net {net!r} not found in parasitics.nets[] of {source}")
    if len(matches) > 1:
        raise ComparisonError(f"net {net!r} appears {len(matches)} times in {source}")
    return matches[0]


def node_capacitance(report_path: Path, data: dict, net: str) -> dict:
    """Validate the raw entry, then take the total from the *default*
    reader (DR.load_extracted_c_sn) so the convention cannot diverge."""
    entry = net_entry(data, net, report_path)
    if "capacitance_ff" not in entry:
        raise ComparisonError(f"net {net!r} in {report_path} has no capacitance_ff")
    ground = checked_cap(entry["capacitance_ff"], f"{net} ground", positive=True)
    coupled = {}
    for i, c in enumerate(entry.get("coupled", []) or []):
        other = c.get("net")
        if not other:
            raise ComparisonError(f"{net} coupled[{i}] has no far-terminal net name")
        cap = checked_cap(c.get("capacitance_ff"), f"{net} coupling to {other}", positive=False)
        coupled[other] = round(coupled.get(other, 0.0) + cap, 12)
    total, prov = DR.load_extracted_c_sn(Path(report_path), net)
    total = checked_cap(total, f"{net} total", positive=True)
    coupling = sum(coupled.values())
    if abs(prov["ground_c_ff"] - ground) > 1e-12 or abs(total - (ground + coupling)) > 1e-9:
        raise ComparisonError(f"{net}: default reader disagrees with raw entry")
    return {
        "net": net,
        "ground_ff": round(ground, 9),
        "coupling_ff": round(coupling, 9),
        "total_ff": round(total, 9),
        "coupled_ff": dict(sorted(coupled.items())),
    }


def storage_nets(data: dict, source: Path) -> list[str]:
    """Every ``sn_<r>_<c>`` net: the union of parasitics.nets[] names and
    device-terminal nets. A storage net a device touches but the parasitics
    block lacks is an error (the reduction must cover *all* nodes)."""
    from_parasitics = {
        n.get("net") for n in data["parasitics"].get("nets", []) if SN_NET_RE.match(str(n.get("net")))
    }
    from_devices = set()
    for dev in data.get("devices", []) or []:
        for net in (dev.get("nets") or {}).values():
            if SN_NET_RE.match(str(net)):
                from_devices.add(net)
    missing = sorted(from_devices - from_parasitics)
    if missing:
        raise ComparisonError(
            f"{source}: storage nets {missing} are device terminals but have no "
            "parasitics entry -- the reduction would not cover every node"
        )
    nets = from_parasitics | from_devices
    if not nets:
        raise ComparisonError(f"{source}: no sn_<row>_<col> storage nets found")
    return sorted(nets, key=row_col)


def row_col(net: str) -> tuple[int, int]:
    m = SN_NET_RE.match(net)
    if not m:
        raise ComparisonError(f"not a storage net name: {net!r}")
    return int(m.group(1)), int(m.group(2))


def select_extreme(nodes: list[dict], *, minimum: bool) -> tuple[dict, list[str]]:
    """Deterministic: extreme total (rounded to TIE_DECIMALS), ties broken by
    (row, col) ascending. Returns the chosen node and every tied net."""
    if not nodes:
        raise ComparisonError("no storage nodes to select from")
    sign = 1 if minimum else -1
    key = lambda n: (sign * round(n["total_ff"], TIE_DECIMALS), row_col(n["net"]))  # noqa: E731
    best = min(nodes, key=key)
    level = round(best["total_ff"], TIE_DECIMALS)
    tied = [n["net"] for n in sorted(nodes, key=lambda n: row_col(n["net"]))
            if round(n["total_ff"], TIE_DECIMALS) == level]
    return best, tied


def reduce_array(report_path: Path) -> tuple[dict, list[dict]]:
    data = load_report(report_path)
    nodes = []
    for net in storage_nets(data, report_path):
        node = node_capacitance(report_path, data, net)
        node["row"], node["col"] = row_col(net)
        nodes.append(node)
    return data, nodes


def distribution(nodes: list[dict]) -> dict:
    lo, lo_tied = select_extreme(nodes, minimum=True)
    hi, hi_tied = select_extreme(nodes, minimum=False)
    totals = [n["total_ff"] for n in nodes]
    grounds = [n["ground_ff"] for n in nodes]
    couplings = [n["coupling_ff"] for n in nodes]
    return {
        "node_count": len(nodes),
        "limiting_node": lo["net"],
        "limiting_rule": (
            "minimum total_ff (rounded to 1e-9 fF); ties broken by (row, col) "
            "ascending. Smallest C_SN = shortest retention at fixed leakage/margin."
        ),
        "nodes_tied_at_minimum": lo_tied,
        "max_node": hi["net"],
        "nodes_tied_at_maximum": hi_tied,
        "total_ff": {
            "min": lo["total_ff"],
            "max": hi["total_ff"],
            "mean": round(statistics.fmean(totals), 9),
            "median": round(statistics.median(totals), 9),
        },
        "ground_ff": {"min": min(grounds), "max": max(grounds)},
        "coupling_ff": {"min": min(couplings), "max": max(couplings)},
        "coupling_fraction_of_total": {
            "min": round(min(n["coupling_ff"] / n["total_ff"] for n in nodes), 6),
            "max": round(max(n["coupling_ff"] / n["total_ff"] for n in nodes), 6),
        },
    }


# ---------------------------------------------------------------------------
# retention baselines (read, never written)
# ---------------------------------------------------------------------------
def read_csv_rows(path: Path) -> list[tuple[int, str, dict]]:
    """(1-based file line number, raw line, parsed row). Rows are one physical
    line each in retention_results.csv (no embedded newlines)."""
    path = Path(path)
    if not path.is_file():
        raise ComparisonError(f"retention results not found: {path}")
    lines = path.read_text().splitlines()
    if not lines:
        raise ComparisonError(f"retention results file is empty: {path}")
    out = []
    reader = csv.DictReader(lines)
    for i, (raw, row) in enumerate(zip(lines[1:], reader), start=2):
        out.append((i, raw, row))
    return out


def baseline_rows(csv_path: Path, single_total_ff: float, single_input_hash: str) -> dict:
    rows = [r for r in read_csv_rows(csv_path) if r[2].get("geometry_name") == SINGLE_GEOMETRY]
    assumed = [r for r in rows if (r[2].get("c_storage_node_margin_factor_ASSUMPTION") or "").strip()]
    extracted = [
        r for r in rows
        if not (r[2].get("c_storage_node_margin_factor_ASSUMPTION") or "").strip()
        and single_input_hash in (r[2].get("notes") or "")
    ]
    if not assumed:
        raise ComparisonError(f"{csv_path}: no assumption-based {SINGLE_GEOMETRY} row (ratified pre-layout)")
    if not extracted:
        raise ComparisonError(
            f"{csv_path}: no extracted {SINGLE_GEOMETRY} row citing input content hash "
            f"{single_input_hash} -- re-run derive_retention.py against this extraction"
        )
    # Ratified Section 5 value = the first (original, issue #3) assumption row;
    # current extracted estimate = the latest row citing this extraction.
    ratified, isolated = assumed[0], extracted[-1]
    c_csv = float(isolated[2]["c_storage_node_ff_ASSUMPTION"])
    if abs(c_csv - single_total_ff) > CSV_C_TOL_FF:
        raise ComparisonError(
            f"{csv_path} line {isolated[0]}: C_SN {c_csv} fF disagrees with the "
            f"recomputed single-cell total {single_total_ff} fF"
        )
    return {"ratified": ratified, "isolated": isolated}


def describe_row(path: Path, entry: tuple[int, str, dict]) -> dict:
    line, raw, row = entry
    return {
        "source": f"{rel(path)}:{line}",
        "line_sha256": sha256_text(raw),
        "timestamp_utc": row["timestamp_utc"],
        "repo_git_sha": row["repo_git_sha"],
        "leakage_source_row": row["leakage_source_row"],
        "leakage_ileak_a": float(row["leakage_ileak_a"]),
        "c_storage_node_ff": float(row["c_storage_node_ff_ASSUMPTION"]),
        "delta_v_sense_margin_v_ASSUMPTION": float(row["delta_v_sense_margin_v_ASSUMPTION"]),
        "retention_time_s": float(row["retention_time_s"]),
    }


def retention_s(c_ff: float, delta_v: float, ileak_a: float) -> float:
    """t = C * dV / I with C in fF, dV in V, I in A -> seconds."""
    if ileak_a <= 0 or delta_v <= 0 or c_ff <= 0:
        raise ComparisonError("retention inputs must be positive")
    return c_ff * 1e-15 * delta_v / ileak_a


def sensitivity(single_ff: float, isolated: dict, nodes: list[dict], dist: dict) -> dict:
    i_leak = isolated["leakage_ileak_a"]
    dv = isolated["delta_v_sense_margin_v_ASSUMPTION"]
    t_single = retention_s(single_ff, dv, i_leak)
    if abs(t_single - isolated["retention_time_s"]) > CSV_T_REL_TOL * isolated["retention_time_s"]:
        raise ComparisonError(
            f"recomputed isolated-cell retention {t_single:.7e} s disagrees with "
            f"{isolated['source']} ({isolated['retention_time_s']:.7e} s)"
        )

    def point(c_ff: float) -> dict:
        ratio = c_ff / single_ff
        t = retention_s(c_ff, dv, i_leak)
        return {
            "c_sn_ff": c_ff,
            "ratio_c_array_over_c_single": round(ratio, 6),
            "relative_delta": round(ratio - 1.0, 6),
            "retention_time_s": float(f"{t:.6e}"),
            "retention_time_us": round(t * 1e6, 4),
        }

    per_node = {n["net"]: point(n["total_ff"]) for n in nodes}
    lo = point(dist["total_ff"]["min"])
    hi = point(dist["total_ff"]["max"])
    return {
        "label": LABEL,
        "formula": "t_array = t_single * (C_array / C_single) = C_array * delta_V / I_leak (same I_leak, delta_V as the isolated-cell row)",
        "units": {"c": "fF", "ratio": "dimensionless", "t": "s (and us)"},
        "leakage_ileak_a": i_leak,
        "leakage_source_row": isolated["leakage_source_row"],
        "delta_v_sense_margin_v_ASSUMPTION": dv,
        "isolated_cell_retention_s_recomputed": float(f"{t_single:.6e}"),
        "limiting_node": dist["limiting_node"],
        "at_limiting_node": lo,
        "at_max_node": hi,
        "per_node": per_node,
        "ground_only_reference": {
            "note": (
                "Coupling counted as load assumes quiet neighbours (far terminal held "
                "at a fixed potential). This reference drops coupling entirely to show "
                "how much of the array C_SN rests on that assumption. It is not a "
                "bound: a switching neighbour injects charge through the coupling "
                "capacitor (a disturb, characterized by #94), which no static "
                "capacitance value represents."
            ),
            "min_ground_ff": dist["ground_ff"]["min"],
            "ratio_min_ground_over_c_single": round(dist["ground_ff"]["min"] / single_ff, 6),
            "retention_time_us": round(retention_s(dist["ground_ff"]["min"], dv, i_leak) * 1e6, 4),
        },
    }


# ---------------------------------------------------------------------------
# leakage geometry trace (AD/AS/PD/PS)
# ---------------------------------------------------------------------------
PARAM_RE = re.compile(r"([A-Za-z_]\w*)\s*=\s*([^\s]+)")


def spice_card(text: str, instance: str) -> str:
    """Join an instance line with its ``+`` continuation lines."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.split() and line.split()[0].lower() == instance.lower():
            card = [line]
            for nxt in lines[i + 1:]:
                if nxt.startswith("+"):
                    card.append(nxt[1:])
                else:
                    break
            return " ".join(card)
    raise ComparisonError(f"instance {instance!r} not found")


def card_geometry(card: str) -> dict:
    params = {k.lower(): v for k, v in PARAM_RE.findall(card)}
    out = {}
    for k in ("w", "l") + GEOMETRY_KEYS:
        out[k] = float(params[k]) if k in params else None
    return out


def extracted_geometry(data: dict) -> dict:
    """Unique (ad, as, pd, ps) over write devices (drain on a storage net)
    and read devices (gate on a storage net)."""
    roles = {"write_device_drain_on_sn": set(), "read_device_gate_on_sn": set()}
    for dev in data.get("devices", []) or []:
        nets, p = dev.get("nets") or {}, dev.get("params") or {}
        geo = tuple(p.get(f"{k}_um2" if k in ("ad", "as") else f"{k}_um") for k in GEOMETRY_KEYS)
        is_sn = lambda n: SN_NET_RE.match(str(n)) or n == "sn"  # noqa: E731
        if is_sn(nets.get("d")) or is_sn(nets.get("s")):
            roles["write_device_drain_on_sn"].add(geo)
        if is_sn(nets.get("g")):
            roles["read_device_gate_on_sn"].add(geo)
    out = {}
    for role, geos in roles.items():
        out[role] = [dict(zip(GEOMETRY_KEYS, g)) for g in sorted(geos, key=str)]
    return out


def geometry_trace(array_data: dict, single_data: dict) -> dict:
    tmpl = LEAKAGE_TEMPLATE.read_text()
    sch = SCHEMATIC_NETLIST.read_text()
    tb = card_geometry(spice_card(tmpl, "xdut"))
    wr = card_geometry(spice_card(sch, "XM_WR"))
    rd = card_geometry(spice_card(sch, "XM_RD"))
    ex_arr = extracted_geometry(array_data)
    ex_single = extracted_geometry(single_data)
    wr_arr = ex_arr["write_device_drain_on_sn"]
    if len(wr_arr) != 1:
        raise ComparisonError(f"array write devices carry {len(wr_arr)} distinct diffusion geometries")
    ex = wr_arr[0]
    passed = [k for k in GEOMETRY_KEYS if tb[k] is not None]
    return {
        "leakage_testbench": {
            "source": rel(LEAKAGE_TEMPLATE),
            "sha256": sha256_file(LEAKAGE_TEMPLATE),
            "instance": "xdut",
            "w_um": tb["w"], "l_um": tb["l"],
            **{f"{k}": tb[k] for k in GEOMETRY_KEYS},
            "diffusion_geometry_passed": passed,
            "note": (
                "No AD/AS/PD/PS on the xdut card, so the shipped "
                "sky130_fd_pr__nfet_01v8 subcircuit wrapper's own defaults apply "
                "(see sim/retention/README.md 'Array-context C_SN' for the PDK "
                "source line). The measured I_leak therefore does not use either "
                "the schematic or the extracted diffusion geometry."
                if not passed else "Diffusion geometry passed explicitly."
            ),
        },
        "schematic_netlist": {
            "source": rel(SCHEMATIC_NETLIST),
            "sha256": sha256_file(SCHEMATIC_NETLIST),
            "XM_WR": {k: wr[k] for k in GEOMETRY_KEYS},
            "XM_RD": {k: rd[k] for k in GEOMETRY_KEYS},
        },
        "extracted_array": ex_arr,
        "extracted_single_cell": ex_single,
        "extracted_over_schematic_write_device": {
            "ad_ratio": round(ex["ad"] / wr["ad"], 6) if wr["ad"] else None,
            "pd_ratio": round(ex["pd"] / wr["pd"], 6) if wr["pd"] else None,
        },
        "geometry_matched_leakage_evidence_committed": False,
    }


# ---------------------------------------------------------------------------
# assemble
# ---------------------------------------------------------------------------
def build(array_report: Path = ARRAY_REPORT, retention_csv: Path = RETENTION_CSV,
          single_source: dict | None = None) -> dict:
    single_source = single_source or DR.EXTRACTED_C_SN_SOURCES[SINGLE_GEOMETRY]
    single_path = Path(single_source["extract_json"])
    single_net = single_source["net"]

    single_data = load_report(single_path)
    single = node_capacitance(single_path, single_data, single_net)
    single_prov = report_provenance(single_path, single_data)

    array_data, nodes = reduce_array(array_report)
    dist = distribution(nodes)

    base = baseline_rows(retention_csv, single["total_ff"], single_prov["input_content_hash"])
    ratified = describe_row(retention_csv, base["ratified"])
    isolated = describe_row(retention_csv, base["isolated"])
    sens = sensitivity(single["total_ff"], isolated, nodes, dist)

    return {
        "schema": SCHEMA,
        "issue": 89,
        "label": LABEL,
        "generated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "repo_git_sha": DR.repo_git_sha(HERE),
        "convention": (
            "total_ff = ground_ff + sum(coupled[].capacitance_ff), read with "
            "derive_retention.load_extracted_c_sn() for both reports. Wiring "
            "parasitics only (poly/li1/met1): the M_RD gate and M_WR drain "
            "junction capacitance are NOT in either number (layout/README.md, "
            "issue #80 'Convention')."
        ),
        "inputs": {
            "array_report": report_provenance(array_report, array_data),
            "single_cell_report": single_prov,
            "retention_csv_rows": [ratified["source"], isolated["source"]],
        },
        "single_cell": single,
        "array": {**dist, "nodes": nodes},
        "retention": {
            "ratified_prelayout": {
                **ratified,
                "status": "RATIFIED (spec/retention-refresh-budget.md Section 5); unchanged here",
                "c_sn_kind": "ASSUMPTION (2.0x margin over computed C_gate)",
            },
            "isolated_cell_extracted": {
                **isolated,
                "status": "isolated-cell EXTRACTED estimate (issue #7); not ratified",
                "c_sn_kind": f"EXTRACTED, {single_prov['path']} net {single_net!r}",
            },
            "array_capacitance_only_sensitivity": sens,
            "array_vs_ratified_context_only": {
                "note": "For context only. Not a revision of Section 5: the ratified value uses an assumed C_SN.",
                "ratio_t_limiting_over_t_ratified": round(
                    sens["at_limiting_node"]["retention_time_s"] / ratified["retention_time_s"], 6),
            },
        },
        "leakage_geometry_trace": geometry_trace(array_data, single_data),
        "limitations": [
            "Capacitance-only: I_leak is the leakage-testbench value (no diffusion geometry passed), not geometry-matched to the extracted AD/AS/PD/PS.",
            "Wiring-only C_SN convention: device gate/junction capacitance excluded from both single-cell and array numbers.",
            "Quiet-neighbour coupling: coupling capacitors counted as load to a fixed far terminal; dynamic neighbour switching is #94.",
            "4x4 array only, committed GDS (input hash above); regenerated geometry (#91) needs re-extraction and a new comparison file.",
            "Constant-current decay and delta_V = VDD/2 are the existing ASSUMPTIONS of sim/retention/README.md.",
            "Single worst-case PVT point (the isolated-cell row's leakage corner); no mismatch.",
        ],
    }


def strip_volatile(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k not in VOLATILE_KEYS}


def summary_lines(doc: dict) -> list[str]:
    a, r = doc["array"], doc["retention"]
    s = r["array_capacitance_only_sensitivity"]
    return [
        f"[{doc['label']}]",
        f"single-cell C_SN ({doc['inputs']['single_cell_report']['path']}): {doc['single_cell']['total_ff']:.6f} fF",
        f"array C_SN over {a['node_count']} nodes: {a['total_ff']['min']:.6f} ({a['limiting_node']}) .. "
        f"{a['total_ff']['max']:.6f} fF ({a['max_node']}); ties at min: {a['nodes_tied_at_minimum']}",
        f"ratio C_array/C_single: {s['at_limiting_node']['ratio_c_array_over_c_single']:.6f} .. "
        f"{s['at_max_node']['ratio_c_array_over_c_single']:.6f}",
        f"ratified pre-layout (Section 5): {r['ratified_prelayout']['retention_time_s']:.6e} s",
        f"isolated-cell extracted:          {r['isolated_cell_extracted']['retention_time_s']:.6e} s",
        f"array capacitance-only sensitivity: {s['at_limiting_node']['retention_time_us']} .. "
        f"{s['at_max_node']['retention_time_us']} us (limiting node {s['limiting_node']})",
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--write", action="store_true", help="write a NEW timestamped JSON under results/")
    g.add_argument("--check", metavar="FILE", help="recompute and compare with a committed comparison JSON")
    args = ap.parse_args(argv)

    try:
        doc = build()
    except ComparisonError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.check:
        committed = json.loads(Path(args.check).read_text())
        if strip_volatile(committed) != json.loads(json.dumps(strip_volatile(doc))):
            print(f"DRIFT: {args.check} does not match a recomputation from the committed inputs", file=sys.stderr)
            return 1
        print(f"OK: {args.check} reproduces from the committed inputs")
        return 0

    for line in summary_lines(doc):
        print(line)
    if args.write:
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
