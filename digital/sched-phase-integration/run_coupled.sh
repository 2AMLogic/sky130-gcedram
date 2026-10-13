#!/usr/bin/env bash
# Coupled scheduler/sequencer matrix (issue #138). Behavioral, iverilog only.
#   1. positive matrix: both sourced interval bases x coupled phase sets x
#      scenarios 0-3; every run must PASS (every launched op executed, scheduler
#      completion >= sequencer completion, deadline / coverage monitors on
#      executed completions);
#   2. infeasible combination (set 'huge'): coupled_params.py and the bench must
#      both reject it with a non-zero result;
#   3. negative controls: deliberately underbudgeted T_ROW / T_ACC (derived - 1,
#      and the stale hard-coded 34) must FAIL, both through the pre-traffic
#      configuration gate and (gate bypassed, CHECK_CFG=0) through the dynamic
#      monitors alone.
# Environment: CHECK_CFG (0 bypasses the pre-traffic gate in the positive matrix), DIG (digital/ tree to take RTL from; default this repo's, used by
# run_coupled_mutation.sh), SCENS, SETS, BASES (space lists), MUT, MUT_N.
# usage: run_coupled.sh [--no-negative]
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
dig="${DIG:-$here/..}"
scens="${SCENS:-0 1 2 3}"
sets="${SETS:-anchored gap1 full_read_pulse fast mismatch}"
bases="${BASES:-ratified extracted}"
mut="${MUT:-0}"; mut_n="${MUT_N:-7}"; chk0="${CHECK_CFG:-1}"
build="$(mktemp -d)"; trap 'rm -rf "$build"' EXIT
srcs=("$dig/sched-phase-integration/launch_adapter.v" "$dig/sched-phase-integration/coupled_top.v"
      "$here/tb_coupled.v" "$dig/control-integration/refresh_sched_rt.v" "$dig/control-integration/gc_ctrl_top.v"
      "$dig/control-integration/cfg_xfer.v" "$dig/spi-control/spi_slave.v" "$dig/phase-control/phase_seq.v")
fail=0

# run_one BASIS SET SCEN CHECK_CFG TROW_X TACC_X ; prints the result lines; returns 0 on TB_RESULT: PASS
run_one() {
  local basis="$1" set="$2" sc="$3" chk="$4" trx="$5" tax="$6" gx="${7:-0}" params
  params="$(COUPLED_FORCE=1 python3 -I "$here/coupled_params.py" "$basis" "$set")" || { echo "[$basis $set] PARAMS FAILED"; return 2; }
  eval "$params"
  iverilog -g2012 -s tb_coupled -o "$build/t.vvp" \
    -P tb_coupled.SCEN="$sc" -P tb_coupled.P_PRE="$P_PRE" -P tb_coupled.P_SENSE="$P_SENSE" \
    -P tb_coupled.P_WB="$P_WB" -P tb_coupled.P_GUARD="$P_GUARD" -P tb_coupled.GAP="$GAP" \
    -P tb_coupled.N_ROWS="$N_ROWS" -P tb_coupled.INTERVAL="$INTERVAL" -P tb_coupled.GUARD="$SCHED_GUARD" \
    -P tb_coupled.PY_T_ROW="$T_ROW" -P tb_coupled.PY_T_ACC="$T_ACC" -P tb_coupled.PY_MIN="$MIN_INTERVAL" \
    -P tb_coupled.PY_SETTLE="$T_SETTLE" -P tb_coupled.CHECK_CFG="$chk" \
    -P tb_coupled.T_ROW_X="$trx" -P tb_coupled.T_ACC_X="$tax" -P tb_coupled.GUARD_X="$gx" \
    -P tb_coupled.MUT="$mut" -P tb_coupled.MUT_N="$mut_n" \
    "${srcs[@]}" || { echo "[$basis $set scen=$sc] COMPILE FAILED"; return 2; }
  vvp -n "$build/t.vvp" > "$build/out" 2>&1
  grep -E '^(CONFIG:|KIND|DEADLINE|VIOLATION|CONFIG_REJECT|TB_RESULT)' "$build/out" | head -${LINES_MAX:-14}
  grep -q '^TB_RESULT: PASS' "$build/out"
}

echo "== 1. coupled positive matrix =="
for basis in $bases; do
  for set in $sets; do
    for sc in $scens; do
      echo "[$basis $set scen=$sc]"
      run_one "$basis" "$set" "$sc" "$chk0" 0 0 || fail=1
    done
  done
done

if [ "${1:-}" != "--no-negative" ]; then
  echo "== 2. infeasible combination must be rejected (non-zero) =="
  for basis in $bases; do
    if python3 -I "$here/coupled_params.py" "$basis" huge >/dev/null 2>"$build/err"; then
      echo "[$basis huge] python derivation ACCEPTED an infeasible combination"; fail=1
    else
      echo "[$basis huge] python: $(cat "$build/err")"
    fi
    out="$(LINES_MAX=6 run_one "$basis" huge 1 1 0 0 2>&1)"; rc=$?
    echo "$out" | sed "s/^/[$basis huge bench] /"
    if [ "$rc" -ne 0 ] && echo "$out" | grep -q '^CONFIG_REJECT: infeasible'; then
      echo "[$basis huge bench] expected rejection observed"
    else
      echo "[$basis huge bench] INFEASIBLE COMBINATION WAS NOT REJECTED"; fail=1
    fi
  done

  echo "== 3. underbudgeted negative controls (must FAIL) =="
  # name:set:trow_x:tacc_x:guard_x:scen. Underbudget = derived-1 (REFRESH D_REF / access D_ACC)
  # or the stale hard-coded 34; legacy_floor = the #74 guard (2) without the per-op decision cycle.
  neg=("row_minus1:anchored:34:0:0:1" "row_minus1:gap1:37:0:0:1" "row_minus1:full_read_pulse:44:0:0:1"
       "acc_minus1:anchored:0:22:0:1" "acc_minus1:mismatch:0:42:0:1"
       "stale34:gap1:34:34:0:1" "stale34:full_read_pulse:34:34:0:1" "stale34:mismatch:34:34:0:1"
       "legacy_floor:anchored:0:0:2:2" "legacy_floor:full_read_pulse:0:0:2:2")
  for n in "${neg[@]}"; do
    IFS=: read -r nname nset trx tax gx nsc <<< "$n"
    for chk in 1 0; do
      out="$(LINES_MAX=4 run_one ratified "$nset" "$nsc" "$chk" "$trx" "$tax" "$gx" 2>&1)"; rc=$?
      first="$(echo "$out" | grep -m1 -E '^(CONFIG_REJECT|VIOLATION)')"
      if [ "$rc" -ne 0 ] && [ -n "$first" ]; then
        echo "[neg $nname $nset gate=$chk] failed as required: $first"
      else
        echo "[neg $nname $nset gate=$chk] NEGATIVE CONTROL DID NOT FAIL AS REQUIRED"; echo "$out"; fail=1
      fi
    done
  done
fi
[ "$fail" = 0 ] && echo "ALL PASS" || echo "SOME FAIL"
exit "$fail"
