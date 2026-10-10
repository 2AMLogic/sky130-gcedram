#!/usr/bin/env python3
"""Export the strobe edges of ONE phase_seq REFRESH operation to a JSON trace (issue #128).

Runs ``iverilog`` + ``vvp`` on ``digital/phase-control/phase_seq.v`` and ``tb_trace_export.v`` (defaults:
the committed ``anchored`` 2/10/20/2 scenario, GAP 0). Refuses to overwrite an existing output file.
Usage: export_rtl_trace.py OUT.json [--pre N --sense N --wb N --guard N --gap N --kind 0|1|2]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
PC = REPO / "digital" / "phase-control"
sys.path.insert(0, str(HERE))
import replay_lib as L  # noqa: E402


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def export(pre=2, sense=10, wb=20, guard=2, gap=0, kind=2) -> dict:
    src, tb = PC / "phase_seq.v", PC / "tb_trace_export.v"
    with tempfile.TemporaryDirectory() as d:
        vvp = Path(d) / "t.vvp"
        cmd = ["iverilog", "-g2012", "-o", str(vvp), f"-Ptb_trace_export.P_PRE={pre}", f"-Ptb_trace_export.P_SENSE={sense}",
               f"-Ptb_trace_export.P_WB={wb}", f"-Ptb_trace_export.P_GUARD={guard}", f"-Ptb_trace_export.GAP={gap}",
               f"-Ptb_trace_export.KIND={kind}", str(src), str(tb)]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        out = subprocess.run(["vvp", str(vvp)], check=True, capture_output=True, text=True).stdout
    tr = L.parse_vvp_output(out)
    ver = subprocess.run(["iverilog", "-V"], capture_output=True, text=True).stdout.splitlines()[0]
    tr["pins"] = dict(phase_seq_v_sha256=sha256(src), tb_trace_export_v_sha256=sha256(tb),
                      iverilog=ver, command=" ".join(["iverilog", "-g2012", "-o", "<tmp>.vvp"] + cmd[4:]),
                      time_base="1 cycle = 1 ns (study assumption, not a silicon frequency claim)",
                      sampling="strobes sampled 0.1 ns after each rising clock edge; zero-width delta glitches not exported")
    return tr


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("out", type=Path)
    for k, v in dict(pre=2, sense=10, wb=20, guard=2, gap=0, kind=2).items():
        ap.add_argument(f"--{k}", type=int, default=v)
    a = ap.parse_args(argv)
    if a.out.exists():
        print(f"refusing to overwrite {a.out}", file=sys.stderr)
        return 2
    tr = export(a.pre, a.sense, a.wb, a.guard, a.gap, a.kind)
    a.out.write_text(json.dumps(tr, indent=1) + "\n")
    print(f"wrote {a.out} ({len(tr['edges'])} edges)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
