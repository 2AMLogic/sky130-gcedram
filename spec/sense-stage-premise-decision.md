# Sense-stage premise: the non-existence wording is stale (issue #312)

**Evidence record, not a spec change.** It changes no ratified value,
relaxes no ratified spec, and grades nothing. It records one correction:
several committed records state that a sense amplifier **does not exist**
for this macro. That premise was true when each was written and is stale
now. The ASSUMPTIONs those statements support all **stand unchanged** —
this record corrects the premise behind them, not the assumptions
themselves.

## What exists

A schematic-level sense latch is a committed design source since #109:

- `design/sense_latch.sch` / `design/sense_latch.spice` (and the raw
  netlist `design/sense_latch.raw.spice`),
- characterized across corners in [`sim/sense-stage/`](../sim/sense-stage/README.md)
  (issue #60; 10 corners),
- characterized for input-referred offset by the mismatch Monte Carlo study
  in [`sim/sense-mismatch/`](../sim/sense-mismatch/README.md)
  (issue #81, closed; committed output),
- with the loaded-column read-path context in
  [`sim/loaded-column/`](../sim/loaded-column/README.md).

What does **not** exist: a layout of the latch, a validated offset/yield
result, or a `sense_en` timing derived from this stage. Its sizes are
provisional, its offset/yield is **not** validated
(`offset_yield_validated: false`), and everything above sits under the
PROPOSED, unratified operating range of
[`operating-range-decision-PROPOSED.md`](operating-range-decision-PROPOSED.md).

## The replacement claim (canonical; reference this, do not paraphrase)

> A schematic-level sense latch exists (`design/sense_latch.sch`, #109),
> characterized across corners and for input-referred offset, but its sizes
> are provisional, it has no layout, its offset/yield is **not** validated
> (`offset_yield_validated: false`), and it sits under the PROPOSED,
> unratified operating range of `spec/operating-range-decision-PROPOSED.md`
> — so there is still no validated sense-margin budget.

## What does not change

- `delta_V = VDD/2` in
  [`retention-refresh-budget.md`](retention-refresh-budget.md) (RATIFIED)
  remains an ASSUMPTION; there is still no validated sense-margin budget
  to re-derive it from.
- `offset_yield_validated`, `sense_decision_implemented` and
  `mismatch_or_offset_yield_validated` stay `false` in every committed
  summary.
- No threshold, corner set or ASSUMPTION status in
  [`macro-pass-conditions-PROPOSED.md`](macro-pass-conditions-PROPOSED.md)
  moves; rows 2a and 2e keep their status cells and their ungraded state
  (the #81 mismatch study covers four corners at 1.8 V, not the RESTRICTED
  set).
- Section 1 of `macro-pass-conditions-PROPOSED.md` (the dated 2026-10-09
  provenance snapshot) is not touched — it records the state at that time
  and is not a present-tense claim.

## The corrected sites

Eleven sites in seven files had their non-existence premise replaced by the
canonical claim above (issue #312):

| File | Site | Was |
|---|---|---|
| `spec/operating-range-decision-PROPOSED.md` | section 1 | "ASSUMPTION pending a sense amplifier" |
| `spec/operating-range-decision-PROPOSED.md` | section 7 | "No sense amplifier exists" |
| `spec/operating-range-decision-PROPOSED.md` | section 8 | "No sense amplifier, mismatch, offset or yield result exists" (canonical claim wording) |
| `spec/retention-refresh-budget.md` | section 8 | "pending an actual sense-amplifier design for this macro" |
| `spec/retention-literature-crosscheck.md` | "Divergence" section, finding 4 | "absent a sense-amplifier design" |
| `spec/supply-reliability-decision-PROPOSED.md` | section 1 | "ASSUMPTION pending a sense amplifier" |
| `spec/macro-pass-conditions-PROPOSED.md` | row 2a evidence | "re-run with the real sense cell loaded once one exists" |
| `spec/macro-pass-conditions-PROPOSED.md` | row 2e evidence | "#81 ... not yet committed" |
| `digital/phase-control/CONTRACT.md` | preamble | "No sense amplifier and no refresh controller exist" |
| `digital/phase-control/CONTRACT.md` | `sense_en` row | "ASSUMPTION; no sense amp exists" |
| `digital/refresh-scheduler/README.md` | `t_row_refresh_op` row | "no sense amp or controller circuit exists" |

Attestation note: the `spec/README.md` index entry for this record is an
edit to an inventoried file (`attest/item10.json` lists the spec index), so
`attest/item10.envelope.json` was regenerated as part of #312. The
inventory file itself, `block-manifest.json` and
`block-manifest.signoff.json` are unchanged (item10's manifest pin is over
the inventory file, not the inventoried files). See
[`t1-analog-attestation-decision.md`](t1-analog-attestation-decision.md)
for the re-attest commands.
