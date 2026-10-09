#!/usr/bin/env python3
"""Print the integration bench parameters as shell assignments, derived from
existing sources rather than retyped:

  INTERVAL      ../refresh-scheduler/params.py <basis>  (retention CSV; floor(t_ret/2),
                1 cycle = 1 ns ASSUMPTION; 'ratified' or 'extracted' stress variant)
  N_ROWS, T_ROW, T_ACC, GUARD
                parameter defaults of ../refresh-scheduler/refresh_sched.v (#74 ASSUMPTIONS)
  MIN_INTERVAL  N_ROWS*T_ROW + T_ACC + GUARD: the #74 feasibility check
                (EAGER_AGE >= 0) solved for INTERVAL. Computed here in Python,
                independently of the Verilog expression in gc_ctrl_top.v, so
                the bench cross-checks the RTL floor.

usage: params.py [ratified|extracted]
"""
import pathlib, re, subprocess, sys

here = pathlib.Path(__file__).resolve().parent
sched = here.parent / "refresh-scheduler"
which = sys.argv[1] if len(sys.argv) > 1 else "ratified"
if which not in ("ratified", "extracted"):
    sys.exit(f"unknown basis {which!r}")

interval = int(subprocess.run([sys.executable, "-I", str(sched / "params.py"), which],
                              check=True, capture_output=True, text=True).stdout.strip())

src = (sched / "refresh_sched.v").read_text()
vals = {}
for name in ("N_ROWS", "T_ROW", "T_ACC", "GUARD"):
    m = re.search(r"parameter\s+integer\s+%s\s*=\s*(\d+)" % name, src)
    if not m:
        sys.exit(f"cannot find default for {name} in refresh_sched.v")
    vals[name] = int(m.group(1))

min_interval = vals["N_ROWS"] * vals["T_ROW"] + vals["T_ACC"] + vals["GUARD"]
if not (min_interval <= interval <= 0xFFFF):
    sys.exit(f"infeasible: MIN_INTERVAL={min_interval} INTERVAL={interval}")

print(f"INTERVAL={interval}")
for k, v in vals.items():
    print(f"{k}={v}")
print(f"MIN_INTERVAL={min_interval}")
