#!/usr/bin/env bash
# Runs the phase_seq bench for the anchored and fast ASSUMPTION scenarios, each
# with GAP=0 and GAP=1. usage: run_tests.sh [src.v]  (override used by mutation)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
src="${1:-$here/phase_seq.v}"
build="$(mktemp -d)"; trap 'rm -rf "$build"' EXIT
fail=0
# name pre sense wb guard   (from sim/refresh-overhead/README.md scenario table)
for sc in "anchored 2 10 20 2" "fast 1 5 5 1"; do
  set -- $sc
  for gap in 0 1; do
    iverilog -g2012 -o "$build/t.vvp" -P tb_phase_seq.P_PRE="$2" -P tb_phase_seq.P_SENSE="$3" \
      -P tb_phase_seq.P_WB="$4" -P tb_phase_seq.P_GUARD="$5" -P tb_phase_seq.GAP="$gap" \
      "$src" "$here/tb_phase_seq.v"
    out="$(vvp "$build/t.vvp")"
    echo "[$1 gap=$gap]"
    echo "$out" | grep -E 'INFO: cycles|CONFLICT|VIOLATION|TB_RESULT' | head -${TB_LINES:-6}
    echo "$out" | grep -q 'TB_RESULT: PASS' || fail=1
  done
done
[ "$fail" = 0 ] && echo "ALL PASS" || echo "SOME FAIL"
exit "$fail"
