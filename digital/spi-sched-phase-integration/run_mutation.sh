#!/usr/bin/env bash
# Mutation check for the SPI -> scheduler -> sequencer integration (issue #146):
# the bench must PASS the real RTL and FAIL on every deliberately broken copy.
#   config-path mutants (the integrated boundary the standalone suites do not
#   cover end to end): SPI floor not passed / stale, SPI upper bound, enable /
#   interval / START_SWEEP not transferred, busy and status wiring, applied
#   interval ignored, data_lost / re-initialisation / refresh_ok logic, disable
#   not honoured, sweep short by rows;
#   timing mutants: wrapper decision guard stale, urgent threshold stale,
#   sequencer phase longer than the budget, sequencer ignores REFRESH starts.
# Mutants are exact-string replacements (must match exactly once) applied to a
# private copy of the digital sources (run_tests.sh DIG overlay); nothing in the
# repository is modified. Mutants that change a configuration value are also run
# with the pre-traffic gate bypassed so the dynamic scoreboard is shown to catch
# them alone. Not included: forcing cfg_xfer.pending low (the busy gap between the synchronised
# cs_n edge and the applied snapshot) is an EQUIVALENT mutant at the SPI boundary under the
# documented frame spacing (the next frame samples STATUS >= 8 sclk after cs_n falls, long after
# the gap), so no SPI-level bench can distinguish it; control-integration documents the gap.
# Exit 0 only if the baseline passes and every mutant is killed.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
one="ratified anchored 3700 130 3 1"
MATRIX="$one" "$here/run_tests.sh" --no-negative >"$tmp/base.log" 2>&1 || { cat "$tmp/base.log"; echo "baseline does not pass"; exit 2; }
echo "baseline: PASS"
rc=0
overlay() {  # dir
  mkdir -p "$1/control-integration" "$1/phase-control" "$1/spi-control" "$1/sched-phase-integration" "$1/spi-sched-phase-integration"
  cp "$here"/../control-integration/*.v "$1/control-integration/"
  cp "$here"/../phase-control/phase_seq.v "$1/phase-control/"
  cp "$here"/../spi-control/spi_slave.v "$1/spi-control/"
  cp "$here"/../sched-phase-integration/launch_adapter.v "$1/sched-phase-integration/"
  cp "$here"/spi_sched_phase_top.v "$1/spi-sched-phase-integration/"
}
verdict() {  # name log status
  if [ "$3" = 0 ]; then echo "MUTANT $1: SURVIVED (bench is too weak)"; rc=1
  elif grep -qE '^(FINDING|CONFIG_REJECT)' "$2"; then echo "MUTANT $1: killed (first: $(grep -m1 -E '^(FINDING|CONFIG_REJECT)' "$2"))"
  else echo "MUTANT $1: failed WITHOUT a finding (compile error?)"; rc=1; fi
}
# name ~ file (relative to digital/) ~ original ~ mutated ~ set ~ gate-bypass-too (1/0)
mutants=(
  "spi_floor_not_passed~control-integration/gc_ctrl_top.v~.MIN_INTERVAL(MIN_INTERVAL)~.MIN_INTERVAL(1)~anchored~1"
  "stale_floor_in_ctrl_top~control-integration/gc_ctrl_top.v~localparam integer MIN_INTERVAL = N_ROWS * T_ROW + T_ACC + GUARD;~localparam integer MIN_INTERVAL = N_ROWS * 34 + 34 + 2;~anchored~1"
  "xstatus_swapped~control-integration/gc_ctrl_top.v~{4'b0, cfg_reject, sweep_active, data_lost, refresh_ok}~{4'b0, cfg_reject, sweep_active, refresh_ok, data_lost}~anchored~0"
  "wrapper_stale_guard~spi-sched-phase-integration/spi_sched_phase_top.v~GUARD + N_ROWS + 1;~GUARD;~anchored~1"
  "xfer_drops_enable~control-integration/cfg_xfer.v~cfg_en       <= spi_en;~cfg_en <= 1'b1;~anchored~0"
  "xfer_drops_interval~control-integration/cfg_xfer.v~cfg_interval <= spi_ivl;~cfg_interval <= cfg_interval;~anchored~0"
  "xfer_drops_sweep~control-integration/cfg_xfer.v~cfg_sweep    <= (spi_tog != tog_seen);~cfg_sweep    <= 1'b0;~anchored~0"
  "sched_ignores_applied_interval~control-integration/refresh_sched_rt.v~ivl_eff <= cfg_interval;~ivl_eff <= ivl_eff;~anchored~0"
  "sched_never_sets_data_lost~control-integration/refresh_sched_rt.v~if (en_eff && !cfg_en) data_lost <= 1;~if (1'b0) data_lost <= 1;~anchored~0"
  "sched_no_reinit_sweep~control-integration/refresh_sched_rt.v~if (!en_eff && cfg_en) begin sw_left <= N_ROWS; reinit <= 1; end~if (!en_eff && cfg_en) begin reinit <= 1; end~anchored~0"
  "sched_refresh_ok_early~control-integration/refresh_sched_rt.v~assign refresh_ok   = en_eff && !reinit;~assign refresh_ok   = en_eff;~anchored~0"
  "sched_refreshes_while_disabled~control-integration/refresh_sched_rt.v~wire        urgent     = sweeping || (en_eff && (age >= urgent_age));~wire        urgent     = sweeping || (age >= urgent_age);~anchored~0"
  "sched_sweep_short~control-integration/refresh_sched_rt.v~if (cfg_sweep) begin sw_left <= N_ROWS; sw_forced <= 1; end~if (cfg_sweep) begin sw_left <= N_ROWS - 4; sw_forced <= 1; end~anchored~0"
  "sched_completes_early~control-integration/refresh_sched_rt.v~if (cnt == 1) begin~if (cnt == 2) begin~anchored~1"
  "stale_urgent_threshold~control-integration/refresh_sched_rt.v~wire [31:0] urgent_age = ivl_eff - T_ROW - T_ACC - GUARD;~wire [31:0] urgent_age = ivl_eff - 34 - 34 - 2;~mismatch~0"
  "spi_upper_bound_off_by_one~spi-control/spi_slave.v~val > MAX_INTERVAL~val >= MAX_INTERVAL~anchored~0"
  "spi_floor_off_by_one~spi-control/spi_slave.v~if (val < MIN_INTERVAL) val = 16'd0;~if (val <= MIN_INTERVAL) val = 16'd0;~anchored~0"
  "spi_sweep_accepted_while_busy~spi-control/spi_slave.v~if (busy_in) nst[3] = 1'b1; else sweep_tog~if (1'b0) nst[3] = 1'b1; else sweep_tog~anchored~0"
  "sequencer_longer_than_budget~phase-control/phase_seq.v~S_SENSE: dur = P_SENSE;~S_SENSE: dur = P_SENSE + 1;~anchored~0"
  "sequencer_ignores_refresh_start~phase-control/phase_seq.v~else if (kind == K_REF || kind == K_READ) begin~else if (kind == K_READ) begin~anchored~0"
)
run_mut() {  # dir set check log
  DIG="$1" MATRIX="ratified $2 3700 130 3 1" CHECK_CFG="$3" STOP_FIRST=1 "$here/run_tests.sh" --no-negative >"$4" 2>&1
}
for m in "${mutants[@]}"; do
  [ -n "${ONLY:-}" ] && ! [[ "$m" =~ $ONLY ]] && continue
  IFS='~' read -r name file orig mut set bypass <<< "$m"
  d="$tmp/$name"; overlay "$d"
  if ! python3 -I -c '
import sys, pathlib
p = pathlib.Path(sys.argv[1]); s = p.read_text()
if s.count(sys.argv[2]) != 1: sys.exit(1)
p.write_text(s.replace(sys.argv[2], sys.argv[3]))' "$d/$file" "$orig" "$mut"; then
    echo "MUTANT $name: anchor not found exactly once in $file"; rc=1; continue
  fi
  run_mut "$d" "$set" 1 "$d/log"; verdict "$name (gate on)" "$d/log" $?
  if [ "$bypass" = 1 ]; then
    run_mut "$d" "$set" 0 "$d/log0"; verdict "$name (gate bypassed, dynamic scoreboard only)" "$d/log0" $?
  fi
done
# adapter faults (bench fault injection): killed through the same scoreboard
for m in "adapter_drops_refresh_launch 1 7" "adapter_drops_access_launch 1 60" "adapter_wrong_row 2 7" "adapter_stretches_start 3 7"; do
  read -r name mu mn <<< "$m"
  MUT="$mu" MUT_N="$mn" MATRIX="$one" STOP_FIRST=1 "$here/run_tests.sh" --no-negative >"$tmp/$name.log" 2>&1; verdict "$name" "$tmp/$name.log" $?
done
[ "$rc" = 0 ] && echo "MUTATION CHECK PASS" || echo "MUTATION CHECK FAIL"
exit "$rc"
