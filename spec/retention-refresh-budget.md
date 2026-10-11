# Retention/refresh budget: ratified basis for the 2T vs 3T decision (issue #5)

**Status: RATIFIED.** This is the exit criterion for the retention/refresh
budget study (#1): it assembles the full evidence chain CLAUDE.md requires —
device-level leakage at temperature corners (#2) → an explicitly labelled
storage-node capacitance assumption (#3) → the retention-time derivation (#3)
→ a literature cross-check (#4) — into the ratified basis for (a) the
bitcell topology decision (2T vs 3T) and (b) the refresh bandwidth overhead.
Per CLAUDE.md: "a retention number without its chain is not a result." This
document is self-contained: a reader who has not seen #2, #3, or #4 can
follow it end to end without opening those issues, though every number below
links back to the committed netlist or write-up that produced it.

> Section 9 (issue #89) is a **PROPOSED, not ratified** addition about
> array-context storage-node inputs. It changes none of the ratified values
> in Sections 5–8.

## 1. The evidence chain, summarized

| Link | What it establishes | Committed evidence |
|---|---|---|
| 1. Device-level leakage (#2) | Worst-case off-state access-device leakage (subthreshold + junction) across sky130 PVT corners | [`sim/leakage/tb_access_leakage.spice.tmpl`](../sim/leakage/tb_access_leakage.spice.tmpl), [`sim/leakage/results/leakage_results.csv`](../sim/leakage/results/leakage_results.csv), write-up in [`sim/leakage/README.md`](../sim/leakage/README.md) |
| 2. Storage-node capacitance assumption (#3) | An explicitly labelled `C_SN` ASSUMPTION per candidate geometry (no layout exists yet to extract parasitics from) | [`sim/retention/README.md`](../sim/retention/README.md) "Storage-node capacitance: computed term + ASSUMED margin" |
| 3. Retention derivation (#3) | `t_retention = C_SN * delta_V / I_leak`, evaluated at the worst-case corner, for both `2T-min` and `3T-min` candidate geometries | [`sim/retention/derive_retention.py`](../sim/retention/derive_retention.py), [`sim/retention/results/retention_results.csv`](../sim/retention/results/retention_results.csv), write-up in [`sim/retention/README.md`](../sim/retention/README.md) |
| 4. Literature cross-check (#4) | Independent sanity check of the derived numbers against three published, silicon-measured gain-cell results | [`spec/retention-literature-crosscheck.md`](retention-literature-crosscheck.md) |

The device-level leakage number (link 1) is **measured** by ngspice
simulation against the shipped sky130 BSIM4 model — not assumed, not
estimated. The storage-node capacitance (link 2) is an **explicit
ASSUMPTION**, because no layout exists yet to extract real parasitics from.
The retention time (link 3) **combines** the two. The literature cross-check
(link 4) is neither a measurement nor an assumption made by this repo — it is
an external sanity check against independently published, fabricated
silicon.

## 2. Worst-case leakage input (recap of #2)

Per [`sim/leakage/README.md`](../sim/leakage/README.md), a 5-process-corner x
3-temperature sweep (15 PVT points, satisfying CLAUDE.md's "PVT corners on
every recorded result") against `sky130_fd_pr__nfet_01v8` (W = 0.42 µm,
L = 0.15 µm, the minimum drawn size the shipped model supports) found the
worst-case (maximum) leakage point at:

**`sf` process corner, 125 °C: `I_leak = 9.898880e-11 A` (~99 pA).**

This is the highest of the 15 measured points, so it is the correct
worst-case input per CLAUDE.md's "Retention claims are made at the
worst-case temperature corner, not typicals" — both candidate topologies
below use this exact, single measured number.

## 3. Candidate geometries and their retention estimates (recap of #3)

Both candidates share the *same* access device and the *same* measured
leakage number (link 1) — nothing about the retention derivation itself
gives one topology a leakage advantage. What differs is the **storage-node
capacitance assumption**, driven by a qualitative topology judgment about
routing proximity (see [`sim/retention/README.md`](../sim/retention/README.md)
"Candidate geometries"):

| Geometry | Topology | `C_SN` (ASSUMED) | Margin factor (ASSUMPTION) | `delta_V` (ASSUMED) | `I_leak` (measured, `sf`/125 °C) | `t_retention` |
|---|---|---|---|---|---|---|
| `2T-min` | 2T | 1.106463 fF | 2.0x over gate-oxide `C_gate` | 0.9 V (`VDD`/2) | 9.898880e-11 A | **~10.06 µs** |
| `3T-min` | 3T | 2.212925 fF | 4.0x over gate-oxide `C_gate` | 0.9 V (`VDD`/2) | 9.898880e-11 A | **~20.12 µs** |

**Important qualifier, carried forward from #3 and #4 and load-bearing for
the topology decision below**: `3T-min`'s ~2x longer retention estimate is
**entirely an artifact of the assumed capacitance margin factor** (4.0x vs
2.0x — a pre-layout engineering judgment about how much closer M3's routing
sits to the storage node, not a measured or physically derived quantity). It
is **not** a leakage-based advantage: M3 is not DC-connected to the storage
node in the 3T topology, so the identical measured leakage number from #2
applies to both candidates. A different, equally defensible margin-factor
assumption could close or reverse this gap without changing anything else in
the derivation. **The retention evidence, taken alone, does not establish a
genuine retention advantage for 3T over 2T.**

## 4. Literature cross-check (recap of #4)

Per [`spec/retention-literature-crosscheck.md`](retention-literature-crosscheck.md),
both this repo's `2T-min` (~10.06 µs) and `3T-min` (~20.12 µs) sit well below
every cited comparator (three IEEE-published, silicon-measured gain-cell
results spanning 65 nm to 16 nm, clustering in a 50–110 µs band for
"conventional" 2T/3T topologies) — `2T-min` by ~11x, `3T-min` by ~4x. The
leading hypothesis, from that document's divergence analysis, is that this
repo's pre-layout `C_SN` assumption is undersized relative to the real,
deliberately-sized storage nodes in published silicon; this is flagged there
as motivation to re-derive `C_SN` post-layout (#7), not as a defect specific
to either topology. **The cross-check document itself concludes it "does not
change the 2T-vs-3T topology decision"** — both candidates diverge from
their closest published comparator by a similar order of magnitude, so
neither is favored by this comparison.

## 5. Ratified retention time

**The ratified retention time, at the worst-case corner, for the ratified
topology (2T — see Section 6), is:**

```
t_retention (worst case, sf corner, 125 C) = ~10.06 us  (1.005989e-05 s)
```

This is a **pre-layout, single-cell** estimate: a single storage node, a
single access device's measured leakage, and an assumed sense margin
(`delta_V = VDD/2`, see [`sim/retention/README.md`](../sim/retention/README.md)
"Sense margin"). It is **not** an array-level or macro-level spec — bitline
coupling, read-disturb during unselected-row access, sense-amplifier offset
in a real design, and array-wide process/mismatch variation are all out of
scope for this single-cell derivation and would each tend to *shorten* the
effective retention window relative to this estimate, per
[`sim/retention/README.md`](../sim/retention/README.md) "What these numbers
say (and do not say)." Per CLAUDE.md: "Never describe the macro as a drop-in
SRAM replacement" — a retention window in the tens-of-microseconds range at
worst case is the dynamic-storage tradeoff this block exists to make
explicit, not a defect to explain away.

## 6. Topology decision: 2T, ratified

**Decision: this macro's baseline bitcell topology is ratified as 2T
(`2T-min`).** 3T remains a documented alternative for a future revisit
(see Section 8), but is not the ratified baseline.

### Rationale

1. **The retention evidence does not favor 3T.** As established in Section 3,
   the ~2x retention gap between `3T-min` and `2T-min` traces entirely to an
   assumed capacitance margin factor, not to a measured or physically
   grounded leakage difference — both topologies share the identical
   measured leakage number from #2, because M3 is not DC-connected to the
   storage node in the 3T topology. Choosing 3T on the strength of this 2x
   figure would mean ratifying a topology decision on an artifact of an
   admittedly-uncalibrated pre-layout assumption, which CLAUDE.md's evidence-chain
   discipline exists specifically to prevent ("agents do not relax the
   ratified spec to make results pass" applies equally to *inflating* a
   decision's apparent evidentiary basis).

2. **Density is a stated, hard requirement this topology exists to meet.**
   Per the README's target specification: "Density vs SRAM: must beat a 6T
   SRAM bitcell on area to justify existing." A 2T cell is, by construction,
   smaller than a 3T cell of the same technology and device sizing — every
   array instance of the extra read-access transistor M3 works directly
   against the primary reason this macro exists over a conventional 6T SRAM
   array. With no retention-based reason (per point 1) to accept that area
   cost, the density requirement is decisive.

3. **3T's genuine, literature-documented advantage is a data-integrity
   property, not a retention-time property, and is out of this study's
   measured scope.** The classic 3T motivation (see
   [`sim/retention/README.md`](../sim/retention/README.md) "Candidate
   geometries") is that M3 isolates the read bitline swing from the storage
   node, avoiding the read-disturb / bitline-coupling risk inherent to 2T,
   where the storage node's gate (M2) has its drain tied directly to the
   read bitline being sensed. This is a real concern, but it is an
   array-level, sense-scheme-dependent effect that neither #2's leakage
   testbench nor #3's single-cell retention derivation measures or models —
   there is no committed evidence, one way or the other, on how severe this
   effect is for this macro's eventual sense/refresh periphery. Per
   CLAUDE.md's "no claim without a testbench," this decision record does not
   assert a magnitude for that risk; it is named here as the concrete,
   documented reason a future revisit of this decision is plausible (see
   Section 8), not as evidence against 2T today.

4. **Neither topology is favored by the literature cross-check.** Per
   Section 4, both candidates diverge from their closest published
   comparator by a similar order of magnitude, so #4 provides no basis to
   prefer one topology over the other on retention grounds.

**Net**: with the retention-time evidence found (Section 3, Section 4) to be
topology-neutral once the capacitance-assumption artifact is discounted, the
decision reduces to the one requirement this study's evidence *does* bear on
decisively — density — which favors 2T. The 3T read-disturb argument is
real but currently unquantified, and is recorded as the named condition
under which this ratified decision should be revisited, not as a reason to
defer the decision itself.

## 7. Refresh budget, as a bandwidth overhead

The refresh interval must not exceed the ratified worst-case retention time
(Section 5), with margin. This repo assumes a conservative **2x safety
margin** between the theoretical single-cell decay bound and the actual
refresh interval design uses — an explicit ASSUMPTION, chosen because
Section 5 already establishes that several array-level effects not modeled
by the single-cell derivation (bitline coupling, read disturb,
sense-amplifier offset, array-wide mismatch) would each tend to *shorten*
the true retention window relative to the single-cell estimate:

```
refresh_interval (ASSUMED, 2x margin) = t_retention / 2
                                       = 10.06 us / 2
                                       = ~5.03 us  (worst case, sf/125 C)
```

This sets a hard upper bound: **every storage row in the array must be
refreshed at least once per ~5.03 µs, at the worst-case corner**, or a
worst-case-leakage cell risks losing its stored value before it is next
read or refreshed.

**Bandwidth overhead** is the fraction of the macro's total operation
bandwidth consumed by refresh rather than by external read/write access:

```
refresh_bandwidth_overhead = (N_rows * t_row_refresh_op) / refresh_interval
```

where `N_rows` is the array's row count and `t_row_refresh_op` is the time
to refresh one row (approximately one read-and-write-back cycle). **Neither
`N_rows` nor `t_row_refresh_op` is ratified yet** — both depend on the
array/periphery design, which is out of scope for the retention/refresh
budget study (#1) and has not been simulated. Per this repo's evidence-chain
discipline, this document does not substitute an invented row count or
cycle time for those undetermined inputs merely to produce a percentage
figure; doing so would produce a number with no committed evidence behind
it, exactly what CLAUDE.md's "a retention number without its chain is not a
result" exists to prevent. What Section 7 *does* ratify is:

- The **refresh-interval upper bound** (~5.03 µs, worst case, with its full
  evidence chain traced above) — the quantity every future array-level
  refresh-controller design must design to.
- The **bandwidth-overhead formula** above, in the correct units (a
  dimensionless fraction of total macro bandwidth) — ready to evaluate the
  moment `N_rows` and `t_row_refresh_op` are ratified by an array/periphery
  design.
- The **qualitative conclusion**: a worst-case refresh interval in the
  low-single-digit-microsecond range is short relative to typical
  SRAM-replacement duty cycles, so non-trivial refresh bandwidth overhead
  should be expected once `N_rows` and `t_row_refresh_op` are known — this
  is the concrete form of CLAUDE.md's "never describe the macro as a
  drop-in SRAM replacement" for this macro's refresh cost, and is consistent
  with the published comparators in Section 4, all of which report refresh
  periods in the same low-tens-to-hundreds-of-microseconds range.

Quantifying the exact overhead percentage is tracked as follow-up work
(Section 8), gated on the array/periphery design this issue's scope
excludes.

## 8. What this ratifies, and what it does not

**Ratified by this document:**

- The worst-case retention time for this macro's ratified topology:
  **~10.06 µs** (2T, `sf` corner, 125 °C), with its full evidence chain.
- The bitcell topology: **2T**, with the rationale in Section 6.
- The refresh-interval upper bound: **~5.03 µs** (worst case, 2x margin
  ASSUMPTION), and the bandwidth-overhead formula it feeds into.

**Not established or ratified by this document** (explicitly out of scope,
tracked as follow-up rather than silently assumed away):

- **Post-layout `C_SN` re-derivation (#7, cited from #4's follow-up)**: the
  single most consequential open assumption in this entire chain. Both the
  retention-time and refresh-interval figures above will change once a real
  layout exists to extract storage-node parasitics from.
- **3T read-disturb quantification**: no testbench in this repo currently
  measures the bitline-coupling / read-disturb risk named in Section 6,
  point 3, as the concrete condition under which the 2T decision should be
  revisited. If a future array/periphery simulation finds this effect
  severe enough to threaten data integrity at the array's target yield, this
  decision should be reopened.
- **Refresh bandwidth overhead as a numeric percentage**: gated on
  `N_rows` and `t_row_refresh_op` from a ratified array/periphery design,
  per Section 7.
- **Sense-amplifier-derived sense margin**: `delta_V = VDD/2` remains an
  ASSUMPTION per #3, pending an actual sense-amplifier design for this
  macro.
- **Density vs SRAM comparison**: Section 6 uses density as a decisive
  *qualitative* argument (2T has fewer devices than 3T), but this document
  does not perform the README's target-spec "must beat a 6T SRAM bitcell on
  area" comparison against public OpenRAM documentation — that remains a
  separate, not-yet-scoped piece of work.

Per CLAUDE.md: "agents do not relax the ratified spec to make results
pass." Nothing in this document adjusts `C_SN`, `delta_V`, `I_leak`, or any
other input in [`sim/leakage/`](../sim/leakage/README.md) or
[`sim/retention/`](../sim/retention/README.md) to change the numbers
above — it assembles what is already committed into a ratified decision and
records, rather than papers over, everything that decision does not yet
settle.

## 9. PROPOSED, not ratified: array-context storage-node inputs (issue #89)

**Status: PROPOSED. Not ratified.** Sections 1–8 remain the ratified
record, and nothing in this section changes them. The retention time is
still **~10.06 µs** (Section 5), the topology is still **2T** (Section 6),
and the refresh-interval upper bound is still **~5.03 µs** (Section 7).
This section proposes which storage-node inputs a *future* array-level
retention study should use, and what evidence it would need before
anything here could replace a ratified number. It is a proposal and does
not approve a new refresh deadline.

### 9.1 Question

Issue #80 extracted the committed 4x4 array. A storage node there has
17–22% less capacitance than the isolated bitcell that the retention
derivation reads. The question is whether the retention derivation's
`C_SN` should come from the array-context extraction rather than from the
isolated cell. A second question follows: whether the junction geometry
behind the leakage term should also be the extracted geometry.

### 9.2 Evidence (snapshot of committed inputs)

[`sim/retention/compare_array_c_sn.py`](../sim/retention/compare_array_c_sn.py)
produced all of these values from the committed reports and CSV rows.
They are recorded with input hashes in
[`sim/retention/results/array_c_sn_comparison_20261011T020547Z.json`](../sim/retention/results/array_c_sn_comparison_20261011T020547Z.json),
and the method is described in
[`sim/retention/README.md`](../sim/retention/README.md) "Array-context
`C_SN`". All rows share the same measured `I_leak` (9.898880e-11 A, `sf`,
125 °C) and the same `delta_V = VDD/2` ASSUMPTION.

| Estimate | `C_SN` (fF) | `t_retention` | Kind |
|---|---|---|---|
| Pre-layout | 1.106463 (ASSUMED, 2.0x `C_gate`) | ~10.06 µs | **Ratified** (Section 5) |
| Isolated cell, extracted (#7) | 0.605354 | ~5.50 µs | Extracted single cell; not ratified |
| 4x4 array, limiting node `sn_3_3` | 0.473620 (0.782x isolated) | ~4.31 µs | **Capacitance-only sensitivity** |
| 4x4 array, largest nodes (four tied interior cells) | 0.502000 (0.829x isolated) | ~4.56 µs | **Capacitance-only sensitivity** |

The array rows scale the *extracted isolated-cell* estimate by
`C_array / C_single`. They do not scale the ratified pre-layout value, and
they are not array retention measurements.

The trace found two further facts, both of which bear on the decision:

1. **`C_SN` is wiring capacitance only, in both reports.** Neither number
   contains the M_RD gate or the M_WR drain-junction capacitance. Those
   are left to the device model (layout/README.md, #80 "Convention").
2. **The measured leakage used no drawn diffusion geometry.** The leakage
   testbench passes no `AD/AS/PD/PS`, so the shipped wrapper's zero
   defaults applied. The layout draws `AD = AS = 0.1974 µm²` and
   `PD = PS = 1.78 µm`; the schematic says 0.1218 µm² and 1.42 µm. More
   reverse-biased junction can only add current, so the committed
   `I_leak` likely understates the drawn device's leakage. No
   geometry-matched leakage evidence is committed.

### 9.3 Alternatives

| | Option | For | Against |
|---|---|---|---|
| A | Keep the isolated-cell `C_SN` (0.605354 fF) | Already in the default derivation; complete evidence chain (#7) | A cell built in the array does not have this capacitance. The isolated cell's extra met1 crossing (0.263 fF) is absent in the array, so every array cell's `C_SN` is overstated by 17–22%. Optimistic |
| B | Use the array minimum under the existing convention (0.473620 fF, `sn_3_3`) | Same reader and convention; deterministic; reproducible from committed extraction; closer to an array-built cell than A | Leakage is still at zero diffusion geometry (optimistic). Assumes quiet neighbours. 4x4 only, and the minimum sits at a corner cell. Wiring only. Static |
| C | Use geometry-matched array evidence: array-context `C_SN` **and** leakage re-measured with the extracted `AD/AS/PD/PS` across the 15 PVT points, with device capacitance from the model | Leakage and capacitance describe the same drawn device; no mixed geometry | Needs new simulation evidence that is not yet committed (Section 9.6) |

### 9.4 Recommendation (proposed)

- **Evidence path: C.** Any future change to Section 5 or Section 7 should
  rest on geometry-matched array evidence. The combination should not be
  ratified while the capacitance describes the array-built device and the
  leakage describes a device with no drawn diffusion. B corrects one input
  and leaves the other biased in the same optimistic direction, so B
  should not be ratified as a revised retention time.
- **Interim planning input: B, labelled.** Until C exists, array studies
  (#94, #147) should use the array limiting-node value as their planning
  input, labelled "capacitance-only sensitivity, leakage at testbench
  geometry". That is ~4.31 µs at `sf`/125 °C against the 5.50 µs extracted
  single-cell estimate, a factor of 0.782. Use the whole distribution
  (`sn_3_3` minimum, 0.473620–0.502000 fF), not one representative cell.
  Choosing the minimum is conservative relative to A. It is not a bound,
  because of the known leakage bias.
- **A is kept only as the isolated-cell baseline.** It is not an input
  for array-level conclusions.
- Rationale: retention is linear in `C_SN` at fixed leakage and margin, so
  an input that overstates `C_SN` by about 20% overstates retention by the
  same factor. Correcting the capacitance makes the estimate more
  representative. Correcting it alone, without the matched leakage, could
  still be mistaken for a corrected chain, which is why B is proposed as a
  labelled planning input and not as a ratified number.

### 9.5 Assumptions behind B

- **Quiet neighbours.** Coupling capacitance (8.5–14.2% of each node's
  total) is counted as load to a far terminal held at a fixed potential:
  `bl`, `rbl`, `wl`, `rwl` quiescent during hold. Dropping it gives
  0.430576 fF, a ratio of 0.71128. That figure shows how much of the value
  rests on this assumption; it is not a bound. A switching neighbour
  injects charge through these capacitors. That is a disturb, which is
  characterized as write/hold/sense trajectories in #94, not a static
  capacitance.
- **Same convention as the default path.** Total equals ground plus all
  coupling capacitors, wiring only. The computed `C_gate` (0.553231 fF)
  must not be added on top. Whether the extracted poly term overlaps the
  channel region has not been checked, so adding it risks counting
  capacitance twice. Device capacitance should come from the BSIM model
  evaluated on the extracted netlist.
- **4x4, committed GDS.** The limiting node is the array corner `sn_3_3`,
  which has the fewest coupled neighbours. A larger array or a regenerated
  layout (#91) needs re-extraction and a new comparison file.
- **Unchanged from Sections 2–5:** constant-current decay, `delta_V =
  VDD/2` (ASSUMPTION), the single worst-case PVT point, and no mismatch.

### 9.6 Remaining evidence before any ratification

1. **Geometry-matched leakage.** Re-run the access-device leakage over the
   same 15 PVT points with `ad = as = 0.1974`, `pd = ps = 1.78`, committed
   as new append-only evidence. Submit it as a `klt sim` corner request,
   not a hand-run grid. Tracked in #149.
2. **A node-capacitance convention that includes device capacitance.**
   Either evaluate `C_SN` with the device model on the extracted array
   netlist (for example, the hold-droop slope at the storage node), or
   show that the extractor's poly term excludes the channel region so
   that `C_gate` and the junction term can be added without counting
   twice.
3. **Dynamic behaviour with neighbours switching.** Physical write, hold
   and sense trajectories at the refresh deadline with mixed neighbour
   patterns: #94.
4. **Repeated refresh.** Data preservation over closed-loop refresh
   cycles: #147.
5. **Array size.** Evidence that the 4x4 limiting node represents the
   macro's array, or an extraction at the macro's `N_ROWS`/`N_COLS`.

### 9.7 Inputs available to #94 and #147, and their limits

| Input | Value | Use it for | Do not use it for |
|---|---|---|---|
| Array `C_SN` distribution | 16 nodes, 0.473620–0.502000 fF, limiting node `sn_3_3` (comparison JSON `array.nodes`) | Choosing the cells to stress; a wiring-only cross-check of simulated node capacitance | Adding to a netlist that already contains the extracted parasitics (that counts the wiring twice) |
| Capacitance-only retention | ~4.31–4.56 µs at `sf`/125 °C (`per_node` in the JSON) | A planning deadline, labelled as sensitivity | A refresh-interval spec or guarantee |
| Extracted device geometry | `AD = AS = 0.1974 µm²`, `PD = PS = 1.78 µm` | Device cards in array-context decks, so that junction leakage and junction capacitance match the layout | Mixing with the testbench `I_leak` as if that were geometry-matched |

## Files

| Path | Purpose |
|---|---|
| `retention-refresh-budget.md` (this file) | Ratified decision record: retention time, 2T-vs-3T topology decision, refresh bandwidth-overhead framing — the exit criterion for #1. Section 9 is a PROPOSED, not ratified, array-context input decision (#89) |
| [`../sim/retention/compare_array_c_sn.py`](../sim/retention/compare_array_c_sn.py) | Issue #89 comparison behind Section 9 (capacitance-only sensitivity) |
| [`retention-literature-crosscheck.md`](retention-literature-crosscheck.md) | Literature cross-check this decision cites (issue #4) |
