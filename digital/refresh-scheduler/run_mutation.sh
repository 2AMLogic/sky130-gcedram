#!/usr/bin/env bash
# Mutation check: the testbench must PASS on the real scheduler and FAIL on
# every deliberately broken copy. Exit 0 only if all mutants are killed.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
"$here/run_tests.sh" >/dev/null || { echo "baseline does not pass"; exit 2; }
echo "baseline: PASS"
declare -A M
M[never_urgent]='s/[|][|] \(age >= URGENT_AGE\);/|| 1'"'"'b0;/'
M[urgent_ignores_ext_op]='s|URGENT_AGE = INTERVAL - T_ROW - T_ACC - GUARD|URGENT_AGE = INTERVAL - T_ROW|'
M[urgent_late_by_guard]='s|URGENT_AGE = INTERVAL - T_ROW - T_ACC - GUARD|URGENT_AGE = INTERVAL - T_ROW - T_ACC + 8|'
M[ptr_skips_rows]='s/ptr [+] 1;  *\/\/ MUT_PTR/ptr + 2;/'
M[never_refresh]='s|op_row <= ptr; cnt <= T_ROW;|op_row <= ptr; cnt <= 0;|'
# eager refresh is a latency/idle-policy optimisation, not a safety property:
# disabling it is an equivalent mutant for the deadline invariant, so it is not listed.
rc=0
for name in "${!M[@]}"; do
  sed -E "${M[$name]}" "$here/refresh_sched.v" > "$tmp/$name.v"
  if cmp -s "$tmp/$name.v" "$here/refresh_sched.v"; then echo "MUTANT $name: sed did not change the source"; rc=1; continue; fi
  if "$here/run_tests.sh" "$tmp/$name.v" >"$tmp/$name.log" 2>&1; then
    echo "MUTANT $name: SURVIVED (testbench is too weak)"; rc=1
  else
    echo "MUTANT $name: killed"
  fi
done
[ "$rc" = 0 ] && echo "MUTATION CHECK PASS" || echo "MUTATION CHECK FAIL"
exit "$rc"
