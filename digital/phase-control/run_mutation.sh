#!/usr/bin/env bash
# Mutation check: the bench must PASS on the real sequencer and FAIL on every
# deliberately broken copy. Exit 0 only if all mutants are killed and every sed
# really changed the source.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
source "$here/../ci/mutation_lib.sh"
mutation_init
mutation_baseline "$here/run_tests.sh"
declare -A M
M[precharge_overlaps_rwl]='s/(assign pre_en   = )\(st == S_PRE\);/\1(st == S_PRE) || (st == S_SENSE);/'
M[sense_before_rwl]='s/(assign sense_en = )\(st == S_SENSE\) && \(cnt == 0\);/\1(st == S_PRE) || ((st == S_SENSE) \&\& (cnt == 0));/'
M[wwl_overlaps_rwl]='s/(assign wwl_en   = )\(st == S_WB\);/\1(st == S_WB) || (st == S_SENSE);/'
M[wwl_overlaps_sense]='s/(assign wwl_en   = )\(st == S_WB\);/\1(st == S_WB) || ((st == S_SENSE) \&\& (cnt == 0));/'
M[writeback_before_sense_done]='s/(assign bl_drive = )\(st == S_WB\) [|][|]/\1(st == S_WB) || ((st == S_SENSE) \&\& (cnt == 0)) ||/'
M[refresh_drops_writeback]='s/\(k == K_REF\) \? S_WB : S_GUARD/1'"'"'b0 ? S_WB : S_GUARD/'
M[refresh_drops_precharge]='s/else if \(kind == K_REF [|][|] kind == K_READ\) begin/else if (kind == K_READ) begin/'
M[refresh_drops_sense]='s/S_PRE:   next_phase = S_SENSE;/S_PRE:   next_phase = (k == K_REF) ? S_WB : S_SENSE;/'
M[sense_window_one_short]='s/S_SENSE: dur = P_SENSE;/S_SENSE: dur = P_SENSE - 1;/'
M[bl_released_early]='s/\(kind_q != K_READ && \(st == S_GUARD/(1'"'"'b0 \&\& (st == S_GUARD/'
M[start_while_busy_ignored_unflagged]='s/if \(start\) start_ignored <= 1.b1;/if (0) start_ignored <= 1'"'"'b1;/'
M[done_never_pulses]='s/st <= S_IDLE; done <= 1.b1; end/st <= S_IDLE; end/'
MUT_SORT=1
MUT_KILL_PATTERN=VIOLATION
mutant_run() { "$here/run_tests.sh" "$1" >"$2" 2>&1; }
mutation_sed_check "$here/phase_seq.v"
