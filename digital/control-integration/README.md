# SPI control + refresh scheduler integration (issue #93, epic #24 items 3-4)

This directory joins the #83 SPI slave to the #74 refresh scheduler through a
proposed configuration-transfer contract
([`CONTRACT.md`](CONTRACT.md)). It contains a combined **behavioral** adapter
and a self-checking integration bench. Nothing here is synthesised, timed,
CDC-signed-off, or ratified, and `spec/` is not edited.

**Plain statement.** A gain cell is dynamic. This control path sets how often
rows are refreshed, and it reports when the retention guarantee does **not**
hold: refresh disabled, or (re)initialisation not yet complete. Nothing here
makes the macro an SRAM replacement.

## Why an adapter, not a wire

`refresh_sched.v` fixes `INTERVAL` at elaboration and has no enable or
forced-sweep input. Wiring the SPI register outputs straight to it cannot
change the interval. It would also give no safe command crossing, and it
would accept intervals the scheduler cannot meet: the #83 floor is a
1-cycle placeholder, while the scheduler needs at least
`N_ROWS*T_ROW + T_ACC + GUARD`.

## Files

| File | Purpose |
|---|---|
| `CONTRACT.md` | proposed contract: transfer, frame spacing, interval range and transition, enable/validity, START_SWEEP busy/completion, status bits, limits |
| `refresh_sched_rt.v` | runtime-configurable scheduler derived from #74: applied interval register, enable, forced/re-init sweeps, `refresh_ok`, `data_lost` |
| `cfg_xfer.v` | behavioral SPI-to-`clk` snapshot transfer (2-flop `cs_n` synchroniser, whole-bundle capture, toggle-based START_SWEEP, `pending`) |
| `gc_ctrl_top.v` | `spi_slave` + `cfg_xfer` + `refresh_sched_rt`; BUSY and XSTATUS wiring; SPI floor = scheduler feasibility floor |
| `tb_ctrl_integ.v` | integration bench: real SPI frames, foreground traffic, independent per-row monitors (header lists M1-M5) |
| `tb_equiv.v` | lockstep bench: `refresh_sched_rt` with the config port idle vs the unchanged #74 `refresh_sched` |
| `params.py` | `INTERVAL` via `../refresh-scheduler/params.py` (retention CSV). `N_ROWS`/`T_ROW`/`T_ACC`/`GUARD` read from `refresh_sched.v` defaults. `MIN_INTERVAL` computed in Python. Nothing retyped |
| `sim_one.sh` | one bench run (basis, SPI half period, phase, traffic, negative-control flag; `SRC_DIR` for mutants) |
| `run_tests.sh` | everything below, serially; non-zero exit on any failure (`--no-mutation` skips step 4) |
| `run_mutation.sh` | fault injection: 12 broken RTL copies, each must fail the bench |
| `results/` | dated run output (append-only; add new files, never edit old ones) |

Changes outside this directory are additive and default-off. `spi_slave.v`
gained `MIN_INTERVAL` (default 1) and `XSTAT_EN` (default 0). With both
defaults the standalone #83 suite gives the same results as before (59/59
checks at both bounds, 8/8 mutants killed): see
`../spi-control/results/*_issue93.txt`. The #74 scheduler is unchanged and its
suite was re-run (`../refresh-scheduler/results/run_tests_2026-10-09_issue93.txt`).

## Inputs, by kind

| Input | Kind | Source |
|---|---|---|
| `INTERVAL` = 5029 cycles | ratified value (the 2x margin is an ASSUMPTION stated by the spec) | `params.py ratified` via [`../refresh-scheduler/params.py`](../refresh-scheduler/params.py), [`spec/retention-refresh-budget.md`](../../spec/retention-refresh-budget.md) Sec. 7 |
| `INTERVAL` = 2751 cycles | newer layout-extracted `C_SN` evidence, **not ratified**, stress variant | `params.py extracted` |
| `N_ROWS`=32, `T_ROW`=34, `T_ACC`=34, `GUARD`=2 | **ASSUMPTION** (#74) | `refresh_sched.v` parameter defaults |
| `MIN_INTERVAL` = 1124 cycles | derived: #74 feasibility constraint | `params.py` (Python) and `gc_ctrl_top.v` (Verilog), cross-checked by the bench |
| 1 cycle = 1 ns, single `clk`, one `rst_n` | **ASSUMPTION** | CONTRACT.md Sec. 1 |
| frame spacing: `cs_n` high and low >= 4 `clk` periods | **ASSUMPTION** (master obligation) | CONTRACT.md Sec. 2 |
| START_SWEEP refused while BUSY; DATA_LOST sticky to reset; shortening without BUSY | **ASSUMPTION** (protocol choices) | CONTRACT.md Sec. 3-5 |

## What the bench does

Every run drives real 16-bit mode-0 SPI frames. The master's timeline is set
by its own `#` delays, with the SPI half period and phase offset as
parameters, so frame edges fall at many positions relative to `clk`. Five
configurations are run at each sourced interval:

| `sclk` half period | phase | relationship | traffic |
|---|---|---|---|
| 3.7 ns | 0.13 ns | `sclk` slower than `clk`, arbitrary phase | saturating reads |
| 0.37 ns | 0.61 ns | `sclk` faster than `clk` | saturating reads |
| 0.5 ns | 0 | same rate, SPI edges coincide with `clk` edges | saturating reads |
| 10 ns | 0.5 ns | slow SPI (~340-cycle frames) | saturating reads |
| 1.3 ns | 0.87 ns | arbitrary | seeded random reads/writes (#74 generator) |

Each run covers the following:

1. Reset defaults, the init sweep, and XSTATUS.
2. Infeasible values are rejected with ERR_RANGE and never applied:
   `MIN_INTERVAL-1`, `INTERVAL+1`, 0.
3. The floor value is accepted, and the bench then runs at it under traffic.
4. No partial commits. A low byte alone changes nothing. A rejected pair
   changes nothing. The shadow is not poisoned.
5. Interval changes under traffic, both up and down, to the floor and to
   `INTERVAL-1`.
6. Interval shortening near a deadline, 14 times. The SPI commit edge is held
   until the oldest row is between 40 cycles before and 30 cycles after the
   scheduler's urgent threshold, then commits to `MIN_INTERVAL` or to the
   midpoint.
7. Forced sweep: BUSY is visible after acceptance and clears only after
   completion. START_SWEEP while busy is refused with ERR_BUSY. Back-to-back
   sweeps.
8. Back-to-back configuration and command frames at the minimum spacing.
9. Disable. The bench waits past the deadline, then issues a sweep while
   disabled, changes the interval while disabled, and re-enables. It checks
   the re-init BUSY, REFRESH_OK, and the sticky DATA_LOST. A quick
   disable/enable pair follows.
10. Reset during transfer: reset mid-frame; a reset pulse inside a frame;
    reset after a commit but before the snapshot is applied; reset during a
    forced sweep, after which no phantom sweep may occur.

The monitors (M1-M5 in the `tb_ctrl_integ.v` header) run every cycle and do
not use the DUT's internal ages or effective deadline.

* M1: per-row deadline against the SPI-committed interval, with the old value
  allowed for `T_SETTLE` after a shortening, plus the ratified bound.
* M2: every row re-armed and REFRESH_OK set by `T_REARM` after a reset or
  re-enable.
* M3: one completion per accepted START_SWEEP within `T_SWEEP`, with every row
  refreshed in between.
* M4: REFRESH_OK only after full (re)initialisation coverage; no
  REFRESH_OK && !DATA_LOST while any row is past its deadline; DATA_LOST set
  by a disable and only by one.
* M5: the applied configuration equals the committed one within `T_XFER`, and
  each applied pair is one the SPI slave actually held.

## Results (`results/run_tests_2026-10-09.txt`, iverilog 13.0)

All six lockstep-equivalence runs show 0 mismatches. Their refresh and
external-op counts are identical to the #74 recorded results (for example,
ratified saturating: 392 / 1332). All 10 integration runs PASS (95 sequence
checks each, plus the per-cycle monitors). Both negative controls FAIL as
required, each with 2 LOST START_SWEEP. All 12 mutants are killed.

Selected measured values (cycles; `N_ROWS`=32, `T_ROW`=`T_ACC`=34):

| Interval basis | worst observed shortening transition | stated bound `T_SETTLE` | min slack vs committed deadline | min slack vs `INTERVAL` (saturating / random) |
|---|---|---|---|---|
| 5029 (ratified) | 1157 | 1163 | 5 | 25 / 5 |
| 2751 (not ratified) | 1155 | 1163 | 5 | 22 / 6 |

The shortening transition sits close to its bound, as expected: after a
shortening to the floor, the scheduler must finish one in-flight external op
and then refresh all 32 rows back to back, at `T_ROW+1` cycles each. The
transition is therefore a real ~1.16 us window under these assumptions.
During that window only the previous, longer interval is guaranteed. A
minimum slack of 5 cycles against the committed deadline shows the guard is
tight, which matches the #74 finding.

## Fault injection (`run_mutation.sh`)

Each mutant must make the bench fail. The comments give the expected reason.

| Mutant | Class | Killed by |
|---|---|---|
| `sweep_toggle_dropped` | lost command | BUSY not seen, LOST START_SWEEP |
| `capture_on_cs_fall` | lost/late config | NOT APPLIED |
| `busy_ignores_sweep` | lost command (second START accepted mid-sweep) | ERR_BUSY missing, LOST START_SWEEP |
| `floor_not_passed_to_spi` | infeasible interval accepted | below-floor rejection check |
| `urgent_ignores_runtime_interval` | unsafe interval transition | deadline VIOLATION after a shortening |
| `shortening_ignored` | unsafe transition / lost config | NOT APPLIED |
| `ptr_restart_on_cfg` | unsafe transition (round-robin order broken on reconfiguration) | deadline VIOLATION |
| `disable_not_applied` | lost command | NOT APPLIED |
| `reinit_skipped` | invalid data reported valid | REFRESH_OK before re-init coverage |
| `ok_ignores_init` | invalid data reported valid after reset | REFRESH_OK low-after-reset check |
| `disable_not_flagged` | unnoticed invalid data | DATA_LOST flag check |
| `sweep_done_early` | incomplete sweep | coverage check |

Not listed as mutants, because they are equivalent under the contract:

* Dropping `pending` from BUSY. The frame spacing already keeps the next
  commit later than the snapshot application. `pending` is belt-and-braces.
* Removing the scheduler-side floor check (`cfg_reject`). It cannot be reached
  behind the SPI floor.
* Capturing the bundle without the synchroniser. Simulation has no
  metastability, which is exactly why this bench does not establish physical
  CDC safety.

## Reproduce

```
digital/control-integration/run_tests.sh                 # ~11 min, serial
digital/control-integration/run_tests.sh --no-mutation   # ~5 min
digital/control-integration/run_mutation.sh              # ~6 min
```

This needs only `iverilog` (`-g2012`), `vvp` and `python3`. It is not wired
into CI, for the same reason as #74: CI has no Verilog simulator.

## Not covered

Physical CDC safety and metastability. Synthesis, timing, and the maximum
`sclk` rate. The real `N_ROWS`/`T_ROW`/`T_ACC`. A memory datapath, and with it
any validity recovery finer than "reset clears DATA_LOST". Multi-bank
refresh. Production or ratified specification. The worst-case
external-access stall is unchanged from #74 and is not re-measured here.
