#!/usr/bin/env python3
"""Stdlib-only consistency checks for the compaction variants (issue #100).

No klt, KLayout, magic or PDK needed. It re-derives what can be re-derived
from committed bytes:

  * each variant's committed GDS/layout/mos files are the ones its recorded
    density result was computed from (sha256), and the recorded areas equal
    an independent recomputation from the committed artifacts;
  * the GDS extents equal the layout.json bbox;
  * the committed check results are all clean (klt drc, klt lvs, KLayout
    sky130A_mr, gate-level rules, magic drc(full));
  * layout/area_density.py with default arguments still reproduces the
    committed baseline result (the --layout-json/--mos-json/--gds flags did
    not change the default behaviour);
  * variants keep the ratified topology (32 devices, W=0.42, L=0.15 in the
    LVS reference) and never re-use the committed baseline's files.

Byte-for-byte regeneration of the GDS needs KLayout and is gated by
`layout/compact/generate.sh --check`.

Run: python3 -I layout/compact/test_compact.py
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAYOUT = HERE.parent
REPO = LAYOUT.parent
sys.path.insert(0, str(LAYOUT))
import area_density as A  # noqa: E402

VARIANTS = ("v1", "v2")
SRAM_PRIMARY_UM2 = 2.0698  # 1.31 x 1.58, quoted-not-measured (spec/density-vs-sram.md S4)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def stem(v: str) -> str:
    return f"gain_cell_2t_{v}_array"


def result_path(v: str) -> Path:
    found = sorted((LAYOUT / "results").glob(f"density_*_{v}.json"))
    assert len(found) == 1, f"expected exactly one density result for {v}: {found}"
    return found[0]


class VariantTests(unittest.TestCase):
    def test_density_result_matches_committed_inputs(self):
        for v in VARIANTS:
            with self.subTest(v=v):
                res = json.loads(result_path(v).read_text())
                s = stem(v)
                self.assertEqual(res["issue"], 100)
                self.assertEqual(res["inputs"]["gds_sha256"], sha(HERE / f"{s}.gds"))
                self.assertEqual(res["inputs"]["layout_json_sha256"], sha(HERE / f"{s}.layout.json"))
                self.assertEqual(res["inputs"]["mos_json_sha256"], sha(HERE / f"{s}_mos.json"))
                mos = json.loads((HERE / f"{s}_mos.json").read_text())
                lay = json.loads((HERE / f"{s}.layout.json").read_text())
                px, py = A.derive_pitch(mos)
                a = res["a_drawn_bitcell_pitch"]
                self.assertEqual((a["pitch_x_um"], a["pitch_y_um"]), (px, py))
                self.assertAlmostEqual(a["area_um2"], round(px * py, 4), places=4)
                b = lay["bbox_um"]
                ext = A.gds_extents(HERE / f"{s}.gds")
                self.assertAlmostEqual(ext["x1"] - ext["x0"], b["x1"] - b["x0"], places=2)
                self.assertAlmostEqual(ext["y1"] - ext["y0"], b["y1"] - b["y0"], places=2)
                bits = 16
                self.assertAlmostEqual(
                    res["b_array_per_bit_with_shared_tap"]["um2_per_bit"],
                    round((b["x1"] - b["x0"]) * (b["y1"] - b["y0"]) / bits, 4), places=4)
                primary = res["sram_comparators"][0]
                self.assertEqual(primary["kind"], "quoted-not-measured")
                self.assertAlmostEqual(primary["area_um2"], SRAM_PRIMARY_UM2, places=4)
                self.assertEqual(res["verdict"]["2T_beats_sram_cell_on_area"],
                                 px * py < SRAM_PRIMARY_UM2)

    def test_committed_checks_are_clean(self):
        for v in VARIANTS:
            with self.subTest(v=v):
                s = stem(v)
                drc = json.loads((HERE / f"{s}.drc.result.json").read_text())
                self.assertEqual((drc["status"], drc["violation_count"]), ("clean", 0))
                lvs = json.loads((HERE / f"{s}.lvs.result.json").read_text())
                self.assertEqual(lvs["status"], "match")
                self.assertEqual(lvs["counts"]["devices"],
                                 {"layout": 32, "reference": 32, "matched": 32})
                for name in ("mr_drc", "extra_rules", "magic_drc"):
                    r = json.loads((HERE / f"{s}.{name}.result.json").read_text())
                    self.assertEqual(r["total"], 0, f"{s}.{name}: {r}")

    def test_topology_is_the_ratified_two_transistor_cell(self):
        for v in VARIANTS:
            with self.subTest(v=v):
                ref = (HERE / f"{stem(v)}.lvs_reference.spice").read_text()
                devs = [l for l in ref.splitlines() if l.startswith("M_")]
                self.assertEqual(len(devs), 32)
                for l in devs:
                    self.assertTrue(re.search(r" nfet L=0\.15U W=0\.42U$", l), l)
                self.assertEqual(sum(l.startswith("M_WR_") for l in devs), 16)
                self.assertEqual(sum(l.startswith("M_RD_") for l in devs), 16)

    def test_baseline_files_untouched_by_variants(self):
        # variants write only new files; the baseline GDS hash is the one
        # recorded in the committed baseline density result
        base = json.loads((LAYOUT / "results" / "density_20261009.json").read_text())
        self.assertEqual(base["inputs"]["gds_sha256"], sha(LAYOUT / "gain_cell_2t_array.gds"))

    def test_default_area_density_run_unchanged(self):
        out = subprocess.run([sys.executable, "-I", str(LAYOUT / "area_density.py"), "--dry-run"],
                             capture_output=True, text=True, check=True).stdout
        new, old = json.loads(out), json.loads((LAYOUT / "results" / "density_20261009.json").read_text())
        for d in (new, old):
            d.pop("generated_utc"), d.pop("klt_version_on_host")
        self.assertEqual(new, old)

    def test_variant_flags_accepted_by_area_density(self):
        r = subprocess.run(
            [sys.executable, "-I", str(LAYOUT / "area_density.py"), "--tag", "v2", "--issue", "100",
             "--layout-json", str(HERE / f"{stem('v2')}.layout.json"),
             "--mos-json", str(HERE / f"{stem('v2')}_mos.json"),
             "--gds", str(HERE / f"{stem('v2')}.gds"), "--dry-run"],
            capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
