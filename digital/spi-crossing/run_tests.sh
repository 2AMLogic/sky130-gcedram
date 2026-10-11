#!/usr/bin/env bash
# Protocol checks for the PROPOSED SPI crossing (issue #157). Serial, no -j.
#   1. positive runs: exactly-once delivery, atomic bundles, BUSY exactness,
#      stopped/restarted sclk, reset cancellation, over several sclk/clk phase
#      relationships and cs_n-high gaps;
#   2. negative control: ack/reservation omitted (NEG=1) -> the bench MUST fail
#      with LOSS / DUP / STALE. A negative control that passes is a failure.
# This is protocol evidence only. Not CDC, not metastability, not timing.
# usage: run_tests.sh      Exit non-zero on any failure.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
build="$(mktemp -d)"; trap 'rm -rf "$build"' EXIT
fail=0

build_tb() {  # half phase gap neg -> $build/t.vvp
  iverilog -g2012 -s tb_xing -o "$build/t.vvp" -P tb_xing.SHALF_PS="$1" -P tb_xing.PHASE_PS="$2" \
    -P tb_xing.GAP_CLK="$3" -P tb_xing.NEG="$4" "$here/xing_model.v" "$here/tb_xing.v"
}

echo "== 1. positive runs (sclk_half_ps phase_ps gap_clk) =="
for combo in "3700 130 4" "370 610 4" "500 0 4" "10000 500 4" "1300 870 4" "370 610 1" "3700 130 1"; do
  read -r half phase gap <<< "$combo"
  build_tb "$half" "$phase" "$gap" 0 || { fail=1; continue; }
  out="$(vvp -n "$build/t.vvp")"
  echo "[half=$half phase=$phase gap=$gap] $(echo "$out" | grep -E "^(SUMMARY|TB_RESULT)" | tr '\n' ' ')"
  echo "$out" | grep -q '^TB_RESULT: PASS' || { echo "$out" | grep -E '^(LOSS|DUP|STALE|MISMATCH|BUSY|TORN|RESET)' | head -5; fail=1; }
done

echo "== 2. negative control: acknowledgement and reservation omitted (must FAIL) =="
for combo in "370 610 4" "500 0 4" "800 300 4"; do
  read -r half phase gap <<< "$combo"
  build_tb "$half" "$phase" "$gap" 1 || { fail=1; continue; }
  out="$(vvp -n "$build/t.vvp")"; echo "$out" | grep -E '^(LOSS|DUP|STALE)' | sort | uniq -c | sort -rn | head -3 | sed "s/^/[neg half=$half] /"
  if echo "$out" | grep -q '^TB_RESULT: FAIL' && echo "$out" | grep -qE '^(LOSS|DUP|STALE)'; then
    echo "[neg half=$half phase=$phase] expected failure observed"
  else
    echo "[neg half=$half phase=$phase] NEGATIVE CONTROL DID NOT FAIL AS REQUIRED"; fail=1
  fi
done

[ "$fail" = 0 ] && echo "ALL PASS" || echo "SOME FAIL"
exit "$fail"
