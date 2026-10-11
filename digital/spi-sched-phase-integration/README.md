# SPI-configured scheduler -> phase-sequencer integration (behavioral, PROPOSED)

Issue #146, epic #24 items 3, 4 and 6. One executed control path from SPI
configuration to row strobes: real SPI frames configure the single runtime
scheduler inside `gc_ctrl_top` (`spi_slave` -> `cfg_xfer` -> `refresh_sched_rt`,
all unchanged), whose operation interface drives the unchanged launch adapter
and `phase_seq`. The effective duration and decision-cycle guard calculations of
#138 (`../sched-phase-integration/COUPLED_REPORT.md`) are applied to this path,
including the SPI feasibility floor. The macro is a dynamic gain-cell array;
this is not an SRAM controller.

**Scope: behavioral simulation only (Icarus Verilog).** No physical CDC or
metastability evidence, no synthesis, no timing sign-off, no maximum `sclk`
rate, no analog restoration or SPICE, and no change to any ratified value
(`INTERVAL` 5029 ratified, 2751 unratified stress variant) or to any production
module. 1 cycle = 1 ns is an ASSUMPTION inherited from the scheduler.

| File | Role |
|---|---|
| `spi_sched_phase_top.v` | wrapper: `gc_ctrl_top` -> `launch_adapter` -> `phase_seq`. Budgets derived exactly as `coupled_top.v` (`T_ROW = D_REF+LAT`, `T_ACC = max(D_RD,D_WR)+LAT`, `GUARD_C = GUARD+N_ROWS+1`) and passed to `gc_ctrl_top`, so the SPI slave's commit floor is `N_ROWS*T_ROW + T_ACC + GUARD_C` |
| `tb_spi_sched_phase.v` | SPI master with independently timed `sclk`, saturated foreground traffic, independent scoreboard, negative-control hooks |
| `run_tests.sh` | positive matrix (2 interval bases, 5 phase-duration sets, 5 SPI/clk relationships), infeasible-set rejection, negative controls |
| `run_mutation.sh` | 20 RTL mutants (config path and timing) plus 4 adapter faults, baseline first; each killed with the gate on and, for value mutants, with the pre-traffic gate bypassed |
| `results/` | dated, append-only logs |

`../sched-phase-integration/coupled_top.v`, `tb_coupled.v` and the #135
harness are unchanged and stay as controls. `coupled_top.v` still carries its
tied-off `gc_ctrl_top` (floor comparison only); this directory adds the missing
transactions. It reuses `coupled_params.py` for the Python cross-derivation.

## Independent scoreboard

All checks use sampled port events at the falling clock edge and the bench's
own model of what it sent over SPI. The DUT's `refresh_ok`, `sweep_done`,
`busy` and `data_lost` are cross-checked against it, never used to define a
completion. A scheduler dispatch (`op_busy` rising) is not a refresh.

* A refresh is complete when the **sequencer** `busy` falls; the row timestamp
  and the kind (from the observed `pre_en`/`rwl_sel`/`wwl_en` profile) and row
  (`row_q`) come from there. Per-row age is measured from that timestamp.
* Exactly-once launch: each scheduler launch yields exactly one sequencer
  execution `LAT` (=1) cycles later (`DROPPED_LAUNCH`, `SPURIOUS_EXEC`,
  `START_IGNORED`, `LAUNCH_OVERRUN`); stable row/kind, phase ordering,
  non-overlapping strobes, per-phase and total durations (`PROFILE`,
  `SEQ_LENGTH`, `ROW_UNSTABLE`, `PHASE_ORDER`, `KIND_MISMATCH`).
* Budget: the scheduler must not declare an operation finished while the
  sequencer is busy (`BUDGET_UNDER`) and its busy length equals the Python
  `T_ROW`/`T_ACC` (`BUDGET_VALUE`).
* Foreground: each accepted request is launched with the same row and
  read/write kind (`ACCESS_*`); refresh rows are round-robin from row 0
  (`REFRESH_ORDER`).
* Deadlines: per-row age <= SPI-committed interval (the previous interval is
  allowed for `T_XFER + T_SETTLE` after a shortening, `CONTRACT.md` Sec. 3) and
  <= the ratified `INTERVAL` always (`DEADLINE`, `DEADLINE_HARD`).
* Sweeps: each START_SWEEP accepted by the SPI slave (observed `sweep_tog`)
  refreshes every row (sequencer completions after acceptance) within
  `T_SWEEP` and gives exactly one `sweep_done`; reset cancels (`SWEEP_*`).
* Enable/validity: `refresh_ok` only after every row completed a refresh since
  the last (re-)initialisation (`OK_EARLY`); re-enable/reset liveness
  (`REARM`); no refresh launch long after a disable commit unless a sweep is
  outstanding (`REFRESH_WHILE_DISABLED`); sticky `data_lost` (`DATA_LOST_FLAG`).
* Configuration: SPI-committed vs applied pair after `T_XFER` (`NOT_APPLIED`),
  only pairs the SPI slave actually held are ever applied (`PARTIAL`),
  `cfg_reject` never fires (the SPI floor filters first).
* Pre-traffic gate (`CHECK_CFG=1`): scheduler `T_ROW`/`T_ACC` not below the
  Python values, and the floors of `gc_ctrl_top`, `spi_slave` and
  `refresh_sched_rt` equal the Python `MIN_INTERVAL`. `CHECK_CFG=0` bypasses it
  so the negative controls show the dynamic scoreboard alone fails.

## Stimulus (one program, every run)

Real 16-bit SPI frames (mode 0) with `sclk`/`cs_n` timed independently of `clk`
(`SCLK_HALF_PS`, `PHASE_PS`), `cs_n` high 4.25 clk between frames (the
documented frame-spacing obligation), under saturated foreground traffic
(`req_valid` always re-asserted, random read/write rows; the 10 ns half-period
run uses saturated reads).

1. Reset defaults, initialisation sweep through the sequencer.
2. Interval writes: below floor (floor-1, also while running at the floor),
   floor, floor+1, maximum, maximum+1, zero, mid; each checked by SPI readback,
   `ERR_RANGE`, XSTATUS `CFG_REJECT`, and `ivl_eff` after `T_XFER`.
3. No partial commit (low byte only, rejected pair, poisoned shadow).
4. Shortening to the floor / mid with the commit held until the oldest row is
   0..40 cycles before (or already past) its urgent threshold.
5. Configuration arriving while the sequencer is busy: commit released at
   chosen offsets inside a REFRESH, WRITE and READ.
6. START_SWEEP: busy visible, refused while busy (`ERR_BUSY`), interval write
   and disable while the sweep runs (sweep completes), sweep while disabled
   (does not set `refresh_ok`), re-enable.
7. Enable/disable with disabled durations 0, 5, 30, 300, 800, 2000 cycles
   (re-enable sweep, `refresh_ok`, sticky `data_lost`), and at the floor.
8. Reset mid-op, inside a sweep, at the floor, while disabled, in a refresh
   at a fixed phase offset, and inside an SPI frame; defaults and
   re-initialisation checked each time.
9. Soak at the floor and at the maximum.

## Negative controls (`run_tests.sh`, first `FINDING` line asserted)

| Control | Expected first finding |
|---|---|
| adapter drops launch 7 (a refresh) / 60 (an access) / 20 (gap1) | `DROPPED_LAUNCH` |
| adapter wrong row / stretched start | `ROW_UNSTABLE` / `START_IGNORED` |
| `T_ROW` or `T_ACC` one below the derived value (anchored, gap1, mismatch), stale 34 | gate on: `CONFIG_REJECT`; gate bypassed: `BUDGET_UNDER` |
| legacy floor (decision cycle dropped, `GUARD_X=2`) | gate on: `CONFIG_REJECT`; bypassed: SPI accepts an infeasible interval (readback/`ERR_RANGE` finding) |
| set `huge` (floor above the ratified interval) | Python and elaboration reject |

## Behavioral CDC assumptions retained (from `../control-integration/CONTRACT.md`)

* `cs_n` crosses through a two-flop synchroniser; the SPI-domain bundle
  `{refresh_en, interval, sweep_tog}` is quasi-static between `cs_n` rises and is
  captured whole on the synchronised rise; commit-to-applied at most 4 clk
  edges (bench bound `T_XFER` = 6).
* Master obligation: `cs_n` high >= 4 clk and low >= 4 clk per frame.
* The status returned to the SPI domain (`busy`, XSTATUS) is assumed already
  synchronised. Icarus has no metastability model; none of this is physical
  CDC evidence. The bench never violates the spacing rule (that negative
  control lives in `../control-integration`).
* The `cfg_xfer.pending` busy bridge cannot be mutation-tested at the SPI
  boundary (equivalent mutant under the spacing rule; see `run_mutation.sh`).

## Reproduce

Needs the pinned Icarus Verilog (`v13_0`, `../ci/install_iverilog.sh`, see
[`../ci/README.md`](../ci/README.md)) and `bash`/`python3`. Serial, no `-j`:

```bash
digital/spi-sched-phase-integration/run_tests.sh      # ~5 min
digital/spi-sched-phase-integration/run_mutation.sh   # ~7 min
# one case with the full program:
MATRIX="ratified anchored 3700 130 3 0" digital/spi-sched-phase-integration/run_tests.sh --no-negative
```

Wired into `../ci/run_digital_regressions.sh` as `spi-sched-phase-tests` and
`spi-sched-phase-mutation`.

## Results (2026-10-11)

Logs: [`results/run_tests_2026-10-11.txt`](results/run_tests_2026-10-11.txt),
[`results/run_mutation_2026-10-11.txt`](results/run_mutation_2026-10-11.txt),
[`results/versions_2026-10-11.txt`](results/versions_2026-10-11.txt). Simulator:
`Icarus Verilog version 13.0 (stable) (v13_0)` (`vvp` same), Python 3.12.3, Ubuntu,
repo base `fb02960`. This local build reports the `v13_0` tag rather than the
`(dfeee90)` commit suffix of the CI-built pin; CI uses `ci/install_iverilog.sh`.

* `run_tests.sh`: ALL PASS, 5 min 11 s serial. 11 positive runs (all
  `TB_RESULT: PASS`, 0 findings), the infeasible set `huge` rejected at both
  bases, 17 negative-control runs each failing for the asserted reason.
* `run_mutation.sh`: MUTATION CHECK PASS, 2 min 48 s, baseline passes, all 20
  RTL mutants and 4 adapter faults killed (gate on, and gate bypassed for the value
  mutants). Findings the mutants trigger include `CFG_REJECT`, `NOT_APPLIED`,
  `DATA_LOST_FLAG`, `REARM`, `OK_EARLY`, `REFRESH_WHILE_DISABLED`,
  `SWEEP_DONE_BEFORE_ROWS`, `SWEEP_ACCEPT_WHILE_PENDING`, `DEADLINE`,
  `BUDGET_UNDER`, `DROPPED_LAUNCH` and SPI readback/status checks.

Parameters: `N_ROWS` 32; scheduler `GUARD` 2, effective `GUARD_C` 35; ratified
`INTERVAL` 5029 (extracted 2751); anchored phases PRE 2 / SENSE 10 / WB 20 /
GUARD 2 / GAP 0 give `D_REF` 34, `D_RD` 14, `D_WR` 22, `T_ROW` 35, `T_ACC` 23,
`MIN_INTERVAL` 1178 for both bases (floor identical in the SPI slave,
`gc_ctrl_top` and the scheduler). `T_XFER` bench bound 6, `T_SWEEP` =
`T_XFER` + `T_SETTLE` (1184 anchored).

Behavioral timing observations (anchored; ranges over the logged runs, cycles).
These are behavioral measurements, not margins of a physical design:

| Quantity | Observed | Bound used |
|---|---|---|
| sequencer busy length read / write / refresh | 14 / 22 / 34 (= Python `D_*`) | exact |
| scheduler busy length access / refresh | 23 / 35 (= `T_ACC`, `T_ROW`) | exact |
| launch -> sequencer busy | 1 (min = max) | `LAT` = 1 |
| scheduler fall - sequencer fall (read / write / refresh) | 8 / 0 / 0 (never negative) | >= 0 |
| SPI commit -> applied | at most 4 | `T_XFER` 6 |
| worst per-row age / ratified bound | 4993 / 5029 (2712 / 2751 extracted) | `INTERVAL` |
| minimum deadline slack (against the committed interval) | 26 anchored; 11 in the `fast` set | 0 |
| START_SWEEP accept -> `sweep_done` | up to 1178 anchored | `T_SWEEP` 1184 |
| longest shortening transition (a row above the new value) | up to 1177 anchored | `T_XFER`+`T_SETTLE` 1184 |

The sweep and shortening transitions come within 6 to 9 cycles of their
contract bounds at the floor; they do not exceed them. No check was relaxed and
no deadline changed. The 10 ns half-period case uses read-only saturated
traffic, so it reports no write executions.
