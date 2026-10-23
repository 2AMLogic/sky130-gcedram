# Re-qualification inventory: open_pdks `c6d73a3` -> `f6eeac7`

Deliverable 1 of issue #166 (part of #165). **Documentation only: no
simulation was run and no existing record was edited.** All `c6d73a3`
records stay byte-identical (append-only, `sim/check_append_only.py`, #67);
re-qualification adds *new* records and supersession notes.

Measured with `grep -rl c6d73a3 sim layout` on `main` @ `bea81bb`
(47 stamped files); "cited by" is a `grep -rl <dir>` over `spec/`,
`block-manifest*.json` and
`sim/loaded-column/cold-corner/EVIDENCE_INDEX.md`. Re-derive the counts
before acting on them.

**Count convention:** "Stamped files" are *direct* counts. Each stamped file
is counted in exactly one row: the row of its nearest listed ancestor
directory, so unlisted subdirectories (`results/`, `sources/`, dated run
directories) roll up into their parent row and nested rows (e.g.
`geometry-matched`) are excluded from their parent. The column therefore sums
to 47, the `grep -rl c6d73a3 sim layout | wc -l` total.

## Table

Groups are ordered by evidence chain (retention chain first). "Reference"
= cited by the ratified spec, a manifest or the evidence index, so it must be
re-run; "historical" = not cited, marked superseded only.

| Group | Directory | Stamped files | Cited by | Disposition |
|---|---|---|---|---|
| G1 (retention chain, #168) | `sim/leakage` | 3 | `retention-refresh-budget.md`, `retention-literature-crosscheck.md` | Reference: re-run first |
| G1 | `sim/leakage/geometry-matched` | 3 | `retention-refresh-budget.md` | Reference: re-run |
| G1 | `sim/bitcell-transient` | 2 | none (cross-checks `sim/leakage`, see `docs/pdk-pin.md`) | Reference for the chain: re-run |
| G1 | `sim/retention` | 1 | `retention-refresh-budget.md`, `spec/README.md`, crosscheck | Reference: re-derive after leakage; no retention number is re-cited before this |
| G2 (loaded column, #169) | `sim/loaded-column` | 3 | PROPOSED decision records, `EVIDENCE_INDEX.md` | Reference: re-run |
| G2 | `sim/loaded-column/cold-corner` | 8 | PROPOSED decision records, `EVIDENCE_INDEX.md` | Reference: re-run; supersession entry goes in `EVIDENCE_INDEX.md` |
| G3 (sense path, #170) | `sim/sense-stage` | 3 | `macro-pass-conditions-PROPOSED.md` | Reference: re-run |
| G3 | `sim/column-periphery` | 4 | none | Historical unless a spec cites it by the time of re-run |
| G3 | `sim/sense-mismatch` | 1 | none | Historical (Monte Carlo; re-run only if promoted to reference) |
| G3 | `sim/write-disturb` | 1 | none | Historical |
| G4 (refresh, #171) | `sim/refresh-replay` | 10 | none | Historical |
| G4 | `sim/refresh-overhead` | 0 | `density-vs-sram.md`, `macro-pass-conditions-PROPOSED.md` | Reference, but consumes other groups' numbers: re-evaluate after G1-G3 |
| G4 | `sim/refresh-energy`, `sim/refresh-op` | 0 | none | Not stamped `c6d73a3`; check their stamps before marking |
| Shared helper | `sim/test_evidence_common.py` | 1 | none (shared helper of the evidence tests, carries the stamp in its fixtures) | Reference: its `c6d73a3` stamps are test-fixture data; update only if the evidence-test contract changes, not per re-run |
| G5 (layout, #172) | `layout`, `layout/results` | 7 | both manifests, most specs | Reference: DRC/LVS/ERC results are tool-run, not PDK-model-run. Re-qualified 2026-10-16 (#172): no status or hash changed, only the `pdk.version` stamp in two generator reports; see `layout/results/pdk_requalification_f6eeac7_20261016.md` |

Six or more reference studies span G1-G5, so per the Champion/Curator
guidance on #166 the work is split per group rather than landed as one
PR (see "Split" below).

## Host findings that gate the re-runs

* **No `f6eeac7` tree at the pinned default.** `~/.ciel` does not exist on
  this host; only the retired `~/.volare` tree at `c6d73a3` is present. A
  `f6eeac7` tree exists under a throwaway `/tmp` path belonging to another
  job and must not be relied on. Re-runs need a `PDK_ROOT` provisioned by
  the worker spec or built inside the worktree (`ciel`, per
  `docs/pdk-pin.md`).
* **Simulator version.** The committed records are stamped `ngspice-46`
  (12,553 occurrences; `ngspice-47` appears 32 times), but this host has
  `ngspice-42`. A pin-only comparison would conflate the PDK change with a
  simulator change, so a re-run needs the same `ngspice` as the original
  records, or the version delta must be called out per result. Host tools
  are not changed from a sweep (worker spec change).
* **Batch backend.** Multi-corner and Monte Carlo grids must go through
  `klt sim` (`KLT_SIM_BACKEND=batch`); any submit failure is reported on
  the issue, not worked around with a local grid.

## Split

Child issues already filed, one per group, each `Part of #166`: G1 #168
(retention chain), G2 #169 (loaded column), G3 #170 (sense path), G4 #171
(refresh), G5 #172 (layout and sign-off). G1 goes first; no retention number
is re-cited until its chain is re-derived. G2-G4 depend on G1 results; the
host prerequisites above apply to all of them.
