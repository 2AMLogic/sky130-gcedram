# Work Plan

This roadmap is generated from current GitHub label state by the Loom Guide role.

<!-- guide:plan-body:start -->
## Operator Attention: Merge-Risk-Hold Pileup

Judge-approved PRs under a hold (`loom:blocked` or `loom:operator`) — only a human merge decision is missing.

- **#76**: ci: run refresh-overhead and evidence_common tests (#73)
- **#152**: sim: re-run sense stage and loaded column with the extracted 4-row C_RBL
- **#214**: feat(sim): device-inclusive C_SN of the compact v2 array

## Very Important

`loom:very-important` (one counts per workspace); every stage takes these first.

- **#168**: Re-qualify G1 retention chain (leakage, bitcell-transient, retention) under open_pdks f6eeac7

## Important

`loom:important`; taken before unlabelled work.

- **#88**: Re-run sense-stage and loaded-column with the extracted 4-row C_RBL (0.86 fF vs assumed 10 fF)

## Ready

Human-approved issues ready for implementation (`loom:issue`).

- **#168**: Re-qualify G1 retention chain (leakage, bitcell-transient, retention) under open_pdks f6eeac7

## In Progress

Issues currently being built (`loom:building`).

- **#73**: CI: run refresh-overhead and evidence_common tests; fix python -I import in test_refresh_overhead
- **#88**: Re-run sense-stage and loaded-column with the extracted 4-row C_RBL (0.86 fF vs assumed 10 fF)
- **#208**: Operator decision: retention/refresh budget vs compact-layout C_SN (from #161)

## PRs Awaiting Review

PRs waiting on Judge (`loom:review-requested`).

_None._

## Approved (Awaiting Merge)

PRs that passed review and are queued for Champion auto-merge (`loom:pr`).

- **#76**: ci: run refresh-overhead and evidence_common tests (#73)
- **#152**: sim: re-run sense stage and loaded column with the extracted 4-row C_RBL
- **#214**: feat(sim): device-inclusive C_SN of the compact v2 array

## Proposed

Issues carrying `loom:curated`.

- **#24**: Build the full gain-cell eDRAM macro (array + sense amp + refresh controller + SPI) to reach Chipalooza sign-off bar *(curated)*
- **#73**: CI: run refresh-overhead and evidence_common tests; fix python -I import in test_refresh_overhead *(curated)*
- **#88**: Re-run sense-stage and loaded-column with the extracted 4-row C_RBL (0.86 fF vs assumed 10 fF) *(curated)*
- **#166**: Re-qualify reference records under open_pdks f6eeac7 and mark c6d73a3 records superseded *(curated)*
- **#168**: Re-qualify G1 retention chain (leakage, bitcell-transient, retention) under open_pdks f6eeac7 *(curated)*
- **#208**: Operator decision: retention/refresh budget vs compact-layout C_SN (from #161) *(curated)*
- **#212**: Re-baseline layout DRC/LVS/ERC evidence under a klt rev with signoff --attest *(curated)*

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
| Very important | 1 |
| Important | 1 |
| Ready (`loom:issue`) | 1 |
| In Progress (`loom:building`) | 3 |
| PRs awaiting review | 0 |
| Approved PRs awaiting merge | 3 |
| Curated | 7 |
| Architect / Hermit proposals | 2 |
| Active epics | 2 |
<!-- guide:plan-body:end -->
