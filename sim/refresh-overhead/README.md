# Refresh-overhead envelope (issue #59, part of #24 item 3)

Evaluates the ratified formula of
[`spec/retention-refresh-budget.md`](../../spec/retention-refresh-budget.md)
Section 7,

```
refresh_bandwidth_overhead = (N_rows * t_row_refresh_op) / refresh_interval
```

over `N_rows` = 4 .. 1024 (powers of two) x four `t_row_refresh_op`
scenarios, at the worst-case corner (`sf`, 125 C). **This is a refresh-cost
envelope, not a macro claim.** No ngspice is run; `spec/` is not edited.

**Plain statement.** A gain cell refreshed every ~5 us is a very different
proposition from SRAM: SRAM holds statically, whereas here every row must be
rewritten thousands of times per millisecond and that work competes with
external access. Nothing below makes this macro an SRAM replacement.

## Inputs, by kind

| Input | Kind | Source |
|---|---|---|
| `t_retention` (worst case, `2T`, `sf`/125 C) | read from CSV, not retyped | [`sim/retention/results/retention_results.csv`](../retention/results/retention_results.csv) (chain: [`sim/retention/README.md`](../retention/README.md)) |
| Safety margin 2x, `refresh_interval = t_retention / 2` | **ASSUMPTION** (spec Section 7) | spec |
| `t_row_refresh_op` phases (precharge, sense, write-back pulse, bl-release guard) | **ASSUMPTION** | durations borrowed from deck settings in [`sim/bitcell-transient`](../bitcell-transient/README.md) (20 ns write / read pulse) and [`sim/loaded-column`](../loaded-column/README.md) (2 ns precharge lead, `t_sense` 10 ns, 2 ns bl release); those are themselves declared test choices, and no refresh controller or sense amp exists |
| `N_rows` | **ASSUMPTION** | array not designed |

The retention CSV is append-only and has two `2T-min` worst-case rows, so
both are evaluated: the 2026-08-20 row (ASSUMED `C_SN`, 10.06 us -> 5.03 us
interval; **the value the spec ratifies**) and the later 2026-08-25 row
(layout-**extracted** `C_SN`, 5.50 us -> 2.75 us interval; newer evidence the
spec does not yet reflect). Do not read the second as a ratified value.

## `t_row_refresh_op` scenarios (all ASSUMPTION; phases in the script)

| Scenario | precharge | sense | write-back pulse | guard | total |
|---|---|---|---|---|---|
| `fast` | 1 | 5 | 5 | 1 | 12 ns |
| `anchored` | 2 | 10 | 20 | 2 | 34 ns |
| `full_read_pulse` | 2 | 20 | 20 | 2 | 44 ns |
| `slow` | 5 | 25 | 50 | 5 | 85 ns |

`fast` is not credible without a boosted wordline: bitcell-transient shows
short plain-1.8 V write pulses cap the written level.

## Break-even `N_rows` (overhead reaches the threshold)

Interval 5.03 us (ratified, ASSUMED `C_SN`):

| Scenario | t_row | 100 % (cannot refresh in time) | 25 % | 10 % |
|---|---|---|---|---|
| fast | 12 ns | 419 | 105 | 42 |
| anchored | 34 ns | 148 | 37 | 14.8 |
| full_read_pulse | 44 ns | 114 | 28.6 | 11.4 |
| slow | 85 ns | 59 | 14.8 | 5.9 |

Interval 2.75 us (extracted `C_SN`, newer evidence):

| Scenario | t_row | 100 % | 25 % | 10 % |
|---|---|---|---|---|
| fast | 12 ns | 229 | 57 | 23 |
| anchored | 34 ns | 81 | 20 | 8.1 |
| full_read_pulse | 44 ns | 62.5 | 15.6 | 6.3 |
| slow | 85 ns | 32 | 8.1 | 3.2 |

Reading: with the deck-anchored 34 ns, a 64-row array at the ratified
interval already spends ~43 % of bandwidth on refresh, and a 128-row array
~87 %; staying within 10 % needs <= 14 rows (8 as a power of two). Exact
values (plus the largest power-of-two row count under each threshold) are in
`results/refresh_overhead_breakeven.csv`; the full grid is in
`results/refresh_overhead_results.csv` (`overhead_pct`, `feasible_lt_100pct`).
Every column carrying a non-measured input has `_ASSUMPTION` in its name.

## Which decision consumes this

The later **macro row-count decision** (array/periphery design, #24 items 1-3,
refresh controller) is the consumer: it bounds the row count and row-refresh
time it can afford. Row-parallel or banked refresh would change the formula's
form and is out of scope here.

## Reproduce

```
python3 sim/refresh-overhead/refresh_overhead.py
python3 sim/refresh-overhead/test_refresh_overhead.py
```

Re-running appends only keys not already present; existing rows are never
rewritten (append-only evidence).

## Appended record: measured `t_row_refresh_op` (issue #110)

The scenarios above are unchanged (their phases remain ASSUMPTION). A later,
separate record feeds the **measured** slowest-corner value from
[`sim/refresh-op`](../refresh-op/README.md) into the same Section 7 formula:
`python3 -I sim/refresh-overhead/eval_measured_t_row.py sim/refresh-op/results/refresh_op_summary_<RUN_ID>.json`
appends to `results/refresh_overhead_measured.csv` (new file; the two CSVs
above are not touched). Results and caveats are in the `refresh-op` README.
