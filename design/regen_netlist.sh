#!/usr/bin/env bash
# regen_netlist.sh -- mechanical netlist regeneration for the 2T gain-cell
# bitcell schematic (issue #14, T1 item 1: design sources).
#
# This is the concrete "regenerated on design change" deliverable
# docs/design-evidence-tiers.md requires (presence AND reproducibility, not
# a one-off drop): it re-derives design/gain_cell_2t.spice from
# design/gain_cell_2t.sch via xschem's own netlister, so "the netlist is
# demonstrably derived from the schematic, not hand-maintained" is a
# one-command, checkable fact.
#
# Usage:
#   ./design/regen_netlist.sh            # regenerate design/gain_cell_2t.spice in place
#   ./design/regen_netlist.sh --check    # regenerate to a scratch file and diff
#                                         # against the committed netlist; exit
#                                         # nonzero (staleness) if they differ
#
# Both modes also fail (nonzero exit) if any device instance in the
# regenerated netlist resolves to anything other than
# sky130_fd_pr__nfet_01v8 -- the ratified 2T topology's access/read device
# (spec/retention-refresh-budget.md Sec.6, sim/leakage/README.md "Device
# choice"). A deliberate deviation from that device would need this script
# updated alongside a PR description explicitly calling it out.
#
# Requires PDK_ROOT/PDK exported (source design/env.sh first) and xschem on
# PATH -- see design/README.md.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESIGN_SCH="${REPO_ROOT}/design/gain_cell_2t.sch"
COMMITTED_NETLIST="${REPO_ROOT}/design/gain_cell_2t.spice"
XSCHEMRC="${REPO_ROOT}/design/xschemrc"

CHECK_MODE=0
if [[ "${1:-}" == "--check" ]]; then
  CHECK_MODE=1
fi

if ! command -v xschem >/dev/null 2>&1; then
  echo "FAIL: xschem not found on PATH -- see design/README.md" >&2
  exit 1
fi
if [[ -z "${PDK_ROOT:-}" || -z "${PDK:-}" ]]; then
  echo "FAIL: PDK_ROOT/PDK not set -- run 'source design/env.sh' first" >&2
  exit 1
fi

SCRATCH_DIR="$(mktemp -d)"
trap 'rm -rf "${SCRATCH_DIR}"' EXIT

# xschem's own exit code reflects its electrical-rule check, not merely
# whether netlisting succeeded (see design/gain_cell_2t.sch's own header
# note on why `sn` deliberately has no hierarchical port). This schematic's
# ports (wl/bl/rwl/rbl) are all declared ipin/opin, and `sn` is a genuine
# 2-pin net, so a clean netlist of this schematic exits 0 with empty
# stdout/stderr -- checked explicitly below rather than assumed.
set +e
XSCHEM_OUT="$(xschem -x -n -s -q --rcfile "${XSCHEMRC}" -o "${SCRATCH_DIR}" "${DESIGN_SCH}" 2>&1)"
XSCHEM_EXIT=$?
set -e
RAW_NETLIST="${SCRATCH_DIR}/gain_cell_2t.spice"
if [[ ! -f "${RAW_NETLIST}" ]]; then
  echo "FAIL: xschem did not produce ${RAW_NETLIST}" >&2
  echo "${XSCHEM_OUT}" >&2
  exit 1
fi
if [[ "${XSCHEM_EXIT}" -ne 0 || -n "${XSCHEM_OUT}" ]]; then
  echo "FAIL: xschem exited ${XSCHEM_EXIT} or printed unexpected stdout/stderr text (expected exit 0, no output):" >&2
  echo "${XSCHEM_OUT}" >&2
  exit 1
fi

# --- Normalize machine-local absolute paths ------------------------------
# xschem embeds an absolute `** sch_path:` comment line that encodes
# wherever THIS machine's repo checkout happens to live -- not reproducible
# across machines/CI runners/worktrees. Rewrite it to a repo-relative path
# so the artifact (and the --check comparison below) is deterministic given
# the same schematic content, regardless of where the repo is checked out.
NORMALIZED_BODY="${SCRATCH_DIR}/normalized.spice"
sed -E "s#^(\\*\\* s(ch|ym)_path: ).*/(design/.*)#\\1\\3#" "${RAW_NETLIST}" > "${NORMALIZED_BODY}"

# --- Ratified-device-flavour gate -----------------------------------------
# Every device instance must be sky130_fd_pr__nfet_01v8 -- the access
# device the retention/leakage evidence chain was measured against. Any
# other sky130_fd_pr__* flavour is a spec deviation that must be called out
# explicitly in the PR that introduces it, not silently absorbed here.
NON_RATIFIED="$(grep -oE 'sky130_fd_pr__[a-zA-Z0-9_]+' "${NORMALIZED_BODY}" | sort -u \
  | grep -v '^sky130_fd_pr__nfet_01v8$' || true)"
if [[ -n "${NON_RATIFIED}" ]]; then
  echo "FAIL: non-ratified sky130_fd_pr primitive(s) found (expected only nfet_01v8):" >&2
  echo "${NON_RATIFIED}" >&2
  exit 1
fi
echo "OK: every device instance resolves to sky130_fd_pr__nfet_01v8."

# --- Provenance header ----------------------------------------------------
# sha256 of the source schematic this netlist is derived from --
# deterministic given its content (unlike a wall-clock timestamp or a `git
# rev-parse HEAD`, which would drift on every unrelated commit elsewhere in
# the repo and make the --check comparison spuriously fail). A reviewer can
# independently reproduce this by hashing the same file.
PROVENANCE_FILE="${SCRATCH_DIR}/provenance.txt"
SCH_HASH="$(sha256sum "${DESIGN_SCH}" | cut -d' ' -f1)"
{
  echo "* gain_cell_2t.spice -- 2T gain-cell bitcell netlist, derived (issue #14)."
  echo "* Regenerate with: ./design/regen_netlist.sh (requires PDK_ROOT/PDK, see"
  echo "* design/README.md). --check verifies this file is not stale relative to"
  echo "* a fresh regeneration from design/gain_cell_2t.sch -- staleness is failure."
  echo "*"
  echo "* Provenance: sha256 of the source schematic this netlist derives from"
  echo "* (reproduce with: sha256sum design/gain_cell_2t.sch). This is the"
  echo "* file-content hash, not a git commit reference, so it stays meaningful"
  echo "* in a shallow clone and does not drift when an unrelated commit"
  echo "* elsewhere touches HEAD."
  echo "*   design/gain_cell_2t.sch: sha256:${SCH_HASH}"
  echo "*"
  echo "* Every device instance below is sky130_fd_pr__nfet_01v8 -- verified"
  echo "* mechanically by this script, not by review alone."
} > "${PROVENANCE_FILE}"

FINAL_NETLIST="${SCRATCH_DIR}/final.spice"
cat "${PROVENANCE_FILE}" "${NORMALIZED_BODY}" > "${FINAL_NETLIST}"

if [[ "${CHECK_MODE}" -eq 1 ]]; then
  if [[ ! -f "${COMMITTED_NETLIST}" ]]; then
    echo "FAIL: ${COMMITTED_NETLIST} does not exist -- run without --check first." >&2
    exit 1
  fi
  if diff -u "${COMMITTED_NETLIST}" "${FINAL_NETLIST}"; then
    echo "OK: ${COMMITTED_NETLIST} matches a fresh regeneration from the current schematic."
    exit 0
  else
    echo "FAIL: ${COMMITTED_NETLIST} is STALE relative to the current schematic." >&2
    echo "      Run ./design/regen_netlist.sh (without --check) and commit the result." >&2
    exit 1
  fi
else
  cp "${FINAL_NETLIST}" "${COMMITTED_NETLIST}"
  echo "OK: wrote ${COMMITTED_NETLIST}"
fi
