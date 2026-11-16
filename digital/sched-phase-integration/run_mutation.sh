#!/usr/bin/env bash
# Mutation check (issue #135): the integration scoreboard must PASS the real
# modules and FAIL (with a VIOLATION) on every deliberately broken variant.
#   adapter mutants  : dropped launch, wrong row, duplicated start
#   sequencer mutants (sed copies of phase_seq.v): early completion variants
# The tmp dir, baseline gate and killed/SURVIVED verdict come from the shared
# harness; this script owns its two mutant loops (the caller-owned-loop case
# documented at digital/ci/mutation_lib.sh:15-18).
# Exit 0 only if every mutant is killed and every sed really changed the source.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
source "$here/../ci/mutation_lib.sh"
seqsrc="$here/../phase-control/phase_seq.v"
mutation_init
mutation_baseline env SCENS=1 TIMINGS=anchored "$here/run_tests.sh"
rc=0
# adapter mutants: name MUT MUT_N   (launch 7 is a reset-sweep REFRESH, 60 a traffic op)
for m in "dropped_launch_refresh 1 7" "dropped_launch_access 1 60" \
         "wrong_row_refresh 2 7" "wrong_row_access 2 60" \
         "duplicated_start_refresh 3 7" "duplicated_start_access 3 60"; do
  read -r name mut n <<< "$m"
  MUT="$mut" MUT_N="$n" SCENS="1" TIMINGS="anchored" "$here/run_tests.sh" >"$tmp/$name.log" 2>&1
  mutation_verdict "$name" "$tmp/$name.log" $? '^VIOLATION'
done
# sequencer mutants (early completion / shortened phases)
declare -A M
M[early_completion_guard_short]='s/default: dur = P_GUARD;/default: dur = P_GUARD - 1;/'
M[early_completion_sense_short]='s/S_SENSE: dur = P_SENSE;/S_SENSE: dur = P_SENSE - 1;/'
M[early_completion_no_guard_after_wb]='s/S_WB:    next_phase = S_GUARD;/S_WB:    next_phase = S_IDLE;/'
M[early_completion_writeback_short]='s/S_WB:    dur = P_WB;/S_WB:    dur = P_WB - 3;/'
for name in $(printf '%s\n' "${!M[@]}" | sort); do
  sed -E "${M[$name]}" "$seqsrc" > "$tmp/$name.v"
  if cmp -s "$tmp/$name.v" "$seqsrc"; then echo "MUTANT $name: sed did not change the source"; rc=1; continue; fi
  SEQ_SRC="$tmp/$name.v" SCENS="1" TIMINGS="anchored" "$here/run_tests.sh" >"$tmp/$name.log" 2>&1
  mutation_verdict "$name" "$tmp/$name.log" $? '^VIOLATION'
done
[ "$rc" = 0 ] && echo "MUTATION CHECK PASS" || echo "MUTATION CHECK FAIL"
exit "$rc"
