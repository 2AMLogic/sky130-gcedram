# Refresh scheduler behavioral model (issue #74, epic #24 item 3)

First digital-partition increment: a parameterised **behavioral** (not
synthesised, not placed) refresh scheduler plus a self-checking testbench for
the deadline invariant. It checks that a controller *can* keep every row inside
the ratified refresh interval of
[`spec/retention-refresh-budget.md`](../../spec/retention-refresh-budget.md)
Section 7 while external accesses compete. `spec/` is not edited.

**Plain statement.** A gain cell is dynamic. Every row must be rewritten about
every 5 us at the worst-case corner and that work competes with external
access; this model quantifies that cost. Nothing here makes the macro an SRAM
replacement.

## Files

| File | Purpose |
|---|---|
| `refresh_sched.v` | scheduler (`N_ROWS`, `T_ROW`, `T_ACC`, `INTERVAL`, `GUARD` parameters, all in clock cycles) |
| `tb_refresh_sched.v` | self-checking testbench; independent per-row age monitor; scenarios 0/1/2 |
| `params.py` | derives `INTERVAL` from the committed retention CSV (not retyped) |
| `run_tests.sh` | iverilog run of all scenarios at both intervals; non-zero exit on any failure |
| `run_mutation.sh` | mutation check: baseline must pass, every broken scheduler must fail |
| `results/` | recorded run output (append-only evidence; add new dated files, never edit) |

## Inputs, by kind

| Input | Kind | Source |
|---|---|---|
| `refresh_interval` = `t_retention / 2` = ~5.03 us (worst case, `sf`/125 C, 2T) | **ratified** (value), 2x margin itself is an ASSUMPTION stated by the spec | spec Sec. 5 and 7; read from [`retention_results.csv`](../../sim/retention/results/retention_results.csv) 2026-08-20 row by `params.py`, floored to **5029 cycles** |
| Newer layout-extracted-`C_SN` interval ~2.75 us (**2751 cycles**) | newer evidence, **not ratified** | CSV 2026-08-25 row (see [`sim/refresh-overhead/README.md`](../../sim/refresh-overhead/README.md)); run as a stress variant only |
| 1 cycle = 1 ns | **ASSUMPTION** | arbitrary time base for converting ns to cycles; not a clock-rate claim |
| `N_ROWS` = 32 | **ASSUMPTION** | array not designed; a value already in the refresh-overhead grid |
| `t_row_refresh_op` = `T_ROW` = 34 cycles | **ASSUMPTION** | the `anchored` scenario of [`refresh_overhead.py`](../../sim/refresh-overhead/refresh_overhead.py); no sense amp or controller circuit exists |
| `T_ACC` = 34 (external op duration) | **ASSUMPTION** | set equal to `T_ROW` |
| Array contents valid after one initialisation sweep at reset; external reads do not restore a cell, writes and refreshes do | **ASSUMPTION** | modelling choice |

## Policy (see header of `refresh_sched.v`)

One non-preemptible op at a time; rows refreshed round-robin; the pointer row
is always the oldest. A refresh is forced ("urgent") when starting an external
access could push the pointer row's refresh past `INTERVAL`
(`age >= INTERVAL - T_ROW - T_ACC - GUARD`); otherwise external requests win.
When no request is pending the scheduler refreshes early ("eager"). Consequence:
refresh occurs as back-to-back **bursts** of about `N_ROWS * T_ROW` cycles, which
dominates the worst-case external stall below. A distributed policy would trade
a lower stall for more complexity; not explored here.

## Testbench

Invariant, checked every cycle by a monitor independent of the DUT (it credits
refreshes and external writes): `age(row) <= INTERVAL` for every row.
Liveness guards stop a vacuous pass (refresh count, external service).
Scenarios: (a) `SCENARIO=0` idle; (b) `1` saturating back-to-back reads
(worst case, no write ever helps); (c) `2` seeded random traffic
(xorshift32, seed `32'h1badcafe`, bursty light/medium/saturating phases,
random read/write and rows). Each runs 12 intervals at the ratified interval
and at the 2751-cycle stress interval.

## Results (`results/run_tests_2026-10-09.txt`, iverilog 13.0)

All six runs PASS. Selected measured values (cycles = ns under the 1 ns
assumption), `N_ROWS`=32, `T_ROW`=`T_ACC`=34:

| Interval | Scenario | min slack to deadline | worst external stall | refresh busy fraction |
|---|---|---|---|---|
| 5029 (ratified) | idle | 1091 | n/a | 28.84 % |
| 5029 | saturating | 25 | 1153 | 22.09 % |
| 5029 | random | 3 | 1119 | 23.43 % |
| 2751 (not ratified) | idle | 1091 | n/a | 65.91 % |
| 2751 | saturating | 22 | 1153 | 40.29 % |
| 2751 | random | 6 | 1153 | 43.25 % |

### Finding: worst-case stall versus the Section 7 overhead figure

The refresh-overhead envelope gives, for these same assumed inputs
(`N_ROWS`=32, 34 ns, 5.03 us), `refresh_bandwidth_overhead` = **21.63 %**
(`sim/refresh-overhead/results/refresh_overhead_results.csv`; 39.54 % for the
2.75 us interval). The scheduler's measured saturated refresh fraction, **22.09 %**
(40.29 %), agrees with the formula to within ~0.5 percentage point (extra from
the scheduling guard and the start-up sweep). The idle fraction is higher
(28.84 %) because the eager policy refreshes earlier than needed; that is
a policy choice, not a requirement.

The formula is an *average*. The worst-case external-access stall measured is
**1153 cycles (~1.15 us) at the ratified interval**, about 34x one external op
and ~23 % of the whole refresh interval: an external request can wait through a
whole 32-row refresh burst plus an op already in flight (1088 + 34 = 1122
cycles, plus a few extra from ops interleaved inside the burst). So "21.6 %
overhead" understates the latency cost; any user of this macro sees ~1.15 us
stalls with this policy. This stall is a result for this *assumed* `N_ROWS` and
`T_ROW`, not a macro specification. Slack of 3 cycles in the random scenario
shows the scheduler's guard is tight, as intended.

## Mutation check (`results/run_mutation_2026-10-09.txt`)

`run_mutation.sh` seds five broken copies of the scheduler; the testbench must
fail each: `never_urgent`, `urgent_ignores_ext_op`, `urgent_late_by_guard`,
`ptr_skips_rows`, `never_refresh`. All five were killed and the baseline passed.
Disabling the eager refresh is deliberately not a mutant: it is an idle-policy
optimisation, equivalent for the deadline invariant.

## Reproduce

```
digital/refresh-scheduler/run_tests.sh       # ~35 s
digital/refresh-scheduler/run_mutation.sh    # ~100 s
```

Needs only `iverilog` (>= 12 style `-g2012`), `vvp` and `python3`.

## CI

CI: `.github/workflows/digital-regressions.yml` runs this under the pinned
Icarus Verilog (see [`digital/ci/README.md`](../ci/README.md)). Behavioral
regression only; not physical CDC, synthesis, timing or macro sign-off.

## Not covered

Synthesis, timing, sense amp, bitline/read-disturb effects, multi-bank or
row-parallel refresh, retention variation across the array, and the real
`N_ROWS`/`T_ROW` (all gated on array/periphery design).
