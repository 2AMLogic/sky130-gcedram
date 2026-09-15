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
#
# Usage:
#   ./layout/generate_array.sh              # regenerate every layout/*array*
#                                            # artifact in place (N_ROWS=N_COLS=4)
#   ./layout/generate_array.sh --check      # regenerate to a scratch dir and
#                                            # assert DRC-clean + LVS-match
#                                            # against the committed lvs
#                                            # reference; does not overwrite
#                                            # committed artifacts
#   N_ROWS=2 N_COLS=2 ./layout/generate_array.sh --check
#                                            # override the array size (env
#                                            # vars) -- see layout/README.md
#                                            # for which sizes this script has
#                                            # actually been verified against
#
# Requires PDK_ROOT/PDK exported (source design/env.sh first) and `klt`
# (klayout-tools) on PATH -- see layout/README.md.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAYOUT_DIR="${REPO_ROOT}/layout"
DESIGN_SPICE="${REPO_ROOT}/design/gain_cell_2t.spice"

N_ROWS="${N_ROWS:-4}"
N_COLS="${N_COLS:-4}"
ARRAY_TAG="${N_ROWS}x${N_COLS}"

CHECK_MODE=0
if [[ "${1:-}" == "--check" ]]; then
  CHECK_MODE=1
fi

if ! command -v klt >/dev/null 2>&1; then
  echo "FAIL: klt (klayout-tools) not found on PATH -- see layout/README.md" >&2
  exit 1
fi
if [[ -z "${PDK_ROOT:-}" || -z "${PDK:-}" ]]; then
  echo "FAIL: PDK_ROOT/PDK not set -- run 'source design/env.sh' first" >&2
  exit 1
fi

OUT_DIR="${LAYOUT_DIR}"
if [[ "${CHECK_MODE}" -eq 1 ]]; then
  OUT_DIR="$(mktemp -d)"
  trap 'rm -rf "${OUT_DIR}"' EXIT
fi

cd "${OUT_DIR}"
if [[ "${OUT_DIR}" != "${LAYOUT_DIR}" ]]; then
  cp "${LAYOUT_DIR}/array_topology.py" .
fi

echo "== 1/5: klt gen mos_array (${ARRAY_TAG} bitcells = $((2 * N_ROWS * N_COLS)) devices, shared tap) =="
klt gen mos_array \
  --params "$(python3 array_topology.py --rows "${N_ROWS}" --cols "${N_COLS}" --emit gen-params)" \
  --pdk "${PDK}" --pdk-root "${PDK_ROOT}" \
  --cell-name gain_cell_2t_array_mos -o gain_cell_2t_array_mos.gds --format json \
  > gain_cell_2t_array_mos.json

echo "== 2/5: klt gen-compose (place, route wl/rwl/bl/rbl buses + per-cell sn, label GND) =="
python3 array_topology.py --rows "${N_ROWS}" --cols "${N_COLS}" --emit compose-request \
  --mos-report gain_cell_2t_array_mos.json \
  > gain_cell_2t_array.layout.request.json
klt gen-compose gain_cell_2t_array.layout.request.json --format json \
  > gain_cell_2t_array.layout.json
UNROUTED="$(python3 -c "import json;print(json.load(open('gain_cell_2t_array.layout.json')).get('unrouted_nets') or [])")"
echo "   unrouted_nets: ${UNROUTED}"
if [[ "${UNROUTED}" != "[]" ]]; then
  echo "FAIL: klt gen-compose left net(s) unrouted: ${UNROUTED}" >&2
  exit 1
fi

echo "== 3/5: klt drc --deck sky130 (informal iteration, not a formal macro sign-off) =="
klt drc gain_cell_2t_array.gds --deck sky130 --format json > gain_cell_2t_array.drc.result.json
DRC_STATUS="$(python3 -c "import json;print(json.load(open('gain_cell_2t_array.drc.result.json'))['status'])")"
echo "   drc status: ${DRC_STATUS}"

echo "== 4/5: generate the array-level LVS reference netlist from design/gain_cell_2t.spice =="
SCH_SPICE_HASH="$(sha256sum "${DESIGN_SPICE}" | cut -d' ' -f1)"
python3 array_topology.py --rows "${N_ROWS}" --cols "${N_COLS}" --emit lvs-reference \
  --source-spice ../design/gain_cell_2t.spice --source-hash "${SCH_SPICE_HASH}" \
  > gain_cell_2t_array.lvs_reference.spice
python3 array_topology.py --rows "${N_ROWS}" --cols "${N_COLS}" --emit lvs-request \
  --gds-path gain_cell_2t_array.gds \
  --top-cell "gain_cell_2t_array_${ARRAY_TAG}_layout_0" \
  --reference-path gain_cell_2t_array.lvs_reference.spice \
  > gain_cell_2t_array.lvs.request.json

echo "== 5/5: klt lvs (informal iteration, not a formal macro sign-off) =="
klt lvs gain_cell_2t_array.lvs.request.json --format json > gain_cell_2t_array.lvs.result.json
LVS_STATUS="$(python3 -c "import json;print(json.load(open('gain_cell_2t_array.lvs.result.json'))['status'])")"
echo "   lvs status: ${LVS_STATUS}"

if [[ "${DRC_STATUS}" != "clean" ]]; then
  echo "FAIL: klt drc reports '${DRC_STATUS}', expected 'clean'." >&2
  exit 1
fi
if [[ "${LVS_STATUS}" != "match" ]]; then
  echo "FAIL: klt lvs reports '${LVS_STATUS}', expected 'match'." >&2
  exit 1
fi

echo "OK: ${ARRAY_TAG} shared-tap bitcell array layout regenerated (DRC clean, LVS match against gain_cell_2t_array.lvs_reference.spice)."
if [[ "${CHECK_MODE}" -eq 1 ]]; then
  echo "OK: --check mode -- committed layout/ artifacts left untouched."
fi
