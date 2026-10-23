#!/usr/bin/env python3
"""Unit tests for the shared klt sim request skeleton in klt_request.py
(issue #196). Run: python3 sim/test_klt_request.py"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # `python -I` safe
import klt_request as K  # noqa: E402

CORNERS = {"process": ["tt"], "temperature_c": [25]}
MEAS = [{"name": "m", "unit": "V", "spice": ".meas tran m FIND v(a) AT=1n"}]


class BuildRequest(unittest.TestCase):
    def test_plain_key_order(self):
        r = K.build_request("a.spice", CORNERS, "10p 1n 0 50p uic", MEAS, 900)
        self.assertEqual(list(r), ["netlist", "engine", "backend", "models", "corners",
                                   "analysis", "measurements", "options"])
        self.assertEqual(r["analysis"], {"kind": "tran", "args": "10p 1n 0 50p uic"})
        self.assertEqual(r["options"], {"timeout_s": 900, "keep_artifacts": False, "waveforms": False})
        self.assertEqual(r["models"]["pdk"], "sky130A")

    def test_exclude_before_monte_carlo(self):
        ex = [{"process": "ss", "temperature_c": 125}]
        r = K.build_request("a.spice", CORNERS, "x", MEAS, 900, exclude=ex,
                            monte_carlo=K.mc_block(10, 7))
        self.assertEqual(list(r)[5:7], ["exclude", "monte_carlo"])
        self.assertEqual(r["monte_carlo"], {"n": 10, "seed": 7, "vary": "mismatch",
                                            "quantiles": [2.5, 50, 97.5]})

    def test_empty_exclude_omitted(self):
        r = K.build_request("a.spice", CORNERS, "x", MEAS, 900, exclude=[])
        self.assertNotIn("exclude", r)

    def test_kind_and_extra_options(self):
        r = K.build_request("a.spice", CORNERS, "v 0 1 1", MEAS, 600, kind="dc",
                            extra_options={"ngspice_init": ["set numdgt=12"]})
        self.assertEqual(r["analysis"]["kind"], "dc")
        self.assertEqual(list(r["options"]), ["timeout_s", "keep_artifacts", "waveforms", "ngspice_init"])

    def test_models_not_aliased(self):
        r = K.build_request("a.spice", CORNERS, "x", MEAS, 900)
        r["models"]["pdk"] = "other"
        self.assertEqual(K.MODELS["pdk"], "sky130A")
        json.dumps(r)


if __name__ == "__main__":
    unittest.main()
