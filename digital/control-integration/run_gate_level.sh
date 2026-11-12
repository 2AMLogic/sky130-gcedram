#!/usr/bin/env bash
# Gate-level replay of the control-integration bench (issue #230, T1 item 1 digital).
#   1. replays tb_ctrl_integ.v on the COMMITTED synthesized netlist
#      (synth/run/gc_ctrl_top_synth.v) against the sky130_fd_sc_hd functional models,
#      ratified basis only (the netlist is elaborated at the module defaults),
#      at three SPI/clk phase relationships, plus the frame-spacing negative control;
#   2. unless --no-mutation: applies two run_mutation.sh mutants to the RTL,
#      RE-SYNTHESIZES each with klt, and requires the gate-level replay to FAIL.
#      Without this the replay would prove nothing.
# env KLT   klt command (default: klt); it must be the pinned release in
#           .github/workflows/signoff.yml and sv2v must be on PATH (mutation only)
# env PDK   PDK variant (default sky130A); PDK_ROOT honoured by klt/this script
# usage: run_gate_level.sh [--no-mutation]
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
mode="${1:-}"
KLT="${KLT:-klt}"
pdk="${PDK:-sky130A}"
netlist="$here/synth/run/gc_ctrl_top_synth.v"
source "$here/../ci/mutation_lib.sh"
mutation_init
fail=0

if [ -n "${PDK_ROOT:-}" ]; then pdkroot="$PDK_ROOT"
else pdkroot="$($KLT pdk find --pdk "$pdk" --format json | python3 -I -c 'import json,sys;print(json.load(sys.stdin)["root"])')"; fi
models="$pdkroot/$pdk/libs.ref/sky130_fd_sc_hd/verilog"
[ -f "$models/sky130_fd_sc_hd.v" ] || { echo "no sky130_fd_sc_hd verilog models under $models"; exit 2; }

# gl_one NETLIST SCLK_HALF_PS PHASE_PS TRAFFIC NEG_SPACING : exit 0 only on TB_RESULT: PASS
gl_one() {
  local nl="$1" half="$2" phase="$3" traffic="$4" neg="$5" tb=tb_ctrl_integ
  eval "$(python3 -I "$here/params.py" ratified)"
  iverilog -g2012 -DGATE_LEVEL -DFUNCTIONAL -DUNIT_DELAY= -s "$tb" -o "$tmp/gl.vvp" \
    -P "$tb.INTERVAL=$INTERVAL" -P "$tb.MIN_INTERVAL=$MIN_INTERVAL" \
    -P "$tb.N_ROWS=$N_ROWS" -P "$tb.T_ROW=$T_ROW" -P "$tb.T_ACC=$T_ACC" -P "$tb.GUARD=$GUARD" \
    -P "$tb.SCLK_HALF_PS=$half" -P "$tb.PHASE_PS=$phase" -P "$tb.TRAFFIC=$traffic" \
    -P "$tb.NEG_SPACING=$neg" \
    "$models/primitives.v" "$models/sky130_fd_sc_hd.v" "$nl" "$here/tb_ctrl_integ.v" || return 2
  vvp -n "$tmp/gl.vvp" > "$tmp/gl.out" 2>&1 || true
  awk '/^(FAIL|VIOLATION|LOST|SPURIOUS|INCOMPLETE|REARM|REFRESH_OK|UNNOTICED|DATA_LOST|NOT APPLIED|PARTIAL|SWEEP|LIVENESS|COVERAGE)/ && n < 4 {print; n++}' "$tmp/gl.out"
  grep -E '^(ERRORS|TB_RESULT)' "$tmp/gl.out"
  grep -q '^TB_RESULT: PASS' "$tmp/gl.out"
}

echo "== 1. gate-level replay on the committed netlist =="
for combo in "3700 130 1" "370 610 1" "500 0 1"; do
  read -r half phase traffic <<< "$combo"
  echo "[gate-level ratified sclk_half_ps=$half phase_ps=$phase traffic=$traffic]"
  gl_one "$netlist" "$half" "$phase" "$traffic" 0 || fail=1
done

echo "== 2. negative control (must FAIL with LOST START_SWEEP) =="
out="$(gl_one "$netlist" 3700 130 1 1 2>&1)"; rc=$?
echo "$out" | sed 's/^/[gate-level neg_spacing] /'
if [ "$rc" -ne 0 ] && echo "$out" | grep -q '^LOST START_SWEEP'; then
  echo "[gate-level neg_spacing] expected failure observed"
else
  echo "[gate-level neg_spacing] NEGATIVE CONTROL DID NOT FAIL AS REQUIRED"; fail=1
fi

if [ "$mode" != "--no-mutation" ]; then
  echo "== 3. mutate RTL -> re-synthesize -> gate-level replay (must FAIL) =="
  mutants=(
    "sweep_toggle_dropped|cfg_xfer.v|cfg_sweep    <= (spi_tog != tog_seen);|cfg_sweep    <= 1'b0;"
    "disable_not_applied|refresh_sched_rt.v|en_eff  <= cfg_en;|en_eff  <= 1'b1;"
  )
  for m in "${mutants[@]}"; do
    IFS='|' read -r name file orig mut <<< "$m"
    d="$tmp/$name"; mkdir -p "$d/spi-control" "$d/control-integration/synth"
    cp "$here/../spi-control/spi_slave.v" "$d/spi-control/"
    cp "$here/cfg_xfer.v" "$here/refresh_sched_rt.v" "$here/gc_ctrl_top.v" "$d/control-integration/"
    mutation_anchor_apply "$name" "$d/control-integration" "$file" "$orig" "$mut" || { fail=1; continue; }
    python3 -I - "$here/synth/gc_ctrl_top.synth.json" "$d/control-integration/synth/req.json" "$d/out" <<'PY'
import json, sys
r = json.load(open(sys.argv[1])); r["outputs"] = {"dir": sys.argv[3]}
json.dump(r, open(sys.argv[2], "w"))
PY
    if ! $KLT synthesize "$d/control-integration/synth/req.json" --pdk "$pdk" --format json > "$d/synth.json" 2> "$d/synth.err"; then
      echo "MUTANT $name: re-synthesis FAILED"; cat "$d/synth.err"; fail=1; continue
    fi
    if gl_one "$d/out/gc_ctrl_top_synth.v" 3700 130 1 0 > "$d/log" 2>&1; then
      echo "MUTANT $name: SURVIVED at gate level (replay is too weak)"; fail=1
    else
      echo "MUTANT $name: killed at gate level"
      grep -E '^ERRORS' "$d/log" | sed 's/^/    /'
    fi
  done
fi

[ "$fail" = 0 ] && echo "GATE-LEVEL ALL PASS" || echo "GATE-LEVEL SOME FAIL"
exit "$fail"
