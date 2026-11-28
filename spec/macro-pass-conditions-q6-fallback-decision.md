# Decision record: Q6 fallback grading for macro pass conditions (issue #395)

**Decision record, not a spec change.** It changes no threshold, corner set,
waiver or ratified value. It records one operator ruling on an open question
of [`macro-pass-conditions-PROPOSED.md`](macro-pass-conditions-PROPOSED.md),
which stays **PROPOSED, NOT RATIFIED**. Ratifying the operating range is owned
by #385, not by this record.

## Question

Q6 (section 7 of the PROPOSED record): if the restricted operating range
(27 C and 125 C, five process corners, `VDD` = 1.8 V, from
[`operating-range-decision-PROPOSED.md`](operating-range-decision-PROPOSED.md))
is not ratified, are items 2 and 6 graded against the full 15-point grid
(5 corners x -40/27/125 C), where the 10 fF baseline fails at fs/-40 C?

## Ruling

Operator ruling, 2026-11-23 (attended session, decision r19-q292, issue #395):
**option a. Grade on the full 15-point grid and report the fs/-40 C failures
as failures.**

Rejected: option b (re-open the range) and option c (grade on the restricted
set regardless of ratification).

## Evidence for the known failure

The schematic baseline uses `C_RBL` = 10 fF (**ASSUMPTION**), ideal write
and read drivers, an ideal precharge switch, and `t_sense` = 10 ns. At
fs/-40 C, the worst-case read separation across all rows (`column_all_rows`)
is 0.0267021 V fresh and 0.0244799 V (24.4799 mV) at the refresh bound. Both
fail the proposed 0.1 V row-2a criterion. [Baseline summary](../sim/loaded-column/results/summary_20261114T091445Z.json)

On the post-#244 layout, the **EXTRACTED-4-ROW** case replaces the entire
10 fF load with 0.955559 fF of wiring capacitance. At fs/-40 C the separation
is 0.110545 V fresh and 0.102376 V aged, a narrow pass at both ages. This
wiring-only case gives the lightest-load bound. Predicting macro read
separation requires the sense-input load that the substitution removes.
[Campaign description](../sim/loaded-column/extracted-crbl/README.md) ·
[Post-#244 results](../sim/loaded-column/extracted-crbl/results/20261029T203633Z/summary.json)

## Effect

- If the keys do not ratify RESTRICTED, grade items 2 and 6 on the full
  15-point grid and report the committed 10 fF baseline's fs/-40 C failures
  as failures.
- No threshold, corner set or waiver changes. This is a grading rule for a
  fallback case, not a relaxation.
- If the keys do ratify RESTRICTED, this record has no effect on grading.
