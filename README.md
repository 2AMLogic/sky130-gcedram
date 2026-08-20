# sky130-gcedram

A 2T/3T gain-cell embedded-DRAM (eDRAM) macro on
[SkyWater sky130](https://github.com/google/skywater-pdk), a 130 nm open
CMOS PDK — designed by AI agents driving
[klayout-tools](https://github.com/2AMLogic/klayout-tools) and the
open-source xschem + ngspice flow.

**Status: just opened.** Nothing is designed yet. The first work is the
retention/refresh budget — the leakage study that everything else in this
repo depends on.

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

## Target specification (DRAFT — engineering to ratify)

The spec is deliberately thin until the retention study lands. Retention is
not a number to be targeted first and justified later; it is *derived* from
the measured leakage of the access device against the shipped sky130 models,
and the bitcell topology decision (2T vs 3T) follows from that derivation.

| Parameter | Position |
|---|---|
| Bitcell topology | 2T or 3T — decided by the retention study, recorded in `spec/` |
| Retention time | Derived, not targeted: leakage evidence chain at the worst-case temperature corner |
| Refresh budget | Set by the ratified retention figure; stated as bandwidth overhead |
| Supply | sky130 standard 1.8 V core; boosted wordline is a design decision to record |
| Density vs SRAM | Must beat a 6T SRAM bitcell on area to justify existing; comparison against public [OpenRAM](https://openram.org/) documentation |
| Temperature range | Corners per the shipped sky130 model set; retention claims at worst case, never typical |

Maturity ladder: retention study → spec ratified → bitcell + array simulated
across PVT → sense/refresh periphery → layout DRC/LVS-clean → post-layout
re-verification → shuttle seat → measured silicon. **Current position:
pre-spec, retention study first.**

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
