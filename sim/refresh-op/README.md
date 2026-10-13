# Closed-loop row refresh operation: measured `t_row_refresh_op` (issue #110)

Epic #24 item 3. Pass condition 3c of
[`spec/macro-pass-conditions-PROPOSED.md`](../../spec/macro-pass-conditions-PROPOSED.md)
asks for a *measured* `t_row_refresh_op` at the slowest restricted corner.
This study replaces the borrowed phase durations of
[`sim/refresh-overhead`](../refresh-overhead/README.md) with a transient
that runs the whole operation. **Everything sits under the PROPOSED,
unratified operating range** (27 C and 125 C, tt/ss/ff/sf/fs global corners,
`VDD` = 1.8 V, no mismatch, no other supply or temperature). No spec file,
ratified value or prior result record was edited; the 3c limit (50 %) and
`N_rows` stay ASSUMPTIONs.

## What was built

| File | Role |
|---|---|
| [`gen_refresh_op.py`](gen_refresh_op.py) | generates the two files below; constants and ASSUMPTIONs at its top; reuses the sense-stage latch/constants from `sim/sense-stage/gen_sense_stage.py` |
| [`refresh_op.spice`](refresh_op.spice) | flat circuit body for `klt sim` (241 parallel instances; bitcell cards inlined from `design/gain_cell_2t.spice`) |
| [`request.json`](request.json) | `klt sim` request: 5 process corners x {27, 125} C = 10 corners, one `tran` each, `backend: batch` |
| [`analyze_refresh_op.py`](analyze_refresh_op.py) | reduces the committed klt report to a points CSV + per-corner summary (new files only) |
| [`test_refresh_op.py`](test_refresh_op.py) | stdlib checks incl. the negative control on synthetic data and reproducibility of the committed summary; wired into CI |
| [`../refresh-overhead/eval_measured_t_row.py`](../refresh-overhead/eval_measured_t_row.py) | appends the overhead record to `../refresh-overhead/results/refresh_overhead_measured.csv` |
| `results/` | append-only evidence (below) |

## The operation (one instance)

`t = 0` precharge on (`rbl`/`ref` start at the opposite rails, i.e. the
previous op's decision) -> precharge released 2 ns before the select edge
(`T_READ` = 4 ns) -> RWL of row 0 falls -> **latch enable at select + SENSE**
-> **WWL pulse of width WB** starts `T_LATCH` after enable, and the latch's
*complement* node `ref` is connected to WBL through an ideal switch (a
stored '1' pulls `rbl` down, so `ref` goes high and writes a '1') ->
`T_GUARD` after WWL falls, latch enable, the WBL connection and RWL are
released -> SN is read 2 ns later (after RWL-coupling has settled).

`t_row_refresh_op` = precharge-on 2 + precharge gap 2 + SENSE + `T_LATCH` 1 +
WB + `T_GUARD` 2 ns. **Searched:** SENSE in {0.5, 1, 2, 5, 10} ns (10 ns is
the sense-stage contract instant) and WB in {0.5, 1, 2, 3, 5, 7.5, 10, 15,
20, 30, 50} ns. **Fixed, not minimised (ASSUMPTION):** precharge-on, gap,
`T_LATCH`, `T_GUARD`.

Patterns, each its own instance: stored '1' pre-read at 0.9 V (the retention
study's `VDD`/2 stored level) and 1.0 V; stored '0' pre-read at -0.1 V and
0.0 V. All four rows of the column hold the same level (as in sense-stage).

## Restore criterion and definitions (all ASSUMPTION)

* decision correct: `d = V(rbl) - V(ref)` just before WWL rises is
  <= -0.9 V for a '1', >= +0.9 V for a '0'. A wrong decision is never "restored".
* restored '1': SN(end) >= FRAC x SN_ref. **SN_ref is the in-deck reference
  write** at the same corner: SN from 0 V, ideal 1.8 V WBL, 20 ns WWL (the
  "post-write level" of the issue). FRAC reported at 0.90 / 0.95 / 0.98;
  **headline 0.95 (ASSUMPTION)**. Because the written level keeps creeping up
  with pulse width (sub-threshold-limited NMOS write, no boosted WL), the
  minimal pulse is strongly FRAC-dependent; that dependence is the result.
* restored '0': decision correct and SN(end) <= 50 mV.
* a (SENSE, WB) point passes when all four patterns are restored; the minimal
  pulse is the lowest WB for which every wider grid WB also passes, with the
  highest failing grid WB below it as the bracket (the grid is coarse: the true
  minimum is in that bracket, so t_row is an upper bound to within one step).
* Ideal drivers; ideal 100 ohm precharge and WBL-connect switches; `C_RBL` =
  `C_WBL` = 10 fF (ASSUMPTION, not extracted; #88/#89 values are not yet
  available); `C_SN` = 0.605354 fF (layout-extracted); reference = `VRBL` - 100 mV;
  first-pass latch sizes; 4-row column; **no mismatch** (offset is in
  [`sim/sense-mismatch`](../sense-mismatch/README.md), not folded in here).

## How it was run (host rules)

* The 10-corner grid is **one `klt sim` request on the batch fleet**; nothing
  was looped locally. Fleet job **`klt-sim-b8eb5b20d95e`** (m7i.4xlarge, spot,
  473 s; recorded in `environment.remote` of the report). A first
  submission of an earlier 133-instance grid (sense {2,5,10} ns; scratch, not
  kept) also passed on the fleet; the grid was then extended to shorter sense
  /pulse times and a stricter pre-read set (the 1.1 V pre-read was above 0.95 x
  the reference at the slow corners, so a no-write could pass; replaced by 1.0 V).
  Another submission of the final grid was refused with "no capacity in any of
  the 30 pools" and was resubmitted unchanged; no local fallback occurred.
* One **local** single-corner debug probe (`tt`/27 C, `--backend local`, the
  earlier 133-instance grid) was run to check the deck; it is not recorded as
  evidence.
* Client: `uvx --from klayout-tools==0.6.0 klt` (the newest the fleet runner
  accepted on 2026-10-09, see [`sim/sense-stage/README.md`](../sense-stage/README.md));
  no host tool was changed. No new klayout-tools issue: the friction met
  (client/runner version skew, capacity refusal) is already tracked / was
  surfaced visibly by the tool.
* The committed report is gzip-compressed with the job bucket name redacted
  (`<redacted-bucket>`); the rest is the unmodified klt output.

## Evidence (append-only)

Run `20261010T005003Z`: netlist sha256
`bd38e8c624fd846332a1ebf77341e826a266b5b12c61e4c0653137f6bf9074c0`
(as hashed by klt). Model library sha256 `48de7c67...133c84`, ngspice-46,
open_pdks per [`docs/pdk-pin.md`](../../docs/pdk-pin.md).

* `results/klt_report_20261010T005003Z.json.gz` raw klt report, 10/10 corners pass
* `results/refresh_op_points_20261010T005003Z.csv` 2400 rows (10 corners x 240 ops; the reference write is in the summary)
* `results/refresh_op_summary_20261010T005003Z.json` per-corner minimal pulses, `t_row_refresh_op`, margins, negative control, assumptions, claims flags
* `../refresh-overhead/results/refresh_overhead_measured.csv` overhead record (new file; prior CSVs untouched)

Rerun with a **new** run id, never edit these.

## Results

SN_ref is the ideal-driver reference write; `w_min` is the minimal passing WB
(highest failing grid WB below it); t_row in ns.

| Corner | T (C) | SN_ref (V) | FRAC 0.95: best SENSE / `w_min` / t_row (next-coarser WB t_row) | SENSE = 10 ns (contract): `w_min` / t_row | FRAC 0.90 / 0.98 at 10 ns: t_row |
|---|---:|---:|---|---|---|
| tt | 27 | 1.284 | 0.5 / 3 (2) / 10.5 (12.5) | 3 (2) / 20 | 18 / 24.5 |
| tt | 125 | 1.410 | 0.5 / 3 (2) / 10.5 (12.5) | 3 (2) / 20 | 18 / 24.5 |
| ss | 27 | 1.179 | 1 / 3 (2) / 11 (13) | 3 (2) / 20 | 18 / 24.5 |
| ss | 125 | 1.295 | 0.5 / 5 (3) / 12.5 (15) | 5 (3) / 22 | 19 / 24.5 |
| ff | 27 | 1.377 | 0.5 / 2 (1) / 9.5 (10.5) | 2 (1) / 19 | 18 / 22 |
| ff | 125 | 1.508 | 0.5 / 3 (2) / 10.5 (12.5) | 3 (2) / 20 | 18 / 22 |
| sf | 27 | 1.436 | 0.5 / 2 (1) / 9.5 (10.5) | 2 (1) / 19 | 18 / 22 |
| sf | 125 | 1.563 | 0.5 / 2 (1) / 9.5 (10.5) | 2 (1) / 19 | 18 / 22 |
| fs | 27 | 1.138 | 2 / 5 (3) / 14 (16.5) | 5 (3) / 22 | 19 / 27 |
| fs | 125 | 1.262 | 0.5 / 5 (3) / 12.5 (15) | 5 (3) / 22 | 19 / 27 |

**Decision-to-restored-level closure.** The latch decided correctly for every
pattern (both stored '1' pre-read levels and both stored '0' levels) at every
corner for SENSE >= 2 ns (SENSE = 1 ns also, except fs/27 C; SENSE = 0.5 ns also,
except ss/27 C and fs/27 C, where it fails) and the latch-driven write reaches the same level as
the ideal-driver write (e.g. fs/27 C, 20 ns pulse: 1.154 V from 0.9 V pre-read
vs SN_ref 1.138 V from 0 V). The read itself disturbs the stored '1' heavily
(fs/27 C: 0.9 V -> 0.77 V at WWL rise); write-back restores it. Stored '0'
restored at every passing point (a '0' needs no write: the '0' patterns are
not discriminating for the negative control).

**Does write-back restore the level?** Only as a fraction. The written level
creeps up with pulse width without saturating inside 50 ns, so "the
post-write level" is not a fixed target: 90 % needs 1-2 ns, 95 % 2-5 ns, 98 %
5-10 ns. The slowest corner is **fs/27 C** at 0.95 / minimum SENSE (lowest `SN_ref`,
1.138 V, and the decision needs SENSE >= 2 ns there); at the 10 ns contract
sense ss/125 C, fs/27 C and fs/125 C tie (5 ns pulse, 22 ns). The cause was
not isolated.

**Margin to the next-coarser step.** Each `w_min` sits one grid step above the
highest failing width (ratio 1.3-2 per step in the bracket column); the true
minimum lies inside it. Using the next-coarser WB costs +1 to +2.5 ns in t_row
(table).

**Negative control.** The 0.2 ns WWL pulse (shorter than every grid width) is
flagged unrestored by the analyzer at all 10 corners for every stored-'1'
pattern and SENSE (`negative_control_ok_all_corners: true`); the unit test
`test_synthetic_corner_flags_negative_control` also checks the flag on
synthetic data.

### Slowest restricted corner and 3c

Slowest-corner `t_row_refresh_op` (FRAC 0.95): **14 ns** (fs/27 C, searched
minimum SENSE) or **22 ns** (10 ns contract sense; ss/125 C, fs/27 C and fs/125 C tie
with 5 ns pulses). Overhead `N_rows x t_row / interval`
(`refresh_overhead_measured.csv`; interval 5.03 us = ratified, ASSUMED `C_SN`;
2.75 us = extracted `C_SN`, newer evidence not reflected in the spec):

| t_row (basis) | interval | `N_rows` = 4 | 64 | 128 | 256 | `N_rows` at 50 % | max power of two <= 50 % |
|---|---|---:|---:|---:|---:|---:|---:|
| 14 ns (min SENSE) | 5.03 us | 1.1 % | 17.8 % | 35.6 % | 71.3 % | 180 | 128 |
| 14 ns (min SENSE) | 2.75 us | 2.0 % | 32.6 % | 65.1 % | 130.2 % | 98 | 64 |
| 22 ns (10 ns SENSE) | 5.03 us | 1.8 % | 28.0 % | 56.0 % | 112.0 % | 114 | 64 |
| 22 ns (10 ns SENSE) | 2.75 us | 3.2 % | 51.2 % | 102.3 % | 204.7 % | 62.5 | 32 |

Against the 3c threshold (<= 50 %, ASSUMPTION): with the contract sense
instant a 64-row array **meets** it at the ratified 5.03 us interval but
**fails** it (51 %) at the 2.75 us extracted-`C_SN` interval; 128 rows fail at
both. These are 3c readings of a first-pass column, not a macro claim; the
macro's `N_rows` is unratified and no decision record was changed. A gain
cell refreshed every ~5 us remains a different proposition from SRAM.

## Not shown / limits

The shortest SENSE (0.5 ns) is a property of the *deck* (ideal drivers, 100 mV
reference separation, zero mismatch, 0.9 V pre-read) not a design claim:
random offset ([`sim/sense-mismatch`](../sense-mismatch/README.md)) would
raise it, and the contract's 10 ns is the safer basis. Not shown: Monte Carlo
or offset in the loop; precharge and guard minimisation (fixed ASSUMPTIONs; the
ideal switches settle in ~1 ps so the real floor is a driver design); boosted
WWL (would shorten the write); extracted `C_RBL`/`C_WBL`; supplies other than
1.8 V; temperatures outside {27, 125} C; the WBL driver being the sense latch
itself (no separate write driver); wear/energy; multi-row or banked refresh;
interaction of the 3 unselected rows beyond identical levels. No spec file
was changed.
