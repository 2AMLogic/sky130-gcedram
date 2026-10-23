#!/usr/bin/env bash
# Mutation check: the testbench must PASS on the real scheduler and FAIL on
# every deliberately broken copy. Exit 0 only if all mutants are killed.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
source "$here/../ci/mutation_lib.sh"
mutation_init
mutation_baseline "$here/run_tests.sh"
declare -A M
M[never_urgent]='s/[|][|] \(age >= URGENT_AGE\);/|| 1'"'"'b0;/'
M[urgent_ignores_ext_op]='s|URGENT_AGE = INTERVAL - T_ROW - T_ACC - GUARD|URGENT_AGE = INTERVAL - T_ROW|'
M[urgent_late_by_guard]='s|URGENT_AGE = INTERVAL - T_ROW - T_ACC - GUARD|URGENT_AGE = INTERVAL - T_ROW - T_ACC + 8|'
M[ptr_skips_rows]='s/ptr [+] 1;  *\/\/ MUT_PTR/ptr + 2;/'
M[never_refresh]='s|op_row <= ptr; cnt <= T_ROW;|op_row <= ptr; cnt <= 0;|'
# eager refresh is a latency/idle-policy optimisation, not a safety property:
# disabling it is an equivalent mutant for the deadline invariant, so it is not listed.
mutant_run() { "$here/run_tests.sh" "$1" >"$2" 2>&1; }
mutation_sed_check "$here/refresh_sched.v"
