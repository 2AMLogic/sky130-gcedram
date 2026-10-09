# SPI control interface (PROPOSED)

Status: **PROPOSED** (issue #83, epic #24 item 4). Not ratified; `spec/` is not
edited. Challenge-4 proposal section 2.3 notes 0 of 24 digital control inputs
are used; this is a candidate answer. The macro is a **dynamic** gain-cell
array that needs refresh; this interface configures refresh and is not an
SRAM-replacement interface.

Tags: **SOURCED** (cites a committed document) or **ASSUMPTION** (design choice, no evidence yet).

## 1. Physical and framing

| Element | Value | Tag |
|---|---|---|
| Signals | `sclk`, `cs_n` (active low), `mosi`, `miso`, async `rst_n`; `busy_in` from the scheduler | ASSUMPTION |
| SPI mode | mode 0 (CPOL=0, CPHA=0): sample on rising, drive on falling `sclk` | ASSUMPTION (most common default) |
| Bit order | MSB first | ASSUMPTION |
| Frame | exactly 16 `sclk` rising edges while `cs_n` low: `{RW, ADDR[6:0], DATA[7:0]}`; RW=1 write, 0 read | ASSUMPTION |
| Read | data returned on `miso` during bits 7:0 of the same frame (read address latched on 8th falling edge); `miso` is 0 in the command phase and for writes | ASSUMPTION |
| `miso` when deselected | Hi-Z (shared bus) | ASSUMPTION |
| Commit | writes and commands take effect on `cs_n` rising edge, only if the frame had exactly 16 edges | ASSUMPTION |
| `sclk` frequency | not specified; behavioral model is time-agnostic | ASSUMPTION |
| `busy_in` | assumed already synchronised to the SPI domain | ASSUMPTION |

## 2. Register map

| Addr | Name | Access | Reset | Function | Tag |
|---|---|---|---|---|---|
| 0x00 | ID | RO | 0xA5 | fixed identity byte | ASSUMPTION |
| 0x01 | CTRL | RW | 0x01 | bit0 `refresh_en`; bits 7:1 reserved, read 0, writes ignored | ASSUMPTION (refresh on at reset because a dynamic array loses data without it) |
| 0x02 | CMD | WO (reads 0) | - | 0x01 START_SWEEP (one refresh sweep; toggles `sweep_tog`), 0x02 CLEAR_STATUS; any other value sets ERR_CMD | ASSUMPTION |
| 0x03 | IVL_L | RW | `MAX_INTERVAL[7:0]` | low byte of refresh interval; write goes to a shadow, read returns committed value | ASSUMPTION |
| 0x04 | IVL_H | RW | `MAX_INTERVAL[15:8]` | high byte; a write **commits** `{IVL_H, shadow L}` if in bounds | ASSUMPTION |
| 0x05 | STATUS | RO | 0x00 | `[0]` ERR_RANGE `[1]` ERR_FRAME `[2]` ERR_ACCESS `[3]` ERR_BUSY `[4]` ERR_CMD (all sticky, cleared by CMD 0x02); `[7]` BUSY (live `busy_in`) | ASSUMPTION |

Unmapped addresses read 0x00.

## 3. Refresh-interval bound

`IVL` is in clock cycles. The legal range is `1 .. MAX_INTERVAL`.

* **MAX_INTERVAL = floor(t_retention / 2)** at the worst-case corner (sf, 125 C, 2T-min), about 5.03 us. **SOURCED**:
  [`spec/retention-refresh-budget.md`](../../spec/retention-refresh-budget.md) Section 7 (ratified; the 2x margin is an ASSUMPTION stated there).
  The number is **not typed in this repo**: `params.py` derives it from
  [`sim/retention/results/retention_results.csv`](../../sim/retention/results/retention_results.csv)
  via the #74 `digital/refresh-scheduler/params.py`. The testbench runs at the
  ratified bound and at the newer, **unratified** layout-extracted-`C_SN` bound (stress variant).
* 1 cycle = 1 ns: **ASSUMPTION** inherited from #74.
* Out-of-bound (0 or above `MAX_INTERVAL`) commit: **rejected**, committed interval unchanged, shadow reverted to the committed low byte, sticky **ERR_RANGE** set.
  Rationale (ASSUMPTION): a longer-than-retention interval silently loses data, so the safe failure is to keep the last good value and flag.
* The reset default is the maximum legal interval (ASSUMPTION); software may only shorten it.
* Lower bound 1 is a placeholder (ASSUMPTION); the true floor is set by the refresh-sweep time (`N_ROWS * T_ROW`, see #74 feasibility check).

## 4. Error handling

| Condition | Effect |
|---|---|
| frame with 1..15 or 17+ rising edges | no state change, ERR_FRAME |
| frame with 0 edges (cs_n glitch) | ignored, no error |
| write to RO/unknown address, or read of unknown address | no state change, ERR_ACCESS |
| START_SWEEP while `busy_in` | not issued, ERR_BUSY |
| unknown CMD value | ERR_CMD |
| `rst_n` low (async) | all registers, shift state and errors return to reset values |

Setting `refresh_en`=0 is allowed (ASSUMPTION) but means the array loses data;
this block does not police it.

## 5. Rules-dependent re-check list

Re-check when any of these change: (1) ratified refresh interval (Sec. 7 / new
retention evidence, e.g. adoption of the layout-extracted `C_SN` interval);
(2) the 2x retention margin; (3) array/pad/pin-count decisions (24 control
inputs, challenge-4 rules text); (4) real scheduler timing (`T_ROW`, sweep
time, `busy_in` timing); (5) `sclk` rate and I/O timing once pad cells and a
clock plan exist; (6) whether the contest rules require a different digital
interface (parallel vs serial).

## 6. Not covered

No synthesis, timing, CDC or layout evidence; the behavioral model uses `sclk`/`cs_n` as clocks directly and is a protocol model only.
