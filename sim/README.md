# sim

ngspice testbenches and PVT-corner results. Everything in this directory
runs from a stock `open_pdks` sky130 install (via `volare`) -- no local
model edits, no uncommitted `.include` paths. Results files are
**append-only evidence** per `CLAUDE.md`: reruns append new rows, they
never overwrite or truncate prior results.

## Append-only evidence guard (issue #67)

[`check_append_only.py`](check_append_only.py) enforces the append-only
rule on every pull request (`append-only` job in
[`../.github/workflows/evidence-checks.yml`](../.github/workflows/evidence-checks.yml)).
It compares **committed Git blobs** at `git merge-base BASE HEAD` against
HEAD -- never worktree text -- using raw bytes and NUL-delimited Git output.
Stdlib Python plus `git` only; no PDK, ngspice or klt.

**Protection inventory** (derived from the *merge-base* tree, so deleting a
file or editing the inventory in the same PR cannot remove its protection):

1. every tracked file under `sim/` with a directory component named
   `results` -- currently `sim/*/results/` (including `sim/sense-stage/results/`) and
   `sim/loaded-column/cold-corner/results/` (CSV results plus the two
   `summary_*.json` files);
2. any path listed in
   [`append_only_inventory.txt`](append_only_inventory.txt): committed
   result-summary files that live *outside* a `results` directory. The list
   is currently empty (re-inventoried 2026-10-09: every tracked result
   summary under `sim/` is inside a `results` directory). JSON is not
   protected by extension -- configuration/input JSON stays editable.

**Rules** for each protected path:

| Case | Verdict |
| --- | --- |
| new file at HEAD (anywhere) | pass |
| unchanged | pass |
| `*.csv`: old bytes are an exact prefix of new bytes (EOF append) | pass |
| `*.csv`: was empty, now has content | pass |
| `*.csv`: nonempty and old content lacks a final LF, any change | **fail** -- appending would alter the last record; write a new evidence file |
| `*.csv`: middle insertion, rewrite, CRLF/LF normalisation, truncation | **fail** |
| any other file (e.g. `summary_*.json`): any byte change | **fail** |
| deleted, renamed or moved (even if a copy is added elsewhere) | **fail** |
| object type or file mode changed | **fail** |

An added copy is fine as long as the original stays at its path. CSV
prefix preservation is a byte-integrity check only; whether appended rows
are scientifically valid is still a review question.

**Fail closed.** Exit `0` = pass, `1` = violation(s) (offending paths are
listed), `2` = the check could not run: base/head commit missing, all-zero
SHA, shallow repository, no merge base, an inventory entry absent from the
merge base, or any `git` / blob-read error. Exit `2` fails the job; it is
never reported as a pass.

**No bypass.** There is no label, commit marker, flag or environment
variable that skips the check. To correct a finding, leave the existing
evidence committed as-is and add a **new** evidence file plus a correction
record citing the original (see [Correcting recorded evidence](#correcting-recorded-evidence-issue-68)).
CI runs the checker as committed on the base branch when it exists there, so
a PR cannot weaken the check that judges it.

Invocation (exactly what CI runs, from the repository root, with full
history fetched):

```bash
python3 -I sim/check_append_only.py --base <BASE_SHA> --head <HEAD_SHA>
python3 -I sim/test_append_only.py   # temporary-Git-repo regression fixtures
```

## Correcting recorded evidence (issue #68)

This is the **sole** correction mechanism. It adds files; it never edits
history. The guard above ([#67](#append-only-evidence-guard-issue-67))
stays in force and has no bypass, so a correction that touches the original
fails CI by design.

**Rules**

1. Never rewrite, truncate, delete, rename or move the original artifact.
   It stays at its path with its bytes unchanged, so the incorrect finding
   remains inspectable.
2. Add a **new** evidence artifact (the corrected results, under a
   `results/` directory, at a new path) and a **new** correction write-up
   (`CORRECTION-<NNNN>-<slug>.md`, next to the original's `README.md`) in the
   same PR.
3. The write-up uses the template below. Every field is required; write
   `none` or `n/a` with a reason rather than omitting one.
4. Corrected numbers are only ever produced by a committed, reproducible
   run against the stock pinned PDK. Hand-edited numbers are not evidence.
5. A correction does not change any spec by itself (see Authorization).

**Template** (copy into `CORRECTION-<NNNN>-<slug>.md`)

```markdown
# Correction <NNNN>: <short title>

## Original (preserved, unmodified)
- Path: <repo path of the original artifact>
- Commit: <full SHA that introduced it>
- Blob hash: <output of `git rev-parse <commit>:<path>`>

## Incorrect finding
<What the original stated or implied, quoted or cited by row/field.>

## Reason
<Root cause: wrong bias, unit error, stale model pin, bad parse, ...>

## Corrected artifact
- Path: <new repo path, distinct from the original>
- Commit: <SHA of the PR commit adding it>
- Blob hash: <`git rev-parse <commit>:<path>`>

## Reproduction command
<Exact command(s) from the repository root, pinned PDK/tool versions,
and which corners/temperatures it covers.>

## Consequences for dependent claims
| Dependent claim / document | Affected? | Action |
| --- | --- | --- |
| <e.g. spec/..., README number, downstream result> | yes/no | <none / spec change proposed in #N> |
```

**Authorization**

| Change | Who approves | How |
| --- | --- | --- |
| Adding corrected evidence and the write-up | normal PR review | ordinary reviewer approval of the PR |
| Any change to a specification or ratified claim | existing two-key process | a `spec/` decision record, ratified by the EE and market keys (`ratification/`) |

A correction PR may *propose* a spec change in the "Consequences" table and
link to a separate decision record. Until that record is ratified, the
ratified claim stands and the correction is documented as pending. Agents
cannot self-authorize a spec relaxation, and a correction must never be used
to make results pass a spec by changing the spec (`CLAUDE.md`).

**Worked example -- ILLUSTRATIVE ONLY.** Every path, hash and number below is
fabricated to show the shape of a correction. None of it is a measured
result and none of it is committed as evidence in this repository.

Suppose `sim/example/results/example_results.csv` (commit `aaaa111`, blob
`1111111`) reported a leakage of `9.9e-12 A` at `sf/125 C` because of a unit
error. The correcting PR contains additions only:

```text
 sim/example/results/example_results.csv                 (unchanged, original kept)
A sim/example/results/example_results_corr0001.csv       (new: corrected rows)
A sim/example/CORRECTION-0001-leakage-units.md           (new: write-up)
```

and the write-up reads:

```markdown
# Correction 0001: leakage unit error (ILLUSTRATIVE)

## Original (preserved, unmodified)
- Path: sim/example/results/example_results.csv
- Commit: aaaa111... (fabricated)
- Blob hash: 1111111... (fabricated)

## Incorrect finding
Row `sf,125` reports 9.9e-12 A (fabricated).

## Reason
Value was scaled per micron twice (fabricated).

## Corrected artifact
- Path: sim/example/results/example_results_corr0001.csv
- Commit: bbbb222... (fabricated)
- Blob hash: 2222222... (fabricated)

## Reproduction command
python3 sim/example/run_example.py --out sim/example/results/example_results_corr0001.csv

## Consequences for dependent claims
| spec/retention-refresh-budget.md | yes | none applied; change proposed
in a separate spec decision record, pending two-key ratification |
```

Reviewers verify with `git diff --name-status BASE...HEAD`: evidence paths
show only `A`, never `M`, `D` or `R`, and `python3 -I sim/check_append_only.py`
passes.

## `leakage/` -- access-device off-state leakage (issue #2)

First link in the retention/refresh budget evidence chain: measures the
candidate 2T/3T gain-cell access device's (`sky130_fd_pr__nfet_01v8`)
off-state leakage (subthreshold conduction + reverse-biased drain-body
junction leakage) against the shipped sky130 models, swept across the 5
shipped MOS process corners (`tt`/`ss`/`ff`/`sf`/`fs`) and the
`-40/27/125 °C` temperature range. See
[`leakage/README.md`](leakage/README.md) for the device-choice rationale,
bias condition, worst-case-corner call-out, and full reproduction
instructions; raw results are in
[`leakage/results/leakage_results.csv`](leakage/results/leakage_results.csv).

Quick start (requires `ngspice` on `PATH` and the PDK pinned in
[`../docs/pdk-pin.md`](../docs/pdk-pin.md) enabled via `volare`):

```bash
python3 sim/leakage/run_leakage_sweep.py --check-env
python3 sim/leakage/run_leakage_sweep.py
```

This is the leakage half of the evidence chain `CLAUDE.md` requires
before any retention-time number can be claimed; the storage-node
capacitance assumption and the retention derivation itself are tracked in
issue #3.

## `retention/` -- retention-time derivation for candidate 2T/3T geometries (issue #3)

Second and third links in the retention/refresh budget evidence chain:
combines the measured worst-case leakage above with an explicitly labelled
storage-node capacitance ASSUMPTION (no layout exists yet to extract one
from) to derive retention-time estimates for a `2T-min` and a `3T-min`
candidate gain-cell geometry, at the worst-case temperature corner. See
[`retention/README.md`](retention/README.md) for the full derivation
(formula, inputs, and which numbers are measured vs. computed vs.
assumed); results are in
[`retention/results/retention_results.csv`](retention/results/retention_results.csv).

Quick start (requires the same PDK install as `leakage/`, no ngspice
invocation needed):

```bash
python3 sim/retention/derive_retention.py --check-env
python3 sim/retention/derive_retention.py
```

## `loaded-column/` -- loaded four-row column: stored levels and read separation (issue #45)

Characterization (not sense-amplifier design) of one four-row column of the
2T bitcell across the 15-point PVT grid, fresh and aged to the ~5.03 us
refresh bound, for every selected row and all patterns of the other rows, with
declared (assumed, schematic-level) bitline loading. Includes signed
deselected-row currents, latency, read disturb and machine-readable results;
failing corners remain visible. See
[`loaded-column/README.md`](loaded-column/README.md).

```bash
python3 sim/loaded-column/run_loaded_column.py --check-env
python3 sim/loaded-column/run_loaded_column.py
python3 sim/loaded-column/analyze_loaded_column.py
```

### `loaded-column/cold-corner/` -- cold-corner failure: attribution and remedies (issue #47)

Reproduces the Phase 2 `fs/-40 C` failure (bit-identical), attributes it with
one-knob-at-a-time sweeps (write drive and timing, read-device sizing and
flavour, read drive, bitline load, sense time, forced stored level), and
compares remedy classes on the full 15-point grid at both ages. It includes
the failed variants and a negative control. A next design contract is
proposed, not ratified. See
[`loaded-column/cold-corner/README.md`](loaded-column/cold-corner/README.md).

```bash
python3 sim/loaded-column/cold-corner/run_variants.py --list
python3 sim/loaded-column/cold-corner/analyze_variants.py
python3 sim/loaded-column/cold-corner/test_variants.py
```

**Supply/reliability evidence package (issue #49, documentation only):**
[`EVIDENCE_INDEX.md`](loaded-column/cold-corner/EVIDENCE_INDEX.md) indexes the
stress/limit inventory, the sense input contract and the pinned primary
source; the decision record is PROPOSED, not ratified
([`spec/supply-reliability-decision-PROPOSED.md`](../spec/supply-reliability-decision-PROPOSED.md)).
Check: `python3 sim/loaded-column/cold-corner/check_evidence_index.py`.

## `sense-stage/` -- single-ended latch sense stage at the restricted corners (issue #60)

Characterizes a first-pass latch sense stage driven per
[`SENSE_INPUT_CONTRACT.md`](loaded-column/cold-corner/SENSE_INPUT_CONTRACT.md)
over exactly the corners and temperatures of the **PROPOSED, unratified**
restricted range ([`spec/operating-range-decision-PROPOSED.md`](../spec/operating-range-decision-PROPOSED.md):
tt/ss/ff/sf/fs at 27 C and 125 C, 1.8 V). The 10-corner grid is one
`klt sim` batch request. Reports minimum resolvable `delta_V` and sense time
per corner, and a FINDING on the `VDD`/2 assumption in `retention/` (no spec
edited). See [`sense-stage/README.md`](sense-stage/README.md).

```bash
python3 -I sim/sense-stage/gen_sense_stage.py
python3 -I sim/sense-stage/test_sense_stage.py
```

## `bitcell-transient/` -- 2T-min bitcell write / read / hold transient (issue #27)

The **first circuit-level simulation of the ratified bitcell**: the two
studies above look at the cell one piece at a time (a DC operating point on
a single access device, then an analytic derivation on top of it), while
this one exercises the whole cell as a circuit in a single `.tran` --
writing a '1' and a '0', reading both, and timing the storage node's decay
-- across the same `tt`/`ss`/`ff`/`sf`/`fs` x `-40/27/125 °C` grid. The deck
`.include`s [`design/gain_cell_2t.spice`](../design/gain_cell_2t.spice)
verbatim rather than transcribing the devices, and loads `sn` with the
post-layout extracted `C_SN` from
[`layout/gain_cell_2t.extract.parasitics.json`](../layout/gain_cell_2t.extract.parasitics.json)
(issue #7, overridable with `--c-sn-ff`). See
[`bitcell-transient/README.md`](bitcell-transient/README.md) for the phase
timing, the `rbl` bias choice, the `.tran` settings and their convergence
check, the worst-case-corner call-out (`sf`/125 °C,
`t_ret_tran` = 2.3958e-05 s), the three corners where the assumed 0.9 V
sense margin turns out to be **unattainable** with a plain-1.8 V wordline,
and the cross-check against `retention/`'s analytic 5.50 µs; raw results are
in
[`bitcell-transient/results/bitcell_transient_results.csv`](bitcell-transient/results/bitcell_transient_results.csv).

Quick start (requires `ngspice` on `PATH`, the PDK pinned in
[`../docs/pdk-pin.md`](../docs/pdk-pin.md) enabled via `volare`, and the
leakage results above already committed -- the hold window is seeded from
them):

```bash
python3 sim/bitcell-transient/run_bitcell_transient.py --check-env
python3 sim/bitcell-transient/run_bitcell_transient.py
```

This is the read-current / written-level / read-disturb evidence the array,
the sense amplifier and the write-margin decision in issue #24 each consume;
it does **not** re-ratify any retention number in
[`spec/retention-refresh-budget.md`](../spec/retention-refresh-budget.md),
which remains a separate, gated spec change.
