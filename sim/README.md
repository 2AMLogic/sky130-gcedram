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
evidence committed as-is and add a **new** evidence file with a correction
record citing the original (correction-record policy: issue #68). CI runs
the checker as committed on the base branch when it exists there, so a PR
cannot weaken the check that judges it.

Invocation (exactly what CI runs, from the repository root, with full
history fetched):

```bash
python3 -I sim/check_append_only.py --base <BASE_SHA> --head <HEAD_SHA>
python3 -I sim/test_append_only.py   # temporary-Git-repo regression fixtures
```

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

## `write-disturb/` -- disturb of unselected and half-selected cells in the extracted 4x4 array (issue #98)

Epic #24 item 6. Ten instances of the committed **extracted** 4x4 array
([`layout/gain_cell_2t_array.extract.parasitics.spice`](../layout/gain_cell_2t_array.extract.parasitics.spice))
are driven with one wordline pulse (half-select, both data polarities) and
with 147 back-to-back writes (the most a 34 ns scheduler could issue in the
5.03 us ratified window), against no-toggle controls and a deliberately leaky
negative control, over the PROPOSED restricted range (tt/ss/ff/sf/fs at
27 C and 125 C, 1.8 V; one `klt sim` batch request). Disturb is reported as a
fraction of `delta_V` = 0.9 V and as equivalent retention loss; the ratified
spec and refresh bound are not touched. See
[`write-disturb/README.md`](write-disturb/README.md).

```bash
python3 -I sim/write-disturb/gen_write_disturb.py
python3 -I sim/write-disturb/test_write_disturb.py
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
