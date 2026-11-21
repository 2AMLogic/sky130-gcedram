#!/usr/bin/env bash
# Reproducible klt pex invocations for issue #383: the schematic-vs-
# extracted stored-'1 retention comparison on the drawn bitcell and the
# 4x4 array, on the ratified retention row (spec/retention-refresh-budget
#.md §5, min = 1.005989e-5 s).
#
# What one invocation per cell does (klt pex 0.9.1, the .github/workflows/
# signoff.yml pin):
#   1. extracts a fresh PDK-bound parasitic netlist from the GDS
#      (--parasitics, --deck sky130 --pdk sky130A --pdk-root "$PDK_ROOT"),
#      writing it under work/<cell>/ (never into layout/);
#   2. runs sim/pex_bitcell_array/measure_pex_retention.py TWICE -- on the
#      committed study-local schematic reference, then on the fresh
#      extraction -- each leg a `klt sim --backend batch
#      --wait-for-capacity 600` grid over tt/ss/ff/sf/fs x -40/27/125 C;
#   3. emits the per-corner, per-spec-row delta envelope (unedited) to
#      results/klt_pex_<cell>_<RUN_ID>.json.
#
# Exit codes: klt pex exits 3 when a delta row failed its limit (a
# measured retention below the ratified benchmark -- evidence, not an
# error) and 4 when a row is unresolved (an unreachable threshold is null
# by design); both are recorded outcomes here. Exit 1 aborts the script.
#
# Environment:
#   PDK_ROOT        pinned open_pdks install (default ~/.ciel; the harness
#                   validates the SOURCES stamp against the repo pin)
#   GCEDRAM_KLT_BIN override for the pinned klt binary
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
STUDY=sim/pex_bitcell_array
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
WORK="$STUDY/work"
mkdir -p "$WORK" "$STUDY/results"

command -v uv >/dev/null || { echo "uv is required to build the pinned klt" >&2; exit 1; }

# Pinned klt 0.9.1 in a study-local venv (gitignored). The harness re-probes
# the version before every use, so a stale venv cannot silently serve a
# different klt.
KLT_VENV="$WORK/klt-0.9.1"
if [ ! -x "$KLT_VENV/bin/klt" ]; then
    uv venv "$KLT_VENV" >/dev/null
    uv pip install --quiet --python "$KLT_VENV/bin/python" "klayout-tools==0.9.1"
fi
KLT_BIN="${GCEDRAM_KLT_BIN:-$KLT_VENV/bin/klt}"
export GCEDRAM_KLT_BIN="$KLT_BIN"
"$KLT_BIN" --version

export PDK_ROOT="${PDK_ROOT:-$HOME/.ciel}"

# Study-local schematic references, regenerated from their named sources;
# test_pex_bitcell_array.py holds them fresh.
python3 -I "$STUDY/gen_reference_netlists.py"

run_cell() {
    local cell="$1" layout="$2" reference="$3"
    mkdir -p "$WORK/$cell"
    local envelope="$STUDY/results/klt_pex_${cell}_${RUN_ID}.json"
    if [ -e "$envelope" ]; then
        echo "refusing to overwrite $envelope" >&2
        exit 1
    fi
    echo "== klt pex $cell -> $envelope"
    local rc=0
    "$KLT_BIN" pex "$layout" \
        -o "$WORK/$cell/extracted.spice" \
        --deck sky130 --pdk sky130A --pdk-root "$PDK_ROOT" \
        --backend batch \
        --measure-command "python3 -I $STUDY/measure_pex_retention.py --cell $cell" \
        --reference-netlist "$reference" \
        --measure-timeout-s 7200 \
        --outdir "$WORK/$cell" \
        --envelope-out "$envelope" \
        --format json >"$WORK/$cell/pex_stdout.json" 2>"$WORK/$cell/pex_stderr.txt" || rc=$?
    echo "klt pex $cell exit $rc (0 pass / 3 failed-limit rows / 4 unresolved rows)"
    tail -5 "$WORK/$cell/pex_stderr.txt" || true
    if [ "$rc" -ne 0 ] && [ "$rc" -ne 3 ] && [ "$rc" -ne 4 ]; then
        echo "klt pex $cell failed to run (exit $rc); see $WORK/$cell/pex_stderr.txt" >&2
        exit "$rc"
    fi
}

# The bitcell first (issue guidance), then the array.
run_cell bitcell layout/gain_cell_2t.gds "$STUDY/reference/gain_cell_2t_schematic.spice"
run_cell array layout/gain_cell_2t_array.gds "$STUDY/reference/gain_cell_2t_array_4x4_schematic.spice"

echo "envelopes: $STUDY/results/klt_pex_bitcell_${RUN_ID}.json $STUDY/results/klt_pex_array_${RUN_ID}.json"
