# Analog phase-control contract (PROPOSED)

Status: **PROPOSED** (issue #108). Nothing here is ratified and `spec/` is not
edited. This defines the strobes a controller would give the (not yet
designed) analog array periphery, and a behavioral sequencer
([`phase_seq.v`](phase_seq.v)) that produces them. The macro is a **dynamic**
gain-cell array: **refresh is mandatory** and every row must be rewritten
within the retention-derived interval. This is not an SRAM interface and not
a drop-in SRAM replacement. **No sense amplifier and no refresh controller
exist**, so every row below is ASSUMPTION unless a committed deck setting is
cited (then SOURCED-by-deck; the deck value is itself a declared test choice).
Behavioral only: not synthesis, timing, CDC or sign-off evidence, and no SPICE
was run.

## 1. Strobes (outputs of `phase_seq`)

Time base 1 cycle = 1 ns, inherited from the scheduler (ASSUMPTION).

| Strobe | Meaning | Tag |
|---|---|---|
| `pre_en` | read-bitline (`rbl`) precharge switch closed | ASSUMPTION (signal set); precharge-switch concept SOURCED [`sim/loaded-column/tb_loaded_column.spice.tmpl`](../../sim/loaded-column/tb_loaded_column.spice.tmpl) |
| `rwl_sel` | read select asserted on the selected row (active-low on `rwl` in the deck; polarity at the pin is not decided here) | ASSUMPTION |
| `sense_en` | sample strobe, last cycle of the `rwl_sel` window | ASSUMPTION; no sense amp exists |
| `wwl_en` | write wordline of the selected row | ASSUMPTION |
| `bl_drive` | write bitline driven; held through the guard phase | ASSUMPTION |
| `busy`, `done`, `row_q` | op in flight, 1-cycle completion pulse, latched row | ASSUMPTION |

Request: `start` (1-cycle, honoured only when idle; otherwise ignored and
`start_ignored` pulses), `kind` = READ(0) / WRITE(1) / REFRESH(2), `row`.

## 2. Phase tables (defaults = `anchored` scenario)

| Op | Phases in order | Cycles (`GAP`=0) |
|---|---|---|
| READ | PRE 2, SENSE 10, GUARD 2 | 14 |
| WRITE | WB 20, GUARD 2 | 22 |
| REFRESH | PRE 2, SENSE 10, WB 20, GUARD 2 | 34 |

| Parameter | Default | Tag |
|---|---|---|
| `P_PRE` precharge | 2 | SOURCED-by-deck: `TPRE_GAP = 2n` ([`tb_loaded_column.spice.tmpl`](../../sim/loaded-column/tb_loaded_column.spice.tmpl) line 28) |
| `P_SENSE` select window to sample | 10 | SOURCED-by-deck: `T_SENSE_S = 10e-9` ([`run_loaded_column.py`](../../sim/loaded-column/run_loaded_column.py) line 88) |
| `P_WB` write pulse | 20 | SOURCED-by-deck: `TWPULSE = 20n` (loaded-column template line 25); `TWL_ON`..`TWL_OFF` 1n..21n in [`tb_bitcell_transient.spice.tmpl`](../../sim/bitcell-transient/tb_bitcell_transient.spice.tmpl) lines 82-83 |
| `P_GUARD` BL release | 2 | SOURCED-by-deck: `TBL_LAG = 2n` (loaded-column template line 26) |
| `GAP` dead cycles between phases | 0 | ASSUMPTION (see open item 3) |
| `fast` set 1/5/5/1 | for tests | ASSUMPTION ([`sim/refresh-overhead/README.md`](../../sim/refresh-overhead/README.md) scenario table) |

The REFRESH write-back rewrites the value sensed; **the data path is not
modelled** (nothing latches or drives the sensed value), so write-back
correctness is not claimed.

## 3. Ordering and overlap rules (checked by the bench)

1. `pre_en` never overlaps `rwl_sel`, `sense_en`, `wwl_en`, `bl_drive`.
2. `sense_en` only while `rwl_sel`.
3. `wwl_en` and `bl_drive` never overlap `rwl_sel`, `sense_en` or `pre_en`.
4. `wwl_en` implies `bl_drive`; `bl_drive` outlasts `wwl_en` by the guard phase.
5. In REFRESH, no `wwl_en`/`bl_drive` before `sense_en` has occurred.
6. READ never drives write strobes; WRITE never runs read strobes.
7. REFRESH contains all four phases in order (a dropped phase fails).
8. No strobe while idle; `done` is one cycle; start-while-busy is ignored and flagged.

## 4. Open items: digital versus analog timing (not reconciled)

Scheduler constants `T_ROW` = 34, `T_ACC` = 34, `GUARD` = 2 (ASSUMPTION, [`../refresh-scheduler/refresh_sched.v`](../refresh-scheduler/refresh_sched.v) lines 26-29).

| Op | Minimum from cited settings | vs scheduler | Result |
|---|---|---|---|
| REFRESH, `anchored` 2+10+20+2 | 34 ns | `T_ROW` = 34 | zero slack; any inter-phase dead cycle exceeds it (`GAP`=1 gives 37; the bench prints this CONFLICT) |
| REFRESH, `fast` 1+5+5+1 | 12 ns | `T_ROW` = 34 | 22 ns unused; `fast` is not credible with plain 1.8 V wordlines (refresh-overhead README) |
| REFRESH, `full_read_pulse` 2+20+20+2 | 44 ns | `T_ROW` = 34 | exceeds by 10 ns |
| READ, 2+10+2 | 14 ns | `T_ACC` = 34 | fits |
| WRITE, 20+2 | 22 ns | `T_ACC` = 34 | fits |

1. **RWL window length.** The loaded-column deck holds the read select for
   `TREAD_PULSE = 20n` (template line 29) and samples at 10 ns; the sequencer
   uses a 10-cycle window ending at the sample. Using the deck's 20 ns pulse
   gives the 44 ns `full_read_pulse` row, longer than `T_ROW`. Open.
2. **Precharge lead.** The deck opens the precharge switch 2 ns *before* the
   select edge (a dead time); the sequencer counts the 2 ns as the precharge
   phase itself. If both are needed, refresh grows by 2 ns. Open.
3. **Phase boundaries.** Whether a dead cycle is needed between phases (WWL
   versus RWL non-overlap in a real circuit) is undecided; `GAP`=0 is the only
   value that fits `T_ROW`. Open.
4. **Scheduler coupling.** The scheduler asserts `op_busy` for exactly `T_ROW`
   cycles and does not wait on `phase_seq.done`. They are not wired together;
   no lockstep equivalence is claimed. Open.
5. Write-in-refresh needs a boosted wordline for a full level at short
   pulses (bitcell-transient); no boost strobe exists here. Open.
6. Polarity, drive strength, pin-level skew and sense-amp offset are all
   undecided.

A closed-loop refresh-operation measurement (companion proposal, not landed)
would be needed to replace these ASSUMPTION rows. Until then no row is a
timing claim.
