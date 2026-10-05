"""Declared variant set for the cold-corner study (issue #47).

Every variant is the Phase 2 baseline with ONE declared knob changed (the
`changes` dict names it), except the explicitly labelled negative control.
Nothing here is a spec value: each knob is a characterization setting or a
candidate design change, and a candidate passing here is a proposal for the
spec/ decision process, not a ratification.

Scopes (which corner/temperature/age points a variant is run at):
  cold_fresh   fs, ss at -40 C, fresh                      (attribution)
  cold_both    fs, ss at -40 C, fresh + refresh bound      (harness check)
  grid_fresh   all 5 corners x -40/27/125 C, fresh         (remedy screen)
  grid_both    all 15 points, fresh + refresh bound        (remedy campaign)
  nc           fs/-40 C and tt/27 C, fresh                 (negative control)
Every scope runs all 4 selected rows x all 16 stored patterns per point.
"""

from __future__ import annotations

import hashlib
import json

CORNERS = ["tt", "ss", "ff", "sf", "fs"]
TEMPS_C = [-40, 27, 125]
AGES = ["fresh", "refresh_bound"]

SCOPES = {
    "cold_fresh": ([("fs", -40), ("ss", -40)], ["fresh"]),
    "cold_both": ([("fs", -40), ("ss", -40)], AGES),
    "grid_fresh": ([(c, t) for c in CORNERS for t in TEMPS_C], ["fresh"]),
    "grid_both": ([(c, t) for c in CORNERS for t in TEMPS_C], AGES),
    "nc": ([("fs", -40), ("tt", 27)], ["fresh"]),
}

NFET = "sky130_fd_pr__nfet_01v8"
NFET_LVT = "sky130_fd_pr__nfet_01v8_lvt"

# Phase 2 baseline (sim/loaded-column/, run 20261005T102906Z). W in um.
BASELINE = {
    "vwl_v": 1.8,
    "twpulse_s": 20e-9,
    "vrwl_sel_v": 0.0,
    "c_rbl_f": 10e-15,
    "t_sense_s": 10e-9,
    "wr_model": NFET,
    "wr_w_um": 0.42,
    "rd_model": NFET,
    "rd_w_um": 0.42,
    "force": 0,
    "vsn1_v": 0.0,
}

# Pass criteria applied by analyze_variants.py. ASSUMPTIONS (proposed
# engineering criteria for this study, NOT spec values; see README).
SEP_MIN_V = 0.1  # worst-case column separation at t_sense
DISTURB_MAX_V = 0.1  # |read disturb| on selected and unselected sn


def _v(vid, cls, scope, why, **changes):
    unknown = set(changes) - set(BASELINE)
    if unknown:
        raise ValueError(f"{vid}: unknown knobs {unknown}")
    return {"id": vid, "class": cls, "scope": scope, "why": why, "changes": changes}


VARIANTS = [
    # --- harness check: must reproduce Phase 2 exactly -------------------
    _v("baseline", "reproduction", "cold_both",
       "Phase 2 deck re-rendered by the variant harness; must equal the committed run"),
    # --- attribution: one declared assumption at a time (cold points) ----
    _v("attr_vwl_2p0", "attribution:write_drive", "cold_fresh", "write-wordline high 2.0 V", vwl_v=2.0),
    _v("attr_vwl_2p2", "attribution:write_drive", "cold_fresh", "write-wordline high 2.2 V", vwl_v=2.2),
    _v("attr_vwl_2p4", "attribution:write_drive", "cold_fresh", "write-wordline high 2.4 V", vwl_v=2.4),
    _v("attr_twpulse_40n", "attribution:write_timing", "cold_fresh", "write pulse 40 ns", twpulse_s=40e-9),
    _v("attr_twpulse_100n", "attribution:write_timing", "cold_fresh", "write pulse 100 ns", twpulse_s=100e-9),
    _v("attr_wr_lvt", "attribution:write_device", "cold_fresh", "M_WR low-Vt flavour", wr_model=NFET_LVT),
    _v("attr_rd_w_0p84", "attribution:read_sizing", "cold_fresh", "M_RD W 0.84 um (2x)", rd_w_um=0.84),
    _v("attr_rd_w_1p68", "attribution:read_sizing", "cold_fresh", "M_RD W 1.68 um (4x)", rd_w_um=1.68),
    _v("attr_rd_lvt", "attribution:read_device", "cold_fresh", "M_RD low-Vt flavour", rd_model=NFET_LVT),
    _v("attr_rwl_m0p2", "attribution:read_drive", "cold_fresh", "selected rwl -0.2 V", vrwl_sel_v=-0.2),
    _v("attr_rwl_m0p4", "attribution:read_drive", "cold_fresh", "selected rwl -0.4 V", vrwl_sel_v=-0.4),
    _v("attr_crbl_5f", "attribution:bitline_load", "cold_fresh", "C_RBL 5 fF", c_rbl_f=5e-15),
    _v("attr_crbl_20f", "attribution:bitline_load", "cold_fresh", "C_RBL 20 fF", c_rbl_f=20e-15),
    _v("attr_crbl_40f", "attribution:bitline_load", "cold_fresh", "C_RBL 40 fF", c_rbl_f=40e-15),
    _v("attr_tsense_5n", "attribution:sense_time", "cold_fresh", "t_sense 5 ns", t_sense_s=5e-9),
    _v("attr_tsense_15n", "attribution:sense_time", "cold_fresh", "t_sense 15 ns", t_sense_s=15e-9),
    _v("attr_tsense_19n", "attribution:sense_time", "cold_fresh", "t_sense 19 ns (end of select)", t_sense_s=19e-9),
] + [
    _v(f"attr_force_sn1_{str(v).replace('.', 'p')}", "attribution:forced_level", "cold_fresh",
       f"write bypassed, stored '1' initialised to {v} V (read-path transfer)",
       force=1, vwl_v=0.0, vsn1_v=v)
    for v in (0.8, 0.9, 1.0, 1.1, 1.2, 1.4, 1.8)
] + [
    # --- remedy candidates (chosen after the attribution pass, see README) --
    # Two classes are carried through the full 15-point x 2-age campaign:
    #   write-path : boost the write wordline (restores the stored level)
    #   read-path  : under-drive the selected read wordline (restores read Vgs)
    # plus a device-flavour candidate in each path (low-Vt write device on the
    # full grid, because its cost is retention; low-Vt read device as a
    # fresh-only screen). Knob values are the smallest attribution step that
    # cleared fs/-40 C, not optimised values.
    _v("rem_vwl_2p0", "remedy:write_wordline_boost", "grid_both",
       "write wordline boosted to 2.0 V (needs a boosted WL supply; 1.8 V device overdriven)", vwl_v=2.0),
    _v("rem_rwl_m0p2", "remedy:read_wordline_underdrive", "grid_both",
       "selected read wordline driven to -0.2 V (needs a negative read-WL supply)", vrwl_sel_v=-0.2),
    _v("rem_wr_lvt", "remedy:write_device_lvt", "grid_both",
       "M_WR low-Vt flavour (raises written level; costs storage-node leakage)", wr_model=NFET_LVT),
    _v("rem_rd_lvt", "remedy:read_device_lvt", "grid_fresh",
       "M_RD low-Vt flavour (raises read current; fresh-only screen)", rd_model=NFET_LVT),
] + [
    # --- negative control: write disabled, .ic opposite to data ----------
    _v("nc_write_disabled", "negative_control", "nc",
       "write wordline never rises, so every cell keeps the INVERSE of its data; "
       "signed separation must be negative and the point must FAIL", vwl_v=0.0),
]

BY_ID = {v["id"]: v for v in VARIANTS}


if len(BY_ID) != len(VARIANTS):
    raise ValueError("duplicate variant id")


def knobs(vid: str) -> dict:
    k = dict(BASELINE)
    k.update(BY_ID[vid]["changes"])
    return k


def variant_sha(vid: str) -> str:
    """Hash of the variant's full knob set + scope (stamped on every row)."""
    v = BY_ID[vid]
    blob = json.dumps({"knobs": knobs(vid), "scope": v["scope"]}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def points_for_scope(scope: str):
    cts, ages = SCOPES[scope]
    return [(c, t, a) for (c, t) in cts for a in ages]


def points(vid: str):
    return points_for_scope(BY_ID[vid]["scope"])
