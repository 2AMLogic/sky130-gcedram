#!/usr/bin/env python3
"""Tests for check_closure_identity.py (issue #338). Run:
    python3 -I sim/pdk-closure-identity/test_check_closure_identity.py

All cases run over small synthetic PDK trees in temporary directories --
no PDK install, no SPICE, no network.  They encode the acceptance criteria
from issue #338:

* (a) a monolith split into per-device includes with identical content
  passes;
* (b) an additive `.param` block consumed only by a non-instantiated model
  passes;
* (c) the same `.model` name redefined in several files, in different
  order, does not read as a delta;
* (d) a changed parameter *inside* an instantiated model fails non-zero;
* (e) a corner-section-gated `.lib` include is in the closure for the
  requested section only;
* (Champion note) a `.param` defined outside any instantiated block but
  *consumed by* an instantiated model (directly, and transitively through
  another parameter) fails non-zero;
* edge cases: missing entry point, corner section absent from one tree, and
  a deck referencing a model absent from the closure are errors (exit 2),
  never a silent pass.
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # `python3 -I` drops the script dir from sys.path
import check_closure_identity as C  # noqa: E402


def write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def entry_with(includes_by_section: dict[str, list[str]]) -> str:
    parts = ["* synthetic entry"]
    for section, incs in includes_by_section.items():
        parts.append(f".lib {section}")
        parts.append(".param entry_knob = 1")
        for inc in incs:
            parts.append(f'.include "{inc}"')
        parts.append(f".endl {section}")
    return "\n".join(parts) + "\n"


NFET_REF_BLOCK = (
    ".model sky130_fd_pr__nfet_01v8 nswilt level=103 version=4.8.sf_penalty\n"
    "+ vth0 = {vth0_nfet} u0 = {u0_nfet} nfactor = 1.5"
)


def nfet_val_block(vth0: str, u0: str) -> str:
    """The same card with numeric parameter values embedded directly."""
    return (
        ".model sky130_fd_pr__nfet_01v8 nswilt level=103 "
        "version=4.8.sf_penalty\n"
        f"+ vth0 = {vth0} u0 = {u0} nfactor = 1.5")

DECK = (
    "* synthetic deck\n"
    "XM1 n1 n2 n3 GND sky130_fd_pr__nfet_01v8 L=0.15 W=0.42\n"
    "R1 n1 n2 1k\n"
    "C1 n2 0 1f\n"
    ".param VRBL = 0.9\n"
    ".tran 1p 1n\n"
    ".end\n"
)


class SyntheticTree:
    """Builder for a one-request synthetic comparison fixture."""

    def __init__(self, sections=("tt", "ss")):
        self.dir = Path(tempfile.mkdtemp(prefix="pkl-"))
        self.sections = list(sections)
        (self.dir / "req").mkdir()
        self.request = self.dir / "req" / "request.json"
        self.a = self.dir / "pdkA"
        self.b = self.dir / "pdkB"

    def make_request(self, netlist="deck.spice", pdk="sky130A",
                     lib="libs.tech/combined/sky130.lib.spice",
                     process=("tt",)) -> None:
        write(self.dir, "req/deck.spice", self.deck)
        self.request.write_text(json.dumps({
            "netlist": netlist,
            "models": {"pdk": pdk, "lib": lib},
            "corners": {"process": list(process), "temperature_c": [27]},
        }))

    deck: str = DECK

    def build_roots(self, files_a: dict[str, str], files_b: dict[str, str],
                    entry_a: str | None = None, entry_b: str | None = None):
        default_entry = entry_with({s: ["models.spice", "params.spice"]
                                    for s in self.sections})
        if entry_a is None:
            entry_a = default_entry
        if entry_b is None:
            entry_b = default_entry
        base_a = dict(files_a)
        base_a["libs.tech/combined/sky130.lib.spice"] = entry_a
        base_b = dict(files_b)
        base_b["libs.tech/combined/sky130.lib.spice"] = entry_b
        for root, files in ((self.a, base_a), (self.b, base_b)):
            pdk_dir = root / "sky130A"
            for rel, text in files.items():
                write(pdk_dir, rel, text)
            write(pdk_dir, "SOURCES",
                  "open_pdks 0123456789abcdef0123456789abcdef01234567\n")

    def run(self, extra=()):
        import contextlib
        import io
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = C.run([
                    "--root-a", str(self.a), "--root-b", str(self.b),
                    "--request", str(self.request), "--klt-version", "klt-test",
                    *extra,
                ])
            except C.CheckError as e:
                print(f"error: {e}", file=sys.stderr)
                rc = 2
        self.last_output = out.getvalue() + err.getvalue()
        return rc

    def cleanup(self):
        shutil.rmtree(self.dir)


class Base(unittest.TestCase):
    def setUp(self):
        self.fx = SyntheticTree()

    def tearDown(self):
        self.fx.cleanup()


class MonolithSplitPasses(Base):
    """(a) identical content reorganized monolith -> per-device includes."""

    def test_pass(self):
        self.fx.make_request(process=("tt",))
        self.fx.build_roots(
            files_a={
                "libs.tech/combined/models.spice": (
                    f"{NFET_REF_BLOCK}\n"
                    ".model sky130_fd_pr__pfet_01v8 pswilt level=103\n"
                    "+ vth0 = {vth0_pfet}\n"
                ),
                "libs.tech/combined/params.spice":
                    ".param vth0_nfet = 0.4 u0_nfet = 350 vth0_pfet = -0.5\n",
            },
            files_b={
                "libs.tech/combined/models.spice": (
                    '.include "devices/nfet.spice"\n'
                    '.include "devices/pfet.spice"\n'
                ),
                "libs.tech/combined/devices/nfet.spice":
                    f"{NFET_REF_BLOCK}\n",
                "libs.tech/combined/devices/pfet.spice":
                    ".model sky130_fd_pr__pfet_01v8 pswilt level=103\n"
                    "+ vth0 = {vth0_pfet}\n",
                "libs.tech/combined/params.spice":
                    ".param vth0_nfet = 0.4 u0_nfet = 350 vth0_pfet = -0.5\n",
            })
        rc = self.fx.run()
        self.assertEqual(rc, 0)


class AdditiveOutsideParamPasses(Base):
    """(b) additive `.param` consumed only by a non-instantiated model."""

    def test_pass(self):
        self.fx.make_request(process=("tt",))
        common = {
            "libs.tech/combined/models.spice":
                f"{NFET_REF_BLOCK}\n"
                ".model sky130_fd_pr__cap_id c cap=\"#perimeter\"\n"
                "+ cj = {cj_plate}\n",
            "libs.tech/combined/params.spice":
                ".param vth0_nfet = 0.4 u0_nfet = 350\n",
        }
        files_a = dict(common)
        files_a["libs.tech/combined/params.spice"] += ""
        files_b = dict(common)
        files_b["libs.tech/combined/params.spice"] += (
            ".param\n+ cj_plate = 1.2e-3 ; Units: farad/meter^2\n"
            "+ cj_plate_sw = 8.6e-11\n")
        self.fx.build_roots(files_a, files_b)
        rc = self.fx.run()
        self.assertEqual(rc, 0)


class SameNameRedefinitionNoFalseDelta(Base):
    """(c) one `.model` name redefined in several files, different order."""

    def test_pass(self):
        self.fx.make_request(process=("tt",))
        dev1 = (f"{NFET_REF_BLOCK}\n"
                ".model sky130_fd_pr__nfet_20v0_base.0 nfet level=54\n"
                "+ tox = 1e-8 version = 1.0\n")
        dev2 = (".model sky130_fd_pr__nfet_20v0_base.0 nfet level=54\n"
                "+ tox = 2e-8 version = 1.0\n")
        dev3 = (".model sky130_fd_pr__nfet_20v0_base.0 nfet level=54\n"
                "+ tox = 3e-8 version = 1.0\n")
        self.fx.build_roots(
            files_a={
                "libs.tech/combined/models.spice": dev1 + dev2 + dev3,
                "libs.tech/combined/params.spice":
                    ".param vth0_nfet = 0.4 u0_nfet = 350\n",
            },
            files_b={
                "libs.tech/combined/models.spice": (
                    '.include "devices/b.spice"\n.include "devices/c.spice"\n'
                    '.include "devices/a.spice"\n'),
                "libs.tech/combined/devices/a.spice": dev1,
                "libs.tech/combined/devices/b.spice": dev2,
                "libs.tech/combined/devices/c.spice": dev3,
                "libs.tech/combined/params.spice":
                    ".param vth0_nfet = 0.4 u0_nfet = 350\n",
            })
        rc = self.fx.run(extra=["--out", str(self.fx.dir / "record.json")])
        self.assertEqual(rc, 0)
        # The exit code alone cannot see an *outside* delta: assert the
        # redefined name produced no block delta at all, in every section.
        record = json.loads((self.fx.dir / "record.json").read_text())
        for section, r in record["sections"].items():
            self.assertEqual(
                r["block_multiset_differing_names"], [],
                f"section {section}: same-named redefinitions leaked as "
                "block deltas")


class InSetModelDeltaFails(Base):
    """(d) a changed parameter inside the instantiated model fails."""

    def test_fail(self):
        self.fx.make_request(process=("tt",))
        self.fx.build_roots(
            files_a={
                "libs.tech/combined/models.spice":
                    f"{nfet_val_block('0.4', '350')}\n",
                "libs.tech/combined/params.spice":
                    ".param vth0_nfet = 0.4 u0_nfet = 350\n",
            },
            files_b={
                "libs.tech/combined/models.spice":
                    f"{nfet_val_block('0.45', '350')}\n",
                "libs.tech/combined/params.spice":
                    ".param vth0_nfet = 0.45 u0_nfet = 350\n",
            })
        rc = self.fx.run()
        self.assertEqual(rc, 1)


class InSetParamFailsDirectAndTransitive(Base):
    """Champion note: a `.param` consumed by an instantiated model (directly
    or through another parameter) must classify inside and fail, even though
    the parameter is defined in a file holding no instantiated block."""

    def _run_case(self, param_b: str, expected_rc: int):
        self.fx.make_request(process=("tt",))
        self.fx.build_roots(
            files_a={
                "libs.tech/combined/models.spice":
                    f"{NFET_REF_BLOCK}\n",
                "libs.tech/combined/params.spice":
                    ".param vth0_nfet = 0.4 u0_nfet = 350\n",
                "libs.tech/combined/no_models_here.spice":
                    ".param vth_shift = 0.0\n.param u0_scale = 1.0\n",
                "libs.tech/combined/entry_extra.spice": "* placeholder\n",
            },
            files_b={
                "libs.tech/combined/models.spice":
                    f"{NFET_REF_BLOCK}\n",
                "libs.tech/combined/params.spice":
                    ".param vth0_nfet = 0.4 u0_nfet = 350\n",
                "libs.tech/combined/no_models_here.spice": param_b,
                "libs.tech/combined/entry_extra.spice": "* placeholder\n",
            },
            entry_a=entry_with({"tt": ["models.spice", "params.spice",
                                       "no_models_here.spice",
                                       "entry_extra.spice"]}),
            entry_b=entry_with({"tt": ["models.spice", "params.spice",
                                       "no_models_here.spice",
                                       "entry_extra.spice"]}))
        rc = self.fx.run()
        self.assertEqual(rc, expected_rc)

    def test_directly_consumed_param_fails(self):
        # the block references u0_nfet directly; changing its definition
        # outside the instantiated block's file must fail
        self._run_case(
            ".param vth_shift = 0.0\n.param u0_scale = 1.0\n"
            ".param u0_nfet = 300\n", 1)

    def test_transitively_consumed_param_fails(self):
        # vth0_eff = 0.4 + vth_shift; vth_shift feeds vth0_eff feeds the
        # instantiated block, so changing vth_shift alone must fail -- even
        # though the parameter lives in a file holding no instantiated block
        self.fx.make_request(process=("tt",))
        block = (".model sky130_fd_pr__nfet_01v8 nswilt level=103 "
                 "version=4.8.sf_penalty\n"
                 "+ vth0 = {vth0_eff} u0 = {u0_nfet} nfactor = 1.5")
        entry = entry_with({"tt": ["models.spice", "params.spice",
                                   "no_models_here.spice"]})
        self.fx.build_roots(
            files_a={
                "libs.tech/combined/models.spice": f"{block}\n",
                "libs.tech/combined/params.spice":
                    ".param vth0_eff = '0.4 + vth_shift' u0_nfet = 350\n",
                "libs.tech/combined/no_models_here.spice":
                    ".param vth_shift = 0.0\n",
            },
            files_b={
                "libs.tech/combined/models.spice": f"{block}\n",
                "libs.tech/combined/params.spice":
                    ".param vth0_eff = '0.4 + vth_shift' u0_nfet = 350\n",
                "libs.tech/combined/no_models_here.spice":
                    ".param vth_shift = 0.05\n",
            },
            entry_a=entry, entry_b=entry)
        rc = self.fx.run()
        self.assertEqual(rc, 1)

    def test_unconsumed_param_passes(self):
        # same file, same delta shape, but the parameter feeds nothing the
        # deck instantiates -> outside -> pass
        self._run_case(
            ".param vth_shift = 0.05\n.param u0_scale = 1.0\n", 0)


class SectionGatedIncludes(Base):
    """(e) section-gated includes: closure per requested section only."""

    def test_closure_contains_only_requested_section(self):
        self.fx.make_request(process=("tt",))
        self.fx.build_roots(
            files_a={
                "libs.tech/combined/models.spice":
                    f"{NFET_REF_BLOCK}\n",
                "libs.tech/combined/params.spice":
                    ".param vth0_nfet = 0.4 u0_nfet = 350\n",
                "libs.tech/combined/params_ss.spice":
                    ".param vth0_nfet = 0.5 u0_nfet = 330\n",
            },
            files_b={},
            entry_a=entry_with({"tt": ["models.spice", "params.spice"],
                                "ss": ["models.spice", "params_ss.spice"]}),
            entry_b=entry_with({"tt": ["models.spice", "params.spice"],
                                "ss": ["models.spice", "params_ss.spice"]}),
        )
        # copy tree A to tree B (identical) for a passing comparison
        shutil.copytree(self.fx.a, self.fx.b, dirs_exist_ok=True)
        closure = C.Closure(self.fx.a / "sky130A",
                            "libs.tech/combined/sky130.lib.spice", "tt")
        self.assertIn("libs.tech/combined/params.spice", closure.files)
        self.assertNotIn("libs.tech/combined/params_ss.spice", closure.files)
        closure_ss = C.Closure(self.fx.a / "sky130A",
                               "libs.tech/combined/sky130.lib.spice", "ss")
        self.assertIn("libs.tech/combined/params_ss.spice", closure_ss.files)
        rc = self.fx.run()
        self.assertEqual(rc, 0)


class ErrorCases(Base):
    """Edge cases must be clear errors (exit 2), never a silent pass."""

    def test_missing_entry_point(self):
        self.fx.make_request(lib="libs.tech/combined/nope.lib.spice")
        self.fx.build_roots({}, {})
        rc = self.fx.run()
        self.assertEqual(rc, 2)

    def test_section_absent_from_one_tree(self):
        self.fx.make_request(process=("ff",))
        self.fx.build_roots(
            files_a={
                "libs.tech/combined/models.spice":
                    f"{NFET_REF_BLOCK}\n",
                "libs.tech/combined/params.spice":
                    ".param vth0_nfet = 0.4 u0_nfet = 350\n",
            },
            files_b={
                "libs.tech/combined/models.spice":
                    f"{NFET_REF_BLOCK}\n",
                "libs.tech/combined/params.spice":
                    ".param vth0_nfet = 0.4 u0_nfet = 350\n",
            },
            entry_a=entry_with({"tt": ["models.spice", "params.spice"],
                                "ff": ["models.spice", "params.spice"]}),
            entry_b=entry_with({"tt": ["models.spice", "params.spice"]}))
        rc = self.fx.run()
        self.assertEqual(rc, 2)

    def test_deck_model_absent_from_closure(self):
        self.fx.deck = (
            "* deck referencing a model neither tree defines\n"
            "XM1 n1 n2 n3 GND sky130_fd_pr__nfet_05v0_nvt L=0.5 W=1\n"
            ".end\n")
        self.fx.make_request(process=("tt",))
        self.fx.build_roots(
            files_a={
                "libs.tech/combined/models.spice":
                    f"{NFET_REF_BLOCK}\n",
                "libs.tech/combined/params.spice":
                    ".param vth0_nfet = 0.4 u0_nfet = 350\n",
            },
            files_b={})
        shutil.copytree(self.fx.a, self.fx.b, dirs_exist_ok=True)
        rc = self.fx.run()
        self.assertEqual(rc, 2)


class UnclassifiedContentDeltaFails(Base):
    """A differing content line attributable to neither block nor param
    fails the check (conservative direction)."""

    def test_fail(self):
        self.fx.make_request(process=("tt",))
        self.fx.build_roots(
            files_a={
                "libs.tech/combined/models.spice":
                    f"{NFET_REF_BLOCK}\n",
                "libs.tech/combined/params.spice":
                    ".param vth0_nfet = 0.4 u0_nfet = 350\n"
                    ".options bad_option = 1\n",
            },
            files_b={
                "libs.tech/combined/models.spice":
                    f"{NFET_REF_BLOCK}\n",
                "libs.tech/combined/params.spice":
                    ".param vth0_nfet = 0.4 u0_nfet = 350\n"
                    ".options bad_option = 2\n",
            })
        rc = self.fx.run()
        self.assertEqual(rc, 1)


class SplitAssignments(unittest.TestCase):
    """The `.param` card parser: spacing variants and name boundaries."""

    def test_space_and_tight_forms(self):
        pairs = C.split_assignments("tol_pfom=0 tol_nw = 0.0, tol_li=0.0")
        self.assertEqual(pairs, [("tol_pfom", "0"),
                                 ("tol_nw", "0.0"),
                                 ("tol_li", "0.0")])

    def test_quoted_expression(self):
        pairs = C.split_assignments("k2_diff = '-1.2 + 0.03 * sw_a' next=2")
        self.assertEqual(pairs[0], ("k2_diff", "'-1.2 + 0.03 * sw_a'"))
        self.assertEqual(pairs[1], ("next", "2"))

    def test_no_false_name_inside_identifier(self):
        pairs = C.split_assignments("rcon = 4.5")
        self.assertEqual(pairs, [("rcon", "4.5")])


class DeckModelCandidates(unittest.TestCase):
    def test_x_card_with_params(self):
        cands = C.deck_model_candidates(
            "XM_WR a b c GND sky130_fd_pr__nfet_01v8 L=0.15 W=0.42 m=1")
        self.assertEqual([c for c, _ in cands],
                         ["sky130_fd_pr__nfet_01v8"])

    def test_m_card_positional(self):
        cands = C.deck_model_candidates("M1 d g s b my_nfet")
        self.assertEqual([c for c, _ in cands], ["my_nfet"])

    def test_ignored_lines(self):
        self.assertEqual(
            C.deck_model_candidates(".meas tran v(x) FIND v(n1) AT=1e-7\n"
                                    "* XM commented out\n"
                                    "R1 a b 1k\n"), [])


if __name__ == "__main__":
    unittest.main()
