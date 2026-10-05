#!/usr/bin/env python3
"""Constant-current threshold voltage of the bitcell's NMOS flavours across
the 15-point grid (issue #47 attribution aid).

Definition (stated, conventional; not a PDK-published number): Vth is the
gate-source voltage at which the drain current reaches 100 nA * W/L with
Vds = 0.1 V, at source-body bias Vsb = 0 V and Vsb = 0.9 V (the latter is the
write device's situation while it charges a storage node towards ~1 V). It is
measured on the shipped sky130 models at the bitcell geometry (W/L =
0.42/0.15 um). The read device's stored-'1' overdrive is compared against
the Vsb = 0 value (its source is the selected rwl at 0 V).

Usage:
    python3 sim/loaded-column/cold-corner/extract_vth.py [--jobs 8]
Appends to results/vth_results.csv (never rewritten).
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import run_loaded_column as R  # noqa: E402
from _evidence_common import (  # noqa: E402
    DEFAULT_PDK_VARIANT, PDK_OPEN_PDKS_COMMIT, append_result, ngspice_version,
    repo_git_sha, resolve_ngspice_lib, resolve_pdk_root,
)

RESULTS_CSV = HERE / "results" / "vth_results.csv"
MODELS = ["sky130_fd_pr__nfet_01v8", "sky130_fd_pr__nfet_01v8_lvt"]
VSB = [0.0, 0.9]
W_UM, L_UM = 0.42, 0.15
I_CRIT_A = 100e-9 * W_UM / L_UM
FIELDS = ["run_id", "timestamp_utc", "repo_git_sha", "pdk_open_pdks_commit", "ngspice_version",
          "corner", "temp_c", "model", "w_um", "l_um", "vds_v", "vsb_v", "i_crit_a",
          "vth_cc_v", "status", "reason"]


def deck(lib, corner, temp):
    lines = [f"* vth extraction {corner} {temp}C", f'.lib "{lib}" {corner}', f".temp {temp}",
             "vg g 0 0"]
    for i, m in enumerate(MODELS):
        for j, vsb in enumerate(VSB):
            n = f"{i}{j}"
            # source at +vsb, body at 0, drain at vsb + 0.1, gate swept relative to ground
            lines += [f"vs{n} s{n} 0 {vsb}", f"vd{n} d{n} 0 {vsb + 0.1}",
                      f"x{n} d{n} g{n} s{n} 0 {m} L={L_UM} W={W_UM} nf=1 ad=0.1218 as=0.1218 "
                      "pd=1.42 ps=1.42 nrd=0.69047619047619 nrs=0.69047619047619",
                      f"eg{n} g{n} s{n} g 0 1"]
    lines += [".control", "dc vg 0 1.8 0.001"]
    for i in range(len(MODELS)):
        for j in range(len(VSB)):
            n = f"{i}{j}"
            lines += [f"let id{n} = -i(vd{n})", f"meas dc vt{n} when id{n}={I_CRIT_A:.6e}"]
    lines += [".endc", ".end"]
    return "\n".join(lines) + "\n"


def run(args):
    lib, corner, temp = args
    d = Path(tempfile.mkdtemp(prefix="gcedram_vth_"))
    p = d / "vth.sp"
    p.write_text(deck(lib, corner, temp))
    res = subprocess.run(["ngspice", "-b", str(p)], capture_output=True, text=True, timeout=1800)
    p.unlink()
    d.rmdir()
    out = {}
    for line in res.stdout.splitlines():
        s = line.split()
        if len(s) >= 3 and s[0].startswith("vt") and s[1] == "=":
            out[s[0]] = float(s[2])
    return corner, temp, out, (res.stdout + res.stderr)[-200:]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdk-root")
    ap.add_argument("--jobs", type=int, default=8)
    a = ap.parse_args(argv)
    lib = resolve_ngspice_lib(resolve_pdk_root(a.pdk_root), DEFAULT_PDK_VARIANT)
    now = datetime.datetime.now(datetime.timezone.utc)
    prov = {"run_id": now.strftime("%Y%m%dT%H%M%SZ"), "timestamp_utc": now.isoformat(timespec="seconds"),
            "repo_git_sha": repo_git_sha(R.REPO_ROOT), "pdk_open_pdks_commit": PDK_OPEN_PDKS_COMMIT,
            "ngspice_version": ngspice_version()}
    pts = [(lib, c, t) for c in R.CORNERS for t in R.TEMPS_C]
    with cf.ProcessPoolExecutor(max_workers=a.jobs) as ex:
        for corner, temp, out, tail in ex.map(run, pts):
            for i, m in enumerate(MODELS):
                for j, vsb in enumerate(VSB):
                    v = out.get(f"vt{i}{j}")
                    append_result(RESULTS_CSV, FIELDS, prov | {
                        "corner": corner, "temp_c": temp, "model": m, "w_um": W_UM, "l_um": L_UM,
                        "vds_v": 0.1, "vsb_v": vsb, "i_crit_a": f"{I_CRIT_A:.6e}",
                        "vth_cc_v": "" if v is None else f"{v:.6f}",
                        "status": "ok" if v is not None else "failed",
                        "reason": "" if v is not None else tail.replace("\n", " ")})
            print(corner, temp, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
