# Sense-stage characterization at the restricted corners (issue #60)

Epic #24 item 2, increment named by
[`spec/operating-range-decision-PROPOSED.md`](../../spec/operating-range-decision-PROPOSED.md)
section 10. **Everything here sits under a PROPOSED, UNRATIFIED operating
range.** The corner set (27 C and 125 C, tt/ss/ff/sf/fs global corners,
`VDD` = 1.8 V) is the interval that record proposes; nothing outside it
was simulated (no -40 C, no other supply, no mismatch). If the two-key
process rejects or changes that range, this evidence still describes only
those points. No ratified value or spec file was edited; any spec change
needs a decision record.

## What was built

| File | Role |
|---|---|
| [`gen_sense_stage.py`](gen_sense_stage.py) | generates the two files below (all constants and ASSUMPTIONs live at its top) |
| [`sense_stage.spice`](sense_stage.spice) | flat circuit body for `klt sim` (98 parallel instances; bitcell cards inlined from `design/gain_cell_2t.spice`, checked by the test) |
| [`request.json`](request.json) | the `klt sim` request: 5 process corners x {27, 125} C = 10 corners, one `tran` each, `backend: batch` |
| [`analyze_sense_stage.py`](analyze_sense_stage.py) | reduces the committed klt report to per-point CSV + per-corner summary (writes new files only) |
| [`test_sense_stage.py`](test_sense_stage.py) | stdlib checks (generated files not stale, scope equals the proposed range, summary reproduces from the committed report); wired into CI |
| `results/` | append-only evidence (below) |

No sense cell is a *design* deliverable yet (sizes are first-pass), so no
schematic was added under `design/`; one belongs with the follow-up that
fixes a cell.

### The stage (ASSUMPTION: topology and sizes)

A clocked cross-coupled-inverter latch. One side is the read bitline
`rbl` (the cell/column drives it directly), the other is a reference node
`ref` held at `VREF` = `VRBL` - offset through the same ideal precharge
switch and loaded by a matched dummy capacitor. NMOS footer and PMOS header
(`sky130_fd_pr__nfet_01v8` / `pfet_01v8`; latch N 1.0/0.15, P 2.0/0.15,
footer 2.0/0.15, header 4.0/0.15 um) enable it. A stored '1' pulls `rbl`
down, so the correct decision is `d = V(rbl) - V(ref)` -> -1.8 V.

### Inputs, per `SENSE_INPUT_CONTRACT.md` (baseline column)

| Contract input | Used here | Status |
|---|---|---|
| `rbl` precharge 0.9 V, released 2 ns before the select edge | same, ideal 100 ohm switch | STUDY-ASSUMPTION |
| `C_RBL` 10 fF | same, on `rbl` and on the dummy reference | ASSUMPTION (not extracted) |
| read word line 1.8 -> 0 V, deselected 1.8 V | same, ideal drivers | EVIDENCE (Phase 2) |
| sense instant 10 ns after select edge | latch enable at +10 ns | ASSUMPTION |
| 4-row column, `C_SN` 0.605354 fF | same; all four rows hold ONE level (selected row = deselected rows) | STUDY-ASSUMPTION |
| stored-level inputs | swept directly as pre-read `SN` levels (0.30 .. 1.20 V for '1'; -0.10, 0.00 V for '0'), 0.05 V steps | sweep, not a measurement |
| `common_reference_v_UNVALIDATED` | **not used** (the contract says do not use) | -- |
| reference level | swept: `VREF` = 0.9 V minus 20 / 50 / 100 / 200 mV | ASSUMPTION |
| decision criterion | `|d|` >= 0.9 V at full swing, correct sign, `t_dec` <= 5 ns after enable | ASSUMPTION |
| mismatch / offset budget | NOT AVAILABLE here (global corners, no Monte Carlo); see [`sim/sense-mismatch/`](../sense-mismatch/README.md) (issue #81) for this latch's offset at four corners | -- |

> Cross-reference (issue #114): the ideal 100 ohm precharge switch above is compared against a designed PMOS precharge, write driver and isolation gate in [`sim/column-periphery`](../column-periphery/README.md); the ideal-vs-real delta is tabulated there. The text above is the original study assumption and is left as written.

Instance kinds: `st_*` (stage only: `rbl` starts at `VREF` +/- 1..100 mV,
no cells), `cell1_*` (end-to-end, stored '1' at the given level),
`cell0_*` (end-to-end, stored '0'). The `cell0_*` instances are the
negative control the contract asks for (rule 3): a '1' that was never
written must read as '0'; they all do. Failed points are kept in the CSV.

## How it was run (host rules)

* The 10-corner grid is a single `klt sim` request on the **batch fleet**;
  nothing was looped locally. Fleet job: **`klt-sim-8c62fc8d1019`** (c7i.8xlarge,
  spot, state `done`, 73 s; recorded in `environment.remote` of the report).
* One **local** single-corner debug probe (`tt`/27 C, `--backend local`) was
  run before submitting to check the deck; it is not recorded as evidence
  and agrees with the fleet's tt/27 C numbers.
* The first submission used the host's `klt` 0.7.0 and was refused by the
  fleet runner (klt 0.5.0, `batch_runner_version_mismatch`): **not
  produced**; the report is committed as a failed-attempt record
  (`klt_report_20261009T131033Z.json`, no numbers). It was resubmitted with
  a throwaway `uvx --from klayout-tools==0.6.0 klt` (no host tool was
  changed). A second fleet job with mixed-case `.meas` names returned no
  values (case-sensitive matching against ngspice's lower-cased output in
  the runner's klt); the deck was changed to lower-case names and that job's
  output is not kept. Both are existing klayout-tools friction:
  [#2914](https://github.com/2AMLogic/klayout-tools/issues/2914) (mixed-case
  `.meas` names fail on the fleet runner),
  [#2948](https://github.com/2AMLogic/klayout-tools/issues/2948) and
  [#2851](https://github.com/2AMLogic/klayout-tools/issues/2851) (runner/client
  version skew). No new issue was filed because these cover the gaps.
* Committed reports have the job bucket name redacted
  (`<redacted-bucket>`); the rest is the unmodified klt output.

## Evidence (append-only)

Run `20261009T131831Z`: netlist sha256 `4cd2834df7cf42edd4553adf158cfa99686bc832cfe862a778e9c2b3c3530ff0`
(as hashed by klt), model library sha256 `48de7c67...133c84`, ngspice-46,
open_pdks `c6d73a35...` per [`docs/pdk-pin.md`](../../docs/pdk-pin.md).
Files in [`results/`](results/) are protected by `sim/check_append_only.py`
(any file under a `results` directory); rerun with a **new** run id, never
edit these.

* `klt_report_20261009T131831Z.json` raw klt report, 10/10 corners pass
* `sense_points_20261009T131831Z.csv` 980 rows (10 corners x 98 instances)
* `sense_summary_20261009T131831Z.json` per-corner metrics, assumptions, claims flags

**Superseded** for the spec-cited record by run `20261016T072807Z` under `f6eeac7` (see "Re-qualification under `f6eeac7`" below); this run is kept unedited as history.

Reproduce: `python3 -I sim/sense-stage/gen_sense_stage.py`, then
`uvx --from klayout-tools==0.6.0 klt sim --format json sim/sense-stage/request.json > sim/sense-stage/results/klt_report_<NEW_RUN_ID>.json`
(`KLT_SIM_BACKEND=batch`; 0.6.0 is the newest client the fleet runner
accepted on 2026-10-09), then `analyze_sense_stage.py` on that report.

## Re-qualification under `f6eeac7` (issue #170, run `20261016T072807Z`)

Supersedes run `20261009T131831Z` (open_pdks `c6d73a3`) for the spec-cited
sense-stage evidence. The old run's files are untouched and remain as the
historical record.

* Request: `request.json` unchanged, one `klt sim` request, 10 corners,
  batch fleet (`uvx --from klayout-tools==0.6.0 klt sim`, `KLT_SIM_BACKEND=batch`).
  Fleet job **`klt-sim-c7d335a7bfdc`** (m7i.4xlarge, spot, `done`, 119 s).
  10/10 corners pass. Earlier same-day submits failed at the fleet's
  `BATCH_MAX_CONCURRENT_INSTANCES=8` cap (no results, nothing committed).
* Files: `results/klt_report_20261016T072807Z.json`,
  `results/sense_points_20261016T072807Z.csv`, `results/sense_summary_20261016T072807Z.json`
  (bucket name redacted as before).
* **PDK revision.** The report's `provenance.pdk` records
  `open_pdks f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7`, source
  `search root: ~/.ciel` (old run: `c6d73a35...`, `~/.volare`). That
  stamp is written by the runner that ran the job (the submitting host has no
  `~/.ciel` tree), so it is the evidence that the fleet used `f6eeac7`.
  Caveat: `models_lib_sha256` / `deck.content_hash` is **identical** to the
  old run (`48de7c67...133c84`). It hashes only the top-level
  `sky130.lib.spice`, so it does not distinguish the two revisions; the
  included device model files are not hashed separately by klt.
* **Simulator.** `engine_version` is `46` in both runs, and klt 0.6.0 /
  KLayout 0.30.12 are the same, so there is no simulator delta to separate
  from the PDK change. Netlist sha256 is unchanged (`4cd2834d...530ff0`).
* **Before/after.** Every per-corner quantity is identical to run
  `20261009T131831Z`: `sense_points_20261016T072807Z.csv` is byte-identical to the old
  CSV (980 rows), and `sense_summary_20261016T072807Z.json` differs only in run id, fleet
  job id and instance type. So for all 10 corners the min resolved delta_V
  bracket, `t_dec` at 1 mV, and the end-to-end lowest resolving stored-'1'
  level (table above) have delta = 0; no result moved, so no follow-up issue
  or decision record is needed and no spec threshold is touched. Only the
  per-corner `runtime_s` fields differ (21-24 s, host-speed noise).
* Reproduce: as in "Evidence" above with a new run id.

## Results

All numbers are from the summary JSON above. Sense time = enable at
select + 10 ns (ASSUMPTION) plus `t_dec` (enable edge to `|d|` = 0.9 V).

### Minimum resolvable delta_V per corner

**Stage only (systematic).** Every swept point, +/-1 mV to +/-100 mV on both
polarities, resolved correctly at all ten corners. The smallest swept
input is the floor: `|d|` at the enable instant of 1.10-1.31 mV (a few
tenths of a mV of drift from the nominal 1 mV while `rbl` floats). **This is
a bound set by the sweep (and by solver tolerance near 1 mV), not a measured
minimum.** Global corners have no mismatch, so no systematic offset appears;
the random offset that sets a real minimum delta_V is **not** characterized
(needs `monte_carlo`; not run). `t_dec` at the 1 mV point is 0.27-0.51 ns
(ff/125 fastest, ss/27 slowest).

**End to end (cell + column + stage).** Lowest stored-'1' pre-read level
that resolves (every swept level above it also resolves; the true minimum
lies in the 0.05 V bracket below the value shown), by reference offset, and
the swing that leaves relative to the Phase 2 baseline written level
(`v_sn1_after_write_min_v`, min over 64 patterns):

| Corner | T (C) | stage floor `|d|` (mV, - / +) | `t_dec` @ 1 mV (ns) | written '1' min (V) | min resolvable `SN` at ref offset 20 / 50 / 100 / 200 mV (V) | usable `dV_SN` at 100 mV (V) | usable `dV_SN`, best swept ref (V) | best / (`VDD`/2) |
|---|---:|---|---:|---:|---|---|---|---|
| tt | 27 | 1.11 / 1.11 | 0.38 | 1.028 | 0.55 / 0.6 / 0.65 / 0.7 | 0.38-0.43 | 0.48-0.53 (20mV) | 0.53-0.59 |
| tt | 125 | 1.16 / 1.16 | 0.33 | 1.123 | 0.45 / 0.5 / 0.55 / 0.6 | 0.57-0.62 | 0.67-0.72 (20mV) | 0.75-0.80 |
| ss | 27 | 1.12 / 1.12 | 0.51 | 0.961 | 0.65 / 0.7 / 0.7 / 0.75 | 0.26-0.31 | 0.31-0.36 (20mV) | 0.34-0.40 |
| ss | 125 | 1.14 / 1.14 | 0.41 | 1.048 | 0.55 / 0.6 / 0.65 / 0.65 | 0.40-0.45 | 0.50-0.55 (20mV) | 0.55-0.61 |
| ff | 27 | 1.10 / 1.10 | 0.30 | 1.088 | 0.5 / 0.55 / 0.6 / 0.6 | 0.49-0.54 | 0.59-0.64 (20mV) | 0.65-0.71 |
| ff | 125 | 1.31 / 1.31 | 0.27 | 1.187 | 0.4 / 0.45 / 0.5 / 0.55 | 0.69-0.74 | 0.79-0.84 (20mV) | 0.88-0.93 |
| sf | 27 | 1.12 / 1.12 | 0.39 | 1.123 | 0.45 / 0.5 / 0.55 / 0.55 | 0.57-0.62 | 0.67-0.72 (20mV) | 0.75-0.80 |
| sf | 125 | 1.17 / 1.17 | 0.33 | 1.217 | 0.35 / 0.4 / 0.45 / 0.5 | 0.77-0.82 | 0.87-0.92 (20mV) | 0.96-1.02 |
| fs | 27 | 1.10 / 1.10 | 0.38 | 0.932 | 0.7 / 0.7 / 0.75 / 0.8 | 0.18-0.23 | 0.23-0.28 (50mV) | 0.26-0.31 |
| fs | 125 | 1.21 / 1.21 | 0.33 | 1.027 | 0.55 / 0.6 / 0.65 / 0.7 | 0.38-0.43 | 0.48-0.53 (20mV) | 0.53-0.59 |

`usable dV_SN` = written level - min resolvable level, given as
[pessimistic, optimistic] because of the 0.05 V grid. Rows: sf/125 is the
ratified worst-case retention corner; 27 C is the restricted cold bound.
Sense time at `SN` = 1.0 V is 0.05-0.11 ns of `t_dec` at every corner
(`sense_time_ns_at_1p0V` in the summary), i.e. about 10.1 ns after the
select edge; near the resolvable limit `t_dec` is 0.12-0.35 ns. The cell
keeps discharging `rbl` while the latch regenerates, so the decision is a
read-through, not a snapshot at the enable instant: at the limit the
differential at the enable edge (`din`) can already be near zero or even
the wrong sign. The limit therefore depends on the enable time and the 5 ns
window, both ASSUMPTIONs. Stored '0' resolved correctly at every corner and
reference (all four references, both '0' levels).

## FINDING: the `VDD`/2 assumption in the retention study

`sim/retention` and the ratified record use `delta_V` = `VDD`/2 = 0.9 V
(ASSUMPTION) in `t_ret = C_SN * delta_V / I_leak`. The retention formula
spends `delta_V` as the **droop of the storage node** from its written
level. Two readings, kept separate:

1. **Stored-level reading** (the PROPOSED record's "stored-level
   compatibility": the stored '1' must stay >= 0.9 V): the stage resolves a
   stored '1' at 0.9 V at every corner and every reference swept
   (`stored1_at_vdd_half_resolves`). **Met.** It is also *relaxed* in the
   sense that the stage resolves far below 0.9 V (0.35-0.80 V). This reading
   does not say the node may *fall by* 0.9 V.
2. **Droop reading** (what the formula consumes): the usable droop is the
   written level minus the lowest resolvable level; across the 10 corners
   and 4 references it is 0.13-0.92 V. At **9 of 10 corners it is below
   0.9 V for every swept reference** (best case per corner, usable droop as a
   fraction of 0.9 V, upper end of the grid bracket: 0.31 fs/27, 0.40 ss/27,
   0.59 tt/27 and fs/125, 0.61 ss/125, 0.71 ff/27, 0.80 tt/125 and sf/27,
   0.93 ff/125). **VIOLATED** at those. At sf/125 (the ratified worst-case
   retention corner) the bracket at the tightest reference (20 mV) is
   0.87-0.92 V (0.96-1.02 of 0.9 V): **indeterminate on this grid**; at
   50 mV it is 0.82-0.87 V and at the 100 mV placeholder separation level
   it is 0.77-0.82 V (violated). At the restricted cold bound (27 C) the
   usable droop is 0.13-0.72 V. A 20 mV reference is not credible without
   an offset result (the random offset of a minimum latch is not known
   here), so the 0.9 V figure is not supported by this stage as built.
   First-order (same `C_SN`, constant-current), the retention term scales
   with the usable droop, which would put the sf/125 term at roughly
   0.85-1.0 of the ratified value for references of 100 mV down to 20 mV.
   That ratio is a finding about the assumption, **not a proposed spec
   number**; no spec file, retention CSV or decision record was edited.
   Reconsidering `delta_V` requires a decision record.

Caveats that bound the finding: written levels are the Phase 2 values (with
the study's `C_SN` 0.605354 fF, which differs from the ratified ASSUMED
1.106463 fF and is not reconciled); all four rows at one level; ideal
drivers and ideal precharge switch; `C_RBL` is an ASSUMPTION; first-pass
latch sizes; 0.05 V level grid; global corners only (no mismatch/offset/yield,
no supply tolerance); 10 ns sense instant. Decision-time sensitivity to
enable time was not swept. A tighter or looser design could move the
numbers; the verdict is for this stage under these assumptions.

## Not shown

No offset or yield result; no Monte Carlo; no supply other than 1.8 V; no
temperature outside {27, 125} C; no extracted `C_RBL`; no layout of the
stage; no sense-time vs enable-time sweep; no power. Nothing here ratifies
the proposed range or any sense-amplifier specification.

## Issue #88: re-run with the extracted 4-row `C_RBL` (append-only, 2026-10-11)

> **Pre-#244 layout.** Everything in this section (0.859179 fF, `C_SN` 0.605354 fF) is history of the layout before PR #248. The same variants on the current layout are in "Issue #261" at the end of this file. The decks and results here are not regenerated or edited.

> **Device provenance (pre-#293 latch).** The decks behind this section predate the issue-#293 latch correction: `gen_sense_stage.py` had dropped the `nrd`/`nrs`/`sa`/`sb`/`sd` tokens from the latch devices, so these runs simulated a latch with no source-drain parasitic resistance. The correction and its effect on the 10 fF deck are in "Latch geometry correction re-run (issue #293, 2026-11-15)" at the end of this file. These variant decks are append-only history and were **not** regenerated, so every `t_dec`, floor and droop-verdict number in this section describes the pre-correction latch. Re-running the variants under the corrected device is tracked in #357 (open).

New evidence only. The sections above and their results files are
unchanged. The loaded-column half of the issue, and the full description of
the `C_RBL` value, are in
[`../loaded-column/extracted-crbl/README.md`](../loaded-column/extracted-crbl/README.md).

**`C_RBL` source.**

| Item | Value |
|---|---|
| File | [`layout/gain_cell_2t_array.parasitics.summary.json`](../../layout/gain_cell_2t_array.parasitics.summary.json) |
| Key | `comparison.c_rbl.extracted_4row_worst_total_ff` |
| Value | **0.859179 fF** (worst `rbl_<c>`: 0.581168 fF ground + 0.278011 fF coupling) |
| Extracted netlist | `layout/gain_cell_2t_array.extract.parasitics.spice`, sha256 `dd2cca26de34d6b7cd39a0d794db64993d6440c5ca7f248cf4d657b6f6b88d33` |
| Label | **EXTRACTED-4-ROW**. The 4-row column stays a STUDY-ASSUMPTION; `N_rows` is **not ratified**. |

**Deck changes.** The generator reads the value from the JSON key
(`gen_sense_stage.py --variant`). Without `--variant` the generator
output is byte-identical to the committed `sense_stage.spice` / `request.json`
(tested). Each variant is a new deck and a new request; `request.json` was
not edited. A variant changes only:

* `.param C_RBL`. It loads both `rbl` and the **matched dummy reference
  load** (`cref_*`), so the reference side drops to the same value. That
  keeps the "ideal matched dummy load" assumption.
* For the layout-card variant, the bitcell diffusion card.

**Interpretation.** The extracted value is wiring only, and it replaces
10 fF. The latch transistors are simulated explicitly, so their own input
load is present. Any further sense-input load that the 10 fF may have
included (isolation, muxing) is not, so 0.859 fF is the lightest-load bound.
2 fF is an ASSUMPTION mid-point.

The scope is unchanged: 27 C and 125 C only. **No -40 C sense-stage result is
claimed.** The -40 C sensitivity is in the loaded-column re-run.

| Run | Variant | `C_RBL` | Bitcell card | Fleet job | Deck sha256 |
|---|---|---|---|---|---|
| `20261009T131831Z` | (issue #60 baseline) | 10 fF ASSUMPTION | design | `klt-sim-8c62fc8d1019` | `4cd2834d...` |
| `20261011T015836Z` | `crbl_ext4row` | 0.859179 fF EXTRACTED-4-ROW | design | `klt-sim-6008da1d6b94` (c7i.4xlarge, 138 s) | `64232229...` |
| `20261011T020128Z` | `crbl_2f` | 2 fF ASSUMPTION | design | `klt-sim-d5296ed7f82b` (m6i.4xlarge, 135 s) | `098cd39b...` |
| `20261011T020422Z` | `crbl_ext4row_layoutcard` | 0.859179 fF EXTRACTED-4-ROW | layout (`ad=as=0.1974`, `pd=ps=1.78`) | `klt-sim-9ad077c252f4` (m6i.4xlarge, 147 s) | `5f0d3f66...` |

**Run details.**

* Every variant ran 10/10 corners `pass` on the batch fleet as a first
  submission, using `uvx --from "klayout-tools==0.6.0" klt sim --backend batch`.
  No local grid was run.
* Reports have the bucket name redacted. Each summary's `netlist_sha256`
  equals the committed variant deck (tested).
* **Negative control.** The `cell0_*` instances are in every deck: a '1' that
  was never written must read '0'. They resolve as '0' at every corner and
  every reference for all three variants.

### Old vs new (summary JSONs; ranges over the 10 corners)

| Quantity | 10 fF (issue #60) | **0.859 fF** | 2 fF | 0.859 fF + layout card |
|---|---|---|---|---|
| Stage-only `t_dec` at the 1 mV point | 0.27-0.51 ns | **0.11-0.23 ns** | 0.14-0.26 ns | 0.11-0.23 ns |
| Stage-only `|d|` at enable, nominal 1 mV | 1.10-1.31 mV | 1.27-1.95 mV | 1.22-1.76 mV | 1.27-1.95 mV |
| All stage-only points (+/-1..100 mV) resolve | yes | yes | yes | yes |
| `t_dec` at `SN` = 1.0 V, 100 mV reference | 0.059-0.090 ns | **0.034-0.053 ns** | 0.037-0.059 ns | 0.033-0.053 ns |
| Min resolvable `SN` at the 100 mV reference | 0.45-0.75 V | 0.40-0.70 V | 0.40-0.70 V | 0.40-0.70 V |
| Droop verdict vs `VDD`/2 at 100 mV reference | violated 10/10 | violated 10/10 | violated 10/10 | violated 10/10 |
| Best-reference droop verdict at sf/125 C | indeterminate (0.87-0.92 V) | **met** (>= 0.917 V, at 20 mV) | indeterminate | indeterminate (0.87-0.92 V, at 50 mV) |

**Decision time.**

* With the extracted load, `t_dec` falls by a factor of about 2.2-2.5 at every
  corner.
* The `|d|` seen at the enable instant drifts further from the nominal 1 mV.
  A lighter floating `rbl` moves more in the 2 ns before enable. Every
  stage-only point still resolves with the correct sign.
* A random-offset budget is still missing (see `sim/sense-mismatch/`, which
  used 10 fF; not re-run here). The 1 mV floor therefore still says nothing
  about mismatch.

**Verdicts.**

* **The droop reading of the `VDD`/2 finding moves at one corner, one
  reference.** At sf/125 C with the 20 mV reference, every swept stored-'1'
  level down to the sweep floor (0.30 V) now resolves. The usable droop is
  therefore >= 0.917 V. That is bounded by the sweep, not measured, and it is
  `met` against 0.9 V, where it was indeterminate before.
* Three things qualify that:
  * It holds only for the bounding 0.859 fF load on the design card. With 2 fF
    or with the layout card it stays indeterminate.
  * The 20 mV reference was already called not credible without an offset
    result.
  * At the 100 mV placeholder reference every corner is still violated.
* The earlier finding stands: `VDD`/2 is not supported by this stage as
  built. Nothing here changes `delta_V` or any spec value. That would need a
  decision record.
* The stored-level reading ("a stored '1' at 0.9 V resolves") remains met
  at every corner, reference and variant.

## Post-#244 layout re-run (issue #249, 2026-10-28)

PR #248 (issue #244) regenerated the layout under klt 0.8.0 (cell 1.84 -> 2.115 um tall, extracted `C_SN` 0.605354 -> 0.672741 fF). This section records the re-run of this bench on the regenerated decks as **new dated evidence**; the earlier results above are untouched history of the pre-#244 layout. Tool: `uvx --from klayout-tools==0.8.0 klt sim --backend batch --format json` (job `klt-sim-43d4e52bc5e0`, run `20261028T085441Z`, 10/10 corners pass); fleet worker ngspice-46, open_pdks stamp `c6d73a3` as reported in the klt report. Request files unchanged (same corners / seeds / thresholds); the decks were regenerated by `gen_sense_stage.py` first and match the committed ones.

Old = `results/sense_summary_20261016T072807Z.json` (the latest prior run, re-qualification under `f6eeac7`), new = `results/sense_summary_20261028T085441Z.json` (report `klt_report_20261028T085441Z.json`).

| Corner | T | stage floor (mV, -) old -> new | written 1 min (V) old -> new | usable dV_SN @20mV old -> new | best-ref verdict old -> new |
|---|---:|---|---|---|---|
| tt | 27 | 1.11 -> 1.11 | 1.028 -> 1.028 | 0.478-0.528 -> 0.478-0.528 | violated -> violated |
| tt | 125 | 1.16 -> 1.16 | 1.123 -> 1.123 | 0.673-0.723 -> 0.673-0.723 | violated -> violated |
| ss | 27 | 1.12 -> 1.12 | 0.961 -> 0.961 | 0.310-0.360 -> 0.310-0.360 | violated -> violated |
| ss | 125 | 1.14 -> 1.14 | 1.048 -> 1.048 | 0.498-0.548 -> 0.498-0.548 | violated -> violated |
| ff | 27 | 1.10 -> 1.10 | 1.088 -> 1.088 | 0.588-0.638 -> 0.588-0.638 | violated -> violated |
| ff | 125 | 1.31 -> 1.31 | 1.187 -> 1.187 | 0.787-0.837 -> 0.787-0.837 | violated -> violated |
| sf | 27 | 1.12 -> 1.12 | 1.123 -> 1.123 | 0.673-0.723 -> 0.673-0.723 | violated -> violated |
| sf | 125 | 1.17 -> 1.17 | 1.217 -> 1.217 | 0.867-0.917 -> 0.867-0.917 | indeterminate_on_this_grid -> indeterminate_on_this_grid |
| fs | 27 | 1.10 -> 1.10 | 0.932 -> 0.932 | 0.232-0.282 -> 0.232-0.282 | violated -> violated |
| fs | 125 | 1.21 -> 1.21 | 1.027 -> 1.027 | 0.477-0.527 -> 0.477-0.527 | violated -> violated |

**No verdict change, and no metric moved at the reported precision.** The only deck difference is the `C_SN` parameter (0.605354 -> 0.672741 fF): the stage sweeps the pre-read storage level directly, so (not separately isolated here) the stage floor, the written-'1' minimum, the usable-`delta_V` window and the best-swept-reference verdict (violated at every corner except sf/125 C, which stays `indeterminate_on_this_grid`) are unchanged. The `VDD`/2 FINDING above stands as written.

## Issue #261: #88 variants re-run on the post-#244 layout (append-only, 2026-10-29)

> **Device provenance (pre-#293 latch).** The three `*_p244` decks of this section (runs `20261029T194412Z`-`20261029T194414Z`) predate the issue-#293 latch correction (latch without `nrd`/`nrs`/`sa`/`sb`/`sd`, i.e. no source-drain parasitic resistance), and were **not** regenerated; every number below, including the `t_dec` tables and the sf/125 C best-reference droop verdict (where the latch is the sensing element), describes the pre-correction latch. See "Latch geometry correction re-run (issue #293, 2026-11-15)" at the end of this file. Re-running these variants under the corrected device was done in #357; see "Corrected-latch re-run of the #88/#261 variants (issue #357, 2026-11-18)" at the end of this file.
>
> **Corrected-device variant decks (since simulated in #357).** `gen_sense_stage.py` also registers `crbl_ext4row_p244_l293`, `crbl_2f_p244_l293` and `crbl_ext4row_layoutcard_p244_l293` (same post-#244 `C_RBL`/`C_SN`, latch emitted from `design/sense_latch.spice`); their decks and request files are in this directory. At the time of #88 no results existed for them; they were run in #357 (section at the end of this file).

New evidence only; the 2026-10-11 variants above stay as pre-#244 history. PR #248 regenerated the layout, so the extracted `C_RBL` moved and the extracted `C_SN` moved too (0.605354 -> 0.672741 fF).

**`C_RBL` source.** Same file and key as above (`layout/gain_cell_2t_array.parasitics.summary.json`, `comparison.c_rbl.extracted_4row_worst_total_ff`), now **0.955559 fF** (worst net `rbl_2`: 0.66272 fF ground; was 0.859179 fF with 0.581168 fF ground). Label unchanged: **EXTRACTED-4-ROW**, 4 rows is a STUDY-ASSUMPTION, `N_rows` is **not ratified**. No `spec/` change.

**Deck handling.** The three 2026-10-11 variant decks are frozen: `gen_sense_stage.py` keeps them in the variant registry as `legacy` entries with the pre-#244 `C_RBL` (so their summaries still reproduce byte for byte) but no longer regenerates them. New variants `crbl_ext4row_p244`, `crbl_2f_p244` and `crbl_ext4row_layoutcard_p244` are generated from the current JSON key and the current extracted `C_SN`; `python3 -I sim/sense-stage/gen_sense_stage.py --variant <id>`. Request files carry the same corners and thresholds as before.

| Run | Variant | `C_RBL` | Bitcell card | Fleet job | Deck sha256 |
|---|---|---|---|---|---|
| `20261029T194412Z` | `crbl_ext4row_p244` | 0.955559 fF EXTRACTED-4-ROW | design | `klt-sim-d8de3410f41e` (c7i.8xlarge) | `3cd4da62...` |
| `20261029T194413Z` | `crbl_2f_p244` | 2 fF ASSUMPTION | design | `klt-sim-9c4817dc05f6` (m6i.4xlarge) | `ff6bf583...` |
| `20261029T194414Z` | `crbl_ext4row_layoutcard_p244` | 0.955559 fF EXTRACTED-4-ROW | layout (`ad=as=0.1974`, `pd=ps=1.78`) | `klt-sim-b233e4ba63c2` (c7i.8xlarge) | `04a4bbc9...` |

**Run details.** Each variant ran 10/10 corners `pass` on the batch fleet (`uvx --from klayout-tools==0.8.0 klt sim --backend batch --format json`), ngspice 46, first submission, no local grid. Run ids are the ingest times of the reports. Each summary's `netlist_sha256` equals the committed variant deck (tested).

### Old vs new (summary JSONs; ranges over the 10 corners)

"Pre-#244" is the 2026-10-11 variant run; "post-#244" is the run above. The 10 fF baseline on the post-#244 layout is `20261028T085441Z` (issue #249).

| Quantity | 10 fF (`20261028T085441Z`) | 0.955559 fF (pre-#244: 0.859179) | 2 fF (pre-#244 in brackets) | 0.955559 fF + layout card |
|---|---|---|---|---|
| Stage-only `t_dec` at the 1 mV point | 0.27-0.51 ns | **0.11-0.23 ns** (0.11-0.23) | 0.14-0.26 ns (0.14-0.26) | 0.11-0.23 ns |
| Stage-only `|d|` at enable, nominal 1 mV | 1.10-1.31 mV | 1.26-1.93 mV (1.27-1.95) | 1.22-1.76 mV (1.22-1.76) | 1.26-1.93 mV |
| All stage-only points (+/-1..100 mV) resolve | yes | yes | yes | yes |
| `t_dec` at `SN` = 1.0 V, 100 mV reference | 0.058-0.089 ns | 0.034-0.053 ns (0.034-0.053) | 0.037-0.058 ns (0.037-0.059) | 0.033-0.053 ns |
| Min resolvable `SN` at the 100 mV reference | 0.45-0.75 V | 0.40-0.70 V (0.40-0.70) | 0.40-0.70 V (0.40-0.70) | 0.40-0.70 V |
| Droop verdict vs `VDD`/2 at 100 mV reference | violated 10/10 | violated 10/10 | violated 10/10 | violated 10/10 |
| Best-reference droop verdict at sf/125 C | indeterminate (0.87-0.92 V) | **met** (>= 0.917 V, at 20 mV) | indeterminate (0.87-0.92 V, at 50 mV) | indeterminate (0.87-0.92 V, at 50 mV) |

**Verdicts.**

* **No verdict changed.** The heavier extracted load (0.859 -> 0.956 fF) and the larger `C_SN` move the numbers by at most two units in the last reported digit (for example the nominal-1 mV `|d|` range 1.27-1.95 -> 1.26-1.93 mV). Decision times keep the 2.2-2.5x improvement over the 10 fF baseline.
* **sf/125 C droop verdict stays `met`, as the data shows.** At the 20 mV reference with `C_RBL` = 0.955559 fF on the design card, every swept stored-'1' level down to the 0.30 V sweep floor resolves, so the usable droop is >= 0.917 V against 0.9 V. That is a bound set by the sweep, not a measurement. The pre-#244 qualifiers carry over unchanged: it holds only for this bounding load on the design card (2 fF and the layout card stay indeterminate), the 20 mV reference was already called not credible without an offset result, and at the 100 mV placeholder reference every corner is still violated.
* The earlier finding stands: `VDD`/2 is not supported by this stage as built. The stored-level reading ("a stored '1' at 0.9 V resolves") remains met at every corner, reference and variant. Nothing here changes `delta_V` or any spec value.
* Not re-run, and still 10 fF based: `sim/sense-mismatch/`. The 1 mV floor says nothing about mismatch.

## Latch geometry correction re-run (issue #293, 2026-11-15)

Issue #293 fixed this deck's latch device: `gen_sense_stage.py` had retyped the latch/footer/header geometry (`dev_params()`), silently dropping the `nrd`/`nrs`/`sa`/`sb`/`sd` tokens that the schematic-derived [`design/sense_latch.spice`](../../design/sense_latch.spice) carries, so this bench simulated a latch with no source-drain parasitic resistance. The generator now emits the latch through `parse_cards()` from the design netlist (as the column-periphery benches already did); the regenerated deck's token-level delta is exactly the five added tokens per latch device (`nrd=0.29`/`0.145`/`0.0725`, `nrs=`, `sa=0 sb=0 sd=0` on `XMN1`/`XMN2`, `XMP1`/`XMP2`/`XMNF`, `XMPH` respectively = `0.29/W` per the bitcell convention). This section records the re-run as **new dated evidence**; earlier results are untouched history. Tool: `uvx --from klayout-tools==0.9.1 klt sim --backend batch --format json --wait-for-capacity 600` (job `klt-sim-e974c305611b`, run `20261115T115315Z`, 10/10 corners pass; runner klt 0.9.0, fleet worker ngspice-47).

**Engine and tool provenance differ between old and new run (not just the latch).** From `environment` in the committed reports (`engine_version` is the worker-side simulator major version; the top-level `engine_build` banner of the old report is the client-side ngspice-42 and is not the engine that ran it): old run `20261028T085441Z` = **ngspice-46** (worker banner built 2026-10-01), runner/client klt 0.8.0; new run `20261115T115315Z` = **ngspice-47** (worker banner built 2026-11-13), runner klt 0.9.0, client/submit klt 0.9.1. The open_pdks revision also differs: the worker-executed stamp (`environment.remote.worker_environment.pdk.stamp_text`, `stamp_scope: "executed"`) is `c6d73a35f524070e85faff4a6a9eef49553ebc2b` (`c6d73a3`) for the old run and `f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7` (`f6eeac7`) for the new one. `models_lib_sha256` (`48de7c67...133c84`) is identical in both but is a client-side hash of the top-level `sky130.lib.spice` only (`models_lib.path: null`, scope `external`; `models_staged: false`), so it does not show that the PDK is the same (see the re-qualification note under `f6eeac7` above). Whether the `c6d73a3` -> `f6eeac7` step matters for this bench is argued from other evidence: `sense_points_20261009T131831Z.csv` and `sense_points_20261016T072807Z.csv` are byte-identical (980 rows) across exactly that PDK pair; neither of those reports carries a `worker_environment` capture (klt 0.6.0), so their revisions are the client-side `provenance.pdk` values. The old-vs-new comparison below therefore changes the latch device, the ngspice version, the open_pdks revision and klt together.

Old = `results/sense_summary_20261028T085441Z.json`, new = `results/sense_summary_20261115T115315Z.json` (report `klt_report_20261115T115315Z.json`).

| Corner | T | stage floor (mV, -) | `t_dec` @ 1 mV (ns) | min resolvable `SN` @100 mV (V) | usable `dV_SN` @ best ref (V) | best-ref verdict |
|---|---:|---|---|---|---|---|
| tt | 27 | 1.11 -> 1.11 | 0.383 -> 0.404 | 0.65 -> 0.65 | 0.478-0.528 -> 0.478-0.528 | violated -> violated |
| tt | 125 | 1.16 -> 1.16 | 0.333 -> 0.353 | 0.55 -> 0.55 | 0.673-0.723 -> 0.673-0.723 | violated -> violated |
| ss | 27 | 1.12 -> 1.12 | 0.510 -> 0.536 | 0.7 -> 0.7 | 0.310-0.360 -> 0.310-0.360 | violated -> violated |
| ss | 125 | 1.14 -> 1.14 | 0.407 -> 0.427 | 0.65 -> 0.65 | 0.498-0.548 -> 0.498-0.548 | violated -> violated |
| ff | 27 | 1.10 -> 1.10 | 0.300 -> 0.319 | 0.6 -> 0.6 | 0.588-0.638 -> 0.588-0.638 | violated -> violated |
| ff | 125 | 1.31 -> 1.31 | 0.274 -> 0.293 | 0.5 -> 0.5 | 0.787-0.837 -> 0.787-0.837 | violated -> violated |
| sf | 27 | 1.12 -> 1.12 | 0.387 -> 0.408 | 0.55 -> 0.55 | 0.673-0.723 -> 0.673-0.723 | violated -> violated |
| sf | 125 | 1.17 -> 1.17 | 0.330 -> 0.350 | 0.45 -> 0.45 | 0.867-0.917 -> 0.867-0.917 | indeterminate_on_this_grid -> indeterminate_on_this_grid |
| fs | 27 | 1.10 -> 1.10 | 0.383 -> 0.403 | 0.75 -> 0.75 | 0.232-0.282 -> 0.232-0.282 | violated -> violated |
| fs | 125 | 1.21 -> 1.21 | 0.334 -> 0.354 | 0.65 -> 0.65 | 0.477-0.527 -> 0.477-0.527 | violated -> violated |

**Scope of the "verdicts unchanged" conclusion.** It was measured on the **10 fF** baseline deck only. For the #88 and #261 variant decks (`C_RBL` 0.859/0.956 fF and 2 fF, layout card) it is an *expectation*, not a measurement: at the time of writing those were not re-simulated on the corrected device; #357 has since done so (see the last section), and the sf/125 C best-reference droop verdict (`met` for the 0.955559 fF design-card variant) holds under the corrected latch.

**The simulated device really changed** -- every one of the 980 measurement rows moved (`t_dec` shifts +0.019-0.025 ns at every corner; `dend` deltas up to 19 mV near the resolution limit). That `t_dec` shift is the *combined* latch + ngspice-46 -> 47 + open_pdks `c6d73a3` -> `f6eeac7` (+ klt) delta: the latch effect is **not isolated** from the engine step or the PDK-revision step, and no run of the pre-#293 deck on ngspice-47 exists to separate them, so the shift must not be quoted as a latch-only number. The direction is consistent with slower regeneration from source-drain resistance in the latch, but that attribution is not established here. Even so, **every summary-level verdict is unchanged at the reported precision** (across the latch change, the ngspice 46 -> 47 step and the open_pdks revision step taken together, which these runs do not separate): the stage floor, the min-resolvable level at every reference, the usable-`dV` brackets and the best-swept-reference verdicts in the per-corner table above are re-derived from run `20261115T115315Z` and all hold as printed. Stored '0' resolves correctly at every corner and reference (negative control: 0 failures), every decided point reaches >= 1.55 V full swing with correct sign, and max `t_dec` is 0.54 ns against the 5 ns window, so **pass condition 2c of `spec/macro-pass-conditions-PROPOSED.md` (Status column: ASSUMPTION) still passes under the corrected device**. The `VDD`/2 FINDING above stands as written. No spec threshold was touched.

## Corrected-latch re-run of the #88/#261 variants (issue #357, 2026-11-18)

Follow-up to #152. The three `*_p244_l293` variants (same post-#244 `C_RBL` 0.955559 fF / 2 fF and cards as the `*_p244` runs, latch emitted from `design/sense_latch.spice` per #293) had committed decks and requests but no results. They were run as **new dated evidence**; the legacy `*_p244` results above are untouched. Tool: `uvx --from klayout-tools==0.9.1 klt sim --batch-set ... --wait-for-capacity 600 --format json` (one invocation, three jobs on the batch fleet, no local grid; runner klt 0.9.0, fleet worker ngspice-47). Every variant: 10/10 corners `pass`, first submission. Each summary's `netlist_sha256` equals the committed `_l293` deck (checked).

**Simulator caveat (old vs new is not engine-matched).** The legacy `*_p244` runs report `environment.engine_version` = `46` (runs `20261029T194412Z`-`20261029T194414Z`); the `*_p244_l293` runs here report `47`. `models_lib_sha256` is identical in all six, so the PDK library is the same, but the simulator moved 46 -> 47 between the old and new columns, so the `t_dec` deltas below are **not isolated to the latch correction**. At the small end (e.g. `crbl_ext4row` tt/125 C, +0.0015 ns on 0.1544 ns, about 1 %) the delta is of the same order as a simulator minor-version step. Mitigation: #293's own +0.019-0.025 ns reference shift was measured across the same 46 -> 47 step, so the percentage comparison against it is like-for-like even though the absolute attribution is not.

| Run | Variant | Fleet job (`environment.remote.job_id`) | Instance | Old run (`*_p244`) |
|---|---|---|---|---|
| `20261118T194931Z` | `crbl_ext4row_p244_l293` | `klt-sim-ebe9d5695365` | c7i.8xlarge | `20261029T194412Z` |
| `20261118T194857Z` | `crbl_2f_p244_l293` | `klt-sim-2a399df2cd34` | m7i.4xlarge | `20261029T194413Z` |
| `20261118T194901Z` | `crbl_ext4row_layoutcard_p244_l293` | `klt-sim-85557e880cf9` | m7i.4xlarge | `20261029T194414Z` |

Run ids are the report ingest (`client_collected_at`) times. Reports: `results/klt_report_<RUN>.json`; reduced by `analyze_sense_stage.py` to `results/sense_summary_<RUN>.json` / `sense_points_<RUN>.csv`.

### Old vs new, per corner (`*_p244` -> `*_p244_l293`)

Quantities: stage-only `t_dec` at the 1 mV point (ns, minus polarity); min resolvable stored-'1' `SN` at the 100 mV reference (V); best-swept-reference droop verdict vs `VDD`/2 (reference in parentheses); 100 mV-reference verdict. The stage floor (minimum resolved |din|) is identical to the printed precision at every corner and is omitted.

**`crbl_ext4row` (0.955559 fF, design card)**

| Corner | T | `t_dec` @ 1 mV (ns) | min `SN` @100 mV (V) | best-ref verdict | 100 mV verdict |
|---|---:|---|---|---|---|
| tt | 27 | 0.166 -> 0.182 | 0.6 -> 0.6 | violated (20 mV) -> violated | violated -> violated |
| tt | 125 | 0.154 -> 0.156 | 0.5 -> 0.5 | violated (20 mV) -> violated | violated -> violated |
| ss | 27 | 0.231 -> 0.242 | 0.7 -> 0.7 | violated (20 mV) -> violated | violated -> violated |
| ss | 125 | 0.181 -> 0.192 | 0.6 -> 0.6 | violated (20 mV) -> violated | violated -> violated |
| ff | 27 | 0.140 -> 0.144 | 0.55 -> 0.55 | violated (50 mV) -> violated | violated -> violated |
| ff | 125 | 0.111 -> 0.122 | 0.45 -> 0.45 | violated (20 mV) -> violated | violated -> violated |
| sf | 27 | 0.170 -> 0.185 | 0.5 -> 0.5 | violated (50 mV) -> violated | violated -> violated |
| sf | 125 | 0.147 -> 0.155 | 0.4 -> 0.4 | **met** (20 mV) -> **met** | violated -> violated |
| fs | 27 | 0.164 -> 0.176 | 0.7 -> 0.7 | violated (20 mV) -> violated | violated -> violated |
| fs | 125 | 0.148 -> 0.155 | 0.6 -> 0.6 | violated (20 mV) -> violated | violated -> violated |

**`crbl_2f` (2 fF ASSUMPTION, design card)**

| Corner | T | `t_dec` @ 1 mV (ns) | min `SN` @100 mV (V) | best-ref verdict | 100 mV verdict |
|---|---:|---|---|---|---|
| tt | 27 | 0.196 -> 0.204 | 0.6 -> 0.6 | violated -> violated | violated -> violated |
| tt | 125 | 0.166 -> 0.176 | 0.5 -> 0.5 | violated -> violated | violated -> violated |
| ss | 27 | 0.257 -> 0.273 | 0.7 -> 0.7 | violated -> violated | violated -> violated |
| ss | 125 | 0.206 -> 0.214 | 0.6 -> 0.6 | violated -> violated | violated -> violated |
| ff | 27 | 0.151 -> 0.160 | 0.55 -> 0.55 | violated -> violated | violated -> violated |
| ff | 125 | 0.136 -> 0.146 | 0.45 -> 0.45 | violated -> violated | violated -> violated |
| sf | 27 | 0.198 -> 0.207 | 0.5 -> 0.5 | violated -> violated | violated -> violated |
| sf | 125 | 0.165 -> 0.175 | 0.4 -> 0.4 | indeterminate (50 mV) -> indeterminate | violated -> violated |
| fs | 27 | 0.193 -> 0.202 | 0.7 -> 0.7 | violated -> violated | violated -> violated |
| fs | 125 | 0.166 -> 0.177 | 0.65 -> 0.65 | violated -> violated | violated -> violated |

**`crbl_ext4row_layoutcard` (0.955559 fF, layout bitcell card)**

| Corner | T | `t_dec` @ 1 mV (ns) | min `SN` @100 mV (V) | best-ref verdict | 100 mV verdict |
|---|---:|---|---|---|---|
| tt | 27 | 0.166 -> 0.181 | 0.6 -> 0.6 | violated -> violated | violated -> violated |
| tt | 125 | 0.154 -> 0.156 | 0.5 -> 0.5 | violated -> violated | violated -> violated |
| ss | 27 | 0.231 -> 0.242 | 0.7 -> 0.7 | violated -> violated | violated -> violated |
| ss | 125 | 0.181 -> 0.192 | 0.6 -> 0.6 | violated -> violated | violated -> violated |
| ff | 27 | 0.140 -> 0.144 | 0.55 -> 0.55 | violated -> violated | violated -> violated |
| ff | 125 | 0.111 -> 0.122 | 0.45 -> 0.45 | violated -> violated | violated -> violated |
| sf | 27 | 0.170 -> 0.185 | 0.5 -> 0.5 | violated -> violated | violated -> violated |
| sf | 125 | 0.147 -> 0.155 | 0.4 -> 0.4 | indeterminate (50 mV) -> indeterminate | violated -> violated |
| fs | 27 | 0.164 -> 0.176 | 0.7 -> 0.7 | violated -> violated | violated -> violated |
| fs | 125 | 0.148 -> 0.155 | 0.6 -> 0.6 | violated -> violated | violated -> violated |

### Does the #293 `t_dec` shift hold for the extracted-`C_RBL` variants?

**Partly: same sign, smaller magnitude, and no verdict change.** #293's own re-run of the 10 fF default deck moved `t_dec` by +0.019-0.025 ns. For the variants the shift of the 1 mV `t_dec` is positive at every corner but smaller: +0.0015-0.0155 ns (`crbl_ext4row`), +0.008-0.016 ns (`crbl_2f`), +0.0015-0.0153 ns (`crbl_ext4row_layoutcard`), i.e. roughly 8-80 % of the 10 fF-deck shift (0.0015/0.019 to 0.0155/0.019), with the smallest shifts at 125 C for the two extracted-`C_RBL` variants (`crbl_ext4row`, `crbl_ext4row_layoutcard`: +0.0015 ns at tt/125 C) but not for `crbl_2f`, whose smallest shift is +0.0082 ns at ff/27 C and whose 125 C shift is larger than its 27 C shift at 4 of 5 corners (tt, ff, sf, fs). The reduction is consistent with the lighter bitline load making the latch's own regeneration a smaller part of `t_dec`, but this section does not isolate that cause; it is an observation of the numbers above, not a mechanism claim.

**Verdicts.** No summary-level verdict changed in any variant at any of the 10 corners: stage floors (identical to the printed precision), min-resolvable `SN` at 100 mV, the 100 mV droop verdict (violated 10/10) and the best-swept-reference verdicts are all as before. In particular the sf/125 C best-reference droop verdict stays **`met`** for `crbl_ext4row` (20 mV reference, as a sweep-floor-bounded result, not a measurement; same qualifiers as in the #261 section: holds only for this bounding load on the design card, the 20 mV reference was already called not credible without an offset result), and stays `indeterminate_on_this_grid` for `crbl_2f` and the layout-card variant. The `VDD`/2 FINDING stands as written. No spec threshold was touched; the macro pass-condition status is not changed by this run.

**Provenance of the #88/#261 numbers.** Where this section supersedes them they are pre-#293-latch numbers and should be read that way: the `*_p244` tables above remain as recorded history on the uncorrected latch, and the corrected-latch values are the ones in this section. Items not re-run remain on their original basis (the 2026-10-11 pre-#244 variants are frozen legacy; `sim/sense-mismatch/` is still 10 fF based).
