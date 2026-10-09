# spec

Ratified spec + decision records. See the repo README for scope.

| Path | Purpose |
|---|---|
| [`retention-refresh-budget.md`](retention-refresh-budget.md) | **Ratified.** The retention/refresh-budget decision record (issue #5): assembles the full evidence chain, ratifies the worst-case retention time, decides 2T vs 3T bitcell topology, and states the refresh budget as a bandwidth overhead |
| [`retention-literature-crosscheck.md`](retention-literature-crosscheck.md) | Cross-checks this repo's derived retention numbers (`sim/retention/`, issue #3) against published gain-cell academic literature; final link in CLAUDE.md's retention evidence chain (issue #4) |
| [`supply-reliability-decision-PROPOSED.md`](supply-reliability-decision-PROPOSED.md) | **PROPOSED, not ratified** (issue #49). Compares write-WL boost, read-WL under-drive and an operating-range limitation for the sense path; verdict: missing reliability evidence, not ready for ratification. Changes no ratified value. Resolved to outcome C by operator ruling 2026-10-08; see section 9 of that file |
| [`operating-range-decision-PROPOSED.md`](operating-range-decision-PROPOSED.md) | **PROPOSED, not ratified** (issue #56). Writes operator-selected outcome C as a restricted operating-temperature range (27 C to 125 C at 1.8 V, from committed baseline grid points only; -40 C fails or is marginal; nothing between). Holds the canonical claim wording (its section 8). Awaits `ee-key` and `market-key`; changes no ratified value |
| [`macro-pass-conditions-PROPOSED.md`](macro-pass-conditions-PROPOSED.md) | **PROPOSED, not ratified** (issue #82). Gradable pass conditions, written before results where none exist, for epic #24 items 2-6 (sense amp, refresh controller, SPI, macro layout, post-layout PVT): quantity, corner set, threshold, ASSUMPTION or ratified-cited status, evidence testbench. Lists which conditions wait on bitline capacitance, offset statistics and Chipalooza rules, and open operator questions. Changes no ratified value |
