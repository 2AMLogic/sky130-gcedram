# RATIFIED decision record: restricted operating-temperature range (outcome C, issue #56)

> **STATUS: RATIFIED.** Flipped from PROPOSED by the two-key process
> (`ratification/ee-key/`, `ratification/market-key/`): the operator's
> merge of the PR that carries this flip is the act of ratification, and
> that merge is the operator's. Ratification changed this status line,
> the section 8 claim label, the `spec/README.md` row and the status
> newly emitted evidence carries (`sim/_evidence_common.py`); it changed
> no number, threshold, criterion or corner recorded below.

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
| tt | -40 | 0.648 / 0.633 | 0.743 / 0.782 | 0.959 | 0.959 / 0.956 | pass |
| ff | -40 | 0.646 / 0.647 | 0.220 / 0.226 | 1.016 | 1.016 / 1.012 | pass |
| sf | -40 | 0.629 / 0.630 | 0.154 / 0.156 | 1.055 | 1.055 / 1.050 | pass |
| fs | 27 | 0.286 / 0.272 | 2.78 / 2.96 | 0.932 | 0.932 / 0.929 | pass |
| ss | 27 | 0.608 / 0.591 | 0.941 / 0.985 | 0.961 | 0.961 / 0.957 | pass |
| tt | 27 | 0.651 / 0.652 | 0.253 / 0.260 | 1.028 | 1.028 / 1.024 | pass |
| ff | 27 | 0.604 / 0.606 | 0.144 / 0.146 | 1.088 | 1.088 / 1.083 | pass |
| sf | 27 | 0.583 / 0.586 | 0.127 / 0.128 | 1.123 | 1.123 / 1.117 | pass |
| fs | 125 | 0.654 / 0.659 | 0.410 / 0.541 | 1.027 | 1.027 / 0.994 | pass |
| ss | 125 | 0.647 / 0.654 | 0.274 / 0.331 | 1.048 | 1.048 / 1.016 | pass |
| tt | 125 | 0.602 / 0.618 | 0.152 / 0.176 | 1.123 | 1.123 / 1.069 | pass |
| ff | 125 | 0.540 / 0.601 | 0.118 / 0.165 | 1.187 | 1.187 / 1.014 | pass |
| sf | 125 | 0.515 / 0.615 | 0.113 / 0.176 | 1.217 | 1.217 / 0.956 | pass |

Totals: 28 of 30 (corner, temperature, age) points pass the study criteria.
The two failures are fs/-40 C at both ages. The worst-case row/pattern is
recorded in the CSV (`stored1_worst_sel_row`, `stored1_worst_pattern_rows3210`).

### Companion table (2026-11-15): the same grid under ngspice-47 (issue #326)

Run `20261114T091445Z` (open_pdks `f6eeac7`, **ngspice-47**) re-simulated the
identical 1920-point grid; section 11 records the shift and its attribution.
Each cell below is `ngspice-46 fresh / refresh_bound -> ngspice-47 fresh /
refresh_bound`, same aggregation and rounding as the ngspice-46 table above.
The ngspice-46 side is quoted from the table above verbatim; the ngspice-47
side is derived from
[`summary_20261114T091445Z.json`](../sim/loaded-column/results/summary_20261114T091445Z.json)
`column_all_rows` groups (`worst_case_separation_v`, `latency_stored1_s.max`,
`stored1_after_write_v.min`, `stored1_preread_v.min`), re-derived 2026-11-15
against `origin/main` @ `512debf`. **The ngspice-46 table above is unchanged**
(append-only evidence); nothing here re-ratifies or relaxes any threshold,
criterion or ratified value.

| Corner | T (C) | Separation min (V) | Max '1' latency (ns) | Stored '1' after write, min (V) | Stored '1' pre-read, min (V) | Study PASS |
|---|---:|---|---|---:|---|---|
| fs | -40 | 0.018 / 0.017 -> 0.027 / 0.024 | not reached, both runs (32 stored-'1' cases per age) | 0.864 -> 0.870 | 0.864 / 0.860 -> 0.870 / 0.867 | **FAIL** both ages -> **FAIL** both ages |
| ss | -40 | 0.121 / 0.113 -> 0.156 / 0.147 | 7.92 / 8.55 -> 5.88 / 6.31 | 0.896 -> 0.902 | 0.896 / 0.893 -> 0.902 / 0.899 | pass, **marginal** -> pass; stored '1' pre-read >= 0.9 V fresh, < 0.9 V aged |
| tt | -40 | 0.648 / 0.633 -> 0.681 / 0.679 | 0.743 / 0.782 -> 0.603 / 0.633 | 0.959 -> 0.966 | 0.959 / 0.956 -> 0.966 / 0.962 | pass -> pass |
| ff | -40 | 0.646 / 0.647 -> 0.648 / 0.649 | 0.220 / 0.226 -> 0.197 / 0.202 | 1.016 -> 1.023 | 1.016 / 1.012 -> 1.023 / 1.019 | pass -> pass |
| sf | -40 | 0.629 / 0.630 -> 0.631 / 0.632 | 0.154 / 0.156 -> 0.146 / 0.147 | 1.055 -> 1.062 | 1.055 / 1.050 -> 1.062 / 1.058 | pass -> pass |
| fs | 27 | 0.286 / 0.272 -> 0.343 / 0.329 | 2.78 / 2.96 -> 2.19 / 2.32 | 0.932 -> 0.938 | 0.932 / 0.929 -> 0.938 / 0.935 | pass -> pass |
| ss | 27 | 0.608 / 0.591 -> 0.666 / 0.656 | 0.941 / 0.985 -> 0.793 / 0.827 | 0.961 -> 0.966 | 0.961 / 0.957 -> 0.966 / 0.963 | pass -> pass |
| tt | 27 | 0.651 / 0.652 -> 0.653 / 0.654 | 0.253 / 0.260 -> 0.230 / 0.236 | 1.028 -> 1.034 | 1.028 / 1.024 -> 1.034 / 1.030 | pass -> pass |
| ff | 27 | 0.604 / 0.606 -> 0.605 / 0.607 | 0.144 / 0.146 -> 0.138 / 0.140 | 1.088 -> 1.095 | 1.088 / 1.083 -> 1.095 / 1.090 | pass -> pass |
| sf | 27 | 0.583 / 0.586 -> 0.583 / 0.585 | 0.127 / 0.128 -> 0.123 / 0.124 | 1.123 -> 1.130 | 1.123 / 1.117 -> 1.130 / 1.124 | pass -> pass |
| fs | 125 | 0.654 / 0.659 -> 0.658 / 0.663 | 0.410 / 0.541 -> 0.366 / 0.471 | 1.027 -> 1.033 | 1.027 / 0.994 -> 1.033 / 1.001 | pass -> pass |
| ss | 125 | 0.647 / 0.654 -> 0.649 / 0.656 | 0.274 / 0.331 -> 0.254 / 0.299 | 1.048 -> 1.054 | 1.048 / 1.016 -> 1.054 / 1.023 | pass -> pass |
| tt | 125 | 0.602 / 0.618 -> 0.603 / 0.619 | 0.152 / 0.176 -> 0.146 / 0.166 | 1.123 -> 1.129 | 1.123 / 1.069 -> 1.129 / 1.078 | pass -> pass |
| ff | 125 | 0.540 / 0.601 -> 0.539 / 0.601 | 0.118 / 0.165 -> 0.116 / 0.153 | 1.187 -> 1.194 | 1.187 / 1.014 -> 1.193 / 1.028 | pass -> pass |
| sf | 125 | 0.515 / 0.615 -> 0.514 / 0.614 | 0.113 / 0.176 -> 0.111 / 0.161 | 1.217 -> 1.223 | 1.217 / 0.956 -> 1.223 / 0.973 | pass -> pass |

Totals under ngspice-47: still 28 of 30 points pass the study criteria; the
two failures are still fs/-40 C at both ages (the 32 stored-'1' cases per age
still never reach the latency droop). One recorded source note: the sf/125 C
fresh pre-read cell above quotes this table's 1.217, but both of the cited
ngspice-46 sources (`pass_fail_20261005T145658Z.csv` and
`summary_20261005T102906Z.json`, both 1.216376) round to 1.216. The ngspice-46
table is left byte-unchanged and the discrepancy is recorded, not corrected.

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

   **Recorded 2026-11-15 (run `20261114T091445Z`, ngspice-47; verified
   against `origin/main` @ `512debf`; see section 11):** the conflict is
   **narrowed, not resolved**. The stored-'1' pre-read level moves
   0.896256 -> 0.902283 V fresh — **clearing** 0.9 V for the first time —
   but only 0.892765 -> 0.898945 V aged, still **1.1 mV below** the 0.9 V
   `delta_V` assumption; `0.898945` must not be rounded to "clears". The
   worst-case separation margin against the 0.1 V study criterion grows
   13.4 mV -> 47.5 mV aged (0.113412 -> 0.147477 V). No threshold,
   criterion or ratified value is changed by this update.
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
  at 27 C the thinnest margins are at fs/27 C (latency 2.8-3.0 ns against
  the 10 ns placeholder; aged separation 0.272 V), so a large change of
  `C_RBL` or timing could still erode the 27 C result. The cold study
  showed ss/-40 C is sensitive to `C_RBL` and `t_sense`.
* `C_SN` in the loaded-column study (0.605354 fF) is not the ratified
  ASSUMED 1.106463 fF; the stored-level checks above use the study value.
* Storage-node levels for longer columns, real layout parasitics and the
  refresh sequencing are not studied.
* The behaviour of the block below 27 C is unknown at the fidelity needed
  to say more than "fails at -40 C in the fs corner".

## 8. Required claim wording (canonical; reference this, do not paraphrase)

> **Operating range (RATIFIED).** Simulated against the
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

## 11. Recorded shift: ngspice-46 -> ngspice-47 (2026-11-15, issue #326)

This section records that the numbers sections 4 to 6 rest on **moved** when
the identical 1920-point loaded-column grid was re-simulated under the
upgraded simulator. It changes **no threshold, no study criterion, no
ratified value and no ASSUMPTION**: section 1's ratified values are
untouched, the section 3 criteria stay study ASSUMPTIONS, and the proposed
27 C to 125 C interval in section 6 is unchanged by everything below. The
simulator pin is `NGSPICE_VERSION_PIN = "ngspice-47"`
(`sim/_evidence_common.py`); the per-study re-qualification inventory this
record belongs to is
[`docs/simulator-requalification-inventory.md`](../docs/simulator-requalification-inventory.md).

**Runs.** ngspice-46 side: run `20261005T102906Z` (open_pdks `c6d73a3`,
ngspice-46) — sections 4 and 5 above, unchanged. ngspice-47 side: run
`20261114T091445Z` (open_pdks `f6eeac7`, ngspice-47) — same deck, corners,
ages, patterns and reductions; 1920 points, 0 `sim_failed`, `coverage_ok:
true` in **both** runs. Every ngspice-47 number in this record is derived
from
[`summary_20261114T091445Z.json`](../sim/loaded-column/results/summary_20261114T091445Z.json)
(and, where stated, the committed probe reports and
[`loaded_column_results.csv`](../sim/loaded-column/results/loaded_column_results.csv)),
re-derived 2026-11-15 against `origin/main` @ `512debf`.

**Size of the shift** (column-wide `column_all_rows` aggregation over all 30
(corner, temperature, age) points, ngspice-46 -> ngspice-47): the worst-case
read separation moves by up to **+65.1 mV** (ss/27 C aged, 0.590660 ->
0.655766 V) and the stored-'1' read latency by up to **-26.2 %** (ss/-40 C
aged, 8.554 -> 6.310 ns; the largest absolute latency change is -2.24 ns at
the same point). Read disturb stays under the 0.1 V study criterion at every
point in both runs (maximum 0.067252 -> 0.060645 V). Per-corner detail: the
companion table in section 4. Per stored pattern the largest single-case
separation delta is 8.755e-02 V at tt/-40 C aged
([`compare_pins.py`](../sim/loaded-column/compare_pins.py) over the two
committed CSV runs). These are a tool-version sensitivity of committed
characterization numbers; they are recorded **beside** the ngspice-46 record,
not substituted for it.

**Cause attribution, measured at the conflict corner.** The ss/-40 C decks
were re-run locally under ngspice-47 twice, changing nothing but which
open_pdks tree `$PDK_ROOT` resolved to (`~/.volare` = `c6d73a3`, `~/.ciel` =
`f6eeac7`) — for **each** of the fresh deck `lc_fresh_sel0.spice` (which
carries the 0.9 V crossing) and the refresh-bound deck
`lc_refresh_bound_sel0.spice` (which carries the surviving conflict). Both
pairs are **bit-identical**: 464 shared measurements, 456 valued ones
identical, 0 differing (the eight without a value are the stored-'0' latency
measurements, which have no crossing by construction):

```bash
python3 -I sim/loaded-column/compare_pins.py --compare-reports \
  sim/loaded-column/results/pin-attribution/klt_report_local_ss40_c6d73a3_ngspice47_20261114T091445Z.json.gz \
  sim/loaded-column/results/pin-attribution/klt_report_local_ss40_f6eeac7_ngspice47_20261114T091445Z.json.gz
# 464 shared measurements: 456 bit-identical, 0 differ.

python3 -I sim/loaded-column/compare_pins.py --compare-reports \
  sim/loaded-column/results/pin-attribution/klt_report_local_ss40_c6d73a3_ngspice47_refresh_bound_20261114T091445Z.json.gz \
  sim/loaded-column/results/pin-attribution/klt_report_local_ss40_f6eeac7_ngspice47_refresh_bound_20261114T091445Z.json.gz
# 464 shared measurements: 456 bit-identical, 0 differ.
```

The `c6d73a3` probes read the retired `~/.volare` tree deliberately and only
for this attribution (the same convention as the sf/125 C probe recorded in
[`sim/loaded-column/README.md`](../sim/loaded-column/README.md)); nothing is
recorded from them as grid evidence. As a cross-check, both ngspice-47 local
probes also reproduce the committed fleet grid's ss/-40 C corners
bit-for-bit (fresh and refresh_bound, 456/456 against
`klt_report_lc_{fresh,refresh_bound}_sel0_20261114T091445Z.json.gz`), so the
probes measured the same thing the record quotes. Together with the earlier
sf/125 C probe (bit-identical, 456/456), the two open_pdks revisions' models
are numerically indistinguishable at **both probed corners**, and the shift
is attributable to the **simulator upgrade, ngspice-46 -> ngspice-47**, at
sf/125 C and at ss/-40 C (both ages). **Scope of that attribution**: the PDK
revision has **not** been probed at the corners extremal in the moved
quantities — the largest single-case separation delta sits at tt/-40 C and
the largest latency delta at ss/-40 C — so per-corner attribution elsewhere
remains an extrapolation, and no mechanism for the simulator-version
sensitivity is established or claimed here (tracked as #300).

**Effect on the findings.**

* Section 5 item 2 (fs/-40 C fails) is unchanged: the 32 stored-'1' cases per
  age still never reach the latency droop in both runs, and the stored-'1'
  level stays below 0.9 V (after write 0.864 -> 0.870 V; pre-read 0.864 ->
  0.870 V fresh, 0.860 -> 0.867 V aged).
* Section 5 item 3 (ss/-40 C conflict) is **half-cleared**, not resolved; the
  dated update is appended to that item above.
* **Section 6's proposed 27 C to 125 C interval is unchanged by the simulator
  upgrade.** Across the whole 30-point grid exactly one verdict moves: the
  ss/-40 C **fresh** stored-level check (below 0.9 V -> at/above 0.9 V,
  0.896256 -> 0.902283 V pre-read). **No study PASS/FAIL verdict moves** —
  fs/-40 C still fails both ages, the other 28 points still pass, and read
  disturb stays under its 0.1 V criterion in both runs. ss/-40 C aged still
  sits below 0.9 V pre-read (0.898945 V), so that corner remains in conflict
  and still is not support for any colder bound.

**Grid-wide extension of the PDK-revision exclusion (2026-11-16, issue
#338).** This dated note extends the PDK-revision exclusion above from the
two probed corners to the **whole loaded-column grid** (all five process
sections ss/sf/tt/fs/ff and all temperatures), on a different and
corner-independent basis: **content identity of the instantiated model
set**, established statically from the two PDK trees with no SPICE run. The
committed checker and its evidence record are
[`sim/pdk-closure-identity/`](../sim/pdk-closure-identity/) with
[`results/closure_identity_c6d73a3_vs_f6eeac7_20261116.json`](../sim/pdk-closure-identity/results/closure_identity_c6d73a3_vs_f6eeac7_20261116.json):
resolving the model closure from the requests' own entry point for every
corner section shows the loaded closures are **not** byte-identical (119 vs
141 files; `f6eeac7` splits the `models_fet.spice` monolith into 22
per-device files and adds an interconnect-capacitance `.param` block), but
every difference is outside the set the decks use -- the eight `lc_*.spice`
decks instantiate exactly one PDK model, `sky130_fd_pr__nfet_01v8` (1024
references), whose block content, corner inputs and feeding parameters are
identical in both revisions, and every differing `.param` is consumed only
by R/C models no deck instantiates. Since a PDK revision can only change a
result through the model content a deck instantiates, the ngspice-46 ->
ngspice-47 attribution recorded above is unchanged by this note and now
rests on both bases: the per-corner probes (direct numerical evidence,
unchanged) and this static closure comparison (corner-independent, this
deck set). **Limits of this note**: it covers this deck set only (the eight
`lc_*.spice` decks instantiating only `sky130_fd_pr__nfet_01v8`); it is a
static file-content argument, not a simulation; and it does **not** retire
the PDK-attribution question in the per-group re-qualification issues
(#166, #171, #182, #301) unless the checker is run over those studies' own
decks and passes -- #182/#301 are `loom:operator` and a human's. Also
recorded here: `environment.models_lib_sha256` in klt reports hashes only
the entry-point `sky130.lib.spice` (klt `sim.py:4451`, klt issue #2522) and
is identical between these revisions despite their closures differing, so
it must **not** be cited as PDK-revision evidence (same caveat as
`sim/sense-stage/README.md`).
