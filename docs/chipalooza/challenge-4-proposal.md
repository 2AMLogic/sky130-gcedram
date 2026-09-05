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

**Honesty note, stated once here rather than repeated on every row.** This
repository is at **single-bitcell maturity**, not macro maturity: the
retention/refresh-budget evidence chain is fully ratified
(`spec/retention-refresh-budget.md`), and a single `2T-min` gain-cell
bitcell has committed design sources
([`design/gain_cell_2t.sch`](../../design/gain_cell_2t.sch)/
[`.spice`](../../design/gain_cell_2t.spice)) and a committed layout
([`layout/gain_cell_2t.gds`](../../layout/gain_cell_2t.gds)) with an
*informal* DRC-clean/LVS-match iteration behind it (see §4.4). **No array,
no sense amplifier, no refresh controller, and no SPI control interface
exist anywhere in this repository** — this macro, as a submittable IP
block with the harness's I/O contract, has not been designed yet. Per
CLAUDE.md's "no claim without a testbench" and this issue's own acceptance
criteria, every spec-table row below states its status against what
`sim/`/`layout/` actually contain today, not against schematic inspection
or an aspirational macro that does not yet exist. This is not a defect
this document introduces or a spec being relaxed to pass — it is an
honest snapshot of where the block actually is on its own maturity ladder
(`README.md`: *"Current position: retention/refresh budget ratified —
bitcell + array simulation next"*).

---

## 1. Type of IP block

An embedded DRAM (eDRAM) memory macro: a 2T gain-cell bitcell array with
sense and refresh periphery (periphery not yet designed — see §3). This is
**not** an SRAM and must never be described as a drop-in replacement for
one (per CLAUDE.md): a gain cell is a *dynamic* storage element that trades
SRAM's static hold for bitcell density, and its retention/refresh budget is
the centerpiece of its spec, not a footnote.

## 2. I/O list, including test ports

### 2.1 Rails — this bitcell's device-level evidence is 1.8 V-only; periphery rail is an open item

Every device in the only design source this repo has —
[`design/gain_cell_2t.sch`](../../design/gain_cell_2t.sch) — is
`sky130_fd_pr__nfet_01v8`, sky130's core **1.8 V** NMOS
([`design/README.md`](../../design/README.md) "Topology: 2T, ratified":
*"Two devices, both `sky130_fd_pr__nfet_01v8`... no other `sky130_fd_pr`
flavour appears anywhere in this schematic"*). The wordline drive scheme
is explicitly **plain 1.8 V, not boosted**
([`design/README.md`](../../design/README.md) "Wordline drive scheme"),
consistent with the repo README's own "Supply" row: *"sky130 standard
1.8 V core; boosted wordline is a design decision to record."*

| Harness rail (assumed common structure) | This block's use |
|---|---|
| 1.8 V digital | **This bitcell's only supply.** Every measured/extracted evidence point in this document (leakage, retention, DRC/LVS) is against `nfet_01v8` at `VDD` = 1.8 V. |
| 3.3 V analog | **Not yet exercised by anything committed in this repo.** A real sense amplifier and refresh controller — neither of which exist yet (§3) — may need 3.3 V-class devices for I/O buffering or a boosted-wordline charge pump (an open item the README itself flags: "boosted wordline is a design decision to record"). This document does not assert either way; it is an undesigned periphery decision, not a rail this bitcell currently consumes. |

If Challenge #4's real (unpublished) brief forces a specific voltage split
that differs from this reconciliation, that is a rail-flavor decision this
document cannot resolve pre-publication and pre-periphery-design.

### 2.2 Harness-supplied bandgap bias voltage / current sources — not yet exercised

No bias/reference circuit of any kind exists in this repo yet (no
sense-amplifier or refresh-controller design has started, per §3). Whether
this macro would consume a harness-supplied bandgap bias or generate its
own is an open architectural decision for the periphery design that has
not been made.

### 2.3 Digital control inputs — 0 of 24 used

No macro-level digital control interface exists. The two per-bitcell
signals that exist in the single-cell layout —`wl` (write wordline) and
`rwl` (read wordline), per
[`layout/README.md`](../../layout/README.md) "Topology mapping" — are
**bitcell-internal row-select signals**, not macro-level control-input
pads: in a real array, `wl`/`rwl` fan out from row-decode logic that does
not exist yet, not from a harness pin directly. A real macro would need,
at minimum, row/column address, read/write/refresh mode select, and SPI
data/clock/chip-select — none of that decode, sequencing, or SPI logic is
designed. All 24 control-input slots remain unused; none of a Chipalooza
submission's required SPI control interface exists in this repo.

### 2.4 Digital test outputs — 0 of 12 used

No macro-level test-output signals exist. `rbl` (read bitline, per
[`layout/README.md`](../../layout/README.md)) is a per-bitcell analog
signal, not a macro-level digital test output — it would need a sense
amplifier (not yet designed) between it and any digital test pad. All 12
test-output slots remain unused.

### 2.5 Dedicated (non-shared, low-resistance) pads — 0 of 4 used

No pad-level interface exists at the macro level; nothing to place here
yet. If a macro were built, the array's bitline pair (`bl`/`rbl`) and
`sn`-adjacent sense nodes are the most likely candidates for dedicated,
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
macro itself is designed — it is not. Every bucket above is unused because
the row/column decode, sense/refresh periphery, and SPI control logic that
would consume these slots do not exist in this repository yet.

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

**What does not exist:** everything needed to turn one bitcell into a
submittable memory macro — an array (row/column replication with a shared
tap/well structure, not the isolated single-cell layout this repo has
today per [`layout/README.md`](../../layout/README.md) "Bill of
devices/layers": *"a single bitcell in isolation, not an array cell with a
shared tap row"*), row/column address decode, a sense amplifier (the read
transistor's sizing today is an explicit placeholder — `design/README.md`:
*"not yet driven by a read-current or sense-margin analysis... no
sense-amplifier design exists yet"*), a refresh controller that keeps every
row inside the ratified ~5.03 µs worst-case refresh interval
([`spec/retention-refresh-budget.md`](../../spec/retention-refresh-budget.md)
§7), and an SPI control interface. None of this periphery is designed,
simulated, or laid out anywhere in this repository as of this document.

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
| Refresh-interval upper bound (worst case, 2x margin ASSUMPTION over §4.1's min) | ~5.03 µs | **Ratified**, per [`spec/retention-refresh-budget.md`](../../spec/retention-refresh-budget.md) §7 | Derived directly from §4.1's min row; the 2x margin factor is an explicit ASSUMPTION, not a measurement |
| Refresh-bandwidth overhead (numeric %) | not derivable | **Unmet — no array/periphery design exists.** Formula is ratified (§7); `N_rows` and `t_row_refresh_op` are undetermined, and per CLAUDE.md this document does not invent them to force a percentage | [`spec/retention-refresh-budget.md`](../../spec/retention-refresh-budget.md) §7 explicitly declines to substitute placeholder values for this reason |

### 4.3 Bitcell topology and density

| Parameter | Value | Status | Evidence |
|---|---|---|---|
| Bitcell topology | 2T (`2T-min`), ratified | **Ratified decision**, not a measured spec row | [`spec/retention-refresh-budget.md`](../../spec/retention-refresh-budget.md) §6 |
| Density vs. 6T SRAM (must beat it to justify existing, per README) | not performed | **Unmet — no comparison has been run.** No public OpenRAM area figure has been pulled and compared against this bitcell's extracted layout footprint | README "Target specification": *"comparison against public OpenRAM documentation — not yet performed"* |
| Single-bitcell footprint (`gain_cell_2t_layout_0`) | 5.42 × 1.84 µm bounding box | Informational only — **not** an array-cell pitch (no shared tap row exists) | [`layout/README.md`](../../layout/README.md) "Bill of devices/layers" |

### 4.4 Layout sign-off status (informal, not a formal DRC/LVS release)

| Check | Result | Status |
|---|---|---|
| `klt drc --deck sky130` | `status: "clean"`, `violation_count: 0` | **Informal pass only.** [`layout/gain_cell_2t.drc.result.json`](../../layout/gain_cell_2t.drc.result.json) reports `coverage.layers_checked` covering **6 of 16** deck-defined layers, with a long `rules_skipped` list (met2–met5, all via layers, MiM caps), and `provenance.deck.released: false` / `provenance.pdk: null`. "Clean" here reflects a still-partial `klt` sky130 rule-deck coverage, not a formal, full-ruleset DRC signoff — flagged as such by Champion's own 2026-08-26 review of this repo's tracker (issue #13) |
| `klt lvs` vs. schematic-equivalent reference | `status: "match"`, 2/2 devices matched, 6/6 nets matched | **Informal pass only**, same caveat: `provenance.deck.released: false`. The 2 `mismatch_count` entries are known non-blocking `severity: "warning"` topology entries for an always-registered-but-unused device class (`pfet`), not real mismatches — [`layout/README.md`](../../layout/README.md) "Informal DRC/LVS iteration" |
| Post-layout, PVT-swept macro-level DRC/LVS | does not exist | **Unmet.** No array, no periphery, no full-macro GDS exists anywhere in this repo | — |

### 4.5 Post-layout PVT simulation (macro-level sign-off bar)

| Parameter | Status | Evidence |
|---|---|---|
| Post-layout PVT-corner simulation of a full macro (array + sense + refresh + SPI), against a ratified macro-level spec | **Unmet — no such macro exists to simulate.** The only post-layout evidence in this repo is the single-cell storage-node parasitic extraction feeding §4.1's retention re-derivation, which is not a PVT *simulation* campaign (it is a deterministic single-corner extraction combined with an already-measured device-level PVT sweep) | [`layout/gain_cell_2t.extract.parasitics.json`](../../layout/gain_cell_2t.extract.parasitics.json), [`sim/retention/README.md`](../../sim/retention/README.md) |

## 5. Test-plan outline (measurement on the packaged part)

This test plan describes what *would* be measured once a real macro exists
and reaches the brief's sign-off bar; **it is not evidence of anything
today** — no array, sense amp, refresh controller, or SPI interface exists
to bond out or test. It mirrors
[sky130-temp-por's own Challenge #4 test-plan
structure](https://github.com/2AMLogic/sky130-temp-por/blob/main/docs/chipalooza/challenge-4-proposal.md#5-test-plan-outline-measurement-on-the-packaged-part),
the most directly comparable sibling proposal in this org, adapted to a
memory macro:

1. **Bring-up.** Confirm the SPI control interface (not yet designed)
   responds and the array powers up to a known state.
2. **Write/read functional sweep.** Write a checkerboard/march pattern
   across the array via the SPI-controlled row/column decode (not yet
   designed) and read it back through the sense amplifier (not yet
   designed), at nominal `VDD`/25 °C, then at PVT extremes.
3. **Retention-time measurement.** Write a known pattern, hold with refresh
   disabled for a swept dwell time, then read back and measure the
   bit-error rate vs. dwell time — the direct silicon analog of §4.1's
   single-cell derivation, at array scale and across PVT. This is the
   single most important measurement this test plan defines, since it is
   the first point where an array-level number could be compared against
   this document's single-cell estimate.
4. **Refresh-interval margin sweep.** With refresh enabled at a
   programmable interval (via SPI, not yet designed), sweep the interval
   from below to above the §4.2 ratified ~5.03 µs bound and find the
   actual failure point at each PVT corner reachable on the bench.
5. **Sense-margin characterization.** Characterize the sense amplifier's
   (not yet designed) offset/noise floor directly, to replace this
   document's `delta_V = VDD/2` ASSUMPTION (§4.1) with a measured value.
6. **Quiescent/refresh current.** Source-meter on `VDD`, measured
   separately during idle-with-refresh, active read, and active write, to
   produce the numeric refresh-bandwidth-overhead figure §4.2 currently
   cannot compute for lack of `N_rows`/`t_row_refresh_op`.
7. **Temperature corner sweep.** Repeat steps 3–4 in a temperature chamber
   at −40 °C and +125 °C, the same corners this repo's device-level
   leakage evidence (§4.1) already treats as worst case.

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
  (`klt`), a headless, scriptable KLayout-based flow — used for the single
  bitcell's geometry capture and informal DRC/LVS iteration
  ([`layout/generate.sh`](../../layout/generate.sh)); not yet exercised at
  array/macro scale.
- No proprietary EDA tool is used anywhere in this design's flow, or is
  expected to be needed for any future step.

## Next steps — what this document does and does not claim

**This document satisfies this issue's
(2AMLogic/sky130-gcedram#20) proposal-document acceptance criteria**: block
type (§1), I/O honestly mapped against the assumed slot budget including
the 1.8 V/3.3 V rail reconciliation (§2), a functional description that
states plainly what exists and what does not (§3), and a spec table whose
every row states a met/unmet verdict against real `sim/`/`layout/` evidence
(§4) — including the one row (§4.1, single-cell retention time) that is
genuinely met, and every other row (macro-level PVT sim, formal DRC/LVS,
refresh-bandwidth percentage, density-vs-SRAM comparison, SPI/array/sense/
refresh existence) stated honestly as unmet, not fabricated or inferred
from schematic inspection alone.

**It does not claim the brief's full sign-off bar** — post-layout PVT
simulation and DRC/LVS-clean GDS **of the actual submittable macro**
in-repo — which does not exist to claim. Per this issue's own instructions,
this gap is real, not a scope choice this document could paper over:
reaching that bar requires, in order, an array with a shared tap/well
structure (the current layout is an isolated single cell,
[`layout/README.md`](../../layout/README.md)), a sense amplifier (the
current read-transistor sizing is an explicit placeholder,
[`design/README.md`](../../design/README.md)), a refresh controller
designed against the §4.2 ratified ~5.03 µs bound, an SPI control
interface, then layout of that entire macro, then post-layout PVT
re-simulation, then formal (full-ruleset) DRC/LVS. That is a multi-issue
body of engineering work, not a single-session extension of this proposal.
A follow-up issue tracking the concrete next increment toward that macro
is filed and cross-referenced from this repo's existing T1/bronze gap
tracker (issue #13) rather than duplicating it.

---

*Full evidence trail:
[`spec/retention-refresh-budget.md`](../../spec/retention-refresh-budget.md)
(the ratified retention/refresh evidence chain and 2T-vs-3T decision),
[`spec/retention-literature-crosscheck.md`](../../spec/retention-literature-crosscheck.md)
(literature cross-check),
[`sim/leakage/`](../../sim/leakage/) (device-level PVT leakage sweep),
[`sim/retention/`](../../sim/retention/) (retention-time derivation, now
extraction-based for `2T-min`),
[`design/`](../../design/) (bitcell schematic + derived netlist),
[`layout/`](../../layout/) (bitcell GDS + informal DRC/LVS + post-layout
parasitic extraction),
[`layout/README.md`](../../layout/README.md) and
[`design/README.md`](../../design/README.md) (maturity/scope caveats cited
throughout this document), and this repo's T1/bronze gap tracker
([issue #13](https://github.com/2AMLogic/sky130-gcedram/issues/13)) for the
generic (not Chipalooza-specific) accounting of what remains before this
block reaches sim-validated/bronze maturity.*
