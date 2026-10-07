# Sense-characterization input contract (PROPOSED, issue #49)

Inputs the next sense-amplifier characterization would consume, each traced
to committed evidence or labelled ASSUMPTION. Nothing here is a
specification. It does not promote `common_reference_v_UNVALIDATED` values
(committed in `results/summary_20261005T145658Z.json`) to anything: they are
listed only as "do not use". The option is **not selected**
([`spec/supply-reliability-decision-PROPOSED.md`](../../../spec/supply-reliability-decision-PROPOSED.md)),
so each level input carries a per-option column.

| Input | Baseline (Phase 2) | Option A (`rem_vwl_2p0`) | Option B (`rem_rwl_m0p2`) | Trace |
|---|---|---|---|---|
| Stored '1' after write, min / max over 30 points | 0.864 / 1.222 V | 1.024 / 1.382 V | 0.864 / 1.222 V | EVIDENCE (summary JSON, `stored1_after_write_v`) |
| Stored '1' at the refresh bound, cold (fs/-40 C) | 0.860 V | 1.020 V | 0.860 V | EVIDENCE |
| Stored '1' at the refresh bound, hot (sf/125 C) | 0.956 V | 1.086 V | 0.956 V | EVIDENCE |
| Stored '0' after write, min | -0.135 V | -0.139 V | -0.135 V | EVIDENCE (sub-ground undershoot) |
| Refresh-bound aging | 5.029945 us (row 0 oldest, 4-row sequential writes) | same | same | ratified bound ([`retention-refresh-budget.md`](../../../spec/retention-refresh-budget.md) s7); sequencing is a STUDY-ASSUMPTION |
| Storage-node capacitance | 0.605354 fF extracted-from-netlist | same | same | EVIDENCE for the study; **differs** from the ratified ASSUMED 1.106463 fF; not reconciled |
| Column size | 4 rows, one `rbl` | same | same | STUDY-ASSUMPTION (not a ratified row count) |
| `C_RBL` | 10 fF | same | same | ASSUMPTION (not extracted); fs/-40 C pass/fail is insensitive to it (README 2b), ss/-40 C is not |
| `rbl` precharge | 0.9 V (`VRBL`), released 2 ns before the read edge | same | same | STUDY-ASSUMPTION, ideal switch (100 ohm) |
| Write wordline | 1.8 V, 20 ns, 0.1 ns edges | 2.0 V, same timing | 1.8 V | EVIDENCE (variants.py/template); ideal driver |
| Read wordline (selected) | 1.8 -> 0 V, 20 ns | 1.8 -> 0 V | 1.8 -> -0.2 V; deselected 1.8 V | EVIDENCE; ideal driver |
| Sense instant | 10 ns after the select edge | same | same | ASSUMPTION |
| `rbl` common mode at sense | stored '1' -> ~0 V | same | stored '1' -> **-0.2 V** (28/30 points) | EVIDENCE; B needs a negative-common-mode input |
| Tested corners | tt, ss, ff, sf, fs x -40/27/125 C, global corners only, no mismatch | same | same | EVIDENCE (full grid, both ages); range for the contract |
| Margin criterion | 0.1 V worst-case column separation | same | same | **ASSUMPTION (placeholder)** |
| Worst-case separation, min over grid | 0.017 V (fs/-40, aged) | 0.413 V | 0.604 V | EVIDENCE; B's includes sub-ground swing |
| Offset/margin budget status | **none**: no sense amplifier, no offset or yield evidence, no mismatch | | | NOT AVAILABLE (summary `claims`: offset/yield false) |
| Read disturb | 0.067 V | 0.067 V | 0.082 V (sf/125) | EVIDENCE; 0.1 V limit is a placeholder |
| Supply/rail tolerances (boost ripple, negative-rail accuracy) | n/a | not studied | not studied | NOT AVAILABLE |

**Rules for the consumer**

1. Select the option first (or characterize both under identical
   conditions); do not interpolate between the columns.
2. Re-derive anything marked ASSUMPTION or NOT AVAILABLE before it becomes
   a pass criterion; extracted `C_RBL` and longer columns are the first.
3. Retain failed variants and add a negative control (the
   `nc_write_disabled` pattern) for any new run.
4. Any new multi-corner or Monte Carlo run is a `klt sim` request (batch
   backend), not a local ngspice grid.
