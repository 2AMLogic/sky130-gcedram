# Sense-stage Monte Carlo mismatch study (issue #81)

Epic #24 items 2 and 6. This is the follow-up to
[`sim/sense-stage/`](../sense-stage/README.md) (issue #60), whose README
lists the mismatch/offset budget as "NOT AVAILABLE". **Everything here sits
under the PROPOSED, UNRATIFIED operating range** of
[`spec/operating-range-decision-PROPOSED.md`](../../spec/operating-range-decision-PROPOSED.md)
(27 C and 125 C, `VDD` = 1.8 V). No -40 C point, no other supply. No spec
file, retention CSV or decision record was edited. `offset_yield_validated`
stays **false**.

## Scope: what is and is not established

**Established** (with the evidence below):

* The input-referred offset distribution (sigma, mean, 95 % CIs) of **this
  latch** (the sense-stage latch, first-pass sizes) from the sky130 PDK's own
  Vth-mismatch model, at **four corners only**: tt/27 C, fs/27 C, ss/125 C,
  sf/125 C, `VDD` = 1.8 V.
* At the least-margin corner (fs/27 C), the spread of the differential that
  the read device and column deliver to the latch, and the end-to-end decision
  probability per stored level with mismatch on every device.

**Not established**:

* **No array-level yield.** Every probability below is per decision for one
  latch or one column instance. Nothing here is a macro, column or bank
  yield, and the error-rate figures are not a bit-error rate of the macro.
* No error rate below about 1 % is **observed**. The 1e-3 and 1e-6 figures
  are extrapolations of a fitted normal model (labelled as such).
* No corner other than the four above (ff not run), no supply tolerance, no
  temperature between 27 C and 125 C, no layout, no extracted `C_RBL`.
* No offset-cancellation, trimming or sizing study. The latch sizes are the
  first-pass sizes of #60; a different latch has a different sigma.
* The mismatch model is the PDK's (Vth only, see below). No silicon data; no
  current-factor (beta) mismatch, because the PDK model does not include it.

## Mismatch model availability (pinned PDK)

Checked against the pinned `sky130A` (`open_pdks`
`c6d73a35f524070e85faff4a6a9eef49553ebc2b`, [`docs/pdk-pin.md`](../../docs/pdk-pin.md)),
`libs.tech/combined/sky130.lib.spice` (sha256 `48de7c67...133c84`, the same
hash klt recorded in both reports):

| What | Where (line numbers in the pinned file) | Finding |
|---|---|---|
| plain corners `tt` `ss` `ff` `sf` `fs` | `.lib tt` 82, `.param MC_MM_SWITCH=0` 83 (same at 110, 137, 164, 191) | mismatch **off**: this is what `sim/sense-stage/` used |
| mismatch corners | header comment "Corners with mismatch analysis" 48-73 lists `tt_mm`, `ss_mm`, `sf_mm`, `fs_mm` (not `ff_mm`) | header list is incomplete |
| `_mm` sections | `.lib tt_mm` 730, `sf_mm` 757, `ff_mm` 784, `ss_mm` 811, `fs_mm` 838; each sets `.param MC_MM_SWITCH=1` on the next line (731, 758, 785, 812, 839) | **available** for all five corners, `ff_mm` included |
| `sky130_fd_pr__nfet_01v8` | `continuous/models_fet.spice` 10041 (`swx_vth = ... + sw_mm_vth0_..._nfet_01v8*mismatch_factor*MC_MM_SWITCH*AGAUSS(0,1.0,1)/sqrt(l*w*mult) ...`) and 10047 (`delvto = {swx_vth*(geometry factors)}`) | per-instance Vth draw, active under `MC_MM_SWITCH=1` |
| `sky130_fd_pr__pfet_01v8` | `continuous/models_fet.spice` 31462 (`delvto = {... + sw_mm_vth0_..._pfet_01v8*mismatch_factor*MC_MM_SWITCH*AGAUSS(0,1.0,1)/sqrt(l*w*mult)}`) | per-instance Vth draw, active |
| coefficients | `continuous/models_global.spice` 63 (`sw_mm_vth0_sky130_fd_pr__nfet_01v8 = 3.356e-03`), 68 (`..._pfet_01v8 = 5.856e-03`) | Vth only; the `deltox` / `mulu0` mismatch lines next to them are commented out |

(`models_fet.spice` sha256 `18be82d0...894f18`, `models_global.spice`
sha256 `ac9df6f4...d9e171f` at the pin.)

Reading the formula (a derivation from the model text, not a simulation):
sigma(Vth) per device is about **20 mV** for the latch NFET (1.0/0.15 um;
3.356 mV / sqrt(0.15) times the NFET geometry factors 1.42 x 1.21 x 1.37),
about **10.7 mV** for the latch PFET (2.0/0.15 um; the PFET geometry factors
do not multiply the mismatch term), and about **55 mV** for the minimum
0.42/0.15 um read device.

**`klt sim` can select these sections and seed the samples.** A bare
`corners.process` name such as `fs_mm` emits `.lib <lib> fs_mm`, and
`monte_carlo: {n, seed, vary: "mismatch"}` writes a per-sample
`.options seed=` card (klt `docs/cli/sim.md`, "Corner axes" and "Monte Carlo
sampling"). Both reports record `environment.monte_carlo.family_mismatch`
with `mosfet: active: true`. The analysis checks rather than assumes it: 40
distinct seeds per corner, and replicas at the same differential in one
sample disagree 379-405 times per corner (they would never disagree if the
draws were not per instance).

**ASSUMPTION / limitation: which devices carry mismatch.** The curator asked
for latch plus read device, with footer/header, write device and precharge
nominal. The PDK switch is **global per `.lib` section**, and
`mismatch_factor`/`MC_MM_SWITCH` are not subcircuit parameters, so mismatch
cannot be turned off per instance without editing the PDK model cards (not
done). In consequence:

* stage-only deck: the four latch devices **and** the footer and header carry
  mismatch. Footer and header are shared by both latch halves (common mode),
  so their contribution to the differential offset is second order; it is
  included in sigma, not removed.
* cell deck: every FET carries mismatch (latch, footer, header, all four
  rows' write and read devices). The precharge and reference switches are
  ideal `sw` elements and carry none.

## What was built

| File | Role |
|---|---|
| [`gen_sense_mismatch.py`](gen_sense_mismatch.py) | generates the four files below; imports the latch devices, sizes, timing and bias from `sim/sense-stage/gen_sense_stage.py` so the two cannot drift |
| [`sense_mismatch.spice`](sense_mismatch.spice), [`request.json`](request.json) | stage-only deck: 25 differentials (0, +/-2, 5, 10, 15, 20, 30, 40, 50, 60, 80, 100, 150 mV) x 6 replica latches = 150 independent latches per sample; `tt_mm`/27, `fs_mm`/27, `ss_mm`/125, `sf_mm`/125 (the cross product minus `exclude`); `monte_carlo` n = 40, seed 2026100981, `vary: mismatch`; `backend: batch` |
| [`sense_mismatch_cell.spice`](sense_mismatch_cell.spice), [`request_cell.json`](request_cell.json) | end-to-end deck at `fs_mm`/27 only: stored '1' at 0.60 .. 1.00 V (0.05 V steps) and stored '0' at 0.0 V, references 50 and 100 mV below precharge, 4 replicas each (80 instances, 4-row column each); same `monte_carlo` seed, n = 40 |
| [`analyze_sense_mismatch.py`](analyze_sense_mismatch.py) | reduces a committed report to a per-trial CSV and a per-corner summary (writes new files only) |
| [`test_sense_mismatch.py`](test_sense_mismatch.py) | stdlib checks: generated files not stale, scope inside the PROPOSED range, `monte_carlo` recorded, baseline sense-stage request untouched, fit recovers a known distribution, summaries reproduce from the committed reports, failed samples kept; wired into CI |
| `results/` | append-only evidence (below) |

Same stage as #60 (ASSUMPTIONS: `C_RBL` 10 fF, precharge 0.9 V, ideal
switches and drivers, ideal matched dummy load, latch enable 10 ns after the
select edge, decision window 5 ns, decided at `|d|` >= 0.9 V). The stage-only
common mode is the #60 one (reference 0.8 V, `rbl` = reference + d). The
transient stops 10 ns after enable instead of 20 ns (the window is 5 ns).

## How it was run (host rules)

* Both grids went to the **batch fleet** as `klt sim` requests with
  `monte_carlo`; nothing was looped locally. Client: throwaway
  `uvx --from klayout-tools==0.6.0 klt` (no host tool changed).
  * stage: fleet job **`klt-sim-17a21079e70b`** (c7i.8xlarge, spot, state
    `done`, 767 s), 160/160 samples pass.
  * cell: fleet job **`klt-sim-56a2e9d55c36`** (c7i.8xlarge, spot, state
    `done`, 207 s), 40/40 samples pass.
* One **local** single-run debug probe (`tt_mm`/27 C, no `monte_carlo`,
  `--backend local`, one ngspice run, 12 s) was run first to confirm that the
  `_mm` section yields per-instance spread. It is not recorded as evidence.
* No sample failed or produced a missing value (counts are in the summaries:
  `n_failed_samples`, `missing_values`, `n_no_definite_polarity`, all 0).
  The CSVs hold one row per sample x instance either way.

## Evidence (append-only)

Files in [`results/`](results/) are protected by `sim/check_append_only.py`.
Rerun with a **new** run id; never edit these.

| File | Content |
|---|---|
| `klt_report_20261009T141819Z.json.gz` | raw klt report, stage-only (gzip; 29 MB uncompressed) |
| `mismatch_points_20261009T141819Z.csv` | 24 000 rows: 4 corners x 40 samples x 150 latches |
| `mismatch_summary_20261009T141819Z.json` | per corner: sample counts, per-differential proportions with Wilson 95 % CIs, probit fits with profile-likelihood CIs, goodness of fit, extrapolated differentials, controls |
| `klt_report_cell_20261009T141826Z.json.gz` | raw klt report, end-to-end at fs/27 C (gzip) |
| `mismatch_cell_points_20261009T141826Z.csv` | 3 200 rows: 40 samples x 80 instances |
| `mismatch_cell_summary_20261009T141826Z.json` | per (reference, level): proportions with CIs, `din` statistics; per reference: lowest zero-error level, droop bracket |

The `.gz` files are `gzip -9 -n` of the klt `--format json` output with the
job bucket name replaced by `<redacted-bucket>` (as in `sim/sense-stage/`);
everything else is unmodified. The size problem is filed as klayout-tools
friction [#2975](https://github.com/2AMLogic/klayout-tools/issues/2975).
Netlist sha256 (as hashed by klt): stage
`22693170c7928b92d2cfc19016da8fceb201aa2785fda8db6a1b23fcb4615e53`, cell
`411967c4b95c5e2c2c3df1e20fdb4c7a1d47dde243de913c16028d015517ea80`; ngspice-46.

Reproduce: `python3 -I sim/sense-mismatch/gen_sense_mismatch.py`, then
`uvx --from klayout-tools==0.6.0 klt sim --format json sim/sense-mismatch/request.json > sim/sense-mismatch/results/klt_report_<NEW_RUN_ID>.json`
(and `request_cell.json` to `klt_report_cell_<NEW_RUN_ID>.json`) with
`KLT_SIM_BACKEND=batch`, optionally `gzip -9 -n`, then
`analyze_sense_mismatch.py` on each report.

## Method

Each latch instance has its own random offset. At a differential `d` the
latch decides '0' (`d` -> +1.8 V) or '1'. Over all 240 latches per
differential per corner (40 samples x 6 replicas), the model
`P(decide '0' | d) = Phi((d - mu) / sigma)` is fitted by maximum likelihood
(probit, 6 000 decisions per corner). `sigma` is the input-referred offset
standard deviation, `mu` the systematic offset. The 95 % intervals are
**profile-likelihood** intervals (chi-square, 1 dof). The textbook
chi-square interval on a sample standard deviation does not apply, because
no latch's offset is observed directly, only its decisions. A second fit
uses the measured differential at the enable instant (`din`) instead of the
nominal `d`; with mismatch, `din` differs from `d` by a 0.7-2.7 mV (1 sigma,
by corner and `d`) pre-enable drift, which the nominal fit counts as part of the offset.

## Results: latch offset (stage only)

| Corner | sigma (mV), nominal `d` [95 % CI] | mu (mV) [95 % CI] | sigma (mV), `din` [95 % CI] | Pearson chi2 / dof | smallest \|d\| with 0 errors at it and above, both polarities (of 240 each) | d at 1e-3, ASSUMPTION (mV, point / upper) | d at 1e-6, ASSUMPTION (mV, point / upper) |
|---|---|---|---|---|---|---|---|
| tt/27 C | **17.7** [16.7, 18.7] | -0.15 [-1.02, 0.72] | 18.5 [17.5, 19.6] | 23.4 / 21 | 60 mV | 54.7 / 58.9 | 84.1 / 90.0 |
| fs/27 C | **16.3** [15.4, 17.3] | -0.34 [-1.16, 0.48] | 16.8 [15.9, 17.9] | 18.4 / 21 | 50 mV | 50.8 / 54.7 | 77.9 / 83.5 |
| ss/125 C | **17.6** [16.6, 18.7] | -0.04 [-0.91, 0.82] | 18.4 [17.3, 19.5] | 14.5 / 21 | 50 mV | 54.5 / 58.7 | 83.8 / 89.8 |
| sf/125 C | **19.2** [18.1, 20.3] | -0.53 [-1.45, 0.39] | 19.6 [18.5, 20.8] | 23.7 / 21 | 60 mV | 59.7 / 64.2 | 91.6 / 98.0 |

* The normal model fits at every corner (Pearson chi-square close to its
  degrees of freedom). The systematic offset is zero within its CI
  everywhere, as expected for a symmetric stage.
* Every trial reached a definite polarity, and every correct decision was
  within the 5 ns window, so P(correct) and P(resolves in window) coincide
  (per-differential values and Wilson intervals are in the summary).
* **Resolution limit of the data.** 240 trials per differential with zero
  errors bound the error rate at that differential to <= 1.24 % (one-sided
  95 %). That is the smallest error rate these runs observe. The 1e-3 and
  1e-6 rows are **ASSUMPTION targets** (no ratified error-rate target exists)
  evaluated by **Gaussian extrapolation** of the fit, 3.09 and 4.75 sigma.
  "upper" uses the upper CI of sigma and the larger \|mu\| bound. The 1e-6
  figure is about 2.5 sigma beyond anything observed; it is not a measurement.

Read against #60: the stage-only sweep there resolved every point down to
1 mV because global corners have no mismatch. With mismatch, a 1 mV input is
a coin flip (P(correct) 0.45-0.61 at +/-2 mV). The 100 mV reference spacing
used as a placeholder in #60 is about 5-6 sigma of this latch's offset; the
20 mV reference that gave the best usable droop there is about 1.0-1.2
sigma, which **is not credible** for this latch.

## Results: read device and column (fs/27 C, end to end)

Two quantities, kept separate. The read-device (cell/column) spread is
**not** folded into the latch sigma above.

**Read-device-induced spread of the delivered differential.** Standard
deviation of `din` (differential at the enable instant) over 160 trials per
level. For context: with a stored '0' (read device off) it is 1.0-1.3 mV, and
the stage-only `din` spread at fs/27 C is about 1.5 mV, so almost all of the
spread below comes from the cell and column devices (dominated by the read
device, sigma(Vth) about 55 mV by the formula above). The distribution is
strongly skewed near threshold; mean and standard deviation are descriptive
only (min/max are in the summary).

| stored '1' (V) | 0.80 | 0.85 | 0.90 | 0.95 | 1.00 |
|---|---:|---:|---:|---:|---:|
| `din` std (mV), ref 50 mV | 251 | 177 | 121 | 54 | 47 |
| `din` std (mV), ref 100 mV | 217 | 212 | 126 | 76 | 51 |

For comparison, the latch offset sigma at this corner is 16.3 mV. Near the
resolvable limit the cell-side spread is an order of magnitude larger than
the latch offset.

**End-to-end decision (latch + cell + column, all with mismatch).** Trials
that resolved correctly within the window, of 160 (Wilson 95 % CI in the
summary):

| stored '1' (V) | 0.60 | 0.65 | 0.70 | 0.75 | 0.80 | 0.85 | 0.90 | 0.95 | 1.00 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ref 50 mV | 14 | 45 | 86 | 130 | 154 | **160** | 160 | 160 | 160 |
| ref 100 mV | 1 | 16 | 48 | 105 | 147 | 156 | 159 | **160** | 160 |

Stored '0' at 0.0 V resolved 160/160 at both references.

| Reference | lowest level with 0 errors at it and above | same, global corner without mismatch (#60) | Phase 2 written '1' min (V) | usable droop at this resolution (V) [pessimistic, optimistic] | stored '1' at 0.9 V |
|---|---|---|---|---|---|
| 50 mV | 0.85 V | 0.70 V | 0.932 | [0.08, 0.13] | 160/160 |
| 100 mV | 0.95 V | 0.75 V | 0.932 | [-0.02, 0.03] | 159/160 |

"0 errors" here means <= 1.85 % per decision (one-sided 95 %, 160 trials);
a tighter error rate would push these levels higher.

## FINDING (for the delta_V assumption; no spec change)

At the least-margin corner, fs/27 C, mismatch raises the lowest stored '1'
level that resolves without error in 160 trials from 0.70 V to 0.85 V
(50 mV reference) and from 0.75 V to 0.95 V (100 mV reference). Against the
Phase 2 written level (0.932 V min), the usable droop that leaves is at
most 0.08-0.13 V at the 50 mV reference. At the 100 mV placeholder reference
it is about zero: a stored '1' at exactly `VDD`/2 = 0.9 V already failed once
in 160. Without mismatch, #60 measured 0.18-0.28 V at this corner. The
#60 finding (the `VDD`/2 = 0.9 V droop assumption is not supported by this
stage) is therefore **strengthened** at this corner. The cause is the
spread of the read path (read device), not the latch offset.

This is a finding about an assumption, **not a proposed spec number**.
Caveats that bound it: 160 trials (about 2 % error-rate resolution, not a
memory-grade tail); written level taken from the Phase 2 nominal run (no
mismatch on the write path); all four rows at one level; ideal drivers and
precharge; `C_RBL` ASSUMPTION; `C_SN` 0.605354 fF (as #60, not reconciled
with the ratified ASSUMED value); first-pass latch; 0.05 V level grid; one
corner (the cell variant was run only at fs/27 C). Reconsidering `delta_V`
or the operating range needs a decision record.

## klayout-tools friction filed

* [#2975](https://github.com/2AMLogic/klayout-tools/issues/2975): Monte
  Carlo reports grow to tens of MB of JSON, with no compact or columnar
  per-sample output (this study gzips its reports).
* [#2976](https://github.com/2AMLogic/klayout-tools/issues/2976): no Monte
  Carlo reduction for binary outcomes against a swept stimulus
  (comparator/latch offset by probit with CIs); this study implements it in
  `analyze_sense_mismatch.py`.

Selecting `_mm` sections and seeding samples worked as documented. The
fleet accepted client 0.6.0 (no version skew this time).
