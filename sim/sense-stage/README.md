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
| mismatch / offset budget | NOT AVAILABLE (global corners, no Monte Carlo) | -- |

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

Reproduce: `python3 -I sim/sense-stage/gen_sense_stage.py`, then
`uvx --from klayout-tools==0.6.0 klt sim --format json sim/sense-stage/request.json > sim/sense-stage/results/klt_report_<NEW_RUN_ID>.json`
(`KLT_SIM_BACKEND=batch`; 0.6.0 is the newest client the fleet runner
accepted on 2026-10-09), then `analyze_sense_stage.py` on that report.

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
