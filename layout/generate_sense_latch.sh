#!/usr/bin/env bash
# generate_sense_latch.sh -- reproducible sky130 layout capture for the
# six-device sense latch (issue #387: the physical deliverable for #382's
# sense amplifier), driven entirely by klayout-tools (`klt`) against the
# canonical netlist committed as design/sense_latch.spice (issue #109).
#
# Like layout/generate_array.sh (whose split-toolchain shape this script
# follows), this does NOT draw layout by hand: layout/sense_latch_topology.py
# parses the canonical netlist's six X cards and derives every generation
# input from them -- the `klt gen` params for the five blocks (mirrored
# cross-coupled nmos/pmos pairs, footer, header, substrate tap), the
# `klt gen-compose` request (placement, connectivity, the explicit
# cross-coupling routing), and the plain-element LVS reference netlist
# with the source netlist's sha256 pinned in its header -- so the layout,
# its request and the reference `klt lvs` compares against can never
# silently drift from the design source.
#
# Toolchains: the same two pinned klt revisions layout/generation-toolchain.json
# already records for the array (issue #91) -- `generation` (klt gen /
# gen-compose) and `check` (klt drc / klt lvs), verified by
# layout/generation_toolchain.py BEFORE anything is written. `klt` on PATH
# is not used.
#
# Usage:
#   ./layout/generate_sense_latch.sh              # regenerate every
#                                                  # layout/sense_latch* artifact
#                                                  # in place
#   ./layout/generate_sense_latch.sh --check      # regenerate in a scratch dir,
#                                                  # byte-compare the stream (and
#                                                  # every plain-text artifact)
#                                                  # with the committed ones --
#                                                  # falling back to
#                                                  # layout/xor_layout_geometry.py
#                                                  # per drawn layer if the bytes
#                                                  # differ -- and assert routed +
#                                                  # DRC clean + 6-device LVS match
#                                                  # with verified body ties;
#                                                  # never touches committed artifacts
#   KEEP_SCRATCH=1 ./layout/generate_sense_latch.sh --check
#                                                  # keep the scratch dir (path printed)
#
# Requires PDK_ROOT/PDK exported (source design/env.sh first), at the pinned
# open_pdks commit (docs/pdk-pin.md).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAYOUT_DIR="${REPO_ROOT}/layout"
TOPOLOGY="${LAYOUT_DIR}/sense_latch_topology.py"
SOURCE_SPICE="${REPO_ROOT}/design/sense_latch.spice"

CHECK_MODE=0
if [[ "${1:-}" == "--check" ]]; then
  CHECK_MODE=1
elif [[ -n "${1:-}" ]]; then
  echo "FAIL: unknown argument '${1}' (usage: generate_sense_latch.sh [--check])" >&2
  exit 64
fi

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

FAILS=()

# Run a command, echoing it for the surrounding log (stderr, so a caller's
# stdout redirection captures only the command's own output).
run() {
  echo "   \$ $*" >&2
  "$@"
}
json_field() {
  python3 -I -c 'import json,sys
try:
    v = json.load(open(sys.argv[1]))
    for key in sys.argv[2].split("."):
        v = v[key]
    print(v)
except Exception: print("error")' "$1" "$2"
}

# The five blocks: id -> generator verb (sense_latch_topology.py names the
# files sense_latch_<block>_mos.json / sense_latch_ptap.json).
emit_params() {  # <block> -> params JSON on stdout
  python3 -I "${TOPOLOGY}" --emit gen-params --block "$1" --source-spice "${SOURCE_SPICE}"
}

echo "== 1/6: klt gen blocks (npair/ppair mirrored pairs, footer, header, ptap) [generation toolchain] =="
cd "${OUT_DIR}"
for block in npair ppair footer header; do
  emit_params "${block}" > "${META_DIR}/params_${block}.json"
  run "${KLT_GENERATION}" gen mos_array \
    --params "${META_DIR}/params_${block}.json" \
    --pdk "${PDK}" --pdk-root "${PDK_ROOT}" \
    --cell-name "sense_latch_${block}" -o "sense_latch_${block}_mos.gds" --format json \
    > "sense_latch_${block}_mos.json"
done
emit_params ptap > "${META_DIR}/params_ptap.json"
run "${KLT_GENERATION}" gen guard_ring \
  --params "${META_DIR}/params_ptap.json" \
  --pdk "${PDK}" --pdk-root "${PDK_ROOT}" \
  --cell-name sense_latch_ptap -o sense_latch_ptap.gds --format json \
  > sense_latch_ptap.json

echo "== 2/6: emit + run klt gen-compose (place, route rbl/ref/vn/vp/GND/vdd, label en/enb) [generation toolchain] =="
( cd "${REPO_ROOT}" && python3 -I "${TOPOLOGY}" --emit compose-request \
    --source-spice design/sense_latch.spice --reports-dir "${OUT_DIR}" \
    > "${OUT_DIR}/sense_latch.layout.request.json" )
run "${KLT_GENERATION}" gen-compose sense_latch.layout.request.json --format json \
  > sense_latch.layout.json
UNROUTED="$(python3 -I -c "import json;print(json.load(open('sense_latch.layout.json')).get('unrouted_nets') or [])")"
echo "   unrouted_nets: ${UNROUTED}"
[[ "${UNROUTED}" == "[]" ]] || FAILS+=("klt gen-compose left net(s) unrouted: ${UNROUTED}")

echo "== 3/6: klt drc --deck sky130 [check toolchain] =="
run "${KLT_CHECK}" drc sense_latch.gds --deck sky130 --format json > sense_latch.drc.result.json || true
DRC_STATUS="$(json_field sense_latch.drc.result.json status)"
echo "   drc status: ${DRC_STATUS}"
[[ "${DRC_STATUS}" == "clean" ]] || FAILS+=("klt drc reports '${DRC_STATUS}', expected 'clean'.")

echo "== 4/6: klt extract (evidence in the run metadata dir, not committed) [check toolchain] =="
run "${KLT_CHECK}" extract sense_latch.gds --deck sky130 --top sense_latch_layout_0 \
  -o "${META_DIR}/sense_latch.extract.spice" --format json > "${META_DIR}/sense_latch.extract.json" || true
# The six-device contract: three nfets with body=GND, three pfets with
# body=vdd, W/L as parsed from the canonical netlist.
if ! python3 -I "${TOPOLOGY}" --check-extract "${META_DIR}/sense_latch.extract.json" \
     --source-spice "${SOURCE_SPICE}" > "${META_DIR}/extract_check.txt"; then
  cat "${META_DIR}/extract_check.txt" || true
  FAILS+=("extracted netlist does not match the canonical six-device contract (see output above)")
else
  echo "   extract: $(tail -1 "${META_DIR}/extract_check.txt")"
fi

echo "== 5/6: generate the LVS reference from design/sense_latch.spice + klt lvs [check toolchain] =="
SCH_SPICE_HASH="$(sha256sum "${SOURCE_SPICE}" | cut -d' ' -f1)"
( cd "${REPO_ROOT}" && python3 -I "${TOPOLOGY}" --emit lvs-reference \
    --source-spice design/sense_latch.spice --source-hash "${SCH_SPICE_HASH}" \
    > "${OUT_DIR}/sense_latch.lvs_reference.spice" )
( cd "${REPO_ROOT}" && python3 -I "${TOPOLOGY}" --emit lvs-request \
    > "${OUT_DIR}/sense_latch.lvs.request.json" )
run "${KLT_CHECK}" lvs sense_latch.lvs.request.json --format json > sense_latch.lvs.result.json || true
LVS_STATUS="$(json_field sense_latch.lvs.result.json status)"
LVS_BODY="$(json_field sense_latch.lvs.result.json body_verification.status)"
LVS_DEVICES="$(python3 -I -c "
import json
try: c = json.load(open('sense_latch.lvs.result.json'))['counts']['devices']
except Exception: c = {}
print(c.get('layout'), c.get('reference'), c.get('matched'))")"
echo "   lvs status: ${LVS_STATUS}  body_verification: ${LVS_BODY}  devices: ${LVS_DEVICES}"
[[ "${LVS_STATUS}" == "match" ]] || FAILS+=("klt lvs reports '${LVS_STATUS}', expected 'match'.")
[[ "${LVS_BODY}" == "verified" ]] || FAILS+=("klt lvs body_verification reports '${LVS_BODY}', expected 'verified'.")
[[ "${LVS_DEVICES}" == "6 6 6" ]] \
  || FAILS+=("klt lvs device counts '${LVS_DEVICES}' != 6 6 6 layout/reference/matched.")

echo "== 6/6: comparison with the committed latch =="
COMPARISON="not-run"
if [[ "${CHECK_MODE}" -ne 1 ]]; then
  echo "   in-place regeneration: committed layout/sense_latch* artifacts were just rewritten; --check is the reproduction gate."
else
  # Byte-compare every artifact the script produces (GDS streams under the
  # pinned generation klt are byte-stable -- same inputs, same bytes; see
  # layout/README.md). A byte difference on the stream is NOT by itself a
  # failure: fall back to layout/xor_layout_geometry.py's per-drawn-layer
  # XOR + bounding-box + label comparison, the same equivalence bar
  # generation-toolchain.json's generation pin cites for the array.
  BYTE_DIFFS=()
  for f in sense_latch.gds sense_latch.layout.request.json sense_latch.layout.json \
           sense_latch.lvs_reference.spice sense_latch.lvs.request.json \
           sense_latch_npair_mos.gds sense_latch_npair_mos.json \
           sense_latch_ppair_mos.gds sense_latch_ppair_mos.json \
           sense_latch_footer_mos.gds sense_latch_footer_mos.json \
           sense_latch_header_mos.gds sense_latch_header_mos.json \
           sense_latch_ptap.gds sense_latch_ptap.json; do
    if ! cmp -s "${LAYOUT_DIR}/${f}" "${OUT_DIR}/${f}"; then
      BYTE_DIFFS+=("${f}")
    fi
  done
  if [[ ${#BYTE_DIFFS[@]} -eq 0 ]]; then
    COMPARISON="byte-identical"
    echo "   all 15 artifacts byte-identical with the committed ones."
  else
    echo "   byte differences: ${BYTE_DIFFS[*]}"
    for f in "${BYTE_DIFFS[@]}"; do
      case "${f}" in
        sense_latch.gds)
          # Drawn layers of the committed latch (13 pairs; enumerate, never
          # count -- layout/xor_layout_geometry.py's own rule). The label-only
          # pairs 67/5, 68/5, 69/5 are compared by the tool's label check.
          if "${KLT_CHECK_PYTHON}" -I "${LAYOUT_DIR}/xor_layout_geometry.py" \
               --committed "${LAYOUT_DIR}/sense_latch.gds" \
               --regenerated "${OUT_DIR}/sense_latch.gds" \
               --top sense_latch_layout_0 \
               --expect-drawn-layer 64/20 --expect-drawn-layer 65/20 \
               --expect-drawn-layer 65/44 --expect-drawn-layer 66/20 \
               --expect-drawn-layer 66/44 --expect-drawn-layer 67/20 \
               --expect-drawn-layer 67/44 --expect-drawn-layer 68/20 \
               --expect-drawn-layer 68/44 --expect-drawn-layer 69/20 \
               --expect-drawn-layer 93/44 --expect-drawn-layer 94/20 \
               --expect-drawn-layer 95/20 \
               -o "${META_DIR}/geometry_xor.json"; then
            echo "   sense_latch.gds: geometry XOR empty on every drawn layer, bbox and labels match."
          else
            COMPARISON="mismatch"
            FAILS+=("regenerated sense_latch.gds differs from the committed stream beyond the XOR-equivalence bar (see above).")
          fi
          ;;
        *)
          COMPARISON="mismatch"
          FAILS+=("regenerated ${f} is not byte-identical with the committed artifact (plain-text artifacts have no XOR fallback).")
          ;;
      esac
    done
    [[ "${COMPARISON}" != "mismatch" ]] && COMPARISON="xor-equivalent"
  fi
fi

if [[ ${#FAILS[@]} -gt 0 ]]; then
  for f in "${FAILS[@]}"; do echo "FAIL: ${f}" >&2; done
  exit 1
fi

echo "OK: six-device sense-latch layout regenerated (routed, DRC clean, LVS match with verified body ties; baseline comparison: ${COMPARISON})."
if [[ "${CHECK_MODE}" -eq 1 ]]; then
  echo "OK: --check mode -- committed layout/ artifacts left untouched."
fi
