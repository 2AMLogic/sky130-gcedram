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
(5 corners x -40/27/125 C), where fs/-40 C is already known to fail?

## Ruling

Operator ruling, 2026-11-23 (attended session, decision r19-q292, issue #395):
**option a. Grade on the full 15-point grid and report the fs/-40 C failures
as failures.**

Rejected: option b (re-open the range) and option c (grade on the restricted
set regardless of ratification).

## Evidence for the known failure

`sim/loaded-column/results/summary_20261114T091445Z.json`, group fs, -40 C,
age `refresh_bound`, scope `column_all_rows`: `worst_case_separation_v` =
0.0244799 V (24.4799 mV), against the 0.1 V row-2a criterion of the PROPOSED
record. The fresh-age group at the same corner reads 0.0267021 V. The figures
are quoted from the committed file; nothing was re-run and no `sim/` file was
touched.

## Effect

- If the keys do not ratify RESTRICTED, items 2 and 6 are graded on the
  15-point grid and the fs/-40 C failures are reported as failures.
- No threshold, corner set or waiver changes. This is a grading rule for a
  fallback case, not a relaxation.
- If the keys do ratify RESTRICTED, this record has no effect on grading.
