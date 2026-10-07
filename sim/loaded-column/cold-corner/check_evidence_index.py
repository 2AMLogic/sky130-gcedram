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
    if a.online:
        online()
    print("RESULT:", "FAIL" if fails else "PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
