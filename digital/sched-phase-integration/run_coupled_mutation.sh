#!/usr/bin/env bash
# Mutation check for the coupled configuration (issue #138): the coupled bench
# must PASS the real RTL and FAIL on every deliberately broken copy.
#   premature completion : scheduler completes one cycle early; sequencer phase
#                          longer than the budget (stale budget after a phase change);
#                          derivation drops the launch latency / ignores WRITE length
#   ignored launches     : adapter drops a launch; sequencer silently ignores REFRESH starts
#   stale floor wiring   : scheduler floor hard-coded; gc_ctrl_top floor hard-coded;
#                          SPI floor not passed; decision guard stale; urgent/eager
#                          thresholds hard-coded to the 34-cycle standalone defaults
# Mutants are exact-string replacements (must match exactly once) applied to a
# private copy of the digital sources (run_coupled.sh DIG overlay); nothing in
# the repository is modified. Scheduler-level mutants are also run with the
# configuration gate bypassed so the dynamic monitors are shown to catch them alone.
# Exit 0 only if the baseline passes and every mutant is killed.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export BASES=ratified
SETS=anchored SCENS="1" "$here/run_coupled.sh" --no-negative >"$tmp/base.log" 2>&1 || { cat "$tmp/base.log"; echo "baseline does not pass"; exit 2; }
echo "baseline: PASS"
rc=0
overlay() {  # dir
  mkdir -p "$1/control-integration" "$1/phase-control" "$1/spi-control" "$1/sched-phase-integration"
  cp "$here"/../control-integration/*.v "$1/control-integration/"
  cp "$here"/../phase-control/phase_seq.v "$1/phase-control/"
  cp "$here"/../spi-control/spi_slave.v "$1/spi-control/"
  cp "$here"/launch_adapter.v "$here"/coupled_top.v "$1/sched-phase-integration/"
}
verdict() {  # name log status
  if [ "$3" = 0 ]; then echo "MUTANT $1: SURVIVED (bench is too weak)"; rc=1
  elif grep -qE '^(VIOLATION|CONFIG_REJECT)' "$2"; then echo "MUTANT $1: killed (first: $(grep -m1 -E '^(VIOLATION|CONFIG_REJECT)' "$2"))"
  else echo "MUTANT $1: failed WITHOUT a finding (compile error?)"; rc=1; fi
}
# name ~ file (relative to digital/) ~ original ~ mutated ~ set ~ scens ~ gate-bypass-too (1/0)
mutants=(
  "sched_completes_early~control-integration/refresh_sched_rt.v~if (cnt == 1) begin~if (cnt == 2) begin~anchored~1~1"
  "sequencer_longer_than_budget~phase-control/phase_seq.v~S_SENSE: dur = P_SENSE;~S_SENSE: dur = P_SENSE + 1;~anchored~1~1"
  "sequencer_guard_longer_than_budget~phase-control/phase_seq.v~default: dur = P_GUARD;~default: dur = P_GUARD + 1;~gap1~1~1"
  "sequencer_ignores_refresh_start~phase-control/phase_seq.v~else if (kind == K_REF || kind == K_READ) begin~else if (kind == K_READ) begin~anchored~1~1"
  "derivation_drops_latency~sched-phase-integration/coupled_top.v~localparam integer T_ROW_D = D_REF + LAT;~localparam integer T_ROW_D = D_REF;~anchored~1~1"
  "derivation_ignores_write_length~sched-phase-integration/coupled_top.v~localparam integer D_ACC   = (D_RD > D_WR) ? D_RD : D_WR;~localparam integer D_ACC   = D_RD;~anchored~1~1"
  "stale_guard_without_decision_cycle~sched-phase-integration/coupled_top.v~GUARD + N_ROWS + 1;~GUARD;~anchored~2~1"
  "stale_floor_in_scheduler~control-integration/refresh_sched_rt.v~localparam integer MIN_INTERVAL = N_ROWS * T_ROW + T_ACC + GUARD;~localparam integer MIN_INTERVAL = N_ROWS * 34 + 34 + 2;~anchored~2~1"
  "stale_floor_in_scheduler_fast~control-integration/refresh_sched_rt.v~localparam integer MIN_INTERVAL = N_ROWS * T_ROW + T_ACC + GUARD;~localparam integer MIN_INTERVAL = N_ROWS * 34 + 34 + 2;~fast~2~1"
  "stale_floor_in_ctrl_top~control-integration/gc_ctrl_top.v~localparam integer MIN_INTERVAL = N_ROWS * T_ROW + T_ACC + GUARD;~localparam integer MIN_INTERVAL = N_ROWS * 34 + 34 + 2;~anchored~1~0"
  "spi_floor_not_passed~control-integration/gc_ctrl_top.v~.MIN_INTERVAL(MIN_INTERVAL)~.MIN_INTERVAL(1)~anchored~1~0"
  "stale_urgent_threshold~control-integration/refresh_sched_rt.v~wire [31:0] urgent_age = ivl_eff - T_ROW - T_ACC - GUARD;~wire [31:0] urgent_age = ivl_eff - 34 - 34 - 2;~mismatch~1 2~1"
)
run_mut() {  # d set scens chk log
  DIG="$1" SETS="$2" SCENS="$3" CHECK_CFG="$4" "$here/run_coupled.sh" --no-negative >"$5" 2>&1
}
for m in "${mutants[@]}"; do
  IFS='~' read -r name file orig mut set scens bypass <<< "$m"
  d="$tmp/$name"; overlay "$d"
  if ! python3 -I -c '
import sys, pathlib
p = pathlib.Path(sys.argv[1]); s = p.read_text()
if s.count(sys.argv[2]) != 1: sys.exit(1)
p.write_text(s.replace(sys.argv[2], sys.argv[3]))' "$d/$file" "$orig" "$mut"; then
    echo "MUTANT $name: anchor not found exactly once in $file"; rc=1; continue
  fi
  run_mut "$d" "$set" "$scens" 1 "$d/log"; verdict "$name (gate on)" "$d/log" $?
  if [ "$bypass" = 1 ]; then
    run_mut "$d" "$set" "$scens" 0 "$d/log0"; verdict "$name (gate bypassed, dynamic monitors only)" "$d/log0" $?
  fi
done
# adapter mutants (bench fault injection): dropped launch of a sweep refresh and of an access
for m in "adapter_drops_refresh_launch 7" "adapter_drops_access_launch 60"; do
  read -r name n <<< "$m"
  MUT=1 MUT_N="$n" SETS=anchored SCENS="1" "$here/run_coupled.sh" --no-negative >"$tmp/$name.log" 2>&1; verdict "$name" "$tmp/$name.log" $?
done
[ "$rc" = 0 ] && echo "MUTATION CHECK PASS" || echo "MUTATION CHECK FAIL"
exit "$rc"
