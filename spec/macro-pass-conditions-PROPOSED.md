# PROPOSED record: macro-level pass conditions for epic #24 items 2-6 (issue #82)

> **STATUS: PROPOSED. NOT RATIFIED.** This document ratifies nothing and
> changes no ratified value. It writes down, in gradable form, what "done"
> would mean for each of epic #24 items 2-6, so results can be graded rather
> than merely reported. Two-key ratification (`ratification/ee-key/`,
> `ratification/market-key/`) is outside the authority of issue #82 and of any
> agent that wrote this file. Until both keys sign, nothing here may be quoted
> as a macro specification, and no result may be described as "passing the
> macro spec".

Epic #24 (parent), issue #82. Pattern follows
[`operating-range-decision-PROPOSED.md`](operating-range-decision-PROPOSED.md).
Epic #24 item 6 calls for post-layout PVT simulation "against a ratified
macro-level spec"; the only ratified spec,
[`retention-refresh-budget.md`](retention-refresh-budget.md), is
device/cell-level (its section 5: "not an array-level or macro-level spec").
**No new simulation was run to write this record.**

## 1. Provenance of the thresholds, and when this was written

Written **2026-10-09**, on `main` at `f677f26`. State of the evidence at that
time, so a reader can tell which conditions were fixed before results and
which were not:

| Item | Evidence existing on 2026-10-09 | Consequence for this record |
|---|---|---|
| 2 sense amplifier | Loaded-column study (run `20261005T102906Z`), cold-corner study (`20261005T145658Z`), sense-stage characterization (#60, `sim/sense-stage/results/`, 2026-10-09) | **Item 2 is graded retrospectively in part.** The record cannot claim its item-2 thresholds precede all results. They are carried unchanged from texts that predate this record (the epic #24 revision of 2026-10-04 and the Phase 3 study criteria), not chosen here. The author read the per-corner table already quoted in `operating-range-decision-PROPOSED.md` section 4 and did **not** open the sense-stage result files while choosing any number |
| 3 refresh controller | Refresh-overhead envelope (#59), behavioral scheduler and testbench (#74, `digital/refresh-scheduler/`) | Interval threshold is the ratified section 7 value (cited, not chosen). Overhead and stall thresholds are new ASSUMPTIONs, set without reading the scheduler's measured stall |
| 4 SPI | None (#83 is open) | Thresholds precede results |
| 5 macro layout | 4x4 array DRC/LVS reports only (#34); no macro GDS | Thresholds precede results |
| 6 post-layout PVT | None | Thresholds precede results |

Rules applied to every threshold below: it is either (a) **RATIFIED-CITED**,
copied from a named section of a ratified file, or (b) an **ASSUMPTION** with
a stated rationale. None was fitted to an existing result. If a later result
fails a threshold, the response is to report the failure; relaxing the
threshold is a decision-record change under section 6, never an edit made to
make a result pass.

### Dated update, 2026-11-20 (issue #386): evidence that landed after the thresholds were fixed

Nothing in this update is an input to any threshold in section 3. The table
above remains the record of what the authors knew on 2026-10-09; this note
exists so the later evidence below cannot be mistaken for an input to the
original choices. Two inputs the 2026-10-09 record listed as outstanding have
since landed on `main`:

- **Read-bitline load.** The 4-row extraction is committed
  (#80, #88, #261): worst total
  **0.955559 fF** on net `rbl_2`
  ([`layout/gain_cell_2t_array.parasitics.summary.json`](../layout/gain_cell_2t_array.parasitics.summary.json)),
  against the 10 fF ASSUMPTION (ratio 0.0956). The sense-stage studies were
  re-run at that load on the #293-corrected latch (#357): design card
  [`sense_summary_20261118T194931Z.json`](../sim/sense-stage/results/sense_summary_20261118T194931Z.json)
  and layout card
  [`sense_summary_20261118T194901Z.json`](../sim/sense-stage/results/sense_summary_20261118T194901Z.json),
  10 corners each; both raw reports carry the executed worker stamp
  `open_pdks f6eeac7` (`klt_report_*.json`,
  `environment.remote.worker_environment.pdk.stamp_text`). The 10 fF baseline
  and the 2 fF sensitivity run remain ASSUMPTIONs, not measurements.
- **Offset statistics.** The mismatch studies are committed (#81; re-run on
  the regenerated decks, #249): stage-only latch offset
  [`mismatch_summary_20261115T115508Z.json`](../sim/sense-mismatch/results/mismatch_summary_20261115T115508Z.json)
  and the separate end-to-end cell study
  [`mismatch_cell_summary_20261115T115950Z.json`](../sim/sense-mismatch/results/mismatch_cell_summary_20261115T115950Z.json);
  both raw reports carry the same executed stamp. The row-2e consequence is
  recorded in the row itself and in section 4.

Landed results are graded against the thresholds above, not the reverse. Two
landed failures are on record for traceability, stated here because the row
2a evidence cell belongs to a separate open change (#312, PR #318): on the
RESTRICTED set the 10 fF baseline's minimum `column_all_rows` separation
(328.8502 mV, `fs`/27 C, refresh-bound age,
[`sim/loaded-column/results/summary_20261114T091445Z.json`](../sim/loaded-column/results/summary_20261114T091445Z.json))
clears the row-2a 0.1 V criterion, while on the **fallback 15-point grid**
the same study's `fs`/-40 C aged separation is **24.4799 mV — below the 0.1 V
criterion, a failure reported as a failure** (Q6, #395). The same corner and
age at the extracted 0.955559 fF load measures **0.102376 V and passes**
(variant `crbl_ext4row`, 15 PVT points x 2 ages, 30/30 pass on separation,
latency and disturb;
[`sim/loaded-column/extracted-crbl/results/20261029T203633Z/summary.json`](../sim/loaded-column/extracted-crbl/results/20261029T203633Z/summary.json),
#88). That pairing does **not** isolate load, because the PDK revision differs
between the two campaigns: the November 10 fF baseline executed under
`open_pdks f6eeac7`, while the October campaign's executed worker stamp
(`environment.remote.worker_environment.pdk.stamp_text` in its raw
`klt_report_*.json.gz`) is `open_pdks c6d73a35f524070e85faff4a6a9eef49553ebc2b`
(`c6d73a3`; the same reports' client-side `provenance.pdk.version` reads
`f6eeac7`, which does not show what the worker ran). The October campaign
carries its own in-run 10 fF control, variant `ref_crbl_10f`, at the same
`c6d73a3` pin, deck family and `IDEAL` periphery: at `fs`/-40 C
refresh-bound age it measures **16.733 mV** against 102.376 mV for
`crbl_ext4row`, so the load-only comparison is 16.733 mV to 102.376 mV. The
two 10 fF figures at the identical point (24.4799 mV at `f6eeac7`, 16.733 mV
at `c6d73a3`) differ by 7.747 mV across the PDK step alone, more than the
2.376 mV by which the extracted result clears the 0.1 V threshold, so the
clearance is not claimed to carry over to the newer pin. The 10 fF fallback-grid
failure stands on either pin. The extracted-load result is cited alongside the
10 fF failure, not in place of it,
and carries its own caveats: `baseline_periphery` is `IDEAL`
(`real_periphery_used: false`), and substituting 0.955559 fF for 10 fF is, in
the campaign's words, "a bounding (lightest-load) case". At the same extracted
load, row 2d's `stored1_preread_v` falls **below its 0.9 V floor on the
fallback grid** — **0.866505 V** at `fs`/-40 C refresh-bound age, 0.869658 V
at `fs`/-40 C fresh, 0.898944 V at `ss`/-40 C refresh-bound age — while the
RESTRICTED-set minimum (27/125 C, 20 points) is 0.934665 V and clears it. The
per-point `PASS` flag in that summary covers separation, latency and
disturb only, so it does not reflect this shortfall; it is reported as a
failure and row 2d is not adjusted (Q6, #395). Separately, the
corrected-latch runs at the extracted load report their usable-droop verdict
at the 100 mV placeholder reference as violated at every corner (the standing
`VDD`/2 FINDING; [`sim/sense-stage/README.md`](../sim/sense-stage/README.md))
— a finding against the ratified `delta_V` ASSUMPTION, not a threshold this
record relaxes (row 2d; Q4, #393).

## 2. Ratified values this record consumes (not touched)

From [`retention-refresh-budget.md`](retention-refresh-budget.md) (RATIFIED):
2T topology (section 6); refresh-interval upper bound ~5.03 us at `sf`/125 C
(section 7, 2x margin ASSUMPTION); bandwidth formula
`(N_rows * t_row_refresh_op) / refresh_interval` (section 7); `delta_V` =
`VDD`/2 = 0.9 V remains an ASSUMPTION (section 8). Not ratified, and so not
fixed here either: `N_rows`, `t_row_refresh_op`, sense-derived margin.

## 3. Pass conditions, one row per item

Legend. **Status**: `RATIFIED-CITED (file section)` or `ASSUMPTION`.
**Corner set** "RESTRICTED" means 5 process corners (tt, ss, ff, sf, fs) at
27 C and 125 C, `VDD` = 1.8 V, which is the interval *proposed* in
[`operating-range-decision-PROPOSED.md`](operating-range-decision-PROPOSED.md)
section 6; if the keys do not ratify it, the fallback is the existing 15-point
grid (5 corners x -40/27/125 C), on which fs/-40 C is already known to fail the
Phase 3 criteria, and item 2/6 would be graded as failing there. Retention
quantities are always evaluated at the worst-case corner, `sf`/125 C
(ratified section 2), in addition to the set.

**Supply reporting rule (Q7, operator ruling 2026-11-23, #396).** Item 6 is
graded at `VDD` = 1.8 V only. Every graded item-6 result (6a-6d) must carry
the sentence "VDD = 1.8 V only; supply tolerance not studied" (or equivalent)
next to it, in the same table cell, summary or report line. No result may be
described as supply-tolerant.

**Statistical rows.** Rows **2e** and **6d** are statistical: their evidence
is mismatch Monte Carlo, graded on sample statistics (sigma fits with
confidence intervals and sample counts reported, unresolved tails stated),
not on single deterministic sweeps. The item-6 row set is 6a-6d, of which 6d
is the statistical row; the Monte Carlo row set for item 6 may be declared
from this statement.

| # | Item | Quantity | Corner / temperature set | Pass threshold | Status | Testbench that will produce the evidence |
|---|---|---|---|---|---|---|
| 2a | Sense amplifier | Column-wide signed read separation `min V(rbl\|0) - max V(rbl\|1)` at `t_sense`, every row, all stored-pattern combinations of the other rows, at both ages (fresh; aged to the refresh bound) | RESTRICTED, plus `sf`/125 C aged | >= 0.1 V at every point; 64/64 cases simulated | ASSUMPTION (0.1 V is the Phase 3 placeholder, [cold-corner README](../sim/loaded-column/cold-corner/README.md) "Pass criteria"; carried, not promoted) | `sim/loaded-column/` and `sim/loaded-column/cold-corner/` (committed); re-run with the real sense cell loaded (a schematic-level sense latch exists, `design/sense_latch.sch`, #109, but has no layout, so the committed decks' ideal drivers are still the state of the evidence) |
| 2b | Sense amplifier | Stored-'1' latency to the 0.1 V droop; read disturb | RESTRICTED | Latency <= 10 ns for every stored-'1' case; read disturb <= 0.1 V | ASSUMPTION (placeholders from the same study; 10 ns and 0.1 V) | same as 2a |
| 2c | Sense amplifier | Correct-sign latch decision, full swing, with a stored-level at the *achievable* written level (not an idealized level) aged to the refresh bound | RESTRICTED | `\|d\|` >= 0.9 V at full swing, correct sign, within 5 ns of enable, every point; negative control (stored '0' never read as '1') passes | ASSUMPTION (decision criterion as stated in [`sim/sense-stage/README.md`](../sim/sense-stage/README.md) "Inputs") | `sim/sense-stage/` (`request.json`, `analyze_sense_stage.py`, `test_sense_stage.py`) |
| 2d | Sense amplifier | Stored-'1' level after write and before read | RESTRICTED | >= 0.9 V, i.e. compatible with the ratified `delta_V` ASSUMPTION; otherwise `delta_V` must be re-ratified, not silently lowered | ASSUMPTION (a reading of the ratified `delta_V` = 0.9 V ASSUMPTION; `operating-range-decision-PROPOSED.md` section 3) | `sim/loaded-column/` (`v_sn1_preread`) |
| 2e | Sense amplifier | Input-referred offset: margin versus offset sigma | RESTRICTED, mismatch Monte Carlo, worst corners | Smallest passing separation (2a) >= 6 x input-referred offset sigma; sample count and the confidence interval on sigma reported, an unresolved tail stated | ASSUMPTION (6 sigma is a placeholder yield proxy, about 1e-9 one-sided per decision under a Gaussian model; chosen because it is a conventional margin and not derived from any array yield target, which does not exist) | Committed: #81 (closed), re-run on the corrected latch (#293, #249) — stage study [`mismatch_summary_20261115T115508Z.json`](../sim/sense-mismatch/results/mismatch_summary_20261115T115508Z.json) (n=40 samples per corner, seed 2026100981, corners tt_mm/27, fs_mm/27, ss_mm/125, sf_mm/125 C — not the RESTRICTED set) and end-to-end cell study [`mismatch_cell_summary_20261115T115950Z.json`](../sim/sense-mismatch/results/mismatch_cell_summary_20261115T115950Z.json) (fs_mm/27 C only); both raw reports carry executed stamp `open_pdks f6eeac7`. Worst latch sigma 19.149 mV (95% CI 18.0904-20.2901) at sf_mm/125 C, so 6 sigma = 114.894 mV, against the measured minimum restricted-set `column_all_rows` separation 328.8502 mV at fs/27 C, refresh-bound age, on the same 10 fF load basis ([`sim/loaded-column/results/summary_20261114T091445Z.json`](../sim/loaded-column/results/summary_20261114T091445Z.json)): the numerical proxy **clears**, as the row's written threshold specifies (full separation, row 2a's quantity). That is not a six-sigma decision margin: a latch sees each population's distance to its reference, and the evidence's own single-reference half-window `candidate_reference_half_window_v` is 164.4251 mV (about 1.43x the 114.894 mV), which the basis question (Q2, #391) owns. Row remains **ungraded**: `offset_yield_validated: false`, the Gaussian tail beyond 40 samples is unresolved, capacitor-family mismatch is unconfirmed in the PDK, read-device spread is not folded into the latch sigma, and corner coverage is four mismatch corners. Yield report and manifest entry: #384; the target itself: Q2 (#391) |
| 3a | Refresh controller | Maximum time since last write or refresh of any row, in wall-clock time (clock cycles x clock period) | Behavioral: idle, saturating foreground traffic, seeded random traffic; clock period chosen so cycles map to time at the declared frequency | <= 5.03 us (about 5.029945 us) for every row under every scenario, including reset-to-first-refresh | **RATIFIED-CITED** ([`retention-refresh-budget.md`](retention-refresh-budget.md) section 7) | `digital/refresh-scheduler/` (`tb_refresh_sched.v`, `run_tests.sh`, mutation check `run_mutation.sh` must *fail* when the scheduler is broken) |
| 3b | Refresh controller | Foreground starvation: any request waiting while refresh is deferred, and refresh deferred by foreground | Same as 3a | Zero starved refreshes; every foreground request is served within a stated bound, and that bound is reported | ASSUMPTION (the bound itself is set by the operator question Q3, below) | `digital/refresh-scheduler/` |
| 3c | Refresh controller | Refresh bandwidth overhead `(N_rows * t_row_refresh_op) / refresh_interval`, evaluated with the *design's own* `N_rows` and the measured `t_row_refresh_op` at the slowest corner | Slowest-read corner of the RESTRICTED set; `refresh_interval` = 5.03 us | <= 50 % | ASSUMPTION (rationale: leaves at least half of the bandwidth to foreground access; the formula is ratified, the limit is not; this is the cost the macro pays for density and is not hidden) | `sim/refresh-overhead/` (envelope, committed) fed by the macro's `t_row_refresh_op` once measured |
| 4a | SPI control | Function: single-address read, write, refresh-status read; first and last valid address; invalid opcode and invalid address rejected with a status/error; interrupted frame and reset recovery | Digital, behavioral (no temperature dependence) | Every self-checking test passes, and the deliberately-broken mutant fails | ASSUMPTION (command set, mode, clock limit, framing are provisional until checked against the published Challenge #4 brief) | Planned: #83 (SPI-slave behavioral model and testbench); not yet committed |
| 4b | SPI control | Data preservation and refresh deadline during SPI traffic at the maximum SCK | Digital, behavioral, with the 3a scenarios overlapped | Zero corrupted data; 3a threshold (<= 5.03 us) still met while SPI is active | **RATIFIED-CITED** for the 5.03 us bound (section 7), ASSUMPTION for the SCK limit | #83 testbench combined with `digital/refresh-scheduler/` |
| 5a | Macro layout | Full-macro DRC | Corner-independent | `status: clean`, `violation_count: 0`, with the rule-deck coverage (layers checked, rules skipped) reported next to the result; a "clean" over a partial deck is reported as *informal*, not as a pass of this row | ASSUMPTION (the rows on the 4x4 array report only 6 of 16 deck layers; whether a released full deck exists is outside this repo, see Q5) | Planned: committed macro GDS plus fresh `klt drc` result JSON under `layout/` (same format as `layout/gain_cell_2t_array.drc.result.json`) |
| 5b | Macro layout | Full-macro LVS and ERC | Corner-independent | LVS `match`, zero error-severity mismatches, 100 % of devices and nets matched; ERC clean; any warning-severity entries enumerated | ASSUMPTION (same reasoning; format as `layout/gain_cell_2t_array.lvs.result.json`, `layout/gain_cell_2t_array.erc.result.json`) | Planned: fresh LVS and ERC results for the macro GDS |
| 6a | Post-layout PVT | Write/read functional margin on the extracted macro | RESTRICTED (mismatch included for 6d); **Supply: `VDD` = 1.8 V only; no supply-tolerance band simulated** (Q7). | Items 2a, 2b, 2c, 2d thresholds met on extracted views, every point; no "informal" substitution of ideal drivers | ASSUMPTION (inherits 2a-2d) | Planned: extracted-netlist `klt sim` request under a new `sim/` directory; not yet committed |
| 6b | Post-layout PVT | Retention/refresh margin: stored data survives a dwell equal to the ratified refresh interval, and the sense margin 6a still holds after that dwell | `sf`/125 C (worst case, ratified section 2) and the RESTRICTED set; **Supply: `VDD` = 1.8 V only; no supply-tolerance band simulated** (Q7). | Hold-and-read passes at dwell = 5.03 us at every point; the dwell at which the first failure occurs is reported and must be >= 5.03 us at `sf`/125 C | **RATIFIED-CITED** for 5.03 us (section 7); ASSUMPTION for "must hold at exactly the interval, i.e. no extra margin demanded here" (see Q1 on the 2x margin) | Planned: same as 6a |
| 6c | Post-layout PVT | Refresh closure on the extracted macro | RESTRICTED; **Supply: `VDD` = 1.8 V only; no supply-tolerance band simulated** (Q7). | 3a and 3c thresholds re-evaluated with extracted `t_row_refresh_op` | **RATIFIED-CITED** (5.03 us) / ASSUMPTION (50 %) | Planned: same as 6a plus `digital/refresh-scheduler/` |
| 6d | Post-layout PVT | Sense-offset margin on the extracted macro | RESTRICTED, mismatch Monte Carlo; **Supply: `VDD` = 1.8 V only; no supply-tolerance band simulated** (Q7). | 2e threshold on extracted bitline loading | ASSUMPTION (inherits 2e) | **Statistical row** (see legend). Waiting on a named input that still does not exist: a mismatch Monte Carlo study at the extracted-macro bitline load (extension of the #81 decks). The deterministic extracted-load variants — design card [`sense_summary_20261118T194931Z.json`](../sim/sense-stage/results/sense_summary_20261118T194931Z.json), layout card [`sense_summary_20261118T194901Z.json`](../sim/sense-stage/results/sense_summary_20261118T194901Z.json), C_RBL = 0.955559 fF — and the 10 fF mismatch study answer different parts of this row; neither is that input. Target basis: Q2 (#391) |

## 4. Which conditions depend on outstanding evidence

A condition marked here cannot be graded, or its threshold cannot be
finalized, until the named input exists. Until then the condition stays a
PROPOSED statement and any report against it is labelled provisional.

| Outstanding input | Conditions that depend on it | Why |
|---|---|---|
| **Bitline capacitance** (4-row extraction landed: worst total 0.955559 fF on `rbl_2`, [`layout/gain_cell_2t_array.parasitics.summary.json`](../layout/gain_cell_2t_array.parasitics.summary.json), #80/#88/#261; the 10 fF baseline and the 2 fF sensitivity run remain ASSUMPTIONs — Q4, #393) | 2a, 2b have extracted-load evidence: the committed `crbl_ext4row` column campaign ([`summary.json`](../sim/loaded-column/extracted-crbl/results/20261029T203633Z/summary.json), #88; 15 PVT points x 2 ages, 30/30 pass; min separation 0.102376 V and worst stored-'1' latency 9.145 ns, both at `fs`/-40 C refresh-bound age; max read disturb 0.060185 V), with `baseline_periphery: IDEAL` and the lightest-load bounding caveat (section 1), alongside the 10 fF baseline ([`sim/loaded-column/results/summary_20261114T091445Z.json`](../sim/loaded-column/results/summary_20261114T091445Z.json)), which fails 2a on the fallback grid; 2c is **not yet gradable**, and 2d is graded provisionally (below): the corrected-latch re-runs at the extracted load ([design card](../sim/sense-stage/results/sense_summary_20261118T194931Z.json), [layout card](../sim/sense-stage/results/sense_summary_20261118T194901Z.json), executed stamp `open_pdks f6eeac7`) sweep the storage node directly ("sweep, not a measurement", [`sim/sense-stage/README.md`](../sim/sense-stage/README.md)), so they bound the minimum resolvable level but do not establish the achieved aged level; grading 2c needs the column study's measured aged level mapped onto that sweep at the matching corner and card (the sense-stage `phase3_stored1_after_write_min_v` is imported from the older Phase 3 study, so that sweep cannot grade 2d). **2d is gradable provisionally, from the column campaign itself**: its `cases.csv.gz` ([`20261029T203633Z`](../sim/loaded-column/extracted-crbl/results/20261029T203633Z/cases.csv.gz)) carries `v_sn_r{0..3}_after_write_v` and `v_sn_r{0..3}_preread_v` in the same cases (select `stored_value` = 1 and use `sel_row` to choose the selected row's fields). For variant `crbl_ext4row`, this design card, this 0.955559 fF load, executed worker stamp `c6d73a3` (section 1) and `IDEAL` periphery: RESTRICTED set (27/125 C, 640 stored-'1' cases) minimum after-write **0.938086 V** (`fs`/27 C, fresh) and minimum preread **0.934665 V** (`fs`/27 C, refresh-bound age), both **pass** the 0.9 V floor; the fallback grid adds -40 C (320 stored-'1' cases) with minimum after-write **0.869663 V** (`fs`/-40 C, fresh) and minimum preread **0.866505 V** (`fs`/-40 C, refresh-bound age), both **fail** it, reported as a failure (Q6, #395). The 0.9 V threshold is untouched. Full-macro grading of 2d stays open: it waits on a macro-sized bitline extraction and real periphery. 2c is the only row of the pair whose "not yet gradable" reason holds, because the column-to-sweep mapping does not exist; 2e still evidenced only on the 10 fF baseline (the mismatch studies); 3c, 6a, 6b, 6c, 6d wait on a macro-sized bitline extraction, which does not exist (4 rows of wiring only) | Every separation, latency and `t_row_refresh_op` figure scales with the read-bitline load; the ss/-40 C result was already shown sensitive to `C_RBL` and `t_sense` |
| **Offset statistics** (landed at the 10 fF baseline: stage study [`mismatch_summary_20261115T115508Z.json`](../sim/sense-mismatch/results/mismatch_summary_20261115T115508Z.json) — worst latch sigma 19.149 mV from `probit_fit_nominal_d` (the same file's `probit_fit_din` worst-corner sigma is larger, 19.6296 mV, 6 sigma = 117.778 mV, which leaves the 2e conclusion unchanged), 95% CI 18.0904-20.2901, n=40 x 4 corners — and end-to-end cell study [`mismatch_cell_summary_20261115T115950Z.json`](../sim/sense-mismatch/results/mismatch_cell_summary_20261115T115950Z.json); #81, #249) | 2e gradable now as a provisional numerical comparison (6 sigma = 114.894 mV vs measured minimum restricted-set separation 328.8502 mV; see the row); full grading and the yield report are #384's and the target itself is Q2 (#391); 6d waits on mismatch evidence at the extracted-macro load, which does not exist; 2a indirectly | `offset_yield_validated` stays `false` in the committed summaries: the tail beyond 40 samples is unresolved, the capacitor mismatch family is unconfirmed for the PDK, and read-device spread is not folded into the latch sigma |
| **Operating-range ratification** (`operating-range-decision-PROPOSED.md`) | Every corner set above | RESTRICTED is a proposal; if rejected or changed, all sets change |
| **Chipalooza Challenge #4 rules** (rules-4.html publishes 2026-11-09 per [`docs/chipalooza/challenge-4-proposal.md`](../docs/chipalooza/challenge-4-proposal.md)) | 4a, 4b (command set, mode, SCK limit), 5a, 5b (which deck counts as full), 6 as a whole (supply and corner definitions the harness uses) | SPI and sign-off details here are assumed from earlier rounds' rules. This record makes no rules-compliance claim |
| **Storage-node capacitance for the array** | 6b | The ratified retention uses the 1.106463 fF ASSUMED `C_SN` (section 3); the post-layout extraction is 0.605354 fF and gives 5.504 us at `sf`/125 C ([`docs/chipalooza/challenge-4-proposal.md`](../docs/chipalooza/challenge-4-proposal.md) section 4.1). The two are not reconciled (Q1) |
| **`N_rows` and the real `t_row_refresh_op`** | 3c, 6c | Neither is ratified; the committed envelope covers `N_rows` 4 to 1024 as ASSUMPTION only |
| **A sense cell design** (sizes are first pass) | 2a to 2e on the real cell | Sense-stage topology and sizes are an ASSUMPTION |

## 5. Overlap with issue #74

#74 (refresh scheduler behavioral model) owns the *scheduler-level deadline
invariant* "no row's time-since-last-write exceeds `refresh_interval`".
Condition 3a only *grades* that invariant at the ratified 5.03 us; it adds no
new refresh model, and the invariant's definition and mutation check live with
#74's testbench. The rows that go beyond #74 are 3b (starvation bound), 3c
(overhead limit), 4b (SPI overlap) and 6c (extracted timing).

## 6. Ratification path (the only route to RATIFIED)

Nothing in this file becomes a specification by any other route. This PR does
not ratify, and no agent, label or merge changes the status line above.

1. A decision record (this file, or a successor that cites it) is reviewed by
   the `ee-key` (`ratification/ee-key/`) and the `market-key`
   (`ratification/market-key/`) independently.
2. `ee-key`: accept or reject each threshold and the evidence basis for it;
   rule on every ASSUMPTION (keep, replace, or demand evidence); confirm that
   no threshold was fitted to a result (section 1).
3. `market-key`: accept or reject the claim consequences, in particular that
   the macro is a dynamic gain-cell memory with a refresh requirement, is
   not full-range, and is not a drop-in replacement for SRAM.
4. Both keys sign, the outcome is recorded in `spec/` and the status line is
   flipped. Until then conditions stay PROPOSED and results against them are
   reported as provisional.
5. After ratification, a threshold change is a new decision record with its
   own two-key pass. A failing result is reported as failing.

## 7. Open questions for the operator

Not decided here; each needs a ruling or a key decision. Q2 to Q7 are filed
as operator decision issues (2026-11-20, issue #386), each with ranked
options and a recommendation; the links are below. Q1 is already with the
operator in #208 (PR #223).

- **Q1. Refresh margin versus the extracted `C_SN`.** The ratified 5.03 us
  interval is half of 10.06 us, which rests on the ASSUMED 1.106463 fF. The
  post-layout extracted `C_SN` (0.605354 fF) gives a single-cell retention of
  5.504 us at `sf`/125 C, so the ratified interval would carry about 1.09x
  margin, not 2x. Which governs the macro: re-derive and re-ratify the
  interval, or keep 5.03 us? Row 6b is written at exactly 5.03 us for that
  reason and may need a stricter dwell. *With the operator: #208, PR #223.*
- **Q2. Offset yield target.** Is 6 sigma (row 2e) the intended proxy, or is a
  different yield or bit-error target to be set? No array yield target exists.
  *Filed as #391.*
- **Q3. Foreground latency bound and overhead limit.** What worst-case
  foreground stall is acceptable (row 3b), and is 50 % refresh overhead (row
  3c) the right ceiling for this macro's claim? *Filed as #392.*
- **Q4. Whether the 0.1 V, 10 fF, 10 ns, 0.9 V and 5 ns values stay as
  placeholders** or are replaced once #80 and #81 land. This record carries
  them forward only so something is gradable now. Both inputs have landed
  (section 1, dated update); the question is now whether the placeholders
  stay as the graded thresholds. *Filed as #393.*
- **Q5. What counts as a "full" DRC/LVS pass** (rows 5a, 5b) while the
  rule deck is partial; and whether a "clean over a partial deck" result may
  be reported at all, and under what label. *Filed as #394.*
- **Q6. Fallback if the restricted range is not ratified.** Should items 2 and
  6 then be graded against the full 15-point grid, where fs/-40 C is already
  known to fail? *Filed as #395. The range review itself — the ratification PR
  and both key reviews — is #385's.*
- **Q7. Supply.** All committed grids are `VDD` = 1.8 V only. Is a supply
  tolerance band required before item 6 is graded? *Filed as #396.*
  **Resolved by operator ruling, 2026-11-23 (option a; round 20261121-r19,
  r19-q293, slate r19-s26; #396):** "Grade item 6 at 1.8 V only, with the
  absence of a supply band stated next to every graded result." No supply
  band is required, and none has been simulated. Options b (a +/-10 % `VDD`
  band) and c (wait for the Chipalooza rules-4.html) were ruled out. This
  records the ruling only: it ratifies nothing, changes no threshold, and the
  record stays PROPOSED. If the harness later defines a supply band, that is
  a new decision record, not an edit here.

**Next step once the operator has answered.** This record then goes to the
`ee-key` and `market-key` reviews per section 6. That two-key pass is not run
by the update that added these links (issue #386): it follows the operator's
answers, Q1 included.

## 8. What this record does not do

- It does not edit `retention-refresh-budget.md` or any other ratified file,
  nor `operating-range-decision-PROPOSED.md`.
- It does not claim any row is met; it gives no result, only conditions.
- It does not describe the macro as an SRAM replacement. A gain cell is
  dynamic: retention and refresh are the centerpiece, not a footnote.
- It uses public sources only: the shipped sky130 models, the committed
  netlists and write-ups in this repo, and the public Chipalooza pages cited
  in `docs/chipalooza/challenge-4-proposal.md`.
