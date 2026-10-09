#!/usr/bin/env bash
# Mutation check: the bench must PASS on the real sequencer and FAIL on every
# deliberately broken copy. Exit 0 only if all mutants are killed and every sed
# really changed the source.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
"$here/run_tests.sh" >/dev/null || { echo "baseline does not pass"; exit 2; }
echo "baseline: PASS"
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
rc=0
for name in $(printf '%s\n' "${!M[@]}" | sort); do
  sed -E "${M[$name]}" "$here/phase_seq.v" > "$tmp/$name.v"
  if cmp -s "$tmp/$name.v" "$here/phase_seq.v"; then echo "MUTANT $name: sed did not change the source"; rc=1; continue; fi
  if "$here/run_tests.sh" "$tmp/$name.v" >"$tmp/$name.log" 2>&1; then
    echo "MUTANT $name: SURVIVED (testbench is too weak)"; rc=1
  elif grep -q 'VIOLATION' "$tmp/$name.log"; then
    echo "MUTANT $name: killed ($(grep -c VIOLATION "$tmp/$name.log") violations shown)"
  else
    echo "MUTANT $name: failed WITHOUT a bench violation (compile error?)"; rc=1
  fi
done
[ "$rc" = 0 ] && echo "MUTATION CHECK PASS" || echo "MUTATION CHECK FAIL"
exit "$rc"
