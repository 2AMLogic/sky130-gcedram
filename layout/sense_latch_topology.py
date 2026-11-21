#!/usr/bin/env python3
"""sense_latch_topology.py -- single source of truth for the six-device
sense latch's physical composition (issue #387): the `klt gen` params for
each block, the `klt gen-compose` request (placement, connectivity, routing
waypoints) and the plain-element LVS reference netlist are all derived from
ONE parse of the canonical netlist design/sense_latch.spice -- so the
layout, the request that produced it and the reference `klt lvs` compares
against can never silently drift apart from the design source (the same
"generated, not hand-transcribed" bar array_topology.py sets for the
bitcell array, and design/regen_netlist.sh before it).

Device -> block mapping (mirrors design/sense_latch.spice's six X cards;
the parser below validates every expectation and refuses anything else):

  - `npair`  XMN1 + XMN2 (nfet_01v8, cross-coupled: each drain on the
             other device's gate, both sources on `vn`), one
             `mos_array` cols=2 `mirror=true` block -- mirroring puts the
             two source pads on the units' outer edges so `vn` can leave
             the block sideways, and the two drains facing each other in
             the middle. Ringless (`add_guard_ring=false`): a closed tap
             ring would block every route to the inner S/D/G pads
             (gen-compose refuses routes that cross a closed ring), and
             the NMOS bodies are tied by the shared substrate instead
             (the `ptap` block below, the gain cell's own precedent).
  - `ppair`  XMP1 + XMP2 (pfet_01v8, cross-coupled on `vp`), same
             mirrored cols=2 shape. Ringed (`add_guard_ring=true`): a
             pfet's body is its own n-well, so the tie must be a tap INSIDE
             that well -- the generator's own ring guarantees that by
             construction. The ring declares one routing opening on its S
             side (ring_gap_side/ring_gap_um) so rbl/ref/vp can reach the
             inner pads; every other side stays closed.
  - `footer` XMNF (nfet_01v8): the `vn` footer switch, a cols=1 ringless
             `mos_array`.
  - `header` XMPH (pfet_01v8): the `vp` header switch, a cols=1 ringed
             `mos_array` with an S-side ring opening (vp in, vdd's source
             tie).
  - `ptap`   a `guard_ring` (add_well=false) P-substrate tap labelled GND:
             names the substrate net so all three NMOS bodies extract as
             GND, and physically ties the footer's source (GND) to the
             substrate.

Cross-coupling routing (the latch's one hard topology constraint): rbl
spans {XMN1.D, XMN2.G, XMP1.D, XMP2.G} and ref spans {XMN2.D, XMN1.G,
XMP2.G, XMP1.D}, so within each pair block the two nets' pads interleave
and any planar routing of both nets must cross. The compose request
resolves each crossing explicitly instead of hoping the router's bounded
detour search finds one: rbl's pair-internal leg takes a li1/met1 corridor
between the S/D and gate bands, and ref's pair-internal leg is pinned to a
met2 (`metal3` role) backbone that hops over rbl's metal -- the per-leg
`layer_role` override, with via drops at each pin only.

Requires no third-party packages (stdlib only) -- run directly by
layout/generate_sense_latch.sh via `python3 sense_latch_topology.py ...`.
The block reports it reads for placement/waypoint geometry are the `klt
gen` JSON responses generate_sense_latch.sh produces in step 1 (the
array_topology.py `_load_mos_ports_um` precedent: derive geometry from the
actual generated block, never from a hardcoded pitch guess).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from typing import Any

#: The canonical design source this module derives everything from,
#: relative to the repository root (never read from a workdir copy).
SOURCE_SPICE = "design/sense_latch.spice"

#: Instance-name -> block-role map. The names are the contract this module
#: validates design/sense_latch.spice against (issue #387's connectivity
#: table names them); a renamed or restructured netlist is a design change
#: that must come with a regeneration, not something to silently absorb.
PAIR_N = ("XMN1", "XMN2")
PAIR_P = ("XMP1", "XMP2")
FOOTER = "XMNF"
HEADER = "XMPH"
ALL_DEVICES = PAIR_N + PAIR_P + (FOOTER, HEADER)

NFET_MODEL = "sky130_fd_pr__nfet_01v8"
PFET_MODEL = "sky130_fd_pr__pfet_01v8"
MODEL_CLASS = {NFET_MODEL: "nfet", PFET_MODEL: "pfet"}

SUBSTRATE_NET = "GND"
WELL_NET = "vdd"

# ---- gen params -----------------------------------------------------------

#: Ring opening on the ppair block's S side. Wide enough that every route
#: column crossing the ring there (rbl/ref's four pad columns and vp's two
#: source columns) keeps the >=0.485um clearance gen-compose demands from
#: the opening's edges at the committed W=2 sizing; the S side of a W=2
#: cols=2 block has a ~4.3um straight run, so 3.4um still leaves the two
#: corner-joined arms connected. If a netlist W change moves the pad
#: columns apart, regenerate and re-check (the compose run fails loudly if
#: a crossing no longer fits the opening).
PPAIR_RING_GAP_UM = 3.4

#: Ring opening on the header block's S side: vp enters at U0_D's column
#: and vdd at U0_S's, i.e. the opening must span [U0_S.x-0.485,
#: U0_D.x+0.485] = [-0.275, 1.365] at the committed W=4 sizing. 2.2um
#: covers it with margin and fits the W=4 single-unit block's ~2.39um S
#: straight run (a wider opening would split the ring into two arcs).
HEADER_RING_GAP_UM = 2.2

#: P-substrate tap block: sized to sit between the npair block's east edge
#: and the footer's west edge (its GND route ties TAP_E to footer.U0_S
#: head-on), the gain cell's own guard_ring precedent for naming the
#: substrate net.
PTAP_PARAMS = {
    "inner_width_um": 1.0,
    "inner_height_um": 1.0,
    "ring_width_um": 0.42,
    "contacts_per_side": 2,
    "add_well": False,
}


def build_gen_params(devices: dict[str, dict], block: str) -> dict:
    """`klt gen mos_array`/`guard_ring` params for one block, with W/L
    read from the parsed netlist devices (a W edit in the source follows
    into the generation input)."""

    def wl(name: str) -> tuple[float, float]:
        return devices[name]["w"], devices[name]["l"]

    if block == "npair":
        (w0, l0), (w1, l1) = wl(PAIR_N[0]), wl(PAIR_N[1])
        if (w0, l0) != (w1, l1):
            raise ValueError(f"{PAIR_N[0]} and {PAIR_N[1]} must share W/L, got {(w0, l0)} vs {(w1, l1)}")
        return {
            "w_um": w0, "l_um": l0, "fingers": 1, "rows": 1, "cols": 2,
            "dummy": 0, "topology": "array", "flavor": "nfet",
            "gate_contact": True, "add_guard_ring": False, "mirror": True,
        }
    if block == "ppair":
        (w0, l0), (w1, l1) = wl(PAIR_P[0]), wl(PAIR_P[1])
        if (w0, l0) != (w1, l1):
            raise ValueError(f"{PAIR_P[0]} and {PAIR_P[1]} must share W/L, got {(w0, l0)} vs {(w1, l1)}")
        return {
            "w_um": w0, "l_um": l0, "fingers": 1, "rows": 1, "cols": 2,
            "dummy": 0, "topology": "array", "flavor": "pfet",
            "gate_contact": True, "add_guard_ring": True, "mirror": True,
            "ring_gap_side": "S", "ring_gap_um": PPAIR_RING_GAP_UM,
        }
    if block == "footer":
        w, l = wl(FOOTER)
        return {
            "w_um": w, "l_um": l, "fingers": 1, "rows": 1, "cols": 1,
            "dummy": 0, "topology": "array", "flavor": "nfet",
            "gate_contact": True, "add_guard_ring": False,
        }
    if block == "header":
        w, l = wl(HEADER)
        return {
            "w_um": w, "l_um": l, "fingers": 1, "rows": 1, "cols": 1,
            "dummy": 0, "topology": "array", "flavor": "pfet",
            "gate_contact": True, "add_guard_ring": True,
            "ring_gap_side": "S", "ring_gap_um": HEADER_RING_GAP_UM,
        }
    if block == "ptap":
        return dict(PTAP_PARAMS)
    raise ValueError(f"unknown block '{block}'")


# ---- placement / routing geometry ----------------------------------------
#
# Every placement origin and routing waypoint below is computed from the
# generated block reports' own bbox/port geometry (never a hardcoded
# pitch), so a netlist W/L change that reshapes a block moves the recipe
# with it. The offsets are the constants the committed layout was routed
# with; each is named for the clearance it buys.

ROW_GAP_Y_UM = 3.43          # ppair/header row above the npair row: the
                             # between-rows channel that carries vp/vdd
                             # (two tracks) must clear the footer's gate
                             # pad (bottom) and the ring arms (top).
PTAP_GAP_X_UM = 1.07         # npair east edge -> ptap west edge.
BLOCK_GAP_X_UM = 0.41        # ptap east edge -> footer west edge (the
                             # generators' own declared min spacing).
HEADER_GAP_X_UM = 3.48       # ppair east edge -> header west edge: the
                             # east channel carrying vp/vdd down and
                             # around (vdd's descent column sits inside).
SOUTH_DROP_UM = 0.55         # below the bottom row: vn's under-row trunk.
NORTH_RISE_UM = 0.41         # above the header: vdd's over-the-top trunk.
CH_TRACK1_OFF_UM = 0.33      # channel track 1 (vp) above the footer's top.
CH_TRACK2_OFF_UM = 0.68      # channel track 2 (vdd) above track 1.
VN_MID_COL_OFF_UM = 0.595    # east of npair: vn's drop column, clear of
                             # npair's east edge and ptap's west edge.
VN_WEST_COL_OFF_UM = -0.475  # west of npair: vn's other drop column.
FOOTER_EAST_APPROACH_UM = 1.085  # east of the footer: vn rises here to
                                 # reach footer.U0_D from the east side
                                 # its port faces.
VDD_COL_OFF_UM = 0.75        # east of ppair: vdd's descent column.
RBL_MIDBAND_OFF_UM = 0.8     # above the ppair S/D band: rbl's internal
                             # corridor between the S/D and gate bands.
REF_CROSS_OFF_UM = -1.2      # below the ppair S/D band: ref's met2
                             # corridor inside the ring interior.

BLOCKS = ("npair", "ppair", "ptap", "footer", "header")


def load_block_report(path: str) -> dict[str, Any]:
    """`{bbox: {x0, y0, x1, y1}, ports: {name: (x_um, y_um)}}` from a
    `klt gen` JSON report -- the geometry the compose request's origins
    and waypoints are derived from."""
    with open(path, encoding="utf-8") as fh:
        report = json.load(fh)
    return {
        "bbox": report["bbox_um"],
        "ports": {p["name"]: (float(p["x_um"]), float(p["y_um"])) for p in report["ports"]},
    }


def _r3(v: float) -> float:
    """Round to the GDS dbu grid (1nm) so computed coordinates never carry
    float noise into the committed request."""
    return round(v, 3)


def build_compose_request(reports: dict[str, dict]) -> dict:
    npair, ppair = reports["npair"], reports["ppair"]
    ptap, footer, header = reports["ptap"], reports["footer"], reports["header"]

    origins = {
        "npair": (0.0, 0.0),
        "ppair": (0.0, _r3(npair["bbox"]["y1"] + ROW_GAP_Y_UM)),
        "ptap": (_r3(npair["bbox"]["x1"] + PTAP_GAP_X_UM - ptap["bbox"]["x0"]), 0.0),
    }
    ptap_x1 = origins["ptap"][0] + ptap["bbox"]["x1"]
    origins["footer"] = (_r3(ptap_x1 + BLOCK_GAP_X_UM - footer["bbox"]["x0"]), 0.0)
    origins["header"] = (
        _r3(ppair["bbox"]["x1"] + HEADER_GAP_X_UM - header["bbox"]["x0"]),
        origins["ppair"][1],
    )

    def port(block: str, name: str) -> tuple[float, float]:
        x, y = reports[block]["ports"][name]
        ox, oy = origins[block]
        return (_r3(x + ox), _r3(y + oy))

    ft_x1 = origins["footer"][0] + footer["bbox"]["x1"]
    np_x1, np_x0 = npair["bbox"]["x1"], npair["bbox"]["x0"]
    bottom_y0 = min(npair["bbox"]["y0"], ptap["bbox"]["y0"], footer["bbox"]["y0"])

    y_south = _r3(bottom_y0 - SOUTH_DROP_UM)
    t_vp = _r3(footer["bbox"]["y1"] + CH_TRACK1_OFF_UM)
    t_vdd = _r3(footer["bbox"]["y1"] + CH_TRACK2_OFF_UM)
    y_north = _r3(origins["header"][1] + header["bbox"]["y1"] + NORTH_RISE_UM)
    x_vn_mid = _r3(np_x1 + VN_MID_COL_OFF_UM)
    x_vn_west = _r3(np_x0 + VN_WEST_COL_OFF_UM)
    x_vn_east = _r3(ft_x1 + FOOTER_EAST_APPROACH_UM)
    x_vdd = _r3(ppair["bbox"]["x1"] + VDD_COL_OFF_UM)
    y_rbl_mid = _r3(port("ppair", "U0_D")[1] + RBL_MIDBAND_OFF_UM)
    y_ref_mid = _r3(port("ppair", "U0_S")[1] + REF_CROSS_OFF_UM)

    def leg(frm: tuple[str, str], to: tuple[str, str], waypoints=None, layer_role=None):
        entry = {
            "from_pin": {"block": frm[0], "port": frm[1]},
            "to_pin": {"block": to[0], "port": to[1]},
        }
        if waypoints is not None:
            entry["waypoints_um"] = waypoints
        if layer_role is not None:
            entry["layer_role"] = layer_role
        return entry

    def pin(block: str, name: str) -> dict:
        return {"block": block, "port": name}

    connectivity = [
        # rbl = XMN1.D + XMN2.G + XMP1.D + XMP2.G: the npair-internal and
        # npair->ppair legs route automatically (the router's own met1
        # pad-band hop and straight vertical); only the ppair-internal leg
        # needs its explicit corridor so ref's met2 crossing stays clear.
        {
            "net": "rbl",
            "pins": [pin("npair", "U0_D"), pin("ppair", "U0_D"),
                     pin("npair", "U1_G"), pin("ppair", "U1_G")],
            "legs": [leg(("ppair", "U0_D"), ("ppair", "U1_G"), [
                [port("ppair", "U0_D")[0], y_rbl_mid],
                [port("ppair", "U1_G")[0], y_rbl_mid],
            ])],
        },
        # ref = XMN2.D + XMN1.G + XMP2.D + XMP1.G: the npair-internal leg
        # routes automatically around the block's west/south; the
        # ppair-internal leg is the deliberate cross-coupling crossing --
        # pinned to a met2 backbone (layer_role metal3) that hops over
        # rbl's met1/li1 corridor, with via drops at its two pins only.
        {
            "net": "ref",
            "pins": [pin("npair", "U0_G"), pin("ppair", "U0_G"),
                     pin("npair", "U1_D"), pin("ppair", "U1_D")],
            "legs": [leg(("ppair", "U0_G"), ("ppair", "U1_D"), [
                [port("ppair", "U0_G")[0], y_ref_mid],
                [port("ppair", "U1_D")[0], y_ref_mid],
            ], layer_role="metal3")],
        },
        # vn = XMN1.S + XMN2.S + XMNF.D: both npair source pads leave
        # sideways (mirror puts them on the outer edges), drop below the
        # bottom row and rise east of the footer so footer.U0_D is reached
        # from the east side its port faces.
        {
            "net": "vn",
            "pins": [pin("npair", "U1_S"), pin("npair", "U0_S"), pin("footer", "U0_D")],
            "legs": [
                leg(("npair", "U1_S"), ("footer", "U0_D"), [
                    [x_vn_mid, port("npair", "U1_S")[1]],
                    [x_vn_mid, y_south],
                    [x_vn_east, y_south],
                    [x_vn_east, port("footer", "U0_D")[1]],
                ]),
                leg(("npair", "U0_S"), ("footer", "U0_D"), [
                    [x_vn_west, port("npair", "U0_S")[1]],
                    [x_vn_west, y_south],
                    [x_vn_east, y_south],
                    [x_vn_east, port("footer", "U0_D")[1]],
                ]),
            ],
        },
        # vp = XMP1.S + XMP2.S + XMPH.D: both ppair source pads drop
        # through the ring's S opening, run east on channel track 1 and
        # rise into the header's own S opening to header.U0_D.
        {
            "net": "vp",
            "pins": [pin("ppair", "U1_S"), pin("ppair", "U0_S"), pin("header", "U0_D")],
            "legs": [
                leg(("ppair", "U1_S"), ("header", "U0_D"), [
                    [port("ppair", "U1_S")[0], t_vp],
                    [port("header", "U0_D")[0], t_vp],
                ]),
                leg(("ppair", "U0_S"), ("header", "U0_D"), [
                    [port("ppair", "U0_S")[0], t_vp],
                ]),
            ],
        },
        # GND = substrate tap + footer source (XMNF.S): head-on from the
        # ptap block sitting immediately west of the footer.
        {
            "net": "GND",
            "pins": [pin("ptap", "TAP_E"), pin("footer", "U0_S")],
        },
        # vdd = both pfet well taps + header source (XMPH.S): ring-to-ring
        # over the top (both TAP_N ports face north), plus the header
        # source tie entering the header's S opening at U0_S's column.
        {
            "net": "vdd",
            "pins": [pin("ppair", "TAP_N"), pin("ppair", "TAP_E"),
                     pin("header", "TAP_N"), pin("header", "U0_S")],
            "legs": [
                leg(("ppair", "TAP_N"), ("header", "TAP_N"), [
                    [port("ppair", "TAP_N")[0], y_north],
                    [port("header", "TAP_N")[0], y_north],
                ]),
                leg(("ppair", "TAP_E"), ("header", "U0_S"), [
                    [x_vdd, port("ppair", "TAP_E")[1]],
                    [x_vdd, t_vdd],
                    [port("header", "U0_S")[0], t_vdd],
                ]),
            ],
        },
    ]

    return {
        "pdk": {"variant": "sky130A"},
        "blocks": [
            {"id": "npair", "generator_report": "sense_latch_npair_mos.json"},
            {"id": "ppair", "generator_report": "sense_latch_ppair_mos.json"},
            {"id": "ptap", "generator_report": "sense_latch_ptap.json"},
            {"id": "footer", "generator_report": "sense_latch_footer_mos.json"},
            {"id": "header", "generator_report": "sense_latch_header_mos.json"},
        ],
        "placement": {
            "strategy": "explicit",
            "order": list(BLOCKS),
            "origins_um": {
                b: {"x": origins[b][0], "y": origins[b][1]} for b in BLOCKS
            },
        },
        "connectivity": connectivity,
        "routing": {
            "layer_role": "metal",
            "width_um": 0.17,
            "cross_block_layer_role": "metal2",
        },
        "pins": [
            {"net": "en", "block": "footer", "port": "U0_G"},
            {"net": "enb", "block": "header", "port": "U0_G"},
        ],
        "options": {
            "cell_name": "sense_latch_layout_0",
            "output": "sense_latch.gds",
        },
    }


# ---- canonical-netlist parsing --------------------------------------------

_X_CARD = re.compile(
    r"^(?P<name>\S+)\s+(?P<d>\S+)\s+(?P<g>\S+)\s+(?P<s>\S+)\s+(?P<b>\S+)\s+"
    r"(?P<model>sky130_fd_pr__(?:nfet|pfet)_01v8)\b"
)
_PARAM = re.compile(r"(?P<key>[A-Za-z][A-Za-z0-9_]*)\s*=\s*(?P<val>[^\s]+)")


def parse_sense_latch_spice(path: str) -> dict[str, Any]:
    """Parse design/sense_latch.spice's six X cards (D/G/S/B order, W/L
    params, `+`-continuation lines joined) plus the commented `**.subckt`
    wrapper line that names the top cell and its external pins. Returns
    `{devices, top, pins}`; raises ValueError on any structural surprise
    so a restructured netlist can never be silently mis-laid-out."""
    with open(path, encoding="utf-8") as fh:
        raw_lines = fh.read().splitlines()

    lines: list[str] = []
    for line in raw_lines:
        if line.startswith("*"):
            continue
        if line.startswith("+") and lines:
            lines[-1] += " " + line[1:]
        else:
            lines.append(line)

    top, top_pins = None, []
    for line in raw_lines:
        m = re.match(r"^\*\*\.subckt\s+(\S+)(.*)", line)
        if m:
            top = m.group(1)
            top_pins = m.group(2).split()
            break

    devices: dict[str, dict] = {}
    for line in lines:
        m = _X_CARD.match(line)
        if not m:
            continue
        params = {p["key"]: p["val"] for p in _PARAM.finditer(line)}
        name = m["name"]
        if name in devices:
            raise ValueError(f"duplicate instance {name} in {path}")
        try:
            w = float(params["W"])
            l = float(params["L"])
        except KeyError as exc:
            raise ValueError(f"{name} in {path} is missing {exc.args[0]}") from exc
        devices[name] = {
            "class": MODEL_CLASS[m["model"]],
            "nets": {"D": m["d"], "G": m["g"], "S": m["s"], "B": m["b"]},
            "w": w,
            "l": l,
        }

    missing = [d for d in ALL_DEVICES if d not in devices]
    if missing:
        raise ValueError(f"{path} is missing device(s) {missing}")
    extra = set(devices) - set(ALL_DEVICES)
    if extra:
        raise ValueError(f"{path} carries unexpected device instance(s) {sorted(extra)}")
    if top is None:
        raise ValueError(f"{path} has no '**.subckt' wrapper line to read the top pins from")

    _validate_structure(devices, top, top_pins)
    return {"devices": devices, "top": top, "pins": top_pins}


def _validate_structure(devices: dict, top: str, top_pins: list[str]) -> None:
    """The six-device latch contract (issue #387's connectivity table):
    two cross-coupled pairs, a footer, a header, the substrate/well tie
    nets, and the schematic's own pin set on the wrapper."""
    n1, n2 = (devices[d] for d in PAIR_N)
    p1, p2 = (devices[d] for d in PAIR_P)
    nf, hd = devices[FOOTER], devices[HEADER]

    if n1["class"] != "nfet" or n2["class"] != "nfet":
        raise ValueError(f"{PAIR_N} must be {NFET_MODEL}")
    if p1["class"] != "pfet" or p2["class"] != "pfet":
        raise ValueError(f"{PAIR_P} must be {PFET_MODEL}")
    if nf["class"] != "nfet":
        raise ValueError(f"{FOOTER} must be {NFET_MODEL}")
    if hd["class"] != "pfet":
        raise ValueError(f"{HEADER} must be {PFET_MODEL}")

    for a, b, label in ((n1, n2, PAIR_N), (p1, p2, PAIR_P)):
        if a["nets"]["D"] != b["nets"]["G"] or b["nets"]["D"] != a["nets"]["G"]:
            raise ValueError(f"{label} is not cross-coupled (a.D!=b.G or b.D!=a.G)")
        if a["nets"]["S"] != b["nets"]["S"]:
            raise ValueError(f"{label} sources are not shared")

    vn, vp = n1["nets"]["S"], p1["nets"]["S"]
    for d in (*PAIR_N, FOOTER):
        if devices[d]["nets"]["B"] != SUBSTRATE_NET:
            raise ValueError(f"{d} bulk must be {SUBSTRATE_NET}")
    for d in (*PAIR_P, HEADER):
        if devices[d]["nets"]["B"] != WELL_NET:
            raise ValueError(f"{d} bulk must be {WELL_NET}")
    if nf["nets"]["S"] != SUBSTRATE_NET or nf["nets"]["D"] != vn:
        raise ValueError(f"{FOOTER} must tie source and bulk to {SUBSTRATE_NET} and drain to vn")
    if hd["nets"]["S"] != WELL_NET or hd["nets"]["D"] != vp:
        raise ValueError(f"{HEADER} must tie source and bulk to {WELL_NET} and drain to vp")

    rbl, ref = n1["nets"]["D"], n2["nets"]["D"]
    if {rbl, ref} != {p1["nets"]["D"], p2["nets"]["D"]}:
        raise ValueError("the nmos and pmos pair drains do not share the same rbl/ref nets")
    expected_pins = [rbl, ref, nf["nets"]["G"], hd["nets"]["G"], WELL_NET]
    if sorted(top_pins) != sorted(expected_pins):
        raise ValueError(
            f"{SOURCE_SPICE}'s '**.subckt {top}' pins {top_pins} do not match the "
            f"device-derived pin set {expected_pins}"
        )


# ---- LVS reference --------------------------------------------------------

def _fmt_um(v: float) -> str:
    return f"{v:g}U"


def build_lvs_reference(source_spice: str, source_hash: str, parsed: dict) -> str:
    """The plain-element (M-card) LVS reference netlist, generated from the
    same parse as the layout request: device names, nets, W/L copied
    unchanged from the X cards; only the SPICE shape differs (M card +
    nfet/pfet class instead of a subcircuit call -- `klt lvs` requires the
    plain-element form, layout/gain_cell_2t.lvs_reference.spice's own
    documented reason). vn/vp stay internal (not .SUBCKT pins), matching
    the schematic's own pin set."""
    devices = parsed["devices"]
    top = parsed["top"]
    pins = parsed["pins"]

    card_order = (*PAIR_N, *PAIR_P, FOOTER, HEADER)
    lines = [
        "* sense_latch.lvs_reference.spice -- GENERATED plain-element",
        "* (schematic-equivalent) LVS reference netlist for the six-device",
        f"* sense latch (issue #387), mechanically derived from {source_spice}'s",
        "* six X-card device instances -- NOT hand-transcribed (regenerate with",
        "* layout/generate_sense_latch.sh, which re-renders this file every run",
        "* via `python3 layout/sense_latch_topology.py --emit lvs-reference`).",
        "* Device names, connectivity, and W/L are copied unchanged from the",
        "* source netlist; only the SPICE *shape* differs here (an M-card device",
        '* class "nfet"/"pfet" instead of an X-card subcircuit call), mirroring',
        "* layout/gain_cell_2t.lvs_reference.spice's own precedent and the reason",
        "* documented there (klt lvs requires the plain-element form).",
        "*",
        "* Provenance: sha256 of the source netlist this reference derives from",
        f"* (reproduce with: sha256sum {source_spice}). This is the file-content",
        "* hash of the canonical design source, so even a comment-only edit",
        "* there invalidates this committed reference (the test in",
        "* layout/test_generation_reproducibility.py re-derives and compares).",
        f"*   {source_spice}: sha256:{source_hash}",
        "*",
        "* vn / vp (the footer/header switch nodes) are deliberately NOT",
        "* top-level .SUBCKT pins here -- matching design/sense_latch.sch's own",
        "* pin set. `klt extract` still promotes them as layout-side pins;",
        "* `klt lvs` compares topology, and layout-only pins matched the same",
        "* way in the single-cell and array precedents.",
        f".SUBCKT {top} " + " ".join(pins),
    ]
    for name in card_order:
        dev = devices[name]
        n = dev["nets"]
        lines.append(
            f"M_{name} {n['D']} {n['G']} {n['S']} {n['B']} {dev['class']} "
            f"L={_fmt_um(dev['l'])} W={_fmt_um(dev['w'])}"
        )
    lines.append(f".ENDS {top}")
    return "\n".join(lines) + "\n"


def build_lvs_request(reference_path: str) -> dict:
    return {
        "layout": {"file": "sense_latch.gds", "deck": "sky130", "top": "sense_latch_layout_0"},
        "reference": {"netlist": reference_path, "top": "sense_latch"},
    }


# ---- extract verification --------------------------------------------------

def check_extract(extract_json_path: str, parsed: dict) -> list[str]:
    """Compare a `klt extract` report against the parsed canonical netlist:
    exactly six devices (three nfet with body=GND, three pfet with
    body=vdd), each with the netlist's own W/L, and every net the netlist
    declares present. Returns a list of problems (empty = conforms)."""
    with open(extract_json_path, encoding="utf-8") as fh:
        report = json.load(fh)

    problems: list[str] = []
    devices = parsed["devices"]
    expected_counts = {"nfet": 0, "pfet": 0}
    for dev in devices.values():
        expected_counts[dev["class"]] += 1

    if report.get("device_count") != len(devices):
        problems.append(f"device_count {report.get('device_count')} != {len(devices)}")
    for cls, want in expected_counts.items():
        got = (report.get("device_counts") or {}).get(cls)
        if got != want:
            problems.append(f"device_counts[{cls}] {got} != {want}")

    by_class_wl = {}
    for name, dev in devices.items():
        by_class_wl.setdefault(dev["class"], []).append((dev["w"], dev["l"]))
    for ext in report.get("devices", []):
        cls = ext["class"]
        params = ext.get("params", {})
        wl = (params.get("w_um"), params.get("l_um"))
        if wl not in by_class_wl.get(cls, []):
            problems.append(f"extracted {cls} W/L {wl} matches no canonical device")
        body = ext.get("nets", {}).get("b")
        want_body = SUBSTRATE_NET if cls == "nfet" else WELL_NET
        if body != want_body:
            problems.append(f"extracted {cls} body net {body!r} != {want_body!r}")

    extracted_nets = {n for ext in report.get("devices", []) for n in ext.get("nets", {}).values()}
    for name, dev in devices.items():
        for terminal, net in dev["nets"].items():
            if net not in extracted_nets:
                problems.append(f"canonical net {net} ({name}.{terminal}) absent from the extracted netlist")
    return problems


# ---- CLI ------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit", choices=["gen-params", "compose-request", "lvs-reference", "lvs-request"])
    parser.add_argument("--check-extract", metavar="EXTRACT_JSON",
                        help="verify a klt extract report against the canonical netlist instead of emitting")
    parser.add_argument("--block", choices=BLOCKS,
                        help="which block's gen params to emit (gen-params only)")
    parser.add_argument("--source-spice", default=SOURCE_SPICE,
                        help="path to the canonical netlist (repo-root-relative or as-is)")
    parser.add_argument("--source-hash", default="",
                        help="sha256 of the source netlist (lvs-reference only)")
    parser.add_argument("--reports-dir", default=".",
                        help="directory holding the five `klt gen` block reports")
    parser.add_argument("--reference-path", default="sense_latch.lvs_reference.spice")
    args = parser.parse_args()

    if args.check_extract:
        if not args.emit:
            parsed = parse_sense_latch_spice(args.source_spice)
            problems = check_extract(args.check_extract, parsed)
            for p in problems:
                print(f"problem: {p}", file=sys.stderr)
            print(f"extract conforms to the canonical six-device contract: {not problems}")
            return 0 if not problems else 1
        parser.error("--check-extract cannot be combined with --emit")

    if not args.emit:
        parser.error("nothing to do: pass --emit ... or --check-extract PATH")
    if args.emit == "gen-params":
        if not args.block:
            parser.error("--emit gen-params needs --block")
        parsed = parse_sense_latch_spice(args.source_spice)
        json.dump(build_gen_params(parsed["devices"], args.block), sys.stdout, indent=2)
        sys.stdout.write("\n")
    elif args.emit == "compose-request":
        parsed = parse_sense_latch_spice(args.source_spice)
        reports = {
            b: load_block_report(f"{args.reports_dir}/{_report_name(b)}")
            for b in BLOCKS
        }
        json.dump(build_compose_request(reports), sys.stdout, indent=2)
        sys.stdout.write("\n")
    elif args.emit == "lvs-reference":
        source_hash = args.source_hash
        if not source_hash:
            with open(args.source_spice, "rb") as fh:
                source_hash = hashlib.sha256(fh.read()).hexdigest()
        parsed = parse_sense_latch_spice(args.source_spice)
        sys.stdout.write(build_lvs_reference(args.source_spice, source_hash, parsed))
    else:
        json.dump(build_lvs_request(args.reference_path), sys.stdout, indent=2)
        sys.stdout.write("\n")
    return 0


def _report_name(block: str) -> str:
    return {
        "npair": "sense_latch_npair_mos.json",
        "ppair": "sense_latch_ppair_mos.json",
        "ptap": "sense_latch_ptap.json",
        "footer": "sense_latch_footer_mos.json",
        "header": "sense_latch_header_mos.json",
    }[block]


if __name__ == "__main__":
    raise SystemExit(main())
