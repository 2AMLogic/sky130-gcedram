# Re-qualification inventory: open_pdks `c6d73a3` -> `f6eeac7`

Deliverable 1 of issue #166 (part of #165). **Documentation only: no
simulation was run and no existing record was edited.** All `c6d73a3`
records stay byte-identical (append-only, `sim/check_append_only.py`, #67);
re-qualification adds *new* records and supersession notes.

Measured with `grep -rl c6d73a3 sim layout` on `main` @ `4de3e77`
(80 stamped files); "cited by" is a `grep -rl <dir>` over `spec/`,
`block-manifest*.json` and
`sim/loaded-column/cold-corner/EVIDENCE_INDEX.md`. Re-derive the counts
before acting on them.

**Count convention:** "Stamped files" are *direct* counts. Each stamped file
is counted in exactly one row: the row of its nearest listed ancestor
directory, so unlisted subdirectories (`results/`, `sources/`, dated run
directories) roll up into their parent row and nested rows (e.g.
`geometry-matched`) are excluded from their parent. The column therefore sums
to 80, the `grep -rl c6d73a3 sim layout | wc -l` total.

## What counts as a re-qualified record

**A `grep -rl f6eeac7` hit is not a re-qualified record.** In a `klt sim`
report, `provenance.pdk.version` is the pin the *submitter* declared, while
`environment.remote.worker_environment.pdk.stamp_text` is what the machine
that actually executed the job had installed. Those two disagree across the
whole tree right now, and the repo recorded the disagreement rather than
hiding it. The state column below therefore uses four values:

| State | Meaning |
|---|---|
| **none** | No `f6eeac7` record exists for the row. |
| **declared-only** | `f6eeac7` records exist, but the executing worker stamped `c6d73a3`. `environment.remote.worker_environment.pdk_stamp_comparison.status` is `mismatch`, or `not_comparable` (the comparison could not be made at all), or the key is absent (the report predates the block). **Not re-qualified.** |
| **matched** | A batch `klt sim` report whose `environment.remote.worker_environment.pdk_stamp_comparison.status` is `match`. **No group is in this state** — see "The gate for the remaining re-runs". |
| **tool-run** | G5 only: a KLayout-only group with no SPICE leg, so no worker stamp exists to compare. Re-qualified against the measured PDK tree of the machine that ran it (`pdk.identity.open_pdks_commit`, read from `$PDK_ROOT/$PDK/SOURCES` by `layout/generation_toolchain.py`, and checked against the pin by its `pdk_problems()`). |

Measured on `main` @ `4de3e77`: of the 28 `f6eeac7`-declaring `klt_report*.json`
files, **23 are `mismatch`, 4 are `not_comparable`, 1 has no
`worker_environment` block, and none is `match`**. Three further `f6eeac7`
hits are prose or code rather than evidence —
`sim/loaded-column/cold-corner/check_evidence_index.py:37` (a
`FORWARD_OPEN_PDKS` constant), `sim/refresh-energy/README.md:456` (prose about
the worker pin) and `sim/sense-mismatch/README.md:272` (a supersession note
recording that it was *not* re-run).

## Table

Groups are ordered by evidence chain (retention chain first). "Reference"
= cited by the ratified spec, a manifest or the evidence index, so it must be
re-run; "historical" = not cited, marked superseded only. "State" gives the
issue that now owns the row and the state of its `f6eeac7` records, with a
path that verifies it.

| Group | Directory | Stamped files | State under `f6eeac7` | Cited by | Disposition |
|---|---|---|---|---|---|
| G1 (retention chain) | `sim/leakage` | 7 | **declared-only** — owner #166, records landed in PR #183. `sim/leakage/results/klt_report_20261016T0731Z.json` -> `mismatch`. The rolled-up `sim/leakage/compact-geometry/results/klt_report_20261020T1716Z.json` is also `mismatch`. | `retention-refresh-budget.md`, `retention-literature-crosscheck.md` | Reference: re-run first |
| G1 | `sim/leakage/geometry-matched` | 5 | **declared-only** — owner #166, landed in PR #183. `sim/leakage/geometry-matched/results/klt_report_20261016T0745Z.json` -> `mismatch`. | `retention-refresh-budget.md` | Reference: re-run |
| G1 | `sim/bitcell-transient` | 24 | **declared-only** — owner **#182** (`loom:operator`), split out of #168. 20 reports from PR #264, all `mismatch`, e.g. `sim/bitcell-transient/results/klt_report_read_d1_20261102T1845Z.json`. | none (cross-checks `sim/leakage`, see `docs/pdk-pin.md`) | Reference for the chain: re-run |
| G1 | `sim/retention` | 3 | **declared-only** — owner #166, landed in PR #183. `sim/retention/results/klt_report_20261022T0533Z.json` -> `not_comparable`, reason `client_stamp_unavailable` (no local stamp to compare against; the worker still stamped `c6d73a3`). | `retention-refresh-budget.md`, `spec/README.md`, crosscheck | Reference: re-derive after leakage; no retention number is re-cited before this |
| G2 (loaded column) | `sim/loaded-column` | 3 | **none** — owner #169 (open, `loom:blocked`). No `f6eeac7` record. | PROPOSED decision records, `EVIDENCE_INDEX.md` | Reference: re-run |
| G2 | `sim/loaded-column/cold-corner` | 8 | **none** — owner #169. Its only `f6eeac7` hit is the `FORWARD_OPEN_PDKS` constant in `check_evidence_index.py`, not a record. | PROPOSED decision records, `EVIDENCE_INDEX.md` | Reference: re-run; supersession entry goes in `EVIDENCE_INDEX.md` |
| G3 (sense path) | `sim/sense-stage` | 4 | **declared-only** — owner #170 (closed `completed`). `sim/sense-stage/results/klt_report_20261028T085441Z.json` -> `not_comparable`; the older `sim/sense-stage/results/klt_report_20261016T072807Z.json` carries no `worker_environment` block at all. | `macro-pass-conditions-PROPOSED.md` | Reference: re-run |
| G3 | `sim/column-periphery` | 5 | **declared-only** — owner #170. `sim/column-periphery/results/klt_report_20261028T085441Z.json` -> `not_comparable`. | none | Historical unless a spec cites it by the time of re-run |
| G3 | `sim/sense-mismatch` | 1 | **none** — owner #170. Explicitly not re-run; see the supersession note at `sim/sense-mismatch/README.md:272`. | none | Historical (Monte Carlo; re-run only if promoted to reference) |
| G3 | `sim/write-disturb` | 3 | **declared-only** — owner #170. `sim/write-disturb/results/klt_report_20261028T083505Z.json` -> `not_comparable`. | none | Historical |
| G4 (refresh) | `sim/refresh-replay` | 10 | **none** — owner #171 (open, `loom:blocked`). No `f6eeac7` record. | none | Historical |
| G4 | `sim/refresh-overhead` | 0 | **none** — owner #171. A 0 count means nothing here carries `c6d73a3`, not that the directory is absent. | `density-vs-sram.md`, `macro-pass-conditions-PROPOSED.md` | Reference, but consumes other groups' numbers: re-evaluate after G1-G3 |
| G4 | `sim/refresh-energy`, `sim/refresh-op` | 2 | **none** — owner #171. Both now carry `c6d73a3` (1 file each); `sim/refresh-energy/README.md:456` mentions `f6eeac7` in prose only. | none | Historical |
| Shared helper | `sim/test_evidence_common.py` | 1 | **n/a** — the stamps are test-fixture data, not evidence of a run. | none (shared helper of the evidence tests, carries the stamp in its fixtures) | Reference: its `c6d73a3` stamps are test-fixture data; update only if the evidence-test contract changes, not per re-run |
| G5 (layout) | `layout`, `layout/results` | 4 | **tool-run, re-qualified** — owner #172 (closed `completed`). `layout/results/generation_reproduction_f6eeac7_20261016.json` records `pdk.identity.open_pdks_commit = f6eeac7…` measured from the running tree's `SOURCES`; write-up at `layout/results/pdk_requalification_f6eeac7_20261016.md`. No `klt sim` leg exists, so no worker stamp applies. | both manifests, most specs | Reference: DRC/LVS/ERC results are tool-run, not PDK-model-run. Re-qualified 2026-10-16 (#172): no status or hash changed, only the `pdk.version` stamp in two generator reports; see `layout/results/pdk_requalification_f6eeac7_20261016.md` |

Six or more reference studies span G1-G5, so per the Champion/Curator
guidance on #166 the work is split per group rather than landed as one
PR (see "Split" below).

**Why the G5 count fell from 7 to 4.** At `bea81bb` the five single-cell and
array generator reports (`layout/gain_cell_2t.layout.json`,
`gain_cell_2t_array.layout.json`, `gain_cell_2t_array_mos.json`,
`gain_cell_2t_mos.json`, `gain_cell_2t_tap.json`) carried `c6d73a3`. Commit
`fbbb319` (2026-10-28) regenerated them with the klt 0.8.0 generators for a
DRC-clean cell and array, and the regenerated reports carry `f6eeac7`
directly. That was a generator change, not part of the #166 re-qualification,
and not a stamp edit: `layout/` is outside `check_append_only.py`'s protected
set (which covers `sim/**/results/**` plus
`sim/append_only_inventory.txt`), so the files were replaced by a rerun of
the generator rather than hand-edited.

## The gate for the remaining re-runs

A group leaves **declared-only** when, and only when, a batch `klt sim`
report committed under it satisfies

```
environment.remote.worker_environment.pdk_stamp_comparison.status == "match"
```

— the full path; the key is nested three levels under `environment`, and a
bare `pdk_stamp_comparison` grep will not find it in every schema version.
Nothing weaker counts:

* `mismatch` means the worker's sky130A revision differs from the submitter's.
* `not_comparable` means no comparison was possible (e.g. reason
  `client_stamp_unavailable` — the submitting host had no readable local
  stamp). It is not a pass.
* an absent `pdk_stamp_comparison` (or absent `worker_environment`) means the
  report predates the block and says nothing either way.
* a `provenance.pdk.version` of `f6eeac7` on its own never counts: that field
  is submitter-declared, and every such record on `main` today was executed
  on a `c6d73a3` worker.

**What would satisfy it:** pinning the sky130A install in the fleet worker
image to open_pdks `f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7` in the worker
spec, which lives in `2AMLogic/2am` under `infra/aws/loom-worker/` (a
different repository — not a change any sweep in this repo can make). That is
tracked on **#182**, which carries `loom:operator`: a human-held step, not
in-flight Builder work. #169 and #171 are parked on the same single
condition, each citing its own probe job (`klt-sim-9287ff5eedde` and
`klt-sim-2066534a33a7`).

## Batch-path findings behind the gate

* **Re-runs execute on the batch fleet, not on a dispatch host.** Multi-corner
  and Monte Carlo grids must be expressed as `klt sim` requests
  (`KLT_SIM_BACKEND=batch`, `--wait-for-capacity 600`); a submit failure is
  reported on the issue, never worked around with a local `ngspice -b` grid.
  A re-run's PDK identity is therefore a property of the *worker image*, which
  is why the gate above is a worker-spec change rather than host setup. A
  dispatch host's own `~/.ciel` / `~/.volare` state matters only in that it
  sets the declared pin and, when no stamp is readable there, yields
  `not_comparable` / `client_stamp_unavailable` instead of a usable
  comparison.
* **The worker still ships `c6d73a3`.** Every `f6eeac7`-declaring report on
  `main` that records a worker environment shows
  `environment.remote.worker_environment.pdk.stamp_text =
  open_pdks c6d73a35f524070e85faff4a6a9eef49553ebc2b`. The #169 and #171 probe
  jobs confirmed it independently of the committed records.
* **Simulator version is not the obstacle.** The fleet worker reports
  `ngspice-46` in
  `environment.remote.worker_environment.simulator.version_banner` — 27 of the
  28 `f6eeac7`-declaring reports, the 28th having no `worker_environment` — and
  that matches the `ngspice-46` the committed `c6d73a3` records carry. The
  `ngspice-42` visible in four of those reports is
  `environment.engine_build.version_banner`, the *submitting* host's local
  binary, which does not execute the grid. So a re-run under `f6eeac7` would
  not also move the simulator version, and a pin-only comparison stays a
  pin-only comparison. The earlier note in this file about a local
  `ngspice-42` described a dispatch host, not a machine that produces
  evidence.

## Split

Child issues, one per group, each `Part of #166`:

| Group | Issue | State |
|---|---|---|
| G1 retention chain (leakage, geometry-matched, retention) | #168 | Closed **`not_planned`**. Its leakage and retention records landed in **PR #183** (merged 2026-10-16, `3d7aa7c`); it was closed rather than completed because its one remaining criterion, `sim/bitcell-transient`, moved to #182. |
| G1 `sim/bitcell-transient` | **#182** | Open, `loom:operator`. **PR #264** (merged 2026-11-02, `59a9a65`) landed the grid as batch `klt sim` requests and recorded the stamp mismatch instead of claiming a re-qualification. |
| G2 loaded column | #169 | Open, `loom:blocked` on the gate above. No `f6eeac7` record. |
| G3 sense path | #170 | Closed `completed`. Its records are **declared-only**, the same condition as G1's: closing #170 recorded that the re-runs happened, not that the stamp matched. |
| G4 refresh | #171 | Open, `loom:blocked` on the gate above. No `f6eeac7` record. |
| G5 layout and sign-off | #172 | Closed `completed`. The only group re-qualified against a verified `f6eeac7` tree, and the only one with no SPICE leg. |

G1 goes first; no retention number is re-cited until its chain is re-derived,
and since no G1 record is stamp-matched that condition is still unmet. G2-G4
depend on G1 results. The gate above applies to every remaining re-run.
