#!/usr/bin/env python3
"""Stdlib-only checks for the array generation pin and baseline comparison
(issue #91): layout/compare_array_layout.py, layout/generation_toolchain.py
and the preflight in layout/generate_array.sh / extract_array_parasitics.sh.
No klt, KLayout or PDK needed: the toolchains are faked, and the GDS
fixtures are byte-level mutations of the committed array GDS.

Run: python3 -I layout/test_generation_reproducibility.py
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import compare_array_layout as C  # noqa: E402
import generation_toolchain as T  # noqa: E402

COMMITTED_GDS = HERE / "gain_cell_2t_array.gds"
TOP = "gain_cell_2t_array_4x4_layout_0"


# ---------------------------------------------------------------- GDS helpers
def records(data: bytes) -> list[list]:
    out = []
    i = 0
    while i < len(data):
        length, rtype, dtype = struct.unpack(">HBB", data[i:i + 4])
        out.append([rtype, dtype, bytearray(data[i + 4:i + length])])
        i += length
        if rtype == 0x04:
            break
    return out


def serialize(recs: list[list]) -> bytes:
    return b"".join(struct.pack(">HBB", len(p) + 4, t, d) + bytes(p) for t, d, p in recs)


def element_spans(recs: list[list], structure: str):
    """(start, end) record-index spans of each element in `structure`."""
    spans, in_struct, start = [], False, None
    for i, (t, _d, p) in enumerate(recs):
        if t == 0x06:
            in_struct = bytes(p).rstrip(b"\x00").decode() == structure
        elif in_struct and t in C.ELEMENT_START:
            start = i
        elif in_struct and t == 0x11 and start is not None:
            spans.append((start, i))
            start = None
    return spans


def first_element(recs, structure, kind):
    for s, e in element_spans(recs, structure):
        if recs[s][0] == kind:
            return s, e
    raise AssertionError(f"no element 0x{kind:02X} in {structure}")


def record_in(recs, span, rtype):
    for i in range(span[0], span[1]):
        if recs[i][0] == rtype:
            return recs[i]
    raise AssertionError(f"record 0x{rtype:02X} not in element")


class Tmp(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.dir = Path(self._d.name)
        self.base = COMMITTED_GDS.read_bytes()

    def tearDown(self):
        self._d.cleanup()

    def gds_compare(self, mutated: bytes) -> dict:
        a, b = self.dir / "a", self.dir / "b"
        a.mkdir(exist_ok=True)
        b.mkdir(exist_ok=True)
        (a / "x.gds").write_bytes(self.base)
        (b / "x.gds").write_bytes(mutated)
        return C.compare(a, b, [("x.gds", "gds")])["artifacts"][0]


# ------------------------------------------------------- comparison: GDS
class GdsComparison(Tmp):
    def test_identical(self):
        r = self.gds_compare(self.base)
        self.assertTrue(r["match"] and r["raw_identical"])

    def test_timestamp_only_change_matches_with_raw_hash_differing(self):
        recs = records(self.base)
        for t, _d, p in recs:
            if t in (0x01, 0x05):  # BGNLIB / BGNSTR: 12 int2 date fields
                p[:] = struct.pack(">12h", 2026, 10, 11, 6, 0, 0, 2026, 10, 11, 6, 0, 1)
        r = self.gds_compare(serialize(recs))
        self.assertFalse(r["raw_identical"])
        self.assertNotEqual(r["raw_sha256"]["committed"], r["raw_sha256"]["regenerated"])
        self.assertTrue(r["match"], r["differences"])
        self.assertEqual(r["canonical_sha256"]["committed"], r["canonical_sha256"]["regenerated"])

    def test_trailing_null_padding_matches(self):
        r = self.gds_compare(self.base + b"\x00" * 512)
        self.assertTrue(r["match"])
        self.assertFalse(r["raw_identical"])

    def test_moved_polygon_vertex_fails(self):
        recs = records(self.base)
        span = first_element(recs, TOP, 0x08)  # BOUNDARY
        xy = record_in(recs, span, 0x10)
        x = struct.unpack(">i", xy[2][:4])[0]
        xy[2][:4] = struct.pack(">i", x + 1)  # 1 dbu
        xy[2][-8:-4] = struct.pack(">i", x + 1)  # keep the polygon closed
        r = self.gds_compare(serialize(recs))
        self.assertFalse(r["match"])
        self.assertTrue(any("BOUNDARY" in d for d in r["differences"]), r["differences"])

    def test_changed_route_width_fails(self):
        recs = records(self.base)
        span = first_element(recs, TOP, 0x09)  # PATH
        w = record_in(recs, span, 0x0F)
        w[2][:] = struct.pack(">i", struct.unpack(">i", bytes(w[2]))[0] - 30)
        r = self.gds_compare(serialize(recs))
        self.assertFalse(r["match"])
        self.assertTrue(any("WIDTH=" in d for d in r["differences"]))

    def test_changed_route_layer_fails(self):
        recs = records(self.base)
        span = first_element(recs, TOP, 0x09)
        layer = record_in(recs, span, 0x0D)
        layer[2][:] = struct.pack(">h", 69)
        self.assertFalse(self.gds_compare(serialize(recs))["match"])

    def test_renamed_label_fails(self):
        recs = records(self.base)
        span = first_element(recs, TOP, 0x0C)  # TEXT
        s = record_in(recs, span, 0x19)
        old = bytes(s[2])
        new = bytearray(old)
        new[-1 if old[-1] != 0 else -2] ^= 0x01  # e.g. bl_0 -> bl_1
        s[2][:] = new
        r = self.gds_compare(serialize(recs))
        self.assertFalse(r["match"])
        self.assertTrue(any("STRING=" in d for d in r["differences"]))

    def test_moved_label_fails(self):
        recs = records(self.base)
        span = first_element(recs, TOP, 0x0C)
        xy = record_in(recs, span, 0x10)
        y = struct.unpack(">i", xy[2][4:8])[0]
        xy[2][4:8] = struct.pack(">i", y + 1640)  # onto the next row
        self.assertFalse(self.gds_compare(serialize(recs))["match"])

    def test_moved_block_instance_fails(self):
        recs = records(self.base)
        span = first_element(recs, TOP, 0x0A)  # SREF of the mos block
        xy = record_in(recs, span, 0x10)
        xy[2][:4] = struct.pack(">i", struct.unpack(">i", xy[2][:4])[0] + 5)
        self.assertFalse(self.gds_compare(serialize(recs))["match"])

    def test_deleted_element_fails(self):
        recs = records(self.base)
        s, e = first_element(recs, TOP, 0x09)
        del recs[s:e + 1]
        r = self.gds_compare(serialize(recs))
        self.assertFalse(r["match"])
        self.assertTrue(any("only in committed" in d for d in r["differences"]))

    def test_duplicated_element_fails(self):
        recs = records(self.base)
        s, e = first_element(recs, TOP, 0x09)
        recs[e + 1:e + 1] = [list(r) for r in recs[s:e + 1]]
        self.assertFalse(self.gds_compare(serialize(recs))["match"])

    def test_element_reorder_matches(self):
        recs = records(self.base)
        spans = element_spans(recs, TOP)
        (s1, e1), (s2, e2) = spans[0], spans[1]
        self.assertEqual(e1 + 1, s2)
        recs[s1:e2 + 1] = recs[s2:e2 + 1] + recs[s1:e1 + 1]
        r = self.gds_compare(serialize(recs))
        self.assertTrue(r["match"], r["differences"])
        self.assertFalse(r["raw_identical"])

    def test_changed_units_fail(self):
        recs = records(self.base)
        for t, _d, p in recs:
            if t == 0x03:
                p[0] ^= 0x01
        self.assertFalse(self.gds_compare(serialize(recs))["match"])

    def test_garbage_fails_cleanly(self):
        r = self.gds_compare(b"\x00\x06\x00\x02\x02\x58" + b"\xff" * 10)
        self.assertFalse(r["match"])
        self.assertTrue(r["differences"][0].startswith("could not parse"))


# ------------------------------------------- comparison: reports and texts
class ReportComparison(Tmp):
    def setUp(self):
        super().setUp()
        self.a, self.b = self.dir / "a", self.dir / "b"
        self.a.mkdir()
        self.b.mkdir()
        self.report = json.loads((HERE / "gain_cell_2t_array.layout.json").read_text())

    def run_json(self, mutated) -> dict:
        (self.a / "r.json").write_text(json.dumps(self.report, indent=2))
        (self.b / "r.json").write_text(mutated if isinstance(mutated, str) else json.dumps(mutated, indent=2))
        return C.compare(self.a, self.b, [("r.json", "json")])["artifacts"][0]

    def test_reformatted_json_matches(self):
        r = self.run_json(json.dumps(self.report, sort_keys=True, separators=(",", ":")))
        self.assertTrue(r["match"])
        self.assertFalse(r["raw_identical"])

    def test_changed_pin_connection_fails(self):
        m = json.loads(json.dumps(self.report))
        m["nets"][0]["pins"][0]["port"] = "U1_G"  # pin moved to another device
        r = self.run_json(m)
        self.assertFalse(r["match"])
        self.assertTrue(any("$.nets[0].pins[0].port" in d for d in r["differences"]))

    def test_changed_route_length_fails(self):
        m = json.loads(json.dumps(self.report))
        m["nets"][1]["route_length_um"] += 0.01
        self.assertFalse(self.run_json(m)["match"])

    def test_unrouted_net_fails(self):
        m = json.loads(json.dumps(self.report))
        m["unrouted_nets"] = ["sn_0_0"]
        self.assertFalse(self.run_json(m)["match"])

    def test_text_artifact_change_fails(self):
        ref = (HERE / "gain_cell_2t_array.lvs_reference.spice").read_text()
        (self.a / "n.spice").write_text(ref)
        (self.b / "n.spice").write_text(ref.replace("rbl_0", "rbl_1", 1))
        r = C.compare(self.a, self.b, [("n.spice", "text")])["artifacts"][0]
        self.assertFalse(r["match"])

    def test_missing_regenerated_artifact_fails(self):
        (self.a / "x.gds").write_bytes(self.base)
        rep = C.compare(self.a, self.b, [("x.gds", "gds")])
        self.assertEqual(rep["result"], "mismatch")
        self.assertIn("missing file", rep["artifacts"][0]["differences"][0])

    def test_committed_baseline_against_itself(self):
        rep = C.compare(HERE, HERE, C.BASELINE_ARTIFACTS)
        self.assertEqual(rep["result"], "match")
        self.assertEqual(len(rep["artifacts"]), 7)

    def test_cli_exit_codes(self):
        (self.a / "x.gds").write_bytes(self.base)
        (self.b / "x.gds").write_bytes(self.base)
        args = ["--committed", str(self.a), "--regenerated", str(self.b), "--artifact", "x.gds:gds"]
        with io.StringIO() as buf:
            sys.stdout, old = buf, sys.stdout
            try:
                self.assertEqual(C.main(args), 0)
                (self.b / "x.gds").write_bytes(self.base[:-4] + b"\x00\x00\x00\x00")  # drop ENDLIB
                self.assertEqual(C.main(args), 1)
            finally:
                sys.stdout = old


# ----------------------------------------------------- toolchain guard
CFG = T.load_config()


def fake_toolchain(root: Path, *, commit: str, klayout: str, version: str, with_klt: bool = True) -> Path:
    """A fake interpreter that answers the identity probe, plus a fake klt."""
    bindir = root / "bin"
    bindir.mkdir(parents=True)
    klt = bindir / "klt"
    if with_klt:
        klt.write_text("#!/bin/sh\necho \"fake klt $*\" >&2\nexit 97\n")
        klt.chmod(klt.stat().st_mode | stat.S_IEXEC)
    ident = {
        "python_executable": str(bindir / "python"), "python_version": "3.x",
        "klayout_tools_version": version, "klayout_tools_commit": commit,
        "klayout_tools_url": "https://github.com/2AMLogic/klayout-tools",
        "klayout_version": klayout, "errors": [],
        "klt_path": str(klt) if with_klt else None,
    }
    py = bindir / "python"
    py.write_text("#!/bin/sh\ncat <<'EOF'\n" + json.dumps(ident) + "\nEOF\n")
    py.chmod(py.stat().st_mode | stat.S_IEXEC)
    return py


def pinned(role: str, **over) -> dict:
    rc = CFG["toolchains"][role]
    kw = {"commit": rc["klayout_tools"].get("commit"), "klayout": rc["klayout"],
          "version": rc["klayout_tools"]["package_version"]}
    kw.update(over)
    return kw


def fake_pdk(root: Path, commit: str) -> tuple[str, str]:
    d = root / "pdk" / "sky130A"
    d.mkdir(parents=True)
    (d / "SOURCES").write_text(f"open_pdks {commit}\nmagic deadbeef\n")
    return str(root / "pdk"), "sky130A"


class ToolchainGuard(Tmp):
    def test_config_pins(self):
        gen, chk = CFG["toolchains"]["generation"], CFG["toolchains"]["check"]
        # since #244 both roles are PyPI release pins (no git commit)
        self.assertNotIn("commit", gen["klayout_tools"])
        self.assertNotIn("commit", chk["klayout_tools"])
        for rc in (gen, chk):
            self.assertRegex(rc["klayout"], r"^\d+\.\d+\.\d+$")
            self.assertRegex(rc["klayout_tools"]["package_version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(gen["klayout_tools"]["package_version"], chk["klayout_tools"]["package_version"])

    def test_check_pin_matches_signoff_workflow(self):
        wf = (REPO / ".github" / "workflows" / "signoff.yml").read_text()
        ver = re.search(r"KLT_VERSION:\s*\"?(\d+\.\d+\.\d+)\"?\s*$", wf, re.M).group(1)
        self.assertEqual(CFG["toolchains"]["check"]["klayout_tools"]["package_version"], ver)
        self.assertIn("klayout-tools==${KLT_VERSION}", wf)

    def test_pdk_pin_matches_evidence_common(self):
        sys.path.insert(0, str(REPO / "sim"))
        import _evidence_common as E
        self.assertEqual(CFG["pdk"]["open_pdks_commit"], E.PDK_OPEN_PDKS_COMMIT)
        self.assertEqual(CFG["pdk"]["variant"], E.DEFAULT_PDK_VARIANT)
        self.assertIn(E.PDK_OPEN_PDKS_COMMIT, (REPO / "docs" / "pdk-pin.md").read_text())

    def test_both_scripts_use_the_shared_pin_not_path_klt(self):
        for name in ("generate_array.sh", "extract_array_parasitics.sh"):
            text = (HERE / name).read_text()
            self.assertTrue("generation_toolchain.py\" preflight --role generation --role check --pdk" in text,
                            f"{name} does not run the shared preflight")
            code = [ln for ln in text.splitlines() if not ln.lstrip().startswith(("#", "echo "))]
            for ln in code:
                self.assertNotRegex(ln, r"(^|[\s(])klt (gen|gen-compose|drc|lvs|erc)\b", f"{name}: bare klt: {ln}")
            self.assertNotIn("2dd24b09", text, f"{name} duplicates the pin literal")
            self.assertNotIn("klayout-tools==0.", text, f"{name} duplicates the pin literal")

    def test_matching_identity(self):
        py = fake_toolchain(self.dir / "g", **pinned("generation"))
        ident, err = T.probe(str(py))
        self.assertIsNone(err)
        self.assertEqual(T.identity_problems(CFG["toolchains"]["generation"], ident), [])

    def test_mismatched_commit_klayout_and_missing_klt(self):
        py = fake_toolchain(self.dir / "g", **pinned("generation", commit="0" * 40, klayout="0.30.10"),
                            with_klt=False)  # a git install where a release is pinned
        ident, _ = T.probe(str(py))
        problems = T.identity_problems(CFG["toolchains"]["generation"], ident)
        joined = "\n".join(problems)
        self.assertIn(f"klayout-tools is a git install ({'0' * 40})", joined)
        self.assertIn("klayout (KLayout Python module) version: expected 0.30.12, actual 0.30.10", joined)
        self.assertIn("no executable `klt`", joined)

    def test_old_generation_revision_is_rejected(self):
        # the pre-#244 generation pin (0.4.0 git revision) must no longer pass
        py = fake_toolchain(self.dir / "o", **pinned("generation", commit="2dd24b09e7569581297aabf9738594e9791210f1",
                                                     version="0.4.0"))
        ident, _ = T.probe(str(py))
        self.assertTrue(T.identity_problems(CFG["toolchains"]["generation"], ident))

    def test_check_release_pin_rejects_git_install_and_wrong_version(self):
        chk = CFG["toolchains"]["check"]
        ok = T.probe(str(fake_toolchain(self.dir / "ok", **pinned("check"))))[0]
        self.assertEqual(T.identity_problems(chk, ok), [])
        git = T.probe(str(fake_toolchain(self.dir / "git", **pinned("check", commit="2" * 40))))[0]
        self.assertTrue(any("git install" in p for p in T.identity_problems(chk, git)))
        old = T.probe(str(fake_toolchain(self.dir / "old", **pinned("check", version="0.6.0"))))[0]
        self.assertTrue(any("package version: expected" in p for p in T.identity_problems(chk, old)))
        self.assertEqual(T.requirement_specs(chk)[0], f"klayout-tools=={chk['klayout_tools']['package_version']}")

    def test_absent_interpreter(self):
        ident, err = T.probe(str(self.dir / "nope" / "bin" / "python"))
        self.assertIsNone(ident)
        self.assertIn("interpreter not found", err)

    def test_preflight_diagnostics(self):
        env = {"GCEDRAM_TOOLCHAIN_DIR": str(self.dir / "empty"),
               "GCEDRAM_KLT_CHECK_PYTHON": str(fake_toolchain(self.dir / "c", **pinned("check")))}
        out, err = io.StringIO(), io.StringIO()
        rc = T.preflight(["generation", "check"], False, CFG, env, out, err)
        self.assertEqual(rc, T.EXIT_TOOLCHAIN)
        self.assertEqual(out.getvalue(), "")  # nothing for the caller to eval
        e = err.getvalue()
        self.assertIn("generation toolchain unavailable or mismatched", e)
        self.assertIn("interpreter not found", e)
        self.assertIn("generation_toolchain.py install --role generation", e)
        gen_version = CFG["toolchains"]["generation"]["klayout_tools"]["package_version"]
        self.assertIn(f"klayout-tools=={gen_version}", e)
        self.assertNotIn("check toolchain", e)
        self.assertIn("No artifacts were written.", e)

    def test_preflight_success_prints_assignments(self):
        env = {"GCEDRAM_KLT_GENERATION_PYTHON": str(fake_toolchain(self.dir / "g", **pinned("generation"))),
               "GCEDRAM_KLT_CHECK_PYTHON": str(fake_toolchain(self.dir / "c", **pinned("check")))}
        pdk_root, pdk = fake_pdk(self.dir, CFG["pdk"]["open_pdks_commit"])
        env.update(PDK_ROOT=pdk_root, PDK=pdk)
        out, err = io.StringIO(), io.StringIO()
        self.assertEqual(T.preflight(["generation", "check"], True, CFG, env, out, err), 0, err.getvalue())
        self.assertIn(f"KLT_GENERATION={self.dir / 'g' / 'bin' / 'klt'}", out.getvalue())
        self.assertIn("KLT_CHECK=", out.getvalue())

    def test_pdk_mismatch(self):
        pdk_root, pdk = fake_pdk(self.dir, "f" * 40)
        problems = T.pdk_problems(CFG, T.pdk_identity(pdk_root, pdk))
        self.assertTrue(any("expected f6eeac7d" in p and "ciel enable" in p for p in problems))
        self.assertTrue(T.pdk_problems(CFG, T.pdk_identity(None, None)))
        self.assertTrue(T.pdk_problems(CFG, T.pdk_identity(str(self.dir / "none"), "sky130A")))


# --------------------------------------- scripts fail before writing
def tree_digest(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}


@unittest.skipUnless(shutil.which("bash"), "bash required")
class ScriptsFailBeforeWriting(Tmp):
    def run_script(self, script: str, args: list[str], env_over: dict[str, str]):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("GCEDRAM_", "KLT_", "PDK"))}
        env.update(env_over)
        before = tree_digest(HERE)
        proc = subprocess.run(["bash", str(HERE / script), *args], capture_output=True, text=True,
                              env=env, timeout=120)
        self.assertEqual(tree_digest(HERE), before, f"{script} modified layout/:\n{proc.stdout}\n{proc.stderr}")
        return proc

    def mismatched_env(self):
        pdk_root, pdk = fake_pdk(self.dir, CFG["pdk"]["open_pdks_commit"])
        return {
            "PDK_ROOT": pdk_root, "PDK": pdk, "KLT_EXTRACT": "true",
            "GCEDRAM_KLT_GENERATION_PYTHON": str(fake_toolchain(
                self.dir / "g", **pinned("generation", commit="1" * 40,
                                         version=CFG["toolchains"]["check"]["klayout_tools"]["package_version"]))),
            "GCEDRAM_KLT_CHECK_PYTHON": str(fake_toolchain(self.dir / "c", **pinned("check"))),
        }

    def test_mismatched_generation_toolchain(self):
        env = self.mismatched_env()  # generation slot holds the check revision
        for script, args in (("generate_array.sh", []), ("generate_array.sh", ["--check"]),
                             ("extract_array_parasitics.sh", [])):
            with self.subTest(script=script, args=args):
                p = self.run_script(script, args, env)
                self.assertEqual(p.returncode, 2, p.stderr)
                self.assertIn("klayout-tools is a git install", p.stderr)
                self.assertIn("No artifacts were written.", p.stderr)
                self.assertNotIn("== 1/", p.stdout)

    def test_absent_generation_toolchain(self):
        pdk_root, pdk = fake_pdk(self.dir, CFG["pdk"]["open_pdks_commit"])
        env = {"PDK_ROOT": pdk_root, "PDK": pdk, "KLT_EXTRACT": "true",
               "GCEDRAM_TOOLCHAIN_DIR": str(self.dir / "no-toolchains")}
        for script in ("generate_array.sh", "extract_array_parasitics.sh"):
            with self.subTest(script=script):
                p = self.run_script(script, [], env)
                self.assertEqual(p.returncode, 2, p.stderr)
                self.assertIn("interpreter not found", p.stderr)
                self.assertIn("install --role generation", p.stderr)
                self.assertIn("install --role check", p.stderr)

    def test_mismatched_pdk(self):
        pdk_root, pdk = fake_pdk(self.dir, "f" * 40)
        env = {"PDK_ROOT": pdk_root, "PDK": pdk, "KLT_EXTRACT": "true",
               "GCEDRAM_KLT_GENERATION_PYTHON": str(fake_toolchain(self.dir / "g", **pinned("generation"))),
               "GCEDRAM_KLT_CHECK_PYTHON": str(fake_toolchain(self.dir / "c", **pinned("check")))}
        p = self.run_script("generate_array.sh", ["--check"], env)
        self.assertEqual(p.returncode, 2, p.stderr)
        self.assertIn("open_pdks commit", p.stderr)

    def test_missing_pdk_env(self):
        p = self.run_script("generate_array.sh", [], {})
        self.assertEqual(p.returncode, 1)
        self.assertIn("PDK_ROOT/PDK not set", p.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=1)
