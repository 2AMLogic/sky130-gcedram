#!/usr/bin/env bash
# Mutation check: TB must PASS on the real slave and FAIL on every broken copy.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
"$here/run_tests.sh" >/dev/null || { echo "baseline does not pass"; exit 2; }
echo "baseline: PASS"
declare -A M
M[no_bound_check]='s/if [(]val == 16.d0 [|][|] val > MAX_INTERVAL[)]/if (1'"'"'b0)/'
M[bound_off_by_one]='s/val > MAX_INTERVAL/val >= MAX_INTERVAL/'
M[zero_allowed]='s/val == 16.d0 [|][|] //'
M[accept_long_frame]='s/if [(]cnt != 5.d16[)] nst\[1\] = 1.b1;/if (cnt < 5'"'"'d16) nst[1] = 1'"'"'b1;/'
M[no_frame_error]='s/if [(]cnt != 5.d16[)] nst\[1\] = 1.b1;/if (cnt != 5'"'"'d16) nst[1] = 1'"'"'b0;/'
M[clear_cmd_noop]='s/8.h02: nst = 5.b0;/8'"'"'h02: nst = nst;/'
M[read_latch_early]='s/else if [(]cnt == 5.d8[)] tx/else if (cnt == 5'"'"'d7) tx/'
M[poisoned_shadow]='s/nst\[0\] = 1.b1; sh_l <= ivl_l;/nst[0] = 1'"'"'b1;/'
rc=0
for name in "${!M[@]}"; do
  sed -E "${M[$name]}" "$here/spi_slave.v" > "$tmp/$name.v"
  if cmp -s "$tmp/$name.v" "$here/spi_slave.v"; then echo "MUTANT $name: sed did not change the source"; rc=1; continue; fi
  if "$here/run_tests.sh" "$tmp/$name.v" >"$tmp/$name.log" 2>&1; then
    echo "MUTANT $name: SURVIVED (testbench is too weak)"; rc=1
  else
    echo "MUTANT $name: killed"
  fi
done
[ "$rc" = 0 ] && echo "MUTATION CHECK PASS" || echo "MUTATION CHECK FAIL"
exit "$rc"
