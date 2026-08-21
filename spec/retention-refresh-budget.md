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

## Files

| Path | Purpose |
|---|---|
| `retention-refresh-budget.md` (this file) | Ratified decision record: retention time, 2T-vs-3T topology decision, refresh bandwidth-overhead framing — the exit criterion for #1 |
| [`retention-literature-crosscheck.md`](retention-literature-crosscheck.md) | Literature cross-check this decision cites (issue #4) |
