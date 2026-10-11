# Physical SPI crossing and reset architecture (PROPOSED design record)

Status: **PROPOSED** (issue #157). Protocol changes in Sec. 9 need operator
approval and stay PROPOSED here. No clock frequency is ratified and no refresh
deadline is relaxed. 1 clk cycle = 1 ns and the frame-spacing values remain
ASSUMPTIONs inherited from [`../control-integration/CONTRACT.md`](../control-integration/CONTRACT.md).
Public sources only (the committed repo files cited below).

Tags: **SOURCED** (a committed file), **ASSUMPTION** (design choice, no
evidence), **OPEN** (a decision or number nobody has made).

## 1. Why this record exists

The behavioral integration (#146, #93) connects scheduler-domain `busy` and
XSTATUS straight into the SPI slave (`gc_ctrl_top.v`), and
[`CONTRACT.md`](../control-integration/CONTRACT.md) Sec. 2 assumes that returned
status is already synchronised. Those are documented scope limits, not
defects. This record supplies the missing crossing architecture so that
synthesis does not silently change command acceptance, configuration latency
or refresh-deadline bounds.

## 2. Domains and crossing inventory

Domains. **SPI**: flops clocked by `sclk` (shift, return-path synchronisers)
and by the `cs_n` rising edge (commit), as in
[`spi_slave.v`](../spi-control/spi_slave.v). `sclk` may stop between frames and
inside a frame. **CLK**: the scheduler clock `clk`, free-running (ASSUMPTION).
Ratio `sclk`/`clk` unspecified (OPEN). One asynchronous `rst_n`.

Rule for the proposal: every asynchronous wire is a **single bit** (a toggle
or a level held until acknowledged). Multi-bit values cross only as a
**bundle** that is held constant for the whole interval in which the receiver
may sample it, qualified by a single-bit toggle. A two-flop synchroniser on
every bus bit does not give a coherent value (bits can resolve in different
cycles); it is not used.

| # | Crossing | From -> to | Owner of data | Mechanism | Reset behaviour | Timing obligation | Verification |
|---|---|---|---|---|---|---|---|
| C1 | Config/command bundle `{sw, en, ivl[15:0]}` | SPI -> CLK | SPI until ack | Bundled data. Loaded at an accepted commit, read by CLK only after `req_tog` is seen, and **not written again until `ack_tog` matches** (mailbox free) | Bundle returns to reset values (`en=1`, `ivl`=reset default, `sw=0`) | Bundle wires settle before the CLK capture edge: path delay `<` about 2 `clk` periods minus setup relative to the launch edge (OPEN, a `set_max_delay`/skew constraint to be set at synthesis) | Protocol: exactly-once and atomic (TB T1, T1b). Structural: confirm the capture flops only enable from the synchronised toggle. Physical: bundle skew |
| C2 | Request toggle `req_tog` | SPI -> CLK | SPI | Toggle, two-flop synchroniser in `clk` (3rd flop OPEN, see Sec. 8). Toggle (not pulse): no minimum pulse width, so the current "cs_n high and low >= 4 clk" rule is no longer needed for capture | 0 | Level held until consumed (guaranteed by C1 protocol) | Protocol: TB. Structural: single-bit sync cell. Physical: MTBF |
| C3 | Acknowledge `ack_tog` | CLK -> SPI | CLK | Toggle, two-flop synchroniser clocked by **`sclk`**; evaluated only at the commit | 0 | Must be visible before the next commit's 16th `sclk` edge, else the next write/command is *refused*, never corrupted (Sec. 8.2) | Protocol: TB T5 (directed violation of the Sec. 8.2 obligation: the mailbox commit right after an accepted one is refused, ERR_BUSY set, bundle and applied configuration untouched, retry succeeds; `run_tests.sh` asserts exactly 2 mailbox refusals per run). Structural/physical as C2 |
| C4 | Sweep-done toggle `sdone_tog` | CLK -> SPI | CLK | Toggle, two-flop synchroniser clocked by `sclk`. Toggles once per *commanded* sweep, when the sweep completes. Compared with SPI-local `sw_tog` | 0 (`sw_tog` also 0) | None beyond a stable level | Protocol: TB T2, T3, T4b, T6 |
| C5 | Snapshot request `snap_req` | SPI -> CLK | SPI | Toggle, two-flop synchroniser in `clk` | 0 | Flipped only after the previous snapshot was acknowledged | Protocol: TB T3 |
| C6 | Snapshot acknowledge `snap_ack` | CLK -> SPI | CLK | Toggle, two-flop synchroniser clocked by `sclk` | 0 | As C3 | Protocol: TB T3 |
| C7 | Snapshot data `snap_hold[7:0]` (XSTATUS: REFRESH_OK, DATA_LOST, SWEEP_ACTIVE, CFG_REJECT, applied count) | CLK -> SPI | CLK until the next request | Bundled data, written once per request, constant until `snap_req` flips again; copied whole into an SPI-side shadow at a frame end after `snap_ack` matches | Reset snapshot | Bundle settles before the SPI copy: skew constraint (OPEN) | Protocol: coherence (TB T3: redundant check bits expose a torn byte). Physical: skew |
| C8 | Commit event (`cs_n` rising edge) | pad -> SPI | SPI | **Not synchronised into `clk`.** It is the launch edge of C1/C2/C5 in the SPI domain (as the SPI slave already treats it). The existing `cfg_xfer` `cs_n` synchroniser is no longer needed | Frame counter cleared by `cs_n` high; reset clears all | `cs_n` is a clock: it needs a glitch-free input (Schmitt pad, OPEN) and clock-tree treatment; `cs_n` high time `>=` the cs_n-to-first-`sclk` setup | Protocol: TB T4d (aborted frames create no request). Structural: clock-use review. Physical: pad/clock constraints |
| C9 | Reset `rst_n` assertion | pad -> both | Both | Asynchronous assert in both domains | All C1..C7 state cleared. A pending request, commanded sweep and snapshot are **cancelled** (Sec. 7) | Minimum low time (OPEN) | Protocol: TB T6. Structural: reset-tree review |
| C10 | Reset release | pad -> both | Both | Release synchronised per domain (reset synchroniser per domain, OPEN) | Domains may leave reset up to a few cycles apart | Master waits `T_RLS` clk periods after `rst_n` rises before the first frame (OPEN; model uses 10 clk) | Protocol: TB waits only; the skew itself is a physical/structural item |
| C11 | Returned `busy`/`XSTATUS` (today: direct connection) | CLK -> SPI | n/a | **Replaced** by C3/C4 (BUSY) and C5-C7 (XSTATUS) | - | - | Structural: no direct connection may remain |

Not an SPI crossing: the external access port (`req_*`, `op_*`) is CLK-domain
and out of scope. `miso` launch (falling `sclk`) is I/O timing, not CDC.

## 3. Acknowledged bundled-data mailbox (SPI -> CLK)

1. Mailbox *free* at the SPI side means `req_tog == ack_s` (`ack_s` is the
   `sclk`-synchronised `ack_tog`).
2. At a commit (valid 16-edge write) that would change CTRL, IVL (the IVL_H
   commit) or issue START_SWEEP, the SPI side checks *free*. If free: load
   the bundle and flip `req_tog` in the same `cs_n` edge. If not free: the
   commit is **refused**, sticky ERR_BUSY is set (name OPEN, Sec. 9 OA-1), the
   bundle is untouched (TB T5 exercises this path for IVL_H and START_SWEEP).
3. The CLK side, on a synchronised `req_tog` change, captures the bundle in one
   cycle into its configuration register, performs the command if `sw=1`,
   and flips `ack_tog`. The bundle is stable throughout because it is only
   rewritten after `ack_tog` is seen, so a request is **consumed exactly once**
   (toggle semantics: two flips cannot be merged because the second flip
   cannot occur before the first is acknowledged) and **atomically** (a
   new interval can never pair with an old enable).
4. IVL_L writes and error/range checks stay SPI-local and need no crossing; they
   keep their current meaning. The scheduler's own feasibility check remains
   defence in depth.

## 4. Command reservation, separate from diagnostic status

START_SWEEP needs more than the mailbox: a second START_SWEEP must not be
accepted while the first has not completed.

* SPI-local `sw_tog` flips at an accepted START_SWEEP. The CLK side flips
  `sdone_tog` (C4) when the commanded sweep completes. The reservation is
  `sw_tog != sdone_s` and spans **commit to completion** with no gap, because it
  starts in the SPI domain at the commit (zero crossing latency) and ends
  only on an acknowledged completion.
* START_SWEEP is accepted only if both the mailbox is free and the reservation
  is clear. STATUS[7] BUSY = mailbox pending OR reservation held.
* BUSY is therefore **exact in the safe direction** and depends on single-bit
  toggles only, so no multi-bit coherence is needed. It is deliberately **not**
  derived from a diagnostic snapshot: an earlier draft that OR-ed a snapshot's
  SWEEP_ACTIVE into BUSY made BUSY flap 1,0,1,0 after completion while the
  snapshot aged; the model avoids that.
* Diagnostic status (XSTATUS and scheduler-internal sweeps, REFRESH_OK,
  DATA_LOST, CFG_REJECT) goes through the separate snapshot path of Sec. 5.
  It may be stale and must not be used for command acceptance.
* Consequence (OA-2): internal initialisation and re-initialisation sweeps no
  longer hold BUSY, so a START_SWEEP issued during one is accepted. The
  contract already defines that case safely: the sweep count restarts, so
  every row is still refreshed after the latest request
  ([`CONTRACT.md`](../control-integration/CONTRACT.md) Sec. 5). Alternative
  for the operators: keep BUSY covering internal sweeps by deriving it from
  a reservation raised by the CLK side, at the cost of an extra
  acknowledged handshake.

## 5. Coherent return-status snapshot (CLK -> SPI)

1. At each non-empty frame end the SPI side, if the previous snapshot was
   acknowledged (`snap_req == snap_ack_s`), copies `snap_hold` whole into the
   shadow that the next frame's XSTATUS read returns, then flips `snap_req`.
   Because the shadow changes only at frame ends, one frame sees one
   snapshot, and each snapshot is a single-cycle capture in the CLK domain.
2. The CLK side serves a mailbox request before a snapshot request. A snapshot
   requested at a commit therefore includes the effect of that commit's
   request. Status can lag; it is never a mixture of two instants.
3. **Freshness bound (assumption: continuous `clk`, master obligations of
   Sec. 8 met):** an XSTATUS byte read in frame `k+2` reflects the CLK domain
   no earlier than the capture requested at frame `k`, i.e. it is at most two
   frame periods plus the capture latency old. With `sclk` stopped there is
   no bound in time (nothing is reading), but the bound in frames holds.
   TB T3 checks this at four idle reads.
4. **Semantic caution (OA-3):** a stale SWEEP_ACTIVE or REFRESH_OK is
   conservative, but a stale **DATA_LOST=0** just after refresh was disabled
   is not. Proposal: derive DATA_LOST also as an SPI-local sticky bit set at the
   CTRL commit that clears `refresh_en` (cleared only by reset), so software
   never reads 0 after the disabling write was accepted. Not modeled.

## 6. Behaviour when `sclk` stops

The return-path synchronisers (C3, C4, C6) are clocked by `sclk`; they do not
advance while it is stopped. This is why the design uses **held levels and
toggles** rather than pulses, and why every decision is taken inside a frame.

| Direction | While `sclk` is stopped | After `sclk` restarts |
|---|---|---|
| SPI -> CLK (C1, C2, C5) | Launched flops are in the SPI domain but are changed only at a commit, which needs a frame. Once launched, the toggle is a held level. The CLK side keeps running and consumes the request regardless of `sclk`. | Nothing to do. |
| CLK -> SPI (C3, C4, C6, C7) | CLK changes a toggle or bundle and keeps it. The SPI domain does not observe it. Nothing is lost: a toggle is a level. | The first two `sclk` edges of the next frame resolve it. All uses are at the commit (16th edge) or the read-data latch (8th falling edge), so a frame of 16 edges has margin. |
| Mid-frame stop (cs_n low) | The frame is held; the shift state and `cnt` do not advance. A commit happens only at the `cs_n` rise after the 16th edge. | The frame completes normally (TB T4a). |
| Stop with `cs_n` high across a sweep completion | `sdone_tog` flips, unseen. | The first read of the next frame returns BUSY=0 (8 `sclk` edges have synchronised it) and BUSY does not flap afterwards (TB T4b). |
| Short frame (<16 edges) then `cs_n` high | No commit, no request. | - (TB T4d) |

A progress claim is only made "per `sclk` edge" for the SPI side and "per
`clk` edge" for the CLK side; no wall-clock claim is made while `sclk` is stopped.

## 7. Reset cancellation and recovery

* `rst_n` low asynchronously clears both domains. A pending, unconsumed
  request is **cancelled**: it is not applied after reset (no stale command).
  A running commanded sweep is cancelled (the reset initialisation sweep
  refreshes every row anyway, as in `CONTRACT.md` Sec. 4/5). `req_tog`, `ack_tog`,
  `sw_tog`, `sdone_tog`, `snap_*` all return to 0 together, so the mailbox is
  free and the reservation clear after reset.
* A START_SWEEP or configuration write that was accepted but not yet applied
  when reset hit is **lost by design**; the master sees reset-default
  registers and must reissue. This is stated as the intended semantics (the
  alternative, surviving reset, would need non-volatile state).
* Recovery: the master holds `cs_n` high and waits `T_RLS` after `rst_n` rises
  (OPEN, C10), then the first command is accepted exactly once (TB T6 i, ii,
  iii: pending START_SWEEP, running sweep, pending CTRL write).
* Open structural items: per-domain synchronised release; confirmation that
  no domain can see a toggle from the other before its own release.

## 8. Timing constraints and latency derivations

Notation: `Tc`, `Ts` = `clk`, `sclk` periods. An "edge" count is of the
receiving clock. A two-flop synchroniser delivers a changed input to its
output after at most 2 receiving edges (first edge may sample the old or the
new value; the second makes it visible; a third flop OPEN for MTBF would add
one). Counts below are for the model's 2-flop version; each extra flop adds
one edge.

### 8.1 Commit -> applied (SPI -> CLK)

`req_tog` flips at the `cs_n` edge. Edge 1: `rq_s[0]`. Edge 2: `rq_s[1]`.
Edge 3: the bundle is captured, `cfg_*` updates, `sweep_active` rises (for
START_SWEEP) and `ack_tog` flips. **At most 3 `clk` edges** commit to applied
in the CLK domain. The measured model maximum is 3.00 ns = 3 edges at 1 ns
(all runs, `run_tests.sh` summary line `max_apply_clk_edges`). The existing
scheme's captured-cycle bound is 4 edges
([`CONTRACT.md`](../control-integration/CONTRACT.md) Sec. 2). The scheduler
then applies the snapshot one cycle later, as `refresh_sched_rt` does today
(`cfg_valid` register): **<= 4 edges to the scheduler, <= 5 with a 3-flop
synchroniser**. Both are inside the existing bench allowance `T_XFER = 6`.

### 8.2 Ack -> mailbox free (CLK -> SPI) and the master obligation

`ack_tog` flips at CLK edge 3 (above), so at most `3 Tc` after the commit
(plus wire skew, OPEN). It is visible to the commit decision after 2 more
`sclk` edges. The next commit (16th edge) therefore finds the mailbox free if

`t_cs_high + t_cs_to_sclk + 13 Ts  >=  3 Tc + t_skew + 2 Ts`  (ASSUMPTION form).

(13 is the number of `sclk` periods from the first rising edge to the 14th,
after which only edges 15 and 16 remain to clock the synchroniser.) The
existing "cs_n high >= 4 clk" rule supplies 4 `Tc` of gap before the first
`sclk` edge, which alone exceeds the `3 Tc` ack latency by one `Tc` of skew
budget; the 2 `Ts` still needed to synchronise the ack into the SPI domain
are covered by the 13 `Ts` term (that is, `4 Tc >= 3 Tc + t_skew` **plus**
`13 Ts >= 2 Ts`). The rest of the 13 `Ts` term only adds margin.
**If the obligation is violated, the effect is a refusal (ERR_BUSY) and a
retry, never loss, duplication or tearing.** This is tested by the directed
TB T5, which violates the obligation on purpose (`sclk` half period 50 ps,
`cs_n` high 0.1 ns, so the next commit lands 1.8 ns after an accepted one,
before the CLK side can capture the request in its minimum 2 `Tc`): the
IVL_H and START_SWEEP commits that follow an accepted CTRL commit are refused
by the mailbox (the sweep reservation is clear at that point), ERR_BUSY is
set, the bundle and the applied configuration are unchanged, the exactly-once
scoreboard is clean, and the master's retry applies the intended value. The
run script asserts exactly 2 mailbox refusals in every positive run. With the
acknowledgement omitted (`NEG=1`) the same sequence produces `STALE/MISMATCH
bundle` scoreboard errors (the CLK side captures a bundle other than the one
the SPI side accepted for that toggle), which is the failure the refusal
prevents. The model's ack latency is a fixed 3 `Tc`; a CLK side that is late
for other reasons is not modelled separately, but reaches the commit decision
through the same `req_tog != ack_s` comparison.

### 8.3 Sweep status latencies

* BUSY rises at the commit: **0 crossing latency**, SPI-local reservation.
* BUSY falls once `sdone_tog` is seen: sweep completion at CLK edge `E`; the SPI
  side needs 2 `sclk` edges. A STATUS read returns 0 if the toggle flipped at
  least 2 `sclk` edges before the 8th falling edge of that frame, otherwise
  the read returns 1 (conservative). Staleness is at most one frame.
  The model's sweep length `SW_LEN = 40` clk is a placeholder for `T_SWEEP`.
* Config applied -> XSTATUS visible: Sec. 5 (<= 2 frames).

### 8.4 Effect on the integration bounds

[`../spi-sched-phase-integration/README.md`](../spi-sched-phase-integration/README.md)
bounds: `T_XFER` = 6 (observed <= 4), `T_SWEEP`, `T_SETTLE`, deadline slack 26
(11 in the `fast` set), "START_SWEEP accept -> sweep_done up to 1178".

* `T_XFER`: unchanged; the proposal's worst case (4 or 5 edges) is inside 6.
* `T_SWEEP`, `T_SETTLE`, the INTERVAL deadlines and all slack numbers: **not
  changed**. They are properties of the scheduler after application.
* New: a **refused** commit adds one retry. The commit-to-applied bound
  applies to *accepted* commits. The worst-case time from the master's first
  attempt of a *shortening* write to application grows by at most one extra
  frame period per refusal. Under the 8.2 obligations no mailbox refusal
  occurs on back-to-back config writes; in the model, mailbox refusals occur
  only in the directed T5 test that violates the obligation. (The other
  refusals in the summary line, at fast `sclk` only, are T2's second
  back-to-back START_SWEEP refused by the sweep reservation of Sec. 4, not by
  the mailbox: `refused_commits` counts both, `mailbox_refusals` only the
  latter.) Even so, the deadline-bearing case (shortening the interval) is a master
  obligation: read STATUS for ERR_BUSY after the write and retry
  (OPEN: whether the shortened-interval deadline analysis must include this
  retry; recommended yes, one frame per retry).
* The integration bench would need re-running against production RTL; this
  record does not claim those results transfer.

### 8.5 Unestablished numbers (all OPEN)

Clock frequencies and ratio; synchroniser depth (2 vs 3); bundle and toggle skew
limits; `T_RLS`; reset minimum pulse; `cs_n` pad/clock constraints; the real
`T_SWEEP`. None is ratified here.

## 9. Protocol changes needing operator approval (all PROPOSED)

| ID | Change | Alternative |
|---|---|---|
| OA-1 | CTRL and IVL_H commits, previously always accepted, are refused with ERR_BUSY while the mailbox is occupied; master retries | Queue depth 2 (more storage); or hold sclk-side SPI ready |
| OA-2 | BUSY is the exact reservation (mailbox pending or commanded sweep outstanding). Internal init/re-init sweeps are visible only in XSTATUS; START_SWEEP during one is accepted and restarts the sweep count | Extend BUSY to internal sweeps with a CLK-raised reservation |
| OA-3 | XSTATUS is a snapshot up to two frames old; DATA_LOST gets an SPI-local sticky mirror | Direct read through a handshake that stalls the frame |
| OA-4 | Register readback (CTRL, IVL_L, IVL_H) returns the value committed into the mailbox, which can lead the applied scheduler value by up to the Sec. 8.1 latency | Read back the applied value through the snapshot |
| OA-5 | After reset release the master waits `T_RLS` before the first frame; requests accepted but unapplied at reset are lost | - |
| OA-6 | `cs_n` is no longer synchronised into `clk`; the "cs_n low >= 4 clk" obligation is dropped; "cs_n high >= 4 clk" is kept as the 8.2 obligation | Keep the frame-qualified scheme, see Sec. 10 |

## 10. Comparison: retain the frame-qualified scheme

The current scheme ([`cfg_xfer.v`](../control-integration/cfg_xfer.v)) is
smaller (one `cs_n` synchroniser, a snapshot capture, no return path) and its
behavioral evidence exists. It still (a) cannot reach synthesis without a
real return-status architecture (status is assumed pre-synchronised), (b)
relies on frame-spacing rules in **both** directions of `cs_n`, (c) can lose a
START_SWEEP if a short `cs_n` pulse is missed, shown by the committed
negative control, and (d) offers no stopped-`sclk` argument for returned
status. The mailbox costs a few toggle flops and one refusal path (OA-1) and
turns (c) into a detected refusal. This record recommends the mailbox; the
decision is the operators'.

## 11. Compatibility with `../spi-control/SPEC.md`

| Item (SPEC.md) | Proposed behaviour | Change? |
|---|---|---|
| Sec. 1 framing, mode 0, 16 edges, commit on `cs_n` rise | Same; `cs_n` is a clock in the SPI domain | No |
| `busy_in` "assumed already synchronised" | Replaced by C3/C4 reservation; no direct scheduler wire | Yes (OA-2) |
| 0x00 ID | Same | No |
| 0x01 CTRL write | Takes effect via mailbox; refused with ERR_BUSY if occupied | Yes (OA-1), readback OA-4 |
| 0x02 CMD START_SWEEP | Accepted only if mailbox free and reservation clear | Same ERR_BUSY wording, wider cause (OA-1/2) |
| 0x02 CMD CLEAR_STATUS | SPI-local, unchanged | No |
| 0x03 IVL_L (shadow) | SPI-local, unchanged | No |
| 0x04 IVL_H commit | Via mailbox; range/floor check unchanged and SPI-local | Yes (OA-1) |
| 0x05 STATUS[3] ERR_BUSY | Also set when a config commit is refused | Yes (OA-1) |
| 0x05 STATUS[7] BUSY | Reservation (exact), not the live scheduler `busy` | Yes (OA-2) |
| 0x06 XSTATUS (`XSTAT_EN`) | Snapshot, <= 2 frames old, coherent | Yes (OA-3) |
| Reset values, async `rst_n` | Same; extended to the new state; pending requests cancelled | Clarified (OA-5) |
| Sec. 3 interval bound and ERR_RANGE | Unchanged | No |

## 12. What is and is not established

Established here (Icarus protocol checks, `run_tests.sh`): exactly-once and
atomic delivery under the stated master obligations, including paused and
restarted `sclk` and reset cancellation; BUSY exactness (never reads 0 while a
commanded sweep is outstanding; no flap); coherent snapshots; commit-to-applied
<= 3 `clk` edges in the model; that a commit made while the mailbox is
occupied (violated Sec. 8.2 obligation, TB T5) is refused with ERR_BUSY,
leaves the bundle and applied configuration untouched, and succeeds on retry;
and that omitting the acknowledgement and reservation (negative control
`NEG=1`) breaks both mechanisms. For the **config bundle**, T5 under `NEG=1`
yields `STALE/MISMATCH bundle` scoreboard errors at every tested `sclk`,
including the slow 3.7 ns half period (T5 sets its own fast `sclk`), and the
script requires such a mailbox-level error in every negative-control run. For
the **sweep reservation**, `NEG=1` loses sweeps (completions fewer than
accepted) and accepts a START_SWEEP while the previous one is outstanding;
this part shows its effect only when frames are shorter than a sweep (fast
`sclk`); at slow `sclk` the sweep finishes between frames and that part of
the unsafe variant is not caught there, which the script does not claim.

**Not established:** metastability or MTBF; physical timing; structural CDC
cleanliness (a reviewed lint pass is required); `cs_n`-as-clock timing;
reset-release skew; any clock frequency; any change to refresh deadlines.

## 13. Follow-up work and blockers before synthesis

1. Operator decision on OA-1..OA-6 (blocks production RTL).
2. Production RTL of the mailbox, reservation and snapshot, replacing
   `cfg_xfer` behind the same scheduler interface; rerun
   `../control-integration` and `../spi-sched-phase-integration` against it.
3. Structural CDC review/lint with a tool that understands toggle and bundle
   protocols; reviewed synchroniser cells (depth decision).
4. Constraints: bundle and toggle skew, `cs_n` as a clock, `T_RLS`, reset
   tree. Needs a clock plan (blocks: no ratified frequency).
5. Physical MTBF estimate with the PDK flip-flop data once a frequency exists.
6. Decide whether the shortened-interval deadline analysis includes a retry.
7. Coordinate with #147 and the #24 decision records without changing their criteria.
