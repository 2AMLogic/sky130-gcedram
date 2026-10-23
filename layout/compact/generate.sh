#!/usr/bin/env bash
# generate.sh -- reproducibly regenerate and verify the compaction variants of
# the 2T gain-cell array (issue #100). Layout comes from gen_compact.py
# (KLayout Python API; `klt gen mos_array` has no pitch / diffusion-sharing
# knob), checks come from the pinned `check` klt toolchain
# (layout/generation-toolchain.json) plus three stricter checks the klt deck
# lacks (klayout_mr_drc.py: the PDK's own KLayout runset; check_extra_rules.py
# and magic_drc.py: gate-level rules, the latter from the PDK's magic tech file).
#
# Usage:
#   ./layout/compact/generate.sh            # write layout/compact/* (v1 v2)
#   ./layout/compact/generate.sh --check    # regenerate in a scratch dir, assert
#                                           # the GDS is byte-identical to the
#                                           # committed one and all gates pass;
#                                           # never touches committed files
#   VARIANTS="v2" ./layout/compact/generate.sh
#
# One-time setup:  source design/env.sh
#                  python3 layout/generation_toolchain.py install --role check
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HERE="${REPO_ROOT}/layout/compact"
VARIANTS="${VARIANTS:-v1 v2}"
ROWS=4; COLS=4
CHECK=0
[[ "${1:-}" == "--check" ]] && CHECK=1

if [[ -z "${PDK_ROOT:-}" || -z "${PDK:-}" ]]; then
  echo "FAIL: PDK_ROOT/PDK not set -- run 'source design/env.sh' first." >&2; exit 1
fi
PREFLIGHT="$(python3 -I "${REPO_ROOT}/layout/generation_toolchain.py" preflight --role check --pdk)" || exit 2
eval "${PREFLIGHT}"                       # KLT_CHECK, KLT_CHECK_PYTHON
PY="${KLT_CHECK_PYTHON}"                  # klayout==0.30.12 (pinned)

OUT="${HERE}"
if [[ "${CHECK}" -eq 1 ]]; then OUT="$(mktemp -d)"; trap 'rm -rf "${OUT}"' EXIT; fi
FAILS=()

for V in ${VARIANTS}; do
  STEM="gain_cell_2t_${V}_array"; TOP="${STEM}_${ROWS}x${COLS}_layout_0"
  echo "== ${V}: generate =="
  "${PY}" -I "${HERE}/gen_compact.py" --variant "${V}" --rows "${ROWS}" --cols "${COLS}" --out "${OUT}"
  cd "${OUT}"
  echo "== ${V}: klt drc (sky130 deck) =="
  "${KLT_CHECK}" drc "${STEM}.gds" --deck sky130 --format json > "${STEM}.drc.result.json" 2>/dev/null || true
  echo "== ${V}: klt lvs =="
  "${KLT_CHECK}" lvs "${STEM}.lvs.request.json" --format json > "${STEM}.lvs.result.json" 2>/dev/null || true
  echo "== ${V}: sky130A_mr.drc (KLayout runset shipped with the PDK) =="
  "${PY}" -I "${HERE}/klayout_mr_drc.py" "${STEM}.gds" "${TOP}" --json "${STEM}.mr_drc.result.json" || FAILS+=("${V}: sky130A_mr.drc")
  echo "== ${V}: extra gate-level rules =="
  "${PY}" -I "${HERE}/check_extra_rules.py" "${STEM}.gds" --json "${STEM}.extra_rules.result.json" || FAILS+=("${V}: extra rules")
  echo "== ${V}: magic drc(full) =="
  "${PY}" -I "${HERE}/magic_drc.py" "${STEM}.gds" "${TOP}" --json "${STEM}.magic_drc.result.json" || FAILS+=("${V}: magic drc")
  for pair in "drc.result:status:clean" "lvs.result:status:match"; do
    f="${STEM}.${pair%%:*}.json"; key="$(cut -d: -f2 <<<"${pair}")"; want="${pair##*:}"
    got="$(python3 -I -c 'import json,sys;print(json.load(open(sys.argv[1]))[sys.argv[2]])' "${f}" "${key}")"
    echo "   ${f}: ${key}=${got}"
    [[ "${got}" == "${want}" ]] || FAILS+=("${V}: ${f} ${key}=${got}, expected ${want}")
  done
  if [[ "${CHECK}" -eq 1 ]]; then
    for f in "${STEM}.gds" "${STEM}.layout.json" "${STEM}_mos.json" "${STEM}.lvs_reference.spice" "${STEM}.lvs.request.json"; do
      cmp -s "${f}" "${HERE}/${f}" || FAILS+=("${V}: ${f} differs from the committed file")
    done
  fi
  cd "${REPO_ROOT}"
done

if [[ ${#FAILS[@]} -gt 0 ]]; then
  for f in "${FAILS[@]}"; do echo "FAIL: ${f}" >&2; done; exit 1
fi
echo "OK: ${VARIANTS} regenerated; klt drc clean, klt lvs match, sky130A_mr + extra rules + magic drc(full) clean."
