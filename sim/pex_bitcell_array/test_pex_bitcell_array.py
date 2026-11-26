#!/usr/bin/env python3
"""Offline checks for the pex_bitcell_array study (issue #383).

No klt, no ngspice, no network (same contract as the other sim/*/test_*.py
suites evidence-checks.yml runs): these hold the two schematic-leg
reference netlists fresh against their named sources, pin the bench
geometry the measure-command harness builds, and exercise the crossing
reduction on synthetic corner data. Stdlib only.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import mock

STUDY_DIR = Path(__file__).resolve().parent
SIM_DIR = STUDY_DIR.parent
REPO_ROOT = SIM_DIR.parent

sys.path.insert(0, str(SIM_DIR))
sys.path.insert(0, str(SIM_DIR / "bitcell-transient"))
sys.path.insert(0, str(SIM_DIR / "retention"))
sys.path.insert(0, str(STUDY_DIR))

import gen_bitcell_transient as G  # noqa: E402
import gen_reference_netlists as GEN  # noqa: E402
import measure_pex_retention as M  # noqa: E402
import pex_bench  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"ok   {name}")
    else:
        FAILURES.append(f"{name}: {detail}")
        print(f"FAIL {name}: {detail}")


def test_references_fresh() -> None:
    for path, text in GEN.render_all().items():
        check(
            f"reference fresh: {Path(path).name}",
            Path(path).read_text() == text,
            "committed file differs from a regeneration; run "
            "python3 -I sim/pex_bitcell_array/gen_reference_netlists.py",
        )


def test_bitcell_reference() -> None:
    cell = pex_bench.CELLS["bitcell"]
    text = cell["reference"].read_text()
    check("bitcell reference passes DUT checks", not pex_bench.dut_problems(text, cell),
          str(pex_bench.dut_problems(text, cell)))
    cards = [ln for ln in text.splitlines() if ln.startswith("XM_")]
    check("bitcell reference carries the two source X cards verbatim",
          cards == [ln.rstrip() for ln in (REPO_ROOT / "design" / "gain_cell_2t.spice")
                    .read_text().splitlines() if ln.startswith("XM_")],
          f"{cards!r}")
    check("bitcell reference omits the source terminator",
          ".end" not in [ln.strip().lower() for ln in text.splitlines()])


def test_array_reference() -> None:
    cell = pex_bench.CELLS["array"]
    text = cell["reference"].read_text()
    problems = pex_bench.dut_problems(text, cell)
    check("array reference passes DUT checks", not problems, str(problems))
    x_cards = [ln for ln in text.splitlines() if ln.startswith("X_")]
    check("array reference instantiates 32 SKY130 X cards",
          len(x_cards) == 32 and all(pex_bench.NFET_MODEL in c for c in x_cards),
          f"{len(x_cards)} cards")
    check("array cards use bare-micrometre L/W (SKY130 convention)",
          all(" L=0.15 W=0.42 " in c for c in x_cards))
    check("array cards keep the source schematic geometry",
          all("ad=0.1218" in c and "pd=1.42" in c and "sa=0 sb=0 sd=0" in c for c in x_cards))
    lvs_tuples = sorted(
        tuple(ln.split()[1:5])
        for ln in (REPO_ROOT / "layout" / "gain_cell_2t_array.lvs_reference.spice")
        .read_text().splitlines()
        if ln.startswith("M_")
    )
    ref_tuples = sorted(tuple(c.split()[1:5]) for c in x_cards)
    check("array D/G/S/B tuples match the LVS reference exactly",
          lvs_tuples == ref_tuples, "tuple sets differ")


def test_committed_extracts() -> None:
    """The committed extractions document connectivity only (unbound M nfet
    cards); their headers are the ordered-pin contract both legs assert
    against, and their bodies ground through the tap/tie resistors."""
    for name in ("bitcell", "array"):
        cell = pex_bench.CELLS[name]
        text = cell["committed_extract"].read_text()
        hdr = pex_bench.subckt_header(text)
        check(f"committed {name} extract header is the expected ordered interface",
              hdr == (cell["top"], cell["pins"]), str(hdr))
        problems = pex_bench.dut_problems(text, cell)
        only_unbound = [p for p in problems if "instance count" in p]
        check(f"committed {name} extract: header + grounded bodies, unbound devices only",
              problems == only_unbound and len(only_unbound) == 1, str(problems))
        m_nfet = [c for c in pex_bench.device_cards(text)
                  if c[0] == "M" and c[3].lower() == "nfet"]
        check(f"committed {name} extract holds {'2' if name == 'bitcell' else '32'} unbound nfet cards",
              len(m_nfet) == cell["nfet_count"], f"{len(m_nfet)}")


def test_hold_measurements_for() -> None:
    for name, node in (("bitcell", "sn"), ("array", "sn_0_0")):
        cell = pex_bench.CELLS[name]
        ms = pex_bench.hold_measurements_for(cell, 1e-3)
        base = G.hold_measurements(1, 1e-3)
        check(f"{name} measurement set size matches the study's",
              len(ms) == len(base), f"{len(ms)} != {len(base)}")
        check(f"{name} every card re-pointed at v({node})",
              all(f"v({node})" in m["spice"] and "v(sn)" not in m["spice"].replace(f"v({node})", "")
                  for m in ms))
        check(f"{name} cards differ from the study's only in the node name",
              all(a["spice"].replace(f"v({node})", "v(sn)") == b["spice"]
                  for a, b in zip(ms, base)))


def test_bench_shape() -> None:
    cell = pex_bench.CELLS["bitcell"]
    dut = cell["reference"].read_text()
    a = pex_bench.build_bench(dut, cell, "schematic", "ref.spice", "0" * 64)
    b = pex_bench.build_bench(dut, cell, "extracted", "ext.spice", "1" * 64)
    tail_a = a[a.index("Xdut"):]
    tail_b = b[b.index("Xdut"):]
    check("both legs' stimulus identical from the X instantiation on",
          tail_a == tail_b)
    check("GND formal bound to SPICE node 0",
          "Xdut 0 bl rbl rwl sn wl gain_cell_2t_layout_0" in a)
    check("substrate anchor present on both legs", "Vvsubs vsubs 0 DC 0" in a)
    check("no lumped c_sn card on either leg",
          not any(ln.lower().startswith("c_sn") for ln in (a + "\n" + b).splitlines()))
    check("DUT inlined verbatim", dut.rstrip("\n") in a)
    p = G.params()
    check("phase timing parsed from the committed template",
          f".param THOLD_START = {p['THOLD_START']:.6e}" in a
          and f".param VDD    = {p['VDD']:g}" in a)
    arr_cell = pex_bench.CELLS["array"]
    arr = pex_bench.build_bench(arr_cell["reference"].read_text(), arr_cell,
                                "schematic", "ref.spice", "0" * 64)
    check("array X instantiation uses the ordered 33-pin interface",
          f"Xdut 0 {' '.join(arr_cell['pins'][1:])} {arr_cell['top']}" in arr)
    check("array bench biases unselected rows/columns",
          "vwl_1 wl_1 0 dc 0" in arr and "vrwl_1 rwl_1 0 dc {VDD}" in arr
          and "vrbl_3 rbl_3 0 dc {VRBL}" in arr)
    check("array bench initialises every storage node", arr.count(".ic v(sn_") == 16)


def test_reduce_t_ret() -> None:
    def ladder_ms(crossed: dict[float, float]) -> dict:
        m = {G.ladder_name(mv): crossed.get(mv / 1000) for mv in G.LADDER_MV}
        m["v_sn_hold_start_v"] = 1.2
        return m

    # threshold 0.3 V inside the crossed rungs -> value, pass/fail vs the
    # ratified benchmark
    crossed = {lv: 1.0 - 2.0 * lv for lv in (0.25, 0.275, 0.3, 0.325, 0.35)}
    row = pex_bench.reduce_t_ret(ladder_ms(crossed), 5e-3)
    check("resolved crossing yields a value", row["value"] is not None, str(row))
    check("resolved long retention passes the ratified benchmark",
          row["status"] == "pass", row["status"])
    fast = {lv: 1.0 - 2.0 * lv for lv in (0.25, 0.275, 0.3, 0.325, 0.35)}
    fast = {lv: 9.0e-6 * (1.0 - lv) for lv in fast}
    row = pex_bench.reduce_t_ret(ladder_ms(fast), 5e-3)
    check("measured retention below the benchmark is a numerical failure",
          row["status"] == "fail" and row["value"] < pex_bench.T_RET_MIN_S, str(row))
    # written level below delta_v -> unreachable threshold, null + cause
    m = ladder_ms({})
    m["v_sn_hold_start_v"] = 0.87
    row = pex_bench.reduce_t_ret(m, 5e-3)
    check("unreachable threshold is null with cause and window",
          row["value"] is None and row["status"] == "error"
          and "floor" in row["message"] and "5.000000e-03" in row["message"], str(row))
    # reachable threshold but no crossed rungs -> null with cause and window
    m = ladder_ms({})
    row = pex_bench.reduce_t_ret(m, 4e-4)
    check("uncrossed ladder is null with cause and window",
          row["value"] is None and row["status"] == "error"
          and "ladder" in row["message"] and "4.000000e-04" in row["message"], str(row))


def test_param_block_tracks_vdd() -> None:
    """Issue #441: the bench's `.param VBL_DATA` / `VRBL` must be derived
    from the template's VDD through gen_bitcell_transient.param_block (the
    shared single definition), not hardcoded -- an overridden or updated
    VDD must propagate into the rendered bench."""
    cell = pex_bench.CELLS["bitcell"]
    dut = cell["reference"].read_text()
    base = G.params()
    for vdd in (1.8, 1.2):
        with mock.patch.object(G, "params", return_value=dict(base, VDD=vdd)):
            bench = pex_bench.build_bench(dut, cell, "schematic", "ref.spice", "0" * 64)
        stale = ".param VBL_DATA = 1.8" in bench and vdd != 1.8
        check(f"VBL_DATA/VRBL track the template VDD ({vdd:g})",
              f".param VBL_DATA = {vdd:g}" in bench
              and f".param VRBL   = {vdd / 2.0:g}" in bench
              and not stale,
              "bench does not derive VBL_DATA/VRBL from VDD")


def test_check_pdk_root_fails_closed() -> None:
    """Issue #441: check_pdk_root goes through _evidence_common's
    pdk_revision_problems, so an unidentifiable tree (missing SOURCES) or
    one at another revision fails closed; only the pinned revision
    passes."""
    other = "c6d73a35f524070e85faff4a6a9eef49553ebc2b"
    cases = [
        ("missing SOURCES", None),
        ("mismatched SOURCES", f"open_pdks {other}\n"),
        ("pinned revision", f"open_pdks {G.PIN}\n"),
    ]
    for label, body in cases:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            variant = root / "sky130A"
            variant.mkdir()
            if body is not None:
                (variant / "SOURCES").write_text(body)
            with mock.patch.object(M, "resolve_pdk_root", return_value=root):
                try:
                    result: object = M.check_pdk_root()
                except SystemExit as e:
                    result = e
            if body == f"open_pdks {G.PIN}\n":
                check(f"check_pdk_root passes on the {label}",
                      result == root, str(result))
            else:
                check(f"check_pdk_root fails closed on {label}",
                      isinstance(result, SystemExit) and "sky130A" in str(result),
                      str(result))


def main() -> int:
    test_references_fresh()
    test_bitcell_reference()
    test_array_reference()
    test_committed_extracts()
    test_hold_measurements_for()
    test_bench_shape()
    test_param_block_tracks_vdd()
    test_check_pdk_root_fails_closed()
    test_reduce_t_ret()
    if FAILURES:
        print(f"\n{len(FAILURES)} failure(s)")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
