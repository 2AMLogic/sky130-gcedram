#!/usr/bin/env bash
# Scheduler -> phase-sequencer integration matrix (issue #135). Behavioral.
# Runs every scenario (0 isolated, 1 back-to-back, 2 refresh arbitration,
# 3 config transitions, 4 reset interruption) for every phase-timing set and
# checks the bench PASSes with the EXPECTED conflict outcome:
#   timing set        phase durations            LOST  SKEW
#   anchored          PRE2 SENSE10 WB20 GUARD2    no    yes  (1-cycle observation skew)
#   gap1              anchored + GAP=1            yes   yes  (REFRESH 37 > T_ROW 34)
#   full_read_pulse   PRE2 SENSE20 WB20 GUARD2    yes   yes  (REFRESH 44)
#   fast              PRE1 SENSE5 WB5 GUARD1      no    no   (REFRESH 12, slack)
#   mismatch          PRE2 SENSE10 WB40 GUARD2    yes   yes  (deliberate; REFRESH 54, WRITE 42 > T_ACC)
# CONFLICT lines are characterization output, not failures; VIOLATION fails.
# Environment (used by run_mutation.sh): SEQ_SRC (phase_seq source override),
# SCENS, TIMINGS (space lists), MUT, MUT_N, VERBOSE.
# usage: run_tests.sh
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
sched="$here/../control-integration/refresh_sched_rt.v"
seq="${SEQ_SRC:-$here/../phase-control/phase_seq.v}"
scens="${SCENS:-0 1 2 3 4}"
timings="${TIMINGS:-anchored gap1 full_read_pulse fast mismatch}"
mut="${MUT:-0}"; mut_n="${MUT_N:-7}"
build="$(mktemp -d)"; trap 'rm -rf "$build"' EXIT
fail=0
# name PRE SENSE WB GUARD GAP EXP_LOST EXP_SKEW
declare -A T=(
  [anchored]="2 10 20 2 0 0 1"
  [gap1]="2 10 20 2 1 1 1"
  [full_read_pulse]="2 20 20 2 0 1 1"
  [fast]="1 5 5 1 0 0 0"
  [mismatch]="2 10 40 2 0 1 1"
)
for tm in $timings; do
  read -r pre sense wb guard gap elost eskew <<< "${T[$tm]}"
  for sc in $scens; do
    iverilog -g2012 -s tb_sched_phase -o "$build/t.vvp" -DVERBOSE="${VERBOSE:-0}" \
      -P tb_sched_phase.SCEN="$sc" -P tb_sched_phase.P_PRE="$pre" -P tb_sched_phase.P_SENSE="$sense" \
      -P tb_sched_phase.P_WB="$wb" -P tb_sched_phase.P_GUARD="$guard" -P tb_sched_phase.GAP="$gap" \
      -P tb_sched_phase.EXP_LOST="$elost" -P tb_sched_phase.EXP_SKEW="$eskew" \
      -P tb_sched_phase.MUT="$mut" -P tb_sched_phase.MUT_N="$mut_n" \
      "$here/launch_adapter.v" "$here/sched_phase_top.v" "$here/tb_sched_phase.v" "$sched" "$seq" \
      || { echo "[$tm scen=$sc] COMPILE FAILED"; fail=1; continue; }
    out="$(vvp -n "$build/t.vvp")"
    echo "[$tm scen=$sc]"
    echo "$out" | grep -E '^(KIND|CONFLICT|VIOLATION|OPTIME|TB_RESULT)'
    echo "$out" | grep -q '^TB_RESULT: PASS' || fail=1
  done
done
[ "$fail" = 0 ] && echo "ALL PASS" || echo "SOME FAIL"
exit "$fail"
