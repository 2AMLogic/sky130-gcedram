# Physical write -> hold -> loaded read at the refresh deadline (issue #94)

Epic #24 item 2. The sense-stage study ([`sim/sense-stage/`](../sense-stage/README.md))
swept *imposed* pre-read storage-node levels and estimated droop with a first-order
constant-current formula. This study replaces the imposed level with a physical
trajectory: write through the access device, hold with the shipped sky130 models
evolving the storage node, then precharge / select / sense a loaded four-row column
with the latch. **Everything sits under the PROPOSED, UNRATIFIED operating range**
([`spec/operating-range-decision-PROPOSED.md`](../../spec/operating-range-decision-PROPOSED.md):
27 C and 125 C, tt/ss/ff/sf/fs, `VDD` = 1.8 V). No spec file, ratified value or
refresh bound was edited; the ratified bound (~5.03 us,
[`spec/retention-refresh-budget.md`](../../spec/retention-refresh-budget.md) section 7)
is only read, to classify points. The sense stage itself is still provisional.

## Result in one paragraph

All 10 corners ran (10/10 pass). **Every main case resolved correctly at every hold age
tested, up to 12 us (2.4x the 5.03 us bound)**: for each corner `all_within_bound_resolve`
is true and no main point failed at any age, so **no failure boundary was found in the
tested range** and the "points on either side of a failure boundary" the issue asked for
do not exist; the grid stops at 12 us. Worst case is sf / 125 C: the stored-'1' level
(written 1.221 V) droops by **0.274 V** by 5.03 us (pre-read 0.947 V) and by 0.57 V by
12 us (0.650 V, still read correctly, `din` -0.38 V, final -1.79 V). The worst stored-'1'
pre-read level within the bound across corners is 0.9475 V (sf/125 C); 27 C droop is
sub-millivolt to ~1.5 mV. This is **not** a refresh-bound sign-off: ideal drivers, global
corners only, no mismatch/offset (issue #81 supplies mismatch separately), an ASSUMED
100 mV reference offset, and a pattern enumeration that is a starting point. It also
does not replace or revise the analytical retention chain (below); it is an
independent physical trajectory that, for these inputs, shows the *provisional* latch
still deciding after the ratified interval. Any revised margin or interval needs its own
decision record.

## What was built

| File | Role |
|---|---|
| [`gen_aged_read.py`](gen_aged_read.py) | generates the two files below (all constants / ASSUMPTIONs at its top) |
| [`aged_read.spice`](aged_read.spice), [`request.json`](request.json) | flat deck, 322 parallel instances; 5 corners x {27, 125} C as one `klt sim` request, one `tran` per corner |
| [`analyze_aged_read.py`](analyze_aged_read.py) | reduces a committed klt report to a per-point CSV + per-corner summary (writes new files only, refuses to overwrite) |
| [`test_aged_read.py`](test_aged_read.py) | stdlib checks, wired into CI and `npm test` (not stale, scope, coverage, write order, analyzer on synthetic reports incl. failure/negative-control cases, committed summaries reproduce) |
| `results/` | append-only evidence |

## Method

Per case, 4 rows on one bitline pair (4-row column is a STUDY-ASSUMPTION):

1. **Write.** Each row's `wl` pulses 0 -> 1.8 V -> 0 for 20 ns (existing write drive, no
   boost), bitline driven to the data value. Every cell **starts at the opposite of its
   data** (0 V for a '1', 1.8 V for a '0'), so the write must flip it. Rows are written in
   25 ns slots, **the selected row last**: its hold age is exactly the case age; the other
   rows are 25-75 ns older.
2. **Hold** (`wl` = 0, `bl` = 0, deselected `rwl` = 1.8 V, `rbl` precharged to 0.9 V
   through an ideal 100 ohm switch). The storage node evolves by the device models only.
   Age is measured from the selected row's `wl` fall to the select edge.
3. **Read.** Precharge released 2 ns before the select edge, selected `rwl` falls, latch
   enabled 10 ns later (contract sense instant). Decision: `d = V(rbl) - V(ref)`, a '1'
   must go to -1.8 V.

| Input | Value | Status |
|---|---|---|
| `C_RBL` | 0.955559 fF, `comparison.c_rbl.extracted_4row_worst_total_ff` of [`layout/gain_cell_2t_array.parasitics.summary.json`](../../layout/gain_cell_2t_array.parasitics.summary.json) (post-#244; the pre-#244 0.859 fF runs are history), also on the matched dummy reference | extracted (#88); 4 rows is an ASSUMPTION |
| `C_SN` | 0.538402 fF, `comparison.c_sn.array_min_total_ff` (array-context, wiring only, smallest = worst droop) | extracted (#89); junction/gate C come from the device models |
| bitcell devices | `design/gain_cell_2t.spice` with the layout's drawn `AD/AS/PD/PS` (0.1974 / 1.78) | #89 reconciliation |
| latch | `design/sense_latch.spice`, the **corrected** schematic-derived latch (issue #293 provenance: `nrd/nrs/sa/sb/sd` included) | first-pass sizes, provisional |
| reference | `VREF` = 0.9 - 0.10 V, ideal matched dummy | ASSUMPTION |
| drivers, precharge switch | ideal | ASSUMPTION |
| mismatch | none (global corners) | not studied |
| solver | `.options method=trap gmin=1e-15 abstol=1e-15 chgtol=1e-18` (as refresh-energy) so the default gmin does not masquerade as leakage on a sub-fF node | |

**Latch provenance and PR #358.** The earlier sense-stage results for the extracted-`C_RBL`
variants are on the pre-#293 latch; corrected-latch results there are pending in PR #358
(open when this was written). This study uses the corrected latch for **every** point, so
its decisions do not inherit that gap, but they are not a replacement for #358's
variant-for-variant comparison. Inputs did not change the stage materially (extracted
`C_RBL` 0.956 fF vs the 10 fF assumption was already studied in #88), so no re-scope was
needed.

**Coverage.** Values {1, 0} x selected rows 0-3 x neighbour patterns of the other three rows
{`sss`, `ooo`, `sos`, `oso`} (s = same value as selected, o = opposite; ascending row
order; includes mixed stored values) x 10 ages
{5 ns, 0.5, 1, 2, 3, 4, **5.03**, 6.5, 8, 12 us} x 10 corners. The 4 patterns are a
**starting point, not a proven worst-case enumeration** (the 8 patterns per selected cell
and their ordering effects were not all run). 5 ns is the zero-hold control (the
shortest age the write-to-read sequencing allows).

**Negative control.** Two points (age 5 ns and 2 us) write a '1' with the wordline high
level at 0.55 V (below the access-device threshold): written level 0.264 V at sf/125 C,
the latch reads '0', and the analyzer sets `negative_control_detected` (true in all 10
corners). The zero-hold control resolves in all corners
(`zero_hold_control_ok_all_corners`).

## Per-point record

`results/aged_points_<RUN>.csv` has one row per (corner, case): `written_v`, `pre_read_v`,
`droop_v`, `post_sense_v`, `read_disturb_v` (`post_sense - pre_read`; the read pulls the
stored-'1' node down by up to 0.34 V at sf/125 C and the stored-'0' node moves too, which
is a property of the read, not aging), `din_v`, `dend_v`, `tdec_s`, signed `decision`,
`correct`, `resolves` (correct sign, |d| >= 0.9 V, tdec <= 5 ns, the sense-stage
criterion), `within_refresh_bound`, `meets_refresh_bound`. Failed points are kept.

## How it was run (host rules)

* The grid is one `klt sim` request on the **batch fleet** (`KLT_SIM_BACKEND=batch`,
  `--wait-for-capacity 600 --hosts 10`, one job per corner so each stays under the
  fleet's 3600 s job ceiling; the host's `klt` 0.9.3.dev was accepted by the runner).
  Fleet job ids are in `aged_summary_<RUN>.json` (`batch_fleet_jobs`).
  An earlier unsharded submission (`klt-sim-f14e52313ce8`) was abandoned before
  completion (its client was killed when its serial job bound was seen to exceed the
  ceiling); nothing from it is used.
* One **local** single-corner debug probe (tt/125 C, `--backend local`, ~7 min) was run
  first to check the deck; it is not recorded as evidence.
* The run reads the runner's ambient ngspice init file (a klt warning); the request does
  not declare `ngspice_init`, same as the other benches here.

## Evidence (append-only)

Run `20261118T201556Z`: ngspice-47, open_pdks `f6eeac7` (`docs/pdk-pin.md`), deck sha256
`e85e0481bbfa27a148845bf98b19ae7ef33624c54bfa370de6e760a0a64b8563`, model library sha256
`48de7c67...133c84`.

* `results/klt_report_20261118T201556Z.json` raw klt report, 10/10 corners pass
* `results/aged_points_20261118T201556Z.csv` 3220 rows
* `results/aged_summary_20261118T201556Z.json` per-corner metrics, assumptions, claims flags

Reproduce: `python3 -I sim/aged-read/gen_aged_read.py`, then
`KLT_SIM_BACKEND=batch klt sim --wait-for-capacity 600 --hosts 10 --format json sim/aged-read/request.json > sim/aged-read/results/klt_report_<NEW_RUN_ID>.json`,
then `python3 -I sim/aged-read/analyze_aged_read.py` on that report. Re-runs use a new run id.

## Relationship to the analytical retention chain

The ratified chain (leakage at temperature -> `C_SN` assumption -> retention) gives a
constant-current bound with `delta_V` = VDD/2 = 0.9 V of allowed droop
(~10.06 us retention, 5.03 us at 2x margin). This study does not test that formula's
inputs. It asks a different question: does the actual write/hold/read, with
voltage-dependent leakage from the device models and the extracted array capacitances,
still produce a correct latch decision at the ratified interval? At sf/125 C the
physical droop at 5.03 us is 0.274 V, well under 0.9 V. That is consistent with leakage falling as the node falls and the
written level (1.22 V) sitting above the `VDD/2` margin the formula assumes, but this
study did not isolate the cause. Nothing here changes a ratified number, and the analytical
chain's own cross-checks (sim/retention, sim/bitcell-transient) are unaffected. The
tested range is global corners with ideal drivers and no mismatch; offset/yield sign-off
needs #81's evidence and is not claimed.
