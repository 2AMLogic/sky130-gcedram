#!/usr/bin/env bash
# One integration-bench run.
# usage: sim_one.sh BASIS SCLK_HALF_PS PHASE_PS TRAFFIC NEG_SPACING
#   BASIS        ratified | extracted   (interval read via params.py, not retyped)
#   TRAFFIC      0 none, 1 saturating reads, 2 seeded random
#   NEG_SPACING  1 = deliberately violate the frame spacing (negative control)
# env SRC_DIR  : directory holding (possibly mutated) cfg_xfer.v,
#                refresh_sched_rt.v, gc_ctrl_top.v  (default: this directory)
# Prints the RESULT/ERRORS/TB_RESULT lines plus the first failure messages.
# Exit 0 only on TB_RESULT: PASS.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
basis="$1"; half="$2"; phase="$3"; traffic="$4"; neg="$5"
src="${SRC_DIR:-$here}"
spi="$here/../spi-control/spi_slave.v"
eval "$(python3 -I "$here/params.py" "$basis")"
build="$(mktemp -d)"; trap 'rm -rf "$build"' EXIT
tb=tb_ctrl_integ
iverilog -g2012 -s "$tb" -o "$build/t.vvp" \
  -P "$tb.INTERVAL=$INTERVAL" -P "$tb.MIN_INTERVAL=$MIN_INTERVAL" \
  -P "$tb.N_ROWS=$N_ROWS" -P "$tb.T_ROW=$T_ROW" -P "$tb.T_ACC=$T_ACC" -P "$tb.GUARD=$GUARD" \
  -P "$tb.SCLK_HALF_PS=$half" -P "$tb.PHASE_PS=$phase" -P "$tb.TRAFFIC=$traffic" \
  -P "$tb.NEG_SPACING=$neg" \
  "$spi" "$src/cfg_xfer.v" "$src/refresh_sched_rt.v" "$src/gc_ctrl_top.v" "$here/tb_ctrl_integ.v"
vvp -n "$build/t.vvp" > "$build/out" 2>&1 || true
awk '/^(FAIL|VIOLATION|LOST|SPURIOUS|INCOMPLETE|REARM|REFRESH_OK|UNNOTICED|DATA_LOST|NOT APPLIED|PARTIAL|SWEEP|LIVENESS|COVERAGE)/ && n < 4 {print; n++}' "$build/out"
grep -E '^(RESULT|ERRORS|TB_RESULT)' "$build/out"
grep -q '^TB_RESULT: PASS' "$build/out"
