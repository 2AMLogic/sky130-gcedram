#!/usr/bin/env python3
"""Stdlib-only drift check: design/column_periphery.spice vs the comparison decks (issues #114, #117).

* The FINAL variant (`f00_*`) of sim/column-periphery/isolation_study.spice must instantiate exactly
  the devices of the schematic-derived netlist design/column_periphery.spice (names, model, W/L,
  nets and every geometry parameter: nf, ad/as, pd/ps, nrd/nrs, sa/sb/sd, m).
* The #114 evidence deck sim/column-periphery/column_periphery.spice is frozen evidence of the
  first-pass slice, which the schematic no longer equals (issue #117 resized it). It is checked
  against itself (every real_* instance identical; sweep instances differ only in the precharge
  width and its width-dependent geometry) and the study's baseline variant (`i00_*`) must equal it,
  so the baseline of the sweep cannot drift from what #114 recorded.
* The latch devices of every instance must equal design/sense_latch.spice.
No xschem, ngspice or PDK needed.

Run: python3 -I design/test_column_periphery.py
"""
from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SCH = HERE / "column_periphery.sch"
NETLIST = HERE / "column_periphery.spice"
LATCH = HERE / "sense_latch.spice"
DECK = REPO / "sim" / "column-periphery" / "column_periphery.spice"

PERIPHERY_DEVICES = ("MPPRE", "MPPREF", "MPU1", "MPU2", "MND2", "MND1", "MNI", "MNS", "MNSR")
BASELINE_114_DEVICES = ("MPPRE", "MPU1", "MPU2", "MND2", "MND1", "MNI", "MNS", "MPS", "MNSR", "MPSR")
STUDY = REPO / "sim" / "column-periphery" / "isolation_study.spice"
LATCH_DEVICES = ("MN1", "MN2", "MP1", "MP2", "MNF", "MPH")
SHARED = {"pref": "vref", "pcb": "pre_b", "prea": "vpre", "dinb1": "dinb", "dinb0": "dinb", "0": "GND",
          "wen": "wen", "wenb": "wenb", "sel": "sel", "selb": "selb", "vdd": "vdd",
          "en": "en", "enb": "enb"}
LOCAL = ("rbl", "sbl", "ref", "sref", "wbl", "x", "y", "vn", "vp")


def logical_lines(text: str):
    out: list[str] = []
    for ln in text.splitlines():
        if ln.startswith("+") and out:
            out[-1] += " " + ln[1:].strip()
        else:
            out.append(ln)
    return out


GEOMETRY = ("nf", "ad", "as", "pd", "ps", "nrd", "nrs", "sa", "sb", "sd", "mult", "m")
DIFF_UM = 0.29  # single-finger diffusion length of the xschem/bitcell convention


def parse_device(line: str):
    """nets, model, W/L and every geometry parameter (all parsed as numbers)."""
    t = line.split()
    params = dict(p.split("=", 1) for p in t[6:] if "=" in p)
    unknown = set(params) - {"W", "L", *GEOMETRY}
    if unknown:
        raise AssertionError(f"unexpected device parameters {sorted(unknown)} in: {line}")
    d = {"nets": tuple(t[1:5]), "model": t[5], "W": float(params["W"]), "L": float(params["L"])}
    for k in GEOMETRY:
        d[k] = round(float(params[k]), 9) if k in params else None
    return d


def resized(dev: dict, w_um: float) -> dict:
    """Independent expectation for a single-finger device resized to w_um:
    ad = as = W*0.29, pd = ps = 2*(W+0.29), nrd = nrs = 0.29/W; L, nf, sa/sb/sd, m unchanged."""
    want = dict(dev)
    want["W"] = w_um
    want["ad"] = want["as"] = round(w_um * DIFF_UM, 9)
    want["pd"] = want["ps"] = round(2 * (w_um + DIFF_UM), 9)
    want["nrd"] = want["nrs"] = round(DIFF_UM / w_um, 9)
    return want


def canon(net: str, inst: str | None) -> str:
    if inst and net.endswith("_" + inst):
        net = net[: -len(inst) - 1]
    net = re.sub(r"^(pcb|selb?)_\d+$", r"\1", net)  # per-edge-time control copies in the study deck
    return SHARED.get(net, net) if inst else {"GND": "GND", "0": "GND"}.get(net, net)


def netlist_devices(path: Path, names):
    devs = {}
    for ln in logical_lines(path.read_text()):
        m = re.match(r"X(\w+) ", ln)
        if m and not ln.startswith("*") and m.group(1) in names:
            d = parse_device(ln)
            d["nets"] = tuple(canon(n, None) for n in d["nets"])
            devs[m.group(1)] = d
    return devs


def deck_devices(names, path=DECK):
    """{instance: {device: parsed}} for the given device names."""
    pat = re.compile(r"X(%s)_(\w+) " % "|".join(names))
    inst: dict[str, dict] = {}
    for ln in logical_lines(path.read_text()):
        m = pat.match(ln)
        if not m or m.group(2).startswith("cp_"):
            continue
        d = parse_device(ln)
        d["nets"] = tuple(canon(n, m.group(2)) for n in d["nets"])
        inst.setdefault(m.group(2), {})[m.group(1)] = d
    return inst


class ColumnPeripheryMatchesDeck(unittest.TestCase):
    def test_netlist_has_exactly_the_slice_devices(self):
        self.assertEqual(sorted(netlist_devices(NETLIST, PERIPHERY_DEVICES)), sorted(PERIPHERY_DEVICES))

    def test_netlist_provenance_hash_matches_schematic(self):
        h = hashlib.sha256(SCH.read_bytes()).hexdigest()
        self.assertIn(f"design/column_periphery.sch: sha256:{h}", NETLIST.read_text(),
                      "netlist stale vs schematic; run design/regen_netlist.sh")

    def test_netlist_has_no_testbench_elements(self):
        self.assertNotRegex(NETLIST.read_text(), r"(?m)^[SVRC]\w* ")

    def test_final_study_instances_equal_schematic(self):
        sch = netlist_devices(NETLIST, PERIPHERY_DEVICES)
        inst = deck_devices(PERIPHERY_DEVICES, STUDY)
        finals = {k: v for k, v in inst.items() if k.startswith("f00_")}
        self.assertEqual(sorted(finals), ["f00_w0", "f00_w1"])
        for name, devs in finals.items():
            with self.subTest(instance=name):
                self.assertEqual(sorted(devs), sorted(PERIPHERY_DEVICES))
                for dev in PERIPHERY_DEVICES:
                    self.assertEqual(devs[dev], sch[dev], f"{dev} in {name} drifted from design/column_periphery.sch")

    def test_study_baseline_equals_114_deck(self):
        base = deck_devices(BASELINE_114_DEVICES)["real_w1"]
        got = deck_devices(BASELINE_114_DEVICES, STUDY)
        for name in ("i00_w1", "i00_w0"):
            with self.subTest(instance=name):
                for dev in BASELINE_114_DEVICES:
                    want = dict(base[dev])
                    if name.endswith("_w0") and "dinb" in want["nets"]:
                        pass  # dinb1/dinb0 both canonicalise to dinb
                    self.assertEqual(got[name][dev], want, f"{dev} in {name} drifted from the #114 baseline")

    def test_114_deck_is_self_consistent(self):
        inst = deck_devices(BASELINE_114_DEVICES)
        self.assertTrue(any(k.startswith("real_") for k in inst))
        self.assertTrue(any(k.startswith("sw_") for k in inst))
        self.assertFalse(any(k.startswith("ideal_") for k in inst), "ideal instances must not carry the slice")
        base = inst["real_w1"]
        for name, devs in inst.items():
            with self.subTest(instance=name):
                self.assertEqual(sorted(devs), sorted(BASELINE_114_DEVICES))
                for dev in BASELINE_114_DEVICES:
                    want = dict(base[dev])
                    if name.startswith("sw_") and dev == "MPPRE":
                        want = resized(base[dev], int(name.split("_")[1]) / 100)
                    self.assertEqual(devs[dev], want, f"{dev} in {name}")

    def test_parser_keeps_full_geometry(self):
        mp = netlist_devices(NETLIST, PERIPHERY_DEVICES)["MPPRE"]
        for k in ("ad", "as", "pd", "ps", "nrd", "nrs"):
            self.assertIsNotNone(mp[k], f"{k} not parsed; geometry would go unchecked")

    def test_resize_convention_reproduces_every_schematic_device(self):
        # the single-finger rule used for the sweep expectation must reproduce the
        # schematic's own geometry at the schematic width, for every slice device
        for dev, d in netlist_devices(NETLIST, PERIPHERY_DEVICES).items():
            with self.subTest(device=dev):
                self.assertEqual(resized(d, d["W"]), d)

    def test_sweep_geometry_would_catch_unscaled_square_counts(self):
        # regression for the first sweep (run 20261009T204412Z): nrd/nrs left at the W=4 value
        sch = netlist_devices(NETLIST, PERIPHERY_DEVICES)["MPPRE"]
        stale = resized(sch, 1.0)
        stale["nrd"] = stale["nrs"] = sch["nrd"]
        self.assertNotEqual(stale, resized(sch, 1.0))
        got = deck_devices(("MPPRE",))["sw_0100"]["MPPRE"]
        self.assertEqual((got["nrd"], got["nrs"]), (0.29, 0.29))
        got8 = deck_devices(("MPPRE",))["sw_0800"]["MPPRE"]
        self.assertEqual((got8["nrd"], got8["nrs"]), (0.03625, 0.03625))

    def test_every_instance_latch_equals_sense_latch(self):
        lat = netlist_devices(LATCH, LATCH_DEVICES)
        inst = deck_devices(LATCH_DEVICES)
        self.assertGreaterEqual(len(inst), 8)
        for name, devs in inst.items():
            with self.subTest(instance=name):
                self.assertEqual(sorted(devs), sorted(LATCH_DEVICES))
                for dev in LATCH_DEVICES:
                    got = dict(devs[dev])
                    # latch input side: sbl in real/sw instances, rbl directly in ideal ones
                    got["nets"] = tuple({"sbl": "rbl", "sref": "ref"}.get(n, n) for n in got["nets"])
                    self.assertEqual(got, lat[dev], f"{dev} in {name} drifted from design/sense_latch.sch")

    def test_precharge_well_is_on_the_precharge_rail(self):
        # documented in the schematic header: MPPRE body = vpre, not vdd
        devs = netlist_devices(NETLIST, PERIPHERY_DEVICES)
        self.assertEqual(devs["MPPRE"]["nets"][3], "vpre")
        self.assertEqual(devs["MPPREF"]["nets"][3], "vref")

    def test_reference_precharge_is_a_copy_of_the_bitline_precharge(self):
        devs = netlist_devices(NETLIST, PERIPHERY_DEVICES)
        a, b = dict(devs["MPPRE"]), dict(devs["MPPREF"])
        self.assertEqual(a.pop("nets"), ("rbl", "pre_b", "vpre", "vpre"))
        self.assertEqual(b.pop("nets"), ("ref", "pre_b", "vref", "vref"))
        self.assertEqual(a, b)

    def test_final_isolation_is_nfet_only_and_dummy_matched(self):
        devs = netlist_devices(NETLIST, PERIPHERY_DEVICES)
        self.assertNotIn("MPS", devs)
        self.assertEqual(devs["MNS"]["W"], devs["MNSR"]["W"])
        self.assertEqual(devs["MNS"]["nets"], ("sbl", "sel", "rbl", "GND"))
        self.assertEqual(devs["MNSR"]["nets"], ("sref", "sel", "ref", "GND"))


if __name__ == "__main__":
    unittest.main()
