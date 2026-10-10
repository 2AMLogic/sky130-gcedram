# Coupled scheduler/sequencer configuration (PROPOSED, behavioral)

Issue #138 (follow-up to #135, epic #24). Adds a **separate, parameter-coupled**
integration configuration next to the #135 characterization harness. The
fixed-duration scheduling policy, the standalone scheduler defaults
(`T_ROW = T_ACC = 34`), the historical conflict harness (`sched_phase_top.v`,
`tb_sched_phase.v`, `TIMING_REPORT.md`, `results/run_*_2026-10-10.txt`) and all
production modules are unchanged; their suites still run and still show the
SKEW / LOST conflicts they were written to show. No phase ordering changes, no
analog restoration claim, no spec change. 1 cycle = 1 ns and the provisional
row count (`N_ROWS` = 32) remain ASSUMPTIONS. A gain-cell macro is dynamic; this
is a refresh/sequencer timing check, not an SRAM-style controller.

Provenance: Icarus Verilog 13.0 (`v13_0`, as pinned by `../ci/install_iverilog.sh`),
Python 3 for `coupled_params.py`; intervals from
`../control-integration/params.py` (retention CSV: ratified 5029, extracted
stress variant 2751 cycles). Logs:
[`results/coupled_run_tests_2026-10-10.txt`](results/coupled_run_tests_2026-10-10.txt),
[`results/coupled_run_mutation_2026-10-10.txt`](results/coupled_run_mutation_2026-10-10.txt).

## 1. Derivation (`coupled_top.v`, cross-checked by `coupled_params.py` and the bench)

```
D_REF = PRE + SENSE + WB + GUARD + 3*GAP        D_RD = PRE + SENSE + GUARD + 2*GAP
D_WR  = WB + GUARD + GAP                        D_ACC = max(D_RD, D_WR)
LAT   = 1   launch/registration latency (measured in #135, re-measured every run)
T_ROW = D_REF + LAT          T_ACC = D_ACC + LAT
GUARD_C = GUARD + N_ROWS + 1
MIN_INTERVAL = N_ROWS*T_ROW + T_ACC + GUARD_C = N_ROWS*(T_ROW+1) + (T_ACC+1) + GUARD
T_SETTLE (shortening bound) = (T_ACC+1) + N_ROWS*(T_ROW+1) + GUARD     (= MIN_INTERVAL)
```

Exact sampled-edge accounting (measured, not assumed): the scheduler's op_busy
is visible from launch cycle L; phase_seq busy rises at L+1 (`LAT`), falls at
L+1+D (its `done`); the scheduler's busy fall and `op_done` are at L+T. With
`T = D + LAT` they coincide for the longest operation (REFRESH, and the longer
of READ/WRITE) and the shorter access op completes the scheduler budget later
(`sched_minus_seq_done` below). `T = D` (derived minus one) fails in every set
(negative controls), so `+LAT` is both necessary and sufficient in all five sets
tested, not assumed.

**Finding (the #74 floor is not legal for these durations).** `refresh_sched_rt`
spends one decision cycle between operations, so a saturated back-to-back sweep
takes `N_ROWS*(T_ROW+1)`, not `N_ROWS*T_ROW`. The #74/#93 floor
`N_ROWS*T_ROW + T_ACC + GUARD` therefore only holds while `T_ACC + GUARD >= N_ROWS`
(true for the standalone 34/34, false for the coupled `anchored` T_ACC 23). The
bench measured a row-deadline miss of up to 6 cycles at the old floor 1145 (anchored,
saturated traffic, first run of this work; row 0 age 1146..1151 > 1145) and the
`legacy_floor` negative control reproduces the defect class. The coupled
configuration therefore passes `GUARD_C` as the scheduler's existing `GUARD`
parameter (conservative; thresholds shrink identically, RTL untouched), giving
a floor equal to the shortening bound. `gc_ctrl_top`/`spi_slave` take the same
`GUARD_C` and effective durations, so the SPI floor follows.

## 2. Results (both interval bases, 4 scenarios each; all PASS)

Scenario 1 (saturating READ/WRITE, 96 REFRESH launches, ratified interval 5029):

| Set (cycles) | T_ROW / T_ACC | floor = shorten bound | sched minus seq done, REFRESH | READ / WRITE | launches executed | next-launch margin (min) | min deadline slack scen 1 / scen 2 (floor) |
|---|---|---|---|---|---|---|---|
| `anchored` 2+10+20+2 | 35 / 23 | 1178 | 0 | +8 / 0 | all | 1 | 38 / 27 |
| `gap1` +GAP 1 | 38 / 24 | 1275 | 0 | +7 / 0 | all | 1 | 57 / 28 |
| `full_read_pulse` 2+20+20+2 | 45 / 25 | 1500 | 0 | 0 / +2 | all | 1 | 48 / 29 |
| `fast` 1+5+5+1 | 13 / 8 | 459 | 0 | 0 / +1 | all | 1 | 2402 / 12 |
| `mismatch` 2+10+40+2 | 55 / 43 | 1838 | 0 | +28 / 0 | all | 1 | 70 / 47 |

(The #135 conflict matrix for the same sets: anchored margin 0 and 1-cycle skew;
gap1 / full_read_pulse / mismatch lost 48 of 96 refresh launches. Here: zero
rejected launches, zero lost, REFRESH completes on the same cycle as the
sequencer, margin +1.) All 40 positive runs (2 bases x 5 sets x 4 scenarios)
pass; the extracted base (INTERVAL 2751) passes with the same floors;
minimum slack at the floor (scenario 2) is 27, 28, 29, 12, 36 cycles for the five sets in the table order. Scenario 2 exercises refused snapshots (floor-1 and
INTERVAL+1), floor accepted, shortening under saturated traffic (4 per run;
longest observed transition above the new interval 1167 of 1178 cycles
anchored, 1272/1275 gap1, 1491/1500 full_read_pulse, 451/459 fast,
1823/1838 mismatch), 2 forced sweeps, disable, re-enable, sweep during a refresh;
scenario 3 resets mid-access, mid-refresh and after a shortening.

Independent monitors (credit only from the executed `phase_seq.done`): row
deadline (previous interval allowed for `T_SETTLE` after a shortening, ratified
bound always), `refresh_ok`/`sweep_done` only after every row executed a
REFRESH, re-arm within `T_SETTLE+4` of reset / re-enable, sweep liveness,
configuration model (floor recomputed in the bench), no launch into a busy
sequencer, any `start_ignored` is a VIOLATION (a rejected launch can never pass
as a refreshed row).

## 3. Rejections and negative controls (`run_coupled.sh`)

* Infeasible combination (`huge`, WB 150: floor 5468 above both intervals):
  `coupled_params.py` exits non-zero and the bench prints
  `CONFIG_REJECT: infeasible` and ends `TB_RESULT: FAIL` before any traffic (not bypassable).
* Underbudgeted budgets (derived minus one for T_ROW and for T_ACC; the stale
  hard-coded 34 for gap1 / full_read_pulse / mismatch; the #74 guard without the
  decision cycle for anchored / full_read_pulse): each FAILS through the
  pre-traffic gate (`CONFIG_REJECT`) and, with the gate bypassed
  (`CHECK_CFG=0`), through the dynamic monitors alone (`SCHEDULER COMPLETES
  WHILE SEQUENCER STILL BUSY`, `applied interval differs from model`).

## 4. Mutation results (`run_coupled_mutation.sh`: 12 mutants + 2 adapter mutants, all killed)

Premature completion: scheduler completes one cycle early; sequencer phases
longer than the budget (SENSE+1, GUARD+1); derivation drops the latency;
derivation ignores the WRITE length. Ignored launches: adapter drops a refresh
and an access launch; sequencer silently ignores REFRESH starts. Stale
feasibility wiring: scheduler floor hard-coded (anchored, fast), `gc_ctrl_top`
floor hard-coded, SPI floor not passed, decision guard stale, urgent threshold
hard-coded to the 34-cycle defaults. Scheduler- and top-level mutants are killed
by the gate and (scheduler-level) by the dynamic monitors alone. The
`gc_ctrl_top`/SPI floor mutants are caught by the gate only: the SPI path is
instantiated for its elaborated floor but not driven with SPI frames here.

## 5. Not established

SPI-driven coupled traffic (the #93 bench still runs the standalone 34/34
defaults and still passes); a completion-driven scheduler (deferred larger
redesign); reset-interruption recovery (#135 F4); any analog restoration,
release-order, CDC, synthesis or timing sign-off claim. The raised floor
(1178 vs 1124 cycles) is a behavioral result for these ASSUMED durations only.
