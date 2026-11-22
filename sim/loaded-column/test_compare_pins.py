#!/usr/bin/env python3
"""Tests for compare_pins.py --compare-equiv (issue #400).

Run: python3 -I sim/loaded-column/test_compare_pins.py

No ngspice, no klt, no network. The exact-match case feeds compare_equiv a
synthetic single-corner report and, as the runner side, the very rows the
same reduce_column_results.rows_for_corner derivation produces from that
report -- every numeric pair then agrees exactly, which is the case whose
zero-deviation summary used to crash (TypeError formatting the
never-populated overall-worst record) before a passing result could be
printed. The committed tt/27 C equivalence pair is re-compared when its two
artifacts are present, an above-bound perturbation must still exit 1, and
an empty set of measurements must report the comparison-unavailable exit
status 2.
"""
import contextlib
import csv
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import compare_pins as C  # noqa: E402
import gen_column_requests as G  # noqa: E402
import reduce_column_results as D  # noqa: E402
import run_loaded_column as R  # noqa: E402

EQUIV = HERE / "results" / "equivalence"
COMMITTED_REPORT = (EQUIV / "klt_report_local_tt27_f6eeac7_ngspice47"
                    "_20261115T101029Z.json.gz")
COMMITTED_CSV = EQUIV / "run_loaded_column_tt27_fresh_sel0.csv"

PROV = {
    "timestamp_utc": "test", "repo_git_sha": "test", "job_id": "klt-sim-test",
    "runner_klt_version": "0.9.0", "pdk_stamp_text": "open_pdks test",
    "ngspice_version": "ngspice-47",
}


def fake_report(values: dict) -> dict:
    return {
        "netlist": {"path": "sim/loaded-column/klt/lc_fresh_sel0.spice"},
        "environment": {"engine_version": "47"},
        "corners": [{
            "corner_id": "tt/novdd/27C", "process": "tt", "temperature_c": 27,
            "status": "pass", "diagnostics": [],
            "measurements": [{"name": k, "value": v} for k, v in values.items()],
        }],
    }


def report_values() -> dict:
    """Measurements for all 16 patterns, enough for rows_for_corner to emit
    16 ok rows: every field valued, latency crossed on every pattern."""
    P = G.params(dict(G.BASELINE_KNOBS))
    T = G.instants(P, dict(G.BASELINE_KNOBS), "fresh")
    v = {}
    for pattern in G.PATTERNS:
        g = G.tag(pattern)
        for r in range(R.N_ROWS):
            v[f"{g}__v_sn_r{r}_wl_off_v"] = 0.1 * (r + 1)
            v[f"{g}__v_sn_r{r}_after_write_v"] = 0.2 * (r + 1)
            v[f"{g}__v_sn_r{r}_preread_v"] = 0.3 * (r + 1)
            v[f"{g}__v_sn_r{r}_end_v"] = 0.3 * (r + 1) + 0.01 * (r + 1)
            v[f"{g}__i_into_rbl_r{r}_preread_a"] = 1e-12 * (r + 1)
            v[f"{g}__i_into_rbl_r{r}_sense_a"] = 2e-12 * (r + 1)
        v[f"{g}__v_rbl_preread_float_v"] = 0.9
        v[f"{g}__v_rbl_sense_v"] = 0.4
        v[f"{g}__v_rbl_end_v"] = 0.3
        v[f"{g}__t_latency_abs_s"] = T["t_read"] + 7.5e-10
    return v


def write_rows(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=R.FIELDS)
        w.writeheader()
        w.writerows(rows)


def run_equiv(report_path, csv_path):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = C.compare_equiv(report_path, csv_path)
    return rc, out.getvalue(), err.getvalue()


@contextlib.contextmanager
def equiv_pair(mutate=None):
    """(report path, runner-csv path) over a temp dir: a synthetic report and
    the runner CSV written from its own rows_for_corner reduction, optionally
    perturbed by `mutate(rows)`."""
    report = fake_report(report_values())
    age, sel = D.job_of(report)
    rows = D.rows_for_corner(report["corners"][0], age=age, sel=sel,
                             knobs=dict(G.BASELINE_KNOBS), c_sn_f=G.c_sn_farads(),
                             prov=dict(PROV), run_id="equiv",
                             deck="lc_fresh_sel0.spice")
    assert all(r["status"] == "ok" for r in rows)
    if mutate:
        mutate(rows)
    with tempfile.TemporaryDirectory() as d:
        rep_p = Path(d) / "report.json"
        rep_p.write_text(json.dumps(report))
        csv_p = Path(d) / "rows.csv"
        write_rows(csv_p, rows)
        yield str(rep_p), str(csv_p)


class EquivExactMatch(unittest.TestCase):
    def test_zero_deviation_prints_a_real_worst_and_passes(self):
        with equiv_pair() as (rep, csvp):
            rc, out, err = run_equiv(rep, csvp)
        self.assertEqual(rc, 0)
        # the overall worst must be a real record even at deviation zero
        self.assertIn("0.000e+00", out)
        self.assertIn("Worst:", out)
        self.assertIn(f"{len(C.FIELDS) * len(G.PATTERNS)} compared values", out)
        self.assertIn("within the declared equivalence bound", out)

    def test_above_bound_deviation_still_fails(self):
        def bump_v_rbl_sense(rows):
            r = next(r for r in rows if r["pattern_rows3210"] == "0001")
            r["v_rbl_sense_v"] = f"{float(r['v_rbl_sense_v']) * 1.01:.6e}"
        with equiv_pair(bump_v_rbl_sense) as (rep, csvp):
            rc, out, err = run_equiv(rep, csvp)
        self.assertEqual(rc, 1)
        self.assertIn("OUTSIDE the declared equivalence bound", err)
        self.assertIn("`v_rbl_sense_v`", out)


class EquivNonFinite(unittest.TestCase):
    def _nonfinite_plus_above_bound(self, token, side):
        def mutate(rows):
            r = next(r for r in rows if r["pattern_rows3210"] == "0000")
            r["v_sn_r0_wl_off_v"] = token
            r["v_rbl_sense_v"] = f"{float(r['v_rbl_sense_v']) * 2:.6e}"
        return mutate

    def test_nan_or_inf_with_above_bound_value_is_unavailable_not_passing(self):
        for token in ("nan", "inf", "-inf"):
            with self.subTest(token=token):
                with equiv_pair(self._nonfinite_plus_above_bound(token, "runner")) \
                        as (rep, csvp):
                    rc, out, err = run_equiv(rep, csvp)
                self.assertEqual(rc, 2)
                self.assertIn("non-finite", err)
                self.assertIn("v_sn_r0_wl_off_v", err)
                self.assertIn("0000", err)
                self.assertNotIn("within the declared equivalence bound", out)

    def test_non_finite_on_klt_side_is_unavailable(self):
        report = fake_report(report_values())
        key = f"{G.tag(G.PATTERNS[0])}__v_rbl_sense_v"
        for m in report["corners"][0]["measurements"]:
            if m["name"] == key:
                m["value"] = float("nan")
        age, sel = D.job_of(report)
        good = fake_report(report_values())
        rows = D.rows_for_corner(good["corners"][0], age=age, sel=sel,
                                 knobs=dict(G.BASELINE_KNOBS),
                                 c_sn_f=G.c_sn_farads(), prov=dict(PROV),
                                 run_id="equiv", deck="lc_fresh_sel0.spice")
        with tempfile.TemporaryDirectory() as d:
            rep_p = Path(d) / "report.json"
            rep_p.write_text(json.dumps(report))
            csv_p = Path(d) / "rows.csv"
            write_rows(csv_p, rows)
            rc, out, err = run_equiv(str(rep_p), str(csv_p))
        self.assertEqual(rc, 2, err)
        self.assertIn("non-finite", err)


class EquivNoMeasurements(unittest.TestCase):
    def test_an_empty_measurement_set_is_comparison_unavailable(self):
        rows = [{k: "" for k in R.FIELDS} for _ in G.PATTERNS]
        for p, r in zip(G.PATTERNS, rows):
            r.update(run_id="t", status="ok", corner="tt", temp_c=27,
                     age_label="fresh", sel_row=0, pattern_rows3210=format(p, "04b"))
        with tempfile.TemporaryDirectory() as d:
            rep_p = Path(d) / "report.json"
            rep_p.write_text(json.dumps(fake_report({})))
            csv_p = Path(d) / "rows.csv"
            write_rows(csv_p, rows)
            with mock.patch.object(D, "rows_for_corner", return_value=rows):
                rc, out, err = run_equiv(str(rep_p), str(csv_p))
        self.assertEqual(rc, 2)
        self.assertIn("no comparable measurements", err)


class EquivCommittedPair(unittest.TestCase):
    def test_committed_tt27_pair_still_compares_456_values_and_passes(self):
        if not (COMMITTED_REPORT.is_file() and COMMITTED_CSV.is_file()):
            self.skipTest("committed equivalence artifacts not present")
        rc, out, err = run_equiv(str(COMMITTED_REPORT), str(COMMITTED_CSV))
        self.assertEqual(rc, 0)
        self.assertIn("456 compared values", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
