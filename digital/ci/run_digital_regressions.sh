#!/usr/bin/env bash
# Serial behavioral regression driver used by CI (and runnable locally).
# Runs every suite even after a failure so all logs exist; exits non-zero if
# any suite failed. usage: run_digital_regressions.sh LOGDIR
set -uo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
logs="${1:?usage: run_digital_regressions.sh LOGDIR}"
mkdir -p "$logs"
{ iverilog -V | head -1; vvp -V | head -1; python3 --version; } 2>&1 | tee "$logs/versions.txt"
fail=0
run() {  # name, command...
  local name="$1"; shift
  echo "::group::$name"
  local t0=$SECONDS
  "$@" 2>&1 | tee "$logs/$name.log"
  local rc=${PIPESTATUS[0]}
  echo "$name: exit=$rc duration=$((SECONDS - t0))s" | tee -a "$logs/summary.txt"
  echo "::endgroup::"
  [ "$rc" -eq 0 ] || fail=1
}
run refresh-scheduler-tests "$root/digital/refresh-scheduler/run_tests.sh"
run refresh-scheduler-mutation "$root/digital/refresh-scheduler/run_mutation.sh"
run spi-control-tests "$root/digital/spi-control/run_tests.sh"
run spi-control-mutation "$root/digital/spi-control/run_mutation.sh"
# Includes its own mutation suite (run_mutation.sh) by default.
run control-integration "$root/digital/control-integration/run_tests.sh"
echo "overall: $([ $fail -eq 0 ] && echo PASS || echo FAIL)" | tee -a "$logs/summary.txt"
exit $fail
