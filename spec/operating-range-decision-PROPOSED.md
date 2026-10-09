# PROPOSED decision record: restricted operating-temperature range (outcome C, issue #56)

> **STATUS: PROPOSED. NOT RATIFIED.** This document ratifies nothing and
> changes no ratified value. It records the proposed written form of outcome C
> for the two-key process (`ratification/ee-key/`,
> `ratification/market-key/`). Two-key ratification is outside the authority
> of issue #56 and of any agent that wrote this file. Until both keys sign,
> nothing here may be quoted as a macro specification.

Epic #24 (parent), issue #56. This is the "ratification-only increment" that
[`supply-reliability-decision-PROPOSED.md`](supply-reliability-decision-PROPOSED.md)
section 7 names for outcome C. **No new simulation was run.** Every number
below is read from committed Phase 2 / Phase 3 evidence.

## 1. Ratified values preserved (not touched by this record)

From [`retention-refresh-budget.md`](retention-refresh-budget.md) (RATIFIED):
2T bitcell topology; worst-case retention ~10.06 us (sf, 125 C, `C_SN`
1.106463 fF ASSUMED, `delta_V` = `VDD`/2 = 0.9 V ASSUMED, `I_leak`
9.898880e-11 A measured); refresh-interval upper bound ~5.03 us (2x margin
ASSUMPTION); refresh bandwidth formula. `delta_V` = `VDD`/2 remains an
ASSUMPTION pending a sense amplifier. Restricting the temperature range
relaxes none of them.

## 2. Operator ruling and what it does not adopt

On 2026-10-08 the operator selected outcome C on #24: the cold-corner
failure is handled by restricting the operating temperature range and saying
so in the claim. The write word-line boost to 2.0 V (option A) and the
sub-ground read word line (option B) are **not adopted**: neither has a
public reliability basis
([`supply-reliability-decision-PROPOSED.md`](supply-reliability-decision-PROPOSED.md)
section 8). They are not rejected on engineering grounds either; they stay
blocked pending a key-supplied reliability source.

## 3. Evidence used

Only the **unassisted Phase 2 baseline** (1.8 V write word line, 0 .. 1.8 V
read word line). No boosted, under-driven, low-Vt or other remedy variant
is used as evidence for outcome C.

| Item | Source |
|---|---|
| Run | `20261005T102906Z`, 1920 points, 0 `sim_failed`, coverage complete ([`summary_20261005T102906Z.json`](../sim/loaded-column/results/summary_20261005T102906Z.json), [`loaded_column_results.csv`](../sim/loaded-column/results/loaded_column_results.csv)) |
| Same data against the Phase 3 criteria | pseudo-variant `phase2_baseline`, 30 points, in [`summary_20261005T145658Z.json`](../sim/loaded-column/cold-corner/results/summary_20261005T145658Z.json) and [`pass_fail_20261005T145658Z.csv`](../sim/loaded-column/cold-corner/results/pass_fail_20261005T145658Z.csv) (rows `variant_id = phase2_baseline`) |
| Reproduction of the cold failure | 256 fs/ss -40 C points bit-identical with the unchanged runner ([cold-corner README](../sim/loaded-column/cold-corner/README.md) section 1) |

Grid actually simulated: process corners tt, ss, ff, sf, fs (global corners
only, no mismatch); temperatures **-40, 27, 125 C**; **`VDD` = 1.8 V only**;
two ages (`fresh`, read 89 ns after the row write; `refresh_bound`, 5.029945
us after the row-0 write); a 4-row column with 16 stored patterns per
selected row (64 cases per corner/temperature/age point); `C_SN` 0.605354 fF
(extracted from the netlist; differs from the ratified ASSUMED 1.106463 fF
and is not reconciled); `C_RBL` 10 fF (ASSUMED, not extracted).

### Criteria (study ASSUMPTIONS, not spec values)

Applied exactly as the Phase 3 study defined them
([README](../sim/loaded-column/cold-corner/README.md), "Pass criteria"): a
point passes only if (1) column-wide worst-case signed separation
`min V(rbl|0) - max V(rbl|1)` at `t_sense` >= 0.1 V, (2) every stored-'1'
case reaches the 0.1 V droop by `t_sense` = 10 ns, (3) read disturb <= 0.1 V,
(4) 64/64 cases simulated. The 0.1 V, 10 fF and 10 ns values are
**placeholders**; they are not promoted to specification values by this
record.

A separate, non-study check is added here and labelled as such: whether the
stored '1' after write and before the read stays at or above 0.9 V, the
`VDD`/2 level the ratified retention derivation assumes for `delta_V`
("stored-level compatibility"). This is a reading of the ratified
ASSUMPTION, not a pass criterion from the study.

## 4. Per-corner result (baseline, both ages)

Entries are the aggregation named in the column header, over all 64 cases of
the point. Each cell is `fresh / refresh_bound`. Values are from
`pass_fail_20261005T145658Z.csv` (`worst_case_separation_v`,
`latency_stored1_max_s`, `v_sn1_after_write_min_v`,
`v_sn1_preread_min_v`); read disturb (max of selected and unselected
`|dV_sn|`) is under 0.07 V at every point and is not tabulated per row.

| Corner | T (C) | Separation min (V) | Max '1' latency (ns) | Stored '1' after write, min (V) | Stored '1' pre-read, min (V) | Study PASS |
|---|---:|---|---|---:|---|---|
| fs | -40 | 0.018 / 0.017 | not reached (32 stored-'1' cases per age) | 0.864 | 0.864 / 0.860 | **FAIL** both ages |
| ss | -40 | 0.121 / 0.113 | 7.92 / 8.55 | 0.896 | 0.896 / 0.893 | pass, **marginal**; stored '1' < 0.9 V |
| tt | -40 | 0.648 / 0.633 | 7.43 / 7.82 | 0.959 | 0.959 / 0.956 | pass |
| ff | -40 | 0.646 / 0.647 | 2.20 / 2.26 | 1.016 | 1.016 / 1.012 | pass |
| sf | -40 | 0.629 / 0.630 | 1.54 / 1.56 | 1.055 | 1.055 / 1.050 | pass |
| fs | 27 | 0.286 / 0.272 | 2.78 / 2.96 | 0.932 | 0.932 / 0.929 | pass |
| ss | 27 | 0.608 / 0.591 | 9.41 / 9.85 | 0.961 | 0.961 / 0.957 | pass; latency within 0.15 ns of the 10 ns placeholder |
| tt | 27 | 0.651 / 0.652 | 2.53 / 2.60 | 1.028 | 1.028 / 1.024 | pass |
| ff | 27 | 0.604 / 0.606 | 1.44 / 1.46 | 1.088 | 1.088 / 1.083 | pass |
| sf | 27 | 0.583 / 0.586 | 1.27 / 1.28 | 1.123 | 1.123 / 1.117 | pass |
| fs | 125 | 0.654 / 0.659 | 4.10 / 5.41 | 1.027 | 1.027 / 0.994 | pass |
| ss | 125 | 0.647 / 0.654 | 2.74 / 3.31 | 1.048 | 1.048 / 1.016 | pass |
| tt | 125 | 0.602 / 0.618 | 1.52 / 1.76 | 1.123 | 1.123 / 1.069 | pass |
| ff | 125 | 0.540 / 0.601 | 1.18 / 1.65 | 1.187 | 1.187 / 1.014 | pass |
| sf | 125 | 0.515 / 0.615 | 1.13 / 1.76 | 1.217 | 1.217 / 0.956 | pass |

Totals: 28 of 30 (corner, temperature, age) points pass the study criteria.
The two failures are fs/-40 C at both ages. The worst-case row/pattern is
recorded in the CSV (`stored1_worst_sel_row`, `stored1_worst_pattern_rows3210`).

Why the cold corners fail ([cold-corner README](../sim/loaded-column/cold-corner/README.md)
section 2): the write passes a degraded '1' (source-follower cut-off plus
word-line feedthrough), the falling read word line couples it down further,
and at the slow-NMOS cold corners the read device is below threshold at the
sense instant (fs/-40 C: Vgs - Vth = -0.148 V; ss/-40 C: -0.087 V). Bit-line
load, sense time and write-pulse length do not fix fs/-40 C.

## 5. Findings and where the criteria disagree

1. **Holds at 27 C and 125 C**, at all five process corners, both ages, on
   every study criterion and with stored '1' >= 0.9 V (lowest: fs/27 C,
   0.929 V pre-read at the refresh bound). Smallest passing separation
   margin: fs/27 C aged, 0.272 V.
2. **Fails at -40 C** at fs (study criteria 1 and 2 fail, both ages).
3. **ss/-40 C is a recorded conflict, not silently resolved.** It passes
   the study separation (0.113 V >= 0.1 V) and latency criteria, but its
   stored '1' (0.896 / 0.893 V) is below the 0.9 V `delta_V` that the
   ratified retention derivation assumes. Neither reading is relaxed. Both
   point to excluding -40 C; the record does not take ss/-40 C as support
   for any bound.
4. tt, ff and sf pass at -40 C. That does not extend the range: which
   process corner a fabricated die lands in is not known in advance, and a
   restriction by temperature must hold at every corner.

## 6. Proposed restricted range, and the resolution of its boundary

**Proposed interval: junction temperature 27 C to 125 C at `VDD` = 1.8 V.**

This is a conservative interval that rests on **discrete simulated points**
(27 C and 125 C) and does not rest on interpolation:

* **Holds at 27 C** (all corners, both ages). **Fails at -40 C** (fs; ss
  marginal and in conflict). **Nothing was simulated between -40 C and
  27 C.** The cold boundary therefore lies somewhere in (-40 C, 27 C]
  and is **not located**. The lower end is set at the lowest temperature
  actually demonstrated, 27 C. No lower value is claimed and no transition
  temperature is inferred (the monotone trend in the stored-'1' level is
  suggestive, and is not evidence).
* **Holds at 125 C**. Nothing was simulated above 125 C.
* **Between 27 C and 125 C** no temperature was simulated. "27 C to 125 C"
  is a statement about its two simulated end temperatures; it is **not** a
  continuous-range validation, and no mid-range temperature (for example
  85 C) was simulated. The hot corner is also the worst-case retention
  corner of the ratified chain, which remains governed by that record.
* **Supply:** the grid is `VDD` = 1.8 V only. Behaviour at any other supply,
  including a supply tolerance band, is unstudied and is not part of this
  proposal. The restricted-range claim is a nominal-supply claim.

## 7. What is not shown (stated limitations)

* No sense amplifier exists. The summary `claims` field has
  `sense_decision_implemented: false`, `offset_yield_validated: false`,
  `all_corner_functional_pass: false`. "Separation >= 0.1 V" is read
  separation, **not** a validated sense decision, and not offset or yield.
* No mismatch or Monte Carlo; no local variation; no supply-tolerance data.
* The passing margins rest on an ideal-driver 4-row column, an assumed
  10 fF `C_RBL`, a 10 ns sense time and a 0.1 V droop, all placeholders;
  ss/27 C sits within 0.15 ns of the 10 ns placeholder, so a modest change
  of `C_RBL` or timing could move the 27 C boundary. The cold study showed
  ss/-40 C is sensitive to `C_RBL` and `t_sense`.
* `C_SN` in the loaded-column study (0.605354 fF) is not the ratified
  ASSUMED 1.106463 fF; the stored-level checks above use the study value.
* Storage-node levels for longer columns, real layout parasitics and the
  refresh sequencing are not studied.
* The behaviour of the block below 27 C is unknown at the fidelity needed
  to say more than "fails at -40 C in the fs corner".

## 8. Required claim wording (canonical; reference this, do not paraphrase)

> **Operating range (PROPOSED, not ratified).** Simulated against the
> shipped sky130 models with ideal drivers, the gain-cell storage and read
> path hold the study's placeholder read-separation criterion at the five
> global process corners at junction temperatures of 27 C and 125 C and
> 1.8 V supply. The same path fails at -40 C in the fs corner and is
> marginal in the ss corner, and was not simulated between -40 C and 27 C,
> above 125 C, or at any other supply. No sense amplifier, mismatch, offset
> or yield result exists. This block is a dynamic gain-cell memory with a
> refresh requirement; it is not full-range and is not a drop-in
> replacement for SRAM.

Other documents reference this section by link. They must not restate the
numbers in other words. Publication in the repo `README.md` is #63.

## 9. Required ratification keys

Not performed here. Neither key is signed by this document or by #56.

| Key | Required decision |
|---|---|
| `ee-key` | accept or reject the evidence in sections 4 to 7 as sufficient for a 27 C to 125 C, 1.8 V restriction; rule on the ss/-40 C conflict in section 5; confirm the 0.1 V, 10 fF and 10 ns values remain placeholders |
| `market-key` | accept or reject the restriction itself and the wording in section 8; confirm the block is not described as full-range, full-PVT or SRAM-replacement-equivalent |
| both | record the outcome in `spec/` and flip this record's status; this PR does not |

## 10. Next increment

Sense characterization at the restricted corners (27 C and 125 C, all five
process corners, `VDD` = 1.8 V, unassisted baseline levels) using
[`SENSE_INPUT_CONTRACT.md`](../sim/loaded-column/cold-corner/SENSE_INPUT_CONTRACT.md)
(baseline column), tracked as #60. Any new multi-corner run goes through
`klt sim`, not a local ngspice grid. Repo `README.md` claim text is #63. A
further increment, only if the keys want a lower bound, would add simulated
temperatures between -40 C and 27 C to locate the boundary.
