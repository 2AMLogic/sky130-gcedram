# Literature cross-check: sky130 gain-cell retention vs. published results (issue #4)

Fourth and final link CLAUDE.md requires in the retention/refresh-budget
evidence chain: device-level leakage (issue #2) → an explicitly labelled
storage-node capacitance assumption (issue #3) → the retention derivation
(issue #3) → **this document**, cross-checking the derived numbers against
published gain-cell measurements from the academic literature, and noting
where this repo's open-PDK, pre-layout numbers diverge from what the
literature reports. Per CLAUDE.md: "a retention number without its chain is
not a result" — this is the step that puts this repo's numbers next to
independently published silicon, rather than letting them stand alone.

## Methodology and citation verification

This is a from-scratch, open-PDK design (per CLAUDE.md, there is no sibling
repo to copy from), so the comparison set below was assembled directly from
public bibliographic sources during this write-up, not recalled from memory
alone. Every citation's title, author list, venue, volume/issue/page, year,
and DOI was verified against the [Crossref](https://www.crossref.org/) public
metadata API, and every quoted retention number is copied verbatim from the
paper's own abstract, reconstructed from the publisher-indexed text via the
[OpenAlex](https://openalex.org/) public API (`abstract_inverted_index`) —
not estimated, not recalled, not paraphrased. Both APIs are public,
unauthenticated, and reproducible by anyone:

```bash
# Bibliographic record (title/authors/venue/volume/issue/page):
curl -s "https://api.crossref.org/works/<DOI>"

# Publisher-indexed abstract (reconstructed from the inverted index):
curl -s "https://api.openalex.org/works/doi:<DOI>"
```

A reader who wants to re-verify any number below should re-run the two
commands above against the DOI cited and read the `abstract` field of the
Crossref/OpenAlex response directly, or follow the DOI to the publisher
(IEEE Xplore) for the primary source. This methodology satisfies CLAUDE.md's
"cite public sources only" rule — every source below is a peer-reviewed IEEE
publication, publicly indexed, cited by DOI.

## This repo's derived numbers (recap, cited from #3)

From [`sim/retention/README.md`](../sim/retention/README.md) and
[`sim/retention/results/retention_results.csv`](../sim/retention/results/retention_results.csv):

| Geometry | Topology | Process | `C_SN` (ASSUMED) | `delta_V` (ASSUMED) | Corner | `t_retention` |
|---|---|---|---|---|---|---|
| `2T-min` | 2T | sky130, 130 nm bulk CMOS | 1.106 fF | 0.9 V (VDD/2) | `sf`, 125 °C (worst case) | **~10.06 µs** |
| `3T-min` | 3T | sky130, 130 nm bulk CMOS | 2.213 fF | 0.9 V (VDD/2) | `sf`, 125 °C (worst case) | **~20.12 µs** |

These are **pre-layout, single-cell** estimates built on two explicitly
labelled assumptions (`C_SN`, `delta_V`) combined with one measured quantity
(worst-case access-device leakage, issue #2). See
[`sim/retention/README.md`](../sim/retention/README.md) for the full
derivation and its own caveats before treating these as more than what they
are.

## Cited literature

Three IEEE-published, silicon-measured gain-cell eDRAM results, chosen to
span a wide range of process nodes (65 nm down to 16 nm) and topologies (2T,
3T, 4T) while each stating a concrete retention/data-retention-time (DRT)
number directly comparable in units (µs) to this repo's derived numbers:

### 1. Chun, Jain, Kim & Kim — 65 nm, asymmetric 2T gain cell

> K. C. Chun, P. Jain, T.-H. Kim, and C. H. Kim, "A 667 MHz Logic-Compatible
> Embedded DRAM Featuring an Asymmetric 2T Gain Cell for High Speed On-Die
> Caches," *IEEE Journal of Solid-State Circuits*, vol. 47, no. 2,
> pp. 547–559, Feb. 2012. DOI:
> [10.1109/JSSC.2011.2168729](https://doi.org/10.1109/JSSC.2011.2168729).
> (Companion conference paper: Symposium on VLSI Circuits, 2010, pp. 191–192,
> DOI: [10.1109/VLSIC.2010.5560303](https://doi.org/10.1109/VLSIC.2010.5560303).)

- **Process**: 65 nm low-power (LP) CMOS.
- **Topology**: asymmetric 2T gain cell — PMOS write device, NMOS read
  device (the write device's gate/junction leakage is used deliberately to
  hold the storage node's logic-'1' level) — the closest published topology
  match to this repo's `2T-min` candidate.
- **Reported retention, verbatim from the abstract**: "A 192 kb eDRAM test
  chip with 512 cells-per-BL implemented in a 65 nm low-power (LP) CMOS
  process shows a random cycle frequency and latency of 667 MHz and 1.65 ns,
  respectively, at 1.1 V and 85 °C. **The measured refresh period at a 99.9%
  bit yield condition was 110 µs**."

### 2. Giterman, Shalom, Burg, Fish & Teman — 16 nm FinFET, 3T mixed-VT gain cell

> R. Giterman, A. Shalom, A. Burg, A. Fish, and A. Teman, "A 1-Mbit Fully
> Logic-Compatible 3T Gain-Cell Embedded DRAM in 16-nm FinFET," *IEEE
> Solid-State Circuits Letters*, vol. 3, pp. 110–113, 2020. DOI:
> [10.1109/LSSC.2020.3006496](https://doi.org/10.1109/LSSC.2020.3006496).

- **Process**: 16 nm FinFET — the most advanced node in this comparison set.
- **Topology**: mixed-VT 3T gain cell — the closest published topology match
  to this repo's `3T-min` candidate.
- **Reported retention, verbatim from the abstract**: "Measurement results
  demonstrate **a 77-µs DRT under a 600-mV VDD**, which is over 10× longer
  than previously reported GC-eDRAMs in 28-nm technologies. The memory was
  fully operational at temperatures spanning **-40 °C to 125 °C** and under a
  supply voltage as low as 450 mV."
- This is the **most directly comparable** of the three citations on
  temperature: its 77 µs figure is explicitly stated to hold across the same
  worst-case 125 °C this repo's derivation uses, not just at room
  temperature.

### 3. Giterman, Fish, Burg & Teman — 28 nm FD-SOI, 4T internal-feedback gain cell

> R. Giterman, A. Fish, A. Burg, and A. Teman, "A 4-Transistor nMOS-Only
> Logic-Compatible Gain-Cell Embedded DRAM With Over 1.6-ms Retention Time at
> 700 mV in 28-nm FD-SOI," *IEEE Transactions on Circuits and Systems I:
> Regular Papers*, vol. 65, no. 4, pp. 1245–1256, Apr. 2018. DOI:
> [10.1109/TCSI.2017.2747087](https://doi.org/10.1109/TCSI.2017.2747087).

- **Process**: 28 nm FD-SOI.
- **Topology**: 4-transistor, nMOS-only, internal-feedback gain cell
  (IFGC) — **not** directly topology-comparable to either of this repo's
  candidates (an extra transistor implements a feedback path specifically to
  suppress storage-node leakage); included to show the far end of the
  literature's range and because its abstract states an explicit, useful
  multiplier over "conventional" gain cells.
- **Reported retention, verbatim from the abstract**: "The fabricated memory
  macro achieves **more than 1.6-ms data retention time at 27 °C**, which is
  **30× longer than conventional gain-cell topologies when applied to this
  technology**."
- Read literally, this implies "conventional" (2T/3T, no internal feedback)
  gain cells at this same 28 nm node retain on the order of ~1.6 ms / 30 ≈
  **~53 µs at 27 °C, 700 mV** — consistent with, and a useful third
  data point alongside, the two directly-topology-matched citations above.
  This inferred figure is **not** independently confirmed against a paper
  that states it directly, so it is reported here as a same-paper-derived
  cross-check, not as an independently cited literature value.

## Side-by-side comparison

| Source | Process node | Topology | Bias / temp | Retention (reported) |
|---|---|---|---|---|
| This repo, `2T-min` (issue #3) | sky130, 130 nm bulk CMOS | 2T | `sf` corner, 125 °C (worst case) | **~10.06 µs** |
| This repo, `3T-min` (issue #3) | sky130, 130 nm bulk CMOS | 3T | `sf` corner, 125 °C (worst case) | **~20.12 µs** |
| Chun et al. 2012, JSSC | 65 nm LP CMOS | 2T (asymmetric) | 1.1 V, 85 °C | **110 µs** (99.9% bit yield) |
| Giterman et al. 2020, SSC-Letters | 16 nm FinFET | 3T (mixed-VT) | 600 mV, −40 °C to 125 °C | **77 µs** (measured DRT) |
| Giterman et al. 2018, TCAS-I | 28 nm FD-SOI | 4T (internal feedback) | 700 mV, 27 °C | **>1.6 ms**; "conventional" topologies at the same node inferred **~53 µs** |

**Every cited "conventional" (2T/3T, no internal feedback) literature number
clusters in a roughly 50–110 µs band**, despite spanning three process
generations (65 nm → 28 nm → 16 nm) and a decade of publication dates
(2010–2020). This clustering, itself an as-reported finding rather than a
hypothesis, is a useful sanity anchor for the divergence discussion below:
if leakage scaling with node were the dominant lever, these three numbers
would be expected to spread out, not cluster — which points toward
deliberate storage-capacitor sizing (a design choice, not a raw device
property) as the more likely dominant lever across this literature set.

## Divergence: this repo's numbers are shorter than every cited comparator

This repo's `2T-min` (~10.06 µs) is roughly **11× shorter** than Chun et
al.'s 65 nm 2T result (110 µs); `3T-min` (~20.12 µs) is roughly **4× shorter**
than Giterman et al.'s 16 nm 3T result (77 µs). This is worth flagging
explicitly rather than glossing over, per CLAUDE.md and this issue's
acceptance criteria — and it runs in a counter-intuitive direction: sky130 is
an *older, larger* node (130 nm) than any of the three cited results, and
older/larger nodes generally have *lower* leakage per unit area than heavily
scaled nodes, all else equal. Naively, this repo's numbers should sit above
the cited range, not below it. The candidate explanations below are
**hypotheses**, not settled findings — none has been independently verified
against a re-derivation, and some point at inputs this repo has already
flagged as its own most speculative assumptions.

1. **The storage-node capacitance assumption (`C_SN`) is very likely the
   dominant factor, and is probably too small — hypothesis.** This repo's
   `C_SN` is a **pre-layout ASSUMPTION**: a 2–4× margin over a single
   minimum-size read transistor's own gate-oxide capacitance (0.553 fF),
   yielding just 1.106–2.213 fF (see
   [`sim/retention/README.md`](../sim/retention/README.md) "Storage-node
   capacitance"). Every cited paper above reports **measured silicon** with a
   real, deliberately-sized storage node — commonly incorporating a
   dedicated storage-capacitor structure sized specifically to hit a target
   retention spec, not "the neighboring transistor's gate cap plus a small
   margin." Since this repo's own retention formula is directly
   proportional to `C_SN` (`t_retention = C_SN * delta_V / I_leak`), a
   literature-scale storage node (order 10–20× larger than this repo's
   assumption) would move `2T-min`/`3T-min` into roughly the same 50–200 µs
   band the cited papers occupy, without changing anything else in the
   derivation. This is exactly the assumption
   [`sim/retention/README.md`](../sim/retention/README.md) already flags as
   needing revisiting once a layout exists (tracked in #7) — this
   cross-check adds an independent reason (not just "no layout yet") to
   expect that revision to raise the retention estimate, not lower it.

2. **Worst-case corner choice (`sf`, 125 °C) is deliberately pessimistic and
   is not always what the literature quotes — hypothesis, partially
   addressed.** Chun et al.'s 110 µs is quoted at 85 °C, not 125 °C; Giterman
   et al. 2018's 1.6 ms figure is quoted at 27 °C. Per
   [`sim/leakage/README.md`](../sim/leakage/README.md) "Worst-case corner,"
   this repo's own `sf`-corner leakage rises by more than 10× between 27 °C
   and 125 °C, so part of the gap versus room/85 °C-quoted literature numbers
   is plausibly a like-for-worse-case comparison rather than like-for-like.
   Giterman et al. 2020 (16 nm, 3T) is the exception and the most directly
   comparable citation on this axis: its 77 µs figure is explicitly validated
   across −40 °C to 125 °C, the same worst-case temperature this repo uses —
   yet `3T-min` is still ~4× shorter than that number, so temperature alone
   does not close the whole gap for the one citation where it is controlled
   for.

3. **Minimum-size, worst-case-leakage device choice — hypothesis.** Per
   [`sim/leakage/README.md`](../sim/leakage/README.md) "Device choice," this
   repo deliberately used the minimum drawn W/L (0.42 µm / 0.15 µm) the
   shipped sky130 model supports, chosen specifically *because* it is the
   worst-case-leakage candidate, not sized for a retention target. Both
   Giterman citations explicitly use **mixed-VT** device choices specifically
   to suppress storage-node leakage — a design lever this repo's #2 has not
   yet evaluated (it only established that the *lower*-threshold `_lvt`
   variant is the wrong direction; a *higher*-threshold or longer-`L` device
   that would lower leakage below the measured minimum-size number remains
   unexplored). This repo's leakage number, taken alone, is closer to a
   deliberately worst-case bound than a design-optimized point, which the
   published designs are.

4. **Sense-margin definition mismatch — hypothesis, unresolved.** This repo
   assumes `delta_V = VDD/2 = 0.9 V`, a coarse rule stated as an explicit
   ASSUMPTION absent a sense-amplifier design (see
   [`sim/retention/README.md`](../sim/retention/README.md) "Sense margin").
   Chun et al.'s 110 µs is defined via a "99.9% bit yield" criterion
   validated statistically against an actual fabricated sense amplifier
   across many cells and bitlines — a different, empirically-derived failure
   definition, not necessarily equivalent to a fixed half-`VDD` swing
   threshold. Public abstracts alone do not establish whether a 99.9%-yield
   criterion implies a larger or smaller effective `delta_V` than 0.9 V
   without replicating the statistical methodology; this is flagged as an
   open question, not resolved here.

5. **Topology complexity buys retention — a documented finding, not a
   hypothesis.** The clearest non-speculative result from this literature
   survey: Giterman et al. 2018 report their 4T internal-feedback gain cell
   is **30× longer-retention than "conventional" gain-cell topologies at the
   same 28 nm node**, reaching the millisecond range. Both of this repo's
   candidates (`2T-min`, `3T-min`) are conventional (no internal feedback),
   so neither is directly comparable to the 1.6 ms figure on a same-topology
   basis — it is included in the table above specifically to show the
   topology-driven end of the literature's range, not as an
   apples-to-apples comparator. If a future increment of this macro adopts
   an internal-feedback or similar topology, this citation is the public
   evidence that doing so is the largest single lever in the published
   literature for extending retention, larger than any of the PVT- or
   sizing-level hypotheses above.

## What this comparison does and does not establish

- **It does not validate or invalidate this repo's derived numbers.** The
  literature comparison is a sanity check against independently published,
  fabricated silicon — it is not a substitute for this repo's own
  device-level leakage measurement (#2) or a re-derivation with corrected
  assumptions. Per CLAUDE.md, "agents do not relax the ratified spec to make
  results pass" — this document does not adjust `C_SN`, `delta_V`, or any
  other input in [`sim/retention/`](../sim/retention/README.md) to close the
  gap; it records the gap and the leading hypothesis for it.
- **It strengthens the case, already made in
  [`sim/retention/README.md`](../sim/retention/README.md)'s "Follow-up"
  section, for prioritizing a post-layout `C_SN` re-derivation (#7).** The
  clustering of independent, cross-node published numbers in a 50–110 µs
  band for conventional gain cells — well above this repo's pre-layout
  10–20 µs estimates — is external evidence (not just "no layout exists
  yet") that the storage-node capacitance assumption is the most likely
  single source of the divergence, and the one most worth re-deriving first.
- **It does not change the 2T-vs-3T topology decision.** Both candidate
  topologies diverge from their closest published comparator by a similar
  order of magnitude (2T: ~11×; 3T: ~4×), so this cross-check does not by
  itself favor one topology over the other for the spec-ratification
  decision tracked in #5.
- Per CLAUDE.md, none of the cited numbers are presented as this repo's own
  measured results — they remain external, cited literature values, kept
  distinct from this repo's measured/computed/assumed values exactly as
  [`sim/retention/README.md`](../sim/retention/README.md)'s "What is
  measured, computed, and assumed here" table already distinguishes those
  three kinds of number for this repo's own numbers.

## Follow-up (out of scope here)

- **Post-layout `C_SN` re-derivation (#7)**: this cross-check's leading
  hypothesis (divergence hypothesis 1 above) adds independent motivation —
  not just "no layout yet" — for prioritizing this once a layout exists.
- **Higher-`V_t` or longer-`L` access-device leakage sweep**: not yet
  tracked as a separate issue; would test divergence hypothesis 3 by
  re-running the #2 leakage testbench against a device sized to trade area
  for lower leakage, the way the cited mixed-`V_t` designs do.
- **Internal-feedback or similar topology evaluation**: out of scope for the
  current 2T/3T decision (#5), but flagged by divergence hypothesis 5 as the
  single largest lever the published literature demonstrates for extending
  retention, should a future increment revisit the topology choice.

## Files

| Path | Purpose |
|---|---|
| `retention-literature-crosscheck.md` (this file) | Literature cross-check write-up: cited sources, side-by-side comparison, divergence hypotheses |
