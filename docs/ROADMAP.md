# Roadmap

sky130-gcedram is a 2T gain-cell embedded-DRAM macro on SkyWater sky130, built
to find out what an open-PDK gain cell can honestly claim and to expose tool
gaps in [klayout-tools](https://github.com/2AMLogic/klayout-tools) on the way.

Status as of 2026-11-13, `main` @ `d9ee3fe`; issue and PR states as read
from the tracker that day. `WORK_PLAN.md` is a generated label snapshot.

## Where it stands

The verdict of record is the machine-graded
[`block-manifest.signoff.json`](../block-manifest.signoff.json) (klt 0.8.0,
re-run by `.github/workflows/signoff.yml`): **9 of 22 T1 rows met**. The
tracker is [#13](https://github.com/2AMLogic/sky130-gcedram/issues/13); the
macro build-out is [#24](https://github.com/2AMLogic/sky130-gcedram/issues/24).

| T1 item | Analog partition | Digital partition |
|---|---|---|
| 1 Design sources | met (`attest/item1.envelope.json`, PR #272) | unmet; PR #276 open |
| 2 Layout | met (`attest/item2.envelope.json`, PR #269) | unmet; #231 |
| 3 DRC clean | met (`layout/gain_cell_2t.drc.result.json`) | unmet; #232 |
| 4 LVS clean | met (`layout/gain_cell_2t.lvs.result.json`) | unmet; #233 |
| 5 Corner verification vs ratified spec | unmet | unmet |
| 6 Monte Carlo for statistical claims | unmet | unmet |
| 7 Post-layout verification | unmet | unmet |
| 8 Characterization report | unmet | unmet |
| 9 Testbenches shipped | met (`attest/item9.envelope.json`) | met (`attest/item9.digital.envelope.json`, PR #271) |
| 10 Repo hygiene | met (`attest/item10.envelope.json`) | met (same envelope, PR #270) |
| 11 Power delivery | met (`layout/gain_cell_2t_array.erc.result.json`) | unmet; #236 |

Against the six macro items of #24:

- **Array:** shared-tap 4x4 proof of technique, DRC clean and LVS matched
  (`layout/gain_cell_2t_array.*`, regenerated under klt 0.8.0 in PR #248).
  Not a ratified row/column count.
- **Sense path:** sense latch and column-periphery schematics with derived
  netlists (`design/sense_latch.*`, `design/column_periphery.*`) and studies
  under `sim/`. Pass conditions are proposed, not ratified
  (`spec/macro-pass-conditions-PROPOSED.md`).
- **Refresh controller and SPI:** behavioral Verilog under `digital/` with 14
  regression suites in CI (`digital/ci/run_digital_regressions.sh`).
  `spi_slave` became synthesizable in PR #274 and its standard-cell-mapped
  netlist is committed as a result artifact
  (`digital/spi-control/results/spi_slave_synth_2026-11-11_issue273.v`); no
  `gc_ctrl_top` gate-level netlist, no gate-level replay and no layout is on
  `main`.
- **Macro layout and post-layout PVT:** not started.

Known limits, with committed evidence: the loaded-column read fails at the
cold corner, so the operating range is restricted (proposed,
`spec/operating-range-decision-PROPOSED.md`); the drawn 2T cell is 2.79x the
quoted public sky130 6T SRAM cell (`spec/density-vs-sram.md`);
device-inclusive retention measures below the ratified 10.06 us (#208).

## Now

1. **Bump the klt pin 0.8.0 -> 0.9.1 and regenerate layout evidence**
   ([#275](https://github.com/2AMLogic/sky130-gcedram/issues/275)). Done when
   `KLT_VERSION` is 0.9.1 in `signoff.yml`, the DRC/LVS/ERC reports and attest
   envelopes are regenerated, the `signoff` job is green and no met row
   becomes unmet. No technical dependency, but the issue carries a park
   pointing at PR #276 while #276 needs this first (see Blocked).
2. **Index three studies in `sim/README.md`** (no issue; seed drafted):
   `sim/cold-start/`, `sim/column-periphery/` and `sim/sense-mismatch/` have
   no section. Done when each has one in the existing per-study format.
3. **Correct `docs/chipalooza/challenge-4-proposal.md`** (no issue; seed
   drafted; named in #24's affected files). It still says no array, sense
   amplifier, refresh controller or SPI exists. Done when every "does not
   exist" statement matches `main`, with unmet rows left unmet.
4. **Refresh `docs/pdk-requalification-inventory.md`** (no issue; seed
   drafted). Its Split section predates #168 closing and the split to #182.
   Done when each group row carries its current issue and state.

## Next

- **Digital item 1** (#230, PR #276): after #275 lands, rebase, regenerate
  `attest/item1.digital.envelope.json` on the pinned klt, `signoff` green,
  row `1.digital` met.
- **Digital layout chain:** #231 (place-and-route, `2.digital`) after #230;
  then #232 and #233 (`3.digital`, `4.digital`); then #236 (`11.digital`).
  Each is done when `klt signoff` reports its row met.
- **PDK re-qualification under open_pdks `f6eeac7`:** #182 (G1
  bitcell-transient), #169 (G2), #171 (G4), tracker #166. Unblocked when a
  batch `klt sim` report shows `pdk_stamp_comparison.status = match`; the
  batch worker still stamps `c6d73a3` (probe recorded on #171, 2026-11-05).
  #169 and #171 also carry a stale unchecked `#166` dependency box that the
  unblock pass reads as open (note on #166, 2026-11-13).
- **Write-hold-sense at the refresh deadline** (#94) after #88 closes via
  PR #152; **repeated closed-loop refresh** (#147) after #94.
- **README status refresh:** the status paragraph and repo-layout tree omit
  the sense path, `digital/`, `attest/` and `docs/`. `README.md` is hashed by
  the item-10 inventory (`attest/item10.json`), and PR #276 edits that
  inventory's envelope (`attest/item10.envelope.json`), so do this after #276,
  with the item-10 envelope regenerated in the same PR.
- **Evidence-check test lists** (#277): after its decision.

## Later

- **Analog items 5, 6 and 8.** First: which rows of
  `spec/macro-pass-conditions-PROPOSED.md` are ratified and which are
  statistical; verdicts against a draft spec are provisional.
- **Item 7 and #24 items 5-6** (full-macro GDS, extracted PVT). First: the
  ratified row count and `t_row_refresh_op`
  (`spec/retention-refresh-budget.md` section 7).
- **Digital items 5-8** (multi-corner timing, post-route functional re-run,
  characterization). First: a routed controller (#231).
- **Cell of record.** `layout/compact/` holds two smaller variants beside
  the unchanged baseline. First: does one replace it, and at which C_SN and
  refresh interval (#208, PR #223).
- **Chipalooza Challenge #4 mapping.** First: read the published brief;
  the SPI command set and harness mapping are assumptions until then (#24).

## Blocked and waiting

No open issue is drawable as labelled today: Now items 2-4 are seed drafts
only, and item 1 needs its park cleared.

- **#275 and PR #276 are parked on each other** (Doctor note on PR #276,
  2026-11-12; routed for a decision). The note's first option is #275 first.
- **PR #152** (issue #88, follow-up #261): approved, with the post-#244
  0.955559 fF C_RBL re-run on the branch, held under `loom:blocked`.
- **PR #223** (issue #208, shorter refresh interval on the 6.45 us bound):
  needs both key reviews re-run on the revised head, then ratification; it
  also conflicts with `main`.
- **Proposed records awaiting ratification:** operating range (#56), macro
  pass conditions (#82), C_SN re-ratification (#244), density inputs (#252).
- **Batch worker PDK revision** gates #182, #169 and #171; **#277** is
  routed for a decision (discovery runner or the two explicit lists).

## Not planned

- A drop-in SRAM replacement claim, or a full-temperature-range claim.
- A 3T cell (2T is ratified), or relaxing a ratified value to pass.
- Silicon measurements: `measurements/` stays empty until a tape-out exists.
