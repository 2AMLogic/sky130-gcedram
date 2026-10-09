# SPI to refresh-scheduler control contract (PROPOSED)

Status: **PROPOSED** (issue #93, epic #24 items 3 and 4). Nothing here is
ratified and `spec/` is not edited. This is a behavioral contract between the
#83 SPI slave and a runtime-configurable version of the #74 refresh scheduler.
It is not a synthesis, timing, CDC or production specification. The macro is a
**dynamic** gain-cell array: this contract configures refresh. It is not an
SRAM-replacement interface.

Tags: **SOURCED** (cites a committed file) or **ASSUMPTION** (a design choice
with no evidence yet).

## 1. Blocks, clocks, reset

| Element | Choice | Tag |
|---|---|---|
| SPI domain | `sclk` and `cs_n` used directly as clocks, mode 0, 16-bit frames, commit on `cs_n` rising edge | ASSUMPTION (as in [`../spi-control/SPEC.md`](../spi-control/SPEC.md)) |
| Scheduler domain | one clock `clk`. Every configuration snapshot is applied on this clock | ASSUMPTION |
| Time base | 1 `clk` cycle = 1 ns, inherited from #74. This is not a clock-rate claim | ASSUMPTION |
| Reset | one asynchronous active-low `rst_n` resets both domains | ASSUMPTION |
| `N_ROWS`, `T_ROW`, `T_ACC`, `GUARD` | 32, 34, 34, 2 cycles. These are the parameter defaults of [`refresh_sched.v`](../refresh-scheduler/refresh_sched.v); `params.py` reads them from that file | ASSUMPTION (from #74) |
| Upper interval bound `INTERVAL` | 5029 cycles (ratified basis). 2751 cycles is an unratified stress variant | SOURCED via [`../refresh-scheduler/params.py`](../refresh-scheduler/params.py) from the retention CSV ([`spec/retention-refresh-budget.md`](../../spec/retention-refresh-budget.md) Sec. 7) |

## 2. Configuration transfer (SPI to scheduler)

* The SPI slave's committed state, `{refresh_en, interval, sweep_tog}`, forms a
  bundle. That bundle changes only at a `cs_n` rising edge.
* `cs_n` passes through a two-flop synchroniser into `clk`. When the
  synchronised rising edge is seen, the whole bundle is captured as one
  snapshot. A one-cycle strobe carries it to the scheduler, which applies it
  whole on the next cycle. The scheduler never sees a partial snapshot, such
  as a new high byte with an old low byte, or a new interval with an old
  enable.
* Latency: at most 4 `clk` edges from the `cs_n` rising edge to application.
  The bench allows `T_XFER = 6` cycles (ASSUMPTION/bound).
* Every frame produces a snapshot, including reads and rejected writes. A
  snapshot that is identical to the applied state changes nothing.
* START_SWEEP is the toggle `sweep_tog`. A snapshot requests a sweep when the
  captured toggle differs from the previously captured one.
* **Frame spacing (master obligation, ASSUMPTION):** `cs_n` stays high for at
  least 4 `clk` periods between frames and low for at least 4 `clk` periods per
  frame. Under this rule every commit is captured, and BUSY is visible before
  the next frame can commit. Two accepted START_SWEEP toggles therefore never
  cancel each other: the second one is refused with ERR_BUSY. The bench's
  negative control breaks the rule with a sub-cycle `cs_n` high pulse, and
  the bench then reports the lost START_SWEEP (see README).
* **Not CDC safety.** iverilog does not model metastability. This
  behavioral transfer shows *what* is captured and *when*. It does **not**
  establish that the physical crossing is safe. A real implementation would
  still need a reviewed synchroniser, a bus-skew constraint between the bundle
  and `cs_n`, a decision on the `sclk`/`clk` ratio, and real synchronisation
  of the returned status (BUSY, XSTATUS). This model assumes that status is
  already synchronised, as #83 assumes for `busy_in`.

## 3. Refresh interval

* **Legal range `[MIN_INTERVAL, INTERVAL]`.**
  `MIN_INTERVAL = N_ROWS*T_ROW + T_ACC + GUARD`. This is the #74
  elaboration-time feasibility check (`EAGER_AGE >= 0`, which implies
  `URGENT_AGE >= 0`) applied to a runtime value. With the assumptions above
  it is 1124 cycles. The 1-cycle floor in #83 was a placeholder.
* **Rejection.** Out-of-range values are refused at the SPI commit: ERR_RANGE
  is set, nothing is committed, and the scheduler is unchanged. The
  scheduler applies the same check again and refuses the whole snapshot
  (sticky `cfg_reject`, XSTATUS[3]). That second check is defence in depth and
  cannot be reached through the SPI slave. A short interval can satisfy the
  retention upper bound and still be infeasible; such intervals are rejected
  explicitly.
* **When an interval becomes effective.**
  * Lengthening takes effect on application. All rows are already within the
    old, shorter value.
  * Shortening is a **bounded transition** that keeps the deadline. The new
    value enters the urgency rule as soon as it is applied. The pointer row is
    always the oldest (#74 round-robin), so every row now past the new urgent
    threshold is refreshed back to back starting from the pointer. Rows
    refreshed in pointer order satisfy
    `age(ptr+k) <= age(ptr) - k*T_ROW`. During that burst each row therefore
    finishes no later than the pointer row would have under the old rule:
    the **old interval still holds** during the transition. The **new interval
    holds for every row** from
    `T_SETTLE = T_XFER + (T_ACC+1) + N_ROWS*(T_ROW+1) + GUARD` cycles after
    the commit, which is 1163 cycles here. Each op occupies its duration plus
    one decision cycle, as in #74. The bound covers one in-flight external op
    followed by `N_ROWS` back-to-back refreshes. The bench checks the old deadline throughout the
    transition and the new deadline after it. It also reports the longest
    transition it observed.
  * BUSY does **not** cover a shortening transition, because software has
    nothing to wait for (ASSUMPTION; the alternative is to hold BUSY for
    `T_SETTLE`).

## 4. Enable, disable, validity

| Event | Behaviour | Tag |
|---|---|---|
| Reset | Initialisation sweep (all rows, as #74). REFRESH_OK=0 until it completes. DATA_LOST=0. Array contents are taken as initialised by that sweep (the #74 assumption, carried over) | ASSUMPTION |
| `refresh_en` 1 to 0 | No new urgent or eager refresh starts. A running op, and any requested sweep, completes. REFRESH_OK=0. **DATA_LOST is set and stays set until reset.** This block has no datapath, so it cannot know when software has rewritten every row; it reports the loss conservatively. The retention guarantee is void while refresh is disabled | ASSUMPTION |
| `refresh_en` 0 to 1 | Re-initialisation sweep: `N_ROWS` back-to-back refreshes starting at the oldest row. BUSY is high during it. REFRESH_OK rises only after it completes. DATA_LOST stays set: contents from before the re-enable are **not** guaranteed | ASSUMPTION |
| Data valid | `REFRESH_OK && !DATA_LOST` | ASSUMPTION |

## 5. START_SWEEP (CMD 0x01)

* Accepted only when BUSY=0. Otherwise it is refused with ERR_BUSY: not
  queued and not lost. Software retries.
* After acceptance, BUSY is high within the transfer latency and stays high
  until the sweep's last row refresh completes. A sweep is `N_ROWS`
  back-to-back refreshes starting at the oldest row, with priority over
  external access. Every row completes a refresh after acceptance. The sweep
  finishes within `T_SWEEP = T_XFER + (T_ACC+1) + N_ROWS*(T_ROW+1) + GUARD`
  cycles, 1163 here.
* If a sweep request arrives while a sweep is running, the count restarts
  rather than being merged into the running sweep, so every row is still
  refreshed after the latest request. Through the SPI slave this cannot
  happen, because the slave refuses START_SWEEP while BUSY.
* A START_SWEEP is executed even when refresh is disabled. It does not change
  REFRESH_OK or DATA_LOST.
* Reset cancels an accepted sweep that has not completed. The reset
  initialisation sweep refreshes every row in any case.

## 6. Status returned to the protocol model

| Where | Bit | Meaning |
|---|---|---|
| STATUS (0x05) | [7] BUSY | transfer pending OR a sweep (init, re-init or forced) is running |
| XSTATUS (0x06, enabled by `XSTAT_EN=1`) | [0] REFRESH_OK | enabled and (re)initialisation sweep complete |
| | [1] DATA_LOST | refresh was disabled since the last reset (sticky) |
| | [2] SWEEP_ACTIVE | a sweep is running |
| | [3] CFG_REJECT | the scheduler refused a snapshot (sticky; not reachable through the SPI floor) |

## 7. Not established here

Physical CDC safety. Synthesis, timing, and the maximum `sclk` rate. The real
`N_ROWS`/`T_ROW`/`T_ACC`. The memory datapath (read/write data), and with it
any finer-grained recovery of data validity than "reset clears DATA_LOST".
Multi-bank refresh. Any production or ratified specification. Re-check this
contract whenever an item in [`../spi-control/SPEC.md`](../spi-control/SPEC.md)
Sec. 5 changes.
