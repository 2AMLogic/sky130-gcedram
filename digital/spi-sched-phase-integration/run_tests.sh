#!/usr/bin/env bash
# SPI -> scheduler -> launch adapter -> phase sequencer integration (issue #146).
# Behavioral, iverilog only. The ONLY scheduler is the one inside gc_ctrl_top
# (SPI slave + cfg_xfer + refresh_sched_rt); it drives the unchanged launch
# adapter and phase_seq through spi_sched_phase_top.v.
#   1. positive matrix: sourced interval bases x phase-duration sets x SPI/clk
#      relationships; every run must PASS (independent per-row completion
#      scoreboard on the sequencer, real SPI transactions under saturated
#      foreground traffic);
#   2. infeasible combination (set 'huge') must be rejected;
#   3. negative controls (must FAIL for the intended reason, first FINDING line
#      asserted): dropped launch, underbudgeted phase duration (T_ROW/T_ACC one
#      below the derived value, through the configuration gate and with the
#      gate bypassed), legacy floor without the decision cycle.
# Environment: DIG (digital/ tree to take RTL from; default this repo, used by
# run_mutation.sh), MATRIX (override of positive-matrix entries 'basis set half_ps
# phase_ps traffic fast', ';'-separated), CHECK_CFG (0 bypasses the pre-traffic gate in the
# positive matrix), STOP_FIRST (1 ends each run at the first finding), MUT, MUT_N.
# usage: run_tests.sh [--no-negative]
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
dig="${DIG:-$here/..}"
build="$(mktemp -d)"; trap 'rm -rf "$build"' EXIT
srcs=("$dig/sched-phase-integration/launch_adapter.v" "$dig/spi-sched-phase-integration/spi_sched_phase_top.v"
      "$here/tb_spi_sched_phase.v" "$dig/control-integration/refresh_sched_rt.v" "$dig/control-integration/gc_ctrl_top.v"
      "$dig/control-integration/cfg_xfer.v" "$dig/spi-control/spi_slave.v" "$dig/phase-control/phase_seq.v")
[ -f "$dig/spi-sched-phase-integration/spi_sched_phase_top.v" ] || srcs[1]="$here/spi_sched_phase_top.v"
fail=0
params_py="$here/../sched-phase-integration/coupled_params.py"

# sclk half period (ps) / master phase offset (ps) vs the 1 ns clk:
#   3700/130 sclk slower than clk, arbitrary phase   370/610 sclk faster than clk
#   500/0 same rate, SPI edges coincide with clk     10000/500 slow SPI (~340 clk per frame)
#   1300/870 intermediate ratio
default_matrix="ratified anchored 3700 130 3 0;ratified anchored 370 610 3 1;ratified anchored 500 0 3 1;ratified anchored 10000 500 1 1;ratified anchored 1300 870 3 1;\
extracted anchored 3700 130 3 1;extracted anchored 500 0 3 1;ratified gap1 3700 130 3 1;ratified fast 370 610 3 1;ratified full_read_pulse 1300 870 3 1;extracted mismatch 3700 130 3 1"
matrix="${MATRIX:-$default_matrix}"

# run_one BASIS SET HALF PHASE TRAFFIC FAST CHECK_CFG STOP_FIRST TROW_X TACC_X GUARD_X MUT MUT_N
# prints the key result lines; returns 0 on TB_RESULT: PASS
run_one() {
  local basis="$1" set="$2" half="$3" ph="$4" tr="$5" fastm="$6" chk="$7" stop="$8" trx="$9" tax="${10}" gx="${11}" mut="${12}" mutn="${13}" params
  params="$(COUPLED_FORCE=1 python3 -I "$params_py" "$basis" "$set")" || { echo "[$basis $set] PARAMS FAILED"; return 2; }
  eval "$params"
  iverilog -g2012 -s tb_spi_sched_phase -o "$build/t.vvp" \
    -P tb_spi_sched_phase.P_PRE="$P_PRE" -P tb_spi_sched_phase.P_SENSE="$P_SENSE" \
    -P tb_spi_sched_phase.P_WB="$P_WB" -P tb_spi_sched_phase.P_GUARD="$P_GUARD" -P tb_spi_sched_phase.GAP="$GAP" \
    -P tb_spi_sched_phase.N_ROWS="$N_ROWS" -P tb_spi_sched_phase.INTERVAL="$INTERVAL" -P tb_spi_sched_phase.GUARD="$SCHED_GUARD" \
    -P tb_spi_sched_phase.PY_D_REF="$D_REF" -P tb_spi_sched_phase.PY_D_RD="$D_RD" -P tb_spi_sched_phase.PY_D_WR="$D_WR" \
    -P tb_spi_sched_phase.PY_T_ROW="$T_ROW" -P tb_spi_sched_phase.PY_T_ACC="$T_ACC" -P tb_spi_sched_phase.PY_GUARD_EFF="$GUARD_EFF" \
    -P tb_spi_sched_phase.PY_MIN="$MIN_INTERVAL" -P tb_spi_sched_phase.PY_SETTLE="$T_SETTLE" -P tb_spi_sched_phase.LAT="$LAT" \
    -P tb_spi_sched_phase.SCLK_HALF_PS="$half" -P tb_spi_sched_phase.PHASE_PS="$ph" -P tb_spi_sched_phase.TRAFFIC="$tr" \
    -P tb_spi_sched_phase.FAST="$fastm" -P tb_spi_sched_phase.CHECK_CFG="$chk" -P tb_spi_sched_phase.STOP_FIRST="$stop" \
    -P tb_spi_sched_phase.T_ROW_X="$trx" -P tb_spi_sched_phase.T_ACC_X="$tax" -P tb_spi_sched_phase.GUARD_X="$gx" \
    -P tb_spi_sched_phase.MUT="$mut" -P tb_spi_sched_phase.MUT_N="$mutn" \
    "${srcs[@]}" || { echo "[$basis $set] COMPILE FAILED"; return 2; }
  vvp -n "$build/t.vvp" > "$build/out" 2>&1
  grep -E '^(CONFIG|FINDING|OBS|SUMMARY|TB_RESULT|refresh_sched_rt|coupled_top)' "$build/out" | head -${LINES_MAX:-16}
  grep -q '^TB_RESULT: PASS' "$build/out"
}

echo "== 1. SPI -> scheduler -> sequencer positive matrix =="
IFS=';' read -ra entries <<< "$matrix"
for e in "${entries[@]}"; do
  read -r basis set half ph tr fastm <<< "$e"
  echo "[$basis $set sclk_half_ps=$half phase_ps=$ph traffic=$tr fast=$fastm]"
  run_one "$basis" "$set" "$half" "$ph" "$tr" "$fastm" "${CHECK_CFG:-1}" "${STOP_FIRST:-0}" 0 0 0 "${MUT:-0}" "${MUT_N:-7}" || fail=1
done

if [ "${1:-}" != "--no-negative" ]; then
  echo "== 2. infeasible combination must be rejected =="
  for basis in ratified extracted; do
    if python3 -I "$params_py" "$basis" huge >/dev/null 2>"$build/err"; then
      echo "[$basis huge] python derivation ACCEPTED an infeasible combination"; fail=1
    else
      echo "[$basis huge] python: $(cat "$build/err")"
    fi
    out="$(LINES_MAX=6 run_one "$basis" huge 3700 130 3 1 1 1 0 0 0 0 7 2>&1)"; rc=$?
    echo "$out" | sed "s/^/[$basis huge bench] /"
    if [ "$rc" -ne 0 ] && echo "$out" | grep -qE 'INFEASIBLE|CONFIG_REJECT: infeasible'; then
      echo "[$basis huge bench] expected rejection observed"
    else
      echo "[$basis huge bench] INFEASIBLE COMBINATION WAS NOT REJECTED"; fail=1
    fi
  done

  echo "== 3. negative controls (must FAIL for the intended reason) =="
  # name|set|trow_x|tacc_x|guard_x|mut|mut_n|gate|first-finding regex
  neg=(
    "dropped_refresh_launch|anchored|0|0|0|1|7|1|^FINDING DROPPED_LAUNCH"
    "dropped_access_launch|anchored|0|0|0|1|60|1|^FINDING DROPPED_LAUNCH"
    "dropped_refresh_launch_gap1|gap1|0|0|0|1|20|1|^FINDING DROPPED_LAUNCH"
    "wrong_row_launch|anchored|0|0|0|2|7|1|^FINDING (ROW_UNSTABLE|REFRESH_ORDER)"
    "stretched_start|anchored|0|0|0|3|7|1|^FINDING START_IGNORED"
    "row_budget_minus1|anchored|34|0|0|0|7|0|^FINDING BUDGET_UNDER"
    "row_budget_minus1_gap1|gap1|37|0|0|0|7|0|^FINDING BUDGET_UNDER"
    "acc_budget_minus1|anchored|0|22|0|0|7|0|^FINDING BUDGET_UNDER"
    "acc_budget_minus1_mismatch|mismatch|0|42|0|0|7|0|^FINDING BUDGET_UNDER"
    "stale34_full_read_pulse|full_read_pulse|34|34|0|0|7|0|^FINDING BUDGET_UNDER"
    "legacy_floor_no_decision_cycle|anchored|0|0|2|0|7|0|^FINDING (CHECK_ivl_[lh]_readback|CHECK_err_range_flag|DEADLINE)"
  )
  for n in "${neg[@]}"; do
    IFS='|' read -r nname nset trx tax gx nmut nmutn gate want <<< "$n"
    for chk in 1 0; do
      # the underbudget / legacy-floor controls are caught by the pre-traffic gate when it is on
      out="$(LINES_MAX=6 run_one ratified "$nset" 3700 130 3 1 "$chk" 1 "$trx" "$tax" "$gx" "$nmut" "$nmutn" 2>&1)"; rc=$?
      if [ "$chk" = 1 ] && [ "$gate" = 0 ]; then
        if [ "$rc" -ne 0 ] && echo "$out" | grep -q '^CONFIG_REJECT'; then
          echo "[neg $nname gate=1] failed as required: $(echo "$out" | grep -m1 '^CONFIG_REJECT')"
        else echo "[neg $nname gate=1] NEGATIVE CONTROL DID NOT FAIL AS REQUIRED"; echo "$out"; fail=1; fi
        continue
      fi
      [ "$chk" = 1 ] && [ "$gate" = 1 ] && continue    # injected faults have no gate variant
      first="$(echo "$out" | grep -m1 '^FINDING')"
      if [ "$rc" -ne 0 ] && echo "$first" | grep -qE "$want"; then
        echo "[neg $nname gate=$chk] failed as required: $first"
      else
        echo "[neg $nname gate=$chk] NEGATIVE CONTROL DID NOT FAIL FOR THE INTENDED REASON (wanted $want)"; echo "$out"; fail=1
      fi
    done
  done
fi
[ "$fail" = 0 ] && echo "ALL PASS" || echo "SOME FAIL"
exit "$fail"
