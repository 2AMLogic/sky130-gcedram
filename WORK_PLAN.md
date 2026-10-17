# Work Plan

This roadmap is generated from current GitHub label state by the Loom Guide role.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

- **#76**: ci: run refresh-overhead and evidence_common tests (#73)
- **#152**: sim: re-run sense stage and loaded column with the extracted 4-row C_RBL
- **#162**: layout: add reproducible compact 2T bitcell variants (1.95 and 1.40 um^2 drawn pitch)

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

_None._

## Important

`loom:important`; taken before unlabelled work.

- **#88**: Re-run sense-stage and loaded-column with the extracted 4-row C_RBL (0.86 fF vs assumed 10 fF)

## Ready

Human-approved issues ready for implementation (`loom:issue`).

_None._

## In Progress

Issues currently being built (`loom:building`).

- **#100**: Decision: 2T bitcell is 2.4x larger than public sky130 6T SRAM cell; README density requirement unmet
- **#197**: Consolidate anchor-style mutant helpers left over after #191 (3 run_mutation scripts)

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

- **#199**: refactor: share anchor-mutant helpers across integration mutation scripts

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#76**: ci: run refresh-overhead and evidence_common tests (#73)
- **#152**: sim: re-run sense stage and loaded column with the extracted 4-row C_RBL
- **#162**: layout: add reproducible compact 2T bitcell variants (1.95 and 1.40 um^2 drawn pitch)

## Proposed

Issues carrying `loom:curated`.

- **#24**: Build the full gain-cell eDRAM macro (array + sense amp + refresh controller + SPI) to reach Chipalooza sign-off bar *(curated)*
- **#73**: CI: run refresh-overhead and evidence_common tests; fix python -I import in test_refresh_overhead *(curated)*
- **#88**: Re-run sense-stage and loaded-column with the extracted 4-row C_RBL (0.86 fF vs assumed 10 fF) *(curated)*
- **#100**: Decision: 2T bitcell is 2.4x larger than public sky130 6T SRAM cell; README density requirement unmet *(curated)*
- **#166**: Re-qualify reference records under open_pdks f6eeac7 and mark c6d73a3 records superseded *(curated)*
- **#168**: Re-qualify G1 retention chain (leakage, bitcell-transient, retention) under open_pdks f6eeac7 *(curated)*
- **#192**: Cite the analog partition's T1 items 1, 2, 9 and 10 with artifact-anchored evidence *(curated)*

## Proposed (Architect / Hermit)

- **#94**: Characterize write-hold-sense trajectories and mixed neighbor patterns at the refresh deadline *(architect)*
- **#147**: Characterize data preservation across repeated closed-loop refresh cycles *(architect)*

## Epics

- **#13**: Track the gap to T1 sim-validated / bronze (klayout-tools design-evidence tiers)
- **#24**: Build the full gain-cell eDRAM macro (array + sense amp + refresh controller + SPI) to reach Chipalooza sign-off bar

## Backlog Balance

| Bucket | Count |
|------|-------|
| Operator merge-risk holds | 3 |
| Very important | 0 |
| Important | 1 |
| Ready (`loom:issue`) | 0 |
| In Progress (`loom:building`) | 2 |
| PRs awaiting review | 1 |
| Approved PRs awaiting merge | 3 |
| Curated | 7 |
| Architect / Hermit proposals | 2 |
| Active epics | 2 |
<!-- guide:plan-body:end -->
