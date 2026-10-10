# Work Plan

This roadmap is generated from current GitHub label state by the Loom Guide role.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs stuck under a `loom:operator` merge-risk hold — implementation work is done, only a human merge decision is missing.

- **#76**: ci: run refresh-overhead and evidence_common tests (#73)
- **#118**: design: column-periphery slice and ideal-vs-real comparison (#114)

## Operator Priority

Issues the operator starred (`loom:operator-priority`); land these first.

_None._

## Ready

Human-approved issues ready for implementation (`loom:issue`).

_None._

## In Progress

Issues currently being built (`loom:building`).

- **#72**: docs(sim): narrow 'a PR cannot weaken the check' claim for the append-only guard

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#126**: docs(sim): narrow 'a PR cannot weaken the check' claim

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#76**: ci: run refresh-overhead and evidence_common tests (#73)
- **#118**: design: column-periphery slice and ideal-vs-real comparison (#114)

## Proposed

Issues carrying `loom:curated`.

- **#24**: Build the full gain-cell eDRAM macro (array + sense amp + refresh controller + SPI) to reach Chipalooza sign-off bar *(curated)*
- **#72**: docs(sim): narrow 'a PR cannot weaken the check' claim for the append-only guard *(curated)*
- **#73**: CI: run refresh-overhead and evidence_common tests; fix python -I import in test_refresh_overhead *(curated)*
- **#100**: Decision: 2T bitcell is 2.4x larger than public sky130 6T SRAM cell; README density requirement unmet *(curated)*
- **#114**: Design the column periphery (precharge, write driver, column select) to replace ideal sources in the read/write studies *(curated)*

## Proposed (Architect / Hermit)

- **#94**: Characterize write-hold-sense trajectories and mixed neighbor patterns at the refresh deadline *(architect)*

## Epics

- **#13**: Track the gap to T1 sim-validated / bronze (klayout-tools design-evidence tiers)
- **#24**: Build the full gain-cell eDRAM macro (array + sense amp + refresh controller + SPI) to reach Chipalooza sign-off bar

## Backlog Balance

| Tier | Count |
|------|-------|
| Operator merge-risk holds | 2 |
| Operator priority | 0 |
| Ready (`loom:issue`) | 0 |
| In Progress (`loom:building`) | 1 |
| PRs awaiting review | 1 |
| Approved PRs awaiting merge | 2 |
| Curated | 5 |
| Architect / Hermit proposals | 1 |
| Active epics | 2 |
<!-- guide:plan-body:end -->
