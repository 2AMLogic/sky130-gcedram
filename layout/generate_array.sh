#!/usr/bin/env bash
# generate_array.sh -- reproducible sky130 layout capture for a shared-tap
# N_ROWS x N_COLS array of the ratified 2T gain-cell bitcell (issue #34),
# built from the single-cell layout's own precedent (issue #15,
# layout/generate.sh) and the ratified schematic/netlist (issue #14,
# design/gain_cell_2t.sch / design/gain_cell_2t.spice).
#
# This is a proof-of-technique increment, not a macro-sized array: see
# layout/README.md "Array (issue #34)" for why N_ROWS=N_COLS=4 was chosen
# and what it does/does not establish (explicitly NOT a ratification of
# spec/retention-refresh-budget.md Sec.7's N_rows).
#
# What gets built (see array_topology.py's own module docstring, and
# layout/README.md's "Array (issue #34)" section, for the full topology):
#   1. ONE `mos_array` generator call sized for all `2 * N_ROWS * N_COLS`
#      transistors (`rows=N_ROWS, cols=2*N_COLS`, `topology="array"`),
#      `add_guard_ring=true` -- a single shared substrate tap ring around
#      the whole grid, not one dedicated tap per bitcell (contrast with
#      the single-cell layout's own per-cell `guard_ring` block). This is
#      "Option A" from issue #34's own implementation guidance.
#   2. `array_topology.py` computes the row/column bus net map (`wl_<r>`/
#      `rwl_<r>` per row, `bl_<c>`/`rbl_<c>` per column, `sn_<r>_<c>` per
#      cell) purely as a function of (N_ROWS, N_COLS) and emits the `klt
#      gen-compose` request from it.
#   3. `klt gen-compose` places the one `mos_array` block and routes every
#      bus/`sn` net -- row/column buses first (left to the router's own
#      automatic path search, which handled every one cleanly), each
#      per-cell `sn` net last with its own explicit `waypoints_um` (see
#      array_topology.py's own `SN_WAYPOINT_X_OFFSET_UM` comment for why).
#   4. `array_topology.py` ALSO generates the array-level LVS reference
#      netlist (an N_ROWS x N_COLS replication of
#      design/gain_cell_2t.spice's two-device subcircuit with the same bus
#      net renaming step 2 used) -- generated, never hand-transcribed,
#      mirroring design/regen_netlist.sh's and
#      layout/gain_cell_2t.lvs_reference.spice's own precedent.
#   5. Informal `klt drc`/`klt extract`/`klt lvs` iteration, the same
#      non-sign-off bar issue #15 already established for the single cell.
#   6. (issue #91) In `--check` mode at the committed 4x4 size, compare the
#      regenerated geometry and connectivity with the committed array
#      (`compare_array_layout.py`), in addition to the status gates above.
#
# Toolchains (issue #91): generation (`klt gen` / `klt gen-compose`) and
# check (`klt drc` / `klt lvs` / `klt erc`) run on two separately pinned klt
# revisions, recorded in layout/generation-toolchain.json and verified by
# layout/generation_toolchain.py BEFORE anything is written. `klt` on PATH is
# not used. One-time setup (venvs under .toolchains/, gitignored):
#   python3 layout/generation_toolchain.py install --role generation
#   python3 layout/generation_toolchain.py install --role check
# See layout/README.md "Reproducing the committed array (issue #91)".
#
# Usage:
#   ./layout/generate_array.sh              # regenerate every layout/*array*
#                                            # artifact in place (N_ROWS=N_COLS=4)
#   ./layout/generate_array.sh --check      # regenerate in a scratch dir, then
#                                            # (a) compare geometry/connectivity
#                                            #     with the committed 4x4, and
#                                            # (b) assert routed + DRC clean +
#                                            #     LVS match + ERC clean;
#                                            # never touches committed artifacts
#   ./layout/generate_array.sh --check --record PATH
#                                            # also write the run record (source
#                                            # SHA, tool identities, PDK, commands,
#                                            # comparison, statuses) to PATH
#   N_ROWS=2 N_COLS=2 ./layout/generate_array.sh --check
#                                            # other sizes: validates the
#                                            # generated size only -- there is no
#                                            # committed baseline to reproduce
#   KEEP_SCRATCH=1 ./layout/generate_array.sh --check
#                                            # keep the scratch dir (path printed)
#
# Requires PDK_ROOT/PDK exported (source design/env.sh first), at the pinned
# open_pdks commit (docs/pdk-pin.md).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAYOUT_DIR="${REPO_ROOT}/layout"
DESIGN_SPICE="${REPO_ROOT}/design/gain_cell_2t.spice"
TOOLCHAIN="${LAYOUT_DIR}/generation_toolchain.py"

N_ROWS="${N_ROWS:-4}"
N_COLS="${N_COLS:-4}"
ARRAY_TAG="${N_ROWS}x${N_COLS}"
BASELINE_TAG="4x4"  # the size of the committed layout/gain_cell_2t_array.gds

CHECK_MODE=0
RECORD_PATH=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --check) CHECK_MODE=1 ;;
    --record)
      [[ $# -ge 2 ]] || { echo "FAIL: --record needs a path" >&2; exit 64; }
      RECORD_PATH="$2"; shift ;;
    *) echo "FAIL: unknown argument '$1' (usage: generate_array.sh [--check] [--record PATH])" >&2; exit 64 ;;
  esac
  shift
done

# ---- Preflight: nothing below this block writes before it has passed. ----
if [[ -z "${PDK_ROOT:-}" || -z "${PDK:-}" ]]; then
  echo "FAIL: PDK_ROOT/PDK not set -- run 'source design/env.sh' first. No artifacts were written." >&2
  exit 1
fi
if ! PREFLIGHT="$(python3 -I "${LAYOUT_DIR}/generation_toolchain.py" preflight --role generation --role check --pdk)"; then
  exit 2
fi
eval "${PREFLIGHT}"  # KLT_GENERATION, KLT_CHECK (+ their *_PYTHON)
export KLT_GENERATION_PYTHON KLT_CHECK_PYTHON
echo "== toolchains: generation=$("${KLT_GENERATION}" --version)  check=$("${KLT_CHECK}" --version)  (layout/generation-toolchain.json) =="
if [[ -n "${RECORD_PATH}" ]]; then
  mkdir -p "$(dirname "${RECORD_PATH}")"
  RECORD_PATH="$(cd "$(dirname "${RECORD_PATH}")" && pwd)/$(basename "${RECORD_PATH}")"
fi

META_DIR="$(mktemp -d)"
OUT_DIR="${LAYOUT_DIR}"
if [[ "${CHECK_MODE}" -eq 1 ]]; then
  OUT_DIR="$(mktemp -d)"
  if [[ -n "${KEEP_SCRATCH:-}" ]]; then
    echo "   scratch: ${OUT_DIR}  (run metadata: ${META_DIR})"
  fi
fi
cleanup() {
  [[ -n "${KEEP_SCRATCH:-}" ]] && return 0
  rm -rf "${META_DIR}"
  [[ "${OUT_DIR}" != "${LAYOUT_DIR}" ]] && rm -rf "${OUT_DIR}"
  return 0
}
trap cleanup EXIT

COMMANDS_LOG="${META_DIR}/commands.txt"
# Run a command, logging it (cwd + argv) for the run record.
run() {
  { printf '(cd %q &&' "${PWD}"; printf ' %q' "$@"; printf ')\n'; } >> "${COMMANDS_LOG}"
  "$@"
}
# Print a top-level JSON field, or "error" if the report is missing/unparsable.
json_field() {
  python3 -I -c 'import json,sys
try: print(json.load(open(sys.argv[1]))[sys.argv[2]])
except Exception: print("error")' "$1" "$2"
}

FAILS=()

cd "${OUT_DIR}"
if [[ "${OUT_DIR}" != "${LAYOUT_DIR}" ]]; then
  cp "${LAYOUT_DIR}/array_topology.py" .
fi

echo "== 1/7: klt gen mos_array (${ARRAY_TAG} bitcells = $((2 * N_ROWS * N_COLS)) devices, shared tap) [generation toolchain] =="
run "${KLT_GENERATION}" gen mos_array \
  --params "$(python3 array_topology.py --rows "${N_ROWS}" --cols "${N_COLS}" --emit gen-params)" \
  --pdk "${PDK}" --pdk-root "${PDK_ROOT}" \
  --cell-name gain_cell_2t_array_mos -o gain_cell_2t_array_mos.gds --format json \
  > gain_cell_2t_array_mos.json

echo "== 2/7: klt gen-compose (place, route wl/rwl/bl/rbl buses + per-cell sn, label GND) [generation toolchain] =="
python3 array_topology.py --rows "${N_ROWS}" --cols "${N_COLS}" --emit compose-request \
  --mos-report gain_cell_2t_array_mos.json \
  > gain_cell_2t_array.layout.request.json
run "${KLT_GENERATION}" gen-compose gain_cell_2t_array.layout.request.json --format json \
  > gain_cell_2t_array.layout.json
UNROUTED="$(python3 -c "import json;print(json.load(open('gain_cell_2t_array.layout.json')).get('unrouted_nets') or [])")"
echo "   unrouted_nets: ${UNROUTED}"
[[ "${UNROUTED}" == "[]" ]] || FAILS+=("klt gen-compose left net(s) unrouted: ${UNROUTED}")

echo "== 3/7: klt drc --deck sky130 (informal iteration, not a formal macro sign-off) [check toolchain] =="
run "${KLT_CHECK}" drc gain_cell_2t_array.gds --deck sky130 --format json > gain_cell_2t_array.drc.result.json || true
DRC_STATUS="$(json_field gain_cell_2t_array.drc.result.json status)"
echo "   drc status: ${DRC_STATUS}"
[[ "${DRC_STATUS}" == "clean" ]] || FAILS+=("klt drc reports '${DRC_STATUS}', expected 'clean'.")

echo "== 4/7: generate the array-level LVS reference netlist from design/gain_cell_2t.spice =="
SCH_SPICE_HASH="$(sha256sum "${DESIGN_SPICE}" | cut -d' ' -f1)"
python3 array_topology.py --rows "${N_ROWS}" --cols "${N_COLS}" --emit lvs-reference \
  --source-spice ../design/gain_cell_2t.spice --source-hash "${SCH_SPICE_HASH}" \
  > gain_cell_2t_array.lvs_reference.spice
python3 array_topology.py --rows "${N_ROWS}" --cols "${N_COLS}" --emit lvs-request \
  --gds-path gain_cell_2t_array.gds \
  --top-cell "gain_cell_2t_array_${ARRAY_TAG}_layout_0" \
  --reference-path gain_cell_2t_array.lvs_reference.spice \
  > gain_cell_2t_array.lvs.request.json

echo "== 5/7: klt lvs (informal iteration, not a formal macro sign-off) [check toolchain] =="
run "${KLT_CHECK}" lvs gain_cell_2t_array.lvs.request.json --format json > gain_cell_2t_array.lvs.result.json || true
LVS_STATUS="$(json_field gain_cell_2t_array.lvs.result.json status)"
echo "   lvs status: ${LVS_STATUS}"
[[ "${LVS_STATUS}" == "match" ]] || FAILS+=("klt lvs reports '${LVS_STATUS}', expected 'match'.")

# The ERC report is graded by `klt signoff` (T1 item 11), which re-reads the
# spec the report names relative to ITS cwd, so the committed report is
# produced from the repo root with repo-root-relative paths. (Scratch/--check
# runs use the scratch dir's own files and are not committed.)
echo "== 6/7: klt erc (supply spec incl. substrate tie, T1 item 11 evidence) [check toolchain] =="
if [[ "${CHECK_MODE}" -eq 1 ]]; then
  cp "${LAYOUT_DIR}/erc-supply-spec.json" .
  run "${KLT_CHECK}" erc gain_cell_2t_array.gds erc-supply-spec.json --pdk sky130 --format json \
    > gain_cell_2t_array.erc.result.json || true
  ERC_FILE="${OUT_DIR}/gain_cell_2t_array.erc.result.json"
else
  ( cd "${REPO_ROOT}" && run "${KLT_CHECK}" erc layout/gain_cell_2t_array.gds layout/erc-supply-spec.json \
      --pdk sky130 --format json > layout/gain_cell_2t_array.erc.result.json ) || true
  ERC_FILE="${LAYOUT_DIR}/gain_cell_2t_array.erc.result.json"
fi
ERC_STATUS="$(json_field "${ERC_FILE}" erc_status)"
echo "   erc status: ${ERC_STATUS}"
[[ "${ERC_STATUS}" == "clean" ]] || FAILS+=("klt erc reports '${ERC_STATUS}', expected 'clean'.")

echo "== 7/7: geometry/connectivity comparison with the committed ${BASELINE_TAG} array =="
COMPARISON_JSON="${META_DIR}/comparison.json"
if [[ "${ARRAY_TAG}" != "${BASELINE_TAG}" ]]; then
  COMPARISON="not-run"
  BASELINE="none: ${ARRAY_TAG} is not the committed ${BASELINE_TAG} size; this run validates the generated ${ARRAY_TAG} array only (routing/DRC/LVS/ERC) and does NOT reproduce the committed baseline"
  echo "   NOTE: ${BASELINE}."
elif [[ "${CHECK_MODE}" -eq 1 ]]; then
  BASELINE="committed layout/ artifacts in the working tree"
  if python3 -I "${LAYOUT_DIR}/compare_array_layout.py" --committed "${LAYOUT_DIR}" \
       --regenerated "${OUT_DIR}" -o "${COMPARISON_JSON}"; then
    COMPARISON="match"
  else
    COMPARISON="mismatch"
    FAILS+=("regenerated ${ARRAY_TAG} geometry/connectivity differs from the committed array (see the differences above).")
  fi
else
  # In-place regeneration: compare what was just written with git HEAD. Not
  # fatal -- --check is the reproduction gate -- but never silent.
  BASELINE="git HEAD:layout/ (in-place regeneration, informational)"
  mkdir -p "${META_DIR}/head"
  HEAD_OK=1
  for f in gain_cell_2t_array_mos.gds gain_cell_2t_array_mos.json gain_cell_2t_array.layout.request.json \
           gain_cell_2t_array.gds gain_cell_2t_array.layout.json gain_cell_2t_array.lvs_reference.spice \
           gain_cell_2t_array.lvs.request.json; do
    git -C "${REPO_ROOT}" show "HEAD:layout/${f}" > "${META_DIR}/head/${f}" 2>/dev/null || HEAD_OK=0
  done
  if [[ "${HEAD_OK}" -eq 0 ]]; then
    COMPARISON="not-run"
    echo "   NOTE: could not read the committed artifacts from git HEAD; comparison skipped."
  elif python3 -I "${LAYOUT_DIR}/compare_array_layout.py" --committed "${META_DIR}/head" \
         --regenerated "${LAYOUT_DIR}" -o "${COMPARISON_JSON}"; then
    COMPARISON="match"
  else
    COMPARISON="mismatch"
    echo "   WARNING: the in-place regeneration changed the committed layout geometry/connectivity." >&2
  fi
fi

RESULT="pass"
[[ ${#FAILS[@]} -eq 0 ]] || RESULT="fail"
python3 -I "${TOOLCHAIN}" record --out "${META_DIR}/generation_reproduction.json" \
  --script layout/generate_array.sh --mode "$([[ ${CHECK_MODE} -eq 1 ]] && echo check || echo in-place)" \
  --array "${ARRAY_TAG}" --baseline "${BASELINE}" --comparison "${COMPARISON_JSON}" \
  --commands "${COMMANDS_LOG}" \
  --status "unrouted_nets=${UNROUTED}" --status "drc=${DRC_STATUS}" --status "lvs=${LVS_STATUS}" \
  --status "erc=${ERC_STATUS}" --status "comparison=${COMPARISON}" --result "${RESULT}"
if [[ -n "${RECORD_PATH}" ]]; then
  cp "${META_DIR}/generation_reproduction.json" "${RECORD_PATH}"
  echo "   run record: ${RECORD_PATH}"
fi

if [[ ${#FAILS[@]} -gt 0 ]]; then
  for f in "${FAILS[@]}"; do echo "FAIL: ${f}" >&2; done
  exit 1
fi

echo "OK: ${ARRAY_TAG} shared-tap bitcell array layout regenerated (routed, DRC clean, LVS match, ERC clean; baseline comparison: ${COMPARISON})."
if [[ "${CHECK_MODE}" -eq 1 ]]; then
  echo "OK: --check mode -- committed layout/ artifacts left untouched."
fi
