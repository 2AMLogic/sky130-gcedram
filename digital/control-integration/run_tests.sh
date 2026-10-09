#!/usr/bin/env bash
# Integration evidence for issue #93. Runs, serially:
#   1. lockstep equivalence: refresh_sched_rt (config port idle) vs the
#      unchanged #74 refresh_sched, both sourced intervals x #74 scenarios 0/1/2;
#   2. integration bench at both sourced intervals x SPI/clk phase relationships
#      (saturating reads), plus seeded random traffic;
#   3. negative controls: frame spacing violated -> the bench MUST fail with a
#      LOST START_SWEEP;
#   4. fault injection: run_mutation.sh (every mutant MUST fail the bench).
# Exit non-zero on any failure.   usage: run_tests.sh [--no-mutation]
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
mode="${1:-}"
build="$(mktemp -d)"; trap 'rm -rf "$build"' EXIT
fail=0

echo "== 1. lockstep equivalence vs digital/refresh-scheduler/refresh_sched.v =="
for basis in ratified extracted; do
  eval "$(python3 -I "$here/params.py" "$basis")"
  for sc in 0 1 2; do
    iverilog -g2012 -s tb_equiv -o "$build/eq.vvp" -P tb_equiv.INTERVAL="$INTERVAL" \
      -P tb_equiv.N_ROWS="$N_ROWS" -P tb_equiv.T_ROW="$T_ROW" -P tb_equiv.T_ACC="$T_ACC" \
      -P tb_equiv.GUARD="$GUARD" -P tb_equiv.SCENARIO="$sc" \
      "$here/../refresh-scheduler/refresh_sched.v" "$here/refresh_sched_rt.v" "$here/tb_equiv.v" || { fail=1; continue; }
    out="$(vvp -n "$build/eq.vvp")"
    echo "[$basis] $(echo "$out" | grep -E '^(EQUIV|MISMATCH|LIVENESS|TB_RESULT)' | head -4 | tr '\n' ' ')"
    echo "$out" | grep -q '^TB_RESULT: PASS' || fail=1
  done
done

echo "== 2. integration bench =="
# sclk half period (ps) and master phase offset (ps) vs the 1 ns clk:
#   3700/130  sclk slower than clk, edges at an arbitrary phase
#   370/610   sclk faster than clk
#   500/0     sclk same rate as clk, SPI edges coincide with clk edges
#   10000/500 slow SPI (frames of ~340 clk cycles)
for basis in ratified extracted; do
  for combo in "3700 130 1" "370 610 1" "500 0 1" "10000 500 1" "1300 870 2"; do
    read -r half phase traffic <<< "$combo"
    echo "[$basis sclk_half_ps=$half phase_ps=$phase traffic=$traffic]"
    "$here/sim_one.sh" "$basis" "$half" "$phase" "$traffic" 0 || fail=1
  done
done

echo "== 3. negative controls (must FAIL with LOST START_SWEEP) =="
for basis in ratified extracted; do
  out="$("$here/sim_one.sh" "$basis" 3700 130 1 1 2>&1)"; rc=$?
  echo "$out" | sed "s/^/[$basis neg_spacing] /"
  if [ "$rc" -ne 0 ] && echo "$out" | grep -q '^LOST START_SWEEP'; then
    echo "[$basis neg_spacing] expected failure observed"
  else
    echo "[$basis neg_spacing] NEGATIVE CONTROL DID NOT FAIL AS REQUIRED"; fail=1
  fi
done

if [ "$mode" != "--no-mutation" ]; then
  echo "== 4. fault injection =="
  "$here/run_mutation.sh" || fail=1
fi

[ "$fail" = 0 ] && echo "ALL PASS" || echo "SOME FAIL"
exit "$fail"
