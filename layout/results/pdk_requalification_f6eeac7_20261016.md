# G5 (layout / sign-off) re-qualification under open_pdks `f6eeac7` (issue #172)

Date: 2026-10-16. Parent: #166 (inventory: `docs/pdk-requalification-inventory.md`).
Source tree: `origin/main` @ `631159b`.

**Question:** does moving the pin from open_pdks `c6d73a3` to
`f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7` (`docs/pdk-pin.md`) change any G5
layout or sign-off record?

**Answer:** no status and no hash changed. The only difference found is the
PDK version string stamped into two generator reports. No spec threshold, manifest or existing
record was touched; every new file below is an addition.

## Environment (all re-runs)

| Item | Value |
|---|---|
| PDK | `PDK_ROOT=~/.ciel`, `sky130A`, `SOURCES` open_pdks `f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7` |
| check toolchain | klayout-tools `0.6.0` @ `c622e8a` (`layout/generation-toolchain.json`), klayout `0.30.12` |
| generation toolchain | klayout-tools `0.4.0` @ `2dd24b09`, klayout `0.30.12` |
| installed via | `python3 layout/generation_toolchain.py install` (venvs under the worktree's gitignored `.toolchains/`); the host `klt` was not used or changed |
| SPICE | none. G5 is tool-run (KLayout) only; no `ngspice`/`klt sim` leg exists, so no batch submit was needed |

klt printed a warning that klayout `0.30.12` differs from the `0.30.10` the
`0.6.0` build was tested against. The pinned toolchain deliberately uses
`0.30.12`, which is also what produced the committed reports.

## Decision table

| Record | Decision | Reason |
|---|---|---|
| `gain_cell_2t_array.drc.result.json` | re-run (new record) | Deck is `klt`'s built-in `sky130` (content hash `sha256:a1d90e06...`); `provenance.pdk` is `null`. Re-run anyway because the generation repro regenerates the GDS. |
| `gain_cell_2t_array.lvs.result.json` | re-run (new record) | Same; reference netlist is generated from `design/gain_cell_2t.spice`. |
| `gain_cell_2t_array.erc.result.json` | re-run (new record) | `provenance.pdk` is `sky130 / built-in / version: null`; spec hash `d6d76e7d...`. |
| `gain_cell_2t.drc.result.json` | re-run (new record) | Old report came from `klt 0.5.0+g2b1e55e51bb8.dirty`, which cannot be rebuilt exactly; re-run on the committed GDS with the pinned `0.6.0`. |
| `gain_cell_2t.lvs.result.json` | re-run (new record) | Same. |
| `layout/results/generation_reproduction_20261011.json` | re-run (new record) | Stamps `c6d73a3` and `~/.volare`; superseded for the PDK identity only. |
| `layout/gain_cell_2t_array.layout.json`, `layout/gain_cell_2t_array_mos.json` | reference only | Generator reports carrying `pdk.version: open_pdks c6d73a3`. The regeneration under `f6eeac7` differs from them only in that string (see below). Not edited. |
| `layout/gain_cell_2t.layout.json`, `gain_cell_2t_tap.json`, `gain_cell_2t_mos.json` | reference only | Single-cell generator reports, produced by `generate.sh`, which is outside the #91 pin and has no reproduction harness. Stamp is historical; the GDS they describe passed DRC/LVS unchanged (below). Not edited. |
| `layout/results/density_20261009.json` | no change needed | The script reads only committed artifacts and does not invoke klt or the PDK. The array GDS is byte-identical under `f6eeac7`, so areas cannot move. Re-running would only copy the old stamp. |
| `block-manifest.json`, `block-manifest.signoff.json` | no change needed | Content-hash pins unchanged; no decision record is raised. |

## Results

### Array generation reproduction

`./layout/generate_array.sh --check --record ...` under `f6eeac7` regenerated the 4x4
array in a scratch directory. Record:
`generation_reproduction_f6eeac7_20261016.json`.

| Artifact | Result |
|---|---|
| `gain_cell_2t_array.gds` | **identical**, sha256 `4a11550681e5a8da5740b54f6a12afde308f25a12037634c801361d6cd55d4cd` (same as committed) |
| `gain_cell_2t_array_mos.gds` | identical |
| `gain_cell_2t_array.layout.request.json`, `.lvs_reference.spice`, `.lvs.request.json` | identical |
| `gain_cell_2t_array.layout.json`, `gain_cell_2t_array_mos.json` | differ **only** in `$.pdk.version`: `open_pdks c6d73a35...` -> `open_pdks f6eeac7d...` |
| routing | complete, `unrouted_nets: []` |

The script's overall `comparison` therefore reads `mismatch` (it compares the
PDK version string exactly), and the script exits non-zero. This is the
expected stamp change, not a geometry or connectivity change. The record is kept as
written by the script rather than hand-edited.

### Sign-off statuses (old vs new)

| Report | Old status | New status | Other differences |
|---|---|---|---|
| array DRC | clean | clean | none; JSON identical to the committed report |
| array LVS | match | match | none; JSON identical |
| array ERC | clean | clean | only `file`/`spec` path fields (scratch run used cwd-relative paths) |
| bitcell DRC | clean | clean | only `provenance.klt_version` (`0.5.0+g2b1e55e51bb8.dirty` -> `0.6.0`); input and deck hashes equal |
| bitcell LVS | match (`mismatch_count: 2`, the documented unused-`pfet` warnings) | match (`mismatch_count: 2`) | only `provenance.klt_version` |

Input hashes: array GDS `4a115506...d4cd`; bitcell GDS `f55f08e3...d259`;
bitcell LVS reference `693c4990...0340`; array LVS reference `61cba9ba...65b7`.

## New files

- `generation_reproduction_f6eeac7_20261016.json`
- `gain_cell_2t_array.{drc,lvs,erc}_f6eeac7_20261016.json`
- `gain_cell_2t.{drc,lvs}_f6eeac7_20261016.json`

## Supersession notes

- `generation_reproduction_20261011.json` is superseded for the PDK identity (`c6d73a3`, `~/.volare`) by
  `generation_reproduction_f6eeac7_20261016.json`. Its geometry findings stand and were reproduced.
- The `c6d73a3` stamps in the five generator reports listed above are left in place. Their
  geometry is confirmed unchanged under `f6eeac7`.
- The two bitcell reports from `klt 0.5.0+g2b1e55e51bb8.dirty` cannot be reproduced
  exactly; the `0.6.0` re-run reached the same statuses on the same input hashes.
- G5 has no `EVIDENCE_INDEX.md`; this file is the index for G5.

## Limits

- DRC/LVS/ERC are computed from layout geometry and the klt deck. Nothing in
  these reports depends on the PDK's SPICE models, so this re-run shows that regeneration
  and checking still agree under the new tree, not that any model-dependent number is unchanged.
- The pinned `generation` toolchain reads the PDK for device generation. Geometry was
  unchanged, which is the evidence that the `f6eeac7` tree does not alter the drawn layout.
- Re-extracted parasitics (`klt extract --parasitics`, `parasitics_summary_pinned_generation_20261011.json`)
  were not re-run: not marked `re-run` above and out of this issue's decision table.
