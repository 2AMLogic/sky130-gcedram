# Single-cell `C_SN` re-ratification (PROPOSED, not ratified)

Status: **PROPOSED. Not ratified.** Issue #244. This record changes no ratified
value: `spec/retention-refresh-budget.md` still carries `C_SN = 0.605354 fF` for
the extracted single cell until the review protocol below completes.

## 1. Decision requested

Operator ruling of 2026-10-28 (option a) accepted the layout regenerated under
klayout-tools 0.8.0 (cell height 1.84 um -> 2.115 um; DRC clean, LVS match, ERC
clean; T1 item 3 met). That regeneration changes the extracted single-cell
storage-node capacitance. This record proposes re-ratifying it:

| | Ratified today | Proposed |
|---|---|---|
| Single-cell extracted `C_SN` (2T-min) | 0.605354 fF | **0.672741 fF** |
| Ground | 0.586490 fF | 0.655316 fF |
| Lateral coupling (bl + rwl) | 0.018864 fF | 0.017425 fF |

The pre-layout ASSUMED value (1.106463 fF) and the ratified retention time
(~10.06 us at sf / 125 C) are **not** touched by this proposal.

## 2. Evidence chain (all committed, reproducible from the stock PDK)

1. Leakage: unchanged (`sim/leakage/`, 9.898880e-11 A, sf / 125 C).
2. Storage-node capacitance: `layout/gain_cell_2t.extract.parasitics.json`,
   `klt extract --parasitics --critical-net sn` (klt 0.8.0) on the regenerated
   `layout/gain_cell_2t.gds`. This is wiring capacitance only (device gate and
   junction capacitance are in the model), as in the existing convention.
3. Derivation: `sim/retention/derive_retention.py`, two NEW rows appended to
   `sim/retention/results/retention_results.csv`: 2T-min extracted
   `t_retention = 6.116519e-06 s` (was 5.503841e-06 s), sf / 125 C.

**The change is geometry, not the extractor.** The pre-#244 GDS extracted with
klt 0.8.0 gives ground 0.58649 fF + coupling 0.018864 fF = 0.605354 fF, which is
the ratified number exactly
(`layout/results/gain_cell_2t.extract.parasitics_pre244_geometry_klt0.8.0_20261028.json`,
input hash `sha256:f55f08e3...`). The +0.067 fF (+11.1 %) comes from the
regenerated geometry (poly `sn` area 0.228 fF, li1 0.150 fF, met1 0.277 fF).

## 3. Downstream numbers moved by the new geometry (new dated evidence)

| Quantity | Before | After | Evidence |
|---|---|---|---|
| Single-cell extracted retention, sf / 125 C | 5.50 us | 6.12 us | `retention_results.csv` |
| 4x4 array `C_SN`, min .. max | 0.4736 .. 0.5020 fF | 0.5384 .. 0.5681 fF | `sim/retention/results/array_c_sn_comparison_20261028T070954Z.json` |
| Array capacitance-only sensitivity | 4.31 .. 4.56 us | 4.90 .. 5.16 us | same file |
| Array limiting node | `sn_3_3` | `sn_3_0` | same file |
| Max row-refresh incremental energy (sf / 125 C, all-one) | 2.46 pJ | 2.54 pJ | `sim/refresh-energy/results/refresh_energy_summary_20261028T071730Z.json` |
| Area per bit (4x4 incl. shared tap) | 7.0861 um2 | 8.4764 um2 | `layout/results/density_20261028_v244.json` |

The capacitance rows are capacitance-only sensitivities at the unchanged
testbench-geometry leakage, as defined in `spec/retention-refresh-budget.md`
Section 9; the Section 9 recommendation (geometry-matched leakage, path C) is
unaffected. The ratified refresh interval (5.03 us) rests on the pre-layout
assumption and does not move.

The row-refresh energy increase is not attributable to `C_SN` alone: the
array netlist (devices, wiring parasitics) was re-extracted. The ten-point grid
passed 10/10 on the fleet (fleet jobs in the report `environment.remote`).

## 4. Direction of the change

A larger `C_SN` is the *favourable* direction for retention
(`t = C * dV / I_leak`), at the cost of area: the single-cell box is 15 % taller (1.84 -> 2.115 um) and
the array bitcell pitch grows 1.64 -> 1.94 um (+18 %), i.e. drawn pitch area
4.887 -> 5.781 um2 and 2.36x -> 2.79x the quoted SRAM cell
(`layout/results/density_20261028_v244.json`). `spec/density-vs-sram.md` and
the SRAM comparison still quote the old figures and need their own refresh
(follow-up); this record does not restate them.

## 5. Ratification protocol

Per the repository protocol, in this order:

1. `ratification/ee-key` review of this record and its evidence: **pending**.
2. `ratification/market-key` review (density cost of the taller cell):
   **pending**.
3. Operator ratification. Only then edit `spec/retention-refresh-budget.md`
   (Sections 5, 9.2, 9.3) to carry 0.672741 fF, with this record cited.

Neither key has run in the PR that adds this record. Agents do not edit the
ratified spec ahead of the ratification.

## 6. Not covered / follow-ups

- The generated decks under `sim/write-disturb`, `sim/refresh-op`,
  `sim/sense-stage`, `sim/sense-mismatch`, `sim/column-periphery` were
  regenerated from the new extraction (their `committed files not stale`
  tests require it). Their committed *results* are history of the pre-#244
  layout and were not re-run; that is a separate campaign.
- `sim/loaded-column`, `sim/bitcell-transient`, `docs/chipalooza` and the
  ratified spec text still quote 0.605354 fF in prose and results; they are
  point-in-time records.
- The fleet worker reports `open_pdks c6d73a35...`; the repo pin is `f6eeac7d...`
  (`docs/pdk-pin.md`). The client-side model library sha256 matches the previous
  run (`48de7c67...`), but the stamps are `not_comparable`
  (`client_stamp_unavailable`), so equality of the worker PDK to the pin is not
  established by this report.
