# Chipalooza Challenge #4 proposal — 2T gain-cell embedded-DRAM (eDRAM) macro (sky130)

Analog/mixed-signal-IP proposal for [Open Circuit Design's Chipalooza
Challenge #4](https://opencircuitdesign.com/chipalooza/) (Sky130 /
ChipFoundry). This document is written to be sendable verbatim once the
design clears its sign-off bar; it contains no personal or institutional
identifiers. Designer CVs and the test-equipment list, if this design is
ever submitted, are separate email attachments outside this repository, per
the challenge's submission process (see
[2AMLogic/sky130-temp-por's own Challenge #4
proposal](https://github.com/2AMLogic/sky130-temp-por/blob/main/docs/chipalooza/challenge-4-proposal.md)
for a sibling repo's version of that same process, on the same PDK).

**Rules status (as of this writing, 2026-09-05): Challenge #4's own rules
page (`rules-4.html`) is not yet published** — the organizers' calendar puts
launch at 2026-11-09. Per
[2AMLogic/2am#542](https://github.com/2AMLogic/2am/issues/542) (the epic
this issue is a phase of), this document assumes the structure common to
the two *published* briefs (`rules-2.html`/`rules-3.html`): a template
wrapper cell in a fixed slot; a harness-supplied bandgap-referenced bias
voltage and up to two bandgap-referenced current sources; 24 digital
control inputs; 12 digital test outputs; 4 shared (multiplexed) analog
lines; 0–4 dedicated pads; an SPI control interface; deliverables of
schematic + pre-layout sim → layout + post-layout sim over PVT → final
DRC/LVS in-repo, verifiable with open-source EDA; a standard open license
(preferably Apache 2.0). When `rules-4.html` publishes, a follow-up issue
must re-check every assumption in this document against the real brief
before any submission — this document is **not** a claim that Challenge
#4's actual rules match this assumption, only the best available structure
to design against today.

**Repository status as of `main` @ `4de3e77`, checked 2026-11-14.** Every
statement below about what this repository does and does not contain was
re-read against the tree at that commit. This stamp covers repository state
only; the 2026-09-05 stamp on the rules paragraph above is a separate,
deliberately frozen date and is **not** refreshed by it.

**Honesty note, stated once here rather than repeated on every row.** This
repository is at **block-increment maturity**, not macro maturity. The
retention/refresh-budget evidence chain is fully ratified
([`spec/retention-refresh-budget.md`](../../spec/retention-refresh-budget.md)),
and the single `2T-min` gain-cell bitcell has committed design sources
([`design/gain_cell_2t.sch`](../../design/gain_cell_2t.sch)/
[`.spice`](../../design/gain_cell_2t.spice)) and a committed layout
([`layout/gain_cell_2t.gds`](../../layout/gain_cell_2t.gds)) with an
*informal* DRC-clean/LVS-match iteration behind it (see §4.4). Beyond that
bitcell, an array, a sense stage, a refresh controller and an SPI control
interface **do now have committed artifacts** — but not one of them is a
macro-ready block. Each sits in exactly one of three status tiers, and this
document uses these tier names verbatim on the rows below:

| Tier | What it means | What is in it |
|---|---|---|
| **Proof of technique** | real geometry with an informal DRC/LVS iteration behind it, but one fixed instance rather than a parameterized macro block | the shared-tap 4×4 bitcell array, [`layout/gain_cell_2t_array.gds`](../../layout/gain_cell_2t_array.gds) (§3, §4.4) |
| **Proposed pass conditions** | schematic-level circuit plus characterization, every point of it under a **PROPOSED, NOT RATIFIED** restricted operating range ([`spec/operating-range-decision-PROPOSED.md`](../../spec/operating-range-decision-PROPOSED.md)) | the sense latch ([`design/sense_latch.sch`](../../design/sense_latch.sch)) and the column-periphery slice ([`design/column_periphery.sch`](../../design/column_periphery.sch)), with their studies under [`sim/`](../../sim/); every `spec/*-PROPOSED.md` record |
| **Behavioral RTL only** | self-checking Verilog with regressions and mutation runs; no layout, no CDC or timing sign-off | everything under [`digital/`](../../digital/) — refresh scheduler, phase sequencer, SPI slave and their integrations. One partial exception: `spi_slave` also has a standard-cell synthesis result (§2.3), which is still neither placed, routed nor timing-closed |

**What those tiers do not add up to is a macro.** There is no integrated
array-plus-periphery block, no row/column address decode anywhere in the
repository, no digital layout, no full-macro GDS and no post-layout PVT
campaign — so this macro, as a submittable IP block carrying the harness's
I/O contract, has not been designed yet, and every I/O bucket in §2.7 is
still 0. Per CLAUDE.md's "no claim without a testbench" and this issue's own
acceptance criteria, every spec-table row below states its status against
what `design/`, `digital/`, `sim/` and `layout/` actually contain at the sha
above, not against schematic inspection or an aspirational macro that does
not yet exist. This is not a defect this document introduces or a spec being
relaxed to pass — it is an honest snapshot of where the block actually is on
its own maturity ladder ([`README.md`](../../README.md): *"Current position:
the bitcell is simulated across PVT (write/read/hold) and laid out DRC-clean
with a matching LVS, but its loaded-column read does not hold over the full
temperature range... The open frontier is the macro: array, sense amplifier
and refresh-controller design..., then macro-level layout and post-layout
re-verification"*).

---

## 1. Type of IP block

An embedded DRAM (eDRAM) memory macro: a 2T gain-cell bitcell array with
sense and refresh periphery. The array exists only as a proof-of-technique
4×4 instance and the periphery only as schematic-level slices plus
behavioral RTL; the integrated macro is not designed (see §3). This is
**not** an SRAM and must never be described as a drop-in replacement for
one (per CLAUDE.md): a gain cell is a *dynamic* storage element that trades
SRAM's static hold for bitcell density, and its retention/refresh budget is
the centerpiece of its spec, not a footnote.

## 2. I/O list, including test ports

### 2.1 Rails — every committed device is 1.8 V-only; the periphery rail is an open item

Every device in **every** design source this repo has is a 1.8 V core
flavour. The bitcell
([`design/gain_cell_2t.sch`](../../design/gain_cell_2t.sch)) is two
`sky130_fd_pr__nfet_01v8`, sky130's core **1.8 V** NMOS
([`design/README.md`](../../design/README.md) "Topology: 2T, ratified":
*"Two devices, both `sky130_fd_pr__nfet_01v8`... no other `sky130_fd_pr`
flavour appears anywhere in this schematic"*). The two periphery slices
added since — the sense latch
([`design/sense_latch.sch`](../../design/sense_latch.sch)) and the
column-periphery slice
([`design/column_periphery.sch`](../../design/column_periphery.sch)) —
introduce `sky130_fd_pr__pfet_01v8`, and nothing else: across `design/` and
every `sim/` deck, `nfet_01v8` and `pfet_01v8` are the only two
`sky130_fd_pr` flavours that appear at all. The wordline drive scheme
is explicitly **plain 1.8 V, not boosted**
([`design/README.md`](../../design/README.md) "Wordline drive scheme"),
consistent with the repo README's own "Supply" row: *"sky130 standard
1.8 V core; boosted wordline is a design decision to record."*

| Harness rail (assumed common structure) | This block's use |
|---|---|
| 1.8 V digital | **The only supply anything committed here uses.** Every measured, extracted or simulated evidence point in this document (leakage, retention, sense, refresh, DRC/LVS) is at `VDD` = 1.8 V against `nfet_01v8`/`pfet_01v8`. |
| 3.3 V analog | **Not yet exercised by anything committed in this repo.** The sense stage that now exists is a 1.8 V latch at schematic level (§3), and no I/O buffer, level shifter or boosted-wordline charge pump is designed anywhere; a macro-ready sense path or refresh controller may still need 3.3 V-class devices for those functions (an open item the README itself flags: "boosted wordline is a design decision to record"). This document does not assert either way; it is an undesigned macro-integration decision, not a rail anything committed here currently consumes. |

If Challenge #4's real (unpublished) brief forces a specific voltage split
that differs from this reconciliation, that is a rail-flavor decision this
document cannot resolve pre-publication and pre-periphery-design.

### 2.2 Harness-supplied bandgap bias voltage / current sources — not yet exercised

No bias or reference *circuit* exists in this repo as a design source. The
sense studies do use a reference level, but it is supplied by a matched
dummy reference and an ideal precharge switch that
[`design/README.md`](../../design/README.md) "Sense latch" explicitly calls
out as **"testbench elements and are not part of this cell"** — so nothing
committed here either generates or consumes a bias/reference today. Whether
this macro would consume a harness-supplied bandgap bias or generate its own
is an open architectural decision for the periphery integration that has not
been made.

### 2.3 Digital control inputs — 0 of 24 used

No macro-level digital control interface exists. A real macro would need,
at minimum, row/column address, read/write/refresh mode select, and SPI
data/clock/chip-select. Two of those three now have committed artifacts, as
**behavioral RTL only**; the third has none at all.

- **SPI control interface — behavioral RTL, plus one synthesis result.**
  [`digital/spi-control/spi_slave.v`](../../digital/spi-control/spi_slave.v)
  is a self-checking behavioral slave (16-bit `{RW, ADDR[6:0], DATA[7:0]}`
  frames; proposed register map in
  [`digital/spi-control/SPEC.md`](../../digital/spi-control/SPEC.md)), with
  crossing/reset architecture in
  [`digital/spi-crossing/`](../../digital/spi-crossing/). It is the one block
  in this repository that has also been **synthesized to sky130 standard
  cells**:
  [`digital/spi-control/results/synth_spi_slave_2026-11-11_issue273.json`](../../digital/spi-control/results/synth_spi_slave_2026-11-11_issue273.json)
  reports `status: "ok"`, `instance_count: 259` `sky130_fd_sc_hd` cells,
  `area_um2: 2750.1376` (of which `sequential_area_um2: 1516.4544`), with the
  netlist committed at
  [`spi_slave_synth_2026-11-11_issue273.v`](../../digital/spi-control/results/spi_slave_synth_2026-11-11_issue273.v).
  It is **not placed, not routed and not timing-closed**: that record's `sta`
  field is `null` (no static timing analysis was attempted) and its
  `equivalence` field is `null`; its only timing number is a `1713.62 ps`
  synthesis-time critical-path estimate. It is also the **only** synthesis
  artifact in the repository — there is no gate-level netlist for the
  scheduler, the phase sequencer or `gc_ctrl_top`, and no `.def`/`.lef`
  anywhere.
- **Read/write/refresh sequencing — behavioral RTL.**
  [`digital/refresh-scheduler/`](../../digital/refresh-scheduler/) (deadline
  scheduler), [`digital/phase-control/`](../../digital/phase-control/)
  (non-overlapping analog phase strobes), and the integrations joining them
  to the SPI path
  ([`digital/control-integration/gc_ctrl_top.v`](../../digital/control-integration/gc_ctrl_top.v),
  [`digital/sched-phase-integration/`](../../digital/sched-phase-integration/),
  [`digital/spi-sched-phase-integration/`](../../digital/spi-sched-phase-integration/)).
  All behavioral and all labelled PROPOSED by their own READMEs: none is
  synthesized, timed or CDC-signed-off.
- **Row/column address decode — does not exist, in any form.** The scheduler
  emits a row *index* (`op_row`) and carries `N_ROWS` as a declared
  ASSUMPTION ("array not designed"); nothing converts that index into the
  `wl`/`rwl` drives an array needs. The two per-bitcell signals in the
  layouts — `wl` (write wordline) and `rwl` (read wordline), per
  [`layout/README.md`](../../layout/README.md) "Topology mapping" — are
  **row-select signals internal to the array fabric**, not macro-level
  control-input pads; in the committed 4×4 array they are per-row buses
  (`wl_0`…`wl_3`, `rwl_0`…`rwl_3`) still driven straight from a testbench,
  not from decode logic.

All 24 control-input slots therefore remain unused. A slot is consumed by a
laid-out macro presenting the harness's I/O contract, and behavioral RTL
existing is not that: a Chipalooza submission's required SPI control
interface exists here as a simulated model and a synthesis estimate, **not**
as a submittable interface.

### 2.4 Digital test outputs — 0 of 12 used

No macro-level test-output signals exist. `rbl` (read bitline, per
[`layout/README.md`](../../layout/README.md)) is an analog signal on the
array fabric, not a macro-level digital test output — it would need a sense
stage between it and any digital test pad. A sense stage now exists, but
only as a schematic-level latch
([`design/sense_latch.sch`](../../design/sense_latch.sch), §3) with
provisional, unoptimized device sizes and no layout, so there is still
nothing committed that could drive a digital test pad. All 12 test-output
slots remain unused.

### 2.5 Dedicated (non-shared, low-resistance) pads — 0 of 4 used

No pad-level interface exists at the macro level; nothing to place here
yet. If a macro were built, the array's per-column bitline buses
(`bl_<c>`/`rbl_<c>`, as named in the committed 4×4 array's own net map —
[`layout/gain_cell_2t_array.parasitics.summary.json`](../../layout/gain_cell_2t_array.parasitics.summary.json))
and `sn`-adjacent sense nodes are the most likely candidates for dedicated,
low-resistance instrumentation given this block's sensitivity to
storage-node coupling (per
[`sim/retention/README.md`](../../sim/retention/README.md) "What these
numbers say (and do not say)": bitline coupling is explicitly named as an
array-level effect not yet modeled) — but this is a placement judgment
about a macro that does not exist, not a proposal committing to specific
pads today.

### 2.6 Shared (multiplexed) analog lines — 0 of 4 used

Same status as §2.5: no macro-level interface exists to place a shared
analog test line on yet.

### 2.7 Pinout summary

| Bucket | Used today | Budget |
|---|---:|---:|
| Rails | 1 (1.8 V core, this bitcell's only measured/extracted supply) | 1.8 V + 3.3 V (assumed) |
| Harness bandgap bias voltage / current sources | 0 | ≤2 |
| Digital control inputs (incl. SPI) | 0 | ≤24 |
| Digital test outputs | 0 | ≤12 |
| Dedicated pads | 0 | ≤4 |
| Shared analog lines | 0 | ≤4 |

This macro comfortably *fits* the assumed slot budget by count (a memory
macro's I/O is naturally address/data/control-bus shaped, well within
24 in / 12 out), but the budget being generously sized is not evidence the
macro itself is designed — it is not. Every bucket above reads 0 on purpose.
A slot is consumed by a laid-out macro that presents the harness's I/O
contract; what this repository has instead is a proof-of-technique array with
no decode attached, a schematic-level sense/column periphery with no layout,
and behavioral SPI/refresh RTL with no physical realization (§3) — while
row/column address decode does not exist at all. These counts are a
macro-level I/O claim and stay 0 until that macro is laid out; they are
deliberately **not** incremented for blocks that exist only as RTL or
schematics.

## 3. Functional description

**What exists:** a single **2T gain-cell bitcell** (`2T-min`, ratified
topology — [`spec/retention-refresh-budget.md`](../../spec/retention-refresh-budget.md)
§6), two NMOS devices per cell — a write-access transistor (`M_WR`, gate
`wl`, drain = storage node `sn`, source `bl`) and a read transistor
(`M_RD`, gate = `sn`, drain `rbl`, source `rwl`) — with no third
dedicated read-access device (the 2T-vs-3T decision explicitly declined 3T
as the baseline). A write pulses `wl` high, driving `sn` toward `bl`'s
level (capped at `VDD` − a threshold-voltage drop, since the wordline is
plain-`VDD`, not boosted — `design/README.md` "Wordline drive scheme"). A
read pulses `rwl` and senses `rbl` through `M_RD`, whose conduction is
gated by whatever charge remains stored on `sn` — the "gain" connection
that gives the topology its name. Being a **dynamic** storage element,
`sn` decays via the write-access transistor's off-state leakage; per this
repo's fully evidenced retention/refresh budget (§4.1), that decay sets a
hard microsecond-scale refresh requirement — this macro is honestly
positioned as trading SRAM's static hold for bitcell density, never as an
SRAM-equivalent replacement (CLAUDE.md).

**What exists beyond that bitcell,** each artifact with the status tier it
actually sits in (tiers defined in the honesty note above):

| Macro ingredient | What is committed | Tier, and what the tier means here |
|---|---|---|
| Array | A shared-tap **4×4** bitcell array: [`layout/gain_cell_2t_array.gds`](../../layout/gain_cell_2t_array.gds), top cell `gain_cell_2t_array_4x4_layout_0` — 32 transistors / 16 bits on one uniform grid inside **one** shared substrate tap ring, `13.91 × 9.75 µm` bounding box, `unrouted_nets: []`. DRC `status: "clean"` / `violation_count: 0`, and LVS `status: "match"` with 32/32 devices and 33/33 nets against the generated reference `GAIN_CELL_2T_ARRAY_4X4`. Per-net parasitics extracted ([`gain_cell_2t_array.extract.parasitics.json`](../../layout/gain_cell_2t_array.extract.parasitics.json)); two independent compact-cell variants also exist under [`layout/compact/`](../../layout/compact/). | **Proof of technique.** One fixed instance, informally checked on exactly the caveats §4.4 states for the bitcell. [`layout/README.md`](../../layout/README.md) calls it a *"proof-of-technique increment, not a macro-sized array"*: only `2x2` and `4x4` are verified sizes and **no array size is ratified**. |
| Sense stage | A latch sense stage as a design source of record: [`design/sense_latch.sch`](../../design/sense_latch.sch)/[`.spice`](../../design/sense_latch.spice) — a cross-coupled 1.8 V pair with footer and header. Characterized in [`sim/sense-stage/`](../../sim/sense-stage/) (10 corners) and [`sim/sense-mismatch/`](../../sim/sense-mismatch/) (Monte Carlo input-referred offset at four corners), and loaded by a four-row column in [`sim/loaded-column/`](../../sim/loaded-column/). | **Proposed pass conditions.** Schematic only — no layout. Sizes are *"provisional first-pass choices, not optimized"* ([`design/README.md`](../../design/README.md)), `offset_yield_validated` is still **false**, and every point sits inside the PROPOSED restricted operating range. |
| Column periphery | A designed precharge / write-driver / isolation slice, replacing the ideal sources earlier studies used: [`design/column_periphery.sch`](../../design/column_periphery.sch)/[`.spice`](../../design/column_periphery.spice), with its study in [`sim/column-periphery/`](../../sim/column-periphery/). | **Proposed pass conditions.** That study states its own limit: *"a **schematic-level** result: no layout, no extracted parasitics, global corners only (no mismatch, no Monte Carlo)"*. |
| Refresh controller | A deadline scheduler checked against the ratified interval ([`digital/refresh-scheduler/`](../../digital/refresh-scheduler/)), a phase sequencer ([`digital/phase-control/`](../../digital/phase-control/)), and the integrations joining them to the SPI path ([`digital/control-integration/`](../../digital/control-integration/), [`digital/sched-phase-integration/`](../../digital/sched-phase-integration/), [`digital/spi-sched-phase-integration/`](../../digital/spi-sched-phase-integration/)). Analog-side studies: [`sim/refresh-op/`](../../sim/refresh-op/) (simulated `t_row_refresh_op`), [`sim/refresh-replay/`](../../sim/refresh-replay/) (RTL strobes replayed into the analog deck), [`sim/refresh-energy/`](../../sim/refresh-energy/), [`sim/refresh-overhead/`](../../sim/refresh-overhead/). | **Behavioral RTL only**, and *not yet reconciled with the analog path*. `N_ROWS`/`T_ROW` are declared ASSUMPTIONs ("array not designed"), and the honest headline of [`sim/refresh-replay/`](../../sim/refresh-replay/) is that **the unmodified RTL waveform does not restore the stored level at any of the 10 corners** — a controller that *models* the deadline, not one shown to refresh this array. |
| SPI control interface | [`digital/spi-control/`](../../digital/spi-control/) (behavioral slave plus the one standard-cell synthesis result, §2.3) and [`digital/spi-crossing/`](../../digital/spi-crossing/) (crossing and reset architecture). | **Behavioral RTL only**, plus a synthesis result that is neither placed, routed nor timing-closed. |

**What still does not exist:** the macro itself, and three things it needs.

1. **Row/column address decode** — nothing anywhere converts a row index
   into `wl`/`rwl` drives (§2.3).
2. **An integrated array-plus-periphery block.** The array has no periphery
   attached, the periphery slices have no array attached, and the
   controller's strobes do not yet restore the array (above) — so there is
   no macro to carry the harness's I/O contract, which is why every bucket
   in §2 is still 0. The read transistor's sizing also remains an explicit
   placeholder — [`design/README.md`](../../design/README.md): *"not yet
   driven by a read-current or sense-margin analysis"* — so even the array
   fabric's read path is not sized against the sense stage that now exists.
3. **Any physical realization past the array fabric**: no digital layout, no
   `.def`/`.lef`, no full-macro GDS, and no post-layout PVT campaign
   (§4.5). A refresh controller that *demonstrably* keeps every row inside
   the ratified ~5.03 µs worst-case refresh interval
   ([`spec/retention-refresh-budget.md`](../../spec/retention-refresh-budget.md)
   §7) is modelled, not demonstrated.

## 4. Target specification at the challenge rails

**What this table is, and is not.** Every "Measured/derived" cell below is
re-derived **only** from what `sim/` and `layout/` actually contain today,
per this issue's own acceptance criteria — no row is relaxed, inferred
from schematic inspection alone, or borrowed from an undesigned macro.
Where this document computes a new number, it states the exact formula and
committed inputs it re-applies (never a new simulation run) so the
arithmetic is independently checkable against the cited files.

### 4.1 Single-cell retention time (`2T-min`, sky130 1.8 V core rail)

Per the fully ratified evidence chain in
[`spec/retention-refresh-budget.md`](../../spec/retention-refresh-budget.md):
measured worst-case access-device off-state leakage across a 5-process ×
3-temperature (15-point) PVT sweep
([`sim/leakage/results/leakage_results.csv`](../../sim/leakage/results/leakage_results.csv))
→ post-layout extracted storage-node capacitance `C_SN` from
[`layout/gain_cell_2t.extract.parasitics.json`](../../layout/gain_cell_2t.extract.parasitics.json)
(issue #7, superseding the earlier pre-layout assumption) → the
constant-current retention formula in
[`sim/retention/derive_retention.py`](../../sim/retention/derive_retention.py):

```
t_retention = C_SN * delta_V / I_leak
C_SN (EXTRACTED, 2T-min)      = 0.605354 fF
delta_V (ASSUMED sense margin) = 0.9 V (= VDD/2)
```

The table below applies this **same, already-committed formula** to
**every** PVT point already measured in `leakage_results.csv` (not a new
simulation — pure arithmetic re-derivation of committed inputs, reproducible
with `python3 -c` against the two cited CSV/JSON files):

| | Corner (process, temp) | `I_leak` (measured, A) | `t_retention` |
|---|---|---|---|
| **Min (worst case — sets the refresh-interval floor)** | `sf`, 125 °C | 9.898880e-11 | **5.504 µs** |
| **Typ** (`tt`, 27 °C) | `tt`, 27 °C | 1.845210e-12 | 295.261 µs |
| **Max (best case, longest)** | `fs`, −40 °C (ties `ff`/`ss`/`tt` at −40 °C, all within the model's leakage floor) | 1.810001e-12 | 301.005 µs |

**Status: MET, at the single-cell level, worst-case-corner evidence
required by CLAUDE.md.** This is the block's one fully-evidenced spec row
— device-level leakage measured at temperature corners → an extracted (not
assumed) storage-node capacitance → the retention derivation, all traceable
to committed netlists per CLAUDE.md's evidence-chain rule. It is **not** an
array-level or macro-level spec: per
[`sim/retention/README.md`](../../sim/retention/README.md) "What these
numbers say (and do not say)," bitline coupling, read-disturb during
unselected-row access, sense-amplifier offset, and array-wide
process/mismatch variation are all out of scope for this single-cell
number and would each tend to *shorten* it in a real array. The min figure
(5.504 µs, `sf`/125 °C) is what a future refresh controller must design
against, not the typ/max figures.

### 4.2 Refresh interval and bandwidth overhead

| Parameter | Value | Status | Evidence |
|---|---|---|---|
| Refresh-interval upper bound (worst case, 2x margin ASSUMPTION) | ~5.03 µs | **Ratified**, per [`spec/retention-refresh-budget.md`](../../spec/retention-refresh-budget.md) §7 | Derived as `t_retention / 2` from the spec's **ASSUMED**-`C_SN` retention row (1.106463 fF → ~10.06 µs; 10.06 / 2 = ~5.03) — **not** from §4.1's min row, which re-derives retention from the layout-*extracted* `C_SN` and gives 5.504 µs at the same worst-case corner (halving to ~2.75 µs). The 2x margin factor is itself an explicit ASSUMPTION, not a measurement. [`sim/refresh-overhead/README.md`](../../sim/refresh-overhead/README.md) records both rows and labels the extracted one *"newer evidence the spec does not yet reflect"*: ~5.03 µs is the ratified bound, ~2.75 µs is **not** ratified, and re-ratification is `spec/`'s two-key decision-record process, not this document's |
| Refresh-bandwidth overhead (numeric %) | not statable as a macro figure | **Unmet — no macro array exists to size.** An envelope now exists; the macro's `N_rows` still does not | Two committed layers, still short of a macro claim. (a) [`sim/refresh-overhead/`](../../sim/refresh-overhead/) evaluates §7's ratified formula over `N_rows` = 4…1024 (powers of two) × four `t_row_refresh_op` scenarios at the worst-case corner; it calls itself *"a refresh-cost envelope, not a macro claim"* and its phase durations are declared ASSUMPTIONs borrowed from other decks. (b) [`sim/refresh-op/`](../../sim/refresh-op/) has since **simulated** `t_row_refresh_op` at the slowest restricted corner (14 ns at a searched-minimum sense, 22 ns with the 10 ns contract sense), so that input is no longer a borrowed assumption — but `N_rows` remains one (*"array not designed"*; the scheduler RTL carries it as a parameter), and both the ratified and the extracted interval are in play. Per CLAUDE.md this document does not pick an `N_rows` to force a single percentage |

### 4.3 Bitcell topology and density

| Parameter | Value | Status | Evidence |
|---|---|---|---|
| Bitcell topology | 2T (`2T-min`), ratified | **Ratified decision**, not a measured spec row | [`spec/retention-refresh-budget.md`](../../spec/retention-refresh-budget.md) §6 |
| Density vs. 6T SRAM (must beat it to justify existing, per README) | performed; the 2T cell **loses** | **Unmet — the requirement is not satisfied, and no longer for want of a comparison.** The comparison has been run and the 2T cell does not beat the public 6T SRAM bitcell on area: about **2.79x** larger at the drawn-cell level (5.7812 µm² against 2.070 µm²) and about **4.10x** larger per bit at the 4×4 array level including its tap ring (8.4764 µm²/bit) | [`spec/density-vs-sram.md`](../../spec/density-vs-sram.md), reading [`layout/results/density_20261028_v244.json`](../../layout/results/density_20261028_v244.json). The SRAM comparator is **quoted, not measured here** — a LEF `SIZE` line for `sky130_fd_bd_sram__sram_sp_cell_opt1`, the cell OpenRAM's sky130 port instantiates — and it uses SRAM-specific foundry "push" rules against this cell's plain logic rules, so the comparison **flatters the SRAM**. No verifiable public *logic-rule* 6T sky130 area was found, so none is quoted; the stated break-even is that such a cell would have to exceed 5.78 µm² drawn / 8.48 µm² per bit at 4×4 before the 2T cell wins |
| Single-bitcell footprint (`gain_cell_2t_layout_0`) | 5.42 × 1.84 µm bounding box | Informational only — **not** an array-cell pitch (no shared tap row exists) | [`layout/README.md`](../../layout/README.md) "Bill of devices/layers" |

### 4.4 Layout sign-off status (informal, not a formal DRC/LVS release)

| Check | Result | Status |
|---|---|---|
| `klt drc --deck sky130` (bitcell **and** 4×4 array) | `status: "clean"`, `violation_count: 0` on both [`layout/gain_cell_2t.drc.result.json`](../../layout/gain_cell_2t.drc.result.json) and [`layout/gain_cell_2t_array.drc.result.json`](../../layout/gain_cell_2t_array.drc.result.json) | **Informal pass only**, on grounds that a close read of the records sharpens rather than removes (both regenerated at the pinned `klt 0.9.1` / KLayout 0.30.12). (i) *Within the deck*, coverage is better than a bare skip count suggests: `coverage.layers_checked` names **10 of the deck's 41** layers, and of the deck's 153 rules **47** are `checked` while the other **106** are classified `inapplicable` with reason `no_applicable_geometry` — none left `skipped` or `unknown`. (ii) *But the deck is not the full ruleset*: the same records list **54 `unmodeled_rules`**, sky130 rules this deck does not implement at all, including ones that do apply to this geometry (`poly.3`, `li.7`, `licon.13`, `difftap.8`–`difftap.11`, `m1.5`), and `provenance.pdk` is `null`, so no PDK stamp is recorded. `provenance.deck.released` is now `true` (it was `false` when this row was first written); that is a **klt deck-release flag, not a foundry signoff**, and must not be read as one. "Clean" therefore means clean against a partial, unstamped deck — flagged as informal by Champion's own 2026-08-26 review of this repo's tracker (issue #13) |
| `klt lvs` vs. generated schematic-equivalent reference | `status: "match"` on both: the bitcell at 2/2 devices and 6/6 nets ([`layout/gain_cell_2t.lvs.result.json`](../../layout/gain_cell_2t.lvs.result.json)), the 4×4 array at 32/32 devices and 33/33 nets against `GAIN_CELL_2T_ARRAY_4X4` ([`layout/gain_cell_2t_array.lvs.result.json`](../../layout/gain_cell_2t_array.lvs.result.json)) | **Informal pass only.** `provenance.deck.released` is `true` on these records too, so the remaining provenance caveat is `provenance.pdk: null` — no PDK stamp on either. The 2 `mismatch_count` entries on each are the known non-blocking `category_counts.topology` entries for an always-registered-but-unused device class (`pfet`), not real mismatches — [`layout/README.md`](../../layout/README.md) "Informal DRC/LVS iteration" |
| Post-layout, PVT-swept **macro-level** DRC/LVS | does not exist | **Unmet — and now narrowly, specifically so.** An array and a schematic-level periphery exist, but **no full-macro GDS exists anywhere in this repo**: the periphery has no layout at all, there is no `.def`/`.lef`, the only `.gds` files are the bitcell, its MOS/tap sub-blocks and the arrays, and nothing has been DRC/LVS'd as an *integrated macro* against a ratified macro-level spec (§4.5). The two compact-cell array variants under [`layout/compact/`](../../layout/compact/) do carry their own `clean`/`match` records, but at an **older** `klt 0.6.0` pin with narrower coverage (8 of 17 deck layers) and `deck.released: false` — weaker provenance than the two rows above, and not macro-level evidence either |

### 4.5 Post-layout PVT simulation (macro-level sign-off bar)

| Parameter | Status | Evidence |
|---|---|---|
| Post-layout PVT-corner simulation of a full macro (array + sense + refresh + SPI), against a ratified macro-level spec | **Unmet on both halves.** There is no such macro to simulate, *and* there is no ratified macro-level spec to simulate it against — the only ratified spec is device/cell-level, and the macro pass conditions remain **PROPOSED, NOT RATIFIED**. Post-layout evidence does now reach past the single cell: the 4×4 array is parasitic-extracted per net, and [`sim/refresh-energy/`](../../sim/refresh-energy/) simulates that extracted array. That is still not a macro PVT campaign — it is one extracted *fabric* instance, driven by ideal sources, with no periphery layout, and only over the restricted corner set proposed by [`spec/operating-range-decision-PROPOSED.md`](../../spec/operating-range-decision-PROPOSED.md) (**PROPOSED, NOT RATIFIED**), never the full model-corner range | [`layout/gain_cell_2t.extract.parasitics.json`](../../layout/gain_cell_2t.extract.parasitics.json), [`layout/gain_cell_2t_array.extract.parasitics.json`](../../layout/gain_cell_2t_array.extract.parasitics.json), [`sim/retention/README.md`](../../sim/retention/README.md), [`spec/macro-pass-conditions-PROPOSED.md`](../../spec/macro-pass-conditions-PROPOSED.md) (PROPOSED / NOT RATIFIED) |

## 5. Test-plan outline (measurement on the packaged part)

This test plan describes what *would* be measured once a real macro exists
and reaches the brief's sign-off bar; **it is not evidence of anything
today**. The array, sense stage, refresh controller and SPI interface that
do exist (§3) are, respectively, a 4×4 proof of technique, two schematic
slices and behavioral RTL — no integrated macro exists to bond out or test.
It mirrors
[sky130-temp-por's own Challenge #4 test-plan
structure](https://github.com/2AMLogic/sky130-temp-por/blob/main/docs/chipalooza/challenge-4-proposal.md#5-test-plan-outline-measurement-on-the-packaged-part),
the most directly comparable sibling proposal in this org, adapted to a
memory macro:

1. **Bring-up.** Confirm the SPI control interface (behavioral RTL plus one
   synthesis result today, §2.3) responds and the array powers up to a known
   state.
2. **Write/read functional sweep.** Write a checkerboard/march pattern
   across the array via the SPI-controlled row/column decode (which does not
   exist in any form, §2.3) and read it back through the sense stage
   (schematic-level latch only, §3), at nominal `VDD`/25 °C, then at the PVT
   extremes the sign-off bar requires.
3. **Retention-time measurement.** Write a known pattern, hold with refresh
   disabled for a swept dwell time, then read back and measure the
   bit-error rate vs. dwell time — the direct silicon analog of §4.1's
   single-cell derivation, at array scale and across PVT. This is the
   single most important measurement this test plan defines, since it is
   the first point where an array-level number could be compared against
   this document's single-cell estimate.
4. **Refresh-interval margin sweep.** With refresh enabled at a
   programmable interval (the SPI register that would set it is behavioral
   RTL today, §2.3), sweep the interval from below to above the §4.2
   ratified ~5.03 µs bound and find the actual failure point at each PVT
   corner reachable on the bench. This is also the measurement that would
   settle the ratified-versus-extracted `C_SN` split §4.2 records, which no
   amount of simulation has settled.
5. **Sense-margin characterization.** Characterize the sense stage's
   offset/noise floor on silicon, to replace this document's
   `delta_V = VDD/2` ASSUMPTION (§4.1) with a measured value. Simulation has
   taken a first pass already —
   [`sim/sense-mismatch/`](../../sim/sense-mismatch/) fits an input-referred
   offset sigma for the current latch at four corners — but that latch
   carries provisional sizes, keeps `offset_yield_validated` **false**, and
   sits under the PROPOSED range, so it replaces nothing in §4.1.
6. **Quiescent/refresh current.** Source-meter on `VDD`, measured
   separately during idle-with-refresh, active read, and active write, to
   produce the numeric refresh-bandwidth-overhead figure §4.2 still cannot
   state as a macro result. `t_row_refresh_op` has since been *simulated* at
   the restricted corners ([`sim/refresh-op/`](../../sim/refresh-op/)), and
   refresh energy estimated on the extracted array
   ([`sim/refresh-energy/`](../../sim/refresh-energy/)); what is missing for
   that figure is a ratified `N_rows` and silicon, not a formula.
7. **Temperature corner sweep.** Repeat steps 3–4 in a temperature chamber
   at **+27 °C and +125 °C** — the interval proposed by
   [`spec/operating-range-decision-PROPOSED.md`](../../spec/operating-range-decision-PROPOSED.md),
   which is **PROPOSED and NOT RATIFIED**: it ratifies nothing pending
   two-key signature, so no restricted operating range named here is a
   settled specification. **−40 °C is a characterization-only corner,
   deliberately outside the proposed interval, and must not be read as an
   operating corner.** That record excludes it precisely because the
   loaded-column read path **fails** at `fs`/−40 °C at both ages, with
   `ss`/−40 °C logged as a marginal conflict rather than silently resolved.
   The two directions do not contradict each other: §4.1's device-level
   leakage sweep *does* include −40 °C, where leakage is lowest and
   retention therefore longest (it is §4.1's best-case row) — the −40 °C
   failure is in the sense path, not in retention. Sweeping −40 °C anyway
   remains worth doing to locate the real cold boundary, which that record
   places somewhere in (−40 °C, 27 °C] and explicitly declines to
   interpolate; but that is a characterization goal, not a corner this
   proposal claims to operate at.

## 6. Category note — memory macro, mixed-signal by construction

This is a digital-facing IP block (an addressable memory array behind an
SPI control interface) built from an inherently analog storage mechanism
(a dynamically decaying charge on an internal node, sensed through a
transistor's conduction). It should be evaluated as **mixed-signal IP**,
not pure digital: its core spec — retention time — is a PVT-corner analog
leakage measurement (§4.1), not a digital timing closure number, even
though its intended control interface is a standard digital SPI bus.

## Licensing

This repository is Apache License 2.0 ([`LICENSE`](../../LICENSE)),
matching the challenge's stated preference for a standard open license.
All modifiable sources — the schematic
([`design/gain_cell_2t.sch`](../../design/gain_cell_2t.sch)), the derived
netlist ([`design/gain_cell_2t.spice`](../../design/gain_cell_2t.spice)),
the committed layout ([`layout/gain_cell_2t.gds`](../../layout/gain_cell_2t.gds)),
every testbench and result
([`sim/leakage/`](../../sim/leakage/), [`sim/retention/`](../../sim/retention/)),
and the ratified spec/decision records
([`spec/`](../../spec/)) — are public in this repository under that same
license. No separate licensing action would be needed for a future
submission.

## Verification flow (open-source EDA)

- **Schematic entry / simulation**: [xschem](https://xschem.sourceforge.io/)
  + [ngspice](https://ngspice.sourceforge.io/), against the open
  [SkyWater sky130](https://github.com/google/skywater-pdk) PDK
  ([`design/env.sh`](../../design/env.sh), [`design/xschemrc`](../../design/xschemrc)).
- **Layout / DRC / LVS**: [klayout-tools](https://github.com/2AMLogic/klayout-tools)
  (`klt`), a headless, scriptable KLayout-based flow — used for the
  bitcell's geometry capture and informal DRC/LVS iteration
  ([`layout/generate.sh`](../../layout/generate.sh)) and, since then, at
  **array** scale: the 4×4 array is generated, DRC'd, LVS'd and
  parasitic-extracted through the same flow
  ([`layout/generate_array.sh`](../../layout/generate_array.sh)), with
  compact-cell variants drawn via KLayout's Python API in
  [`layout/compact/`](../../layout/compact/). The same toolchain produced the
  one gate-level synthesis result (§2.3). It is **not** yet exercised at
  macro scale: no place-and-route and no macro-level DRC/LVS.
- No proprietary EDA tool is used anywhere in this design's flow, or is
  expected to be needed for any future step.

## Next steps — what this document does and does not claim

**This document satisfies this issue's
(2AMLogic/sky130-gcedram#20) proposal-document acceptance criteria**: block
type (§1), I/O honestly mapped against the assumed slot budget including
the 1.8 V/3.3 V rail reconciliation (§2), a functional description that
states plainly what exists, at which status tier, and what does not (§3),
and a spec table whose every row states a met/unmet verdict against real
`design/`/`digital/`/`sim/`/`layout/` evidence (§4) — including the one row
(§4.1, single-cell retention time) that is genuinely met, and every other
row (macro-level PVT sim, formal DRC/LVS, refresh-bandwidth percentage,
density-vs-SRAM comparison) stated honestly as unmet, not fabricated or
inferred from schematic inspection alone, with the *reason* for each kept
current: several are now unmet because a committed increment falls short,
not because nothing exists.

**It does not claim the brief's full sign-off bar** — post-layout PVT
simulation and DRC/LVS-clean GDS **of the actual submittable macro**
in-repo — which does not exist to claim. This gap is real, not a scope
choice this document could paper over. Stated as what *remains*, now that
several of the prerequisites have partly landed:

| Prerequisite | State |
|---|---|
| An array with a shared tap/well structure | **Done as a proof of technique** — the 4×4 array (§3, §4.4). Remains: a parameterized array with a *ratified* row/column count; only `2x2` and `4x4` are verified and no size is ratified |
| A sense stage | **Schematic-level, done; neither sized nor laid out** (§3). Remains: sizing driven by a read-current/sense-margin analysis, an offset/yield result (`offset_yield_validated` is still false), and layout |
| Row/column address decode | **Not started** — nothing converts a row index into `wl`/`rwl` drives (§2.3) |
| A refresh controller against the §4.2 ratified ~5.03 µs bound | **Behavioral RTL, done; not reconciled with the analog path** — the unmodified RTL refresh waveform does not restore the stored level at any simulated corner ([`sim/refresh-replay/`](../../sim/refresh-replay/)). Remains: a waveform that restores, then synthesis and timing |
| An SPI control interface | **Behavioral RTL, done; this one block synthesized** (§2.3). Remains: place-and-route, timing closure, and physical CDC/reset sign-off |
| Integration of all of it into one macro, then its layout | **Not started.** No `.def`/`.lef`, no full-macro GDS |
| Post-layout PVT re-simulation of that macro | **Not started**, and it needs a *ratified* macro-level spec to be graded against; the pass conditions are still PROPOSED ([`spec/macro-pass-conditions-PROPOSED.md`](../../spec/macro-pass-conditions-PROPOSED.md)) |
| Formal (full-ruleset, PDK-stamped) DRC/LVS | **Not started.** Today's records are deck-partial and carry `provenance.pdk: null` (§4.4) |

That is a multi-issue body of engineering work, not a single-session
extension of this proposal. It is tracked as epic
[#24](https://github.com/2AMLogic/sky130-gcedram/issues/24),
cross-referenced from this repo's existing T1/bronze gap tracker (issue
[#13](https://github.com/2AMLogic/sky130-gcedram/issues/13)) rather than
duplicating it.

---

*Full evidence trail:
[`spec/retention-refresh-budget.md`](../../spec/retention-refresh-budget.md)
(the ratified retention/refresh evidence chain and 2T-vs-3T decision),
[`spec/retention-literature-crosscheck.md`](../../spec/retention-literature-crosscheck.md)
(literature cross-check),
[`spec/density-vs-sram.md`](../../spec/density-vs-sram.md) (the §4.3 density
comparison), and the **PROPOSED, not ratified** records
([`spec/operating-range-decision-PROPOSED.md`](../../spec/operating-range-decision-PROPOSED.md),
[`spec/macro-pass-conditions-PROPOSED.md`](../../spec/macro-pass-conditions-PROPOSED.md)
and the other `spec/*-PROPOSED.md` files — none of which may be quoted as a
macro specification);
[`sim/leakage/`](../../sim/leakage/) (device-level PVT leakage sweep),
[`sim/retention/`](../../sim/retention/) (retention-time derivation, now
extraction-based for `2T-min`),
[`sim/sense-stage/`](../../sim/sense-stage/),
[`sim/sense-mismatch/`](../../sim/sense-mismatch/),
[`sim/loaded-column/`](../../sim/loaded-column/) and
[`sim/column-periphery/`](../../sim/column-periphery/) (the sense path),
[`sim/refresh-op/`](../../sim/refresh-op/),
[`sim/refresh-replay/`](../../sim/refresh-replay/),
[`sim/refresh-energy/`](../../sim/refresh-energy/) and
[`sim/refresh-overhead/`](../../sim/refresh-overhead/) (the refresh path);
[`design/`](../../design/) (bitcell, sense-latch and column-periphery
schematics + derived netlists),
[`digital/`](../../digital/) (behavioral control RTL, its regressions and
mutation runs, and the one standard-cell synthesis result),
[`layout/`](../../layout/) (bitcell and 4×4 array GDS + informal DRC/LVS +
post-layout parasitic extraction) with
[`layout/compact/`](../../layout/compact/) (compact-cell array variants),
[`layout/README.md`](../../layout/README.md) and
[`design/README.md`](../../design/README.md) (maturity/scope caveats cited
throughout this document), and this repo's T1/bronze gap tracker
([issue #13](https://github.com/2AMLogic/sky130-gcedram/issues/13)) for the
generic (not Chipalooza-specific) accounting of what remains before this
block reaches sim-validated/bronze maturity.*
