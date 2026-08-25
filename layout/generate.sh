#!/usr/bin/env bash
# generate.sh -- reproducible sky130 layout capture for the 2T gain-cell
# bitcell (issue #15, T1 item 2: layout), driven entirely by klayout-tools
# (`klt`) against the ratified schematic/netlist committed by issue #14
# (design/gain_cell_2t.sch, design/gain_cell_2t.spice).
#
# This does NOT draw layout by hand: it composes klt's own parametrized
# layout generators (`klt gen`) with klt's block-placement/router
# (`klt gen-compose`), sized and wired to exactly the two devices and the
# exact connectivity design/gain_cell_2t.spice declares -- so the layout is
# reproducible from committed *inputs* (this script + the klt generator
# params below), the same "presence AND reproducibility" bar
# design/regen_netlist.sh already meets for the schematic -> netlist step.
#
# What gets built (see layout/README.md "Topology mapping" for the full
# device-by-device correspondence back to design/gain_cell_2t.sch):
#   1. `mos_array` generator -> two independent W=0.42um L=0.15um nfets
#      (U0 = M_WR, U1 = M_RD), gate_contact=true so both gates are routable.
#   2. `guard_ring` generator (add_well=false) -> a P-substrate tap, so the
#      composed layout's extracted NMOS body terminal resolves to a real
#      "GND" net instead of the deck's synthesized global (see
#      docs/cli/extract.md "NMOS body" in 2AMLogic/klayout-tools) --
#      matching design/gain_cell_2t.spice's explicit body=GND on both
#      devices.
#   3. `klt gen-compose` places both blocks, routes the one inter-device net
#      (`sn`: M_WR's drain to M_RD's gate) on a second metal level (the
#      self-net bus would otherwise cross M_RD's own source pad on li1 --
#      see docs/cli/gen-compose.md "Cross-block bus routing"), and labels
#      wl/bl/rwl/rbl/GND as top-level pins.
#
# Usage:
#   ./layout/generate.sh            # regenerate every layout/*.gds/*.json
#                                    # artifact in place
#   ./layout/generate.sh --check    # regenerate to a scratch dir and assert
#                                    # DRC-clean + LVS-match against the
#                                    # committed lvs reference; does not
#                                    # overwrite the committed artifacts
#                                    # (GDS streams embed a generation
#                                    # timestamp per the GDSII spec, so a
#                                    # byte-for-byte diff against the
#                                    # committed .gds is not a meaningful
#                                    # staleness check the way
#                                    # design/regen_netlist.sh's plain-text
#                                    # netlist diff is -- LVS/DRC status is
#                                    # the reproducibility gate here instead)
#
# Requires PDK_ROOT/PDK exported (source design/env.sh first) and `klt`
# (klayout-tools) on PATH -- see layout/README.md.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAYOUT_DIR="${REPO_ROOT}/layout"

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

echo "== 1/4: klt gen mos_array (U0=M_WR, U1=M_RD) =="
klt gen mos_array \
  --params '{"w_um":0.42,"l_um":0.15,"fingers":1,"rows":1,"cols":2,"dummy":0,"topology":"array","flavor":"nfet","gate_contact":true}' \
  --pdk "${PDK}" --pdk-root "${PDK_ROOT}" \
  --cell-name gain_cell_2t_mos -o gain_cell_2t_mos.gds --format json \
  > gain_cell_2t_mos.json

echo "== 2/4: klt gen guard_ring (P-substrate tap, add_well=false) =="
klt gen guard_ring \
  --params '{"inner_width_um":1.0,"inner_height_um":1.0,"ring_width_um":0.42,"contacts_per_side":2,"add_well":false}' \
  --pdk "${PDK}" --pdk-root "${PDK_ROOT}" \
  --cell-name gain_cell_2t_tap -o gain_cell_2t_tap.gds --format json \
  > gain_cell_2t_tap.json

echo "== 3/4: klt gen-compose (place, route sn, label wl/bl/rwl/rbl/GND) =="
if [[ "${OUT_DIR}" != "${LAYOUT_DIR}" ]]; then
  cp "${LAYOUT_DIR}/gain_cell_2t.layout.request.json" .
fi
klt gen-compose gain_cell_2t.layout.request.json --format json \
  > gain_cell_2t.layout.json

echo "== 4/4: informal DRC/extract/LVS iteration (geometry-capture check, not a formal sign-off) =="
klt drc gain_cell_2t.gds --deck sky130 --format json > gain_cell_2t.drc.result.json
DRC_STATUS="$(python3 -c "import json;print(json.load(open('gain_cell_2t.drc.result.json'))['status'])")"
echo "   drc status: ${DRC_STATUS}"

klt extract gain_cell_2t.gds --deck sky130 --top gain_cell_2t_layout_0 \
  -o gain_cell_2t.extract.spice --format json > gain_cell_2t.extract.json

if [[ "${OUT_DIR}" != "${LAYOUT_DIR}" ]]; then
  cp "${LAYOUT_DIR}/gain_cell_2t.lvs_reference.spice" .
  cp "${LAYOUT_DIR}/gain_cell_2t.lvs.request.json" .
fi
klt lvs gain_cell_2t.lvs.request.json --format json > gain_cell_2t.lvs.result.json
LVS_STATUS="$(python3 -c "import json;print(json.load(open('gain_cell_2t.lvs.result.json'))['status'])")"
echo "   lvs status: ${LVS_STATUS}"

if [[ "${DRC_STATUS}" != "clean" ]]; then
  echo "FAIL: klt drc reports '${DRC_STATUS}', expected 'clean'." >&2
  exit 1
fi
if [[ "${LVS_STATUS}" != "match" ]]; then
  echo "FAIL: klt lvs reports '${LVS_STATUS}', expected 'match'." >&2
  exit 1
fi

echo "OK: 2T-min bitcell layout regenerated (DRC clean, LVS match against gain_cell_2t.lvs_reference.spice)."
if [[ "${CHECK_MODE}" -eq 1 ]]; then
  echo "OK: --check mode -- committed layout/ artifacts left untouched."
fi
