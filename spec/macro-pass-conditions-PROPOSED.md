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

| # | Item | Quantity | Corner / temperature set | Pass threshold | Status | Testbench that will produce the evidence |
|---|---|---|---|---|---|---|
| 2a | Sense amplifier | Column-wide signed read separation `min V(rbl\|0) - max V(rbl\|1)` at `t_sense`, every row, all stored-pattern combinations of the other rows, at both ages (fresh; aged to the refresh bound) | RESTRICTED, plus `sf`/125 C aged | >= 0.1 V at every point; 64/64 cases simulated | ASSUMPTION (0.1 V is the Phase 3 placeholder, [cold-corner README](../sim/loaded-column/cold-corner/README.md) "Pass criteria"; carried, not promoted) | `sim/loaded-column/` and `sim/loaded-column/cold-corner/` (committed); re-run with the real sense cell loaded once one exists |
| 2b | Sense amplifier | Stored-'1' latency to the 0.1 V droop; read disturb | RESTRICTED | Latency <= 10 ns for every stored-'1' case; read disturb <= 0.1 V | ASSUMPTION (placeholders from the same study; 10 ns and 0.1 V) | same as 2a |
| 2c | Sense amplifier | Correct-sign latch decision, full swing, with a stored-level at the *achievable* written level (not an idealized level) aged to the refresh bound | RESTRICTED | `\|d\|` >= 0.9 V at full swing, correct sign, within 5 ns of enable, every point; negative control (stored '0' never read as '1') passes | ASSUMPTION (decision criterion as stated in [`sim/sense-stage/README.md`](../sim/sense-stage/README.md) "Inputs") | `sim/sense-stage/` (`request.json`, `analyze_sense_stage.py`, `test_sense_stage.py`) |
| 2d | Sense amplifier | Stored-'1' level after write and before read | RESTRICTED | >= 0.9 V, i.e. compatible with the ratified `delta_V` ASSUMPTION; otherwise `delta_V` must be re-ratified, not silently lowered | ASSUMPTION (a reading of the ratified `delta_V` = 0.9 V ASSUMPTION; `operating-range-decision-PROPOSED.md` section 3) | `sim/loaded-column/` (`v_sn1_preread`) |
| 2e | Sense amplifier | Input-referred offset: margin versus offset sigma | RESTRICTED, mismatch Monte Carlo, worst corners | Smallest passing separation (2a) >= 6 x input-referred offset sigma; sample count and the confidence interval on sigma reported, an unresolved tail stated | ASSUMPTION (6 sigma is a placeholder yield proxy, about 1e-9 one-sided per decision under a Gaussian model; chosen because it is a conventional margin and not derived from any array yield target, which does not exist) | Planned: #81 (Monte Carlo study of the sense stage via `klt sim` `monte_carlo`); not yet committed |
| 3a | Refresh controller | Maximum time since last write or refresh of any row, in wall-clock time (clock cycles x clock period) | Behavioral: idle, saturating foreground traffic, seeded random traffic; clock period chosen so cycles map to time at the declared frequency | <= 5.03 us (about 5.029945 us) for every row under every scenario, including reset-to-first-refresh | **RATIFIED-CITED** ([`retention-refresh-budget.md`](retention-refresh-budget.md) section 7) | `digital/refresh-scheduler/` (`tb_refresh_sched.v`, `run_tests.sh`, mutation check `run_mutation.sh` must *fail* when the scheduler is broken) |
| 3b | Refresh controller | Foreground starvation: any request waiting while refresh is deferred, and refresh deferred by foreground | Same as 3a | Zero starved refreshes; every foreground request is served within a stated bound, and that bound is reported | ASSUMPTION (the bound itself is set by the operator question Q3, below) | `digital/refresh-scheduler/` |
| 3c | Refresh controller | Refresh bandwidth overhead `(N_rows * t_row_refresh_op) / refresh_interval`, evaluated with the *design's own* `N_rows` and the measured `t_row_refresh_op` at the slowest corner | Slowest-read corner of the RESTRICTED set; `refresh_interval` = 5.03 us | <= 50 % | ASSUMPTION (rationale: leaves at least half of the bandwidth to foreground access; the formula is ratified, the limit is not; this is the cost the macro pays for density and is not hidden) | `sim/refresh-overhead/` (envelope, committed) fed by the macro's `t_row_refresh_op` once measured |
| 4a | SPI control | Function: single-address read, write, refresh-status read; first and last valid address; invalid opcode and invalid address rejected with a status/error; interrupted frame and reset recovery | Digital, behavioral (no temperature dependence) | Every self-checking test passes, and the deliberately-broken mutant fails | ASSUMPTION (command set, mode, clock limit, framing are provisional until checked against the published Challenge #4 brief) | Planned: #83 (SPI-slave behavioral model and testbench); not yet committed |
| 4b | SPI control | Data preservation and refresh deadline during SPI traffic at the maximum SCK | Digital, behavioral, with the 3a scenarios overlapped | Zero corrupted data; 3a threshold (<= 5.03 us) still met while SPI is active | **RATIFIED-CITED** for the 5.03 us bound (section 7), ASSUMPTION for the SCK limit | #83 testbench combined with `digital/refresh-scheduler/` |
| 5a | Macro layout | Full-macro DRC | Corner-independent | `status: clean`, `violation_count: 0`, with the rule-deck coverage (layers checked, rules skipped) reported next to the result; a "clean" over a partial deck is reported as *informal*, not as a pass of this row | ASSUMPTION (the rows on the 4x4 array report only 6 of 16 deck layers; whether a released full deck exists is outside this repo, see Q5) | Planned: committed macro GDS plus fresh `klt drc` result JSON under `layout/` (same format as `layout/gain_cell_2t_array.drc.result.json`) |
| 5b | Macro layout | Full-macro LVS and ERC | Corner-independent | LVS `match`, zero error-severity mismatches, 100 % of devices and nets matched; ERC clean; any warning-severity entries enumerated | ASSUMPTION (same reasoning; format as `layout/gain_cell_2t_array.lvs.result.json`, `layout/gain_cell_2t_array.erc.result.json`) | Planned: fresh LVS and ERC results for the macro GDS |
| 6a | Post-layout PVT | Write/read functional margin on the extracted macro | RESTRICTED (mismatch included for 6d) | Items 2a, 2b, 2c, 2d thresholds met on extracted views, every point; no "informal" substitution of ideal drivers | ASSUMPTION (inherits 2a-2d) | Planned: extracted-netlist `klt sim` request under a new `sim/` directory; not yet committed |
| 6b | Post-layout PVT | Retention/refresh margin: stored data survives a dwell equal to the ratified refresh interval, and the sense margin 6a still holds after that dwell | `sf`/125 C (worst case, ratified section 2) and the RESTRICTED set | Hold-and-read passes at dwell = 5.03 us at every point; the dwell at which the first failure occurs is reported and must be >= 5.03 us at `sf`/125 C | **RATIFIED-CITED** for 5.03 us (section 7); ASSUMPTION for "must hold at exactly the interval, i.e. no extra margin demanded here" (see Q1 on the 2x margin) | Planned: same as 6a |
| 6c | Post-layout PVT | Refresh closure on the extracted macro | RESTRICTED | 3a and 3c thresholds re-evaluated with extracted `t_row_refresh_op` | **RATIFIED-CITED** (5.03 us) / ASSUMPTION (50 %) | Planned: same as 6a plus `digital/refresh-scheduler/` |
| 6d | Post-layout PVT | Sense-offset margin on the extracted macro | RESTRICTED, mismatch Monte Carlo | 2e threshold on extracted bitline loading | ASSUMPTION (inherits 2e) | Planned: extension of #81 |

## 4. Which conditions depend on outstanding evidence

A condition marked here cannot be graded, or its threshold cannot be
finalized, until the named input exists. Until then the condition stays a
PROPOSED statement and any report against it is labelled provisional.

| Outstanding input | Conditions that depend on it | Why |
|---|---|---|
| **Bitline capacitance** (`C_RBL` is a 10 fF ASSUMPTION; extraction is #80) | 2a, 2b, 2c, 2e, 3c, 6a, 6b, 6c, 6d | Every separation, latency and `t_row_refresh_op` figure scales with the read-bitline load; the ss/-40 C result was already shown sensitive to `C_RBL` and `t_sense` |
| **Offset statistics** (no mismatch exists; #81) | 2e, 6d; indirectly 2a | The 6-sigma comparison needs sigma; `offset_yield_validated` is `false` in the committed summary |
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

Not decided here; each needs a ruling or a key decision.

- **Q1. Refresh margin versus the extracted `C_SN`.** The ratified 5.03 us
  interval is half of 10.06 us, which rests on the ASSUMED 1.106463 fF. The
  post-layout extracted `C_SN` (0.605354 fF) gives a single-cell retention of
  5.504 us at `sf`/125 C, so the ratified interval would carry about 1.09x
  margin, not 2x. Which governs the macro: re-derive and re-ratify the
  interval, or keep 5.03 us? Row 6b is written at exactly 5.03 us for that
  reason and may need a stricter dwell.
- **Q2. Offset yield target.** Is 6 sigma (row 2e) the intended proxy, or is a
  different yield or bit-error target to be set? No array yield target exists.
- **Q3. Foreground latency bound and overhead limit.** What worst-case
  foreground stall is acceptable (row 3b), and is 50 % refresh overhead (row
  3c) the right ceiling for this macro's claim?
- **Q4. Whether the 0.1 V, 10 fF, 10 ns, 0.9 V and 5 ns values stay as
  placeholders** or are replaced once #80 and #81 land. This record carries
  them forward only so something is gradable now.
- **Q5. What counts as a "full" DRC/LVS pass** (rows 5a, 5b) while the
  rule deck is partial; and whether a "clean over a partial deck" result may
  be reported at all, and under what label.
- **Q6. Fallback if the restricted range is not ratified.** Should items 2 and
  6 then be graded against the full 15-point grid, where fs/-40 C is already
  known to fail?
- **Q7. Supply.** All committed grids are `VDD` = 1.8 V only. Is a supply
  tolerance band required before item 6 is graded?

## 8. What this record does not do

- It does not edit `retention-refresh-budget.md` or any other ratified file,
  nor `operating-range-decision-PROPOSED.md`.
- It does not claim any row is met; it gives no result, only conditions.
- It does not describe the macro as an SRAM replacement. A gain cell is
  dynamic: retention and refresh are the centerpiece, not a footnote.
- It uses public sources only: the shipped sky130 models, the committed
  netlists and write-ups in this repo, and the public Chipalooza pages cited
  in `docs/chipalooza/challenge-4-proposal.md`.
