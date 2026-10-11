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

## 2026-10-11 addendum: extracted `C_RBL` row (issue #88, PROPOSED)

Added under rule 2 ("Re-derive anything marked ASSUMPTION ... extracted
`C_RBL` ... is the first"). The table and rules above are unchanged, and the
10 fF row still describes every result produced before this date. This
section adds the extracted value as a separate row. It does not replace the
old row and is not a pass criterion. Evidence:
[`../extracted-crbl/README.md`](../extracted-crbl/README.md) (loaded column, run
`20261011T015419Z`) and the "Issue #88" section of
[`../../sense-stage/README.md`](../../sense-stage/README.md) (sense stage). Baseline
periphery: **ideal** (PR #118 / issue #114 not merged).

| Input | Baseline (Phase 2) | Option A | Option B | Trace |
|---|---|---|---|---|
| `C_RBL`, extracted (new row) | **0.859179 fF** | not re-run | not re-run | **EXTRACTED-4-ROW**: `layout/gain_cell_2t_array.parasitics.summary.json` key `comparison.c_rbl.extracted_4row_worst_total_ff`, netlist sha256 `dd2cca26de34d6b7cd39a0d794db64993d6440c5ca7f248cf4d657b6f6b88d33`. Wiring only; it **replaces** the 10 fF lumped load and is not added to it, so it is a lightest-load bound (the sense-input share of the 10 fF is untraced). Column size stays the 4-row STUDY-ASSUMPTION; `N_rows` **not ratified**. |
| Worst-case separation, min over grid, at extracted `C_RBL` | 0.075 V (fs/-40, aged) | not re-run | not re-run | EVIDENCE (`summary.json`, variant `crbl_ext4row`); fs/-40 C still FAILS (0.1 V placeholder, latency 12.97 ns > 10 ns); 28/30 points pass, as at 10 fF |
| ss/-40 C at extracted `C_RBL` | 0.370 V aged / 0.388 V fresh; latency 1.69 / 1.56 ns | not re-run | not re-run | EVIDENCE; was 0.113 / 0.121 V at 10 fF (marginal); passes either way |
| `C_RBL` 2 fF (trend) | min 0.052 V (fs/-40 aged); ss/-40 0.288 V aged | not re-run | not re-run | ASSUMPTION mid-point, trend only |
| Extracted `C_RBL` + layout diffusion card (`ad=as=0.1974`, `pd=ps=1.78`) | min 0.108 V (fs/-40 aged), **30/30 pass** | not re-run | not re-run | EVIDENCE, labelled device-card variant; the only verdict flip (fs/-40 C passes by 8 mV over the placeholder). Which card is right is issue #89 |
| Sense-stage `t_dec` at the 1 mV point (27/125 C only) | 0.11-0.23 ns (was 0.27-0.51 ns) | not re-run | not re-run | EVIDENCE (`sense_summary_20261011T015836Z.json`); no -40 C sense-stage result |

**Status of the old row.** "fs/-40 C pass/fail is insensitive to `C_RBL`"
still holds for the verdict on the design card, now down to 0.859 fF. It
does not hold for the separation value (0.017 -> 0.075 V). "ss/-40 C is not
insensitive" is confirmed. Its margin rises from 0.113 V to 0.370 V at the
bounding load.

**Still open** before any of this becomes a pass criterion:
* sense-input load (the share of the 10 fF the extraction cannot see);
* longer columns (`N_rows`);
* the bitcell device card (#89);
* real periphery (#114);
* an offset budget.

Rules 1-4 above still apply. The new runs keep the failed variants and a
negative control (`nc_write_disabled_ext4row`, all 8 points fail with
negative separation), and they ran as `klt sim` batch requests.
