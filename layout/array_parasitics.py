#!/usr/bin/env python3
"""Reduce `klt extract --parasitics` reports of the bitcell array (issue #80).

Stdlib only. Reads:

* the committed 4x4 extraction (``--committed``,
  layout/gain_cell_2t_array.extract.parasitics.json);
* the committed single-cell extraction (``--single-cell``,
  layout/gain_cell_2t.extract.parasitics.json), for the storage-node
  reference value;
* zero or more row-count scaling extractions (``--scaling
  N_ROWS:extract.json:gates.json``) produced in a scratch directory by
  layout/extract_array_parasitics.sh.

Writes one summary JSON (``-o``). Capacitance convention, identical to
sim/retention/derive_retention.py's ``load_extracted_c_sn()``: a net's
total = its own lumped ground capacitance (``parasitics.nets[].
capacitance_ff``) + every coupling capacitor reported on it
(``parasitics.nets[].coupled[].capacitance_ff``, summed). Coupling is
counted as load (its far terminal is another signal net, not ground);
that is an upper-bound-style choice, stated in the summary.

Run ``python3 array_parasitics.py --self-test`` for the built-in checks.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Values this extraction is compared against. They are READ here, never
# changed: the contract, the sense-stage deck and every spec file are out of
# scope for issue #80.
C_RBL_ASSUMPTION_FF = 10.0
C_RBL_ASSUMPTION_SOURCE = (
    "sim/sense-stage/gen_sense_stage.py:46 C_RBL_F = 10e-15 "
    "(ASSUMPTION; sim/loaded-column/cold-corner/SENSE_INPUT_CONTRACT.md)"
)
C_SN_SINGLE_CELL_FF = 0.605354
C_SN_SINGLE_CELL_SOURCE = (
    "layout/gain_cell_2t.extract.parasitics.json net 'sn' "
    "(issue #7; used by sim/retention/derive_retention.py)"
)
EXTRAPOLATE_ROWS = [16, 32, 64, 128, 256]
NET_RE = re.compile(r"^(wl|rwl|bl|rbl)_(\d+)$|^sn_(\d+)_(\d+)$")


def _r6(x: float) -> float:
    return round(x, 6)


def net_entry(net: dict) -> dict:
    ground = float(net["capacitance_ff"])
    coupled = sorted(
        ((c["net"], float(c["capacitance_ff"])) for c in net.get("coupled", [])),
        key=lambda t: t[0],
    )
    coupling = sum(c for _, c in coupled)
    return {
        "ground_ff": _r6(ground),
        "coupling_ff": _r6(coupling),
        "total_ff": _r6(ground + coupling),
        "resistance_ohm": _r6(float(net["resistance_ohm"])),
        "by_layer_ground_ff": {
            b["layer"]: _r6(float(b["capacitance_ff"])) for b in (net.get("by_layer") or [])
        },
        "coupled_ff": {n: _r6(c) for n, c in coupled},
    }


def classify(report: dict) -> dict:
    """Group a report's parasitics nets into row/column/cell tables."""
    out = {"wl": {}, "rwl": {}, "bl": {}, "rbl": {}, "sn": {}, "other": {}}
    for net in report["parasitics"]["nets"]:
        name = net["net"]
        m = NET_RE.match(name)
        if not m:
            out["other"][name] = net_entry(net)
        elif m.group(1):
            out[m.group(1)][name] = net_entry(net)
        else:
            out["sn"][name] = net_entry(net)
    return out


def single_cell_c_sn(report: dict) -> float:
    for net in report["parasitics"]["nets"]:
        if net["net"] == "sn":
            return net_entry(net)["total_ff"]
    raise SystemExit("single-cell report has no 'sn' parasitics entry")


def linfit(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """Least-squares y = a + b*x; returns (a, b, max |residual|)."""
    n = len(xs)
    if n < 2:
        raise ValueError("need at least two points for a fit")
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - b * mx
    res = max(abs(y - (a + b * x)) for x, y in zip(xs, ys))
    return a, b, res


def worst(table: dict, key: str) -> tuple[str, dict]:
    name = max(table, key=lambda k: (table[k][key], k))
    return name, table[name]


def scaling_block(points: list[tuple[int, dict, dict]]) -> dict:
    pts = []
    for n_rows, groups, gates in sorted(points, key=lambda p: p[0]):
        rbl_name, rbl = worst(groups["rbl"], "total_ff")
        bl_name, bl = worst(groups["bl"], "total_ff")
        pts.append({
            "n_rows": n_rows,
            "gates": gates,
            "worst_rbl": {"net": rbl_name, **{k: rbl[k] for k in ("ground_ff", "coupling_ff", "total_ff")}},
            "worst_bl": {"net": bl_name, **{k: bl[k] for k in ("ground_ff", "coupling_ff", "total_ff")}},
        })
    xs = [float(p["n_rows"]) for p in pts]
    fits = {}
    for bus in ("worst_rbl", "worst_bl"):
        for q in ("ground_ff", "total_ff"):
            a, b, res = linfit(xs, [p[bus][q] for p in pts])
            fits[f"{bus}.{q}"] = {
                "fixed_ff": _r6(a), "per_row_ff": _r6(b), "max_abs_residual_ff": _r6(res),
            }
    rbl_tot = fits["worst_rbl.total_ff"]
    extrap = [
        {
            "n_rows": n,
            "worst_rbl_total_ff": _r6(rbl_tot["fixed_ff"] + rbl_tot["per_row_ff"] * n),
            "worst_bl_total_ff": _r6(fits["worst_bl.total_ff"]["fixed_ff"]
                                     + fits["worst_bl.total_ff"]["per_row_ff"] * n),
        }
        for n in EXTRAPOLATE_ROWS
    ]
    rows_at_assumption = (C_RBL_ASSUMPTION_FF - rbl_tot["fixed_ff"]) / rbl_tot["per_row_ff"]
    return {
        "points": pts,
        "fit": fits,
        "extrapolation_ASSUMPTION": {
            "label": "ASSUMPTION",
            "basis": (
                "Linear fixed + per-row fit through the extracted N_ROWS points above, "
                "evaluated beyond the largest extracted N_ROWS. Assumes the column keeps "
                "this exact array_topology.py bus geometry (li1 column bus, same pitch, "
                "no strapping/segmenting, no column mux, no periphery wiring) -- none of "
                "which a macro is required to keep. Not extracted; not a ratified N_rows."
            ),
            "rows": extrap,
            "n_rows_where_wiring_alone_reaches_c_rbl_assumption": _r6(rows_at_assumption),
        },
    }


def build_summary(committed: dict, committed_path: str, single: dict,
                  scaling: list[tuple[int, dict, dict]]) -> dict:
    g = classify(committed)
    c_sn_single = single_cell_c_sn(single)
    if abs(c_sn_single - C_SN_SINGLE_CELL_FF) > 1e-6:
        raise SystemExit(
            f"single-cell C_SN {c_sn_single} != referenced {C_SN_SINGLE_CELL_FF} -- "
            "the committed single-cell extraction changed; re-check this comparison")
    rbl_name, rbl = worst(g["rbl"], "total_ff")
    sn_tot = [v["total_ff"] for v in g["sn"].values()]
    sn_rel = {
        k: _r6((v["total_ff"] - C_SN_SINGLE_CELL_FF) / C_SN_SINGLE_CELL_FF)
        for k, v in g["sn"].items()
    }
    prov = committed.get("provenance", {})
    summary = {
        "schema": "gcedram.array_parasitics.summary/1",
        "issue": 80,
        "source": {
            "extraction": committed_path,
            "netlist": committed.get("netlist_path"),
            "netlist_sha256": committed.get("netlist_sha256"),
            "top": committed.get("top"),
            "device_count": committed.get("device_count"),
            "klt_version": prov.get("klt_version"),
            "klayout_version": prov.get("klayout_version"),
            "deck_content_hash": (prov.get("deck") or {}).get("content_hash"),
            "input_content_hash": (prov.get("input") or {}).get("content_hash"),
            "critical_nets": committed["parasitics"].get("critical_nets"),
        },
        "convention": (
            "total_ff = ground_ff + coupling_ff (every coupling capacitor reported on the net, "
            "summed), same as derive_retention.load_extracted_c_sn(). Extracted wiring "
            "parasitics only: by_layer lists poly/li1(metal0)/met1(metal1); diffusion "
            "junction and gate capacitance of the devices are NOT in these numbers -- they "
            "are carried by the extracted device cards' AD/AS/PD/PS and W/L and evaluated "
            "by the BSIM model at simulation time."
        ),
        "model_limits": committed["parasitics"].get("model"),
        "per_column": {"rbl": g["rbl"], "bl": g["bl"]},
        "per_row": {"wl": g["wl"], "rwl": g["rwl"]},
        "per_cell_sn": g["sn"],
        "comparison": {
            "c_rbl": {
                "assumption_ff": C_RBL_ASSUMPTION_FF,
                "assumption_source": C_RBL_ASSUMPTION_SOURCE,
                "extracted_4row_worst_net": rbl_name,
                "extracted_4row_worst_ground_ff": rbl["ground_ff"],
                "extracted_4row_worst_total_ff": rbl["total_ff"],
                "ratio_extracted_total_to_assumption": _r6(rbl["total_ff"] / C_RBL_ASSUMPTION_FF),
            },
            "c_sn": {
                "single_cell_ff": C_SN_SINGLE_CELL_FF,
                "single_cell_source": C_SN_SINGLE_CELL_SOURCE,
                "array_min_total_ff": _r6(min(sn_tot)),
                "array_max_total_ff": _r6(max(sn_tot)),
                "array_relative_delta_min": min(sn_rel.values()),
                "array_relative_delta_max": max(sn_rel.values()),
                "finding": (
                    "array-context C_SN differs from the single-cell value used by retention"
                    if max(abs(v) for v in sn_rel.values()) > 0.01 else
                    "array-context C_SN within 1% of the single-cell value"
                ),
            },
        },
    }
    if scaling:
        sc = scaling_block(scaling)
        four = [p for p in scaling if p[0] == 4]
        if four:
            diffs = []
            for kind in ("rbl", "bl", "wl", "rwl", "sn"):
                for name, v in g[kind].items():
                    other = four[0][1][kind].get(name)
                    if other is None:
                        raise SystemExit(f"scratch 4x4 lacks net {name}")
                    diffs.append(abs(other["total_ff"] - v["total_ff"]))
            sc["scratch_4row_vs_committed_max_abs_diff_ff"] = _r6(max(diffs))
        summary["row_scaling"] = sc
    return summary


def _self_test() -> None:
    a, b, r = linfit([2, 4, 8], [1.0, 2.0, 4.0])
    assert abs(a) < 1e-12 and abs(b - 0.5) < 1e-12 and r < 1e-12
    net = {"net": "rbl_0", "capacitance_ff": 0.5, "resistance_ohm": 10,
           "coupled": [{"net": "x", "capacitance_ff": 0.1}, {"net": "y", "capacitance_ff": 0.2}]}
    e = net_entry(net)
    assert e["total_ff"] == 0.8 and e["coupling_ff"] == 0.3
    rep = {"parasitics": {"nets": [net, {**net, "net": "sn_1_2"}, {**net, "net": "GND"}]}}
    gr = classify(rep)
    assert "rbl_0" in gr["rbl"] and "sn_1_2" in gr["sn"] and "GND" in gr["other"]
    print("self-test OK")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--committed")
    ap.add_argument("--single-cell")
    ap.add_argument("--scaling", action="append", default=[],
                    metavar="N_ROWS:EXTRACT_JSON:GATES_JSON")
    ap.add_argument("-o", "--output")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        _self_test()
        return 0
    if not (args.committed and args.single_cell and args.output):
        ap.error("--committed, --single-cell and -o are required")
    repo = Path(__file__).resolve().parent.parent
    committed_path = Path(args.committed).resolve()
    try:
        rel = str(committed_path.relative_to(repo))
    except ValueError:
        rel = str(committed_path)
    committed = json.loads(committed_path.read_text())
    single = json.loads(Path(args.single_cell).read_text())
    scaling = []
    for spec in args.scaling:
        n, ext, gates = spec.split(":", 2)
        scaling.append((int(n), classify(json.loads(Path(ext).read_text())),
                        json.loads(Path(gates).read_text())))
    summary = build_summary(committed, rel, single, scaling)
    Path(args.output).write_text(json.dumps(summary, indent=2, sort_keys=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
