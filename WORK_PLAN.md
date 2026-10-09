# Work Plan

This roadmap is generated from current GitHub label state by the Loom Guide role.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs stuck under a `loom:operator` merge-risk hold — implementation work is done, only a human merge decision is missing.

_None._

## Operator Priority

Issues the operator starred (`loom:operator-priority`); land these first.

_None._

## Ready

Human-approved issues ready for implementation (`loom:issue`).

_None._

## In Progress

Issues currently being built (`loom:building`).

_None._

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

_None._

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#76**: ci: run refresh-overhead and evidence_common tests (#73)

## Proposed

Issues carrying `loom:curated`.

- **#24**: Build the full gain-cell eDRAM macro (array + sense amp + refresh controller + SPI) to reach Chipalooza sign-off bar *(curated)*
- **#73**: CI: run refresh-overhead and evidence_common tests; fix python -I import in test_refresh_overhead *(curated)*

## Proposed (Architect / Hermit)

- **#62**: CI: enforce append-only sim/ results mechanically *(architect)*
- **#80**: Extract read-bitline and wordline parasitics from the 4x4 array to replace the C_RBL assumption *(architect)*
- **#81**: Monte Carlo mismatch study of the sense stage: input-referred offset at the restricted corners *(architect)*
- **#82**: Draft macro-level pass conditions for epic #24 items 2-6 as a PROPOSED record *(architect)*
- **#83**: Propose the SPI control interface spec with a behavioral SPI-slave model and testbench (#24 item 4) *(architect)*

## Epics

- **#13**: Track the gap to T1 sim-validated / bronze (klayout-tools design-evidence tiers)
- **#24**: Build the full gain-cell eDRAM macro (array + sense amp + refresh controller + SPI) to reach Chipalooza sign-off bar

## Backlog Balance

| Tier | Count |
|------|-------|
| Operator merge-risk holds | 0 |
| Operator priority | 0 |
| Ready (`loom:issue`) | 0 |
| In Progress (`loom:building`) | 0 |
| PRs awaiting review | 0 |
| Approved PRs awaiting merge | 1 |
| Curated | 2 |
| Architect / Hermit proposals | 5 |
| Active epics | 2 |
<!-- guide:plan-body:end -->
