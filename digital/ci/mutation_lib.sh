# Shared mutation-check harness, sourced by digital/*/run_mutation.sh.
#
# Caller contract (set before calling mutation_sed_check):
#   here          directory of the calling script (for mutation_sed_check's use)
#   M             associative array: mutant name -> `sed -E` expression
#   mutant_run    function: mutant_run <mutated-source> <logfile>; runs the
#                 bench against that copy and returns non-zero if it FAILED
# Optional:
#   MUT_SORT=1          iterate mutants in sorted order (default: hash order,
#                       which keeps the committed results/ listings stable)
#   MUT_KILL_PATTERN=re a mutant only counts as killed if its log matches this
#                       grep -E pattern; a failure without it is reported as a
#                       probable compile error (default: any failure is a kill)
#
# Exact-string ("anchor") mutants use mutation_anchor_apply and
# mutation_verdict instead of mutation_sed_check; the caller owns the mutant
# table and loop, and the `rc` variable (set rc=0 first) that they update.
# Output strings are the evidence format of the committed results/ files.

mutation_init() {  # sets $tmp and removes it on exit
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
}

mutation_baseline() {  # <command...>: exit 2 unless the unmutated bench passes
  "$@" >/dev/null || { echo "baseline does not pass"; exit 2; }
  echo "baseline: PASS"
}

mutation_sed_check() {  # <source file to mutate>; exits with the check status
  local src="$1" name rc=0 names
  if [ "${MUT_SORT:-0}" = 1 ]; then
    names="$(printf '%s\n' "${!M[@]}" | sort)"
  else
    names="$(printf '%s\n' "${!M[@]}")"
  fi
  for name in $names; do
    sed -E "${M[$name]}" "$src" > "$tmp/$name.v"
    if cmp -s "$tmp/$name.v" "$src"; then echo "MUTANT $name: sed did not change the source"; rc=1; continue; fi
    if mutant_run "$tmp/$name.v" "$tmp/$name.log"; then
      echo "MUTANT $name: SURVIVED (testbench is too weak)"; rc=1
    elif [ -z "${MUT_KILL_PATTERN:-}" ]; then
      echo "MUTANT $name: killed"
    elif grep -qE "$MUT_KILL_PATTERN" "$tmp/$name.log"; then
      echo "MUTANT $name: killed ($(grep -cE "$MUT_KILL_PATTERN" "$tmp/$name.log") violations shown)"
    else
      echo "MUTANT $name: failed WITHOUT a bench violation (compile error?)"; rc=1
    fi
  done
  [ "$rc" = 0 ] && echo "MUTATION CHECK PASS" || echo "MUTATION CHECK FAIL"
  exit "$rc"
}

mutation_anchor_apply() {  # <name> <dir> <file> <original> <mutated>: replace <original> once in <dir>/<file>
  python3 -I -c '
import sys, pathlib
p = pathlib.Path(sys.argv[1]); s = p.read_text()
if s.count(sys.argv[2]) != 1: sys.exit(1)
p.write_text(s.replace(sys.argv[2], sys.argv[3]))' "$2/$3" "$4" "$5" && return 0
  echo "MUTANT $1: anchor not found exactly once in $3"
  return 1
}

mutation_verdict() {  # <name> <logfile> <bench status> <finding regex>; sets rc=1 unless killed
  if [ "$3" = 0 ]; then echo "MUTANT $1: SURVIVED (bench is too weak)"; rc=1
  elif grep -qE "$4" "$2"; then echo "MUTANT $1: killed (first: $(grep -m1 -E "$4" "$2"))"
  else echo "MUTANT $1: failed WITHOUT a finding (compile error?)"; rc=1; fi
}
