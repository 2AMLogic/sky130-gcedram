#!/usr/bin/env python3
"""Stdlib-only drift check: design/sense_latch.spice vs the sense-stage deck (issue #109).

The latch devices of the design of record (design/sense_latch.sch, via its
derived netlist) must equal -- names, model, W/L, nets -- what
sim/sense-stage/sense_stage.spice instantiates for every instance block.
No xschem, ngspice or PDK needed.

Run: python3 -I design/test_sense_latch.py
"""
from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SCH = HERE / "sense_latch.sch"
NETLIST = HERE / "sense_latch.spice"
DECK = REPO / "sim" / "sense-stage" / "sense_stage.spice"

LATCH_DEVICES = ("MN1", "MN2", "MP1", "MP2", "MNF", "MPH")
# Nets that are per-instance in the deck (suffixed _<instance>); the rest
# (en, enb, vdd, ground) are shared testbench nets. Schematic GND == deck 0.
LOCAL_NETS = ("rbl", "ref", "vn", "vp")
GROUND = {"GND": "0", "0": "0"}


def logical_lines(text: str):
    out: list[str] = []
    for ln in text.splitlines():
        if ln.startswith("+") and out:
            out[-1] += " " + ln[1:].strip()
        else:
            out.append(ln)
    return out


def parse_device(line: str):
    t = line.split()
    params = dict(p.split("=", 1) for p in t[6:] if "=" in p)
    return {
        "nets": tuple(t[1:5]),  # D G S B
        "model": t[5],
        "W": float(params["W"]),
        "L": float(params["L"]),
    }


def canon_net(net: str, suffix: str | None) -> str:
    net = GROUND.get(net, net)
    if suffix and net.endswith("_" + suffix):
        net = net[: -len(suffix) - 1]
    return net


def schematic_devices():
    devs = {}
    for ln in logical_lines(NETLIST.read_text()):
        m = re.match(r"X(\w+) ", ln)
        if m and not ln.startswith("*"):
            d = parse_device(ln)
            d["nets"] = tuple(canon_net(n, None) for n in d["nets"])
            devs[m.group(1)] = d
    return devs


def deck_devices():
    """{instance_suffix: {device_name: parsed}} for every latch device in the deck."""
    pat = re.compile(r"X(%s)_(\w+) " % "|".join(LATCH_DEVICES))
    inst: dict[str, dict] = {}
    for ln in logical_lines(DECK.read_text()):
        m = pat.match(ln)
        if not m:
            continue
        name, suffix = m.group(1), m.group(2)
        d = parse_device(ln)
        d["nets"] = tuple(canon_net(n, suffix) for n in d["nets"])
        inst.setdefault(suffix, {})[name] = d
    return inst


class SenseLatchMatchesDeck(unittest.TestCase):
    def test_netlist_has_exactly_the_six_latch_devices(self):
        self.assertEqual(sorted(schematic_devices()), sorted(LATCH_DEVICES))

    def test_netlist_provenance_hash_matches_schematic(self):
        h = hashlib.sha256(SCH.read_bytes()).hexdigest()
        self.assertIn(f"design/sense_latch.sch: sha256:{h}", NETLIST.read_text(),
                      "netlist stale vs schematic; run design/regen_netlist.sh")

    def test_deck_has_instances(self):
        self.assertGreater(len(deck_devices()), 0)

    def test_every_deck_instance_equals_schematic(self):
        sch = schematic_devices()
        for suffix, devs in deck_devices().items():
            with self.subTest(instance=suffix):
                self.assertEqual(sorted(devs), sorted(LATCH_DEVICES))
                for name in LATCH_DEVICES:
                    self.assertEqual(devs[name], sch[name], f"{name} in {suffix} drifted from design/sense_latch.sch")

    def test_testbench_elements_not_in_cell(self):
        # ideal precharge switch / dummy reference stay in the testbench
        text = NETLIST.read_text()
        self.assertNotRegex(text, r"(?m)^[SV]\w* ")


if __name__ == "__main__":
    unittest.main()
