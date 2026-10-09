#!/usr/bin/env bash
# Runs scenarios (a) idle (b) saturating (c) seeded random with iverilog.
# usage: run_tests.sh [src.v]   (src override is used by run_mutation.sh)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
src="${1:-$here/refresh_sched.v}"
build="$(mktemp -d)"; trap 'rm -rf "$build"' EXIT
fail=0
for basis in ratified extracted; do
  interval="$(python3 -I "$here/params.py" "$basis")"
  for sc in 0 1 2; do
    iverilog -g2012 -o "$build/t.vvp" -P tb_refresh_sched.INTERVAL="$interval" \
      -P tb_refresh_sched.SCENARIO="$sc" "$src" "$here/tb_refresh_sched.v"
    out="$(vvp "$build/t.vvp")"
    echo "[$basis] $(echo "$out" | grep -E 'RESULT|VIOLATION|LIVENESS' | head -3)"
    echo "$out" | grep -q 'TB_RESULT: PASS' || fail=1
  done
done
[ "$fail" = 0 ] && echo "ALL PASS" || echo "SOME FAIL"
exit "$fail"
