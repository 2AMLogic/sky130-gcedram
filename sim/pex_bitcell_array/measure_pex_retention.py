#!/usr/bin/env python3
"""`klt pex --measure-command` harness (issue #383): measure the stored-'1
hold-decay retention time ``t_ret_tran_s`` on ONE leg of the drawn bitcell
or the 4x4 array.

``klt pex`` (klt 0.9.1, pinned) invokes this command TWICE per cell -- once
with ``--reference-netlist`` (the schematic leg) and once with its own
freshly ``--parasitics``-extracted, PDK-bound netlist (the extracted leg) --
passing that netlist's path as the final argument and in ``KLT_PEX_NETLIST``,
with ``KLT_PEX_SIDE`` naming the leg. Each invocation:

1. checks the DUT it was handed (flat top name, ORDERED pin list against
   the committed extraction header, ``sky130_fd_pr__nfet_01v8`` instance
   count, and a resistor-network proof that every MOS body reaches the GND
   pin -- ``pex_bench.dut_problems``);
2. builds the write/read/hold transient bench of
   ``sim/bitcell-transient/`` around it (phase timing parsed from the
   committed template; the template's lumped extracted ``c_sn`` omitted so
   the fresh extract supplies the storage-node wiring capacitance once),
   with the GND formal bound to SPICE node 0 and every storage node
   observable and source-free during hold;
3. runs it as one ``klt sim`` batch request per temperature (5 process
   corners each, ``--backend batch --wait-for-capacity 600``, the pinned
   open_pdks install via ``PDK_ROOT``), with the SAME window per corner on
   both legs (sized once from the current-pin leakage rows and the
   committed single-cell extracted ``C_SN`` seed -- window choice affects
   runtime, never the crossing value);
4. gates every report on the worker PDK stamp
   (``pdk_stamp_comparison.status == match`` naming the repo pin) and the
   pinned klt version, saving the reports either way;
5. reduces each corner exactly as ``sim/bitcell-transient/`` does: the
   threshold is THAT LEG'S OWN ``v_sn_hold_start_v`` minus the 0.9 V sense
   margin, and ``t_ret_tran_s`` is the first subsequent falling crossing,
   cubic-interpolated between the 4 nearest crossed rungs of the fixed
   ``.meas`` level ladder (``reduce_bitcell_transient.ladder_crossing``
   verbatim; the ladder ``WHEN ... TD`` values are relative to the hold
   start). An unreachable threshold (at/below the 0.05 V floor -- a
   write-margin failure, not a retention result) or a threshold whose rungs
   were not crossed inside the window is ``null`` with the cause and the
   observation window, never a fabricated value.

It then prints the ``klt pex`` measurement document on stdout -- one
``t_ret_tran_s`` row per corner, status ``pass``/``fail`` against the
ratified §5 single-cell benchmark ``min = 1.005989e-5 s`` (a measured value
below the benchmark is a numerical failure and remains evidence) -- and
writes the per-side audit JSON, the generated benches/requests and the
native ``klt sim`` reports into the study's results tree. Nothing there is
ever overwritten (append-only evidence).

Stdlib only; the ``klt`` binary is resolved from ``GCEDRAM_KLT_BIN`` or
``PATH`` and must report the pinned version.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

STUDY_DIR = Path(__file__).resolve().parent
SIM_DIR = STUDY_DIR.parent
REPO_ROOT = SIM_DIR.parent

sys.path.insert(0, str(SIM_DIR))
sys.path.insert(0, str(SIM_DIR / "bitcell-transient"))
sys.path.insert(0, str(SIM_DIR / "retention"))
sys.path.insert(0, str(STUDY_DIR))

from _evidence_common import (  # noqa: E402
    PDK_OPEN_PDKS_COMMIT,
    measurements_of,
    read_open_pdks_commit,
    resolve_pdk_root,
    worker_pdk_stamp_problems,
)
import gen_bitcell_transient as G  # noqa: E402
import run_bitcell_transient as R  # noqa: E402

import pex_bench  # noqa: E402

KLT_PIN = "klt 0.9.1"
WAIT_FOR_CAPACITY_S = "600"
SIM_TIMEOUT_S = 3600
#: Window seed: the committed single-cell extracted C_SN (the same number
#: `gen_bitcell_transient.py` seeds its own windows from), used for BOTH
#: cells and BOTH legs so every paired corner shares one window. It sizes
#: the observation window only -- it never enters a measured value.
from derive_retention import load_extracted_c_sn  # noqa: E402

C_SN_SEED_FF, _ = load_extracted_c_sn(R.EXTRACT_JSON, "sn")


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def klt_argv() -> list[str]:
    argv = shlex.split(os.environ.get("GCEDRAM_KLT_BIN") or "klt")
    probe = subprocess.run(
        argv + ["--version"], capture_output=True, text=True, timeout=120
    )
    version = probe.stdout.strip()
    if version != KLT_PIN:
        raise SystemExit(
            f"klt at {' '.join(argv)!r} reports {version!r}, expected the pinned "
            f"{KLT_PIN!r} (this study's own pin, the version that produced "
            "the committed envelopes). Set GCEDRAM_KLT_BIN to the pinned install."
        )
    return argv


def check_pdk_root() -> Path:
    root = resolve_pdk_root(None)
    variant = root / "sky130A"
    commit = read_open_pdks_commit(variant)
    if commit != PDK_OPEN_PDKS_COMMIT:
        raise SystemExit(
            f"PDK_ROOT={root} resolves to open_pdks {commit!r}, pinned is "
            f"{PDK_OPEN_PDKS_COMMIT!r}"
        )
    return root


def _unique(path: Path) -> Path:
    if path.exists():
        raise SystemExit(f"refusing to overwrite existing evidence file {path}")
    return path


def run_leg(cell: dict, side: str, netlist: Path, results_dir: Path) -> dict:
    leak = G.load_leakage_current_pin()
    klt = klt_argv()
    p = G.params()
    t_hold = p["THOLD_START"]

    netlist_sha = sha256_of(netlist)
    dut_text = netlist.read_text()
    problems = pex_bench.dut_problems(dut_text, cell)
    if problems:
        raise SystemExit(
            f"{side}-leg DUT {netlist} failed its checks:\n  - " + "\n  - ".join(problems)
        )

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    provenance = {
        "side": side,
        "cell": cell["top"],
        "netlist": str(netlist),
        "netlist_sha256": f"sha256:{netlist_sha}",
        "klt_version": KLT_PIN,
        "generated_utc": stamp,
        "pdk_root_commit": PDK_OPEN_PDKS_COMMIT,
        "c_sn_seed_ff": f"{C_SN_SEED_FF:.6f}",
    }
    _unique(results_dir / f"provenance_{cell_key(cell)}_{side}.json").write_text(
        json.dumps(provenance, indent=2) + "\n"
    )

    audit = {
        "side": side,
        "cell": cell["top"],
        "netlist": str(netlist),
        "netlist_sha256": f"sha256:{netlist_sha}",
        "delta_v_sense_margin_v_ASSUMPTION": pex_bench.DELTA_V_V,
        "t_ret_min_s": pex_bench.T_RET_MIN_S,
        "threshold_floor_v": R.THRESHOLD_FLOOR_V,
        "corners": [],
    }
    doc_corners = []
    reports = []
    for temp_c in G.TEMPS_C:
        window_seed = G.hold_window_s(leak, temp_c, C_SN_SEED_FF)
        tstop = G.hold_tstop(window_seed)
        window = tstop - t_hold
        ttag = G.tag_t(temp_c)
        stem = f"{cell_key(cell)}_{side}_{ttag}"
        bench = results_dir / f"bench_{stem}.spice"
        request = results_dir / f"request_{stem}.json"
        report = results_dir / f"klt_sim_report_{stem}.json"
        _unique(bench).write_text(
            pex_bench.build_bench(dut_text, cell, side, str(netlist), netlist_sha)
        )
        req = G.klt_request(
            bench.name,
            {"process": list(G.PROCESS_CORNERS), "temperature_c": [temp_c]},
            f"{R.TSTEP} {G.g(tstop)} 0 {G.g(G.tmax_for(window_seed))}",
            pex_bench.hold_measurements_for(cell, window),
            SIM_TIMEOUT_S,
            extra_options=G.MEAS_PRECISION,
        )
        _unique(request).write_text(json.dumps(req, indent=2) + "\n")
        argv = klt + [
            "sim",
            str(request),
            "--backend",
            "batch",
            "--wait-for-capacity",
            WAIT_FOR_CAPACITY_S,
            "--format",
            "json",
            "--report-out",
            str(_unique(report)),
        ]
        proc = subprocess.run(argv, capture_output=True, text=True)
        if proc.returncode != 0:
            sys.stderr.write(
                f"klt sim failed for {stem} (exit {proc.returncode}):\n"
                f"{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}\n"
            )
            raise SystemExit(1)
        rep = json.loads(report.read_text())
        reports.append((stem, report, rep))

        for c in rep["corners"]:
            if c.get("status") != "pass":
                raise SystemExit(
                    f"{stem}: corner {c.get('corner_id')} status {c.get('status')!r} "
                    f"(diagnostics: {c.get('diagnostics')})"
                )
            m = measurements_of(c, strict=True)
            row = pex_bench.reduce_t_ret(m, window)
            t_ret = row["value"]
            audit_row = {
                "corner_id": f"{c['process']}/{temp_c}C",
                "process": c["process"],
                "temperature_c": temp_c,
                "v_sn_hold_start_v": row["v_sn_hold_start_v"],
                "threshold_v": row["threshold_v"],
                "hold_window_s": window,
                "tstop_s": tstop,
                "tmax_s": G.tmax_for(window_seed),
                "ladder_crossed_levels_v": row["ladder_crossed_levels_v"],
                "t_ret_tran_s": t_ret,
                "status": row["status"],
            }
            if "message" in row:
                audit_row["message"] = row["message"]
            audit["corners"].append(audit_row)
            doc_corners.append(
                {
                    "corner_id": audit_row["corner_id"],
                    "measurements": [
                        {
                            "name": "t_ret_tran_s",
                            "unit": "s",
                            "value": t_ret,
                            "status": row["status"],
                            **({"message": row["message"]} if t_ret is None else {}),
                        }
                    ],
                }
            )

    stamps = []
    for stem, path, rep in reports:
        problems = worker_pdk_stamp_problems(rep)
        if problems:
            stamps.append((stem, str(path), problems))
    if stamps:
        for stem, path, problems in stamps:
            sys.stderr.write(f"PDK stamp gate FAILED for {stem} ({path}): {problems}\n")
        sys.stderr.write(
            "The affected run is stopped per issue #383's outcome table; the request, "
            "job id, stamp and simulator details are saved in the reports above.\n"
        )
        raise SystemExit(3)

    _unique(results_dir / f"audit_{cell_key(cell)}_{side}.json").write_text(
        json.dumps(audit, indent=2) + "\n"
    )
    return {"corners": doc_corners}


def cell_key(cell: dict) -> str:
    return "array" if cell["top"].startswith("gain_cell_2t_array") else "bitcell"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--cell", required=True, choices=sorted(pex_bench.CELLS))
    ap.add_argument("netlist", nargs="?")
    a = ap.parse_args(argv)

    side = os.environ.get("KLT_PEX_SIDE")
    if side not in ("schematic", "extracted"):
        raise SystemExit(f"KLT_PEX_SIDE must be schematic|extracted, got {side!r}")
    netlist = Path(a.netlist or os.environ["KLT_PEX_NETLIST"])
    if not netlist.is_file():
        raise SystemExit(f"netlist {netlist} does not exist")

    check_pdk_root()
    results_dir = Path(
        os.environ.get("GCEDRAM_PEX_RESULTS_DIR")
        or (STUDY_DIR / "results" / "native")
    )
    results_dir.mkdir(parents=True, exist_ok=True)

    doc = run_leg(pex_bench.CELLS[a.cell], side, netlist, results_dir)
    json.dump(doc, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
