#!/usr/bin/env python3
"""Unit tests for the shared SPICE/waveform helpers in _evidence_common.py
(issue #58). Run: python3 sim/test_evidence_common.py"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # `python -I` safe
import _evidence_common as C  # noqa: E402


class SpiceNumber(unittest.TestCase):
    def test_suffixes(self):
        self.assertEqual(C.spice_number("1k"), 1e3)
        self.assertEqual(C.spice_number("1meg"), 1e6)
        self.assertAlmostEqual(C.spice_number("100p"), 1e-10, places=22)
        self.assertEqual(C.spice_number("1.8"), 1.8)
        self.assertEqual(C.spice_number("1e-9"), 1e-9)

    def test_bad(self):
        with self.assertRaises(ValueError):
            C.spice_number("1x")
        with self.assertRaises(ValueError):
            C.spice_number("@@VRBL@@")


class Interp(unittest.TestCase):
    def test_basic_and_clamp(self):
        t, y = [0.0, 1.0, 2.0], [0.0, 10.0, 20.0]
        self.assertEqual(C.interp_at(t, y, 0.5), 5.0)
        self.assertEqual(C.interp_at(t, y, -1), 0.0)
        self.assertEqual(C.interp_at(t, y, 9), 20.0)

    def test_duplicate_timestamp(self):
        t, y = [0.0, 1.0, 1.0, 2.0], [0.0, 1.0, 5.0, 6.0]
        self.assertEqual(C.interp_at(t, y, 1.0), 5.0)
        self.assertEqual(C.interp_at(t, y, 1.5), 5.5)


class Crossings(unittest.TestCase):
    t, y = [0.0, 1.0, 2.0, 3.0], [1.0, 1.0, 0.5, 0.0]

    def test_semantics_differ(self):
        # absolute vs relative to t0
        self.assertAlmostEqual(C.first_crossing_below(self.t, self.y, 0.25, 1.0), 2.5)
        self.assertAlmostEqual(C.first_below(self.t, self.y, 1.0, 0.25), 1.5)
        # already below at start: first sample time vs 0.0
        self.assertEqual(C.first_crossing_below(self.t, self.y, 2.0, 0.5), 1.0)
        self.assertEqual(C.first_below(self.t, self.y, 0.5, 2.0), 0.0)
        self.assertIsNone(C.first_below(self.t, self.y, 0.0, -1.0))
        self.assertIsNone(C.first_crossing_below(self.t, self.y, -1.0, 0.0))


class ReadWrdata(unittest.TestCase):
    def test_layout_and_min_points(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "w.dat"
            p.write_text("junk\n" + "".join(
                f"{i} {i*2} {i} {i*3}\n" for i in range(5)))
            cols = C.read_wrdata(p, 3)
            self.assertEqual(cols, [[0, 1, 2, 3, 4], [0, 2, 4, 6, 8], [0, 3, 6, 9, 12]])
            with self.assertRaises(RuntimeError):
                C.read_wrdata(p, 10)


class PdkRevision(unittest.TestCase):
    """PDK resolution defaults to ~/.ciel and verifies the tree's
    open_pdks revision against the pin (issue #165)."""

    def _variant(self, root: Path, sources: str | None) -> Path:
        v = root / "sky130A"
        (v / "libs.tech/combined").mkdir(parents=True)
        (v / "libs.tech/combined/sky130.lib.spice").write_text("* lib\n")
        if sources is not None:
            (v / "SOURCES").write_text(sources)
        return v

    def test_match(self):
        with tempfile.TemporaryDirectory() as d:
            v = self._variant(Path(d), f"open_pdks {C.PDK_OPEN_PDKS_COMMIT}\nskywater-pdk abc\n")
            self.assertEqual(C.pdk_revision_problems(v), [])

    def test_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            v = self._variant(Path(d), "open_pdks " + "c6d73a35f524070e85faff4a6a9eef49553ebc2b\n")
            problems = C.pdk_revision_problems(v)
            self.assertEqual(len(problems), 1)
            self.assertIn("expected open_pdks f6eeac7d", problems[0])
            self.assertIn("actual c6d73a35", problems[0])

    def test_missing_sources_is_a_failure(self):
        with tempfile.TemporaryDirectory() as d:
            v = self._variant(Path(d), None)
            self.assertIn("not found", C.pdk_revision_problems(v)[0])
            v2 = self._variant(Path(d) / "x", "skywater-pdk abc\n")
            self.assertIn("no `open_pdks <sha>` line", C.pdk_revision_problems(v2)[0])

    def test_default_root_is_ciel_not_volare(self):
        old = os.environ.pop("PDK_ROOT", None)
        try:
            self.assertEqual(C.resolve_pdk_root(None), Path("~/.ciel").expanduser())
            self.assertNotEqual(C.resolve_pdk_root(None), Path("~/.volare").expanduser())
            os.environ["PDK_ROOT"] = "/somewhere"
            self.assertEqual(C.resolve_pdk_root(None), Path("/somewhere"))
            self.assertEqual(C.resolve_pdk_root("/cli"), Path("/cli"))
        finally:
            os.environ.pop("PDK_ROOT", None)
            if old is not None:
                os.environ["PDK_ROOT"] = old

    def test_env_check_fails_on_stray_revision(self):
        # check_ngspice_available must reject a present library whose SOURCES
        # names another revision, regardless of whether ngspice is on PATH.
        with tempfile.TemporaryDirectory() as d:
            v = self._variant(Path(d), "open_pdks " + "c6d73a35f524070e85faff4a6a9eef49553ebc2b\n")
            lib = C.resolve_ngspice_lib(Path(d), "sky130A")
            self.assertTrue(lib.is_file())
            self.assertFalse(C.check_ngspice_available(lib))
            (v / "SOURCES").write_text(f"open_pdks {C.PDK_OPEN_PDKS_COMMIT}\n")
            self.assertEqual(C.pdk_revision_problems(v), [])


class Sha256(unittest.TestCase):
    def test_hex_and_prefixed(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "x"
            f.write_bytes(b"abc")
            h = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
            self.assertEqual(C.sha256_hex(f), h)
            self.assertEqual(C.sha256_prefixed(f), "sha256:" + h)


class Decided(unittest.TestCase):
    def test_classification_and_edges(self):
        self.assertEqual(C.decided(None, 0.9), "none")
        self.assertEqual(C.decided(-0.9, 0.9), "1")
        self.assertEqual(C.decided(0.9, 0.9), "0")
        self.assertEqual(C.decided(-0.89, 0.9), "unresolved")
        self.assertEqual(C.decided(0.0, 0.9), "unresolved")


class LoadJson(unittest.TestCase):
    def test_plain_and_gzip(self):
        import gzip
        import json

        doc = {"corners": [{"name": "tt", "v": 1.5}]}
        with tempfile.TemporaryDirectory() as d:
            plain = Path(d) / "klt_report.json"
            plain.write_text(json.dumps(doc))
            gz = Path(d) / "klt_report.json.gz"
            with gzip.open(gz, "wt") as fh:
                json.dump(doc, fh)
            self.assertEqual(C.load_json(plain), doc)
            self.assertEqual(C.load_json(gz), doc)
            self.assertEqual(C.load_json(str(gz)), doc)


if __name__ == "__main__":
    unittest.main()
