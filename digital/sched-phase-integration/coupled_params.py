#!/usr/bin/env python3
"""Derive the coupled scheduler/sequencer budgets for one phase-duration set,
independently of the Verilog (coupled_top.v) so the bench can cross-check the RTL.
Behavioral, ASSUMPTION-based (1 cycle = 1 ns inherited from the scheduler).

  D_REF = PRE+SENSE+WB+GUARD+3*GAP      REFRESH sequencer busy length
  D_RD  = PRE+SENSE+GUARD+2*GAP         READ
  D_WR  = WB+GUARD+GAP                  WRITE
  LAT   = 1   launch/registration latency (measured in #135, TIMING_REPORT.md Sec. 1)
  T_ROW = D_REF + LAT ; T_ACC = max(D_RD, D_WR) + LAT
  GUARD_EFF    = SCHED_GUARD + N_ROWS + 1   (per-op decision cycle accounted; see coupled_top.v)
  MIN_INTERVAL = N_ROWS*T_ROW + T_ACC + GUARD_EFF       runtime feasibility floor (legal under saturation)
  T_SETTLE     = (T_ACC+1) + N_ROWS*(T_ROW+1) + SCHED_GUARD   shortening bound
                 (one in-flight external op, then N_ROWS back-to-back refreshes;
                 each op occupies its duration plus one decision cycle)
INTERVAL comes from ../control-integration/params.py (retention CSV), N_ROWS and
SCHED_GUARD from the same place. Exit status is non-zero when the combination is
infeasible (MIN_INTERVAL > INTERVAL or INTERVAL > 16 bit); nothing is printed then
except the reason on stderr.

usage: coupled_params.py BASIS SET     BASIS: ratified|extracted
       SET: anchored|gap1|full_read_pulse|fast|mismatch|huge   or  PRE,SENSE,WB,GUARD,GAP
"""
import pathlib, subprocess, sys

SETS = {  # PRE SENSE WB GUARD GAP
    "anchored":        (2, 10, 20, 2, 0),
    "gap1":            (2, 10, 20, 2, 1),
    "full_read_pulse": (2, 20, 20, 2, 0),
    "fast":            (1, 5, 5, 1, 0),
    "mismatch":        (2, 10, 40, 2, 0),
    "huge":            (2, 10, 150, 2, 0),   # deliberately infeasible against the sourced intervals
}
LAT = 1
here = pathlib.Path(__file__).resolve().parent
basis, name = sys.argv[1], sys.argv[2]
if name in SETS:
    pre, sense, wb, guard, gap = SETS[name]
else:
    pre, sense, wb, guard, gap = (int(x) for x in name.split(","))
base = {}
for line in subprocess.run([sys.executable, "-I", str(here.parent / "control-integration" / "params.py"), basis],
                           check=True, capture_output=True, text=True).stdout.split():
    k, v = line.split("=")
    base[k] = int(v)
n, sg, interval = base["N_ROWS"], base["GUARD"], base["INTERVAL"]
d_ref = pre + sense + wb + guard + 3 * gap
d_rd = pre + sense + guard + 2 * gap
d_wr = wb + guard + gap
t_row = d_ref + LAT
t_acc = max(d_rd, d_wr) + LAT
g_eff = sg + n + 1
min_ivl = n * t_row + t_acc + g_eff
settle = (t_acc + 1) + n * (t_row + 1) + sg
import os
infeasible = not (min_ivl <= interval <= 0xFFFF)
if infeasible and not os.environ.get("COUPLED_FORCE"):   # COUPLED_FORCE=1: print anyway (bench negative controls)
    sys.exit(f"INFEASIBLE: set={name} MIN_INTERVAL={min_ivl} INTERVAL={interval} (T_ROW={t_row} T_ACC={t_acc})")
for k, v in (("P_PRE", pre), ("P_SENSE", sense), ("P_WB", wb), ("P_GUARD", guard), ("GAP", gap),
             ("INTERVAL", interval), ("N_ROWS", n), ("SCHED_GUARD", sg), ("GUARD_EFF", g_eff),
             ("D_REF", d_ref), ("D_RD", d_rd), ("D_WR", d_wr), ("LAT", LAT),
             ("T_ROW", t_row), ("T_ACC", t_acc), ("MIN_INTERVAL", min_ivl), ("T_SETTLE", settle)):
    print(f"{k}={v}")
