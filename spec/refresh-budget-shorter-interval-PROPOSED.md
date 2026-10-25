# PROPOSED decision record: shorter refresh interval on the device-inclusive retention bound (issue #208)

> **STATUS: PROPOSED. NOT RATIFIED.** This document ratifies nothing and
> changes no ratified value. It writes the operator-selected option (a) of
> issue #208 in the form the two-key process (`ratification/ee-key/`,
> `ratification/market-key/`) can review. Until both keys sign and the
> operator ratifies, [`retention-refresh-budget.md`](retention-refresh-budget.md)
> Sections 5 and 7 stand as written (retention ~10.06 us, refresh interval
> upper bound ~5.03 us). `sim/retention/results/retention_results.csv` and
> every other committed result are untouched. **No new simulation was run**:
> every number is read from committed evidence.

Issue #208. Evidence: PR #214, with #161 (wiring-only compact `C_SN`) and #89
(Section 9 of the ratified record) upstream of it. Operator direction
(2026-10-24, issue #208): the decision goes through spec ratification, with
the key reviews first as input, then operator ratification.

## 1. Ratified values preserved (not touched by this record)

From [`retention-refresh-budget.md`](retention-refresh-budget.md) (RATIFIED):
2T topology; worst-case retention ~10.06 us (`sf`, 125 C, `C_SN` 1.106463 fF
ASSUMED, `delta_V` = `VDD`/2 = 0.9 V ASSUMED, `I_leak` 9.898880e-11 A);
refresh-interval upper bound ~5.03 us (2x margin ASSUMPTION); the refresh
bandwidth formula. This record proposes replacing the retention and
refresh-interval figures only if ratified, and only with the values in
Section 4.

## 2. Why the ratified figure is in question

The ratified `C_SN` is an assumption made before any layout existed. Since
then, extraction (#7, #80, #161) has measured wiring-only capacitance
(0.317 fF on the compact v2 limiting node, 2.69 us), and #214 added the
device terms with the BSIM models in the loop (hold-droop slope over the
`delta_V` window, extracted netlist, quiet neighbours, ideal drivers, global
corners). Section 9.6 item 2 of the ratified record named this as the
missing evidence.

## 3. Evidence (read from committed files)

Source: [`sim/retention/results/compact_device_c_sn_20261022T0533Z.json`](../sim/retention/results/compact_device_c_sn_20261022T0533Z.json)
(15/15 PVT points through one `klt sim` batch request; reproduction recipe
in [`sim/retention/README.md`](../sim/retention/README.md)). Worst case,
`sf` / 125 C, limiting node `$32`, geometry-matched compact v2 `I_leak`
1.0595e-10 A, `delta_V` = 0.9 V (ASSUMPTION):

| Case | `C_SN` (fF) | Retention (us) |
|---|---|---|
| Wiring only (#161) | 0.317 | 2.69 |
| `p`: devices, extracted poly term removed (lower) | 0.759 | **6.45** |
| `a`: devices on top of extracted wiring (upper) | 0.937 | 7.96 |
| `b`: as `a`, read terminals grounded (bounding bias, not the idle bias) | 1.109 | 9.42 |
| Ratified (assumed `C_SN` 1.106 fF, legacy-geometry leakage) | 1.106 | 10.06 |

Controls: an ideal 1 fF capacitor reads exactly in the same batch; a 5x lower
test current agrees within 0.31 %; `wiring only <= p <= a` at every point.
The channel-poly double count is **bracketed, not decided**: whether the
extractor's poly term overlaps the channel is still open.

## 4. Proposal: option (a)

Base the budget on the **conservative bound `p` = 6.45 us** at `sf` / 125 C.
At the ratified 2x margin ASSUMPTION:

```
refresh_interval (2x margin) = 6.4495 us / 2 = ~3.22 us   (was ~5.03 us)
```

A bound at the low end of the bracket is safe whichever side of the double
count is true, and follows CLAUDE.md's worst-case-corner rule. It keeps the
compact 2T cell (drawn pitch 1.399 um^2, `v2`) and its density position
([`density-vs-sram.md`](density-vs-sram.md)).

**Cost, stated plainly.** Every row must be refreshed ~1.56x as often as
under the ratified 5.03 us bound (5.029945 / 3.22475). The bandwidth overhead
formula of Section 7 of the ratified record scales by the same factor; its
`N_rows` and `t_row_refresh_op` inputs are still not ratified, so no
percentage is given here. Issue #208's option text says "3x refresh
bandwidth versus 10.06 us"; that compares a retention time with a refresh
interval. On the like-for-like basis (refresh interval to refresh interval)
the factor is 1.56x. The 3.1x figure is the mismatched comparison: it is the
ratified retention time (10.06 us) divided by the new refresh interval
(3.22 us), not a ratio of like quantities. Because interval = retention / 2,
the ratio of the two retention times (10.06 / 6.45) is also 1.56x. The
reviewers should rule on the 1.56x figure.

**Scope of the ~3.22 us figure, and the 2x margin.** The ~3.22 us interval is
a *necessary* upper bound at global corners with no local variation. The
unchanged 2x margin does **not** cover access-device Vth mismatch, and its
ratified rationale ("array-wide mismatch", Section 7 of the ratified record)
is not carried forward onto this value. The pinned model text gives
sigma(Vth) of about 55 mV for a 0.42/0.15 um `nfet_01v8`
(`sim/sense-mismatch/README.md`, "Mismatch model availability"). At `sf` /
125 C, kT/q is about 34.3 mV, and with an assumed slope factor n = 1.3-1.5 a
1-sigma Vth shift multiplies subthreshold leakage by roughly 2.9-3.4x (a hand
estimate from model text, not a simulation). The 2x margin is therefore
consumed at about 0.56-0.65 sigma, and a 3-sigma cell leaks roughly 25-40x
more. A macro refresh interval needs mismatch-inclusive leakage evidence (for
example a leakage Monte Carlo of the access device at `sf_mm` / 125 C via the
`klt sim` `monte_carlo` path, sized from its tail at the macro bit count) and
is expected to be materially shorter than 3.22 us. That evidence is not part
of this PR.

What the proposal does **not** claim: that 6.45 us is the true retention. It
is the low end of a bracket that still has an open question, on a single
4x4 array, at global corners, with `delta_V` = `VDD`/2 ASSUMED, no mismatch,
no neighbour switching (#94), no repeated refresh (#147), and the leakage
chain pinned to open_pdks `f6eeac7` (#168). Each of those can move the
number, and the neighbour-switching and mismatch effects would shorten it
further.

## 5. Options not adopted (with their evidence)

| Option | Why not, on the committed evidence |
|---|---|
| (b) one more study to decide the poly double count | The bracket is 6.45-7.96 us. Deciding it moves the 2x-margin deadline from ~3.2 us to at most ~4.0 us, for another measurement round, and would still sit below the ratified 5.03 us. It stays available as a later tightening; (a) does not preclude it. |
| (c) add explicit storage capacitance | Restoring 10.06 us needs a `C_SN` of 1.184 fF at `I_leak` = 1.0595e-10 A (per `sim/retention/README.md`), about 0.43 fF above the lower bound `p` (0.759 fF) and about 0.25 fF above `a`, i.e. 0.25-0.43 fF across the bracket. It changes the cell, spends the density the compaction in #100 bought and reopens layout and the README density requirement. |
| Keep 10.06 us unchanged | Not supported: the device-inclusive measurement is below it at every idle-bias case, and only the bounding bias `b` (9.42 us) approaches it without reaching it. |

## 6. If ratified, the edits that follow (not made by this PR)

* `retention-refresh-budget.md` Section 5: worst-case retention ~6.45 us,
  with `C_SN` source changed from ASSUMPTION to the extracted
  device-inclusive value; Section 7: refresh-interval upper bound ~3.22 us, scoped as a necessary global-corner bound that excludes mismatch, with the "array-wide mismatch" rationale for the 2x margin not carried forward (Section 4);
  supersession notes on the superseded figures.
* A new append-only row in `retention_results.csv`. Existing rows are not
  edited.
* Re-statement of the Section 9 caveats that this evidence resolves
  (9.6 item 2).

## 7. Required ratification keys

Neither key is signed by this document or by #208.

| Key | Required decision |
|---|---|
| `ee-key` | accept or reject the evidence in Section 3 as sufficient for a 6.45 us conservative bound; rule on using the lower end of the bracket while the double count is open; rule on the 2x refresh margin staying unchanged, given that it does not absorb access-device Vth mismatch (Section 4); confirm the 1.56x cost reading in Section 4 |
| `market-key` | accept or reject the claim consequence: a ~3.2 us worst-case refresh interval, 1.56x the previously ratified bandwidth, against the density position; confirm the macro is still not described as a drop-in SRAM replacement |
| operator | after both keys: ratify or reject. `loom:operator` stays on the PR until then |

## 8. Next increment

On ratification, the edits in Section 6. Independent of this decision:
neighbour-switching dynamics (#94), repeated refresh (#147), array-size
scaling (Section 9.6 item 5), and the re-statement of retention if #168
changes `I_leak`.
