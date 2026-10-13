#!/usr/bin/env bash
# regen_netlist.sh -- mechanical netlist regeneration for the design/
# schematics: the 2T gain-cell bitcell (issue #14, T1 item 1) and the sense
# latch (issue #109).
#
# This is the concrete "regenerated on design change" deliverable
# docs/design-evidence-tiers.md requires (presence AND reproducibility, not
# a one-off drop): it re-derives design/<cell>.spice from design/<cell>.sch
# via xschem's own netlister, so "the netlist is demonstrably derived from
# the schematic, not hand-maintained" is a one-command, checkable fact.
#
# Usage:
#   ./design/regen_netlist.sh            # regenerate every committed netlist in place
#   ./design/regen_netlist.sh --check    # regenerate to scratch and diff against
#                                         # the committed netlists; exit nonzero
#                                         # (staleness) if any differs
#
# Per-cell device-flavour gate (both modes fail on a violation):
#   gain_cell_2t : only sky130_fd_pr__nfet_01v8 (spec/retention-refresh-budget.md
#                  Sec.6, sim/leakage/README.md "Device choice")
#   sense_latch  : only sky130_fd_pr__nfet_01v8 / sky130_fd_pr__pfet_01v8 (the
#                  flavours sim/sense-stage/gen_sense_stage.py instantiates)
# A deliberate deviation needs this script updated alongside a PR description
# explicitly calling it out.
#
# xschem version tolerance: the PDK xschemrc prints an informational banner
# and older xschem (3.4.4) leaves expr('...') geometry params unevaluated;
# the banner lines are filtered and design/normalize_netlist.py evaluates
# the expressions, so the output is the same across xschem versions.
#
# Requires PDK_ROOT/PDK exported (source design/env.sh first) and xschem on
# PATH -- see design/README.md.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
XSCHEMRC="${REPO_ROOT}/design/xschemrc"

# cell name -> "|"-separated allowed sky130_fd_pr flavours
CELLS=(gain_cell_2t sense_latch)
declare -A ALLOWED=(
  [gain_cell_2t]="sky130_fd_pr__nfet_01v8"
  [sense_latch]="sky130_fd_pr__nfet_01v8|sky130_fd_pr__pfet_01v8"
)
declare -A DESCR=(
  [gain_cell_2t]="2T gain-cell bitcell netlist, derived (issue #14)."
  [sense_latch]="sense-latch netlist (latch + footer/header), derived (issue #109)."
)

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

STATUS=0
for CELL in "${CELLS[@]}"; do
  DESIGN_SCH="${REPO_ROOT}/design/${CELL}.sch"
  COMMITTED_NETLIST="${REPO_ROOT}/design/${CELL}.spice"
  CELL_DIR="${SCRATCH_DIR}/${CELL}"
  mkdir -p "${CELL_DIR}"

  # xschem's exit code reflects its electrical-rule check, not merely whether
  # netlisting succeeded; a clean netlist exits 0. The PDK xschemrc prints a
  # fixed informational banner, which is filtered; anything else is a failure.
  set +e
  XSCHEM_OUT="$(xschem -x -n -s -q --rcfile "${XSCHEMRC}" -o "${CELL_DIR}" "${DESIGN_SCH}" 2>&1)"
  XSCHEM_EXIT=$?
  set -e
  XSCHEM_OUT="$(printf '%s\n' "${XSCHEM_OUT}" | grep -vE '^(open_pdks installation:|SKYWATER_MODELS:|SKYWATER_STDCELLS:|setup_tcp_bespice:)' | sed '/^$/d' || true)"
  RAW_NETLIST="${CELL_DIR}/${CELL}.spice"
  if [[ ! -f "${RAW_NETLIST}" ]]; then
    echo "FAIL: xschem did not produce ${RAW_NETLIST}" >&2
    echo "${XSCHEM_OUT}" >&2
    exit 1
  fi
  if [[ "${XSCHEM_EXIT}" -ne 0 || -n "${XSCHEM_OUT}" ]]; then
    echo "FAIL: ${CELL}: xschem exited ${XSCHEM_EXIT} or printed unexpected text (expected exit 0, no output):" >&2
    echo "${XSCHEM_OUT}" >&2
    exit 1
  fi

  # Evaluate version-dependent expr() params and rewrap deterministically.
  EVALUATED="${CELL_DIR}/evaluated.spice"
  python3 -I "${REPO_ROOT}/design/normalize_netlist.py" "${RAW_NETLIST}" "${EVALUATED}"

  # Rewrite the machine-local absolute `** sch_path:` comment to a
  # repo-relative path so the artifact is deterministic across checkouts.
  NORMALIZED_BODY="${CELL_DIR}/normalized.spice"
  sed -E "s#^(\\*\\* s(ch|ym)_path: ).*/(design/.*)#\\1\\3#" "${EVALUATED}" > "${NORMALIZED_BODY}"

  # Device-flavour gate.
  NON_RATIFIED="$(grep -oE 'sky130_fd_pr__[a-zA-Z0-9_]+' "${NORMALIZED_BODY}" | sort -u \
    | grep -vE "^(${ALLOWED[$CELL]})\$" || true)"
  if [[ -n "${NON_RATIFIED}" ]]; then
    echo "FAIL: ${CELL}: non-ratified sky130_fd_pr primitive(s) (allowed: ${ALLOWED[$CELL]//|/, }):" >&2
    echo "${NON_RATIFIED}" >&2
    exit 1
  fi
  echo "OK: ${CELL}: every device instance resolves to {${ALLOWED[$CELL]//|/, }}."

  # Provenance header: sha256 of the source schematic (deterministic, unlike
  # a timestamp or git HEAD). Reproduce with: sha256sum design/<cell>.sch
  SCH_HASH="$(sha256sum "${DESIGN_SCH}" | cut -d' ' -f1)"
  FINAL_NETLIST="${CELL_DIR}/final.spice"
  {
    echo "* ${CELL}.spice -- ${DESCR[$CELL]}"
    echo "* Regenerate with: ./design/regen_netlist.sh (requires PDK_ROOT/PDK, see"
    echo "* design/README.md). --check verifies this file is not stale relative to"
    echo "* a fresh regeneration from design/${CELL}.sch -- staleness is failure."
    echo "*"
    echo "* Provenance: sha256 of the source schematic this netlist derives from"
    echo "* (reproduce with: sha256sum design/${CELL}.sch). This is the"
    echo "* file-content hash, not a git commit reference, so it stays meaningful"
    echo "* in a shallow clone and does not drift when an unrelated commit"
    echo "* elsewhere touches HEAD."
    echo "*   design/${CELL}.sch: sha256:${SCH_HASH}"
    echo "*"
    if [[ "${ALLOWED[$CELL]}" == *"|"* ]]; then
      echo "* Every device instance below is one of {${ALLOWED[$CELL]//|/, }} --"
    else
      echo "* Every device instance below is ${ALLOWED[$CELL]} -- verified"
    fi
    echo "* mechanically by this script, not by review alone."
    cat "${NORMALIZED_BODY}"
  } > "${FINAL_NETLIST}"

  if [[ "${CHECK_MODE}" -eq 1 ]]; then
    if [[ ! -f "${COMMITTED_NETLIST}" ]]; then
      echo "FAIL: ${COMMITTED_NETLIST} does not exist -- run without --check first." >&2
      STATUS=1
    elif diff -u "${COMMITTED_NETLIST}" "${FINAL_NETLIST}"; then
      echo "OK: ${COMMITTED_NETLIST} matches a fresh regeneration from the current schematic."
    else
      echo "FAIL: ${COMMITTED_NETLIST} is STALE relative to the current schematic." >&2
      echo "      Run ./design/regen_netlist.sh (without --check) and commit the result." >&2
      STATUS=1
    fi
  else
    cp "${FINAL_NETLIST}" "${COMMITTED_NETLIST}"
    echo "OK: wrote ${COMMITTED_NETLIST}"
  fi
done
exit "${STATUS}"
