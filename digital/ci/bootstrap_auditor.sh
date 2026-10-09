#!/usr/bin/env bash
# Local auditor bootstrap: check build prerequisites, then build the pinned
# Icarus Verilog (via digital/ci/install_iverilog.sh, the single source of the
# pin) into an explicit prefix. Never installs packages, never edits shell
# startup files, never runs the regression suites.
# usage: bootstrap_auditor.sh PREFIX BUILD_DIR
#   PREFIX     absolute path, outside the repository (simulator install dir)
#   BUILD_DIR  absolute path, outside the repository (scratch build tree)
set -euo pipefail

usage() {
  echo "usage: $0 ABSOLUTE_PREFIX ABSOLUTE_BUILD_DIR" >&2
  echo "  both paths must be outside the repository checkout" >&2
}

if [ "$#" -ne 2 ] || [ -z "$1" ] || [ -z "$2" ]; then
  usage
  exit 2
fi
prefix="$1"
build="$2"
case "$prefix" in /*) ;; *) echo "error: PREFIX must be absolute: $prefix" >&2; usage; exit 2 ;; esac
case "$build" in /*) ;; *) echo "error: BUILD_DIR must be absolute: $build" >&2; usage; exit 2 ;; esac

case "$prefix" in
  *[[:space:]]*) echo "error: PREFIX must not contain whitespace (Icarus configure rejects it): $prefix" >&2; exit 2 ;;
esac

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd -P)"

outside_repo() {
  local p
  p="$(realpath -m -- "$1")"
  case "$p/" in
    "$repo"/*) return 1 ;;
  esac
  return 0
}
for pair in "PREFIX:$prefix" "BUILD_DIR:$build"; do
  if ! outside_repo "${pair#*:}"; then
    echo "error: ${pair%%:*} must be outside the repository ($repo): ${pair#*:}" >&2
    exit 2
  fi
done

# Prerequisites first, before anything is created.
missing=()
for tool in python3 git gperf bison flex g++ make; do
  command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
done
if [ "${#missing[@]}" -gt 0 ]; then
  echo "error: missing prerequisite tool(s): ${missing[*]}" >&2
  echo "This script does not install packages. On Ubuntu 24.04 ask an administrator, or run:" >&2
  echo "  sudo apt-get update" >&2
  echo "  sudo apt-get install -y --no-install-recommends python3 git gperf bison flex g++ make" >&2
  exit 1
fi

mkdir -p -- "$prefix" "$build"
"$here/install_iverilog.sh" "$prefix" "$build"

echo
echo "Pinned Icarus Verilog installed in: $prefix"
echo "Use it (this shell only; no startup files were modified):"
printf '  export PATH=%q:"$PATH"\n' "$prefix/bin"
echo "Then confirm: command -v iverilog vvp"
