# sky130-gcedram

A 2T/3T gain-cell embedded-DRAM (eDRAM) macro on
[SkyWater sky130](https://github.com/google/skywater-pdk), a 130 nm open
CMOS PDK — designed by AI agents driving
[klayout-tools](https://github.com/2AMLogic/klayout-tools) and the
open-source xschem + ngspice flow.

**Status: 2T bitcell designed, simulated, and DRC/LVS-clean.** The leakage
study that everything else in this repo depends on is done and its evidence
chain is ratified in `spec/`. On top of it the bitcell itself now exists as
committed artifacts: an xschem schematic and its derived netlist
([`design/gain_cell_2t.sch`](design/gain_cell_2t.sch),
[`design/gain_cell_2t.spice`](design/gain_cell_2t.spice)), a layout that
runs DRC-clean and LVS-matches that netlist
([`layout/gain_cell_2t.gds`](layout/gain_cell_2t.gds), with its
[DRC](layout/gain_cell_2t.drc.result.json) and
[LVS](layout/gain_cell_2t.lvs.result.json) result reports committed — an
informal pass against klayout-tools' unreleased sky130 deck, not a foundry
sign-off run), and a circuit-level write/read/hold transient across a
15-point PVT grid
([`sim/bitcell-transient/`](sim/bitcell-transient/README.md)). All of that
is at the **single-bitcell** level: the next work is the macro around it —
array, sense amplifier, and refresh controller — tracked in
[#24](https://github.com/2AMLogic/sky130-gcedram/issues/24).

**Built agent-native.** Every specification, decision record, testbench, and
line of documentation here is produced by AI agents working from a ratified
spec and an append-only evidence trail — not human-authored work that agents
merely assisted with. Verification is the product: every claim traces to a
recorded result under PVT corners. Where the agents hit friction with the
open-source tooling — most often
[klayout-tools](https://github.com/2AMLogic/klayout-tools) — that friction is
filed as a public issue against the tool itself, so the fix benefits everyone
using sky130, not just this repo.

## Why this block, on this PDK

Gain-cell eDRAM is a mature topology with two decades of academic literature
behind it. Unlike commodity DRAM it needs no special process step — a gain
cell is built from ordinary logic transistors, which is the whole point of
the topology: embedded memory denser than SRAM on a standard logic process.
What does not exist publicly is an implementation on an open PDK. Closing
that gap is this repo's reason to exist.

The block is honest about its trade: a gain cell is *dynamic*. It gives up
SRAM's static hold in exchange for density, and the design lives or dies on
the retention/refresh budget. That budget is the centerpiece of the spec
here, not a footnote — every retention-time claim carries its evidence
chain (device-level leakage at temperature corners → an explicitly labelled
storage-node capacitance assumption → the retention derivation), all
reproducible from a stock PDK install with the netlists committed.

sky130 is the right first home: fully open, fully supported plain CMOS, with
shipped device models that the leakage study can run against directly. And
the macro itself — a bit array plus its sense amplifiers and refresh
periphery — is a mixed-signal layout workout, exactly the kind of work that
surfaces tool friction for
[klayout-tools](https://github.com/2AMLogic/klayout-tools) to absorb.

## Target specification

The retention/refresh budget has been ratified (issue #5): retention is
*derived* from the measured leakage of the access device against the shipped
sky130 models, not targeted first and justified later, and the bitcell
topology decision (2T vs 3T) follows from that derivation. Full evidence
chain and rationale: [`spec/retention-refresh-budget.md`](spec/retention-refresh-budget.md).

| Parameter | Position |
|---|---|
| Bitcell topology | **2T, ratified.** Retention evidence is topology-neutral once a pre-layout capacitance assumption is discounted; density (a hard requirement to beat 6T SRAM on area) decides it. See [`spec/retention-refresh-budget.md`](spec/retention-refresh-budget.md) § 6. |
| Retention time | **~10.06 µs, worst case** (`sf` corner, 125 °C), pre-layout single-cell estimate. See [`spec/retention-refresh-budget.md`](spec/retention-refresh-budget.md) § 5. |
| Refresh budget | Refresh interval ≤ **~5.03 µs** (worst case, 2x margin assumption); bandwidth-overhead formula ratified, numeric percentage pending array/periphery design. See [`spec/retention-refresh-budget.md`](spec/retention-refresh-budget.md) § 7. |
| Supply | sky130 standard 1.8 V core; boosted wordline is a design decision to record |
| Density vs SRAM | Must beat a 6T SRAM bitcell on area to justify existing; comparison against public [OpenRAM](https://openram.org/) documentation — not yet performed |
| Temperature range | Corners per the shipped sky130 model set; retention claims at worst case, never typical |

Maturity ladder: retention study → spec ratified → bitcell + array simulated
across PVT → sense/refresh periphery → layout DRC/LVS-clean → post-layout
re-verification → shuttle seat → measured silicon. **Current position: the
bitcell has cleared every rung it can reach on its own — simulated across
PVT (write/read/hold) and laid out DRC-clean with a matching LVS. The open
frontier is the macro: array, sense amplifier and refresh-controller design
([#24](https://github.com/2AMLogic/sky130-gcedram/issues/24)), then
macro-level layout and post-layout re-verification.**

## Repo layout

```
spec/          ratified spec + decision records
design/        schematics / netlists (xschem)
sim/           testbenches + PVT corner results (ngspice)
layout/        GDS + DRC/LVS reports (klayout-tools driven)
measurements/  silicon characterization (empty until tape-out)
```

## License

Apache License 2.0 — see [LICENSE](LICENSE).
