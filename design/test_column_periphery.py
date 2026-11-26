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

This module also hosts the shared SPICE X-card parser and deck matcher that
design/test_sense_latch.py imports (issue #410).

Run: python3 -I design/test_column_periphery.py
"""
from __future__ import annotations

import hashlib
import re
import tempfile
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
# netlist-side ground canonicalisation; other decks (sense_stage.spice) pass
# their own `shared` map instead of inheriting the slice-only aliases above
GROUND = {"GND": "GND", "0": "GND"}


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


NUMBERED_CONTROLS = re.compile(r"^(pcb|selb?)_\d+$")


def _x_card_name(line: str) -> str | None:
    """Return the full instance name after a leading X/x designator, or None."""
    tokens = line.split()
    if not tokens:
        return None
    head = tokens[0]
    if len(head) < 2 or head[0] not in ("X", "x"):
        return None
    return head[1:]


def canon(net: str, inst: str | None, shared=SHARED, *, strip_numbered_controls: bool | None = None) -> str:
    if not inst:
        return GROUND.get(net, net)
    if net.endswith("_" + inst):
        return net[: -len(inst) - 1]
    if strip_numbered_controls is None:
        strip_numbered_controls = shared is SHARED
    if strip_numbered_controls:
        net = NUMBERED_CONTROLS.sub(r"\1", net)  # per-edge-time control copies in the study deck
    return shared.get(net, net)


def netlist_devices(path: Path):
    """{name: parsed} for every X card in the netlist at `path`.

    Deliberately unfiltered (issue #410): an unexpected card must surface here
    -- and so fail the exactness tests -- not be silently discarded."""
    devs = {}
    for ln in logical_lines(path.read_text()):
        name = _x_card_name(ln)
        if name is None:
            continue
        d = parse_device(ln)
        d["nets"] = tuple(canon(n, None) for n in d["nets"])
        devs[name] = d
    return devs


def deck_devices(names, path=DECK, *, shared=SHARED, skip_prefix="cp_", strip_numbered_controls: bool | None = None):
    """{instance: {device: parsed}} for the given device names.

    `shared` is the deck-side net canonicalisation map; `skip_prefix` drops
    instances whose name starts with it (the study deck's `cp_` copies).
    `strip_numbered_controls` defaults to True only for `SHARED` (rewriting
    column-periphery study controls `pcb_<n>`/`sel_<n>`/`selb_<n>`)."""
    if not names:
        return {}
    pat = re.compile(r"(%s)_(.+)" % "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)))
    inst: dict[str, dict] = {}
    for ln in logical_lines(path.read_text()):
        full_name = _x_card_name(ln)
        if full_name is None:
            continue
        m = pat.fullmatch(full_name)
        if not m or (skip_prefix and m.group(2).startswith(skip_prefix)):
            continue
        dev_name, suffix = m.group(1), m.group(2)
        d = parse_device(ln)
        d["nets"] = tuple(
            canon(n, suffix, shared, strip_numbered_controls=strip_numbered_controls)
            for n in d["nets"]
        )
        inst.setdefault(suffix, {})[dev_name] = d
    return inst


class ColumnPeripheryMatchesDeck(unittest.TestCase):
    def test_netlist_has_exactly_the_slice_devices(self):
        self.assertEqual(sorted(netlist_devices(NETLIST)), sorted(PERIPHERY_DEVICES))

    def test_netlist_devices_surfaces_extra_cards(self):
        # negative control (issue #410): an extra X card in netlist text must
        # surface in netlist_devices() -- regardless of SPICE whitespace, X/x
        # case, or non-word characters in the instance name -- instead of being
        # filtered out before the exactness / NFET-only assertions run
        body = ("dinb gnd gnd gnd sky130_fd_pr__nfet_01v8 L=0.15 W=1 nf=1"
                " ad=0.29 as=0.29 pd=2.58 ps=2.58 nrd=0.29 nrs=0.29"
                " sa=0 sb=0 sd=0 mult=1 m=1")
        base_text = NETLIST.read_text()
        cases = (
            ("XMPS ", "MPS"),
            ("XMPS\t", "MPS"),
            ("xMPS\t", "MPS"),
            ("XMPS-extra ", "MPS-extra"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            for idx, (prefix, expected_name) in enumerate(cases):
                with self.subTest(prefix=prefix):
                    doctored = Path(tmp) / f"extra_{idx}.spice"
                    doctored.write_text(base_text.replace(".end\n", f"{prefix}{body}\n.end\n", 1))
                    devs = netlist_devices(doctored)
                    self.assertIn(expected_name, devs)
                    self.assertNotEqual(sorted(devs), sorted(PERIPHERY_DEVICES))

    def test_deck_devices_handles_tabs_lowercase_x_and_nonword_instances(self):
        # deck X-card recognition must split on SPICE whitespace, accept a
        # lowercase x designator, and keep the full instance name (including
        # non-word characters such as hyphens)
        intact = deck_devices(BASELINE_114_DEVICES)
        text = DECK.read_text()
        tabbed = re.sub(
            r"(?m)^(X(?:%s)_real_w1) " % "|".join(BASELINE_114_DEVICES),
            r"\1\t",
            text,
        )
        tabbed = tabbed.replace("XMPPRE_real_w1\t", "xMPPRE_real_w1\t", 1)
        hyphenated = text.replace("_real_w1", "_real-w1")
        with tempfile.TemporaryDirectory() as tmp:
            tab_path = Path(tmp) / "tabbed.spice"
            tab_path.write_text(tabbed)
            got_tab = deck_devices(BASELINE_114_DEVICES, tab_path)
            self.assertEqual(len(got_tab), len(intact))
            self.assertEqual(got_tab["real_w1"], intact["real_w1"])

            hyp_path = Path(tmp) / "hyphen.spice"
            hyp_path.write_text(hyphenated)
            got_hyp = deck_devices(BASELINE_114_DEVICES, hyp_path)
            self.assertIn("real-w1", got_hyp)
            self.assertEqual(got_hyp["real-w1"], intact["real_w1"])

    def test_netlist_provenance_hash_matches_schematic(self):
        h = hashlib.sha256(SCH.read_bytes()).hexdigest()
        self.assertIn(f"design/column_periphery.sch: sha256:{h}", NETLIST.read_text(),
                      "netlist stale vs schematic; run design/regen_netlist.sh")

    def test_netlist_has_no_testbench_elements(self):
        self.assertNotRegex(NETLIST.read_text(), r"(?m)^[SVRC]\w* ")

    def test_final_study_instances_equal_schematic(self):
        sch = netlist_devices(NETLIST)
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
                    self.assertEqual(got[name][dev], base[dev], f"{dev} in {name} drifted from the #114 baseline")

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
        mp = netlist_devices(NETLIST)["MPPRE"]
        for k in ("ad", "as", "pd", "ps", "nrd", "nrs"):
            self.assertIsNotNone(mp[k], f"{k} not parsed; geometry would go unchecked")

    def test_resize_convention_reproduces_every_schematic_device(self):
        # the single-finger rule used for the sweep expectation must reproduce the
        # schematic's own geometry at the schematic width, for every slice device
        for dev, d in netlist_devices(NETLIST).items():
            with self.subTest(device=dev):
                self.assertEqual(resized(d, d["W"]), d)

    def test_sweep_geometry_would_catch_unscaled_square_counts(self):
        # regression for the first sweep (run 20261009T204412Z): nrd/nrs left at the W=4 value
        sch = netlist_devices(NETLIST)["MPPRE"]
        stale = resized(sch, 1.0)
        stale["nrd"] = stale["nrs"] = sch["nrd"]
        self.assertNotEqual(stale, resized(sch, 1.0))
        got = deck_devices(("MPPRE",))["sw_0100"]["MPPRE"]
        self.assertEqual((got["nrd"], got["nrs"]), (0.29, 0.29))
        got8 = deck_devices(("MPPRE",))["sw_0800"]["MPPRE"]
        self.assertEqual((got8["nrd"], got8["nrs"]), (0.03625, 0.03625))

    def test_every_instance_latch_equals_sense_latch(self):
        lat = netlist_devices(LATCH)
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
        devs = netlist_devices(NETLIST)
        self.assertEqual(devs["MPPRE"]["nets"][3], "vpre")
        self.assertEqual(devs["MPPREF"]["nets"][3], "vref")

    def test_reference_precharge_is_a_copy_of_the_bitline_precharge(self):
        devs = netlist_devices(NETLIST)
        a, b = dict(devs["MPPRE"]), dict(devs["MPPREF"])
        self.assertEqual(a.pop("nets"), ("rbl", "pre_b", "vpre", "vpre"))
        self.assertEqual(b.pop("nets"), ("ref", "pre_b", "vref", "vref"))
        self.assertEqual(a, b)

    def test_final_isolation_is_nfet_only_and_dummy_matched(self):
        devs = netlist_devices(NETLIST)
        self.assertNotIn("MPS", devs)
        self.assertEqual(devs["MNS"]["W"], devs["MNSR"]["W"])
        self.assertEqual(devs["MNS"]["nets"], ("sbl", "sel", "rbl", "GND"))
        self.assertEqual(devs["MNSR"]["nets"], ("sref", "sel", "ref", "GND"))


if __name__ == "__main__":
    unittest.main()
