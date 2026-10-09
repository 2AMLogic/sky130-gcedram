#!/usr/bin/env bash
# iverilog run of the SPI testbench at the ratified and extracted-C_SN bounds.
# usage: run_tests.sh [src.v]   (src override is used by run_mutation.sh)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
src="${1:-$here/spi_slave.v}"
build="$(mktemp -d)"; trap 'rm -rf "$build"' EXIT
fail=0
for basis in ratified extracted; do
  max="$(python3 -I "$here/params.py" "$basis")"
  iverilog -g2012 -o "$build/t.vvp" -P tb_spi_slave.MAX_INTERVAL="$max" "$src" "$here/tb_spi_slave.v"
  out="$(vvp "$build/t.vvp")"
  echo "[$basis MAX_INTERVAL=$max] $(echo "$out" | grep -E '^FAIL|checks=|TB_RESULT' | head -8)"
  echo "$out" | grep -q 'TB_RESULT: PASS' || fail=1
done
[ "$fail" = 0 ] && echo "ALL PASS" || echo "SOME FAIL"
exit "$fail"
