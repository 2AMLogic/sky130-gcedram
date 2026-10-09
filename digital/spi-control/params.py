#!/usr/bin/env python3
"""Print the refresh-interval bound (cycles, 1 cycle = 1 ns ASSUMPTION) for the
SPI interval register. Reuses digital/refresh-scheduler/params.py, which reads
the committed retention CSV (spec/retention-refresh-budget.md Sec.7 basis), so
no number is retyped here.  usage: params.py [ratified|extracted]"""
import pathlib, subprocess, sys
src = pathlib.Path(__file__).resolve().parents[1] / "refresh-scheduler" / "params.py"
which = sys.argv[1] if len(sys.argv) > 1 else "ratified"
out = subprocess.run([sys.executable, "-I", str(src), which], check=True,
                     capture_output=True, text=True).stdout.strip()
print(int(out))
