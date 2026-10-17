#!/usr/bin/env bash
# Mutation check: TB must PASS on the real slave and FAIL on every broken copy.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
source "$here/../ci/mutation_lib.sh"
mutation_init
mutation_baseline "$here/run_tests.sh"
declare -A M
M[no_bound_check]='s/if [(]val == 16.d0 [|][|] val > MAX_INTERVAL[)]/if (1'"'"'b0)/'
M[bound_off_by_one]='s/val > MAX_INTERVAL/val >= MAX_INTERVAL/'
M[zero_allowed]='s/val == 16.d0 [|][|] //'
M[accept_long_frame]='s/if [(]cnt != 5.d16[)] nst\[1\] = 1.b1;/if (cnt < 5'"'"'d16) nst[1] = 1'"'"'b1;/'
M[no_frame_error]='s/if [(]cnt != 5.d16[)] nst\[1\] = 1.b1;/if (cnt != 5'"'"'d16) nst[1] = 1'"'"'b0;/'
M[clear_cmd_noop]='s/8.h02: nst = 5.b0;/8'"'"'h02: nst = nst;/'
M[read_latch_early]='s/else if [(]cnt == 5.d8[)] tx/else if (cnt == 5'"'"'d7) tx/'
M[poisoned_shadow]='s/nst\[0\] = 1.b1; sh_l <= ivl_l;/nst[0] = 1'"'"'b1;/'
mutant_run() { "$here/run_tests.sh" "$1" >"$2" 2>&1; }
mutation_sed_check "$here/spi_slave.v"
