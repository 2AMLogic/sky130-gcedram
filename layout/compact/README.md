# layout/compact -- bitcell-compaction variants (issue #100)

Reproducible compact layouts of the ratified 2T gain cell (two
`sky130_fd_pr__nfet_01v8`, W = 0.42 um, L = 0.15 um; topology unchanged) and
the checks that grade them. The write-up with results, comparison and caveats
is the Addendum in [`spec/density-vs-sram.md`](../../spec/density-vs-sram.md).
Nothing in `layout/gain_cell_2t*` (the committed uniform-grid baseline) is
modified.

## Why not `klt gen`

`klt gen mos_array` draws identical isolated unit devices on a fixed grid and
has no pitch, shared-source/drain or mirror parameter, so no parameter set
compacts the baseline (gap filed generically as
[klayout-tools#3299](https://github.com/2AMLogic/klayout-tools/issues/3299)).
`gen_compact.py` draws the same devices with KLayout's Python API instead.
The generated GDS is byte-reproducible (no GDS timestamps).

| File | Role |
|---|---|
| `gen_compact.py` | generator: `--variant v1\|v2 --rows 4 --cols 4 --out DIR` |
| `generate.sh` | regenerate + run every gate; `--check` = scratch run, GDS must be byte-identical to the committed one |
| `check_extra_rules.py` | gate-level spacing/enclosure rules the klt deck lacks |
| `klayout_mr_drc.py` | the `sky130A_mr.drc` KLayout runset shipped with the PDK |
| `magic_drc.py` | `drc(full)` from the pinned PDK's magic tech file (check-only implant copy) |
| `test_compact.py` | stdlib-only consistency test (run in CI) |
| `gain_cell_2t_<v>_array.*` | committed GDS, layout/mos/LVS inputs and the five check results per variant |

Variants: `v1` (isolated stacked devices, 0.985 x 1.98 um) and `v2` (adds
mirrored-pair diffusion sharing, 0.985 x 1.42 um). Both are 4 rows x 4 columns
with the same style of tap ring as the baseline (0.5 um clearance).

## Reproduce

```bash
source design/env.sh                                   # PDK_ROOT / PDK
python3 layout/generation_toolchain.py install --role check   # one time
./layout/compact/generate.sh            # rewrites the files above
./layout/compact/generate.sh --check    # verify without touching them
python3 -I layout/compact/test_compact.py
python3 -I layout/area_density.py --tag v2 --issue 100 \
    --layout-json layout/compact/gain_cell_2t_v2_array.layout.json \
    --mos-json    layout/compact/gain_cell_2t_v2_array_mos.json \
    --gds         layout/compact/gain_cell_2t_v2_array.gds
```

`generate.sh` needs `magic` and the `klayout` binary on `PATH` for the last
two gates. These are not "sign-off": no implant/npc/well layers are drawn
(same simplification as the committed `mos_array` layout) and ERC, antenna and
density checks were not run.
