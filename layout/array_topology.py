#!/usr/bin/env python3
"""array_topology.py -- single source of truth for the shared-tap bitcell
array's net map (issue #34), used by both `generate_array.sh`'s `klt
gen-compose` request and its array-level LVS reference netlist -- so the two
artifacts a `klt lvs` run compares can never silently drift apart (the same
"generated, not hand-transcribed" bar this issue's own acceptance criteria
set for the reference netlist).

Topology (mirrors design/gain_cell_2t.spice's two-device subcircuit,
replicated N_ROWS x N_COLS times):

  - `mos_array` is requested as a single ``rows=N_ROWS, cols=2*N_COLS``
    grid (``topology="array"``, i.e. plain row-major unit numbering, not
    common-centroid) of identical unit nfets -- each bitcell (row r, col c)
    occupies two adjacent grid columns: ``2*c`` = M_WR, ``2*c+1`` = M_RD.
    This is exactly the single-cell layout's own `mos_array` shape
    (`layout/generate.sh`: cols=2, U0=M_WR, U1=M_RD) tiled R x C times, so
    `idx(r, c, is_rd=False)`/`idx(r, c, is_rd=True)` below generalize that
    precedent rather than inventing a new indexing scheme.
  - Per-row buses: `wl_<r>` (every M_WR gate in row r), `rwl_<r>` (every
    M_RD source in row r).
  - Per-column buses: `bl_<c>` (every M_WR source in column c), `rbl_<c>`
    (every M_RD drain in column c).
  - Per-cell internal node: `sn_<r>_<c>` (M_WR's drain to M_RD's gate) --
    NOT promoted as a top-level pin (no `pins[]` entry), matching the
    single-cell schematic/layout's own convention for `sn`
    (`design/README.md` "Node naming", `layout/README.md` "Topology
    mapping"). `klt gen-compose` still labels it (every routed
    `connectivity[]` net gets a net-name label on the composed GDS) and
    `klt extract` still promotes it to a `.SUBCKT` pin, the same
    layout-tool-level (not topology-level) quirk the single-cell layout's
    own README already documents for its own `sn`.
  - Shared substrate tap: one `mos_array(add_guard_ring=true)` ring around
    the whole grid (not one per-cell tap) -- its `TAP_W` port is labelled
    `GND`, the same single-port-labels-the-whole-ring pattern
    `layout/generate.sh` already uses for the single cell's dedicated tap.

Requires no third-party packages (stdlib only) -- run directly by
`generate_array.sh` via `python3 array_topology.py ...`.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

W_UM = 0.42
L_UM = 0.15
ROUTING_LAYER_ROLE = "metal"
ROUTING_WIDTH_UM = 0.17
CROSS_BLOCK_LAYER_ROLE = "metal2"


def mos_idx(n_cols: int, r: int, c: int, is_rd: bool) -> int:
    """Grid index (`U<idx>`) of the WR (``is_rd=False``) or RD
    (``is_rd=True``) device of bitcell (r, c) in the ``rows=N_ROWS,
    cols=2*N_COLS`` ``mos_array`` grid (row-major ``topology="array"``
    numbering: ``idx = r * (2*N_COLS) + grid_col``)."""
    grid_col = 2 * c + (1 if is_rd else 0)
    return r * (2 * n_cols) + grid_col


def build_topology(n_rows: int, n_cols: int) -> dict:
    """Returns a dict describing every net (row/column buses + per-cell
    `sn`) and every device, purely as a function of (n_rows, n_cols) --
    consumed by both `--emit request` and `--emit lvs-reference` below."""
    if n_rows < 1 or n_cols < 1:
        raise ValueError("n_rows/n_cols must both be >= 1")

    nets: dict[str, list[str]] = {}

    for r in range(n_rows):
        nets[f"wl_{r}"] = [f"U{mos_idx(n_cols, r, c, False)}_G" for c in range(n_cols)]
        nets[f"rwl_{r}"] = [f"U{mos_idx(n_cols, r, c, True)}_S" for c in range(n_cols)]

    for c in range(n_cols):
        nets[f"bl_{c}"] = [f"U{mos_idx(n_cols, r, c, False)}_S" for r in range(n_rows)]
        nets[f"rbl_{c}"] = [f"U{mos_idx(n_cols, r, c, True)}_D" for r in range(n_rows)]

    for r in range(n_rows):
        for c in range(n_cols):
            nets[f"sn_{r}_{c}"] = [
                f"U{mos_idx(n_cols, r, c, False)}_D",
                f"U{mos_idx(n_cols, r, c, True)}_G",
            ]

    devices = []
    for r in range(n_rows):
        for c in range(n_cols):
            devices.append(
                {
                    "wr_name": f"M_WR_{r}_{c}",
                    "rd_name": f"M_RD_{r}_{c}",
                    "sn": f"sn_{r}_{c}",
                    "wl": f"wl_{r}",
                    "bl": f"bl_{c}",
                    "rwl": f"rwl_{r}",
                    "rbl": f"rbl_{c}",
                }
            )

    return {"n_rows": n_rows, "n_cols": n_cols, "nets": nets, "devices": devices}


def build_gen_request(n_rows: int, n_cols: int) -> dict:
    """`klt gen mos_array` request params for the whole shared-tap array
    block (Option A from issue #34's implementation guidance: one
    `mos_array` sized for all `2 * N_ROWS * N_COLS` transistors with
    `add_guard_ring=true`, rather than composing N_ROWS*N_COLS separate
    per-cell `guard_ring` blocks)."""
    return {
        "w_um": W_UM,
        "l_um": L_UM,
        "fingers": 1,
        "rows": n_rows,
        "cols": 2 * n_cols,
        "dummy": 0,
        "topology": "array",
        "flavor": "nfet",
        "gate_contact": True,
        "add_guard_ring": True,
    }


def _load_mos_ports_um(mos_report_path: str) -> dict[str, tuple[float, float]]:
    """``{port_name: (x_um, y_um)}`` from an already-generated `klt gen
    mos_array` report (the file `generate_array.sh` produces in step 1,
    before this module's `compose-request` emission runs) -- used to derive
    the explicit-waypoint detours below from the *actual* generated
    geometry rather than a hardcoded row-pitch guess that could silently
    drift out of sync with a future `klt gen mos_array` change."""
    with open(mos_report_path, encoding="utf-8") as fh:
        report = json.load(fh)
    return {p["name"]: (float(p["x_um"]), float(p["y_um"])) for p in report["ports"]}


#: How far past each cell's own M_WR drain (`sn_<r>_<c>`'s own start pin)
#: the per-cell `sn` net's single explicit waypoint sits, before rising to
#: M_RD's gate y-level (see `build_compose_request`'s own routing-order
#: comment for why `sn` needs an explicit waypoint at all). `0.2` was the
#: smallest offset (in `0.05um` steps from the naive `0.0`) that cleared
#: `klt drc`'s own `li1.space.1` minimum-spacing rule against M_WR's own
#: gate-contact landing pad immediately to `sn`'s west at this bitcell's
#: `w_um`/`l_um` sizing (issue #34's own DRC iteration; see this file's/
#: README's "klayout-tools friction" notes) -- not re-derived from the
#: deck's own rule value here, since `klt gen-compose`'s router does not
#: expose the resolved deck's spacing rule to a caller for it to compute
#: a provably-sufficient offset from first principles.
SN_WAYPOINT_X_OFFSET_UM = 0.2


def build_compose_request(n_rows: int, n_cols: int, mos_report_path: str) -> dict:
    topo = build_topology(n_rows, n_cols)
    ports = _load_mos_ports_um(mos_report_path)

    # Route order matters to `klt gen-compose`'s router: a later net can be
    # forced to jog around an earlier net's already-drawn metal, but not
    # vice versa. The row/column buses (`wl_<r>`/`rwl_<r>`/`bl_<c>`/
    # `rbl_<c>`) are routed FIRST, letting the router's own automatic
    # same-block cross-layer/detour-lane search (docs/cli/gen-compose.md
    # "Cross-block bus routing") pick each bus's path freely -- every bus
    # net composed cleanly this way with no explicit help needed (issue
    # #34's own routing iteration; see this file's/README's "klayout-tools
    # friction" notes for the earlier, less-robust orderings that were
    # tried first and abandoned). Each per-cell `sn_<r>_<c>` net is routed
    # LAST, with its own explicit `waypoints_um` (below) so it reaches its
    # own M_RD unit's gate pad by a path the buses' own (opaque, not
    # reported back by `klt gen-compose`) chosen geometry cannot already be
    # occupying.
    net_order = (
        [f"wl_{r}" for r in range(n_rows)]
        + [f"rwl_{r}" for r in range(n_rows)]
        + [f"bl_{c}" for c in range(n_cols)]
        + [f"rbl_{c}" for c in range(n_cols)]
        + [f"sn_{r}_{c}" for r in range(n_rows) for c in range(n_cols)]
    )

    # `sn_<r>_<c>`'s own explicit waypoint: a single intermediate point at
    # (M_WR's drain x + SN_WAYPOINT_X_OFFSET_UM, M_RD's gate y) forces a
    # "rise, then jog right" Manhattan backbone -- the mirror image of the
    # naive "jog right at the source/drain band, then rise" default the
    # router falls back to left-uncontrolled, which runs directly across
    # M_RD's own source pad (a same-block self-net pad-crossing short) or,
    # once the row/column buses above already claim that band, across
    # their own already-routed metal. Rising directly from M_WR's own
    # drain first, offset just clear of M_WR's own gate-contact landing pad
    # (see SN_WAYPOINT_X_OFFSET_UM), avoids both.
    waypoints_by_net: dict[str, list[list[float]]] = {}
    for r in range(n_rows):
        for c in range(n_cols):
            wr_d = f"U{mos_idx(n_cols, r, c, False)}_D"
            rd_g = f"U{mos_idx(n_cols, r, c, True)}_G"
            wr_x, _wr_y = ports[wr_d]
            _rd_x, rd_y = ports[rd_g]
            waypoints_by_net[f"sn_{r}_{c}"] = [[wr_x + SN_WAYPOINT_X_OFFSET_UM, rd_y]]

    connectivity = []
    for net in net_order:
        entry: dict[str, Any] = {
            "net": net,
            "pins": [{"block": "mos", "port": port} for port in topo["nets"][net]],
        }
        if net in waypoints_by_net:
            entry["waypoints_um"] = waypoints_by_net[net]
        connectivity.append(entry)
    return {
        "pdk": {"variant": "sky130A"},
        "blocks": [{"id": "mos", "generator_report": mos_report_path}],
        "placement": {
            "strategy": "explicit",
            "order": ["mos"],
            "origins_um": {"mos": {"x": 0.0, "y": 0.0}},
        },
        "connectivity": connectivity,
        "routing": {
            "layer_role": ROUTING_LAYER_ROLE,
            "width_um": ROUTING_WIDTH_UM,
            "cross_block_layer_role": CROSS_BLOCK_LAYER_ROLE,
        },
        "pins": [{"net": "GND", "block": "mos", "port": "TAP_W"}],
        "options": {
            "cell_name": f"gain_cell_2t_array_{n_rows}x{n_cols}_layout_0",
            "output": "gain_cell_2t_array.gds",
        },
    }


def build_lvs_reference(n_rows: int, n_cols: int, source_spice_path: str, source_hash: str) -> str:
    topo = build_topology(n_rows, n_cols)
    top = f"gain_cell_2t_array_{n_rows}x{n_cols}"
    pins = (
        [f"wl_{r}" for r in range(n_rows)]
        + [f"rwl_{r}" for r in range(n_rows)]
        + [f"bl_{c}" for c in range(n_cols)]
        + [f"rbl_{c}" for c in range(n_cols)]
    )
    lines = [
        "* gain_cell_2t_array.lvs_reference.spice -- GENERATED array-level plain-",
        "* element (schematic-equivalent) LVS reference netlist for issue #34's",
        f"* {n_rows}-row x {n_cols}-column shared-tap bitcell array, mechanically",
        f"* replicating {source_spice_path}'s two-device subcircuit {n_rows}x{n_cols}",
        "* times with the row/column bus net renaming array_topology.py computes --",
        "* NOT hand-transcribed (see layout/generate_array.sh, which regenerates this",
        "* file every run via `python3 layout/array_topology.py --emit lvs-reference`).",
        "* Device names, connectivity, and W/L are copied unchanged from the source",
        "* two-device netlist; only the SPICE *shape* differs (an M-card device class",
        '* "nfet" instead of an X-card subcircuit call, plus a real .SUBCKT/.ENDS',
        "* wrapper with the row/column bus pins below), mirroring",
        "* layout/gain_cell_2t.lvs_reference.spice's own single-cell precedent and",
        "* the reason documented there (klt lvs requires the plain-element form).",
        "*",
        "* Provenance: sha256 of the source netlist this array replicates from",
        f"* (reproduce with: sha256sum {source_spice_path}).",
        f"*   {source_spice_path}: sha256:{source_hash}",
        "*",
        f"* sn_<r>_<c> (each bitcell's internal storage node) is deliberately NOT a",
        "* top-level .SUBCKT pin here either -- matching design/gain_cell_2t.sch's",
        "* and the single-cell layout's own convention (see array_topology.py's",
        "* module docstring \"Per-cell internal node\").",
        f".SUBCKT {top} " + " ".join(pins),
    ]
    for dev in topo["devices"]:
        lines.append(
            f"{dev['wr_name']} {dev['sn']} {dev['wl']} {dev['bl']} GND nfet L=0.15U W=0.42U"
        )
        lines.append(
            f"{dev['rd_name']} {dev['rbl']} {dev['sn']} {dev['rwl']} GND nfet L=0.15U W=0.42U"
        )
    lines.append(f".ENDS {top}")
    return "\n".join(lines) + "\n"


def build_lvs_request(n_rows: int, n_cols: int, gds_path: str, top_cell: str, reference_path: str) -> dict:
    return {
        "layout": {"file": gds_path, "deck": "sky130", "top": top_cell},
        "reference": {
            "netlist": reference_path,
            "top": f"gain_cell_2t_array_{n_rows}x{n_cols}",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, required=True, help="N_ROWS")
    parser.add_argument("--cols", type=int, required=True, help="N_COLS")
    parser.add_argument(
        "--emit",
        required=True,
        choices=["gen-params", "compose-request", "lvs-reference", "lvs-request"],
        help="which artifact to print to stdout",
    )
    parser.add_argument("--mos-report", default="gain_cell_2t_array_mos.json")
    parser.add_argument("--source-spice", default="../design/gain_cell_2t.spice")
    parser.add_argument("--source-hash", default="")
    parser.add_argument("--gds-path", default="gain_cell_2t_array.gds")
    parser.add_argument("--top-cell", default="")
    parser.add_argument("--reference-path", default="gain_cell_2t_array.lvs_reference.spice")
    args = parser.parse_args()

    if args.emit == "gen-params":
        json.dump(build_gen_request(args.rows, args.cols), sys.stdout, indent=2)
        sys.stdout.write("\n")
    elif args.emit == "compose-request":
        json.dump(
            build_compose_request(args.rows, args.cols, args.mos_report),
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
    elif args.emit == "lvs-reference":
        sys.stdout.write(
            build_lvs_reference(args.rows, args.cols, args.source_spice, args.source_hash)
        )
    elif args.emit == "lvs-request":
        top_cell = args.top_cell or f"gain_cell_2t_array_{args.rows}x{args.cols}_layout_0"
        json.dump(
            build_lvs_request(args.rows, args.cols, args.gds_path, top_cell, args.reference_path),
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
