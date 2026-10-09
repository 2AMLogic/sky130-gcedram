#!/usr/bin/env bash
# extract_array_parasitics.sh -- post-layout bitline/wordline/storage-node
# parasitic extraction of the committed shared-tap bitcell array (issue #80).
#
# Extraction only: no layout change. Two parts:
#
#   1. The COMMITTED 4x4 array (layout/gain_cell_2t_array.gds, produced by
#      layout/generate_array.sh) -> layout/gain_cell_2t_array.extract.parasitics.{spice,json}
#      `klt extract --parasitics` with EVERY bus net (wl_<r>, rwl_<r>, bl_<c>,
#      rbl_<c>) and every storage node (sn_<r>_<c>) named `--critical-net`,
#      so the lateral (same-layer sidewall) coupling pass covers every pair
#      that touches a signal net -- not only the storage node, as the
#      single-cell extraction (issue #7) did.
#
#   2. A row-count scaling set, regenerated in a SCRATCH directory (never
#      committed as layout): N_ROWS in {2, 4, 8} x N_COLS=4, each built with
#      the exact generate_array.sh recipe (array_topology.py -> klt gen
#      mos_array -> klt gen-compose), gated on unrouted_nets == [], DRC clean
#      and LVS match, then extracted with the same flags as part 1. The
#      scratch 4x4 must reproduce the committed 4x4's numbers.
#
# Both parts are reduced by array_parasitics.py into
# layout/gain_cell_2t_array.parasitics.summary.json (per-net table, the
# comparison against the 10 fF C_RBL and 0.605354 fF C_SN assumptions, and a
# fixed + per-row linear fit). Anything beyond N_ROWS=8 in that file is an
# extrapolation and is labelled ASSUMPTION there.
#
# Usage (from anywhere; paths are resolved against the repo root):
#   source design/env.sh
#   ./layout/extract_array_parasitics.sh
#
# Freshness of the committed extraction can be checked without re-running:
#   klt extract --check layout/gain_cell_2t_array.extract.parasitics.json   (from the repo root)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAYOUT_DIR="${REPO_ROOT}/layout"
DESIGN_SPICE="${REPO_ROOT}/design/gain_cell_2t.spice"
N_COLS=4
SCALING_ROWS=(2 4 8)

if ! command -v klt >/dev/null 2>&1; then
  echo "FAIL: klt (klayout-tools) not found on PATH -- see layout/README.md" >&2
  exit 1
fi
if [[ -z "${PDK_ROOT:-}" || -z "${PDK:-}" ]]; then
  echo "FAIL: PDK_ROOT/PDK not set -- run 'source design/env.sh' first" >&2
  exit 1
fi

# Every signal net of an R x C array, as repeated --critical-net flags.
critical_net_flags() {
  local rows="$1" cols="$2" r c
  for ((r = 0; r < rows; r++)); do
    printf -- '--critical-net\nwl_%d\n--critical-net\nrwl_%d\n' "$r" "$r"
  done
  for ((c = 0; c < cols; c++)); do
    printf -- '--critical-net\nbl_%d\n--critical-net\nrbl_%d\n' "$c" "$c"
  done
  for ((r = 0; r < rows; r++)); do
    for ((c = 0; c < cols; c++)); do
      printf -- '--critical-net\nsn_%d_%d\n' "$r" "$c"
    done
  done
}

echo "== 1/3: klt extract --parasitics on the committed 4x4 array =="
mapfile -t CRIT_4 < <(critical_net_flags 4 "${N_COLS}")
(
  cd "${REPO_ROOT}"
  klt extract layout/gain_cell_2t_array.gds --deck sky130 \
    --top gain_cell_2t_array_4x4_layout_0 --parasitics "${CRIT_4[@]}" \
    -o layout/gain_cell_2t_array.extract.parasitics.spice --format json \
    > layout/gain_cell_2t_array.extract.parasitics.json
)
STATUS="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['status'])" \
  "${LAYOUT_DIR}/gain_cell_2t_array.extract.parasitics.json")"
echo "   extract status: ${STATUS}"
if [[ "${STATUS}" != "extracted" ]]; then
  echo "FAIL: klt extract reports '${STATUS}', expected 'extracted'." >&2
  exit 1
fi

echo "== 2/3: row-count scaling set (scratch, N_ROWS in ${SCALING_ROWS[*]} x N_COLS=${N_COLS}) =="
SCRATCH="$(mktemp -d)"
# KEEP_SCRATCH=1 keeps the scratch arrays for inspection (path printed).
trap '[[ -n "${KEEP_SCRATCH:-}" ]] || rm -rf "${SCRATCH}"' EXIT
[[ -n "${KEEP_SCRATCH:-}" ]] && echo "   scratch: ${SCRATCH}"
SCH_SPICE_HASH="$(sha256sum "${DESIGN_SPICE}" | cut -d' ' -f1)"
SCALING_ARGS=()
for R in "${SCALING_ROWS[@]}"; do
  TAG="${R}x${N_COLS}"
  D="${SCRATCH}/${TAG}"
  mkdir -p "${D}"
  cp "${LAYOUT_DIR}/array_topology.py" "${D}/"
  (
    cd "${D}"
    klt gen mos_array \
      --params "$(python3 array_topology.py --rows "${R}" --cols "${N_COLS}" --emit gen-params)" \
      --pdk "${PDK}" --pdk-root "${PDK_ROOT}" \
      --cell-name gain_cell_2t_array_mos -o gain_cell_2t_array_mos.gds --format json \
      > gain_cell_2t_array_mos.json
    python3 array_topology.py --rows "${R}" --cols "${N_COLS}" --emit compose-request \
      --mos-report gain_cell_2t_array_mos.json > gain_cell_2t_array.layout.request.json
    klt gen-compose gain_cell_2t_array.layout.request.json --format json \
      > gain_cell_2t_array.layout.json
    klt drc gain_cell_2t_array.gds --deck sky130 --format json > drc.json
    python3 array_topology.py --rows "${R}" --cols "${N_COLS}" --emit lvs-reference \
      --source-spice "${DESIGN_SPICE}" --source-hash "${SCH_SPICE_HASH}" \
      > gain_cell_2t_array.lvs_reference.spice
    python3 array_topology.py --rows "${R}" --cols "${N_COLS}" --emit lvs-request \
      --gds-path gain_cell_2t_array.gds \
      --top-cell "gain_cell_2t_array_${TAG}_layout_0" \
      --reference-path gain_cell_2t_array.lvs_reference.spice \
      > lvs.request.json
    klt lvs lvs.request.json --format json > lvs.json || true
    mapfile -t CRIT < <(critical_net_flags "${R}" "${N_COLS}")
    klt extract gain_cell_2t_array.gds --deck sky130 \
      --top "gain_cell_2t_array_${TAG}_layout_0" --parasitics "${CRIT[@]}" \
      -o extract.parasitics.spice --format json > extract.parasitics.json
  )
  python3 - "${D}" "${TAG}" <<'PY'
import json, sys
d, tag = sys.argv[1], sys.argv[2]
unrouted = json.load(open(f"{d}/gain_cell_2t_array.layout.json")).get("unrouted_nets") or []
drc = json.load(open(f"{d}/drc.json"))["status"]
lvs = json.load(open(f"{d}/lvs.json"))["status"]
ext = json.load(open(f"{d}/extract.parasitics.json"))["status"]
print(f"   {tag}: unrouted={unrouted} drc={drc} lvs={lvs} extract={ext}")
json.dump({"unrouted_nets": unrouted, "drc_status": drc, "lvs_status": lvs},
          open(f"{d}/gates.json", "w"))
if unrouted or drc != "clean" or lvs != "match" or ext != "extracted":
    sys.exit(f"FAIL: {tag} scaling array did not pass its gates")
PY
  SCALING_ARGS+=(--scaling "${R}:${D}/extract.parasitics.json:${D}/gates.json")
done

echo "== 3/3: reduce to layout/gain_cell_2t_array.parasitics.summary.json =="
python3 "${LAYOUT_DIR}/array_parasitics.py" \
  --committed "${LAYOUT_DIR}/gain_cell_2t_array.extract.parasitics.json" \
  --single-cell "${LAYOUT_DIR}/gain_cell_2t.extract.parasitics.json" \
  "${SCALING_ARGS[@]}" \
  -o "${LAYOUT_DIR}/gain_cell_2t_array.parasitics.summary.json"
echo "OK: array parasitic extraction + summary written."
