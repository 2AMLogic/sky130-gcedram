#!/usr/bin/env python3
"""Stdlib-only drift check: design/sense_latch.spice vs the sense-stage deck (issue #109).

The latch devices of the design of record (design/sense_latch.sch, via its
derived netlist) must equal -- names, model, W/L, nets, and every geometry
parameter (nf, ad/as, pd/ps, nrd/nrs, sa/sb/sd, mult, m) -- what
sim/sense-stage/sense_stage.spice instantiates for every instance block.
No xschem, ngspice or PDK needed. The X-card parser, netlist walker and deck
matcher are imported from test_column_periphery (issue #410) rather than
duplicated here.

Run: python3 -I design/test_sense_latch.py
"""
from __future__ import annotations

import hashlib
import re
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # python3 -I omits the script directory from sys.path

from test_column_periphery import (  # noqa: E402  (needs the sys.path insert above)
    GROUND,
    LATCH_DEVICES,
    canon,
    deck_devices,
    logical_lines,
    netlist_devices,
    parse_device,
)

REPO = HERE.parent
SCH = HERE / "sense_latch.sch"
NETLIST = HERE / "sense_latch.spice"
DECK = REPO / "sim" / "sense-stage" / "sense_stage.spice"


class SenseLatchMatchesDeck(unittest.TestCase):
    def test_netlist_has_exactly_the_six_latch_devices(self):
        self.assertEqual(sorted(netlist_devices(NETLIST)), sorted(LATCH_DEVICES))

    def test_netlist_provenance_hash_matches_schematic(self):
        h = hashlib.sha256(SCH.read_bytes()).hexdigest()
        self.assertIn(f"design/sense_latch.sch: sha256:{h}", NETLIST.read_text(),
                      "netlist stale vs schematic; run design/regen_netlist.sh")

    def test_deck_has_instances(self):
        self.assertGreater(len(deck_devices(LATCH_DEVICES, DECK, shared=GROUND, skip_prefix=None)), 0)

    def test_every_deck_instance_equals_schematic(self):
        sch = netlist_devices(NETLIST)
        inst = deck_devices(LATCH_DEVICES, DECK, shared=GROUND, skip_prefix=None)
        for suffix, devs in inst.items():
            with self.subTest(instance=suffix):
                self.assertEqual(sorted(devs), sorted(LATCH_DEVICES))
                for name in LATCH_DEVICES:
                    self.assertEqual(devs[name], sch[name], f"{name} in {suffix} drifted from design/sense_latch.sch")

    def test_dropped_geometry_parameter_is_a_failure(self):
        # negative control (issue #410): a latch card missing a geometry
        # parameter (here nrd) parses as nrd=None and must not equal the
        # intact schematic card, so a deck regression that drops or alters
        # nrd cannot pass test_every_deck_instance_equals_schematic silently
        card = next(ln for ln in logical_lines(NETLIST.read_text()) if ln.split()[:1] == ["XMN1"])
        doctored = parse_device(re.sub(r" nrd=[-\w.]+", "", card))
        self.assertIsNone(doctored["nrd"])
        self.assertNotEqual(doctored, netlist_devices(NETLIST)["MN1"])

    def test_numbered_nets_are_preserved(self):
        # regression (issue #410): column-periphery's numbered-control rewrite
        # (pcb_<n>/sel_<n>/selb_<n>) must not collapse distinct numbered nets
        # in the sense-latch schematic or sense-stage deck
        for net in ("pcb_1", "sel_1", "selb_1"):
            self.assertEqual(canon(net, None), net)
            self.assertEqual(canon(net, "st_m100mv", GROUND), net)
        with tempfile.TemporaryDirectory() as tmp:
            sch_path = Path(tmp) / "sense_latch.spice"
            deck_path = Path(tmp) / "sense_stage.spice"
            sch_path.write_text(re.sub(r"\brbl\b", "sel_1", NETLIST.read_text()))
            deck_path.write_text(re.sub(r"\brbl_(\w+)", r"sel_2_\1", DECK.read_text()))
            sch = netlist_devices(sch_path)
            inst = deck_devices(LATCH_DEVICES, deck_path, shared=GROUND, skip_prefix=None)
        self.assertGreater(len(inst), 0)
        self.assertEqual(sch["MN1"]["nets"][0], "sel_1")
        for suffix, devs in inst.items():
            with self.subTest(instance=suffix):
                self.assertEqual(devs["MN1"]["nets"][0], "sel_2")
                self.assertNotEqual(devs["MN1"], sch["MN1"])

    def test_tab_delimited_deck_instance_is_parsed(self):
        # regression (issue #410): changing the first separator to a tab (or
        # lowercasing the X designator) on an instance's latch cards must not
        # silently drop that instance from the deck comparison
        intact = deck_devices(LATCH_DEVICES, DECK, shared=GROUND, skip_prefix=None)
        tabbed = re.sub(
            r"(?m)^(X(?:%s)_st_m100mv) " % "|".join(LATCH_DEVICES),
            r"\1\t",
            DECK.read_text(),
        )
        tabbed = tabbed.replace("XMN1_st_m100mv\t", "xMN1_st_m100mv\t", 1)
        with tempfile.TemporaryDirectory() as tmp:
            deck_path = Path(tmp) / "tabbed_sense_stage.spice"
            deck_path.write_text(tabbed)
            got = deck_devices(LATCH_DEVICES, deck_path, shared=GROUND, skip_prefix=None)
        self.assertEqual(len(got), len(intact))
        self.assertIn("st_m100mv", got)
        self.assertEqual(got["st_m100mv"], netlist_devices(NETLIST))

    def test_testbench_elements_not_in_cell(self):
        # ideal precharge switch / dummy reference stay in the testbench
        text = NETLIST.read_text()
        self.assertNotRegex(text, r"(?m)^[SV]\w* ")


if __name__ == "__main__":
    unittest.main()
