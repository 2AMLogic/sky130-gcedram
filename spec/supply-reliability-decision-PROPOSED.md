# PROPOSED decision record: supply-assisted read/write for the sense path (issue #49)

> **STATUS: PROPOSED. NOT RATIFIED.** This document ratifies nothing and
> changes no ratified value. It prepares a decision for the two-key process
> (`ratification/ee-key/`, `ratification/market-key/`). Two-key ratification is
> outside the authority of issue #49 and of any agent that wrote this file.
> Until ratified, nothing here may be quoted as a macro specification.

Epic #24, phase 4. Evidence base:
[`sim/loaded-column/cold-corner/EVIDENCE_INDEX.md`](../sim/loaded-column/cold-corner/EVIDENCE_INDEX.md),
[`STRESS_LIMIT_INVENTORY.md`](../sim/loaded-column/cold-corner/STRESS_LIMIT_INVENTORY.md),
[`SENSE_INPUT_CONTRACT.md`](../sim/loaded-column/cold-corner/SENSE_INPUT_CONTRACT.md).

## 1. Ratified values preserved (not touched by this record)

From [`retention-refresh-budget.md`](retention-refresh-budget.md) (RATIFIED):
2T bitcell topology; worst-case retention ~10.06 us (sf, 125 C, `C_SN`
1.106463 fF ASSUMED, `delta_V` = `VDD`/2 = 0.9 V ASSUMED, `I_leak`
9.898880e-11 A measured); refresh-interval upper bound ~5.03 us (2x margin
ASSUMPTION); refresh bandwidth formula. `delta_V` = `VDD`/2 remains an
ASSUMPTION pending a sense amplifier. No option below relaxes any of them.
One tension is **recorded, not resolved**: option B leaves the cold stored '1'
at 0.864 V < 0.9 V.

## 2. The problem (evidence, not opinion)

Phase 2 periphery (1.8 V write wordline, 0 .. 1.8 V read wordline) fails at
fs/-40 C: stored '1' 0.864 V, separation 0.018 V, 32 of 128 stored-'1' points
never reach the 0.1 V droop; ss/-40 C is marginal
([cold-corner README](../sim/loaded-column/cold-corner/README.md) sections 1-2).
Bitline load, sense time, longer write pulses and wider `M_RD` do not fix it.

## 3. Options

| | A. Write-WL boost to 2.0 V | B. Read-WL under-drive to -0.2 V | C. Operating-range limitation |
|---|---|---|---|
| Simulated result (ideal drivers, 4-row, 10 fF assumed) | 30/30 PASS, min separation 0.413 V | 30/30 PASS, min separation 0.604 V | fs/-40 C fails; ss/-40 C marginal |
| Cold stored '1' | 1.024 V (fixes root cause) | 0.864 V (unchanged) | 0.864 V |
| Terminal stress vs the only documented range (V_GS 0..1.95 V, **model validity**) | `M_WR` V_GS = 2.0 V: **outside** by 0.05 V | V_BS = +0.2 V inside +0.3 V; `rbl` goes to -0.2 V (28/30 points) | none new |
| Reliability limit documented | **none found** | **none found** | n/a |
| New supply | +2.0 V wordline rail (boost) | -0.2 V rail on read WL; sense input must take negative common mode | none |
| Main unresolved evidence | oxide/HCI stress at 2.0 V, 125 C, pulsed | forward-junction injection/latch-up on array p-well and `rbl`; model junction validity | ratification of a restricted range |
| Retention-assumption effect | improves (`delta_V` 0.9 V reachable at cold) | conflict: stored '1' < 0.9 V at cold | unchanged |
| Hot-corner cost | min separation 0.515 -> 0.435 V | read disturb 0.067 -> 0.082 V | none |

## 4. Ranking (PROPOSED)

Ranking is of **engineering merit if the missing evidence resolves
favourably**, and is separate from adoptability, which is **blocked for A and
B** (section 6).

1. **A, write-WL boost** (conditional). Fixes the stored level itself and
   so supports the ratified retention assumption; leaves the read path at
   standard 0 .. 1.8 V levels and a ground-referred `rbl`, which keeps the
   sense input conventional. Costs: a 2.0 V gate stress on a 1.8 V device that
   has no cited limit, and lower hot margin.
2. **C, operating-range limitation** (conditional on market-key). Needs no
   unproven stress and is honest, but gives up the cold slow-NMOS corners
   (an explicit scope reduction) and sets a ceiling on any claim.
3. **B, read-WL under-drive** (conditional). The largest simulated margin,
   but it does not address the stored-level/retention tension, and its
   simulated margin partly comes from `rbl` swinging below ground, so it
   puts a negative common-mode requirement on the sense input and a
   forward-junction exposure on **every** cell on the column, with no
   documented limit.

Why B is below C although it simulates best: B's score depends on a
condition (sub-ground column) that the study did not stress-characterize,
and it does not repair the ratified retention assumption. This ordering is a
judgement for the keys, and would change if (i) a documented 2.0 V limit is
refused (A drops out), or (ii) isolated-well and injection evidence supports
B.

## 5. Unresolved evidence (each blocks the cited option)

See [`STRESS_LIMIT_INVENTORY.md`](../sim/loaded-column/cold-corner/STRESS_LIMIT_INVENTORY.md) section 5:
2.0 V gate-oxide/HCI limit for the sky130 1.8 V NMOS (A);
junction injection/latch-up limit under -0.2 V and sub-ground `rbl`, and
model junction validity across temperature (B); driver/pump circuits (A, B);
extracted `C_RBL`, longer columns, mismatch and an offset budget (all).

## 6. Required ratification keys

Not performed here. For each, the key and the item:

| Key | Required decision |
|---|---|
| `ee-key` | (a) accept or reject a reliability basis for `M_WR` V_GS = 2.0 V, naming the cited limit; (b) accept or reject sub-ground read wordline/`rbl` and its isolation basis; (c) confirm that the study's placeholder criteria (0.1 V separation, 10 fF `C_RBL`, 10 ns sense) are not specification values |
| `market-key` | (d) accept or reject an operating-range restriction (option C) and the wording of the corresponding claim; confirm the block is not described as full-PVT or SRAM-replacement-equivalent if C is chosen |
| both | (e) record the chosen option as a decision in `spec/`, preserving every key in section 1 |

## 7. Verdict

**MISSING EVIDENCE. Not ready for ratification.** No option has the evidence
required for adoption: the documented voltage statement for the device is a
model-validity range, 2.0 V lies outside it, and no reliability limit was
found for either supply-assisted option. SPICE success is not accepted as a
substitute. Option C is the only candidate with no missing stress evidence,
and requires only a scope decision by the keys.

### Next independently scoped increment, per viable outcome

* **Outcome A viable** (a documented or measured 2.0 V limit is supplied):
  a bounded sense-characterization increment using the contract in
  [`SENSE_INPUT_CONTRACT.md`](../sim/loaded-column/cold-corner/SENSE_INPUT_CONTRACT.md)
  with the boosted write level, plus a boost-driver stress/ripple study
  (`VWL` tolerance band 1.95-2.0+ vs time).
* **Outcome B viable** (injection/isolation evidence is supplied): a
  sub-ground column study (junction current and substrate-injection bound,
  negative-common-mode sense input) before any sense circuit.
* **Outcome C chosen**: a ratification-only increment writing the
  operating-range restriction into `spec/` (key-signed), followed by the same
  sense characterization limited to the restricted corners.
* **Common**: an independent increment to obtain a primary reliability source
  for the 1.8 V NMOS (the missing item for both A and B). It is a research
  task, not a simulation.

## 8. Evidence status update (issue #51, appended; sections 1-7 unchanged)

Status remains **PROPOSED. NOT RATIFIED.** No spec value is relaxed or
ratified. Source: [`reliability-search-log-issue51.md`](../sim/loaded-column/cold-corner/sources/reliability-search-log-issue51.md).

* **(a) 2.0 V gate-oxide/TDDB/HCI limit for the 1.8 V NMOS: not found** in
  skywater-pdk, open_pdks, the model library, arXiv/OpenAlex or the public
  issue trackers. Published gate-stress limits cover only HV (7.3 V) and VHV
  (5.5 V) devices and are not transferable.
* **(b) forward-junction injection / latch-up bound: not found.** Only DRC
  latch-up rules and reverse-breakdown specs exist.
* New adverse-to-neutral fact: the SkyWater methodology page classifies any
  use outside GND..Vcc as "high voltage" usage with biasing conditions in a
  non-public ETD. Both A (2.0 V) and B (-0.2 V) are such usage. This does not
  refute either option; it means neither can be justified from public data.
* Not excluded: NDA foundry documents (ETD/EDR) and paywalled literature,
  which were not reachable.

**Outcome supported: C** (operating-range limitation, no supply assist) is the
only outcome the evidence leaves viable without a missing stress item. A and
B remain blocked, not rejected: each stays viable only if the keys supply a
reliability basis (for example an ETD/EDR excerpt obtained by the project
under its own terms, or measured data) or accept the risk explicitly.
Verdict: **MISSING EVIDENCE, unchanged for A and B.**

**Next independently scoped increment**: the `ee-key` and `market-key`
decisions in section 6 remain required. The next increment is the
ratification-only one for outcome C (write the operating-range restriction
into `spec/`, key-signed), followed by sense characterization at the
restricted corners using the existing contract. If the keys instead want A or
B, the prerequisite is a key-supplied reliability source; no further public
search is expected to change that.

## 9. Outcome-C disposition (issue #56, appended 2026-10-09; sections 1-8 unchanged)

**Operator ruling, 2026-10-08, on #24: outcome C.** The cold-corner failure
is handled by restricting the operating temperature range and saying so in
the claim. Options A (write-WL boost to 2.0 V) and B (sub-ground read word
line) are not adopted, for the missing reliability basis recorded in section
8; they remain blocked, not rejected, and the analysis above is kept.

This is the operator's selection of an option. It is **not** two-key
ratification. This record is still **PROPOSED. NOT RATIFIED.**, and
`ratification/ee-key` and `ratification/market-key` have not signed. The
ratification-only increment named in section 7 is written as
[`operating-range-decision-PROPOSED.md`](operating-range-decision-PROPOSED.md)
(also PROPOSED), which holds the proposed range, per-corner evidence, the
stated boundary resolution and the canonical claim wording (its section 8).
Sense characterization at the restricted corners (#60) is the next circuit
increment. No ratified value is changed.
