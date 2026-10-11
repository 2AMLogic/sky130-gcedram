#!/usr/bin/env python3
"""Check that the issue #49 evidence package resolves and is consistent.

Stdlib only; no simulation. Exit 0 = all checks pass, 1 = any failure.
`--online` additionally re-fetches the SkyWater PDK page (network; optional).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RES = HERE / "results"

DOCS = [
    HERE / "EVIDENCE_INDEX.md",
    HERE / "STRESS_LIMIT_INVENTORY.md",
    HERE / "SENSE_INPUT_CONTRACT.md",
    HERE / "sources" / "skywater-pdk-device-details-excerpt.md",
    ROOT / "spec" / "supply-reliability-decision-PROPOSED.md",
    HERE / "sources" / "reliability-search-log-issue51.md",
    HERE.parent / "extracted-crbl" / "README.md",
]
OPEN_PDKS = "c6d73a35f524070e85faff4a6a9eef49553ebc2b"
HASHES = {
    "summary_20261005T145658Z.json": "5c449e87c4b492d8a746a7e5edbdf1f247204b57e4ea87b10112570b85d15df4",
    "pass_fail_20261005T145658Z.csv": "42fc77a6d56f82822520ecbc5bd0d0fcb7905e88eeadcedd698885f0a202ae99",
}
LIB_SHA = "48de7c677e2c6e7d09b2559279de9f818be71010a4aa933d728eb4db3b133c84"
MIN_ROWS = {"variant_results.csv": 10176, "phase2_reproduction.csv": 256, "vth_results.csv": 60}
RUN_IDS = {"20261005T135553Z": 3456, "20261005T141748Z": 6720}
DOC_LINE = "V_DS = 0 to 1.95V   V_GS = 0 to 1.95V   V_BS = +0.3 to -1.95V"

fails: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        fails.append(msg)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def close(a: float, b: float, tol: float = 6e-4) -> bool:
    return abs(a - b) <= tol


def links() -> None:
    pat = re.compile(r"\[[^\]]*\]\(([^)#\s]+)(?:#[^)]*)?\)")
    for d in DOCS:
        if not d.exists():
            check(False, f"document exists: {d}")
            continue
        bad = []
        for m in pat.finditer(d.read_text()):
            t = m.group(1)
            if re.match(r"[a-z]+://", t):
                continue
            if not (d.parent / t).resolve().exists():
                bad.append(t)
        check(not bad, f"links resolve in {d.name}" + (f" (missing {bad})" if bad else ""))


def pins() -> None:
    for name, p in {
        "docs/pdk-pin.md": ROOT / "docs" / "pdk-pin.md",
        "sim/_evidence_common.py": ROOT / "sim" / "_evidence_common.py",
        "cold-corner README": HERE / "README.md",
        "EVIDENCE_INDEX.md": HERE / "EVIDENCE_INDEX.md",
    }.items():
        check(OPEN_PDKS in p.read_text(), f"open_pdks pin present in {name}")
    for f, h in HASHES.items():
        check(sha(RES / f) == h, f"sha256 {f}")
    for f, n in MIN_ROWS.items():
        with open(RES / f) as fh:
            rows = sum(1 for _ in csv.reader(fh)) - 1
        check(rows >= n, f"{f} rows {rows} >= {n}")
    with open(RES / "variant_results.csv") as fh:
        rr = list(csv.DictReader(fh))
    for rid, n in RUN_IDS.items():
        got = sum(1 for r in rr if r["run_id"] == rid)
        check(got == n, f"run {rid} has {got} rows (expect {n})")
    check(all(r["pdk_open_pdks_commit"] == OPEN_PDKS for r in rr), "every variant row carries the open_pdks pin")
    root = Path(os.environ.get("PDK_ROOT", "~/.volare")).expanduser() / "sky130A"
    src, lib = root / "SOURCES", root / "libs.tech/combined/sky130.lib.spice"
    if src.exists():
        check(OPEN_PDKS in src.read_text(), "installed PDK SOURCES matches pin")
        check(sha(lib) == LIB_SHA, "installed model library sha256 matches the recorded one")
    else:
        print("SKIP installed PDK not found (set PDK_ROOT to verify SOURCES and library hash)")


def numbers() -> None:
    s = json.loads((RES / "summary_20261005T145658Z.json").read_text())["variants"]

    def pts(v):
        return s[v]["points"]

    def pt(v, c, t, a):
        return next(p for p in pts(v) if p["corner"] == c and p["temp_c"] == t and p["age"] == a)

    for v in ("phase2_baseline", "rem_vwl_2p0", "rem_rwl_m0p2"):
        check(len(pts(v)) == 30, f"{v}: 30 points")
    mnf = lambda v, f: min(f(p) for p in pts(v))
    mxf = lambda v, f: max(f(p) for p in pts(v))
    a0, a1 = "after_write", "preread"
    check(close(mnf("rem_vwl_2p0", lambda p: p["stored0_after_write_v"]["min"]), -0.1393), "A stored '0' min -0.139 V")
    check(close(mnf("phase2_baseline", lambda p: p["stored0_after_write_v"]["min"]), -0.13465), "baseline stored '0' min -0.135 V")
    check(close(mnf("phase2_baseline", lambda p: p["stored1_after_write_v"]["min"]), 0.8637), "baseline stored '1' min 0.864 V")
    check(close(mxf("phase2_baseline", lambda p: p["stored1_after_write_v"]["max"]), 1.2219), "baseline stored '1' max 1.222 V")
    check(close(mnf("rem_vwl_2p0", lambda p: p["stored1_after_write_v"]["min"]), 1.0238), "A stored '1' min 1.024 V")
    check(close(mxf("rem_vwl_2p0", lambda p: p["stored1_after_write_v"]["max"]), 1.3823), "A stored '1' max 1.382 V")
    check(close(pt("rem_vwl_2p0", "fs", -40, "refresh_bound")["stored1_preread_v"]["min"], 1.0198), "A cold at bound 1.020 V")
    check(close(pt("rem_vwl_2p0", "sf", 125, "refresh_bound")["stored1_preread_v"]["min"], 1.0861), "A hot at bound 1.086 V")
    check(close(pt("phase2_baseline", "sf", 125, "refresh_bound")["stored1_preread_v"]["min"], 0.9555), "baseline hot at bound 0.956 V")
    check(close(pt("phase2_baseline", "fs", -40, "refresh_bound")["stored1_preread_v"]["min"], 0.8604), "baseline cold at bound 0.860 V")
    check(close(pt("phase2_baseline", "fs", -40, "fresh")["worst_case_separation_v"], 0.018, 6e-4), "baseline fs/-40 fresh separation 0.018 V")
    check(close(pt("phase2_baseline", "fs", -40, "refresh_bound")["worst_case_separation_v"], 0.017, 6e-4), "baseline fs/-40 aged separation 0.017 V")
    check(close(s["rem_vwl_2p0"]["min_point_separation_v"], 0.4125), "A min separation 0.413 V")
    check(close(s["rem_rwl_m0p2"]["min_point_separation_v"], 0.6040), "B min separation 0.604 V")
    check(close(pt("phase2_baseline", "sf", 125, "fresh")["worst_case_separation_v"], 0.515), "baseline hot separation 0.515 V")
    check(close(pt("rem_vwl_2p0", "sf", 125, "fresh")["worst_case_separation_v"], 0.435), "A hot separation 0.435 V")
    check(close(mxf("rem_rwl_m0p2", lambda p: p["read_disturb_sel_abs_max_v"]), 0.0816), "B read disturb 0.082 V")
    check(close(mxf("phase2_baseline", lambda p: p["read_disturb_sel_abs_max_v"]), 0.0673), "baseline read disturb 0.067 V")
    n_clamped = sum(1 for p in pts("rem_rwl_m0p2") if p["v_rbl_sense_stored1_v"]["min"] <= -0.1990)
    check(n_clamped == 28, f"B: rbl reaches -0.2 V in {n_clamped}/30 points (doc says 28)")
    cold = [pt("rem_rwl_m0p2", "fs", -40, a)["v_rbl_sense_stored1_v"]["min"] for a in ("fresh", "refresh_bound")]
    check(close(cold[0], -0.0252, 5e-4) and close(cold[1], -0.0077, 5e-4), "B fs/-40 rbl reaches -0.025 / -0.008 V")
    check(not any(p["v_rbl_sense_stored1_v"]["min"] < -0.2001 for p in pts("rem_rwl_m0p2")), "B rbl never below -0.2 V")
    check(abs(s["phase2_baseline"]["points"][0]["level_chain"]["v_sn1_after_write_min_v"] - 0.9594) < 1e-3, "baseline tt/-40 sanity")
    with open(RES / "variant_results.csv") as fh:
        r0 = next(csv.DictReader(fh))
    check(close(float(r0["c_sn_ff"]), 0.605354, 1e-6), "study C_SN = 0.605354 fF")
    check(float(r0["vrbl_precharge_v"]) == 0.9, "VRBL = 0.9 V")
    ratified = (ROOT / "spec" / "retention-refresh-budget.md").read_text()
    for tok in ("1.106463", "9.898880e-11", "~5.03", "1.005989e-05", "RATIFIED"):
        check(tok in ratified, f"ratified spec still contains {tok}")


def status() -> None:
    d = (ROOT / "spec" / "supply-reliability-decision-PROPOSED.md").read_text()
    check("STATUS: PROPOSED. NOT RATIFIED." in d, "decision record is conspicuously PROPOSED")
    check("MISSING EVIDENCE" in d, "decision record carries a verdict")
    for tok in ("1.106463", "9.898880e-11", "~5.03 us", "~10.06 us"):
        check(tok in d, f"decision record preserves {tok}")
    ex = (HERE / "sources" / "skywater-pdk-device-details-excerpt.md").read_text()
    check(DOC_LINE in ex.replace("\n", " ") or "V_DS = 0 to 1.95V" in ex, "excerpt carries the verbatim validity line")
    check("995acd5dfa0589d156619694db011873796a5d2d" in ex, "excerpt pins the skywater-pdk commit")


SW_PDK_HEAD = "7198cf647113f56041e02abf3eb623692820c5e1"
SW_FILES = {
    "docs/rules/hv.rst": "f355ddf478c129661e96b44d4c4509a124e85e2e44d51bd3b072b43aee7e1f98",
    "docs/rules/assumptions.rst": "99981cebb004a90f7947abc9461f03cdacc4b1906c94f340359c7aeb13f62edc",
    "docs/rules/device-details/diodes/diodes-table0.rst": "3f16c7dd4f2d9a24c6db99e7750ae588b12664e8c0d350e1a180f49bb8dc0b06",
    "docs/rules/device-details.rst": "506021827f52b26673daf8b580f8d79d408724af3138a65695bde86e5c1c6e49",
}
OP_HEAD = "801834fcbf9119e6fd4462f97da9e637f284539a"
OP_TECH = "5f96a22bd00169807b2228742e17a27e3624e5fb010c523447bbc4fee30a4f97"
# verbatim excerpts quoted in the #51 log: (path in skywater-pdk, text)
SW_EXCERPTS = [
    ("docs/rules/hv.rst", "High Voltage is defined as a voltage outside the range of GND to Vcc."),
    ("docs/rules/hv.rst", "The biasing conditions of these high voltage devices are detailed in the ETD."),
    ("docs/rules/hv.rst", "a. Any HV NMOS device: 7.3 V @ 25C."),
    ("docs/rules/hv.rst", "These voltages are not operating voltages, but points of failure."),
    ("docs/rules/assumptions.rst", "Minimum n+ or p+ - nwell spacing to prevent latch-up,um,0.23,NPNWLU"),
    ("docs/rules/device-details.rst", "Reverse-active mode operation of the BJT"),
]


def issue51() -> None:
    log_p = HERE / "sources" / "reliability-search-log-issue51.md"
    log = log_p.read_text()
    flat = re.sub(r"\s+", " ", log)
    for h in [SW_PDK_HEAD, OP_HEAD, OP_TECH, *SW_FILES.values()]:
        check(h in log, f"#51 log pins {h[:12]}...")
    for path, text in SW_EXCERPTS:
        check(re.sub(r"\s+", " ", text) in flat, f"#51 log quotes: {text[:50]}")
    for tok in ("not found", "**No match**", "NOT-APPLICABLE", "Unretrievable"):
        check(tok in log, f"#51 log records negative/unretrievable result marker: {tok}")
    check(log.count("\n| ") >= 12 and "| 12 |" in log, "#51 log has the 12 recorded searches")
    d = (ROOT / "spec" / "supply-reliability-decision-PROPOSED.md").read_text()
    check("## 8. Evidence status update (issue #51" in d, "decision record has the #51 evidence status")
    check("Outcome supported: C" in d, "decision record states the supported outcome")
    check("STATUS: PROPOSED. NOT RATIFIED." in d and "RATIFIED" not in d.split("## 8.")[1].replace("NOT RATIFIED", "").replace("ratified", "").replace("ratification", ""), "section 8 does not claim ratification")
    inv = (HERE / "STRESS_LIMIT_INVENTORY.md").read_text()
    check("### 5.1 Issue #51 search update" in inv and "**UNAVAILABLE**" in inv, "inventory section 5 preserved and 5.1 appended")
    check("Issue #51 addendum" in (HERE / "EVIDENCE_INDEX.md").read_text(), "index has the #51 addendum")


EXT_DIR = HERE.parent / "extracted-crbl"
EXT_RUN = EXT_DIR / "results" / "20261011T015419Z"
SS_RES = ROOT / "sim" / "sense-stage" / "results"
ISSUE88_HASHES = {
    EXT_RUN / "summary.json": "77d07c21bcf59aa3c5b81e64c2ceb90026e2ff79788c57a808d4acdd72efe464",
    EXT_RUN / "cases.csv.gz": "48a83f9e2ef56f7f0617eb4c33d241215b35a0ccb549952c9138af8a71f3dbc4",
    SS_RES / "sense_summary_20261011T015836Z.json": "d171548c93997aa1bd1207f2511d2585eef33bdb1bef4b00781d9779214caa0b",
    SS_RES / "sense_summary_20261011T020128Z.json": "5a913667308f99335046eb930ecfb5d655e30ba1bb508848ab382deab94a1bda",
    SS_RES / "sense_summary_20261011T020422Z.json": "39b06ab5d4acba1aa01af6b9b9b8ff5a73c049e87350825312c060a82ff03bad",
}
ARRAY_NETLIST_SHA = "dd2cca26de34d6b7cd39a0d794db64993d6440c5ca7f248cf4d657b6f6b88d33"


def issue88() -> None:
    """Issue #88: extracted C_RBL re-run, contract addendum numbers, pins."""
    for p, h in ISSUE88_HASHES.items():
        check(p.exists() and sha(p) == h, f"#88 sha256 {p.relative_to(ROOT)}")
    par = json.loads((ROOT / "layout" / "gain_cell_2t_array.parasitics.summary.json").read_text())
    c_rbl = par["comparison"]["c_rbl"]["extracted_4row_worst_total_ff"]
    check(close(c_rbl, 0.859179, 1e-6), "#88 extracted C_RBL is 0.859179 fF at the cited key")
    check(par["source"]["netlist_sha256"] == ARRAY_NETLIST_SHA, "#88 extracted netlist sha256 pinned")
    s = json.loads((EXT_RUN / "summary.json").read_text())
    check(not s["errors"], "#88 loaded-column summary has no errors")
    check(s["reproduction"]["ok"] and s["reproduction"]["cases_compared"] == 1920,
          "#88 10 fF harness reproduces committed Phase 2 (1920 cases)")
    check(s["negative_control"]["behaves_as_expected"], "#88 negative control fails as required")
    check(not s["claims"]["spec_changed"] and not s["claims"]["n_rows_ratified"]
          and not s["claims"]["real_periphery_used"], "#88 claims: no spec change, N_rows not ratified, ideal periphery")
    check(close(s["c_rbl_source"]["value_ff"], c_rbl, 1e-9), "#88 run used the cited C_RBL")
    V = s["variants"]

    def pt(v, c, t, a):
        return next(p for p in V[v]["points"] if (p["corner"], p["temp_c"], p["age"]) == (c, t, a))

    ext_min = V["crbl_ext4row"]["min_point_separation_v"]
    check(close(ext_min, 0.075, 6e-4), "#88 extracted min separation 0.075 V")
    check(close(pt("crbl_ext4row", "fs", -40, "refresh_bound")["worst_case_separation_v"], ext_min, 1e-12),
          "#88 extracted min is at fs/-40 aged")
    a = pt("crbl_ext4row", "fs", -40, "refresh_bound")
    check(not a["PASS"] and close(a["latency_stored1_s"]["max"] * 1e9, 12.97, 6e-3), "#88 fs/-40 aged FAIL, latency 12.97 ns")
    check(V["crbl_ext4row"]["n_points_pass"] == 28 and V["ref_crbl_10f"]["n_points_pass"] == 28, "#88 28/30 at 10 fF and extracted")
    for age, sep, lat in (("refresh_bound", 0.370, 1.69), ("fresh", 0.388, 1.56)):
        p = pt("crbl_ext4row", "ss", -40, age)
        check(p["PASS"] and close(p["worst_case_separation_v"], sep, 6e-4) and close(p["latency_stored1_s"]["max"] * 1e9, lat, 6e-3),
              f"#88 ss/-40 {age} {sep} V / {lat} ns")
    check(close(V["crbl_2f"]["min_point_separation_v"], 0.052, 6e-4), "#88 2 fF min 0.052 V")
    check(close(pt("crbl_2f", "ss", -40, "refresh_bound")["worst_case_separation_v"], 0.288, 6e-4), "#88 2 fF ss/-40 aged 0.288 V")
    check(V["crbl_ext4row_layoutcard"]["n_points_pass"] == 30
          and close(V["crbl_ext4row_layoutcard"]["min_point_separation_v"], 0.108, 6e-4), "#88 layout card 30/30, min 0.108 V")
    ss = json.loads((SS_RES / "sense_summary_20261011T015836Z.json").read_text())
    td = [c["stage_tdec_at_1mv_ns_minus"] for c in ss["corners"]]
    check(close(min(td), 0.11, 6e-3) and close(max(td), 0.23, 6e-3), "#88 sense-stage t_dec at 1 mV 0.11-0.23 ns")
    check({c["temp_c"] for c in ss["corners"]} == {27, 125}, "#88 sense stage has no -40 C result")
    con = (HERE / "SENSE_INPUT_CONTRACT.md").read_text()
    head, _, add = con.partition("## 2026-10-11 addendum: extracted `C_RBL` row (issue #88, PROPOSED)")
    check(bool(add), "#88 contract has the dated addendum")
    check("| `C_RBL` | 10 fF | same | same | ASSUMPTION (not extracted)" in head and "4. Any new multi-corner" in head,
          "#88 original contract row and rules preserved")
    for tok in ("0.859179 fF", "EXTRACTED-4-ROW", "not ratified", ARRAY_NETLIST_SHA, "0.075 V", "0.370 V", "0.288 V",
                "0.108 V", "12.97 ns", "0.11-0.23 ns", "comparison.c_rbl.extracted_4row_worst_total_ff", "**ideal**"):
        check(tok in add, f"#88 contract addendum quotes {tok}")
    check("Issue #88 addendum" in (HERE / "EVIDENCE_INDEX.md").read_text(), "index has the #88 addendum")


def issue51_online() -> None:
    import urllib.request
    base = f"https://raw.githubusercontent.com/google/skywater-pdk/{SW_PDK_HEAD}/"
    got = {}
    for path, h in SW_FILES.items():
        try:
            b = urllib.request.urlopen(urllib.request.Request(base + path, headers={"User-Agent": "curl/8"}), timeout=30).read()
        except Exception as e:  # network failure is a failure of the online check
            check(False, f"fetch {path}: {e}")
            continue
        got[path] = re.sub(r"\s+", " ", b.decode("utf8", "ignore"))
        check(hashlib.sha256(b).hexdigest() == h, f"online sha256 {path} at pinned commit")
    for path, text in SW_EXCERPTS:
        if path in got:
            check(re.sub(r"\s+", " ", text) in got[path], f"online excerpt in {path}: {text[:40]}")
    try:
        b = urllib.request.urlopen(urllib.request.Request(
            f"https://raw.githubusercontent.com/RTimothyEdwards/open_pdks/{OP_HEAD}/sky130/magic/sky130.tech",
            headers={"User-Agent": "curl/8"}), timeout=60).read()
        check(hashlib.sha256(b).hexdigest() == OP_TECH, "online sha256 open_pdks sky130/magic/sky130.tech")
    except Exception as e:
        check(False, f"fetch open_pdks tech: {e}")


def online() -> None:
    import html
    import urllib.request
    url = "https://skywater-pdk.readthedocs.io/en/main/rules/device-details.html"
    t = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "curl/8"}), timeout=30).read().decode("utf8", "ignore")
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", t, flags=re.S)
    t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))
    check("V_{DS} = 0" in t and "1.95V" in t, "live PDK page still states the V_DS range")
    check("V_{GS} = 0" in t and "to -1.95V" in t, "live PDK page still states the V_GS range")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--online", action="store_true")
    a = ap.parse_args()
    links()
    pins()
    numbers()
    status()
    issue51()
    issue88()
    if a.online:
        online()
        issue51_online()
    print("RESULT:", "FAIL" if fails else "PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
