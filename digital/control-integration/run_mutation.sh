#!/usr/bin/env bash
# Fault injection (issue #93): the integration bench must PASS on the real
# RTL and FAIL on every deliberately broken copy (lost commands, unsafe
# interval transitions, wrong validity/busy semantics). Exit 0 only if the
# baseline passes and every mutant is killed.
# Each mutant is one exact-string replacement (must match exactly once).
# Bench configuration for mutants: ratified interval, sclk_half 3.7 ns,
# phase 0.13 ns, saturating reads.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
cfg=(ratified 3700 130 1 0)

"$here/sim_one.sh" "${cfg[@]}" > "$tmp/base.log" 2>&1 || { cat "$tmp/base.log"; echo "baseline does not pass"; exit 2; }
echo "baseline: PASS"

# name | file | original text | mutated text
mutants=(
  "sweep_toggle_dropped|cfg_xfer.v|cfg_sweep    <= (spi_tog != tog_seen);|cfg_sweep    <= 1'b0;"
  "capture_on_cs_fall|cfg_xfer.v|wire      cs_rise = cs_s[1] && !cs_s[2];|wire      cs_rise = !cs_s[1] && cs_s[2];"
  "busy_ignores_sweep|gc_ctrl_top.v|assign busy = xfer_pending || sweep_active;|assign busy = xfer_pending;"
  "floor_not_passed_to_spi|gc_ctrl_top.v|.MIN_INTERVAL(MIN_INTERVAL)|.MIN_INTERVAL(1)"
  "urgent_ignores_runtime_interval|refresh_sched_rt.v|wire [31:0] urgent_age = ivl_eff - T_ROW|wire [31:0] urgent_age = INTERVAL - T_ROW"
  "shortening_ignored|refresh_sched_rt.v|ivl_eff <= cfg_interval;|if (cfg_interval > ivl_eff) ivl_eff <= cfg_interval;"
  "ptr_restart_on_cfg|refresh_sched_rt.v|ivl_eff <= cfg_interval;|ivl_eff <= cfg_interval; ptr <= 0;"
  "disable_not_applied|refresh_sched_rt.v|en_eff  <= cfg_en;|en_eff  <= 1'b1;"
  "reinit_skipped|refresh_sched_rt.v|begin sw_left <= N_ROWS; reinit <= 1; end|begin sw_left <= N_ROWS; end"
  "ok_ignores_init|refresh_sched_rt.v|assign refresh_ok   = en_eff && !reinit;|assign refresh_ok   = en_eff;"
  "disable_not_flagged|refresh_sched_rt.v|if (en_eff && !cfg_en) data_lost <= 1;|if (en_eff && !cfg_en) data_lost <= 0;"
  "sweep_done_early|refresh_sched_rt.v|if (sw_left == 1) begin|if (sw_left == 2) begin"
)

rc=0
for m in "${mutants[@]}"; do
  IFS='|' read -r name file orig mut <<< "$m"
  d="$tmp/$name"; mkdir -p "$d"
  cp "$here/cfg_xfer.v" "$here/refresh_sched_rt.v" "$here/gc_ctrl_top.v" "$d/"
  if ! python3 -I -c '
import sys, pathlib
p = pathlib.Path(sys.argv[1]); s = p.read_text()
if s.count(sys.argv[2]) != 1: sys.exit(1)
p.write_text(s.replace(sys.argv[2], sys.argv[3]))' "$d/$file" "$orig" "$mut"; then
    echo "MUTANT $name: anchor not found exactly once in $file"; rc=1; continue
  fi
  if SRC_DIR="$d" "$here/sim_one.sh" "${cfg[@]}" > "$d/log" 2>&1; then
    echo "MUTANT $name: SURVIVED (bench is too weak)"; rc=1
  else
    echo "MUTANT $name: killed"
    awk '/^(FAIL|VIOLATION|LOST|SPURIOUS|INCOMPLETE|REARM|REFRESH_OK|UNNOTICED|DATA_LOST|NOT APPLIED|PARTIAL|SWEEP)/ && n < 1 {print "    first: " $0; n++} /^ERRORS/ {print "    " $0}' "$d/log"
  fi
done
[ "$rc" = 0 ] && echo "MUTATION CHECK PASS" || echo "MUTATION CHECK FAIL"
exit "$rc"
