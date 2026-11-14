# Loaded four-row 2T column: stored levels and read separation (issue #45)

First **characterization** increment of Epic #24 phase 2 (sense path). It
answers a bounded question before any sense circuit is designed: with one
four-row column of the ratified 2T bitcell, what stored levels can the existing
write drive achieve, and what read-bitline response do those levels produce
(for both stored values, every selected row, every pattern of the other three
rows) across the 15-point corner/temperature grid, fresh and aged to the
~5.03 us refresh bound?

**This is not a sense amplifier, a sense decision, or an offset/yield
validation, and no all-corner functional-pass claim follows from it.** The
campaign contains failing engineering points on purpose; they stay visible.

## Files

| File | Role |
|---|---|
| [`tb_loaded_column.spice.tmpl`](tb_loaded_column.spice.tmpl) | Testbench template; its `.param` block is the single source of truth for phase timing |
| [`run_loaded_column.py`](run_loaded_column.py) | Runner: renders decks, runs ngspice, appends result rows |
| [`analyze_loaded_column.py`](analyze_loaded_column.py) | Coverage/provenance check, signed separation, summary JSON, optional separation gate |
| [`test_analysis.py`](test_analysis.py) | Analysis tests, incl. the impossible-threshold-fails test |
| [`results/loaded_column_results.csv`](results/loaded_column_results.csv) | Append-only evidence: 1920 rows, one per simulation point |
| [`results/summary_20261005T102906Z.json`](results/summary_20261005T102906Z.json) | Machine-readable per-group summary of that run |

Re-qualification under open_pdks `f6eeac7` (issue #169) adds:

| File | Role |
|---|---|
| [`gen_column_requests.py`](gen_column_requests.py) | Generator: writes the `klt sim` decks and batch requests from this study's own template/params |
| [`klt/`](klt) | The generated circuit bodies (`lc_<age>_sel<row>.spice`) and requests (`request_*.json`) that were submitted |
| [`reduce_column_results.py`](reduce_column_results.py) | Reducer: gates a report on the worker's PDK stamp, then appends rows in the schema above |
| [`compare_pins.py`](compare_pins.py) | Tabulates the two pins' deltas against a declared tolerance; also diffs two reports (`--compare-reports`) |
| [`test_gen_column_requests.py`](test_gen_column_requests.py) | Generator staleness / deck-relocatability / reducer-gate tests |
| `results/klt_report_lc_*_20261114T091445Z.json.gz` | The eight raw fleet reports (gzipped), one per request |
| [`results/summary_20261114T091445Z.json`](results/summary_20261114T091445Z.json) | Per-group summary of the `f6eeac7` run |
| `results/pin-attribution/` | Two single-corner local reports that isolate the PDK revision from the simulator version |

## Sources, pins, and what is derived from what

* **Bitcell devices**: parsed from the committed
  [`design/gain_cell_2t.spice`](../../design/gain_cell_2t.spice) (model, W/L and
  instance parameters of `M_WR`/`M_RD`); no device is restated by hand.
* **Array connectivity**: [`layout/array_topology.py`](../../layout/array_topology.py)
  `build_topology(4, 1)` -- `wl_r`/`rwl_r` per row, `bl_0`/`rbl_0` for the
  column, `sn_r_0` per cell, `M_WR` source on `bl`, `M_RD` drain on `rbl`,
  `M_RD` source on `rwl`. One column is simulated; the bitcell-transient
  conventions (1.8 V, plain 1.8 V wordlines, 20 ns write pulse, 100 ps edges,
  active-low read select on `rwl`, `rbl` bias `VDD/2`) are reused.
* **Storage-node capacitance**: the extracted 0.605354 fF per cell
  ([`layout/gain_cell_2t.extract.parasitics.json`](../../layout/gain_cell_2t.extract.parasitics.json),
  read via `sim/retention/derive_retention.py`), lumped on each `sn`, in
  addition to the models' own device capacitance (the same two-bound caveat as
  [`sim/bitcell-transient/README.md`](../bitcell-transient/README.md)).
* **Refresh bound**: `T_REFRESH_S` = 1.005989e-05 s / 2 = 5.029945e-06 s, from
  [`spec/retention-refresh-budget.md`](../../spec/retention-refresh-budget.md)
  section 7. It is used as given; the spec is not altered.
* **PDK / tool pins**: shipped sky130 combined ngspice library from the PDK
  pinned in [`docs/pdk-pin.md`](../../docs/pdk-pin.md) (open_pdks
  `c6d73a35f524070e85faff4a6a9eef49553ebc2b`, variant `sky130A`), ngspice-46,
  Python 3 stdlib only. Provenance is stamped on every CSV row
  (`repo_git_sha`, `pdk_open_pdks_commit`, `ngspice_version`, `run_id`). Note
  `repo_git_sha` is the repository HEAD at run time (`8aed192`, the base this
  PR branches from), i.e. before this directory was committed.

## Test bench, step by step

One `.tran` per (corner, temperature, age, selected row, 4-bit stored pattern):

1. **Write** (documented existing write drive: `wl` 0 -> 1.8 V -> 0, 20 ns,
   `bl` = 1.8 V for a '1' or 0 V for a '0', no boosting). The rows are written
   sequentially, row `r` at 1 ns + 25 ns * r; `bl` returns to 0 V 2 ns after
   the wordline is fully low. Initial condition is the **opposite** of the data
   (`.ic`), so each write is a genuine overwrite. Later rows' bitline swings
   see the earlier rows' `M_WR` (write-disturb through the access device is
   therefore in the numbers, in a fixed row order).
2. **Hold / age**: `wl` = 0, `bl` = 0, every `rwl` = 1.8 V (deselected), `rbl_0`
   held at 0.9 V by the precharge switch. `fresh` reads at 110 ns.
   `refresh_bound` reads at `t_wl_off(row 0) + 5.029945 us`, so row 0 is exactly at
   the bound and rows 1..3 are younger (`sel_row_age_at_read_s` and
   `max_row_age_at_read_s` record the actual ages). Ages are measured from
   the start of the wordline fall (`TW0+TWPULSE`); the fall ends one 100 ps
   edge later, so row 0's age after the wordline is fully off is ~100 ps short
   of the exact bound (negligible against 5.03 us).
3. **Precharge/read**: precharge switch (100 ohm on, 1e12 ohm off) opens 2 ns
   before the read, so `rbl_0` floats on the declared load; the selected row's
   `rwl` then falls to 0 V for 20 ns. `v_rbl_sense_v` is sampled `t_sense` after
   the select edge starts. Initial `rbl_0` = 0.9 V.
4. Measured per point: stored levels at each row's wordline fall and after write
   (all 4 rows), pre-read levels, signed per-row currents into `rbl` before the
   read and at the sense instant, `rbl` voltage at/after the sense instant,
   latency, and read disturb of the selected and of the worst unselected `sn`.

   Cross-reference (issue #114): the ideal precharge switch and ideal `bl_0` source here are compared with a designed slice in [`sim/column-periphery`](../column-periphery/README.md); the ideal-vs-real delta is tabulated there. The text above is the original study assumption and is left as written.

### Declared assumptions (proposed engineering choices, not spec values)

| Quantity | Value | Basis |
|---|---|---|
| `C_RBL` (rbl load) | 10 fF | **Assumed, schematic-level.** Stand-in for column wire plus sense-input load; **not extracted**. The four `M_RD` drain junctions are model-internal. `bl` is an ideal driver. |
| `t_sense` | 10 ns after select edge | Assumed; no sense circuit exists. |
| Latency threshold | `rbl` 0.1 V below its pre-read level | Assumed; latency is *time to that droop*, not a sense decision time. |
| Precharge level | 0.9 V (`VDD/2`) | Inherited from bitcell-transient. |
| Write order / read age | rows 0..3; read age referenced to row 0 | Test choice. |

No extracted bitline parasitics were used. Everything above `C_RBL` is
schematic-level; extracted-parasitic effects (bitline RC, wordline coupling)
remain further evidence.

### Sign conventions

* `i_into_rbl_r<k>_*`: current from `rwl_k` **through `M_RD` into `rbl_0`**.
  Positive charges the read bitline, negative discharges it. It is `-i(vrwl_k)`
  for the ngspice source branch. "Deselected-row currents" are the three
  non-selected rows' values; `_preread_` is sampled while `rbl` is still held at
  0.9 V, `_sense_` at the sense instant (`rbl` has moved).
* **Separation** `V_sep = V(rbl | stored 0) - V(rbl | stored 1)` at the sense
  instant; positive means the '1' discharged `rbl` further. The group
  worst-case separation is `min over stored-0 cases of V(rbl)` minus
  `max over stored-1 cases of V(rbl)`, over all patterns in the group
  (per selected row, and a `column_all_rows` group over all four rows).
* Read disturb = `V(sn)` after the read tail minus `V(sn)` immediately before.

## Reproduce

```bash
python3 sim/loaded-column/run_loaded_column.py --check-env
python3 sim/loaded-column/run_loaded_column.py            # full 15-corner campaign (1920 points)
python3 sim/loaded-column/run_loaded_column.py --corners fs --temps-c -40 --jobs 4   # subset
python3 sim/loaded-column/analyze_loaded_column.py        # coverage + provenance + summary JSON
python3 sim/loaded-column/analyze_loaded_column.py --min-separation-v 0.1   # optional gate
python3 sim/loaded-column/test_analysis.py
```

The runner batches the 16 stored patterns of one (corner, temperature, age,
row) into one ngspice process (`alterparam` + `reset`), because the PDK library
parse dominates a single run; a batched case was checked to reproduce the
standalone-run values exactly. Each case runs after `destroy all` (an aborted
`tran` leaves no plot, so no output file, rather than the previous case's
data), and a case whose last timepoint is earlier than its planned stop time
is recorded as `sim_failed`. These guards were added after run
`20261005T102906Z`; a re-run of the fs/27 C row-0 batches (both ages, 32
points) with the guarded runner reproduced every committed field exactly. A full campaign took ~20 minutes of wall time on
a shared 18-core machine. Results are appended (never rewritten); the analyzer
defaults to the latest `run_id` and refuses to overwrite a summary.

### Analysis exit codes and the impossible-threshold test

`analyze_loaded_column.py` exits 0 if coverage/provenance pass (and an optional
`--min-separation-v` gate is met), 1 on missing/duplicated/unexpected points or
missing provenance, 2 when a gate threshold is not met. Failing engineering
points do **not** fail the default check -- they are reported. `test_analysis.py`
verifies on synthetic data and on the committed campaign that a deliberately
impossible threshold (`--min-separation-v 50`) exits 2, and that a missing point
exits 1.

## Results (run `20261005T102906Z`)

Coverage: 5 corners x 3 temperatures x 2 ages x 4 selected rows x 16 patterns
= **1920 points, 0 simulation failures, coverage and provenance check OK**
(each selected row sees both stored values with all 8 patterns of the other
three rows). At the assumptions above, 150/150 groups have a positive
worst-case separation, but fs/-40 C is effectively failing, ss/-40 C is
marginal, and fs/27 C has roughly half the margin of the remaining 12
points; this positivity is a property of the assumed light load
and a fixed 10 ns sense instant, not a validated margin.

Worst-case column separation (all rows, all patterns), signed per the
convention above:

| Corner / T | fresh | refresh bound | Notes |
|---|---:|---:|---|
| fs / -40 C | 0.018 V | 0.017 V | **Failing engineering point.** Stored '1' only 0.864 V (0.860 V aged); `rbl` droop never reaches the 0.1 V latency threshold in 32 of 128 stored-'1' points (reason recorded per row) |
| ss / -40 C | 0.121 V | 0.113 V | Marginal. Stored '1' 0.896 V (0.893 V aged); latency up to 8.6 ns, close to `t_sense` |
| fs / 27 C | 0.286 V | 0.272 V | **Reduced margin.** Stored '1' 0.932 V (0.929 V aged); latency up to 2.8 ns (3.0 ns aged); worst stored-'1' `rbl` 0.61 .. 0.63 V; separation about half that of the other room/hot corners |
| other 12 points | 0.515 .. 0.654 V | 0.586 .. 0.659 V | `rbl` for stored '0' stays at ~0.899 V; worst-case (highest) stored-'1' `rbl` 0.24 .. 0.38 V |

The fs corner degrades monotonically from 125 C (0.654 V) through 27 C
(0.286 V) to -40 C (0.018 V), and ss is also low at -40 C: the low-margin
region is the fs/ss cold-to-room side of the grid, not two isolated points.
(Per selected row, the largest separation is 0.660 V, at fs/125 C aged, row 3;
the table gives column-wide worst cases.)

Other measured quantities (full per-corner detail in the summary JSON):

* **Stored levels** (selected cell, after write, minimum over patterns): stored
  '1' ranges 0.864 V (fs/-40 C) to 1.217 V (sf/125 C), stored '0' sits at
  -0.135 .. -0.061 V (wordline feedthrough pushes it below ground). Aged to the
  bound the minimum stored '1' pre-read level is 0.860 V (fs/-40 C); the
  hottest corners decay most (sf/125 C: 1.217 -> 0.956 V). Stored '1' is below the
  assumed 0.9 V sense-margin reference at fs/-40 C and ss/-40 C. This is
  reported, not adjusted in the spec.
* **Latency** to the assumed 0.1 V droop (stored '1'): 0.11 ns .. 8.6 ns where
  reached (slowest at ss/-40 C); missing at fs/-40 C as above.
* **Read disturb** on the selected `sn`: -0.064 .. +0.067 V over the campaign
  (per-group ranges in the summary JSON).
* **Deselected-row currents** (signed, into `rbl`): before the read they are
  pA to ~nA (up to +1.8 nA at sf/125 C fresh, negative, down to about -14 pA, at some hot
  points). **At the sense instant**, once a selected '1' has pulled `rbl` down,
  deselected rows storing '1' *source current into `rbl`* (rwl at 1.8 V), up to
  +24 uA at sf/125 C fresh -- comparable to the selected cell's own sink current.
  The pattern of the other rows therefore moves the stored-'1' result and is
  the dominant source of the spread between the best and worst stored-'1'
  `rbl` values.

## Do the distributions permit a proposed sense reference?

Under the stated assumptions, every group has a positive window between the
two distributions (`candidate_reference_v_UNVALIDATED` and
`candidate_reference_half_window_v` in the summary), but its width varies
strongly:

* At 12 of 15 corner/temperature points, both ages: column window
  0.515 .. 0.659 V wide (half-window >= 0.257 V), lying roughly between
  0.24 .. 0.38 V (worst stored '1') and ~0.899 V (stored '0').
* fs/27 C: window ~0.27 .. 0.29 V wide (half-window 0.136 .. 0.143 V), between
  ~0.61 .. 0.63 V and ~0.899 V.
* ss/-40 C: ~0.11 .. 0.12 V wide; fs/-40 C: ~0.02 V -- no credible single
  reference, given any non-zero comparator offset.

The window centres also move (0.57 .. 0.64 V at the 12 points, 0.76 V at
fs/27 C, 0.84 .. 0.89 V at the cold fs/ss points). A single fixed `rbl`
reference common to the 13 non-cold points would have to sit between
0.627 V (fs/27 C aged, worst stored '1') and 0.899 V, i.e. half-window
~0.136 V set entirely by fs/27 C; no common reference reaches fs/-40 C or
ss/-40 C. Because the result rests on an
assumed load (`C_RBL`) and an assumed sense instant, and the window narrows
from room to cold temperature on the fs/ss side, **no sense reference is
proposed or ratified**.

## What further evidence is needed

* Extracted bitline/wordline parasitics (and a real `C_RBL`), then a sensitivity
  over load and sense time.
* Resolution of the cold-corner write-level shortfall (stored '1' < 0.9 V at
  fs/-40 C and ss/-40 C) through the normal spec decision process
  (read-device sizing is still a placeholder).
* A sense-circuit schematic with an offset/noise budget and Monte-Carlo or
  statistical-mismatch evidence; none is claimed here.
* Longer columns (this is four rows; deselected-row loading scales with row count).
* Re-simulation after any refresh-interval change (this study read at exactly
  the current bound only for row 0).

## Limitations

Single column (no neighbouring-column coupling); ideal write driver and
precharge; row 0 is the oldest row; sequential write order is fixed; process
corners are global (no mismatch). Append-only rule: the existing
`sim/bitcell-transient/` evidence is untouched.

## Re-qualification under open_pdks `f6eeac7` (issue #169)

The repo pin moved from `c6d73a3` to `f6eeac7`
([`docs/pdk-pin.md`](../../docs/pdk-pin.md)), so this study's records were
re-run under the new pin. The `c6d73a3` rows, summary and text above are
**unchanged**; the new grid is appended as run `20261114T091445Z`.

### How it was run

The grid is expressed as `klt sim` corner requests and run on the batch fleet
(`sim/README.md`; a hand-launched local `ngspice -b` grid is not an option on a
shared host). Eight requests -- one per (age, selected row) -- each cover the
full 15-point PVT grid, so 120 corner units and 1920 points, the same grid as
run `20261005T102906Z`:

| | |
|---|---|
| Requests / decks | [`klt/request_lc_{fresh,refresh_bound}_sel{0..3}.json`](klt) + the matching `.spice` bodies |
| Batch jobs | `klt-sim-79cbeb8482ff`, `0076e86a56b6`, `2347ba3b15f5`, `f5cd4b1fee75` (fresh); `602978304e45`, `9a613789fd90`, `c071ae6a92be`, `bfacea7f99c0` (aged) |
| Result | 120/120 units `pass`, 0 errored, 0 inconclusive; 1920 rows, 0 `sim_failed` |
| Worker | aws-batch-fleet, m7i.4xlarge spot, runner klt 0.9.0 (`runner_compatibility: match`), client klt 0.9.2.dev1029 |
| Simulator | **ngspice-47** (`engine_build_comparison: match`); the `c6d73a3` records are ngspice-46 |
| Worker PDK | `open_pdks f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7`, `stamp_scheme: sources-sha256`, **`pdk_stamp_comparison: match`** |
| Per-unit runtime | 3.8 .. 5.2 s (fresh), 7.1 .. 8.0 s (aged) |

`reduce_column_results.py` **refuses** to write a row from a report whose
`pdk_stamp_comparison` is not `match`, or whose worker stamp does not name the
repo pin (issue #169's condition for filing a fleet run under this pin); the
refusal is covered by `test_gen_column_requests.py`. The client-side half of
that comparison needs `$PDK_ROOT` to be set explicitly, because this host has
two `sky130A` installs and `backend: batch` refuses `--pdk-root`
(2AMLogic/klayout-tools#5731); without it the comparison comes back
`not_comparable: client_stamp_unavailable` and nothing may be recorded.

### Three declared differences from `run_loaded_column.py`, and their size

`klt sim` has no per-case axis for a transient grid and cannot return named
transient node vectors (2AMLogic/klayout-tools#5731), so the deck and the
reductions are shaped differently from the local runner. Each difference was
measured, not assumed:

1. **16 stored patterns are 16 independent column instances in one deck**,
   instead of 16 `.control`/`alterparam` cases in one process. The instances
   share only ideal voltage sources (write/read wordlines, the precharge
   source and its control), so none loads another; a per-instance 0 V source
   `vam_r<r>_p<pp>` carries each cell's read current so the wordline sources
   can be shared (`i_into_rbl = +i(vam)`, where the local runner read
   `-i(vrwl_r)` of an unshared source).
2. **Reductions are `.meas` cards** at the same instants
   `run_loaded_column.measure()` interpolates at, not Python interpolation of
   a `wrdata` waveform. `i_desel_sum_*`, `dv_rbl_sense_v`, `latency_s`,
   `dv_sn_sel_read_disturb_v` and `dv_sn_unsel_worst_signed_v` are still
   derived arithmetically, now in the reducer.
3. **The latency threshold is the absolute level `VRBL - 0.1 V`**, because
   ngspice cannot reference one `.meas` result from another's `WHEN` value.
   The local runner used the *measured* pre-read float level minus 0.1 V.
   Over the new grid that level differs from `VRBL` by at most 9.9e-04 V
   (mean 2.2e-05 V), which is <= ~1 ps of latency against latencies of
   0.11 .. 6.31 ns. Both the threshold used and `v_rbl_preread_float_v` are on
   every row, so the difference is visible rather than assumed.

**Equivalence check for (1) and (2)** -- the new deck run through `klt sim
--backend local` against the *same* PDK tree and the *same* ngspice-47 as a
`run_loaded_column.py` run of the same point (tt, 27 C, fresh, selected row 0,
all 16 patterns): worst relative deviation **4.1e-04**, on a deselected-row
current of 6.68e-11 A (absolute 2.7e-14 A); `v_rbl_sense_v` 1.3e-04 relative
(absolute 1.7e-10 V); latency agreed to seven significant figures
(2.302366e-10 s vs 2.302367e-10 s). The deck reshape and the `.meas`
reductions therefore account for none of the changes below.

### What changed, and why

Every headline figure moved slightly in the favourable direction, and **no
conclusion of this study changes**: 150/150 groups still have a positive
worst-case separation, the cold-corner written-level shortfall is still there
(worst stored '1' storage node 0.8697 V, still below the 0.9 V the text above
discusses), and the same 64 stored-'1' points still never reach the latency
threshold.

| Quantity | `c6d73a3` / ngspice-46 | `f6eeac7` / ngspice-47 |
|---|---|---|
| Worst-case separation, min over the 150 groups | 0.016729 V | 0.024480 V |
| Worst-case separation, max over the 150 groups | 0.659577 V | 0.681050 V |
| Worst stored-'1' `rbl` at `t_sense` | 0.882141 V | 0.874437 V |
| Lowest stored-'0' `rbl` at `t_sense` | 0.898648 V | 0.898709 V |
| Lowest stored-'1' storage node after write | 0.863683 V | 0.869663 V |
| Lowest stored-'1' storage node pre-read | 0.860385 V | 0.866506 V |
| Latency (stored '1'), max / n measured / n never crossed | 8.5539e-09 s / 896 / 64 | 6.3099e-09 s / 896 / 64 |
| \|read disturb\| on the selected node, max | 0.067252 V | 0.060645 V |
| \|read disturb\| on an unselected node, max | 0.060136 V | 0.056588 V |
| \|deselected-row current sum\| at `t_sense`, max | 2.8362e-05 A | 3.0482e-05 A |

Row-level deltas are tabulated by

```bash
python3 -I sim/loaded-column/compare_pins.py
```

which joins the two runs on (corner, temperature, age, selected row, stored
pattern) -- 1920 shared points, none missing on either side -- and checks each
point against a **declared comparison tolerance** (`|head-base| <= max(atol,
2% x |base|)`, atol 1 mV / 1 pA / 10 ps; these are comparison tolerances
stated for this check only, not spec thresholds, and nothing in `spec/` is
relaxed by them). **16 of the 29 compared fields have points outside it**; the
largest movements are `v_rbl_sense_v` up to 8.76e-02 V (tt, -40 C, aged),
`latency_s` up to 2.24e-09 s (ss, -40 C, aged), the read currents up to ~8%
(sf, 125 C) and the deselected-row currents up to ~15% (sf, 125 C, where they
are ~1e-09 A). `compare_pins.py` exits 1 while any field is outside tolerance,
so this is a visible, standing condition and not a silent pass.

**The PDK revision is not the cause.** The same deck, run locally at sf/125 C
(the largest-delta corner) twice with nothing changed but which open_pdks tree
`$PDK_ROOT` resolved to, gives **bit-identical** results:

```bash
python3 -I sim/loaded-column/compare_pins.py --compare-reports \
  sim/loaded-column/results/pin-attribution/klt_report_local_sf125_c6d73a3_ngspice47_20261114T091445Z.json.gz \
  sim/loaded-column/results/pin-attribution/klt_report_local_sf125_f6eeac7_ngspice47_20261114T091445Z.json.gz
# 464 shared measurements: 456 bit-identical, 0 differ
```

(the eight without a value are the stored-'0' latency measurements, which have
no crossing by construction). The `c6d73a3` probe reads the retired
`~/.volare` tree deliberately and only for this attribution; it is not grid
evidence and nothing is recorded from it. So for this study the two open_pdks
revisions' models are numerically indistinguishable, and the movement above is
the **simulator upgrade, ngspice-46 -> ngspice-47**, which arrived on the fleet
image with the new PDK. That is a tool-version sensitivity of the committed
characterization numbers, not a model-revision finding; it is tracked in
**#300** -- it is not resolved here and no threshold was changed to absorb
it.

### Reproduce

```bash
export PDK_ROOT=~/.ciel            # required: `backend: batch` refuses --pdk-root
python3 -I sim/loaded-column/gen_column_requests.py --check     # decks/requests current?
cd sim/loaded-column/klt
klt sim --batch-set request_lc_fresh_sel0.json ... request_lc_refresh_bound_sel3.json \
    --max-in-flight 4 --wait-for-capacity 600 --capacity-retries 2
cd -
python3 -I sim/loaded-column/reduce_column_results.py --run-id <new-run-id> \
    sim/loaded-column/results/klt_report_lc_*_<new-run-id>.json.gz
python3 -I sim/loaded-column/analyze_loaded_column.py --run-id <new-run-id>
python3 -I sim/loaded-column/compare_pins.py
python3 -I sim/loaded-column/test_gen_column_requests.py
```

A single corner can be re-run locally for a debug probe
(`klt sim <request> --backend local` with the request's `corners` narrowed);
the full grid must go to the fleet.

### Not re-qualified here

The **cold-corner variant campaign** in [`cold-corner/`](cold-corner) is still
pinned to `c6d73a3` and ngspice-46. Its grid is 10176 points (30 variants x
their scopes x 4 selected rows x 16 patterns), and at ~29 `.meas` declarations
per point -- the only reduction shape `klt sim` offers for a transient grid --
it does not fit a committed request/report evidence set at that granularity
(~305k measurement declarations, tens of MB of JSON). See
2AMLogic/klayout-tools#5731 for the tool gap and **#301** for the follow-up,
which names the three ways out and the checks that must move with it. `gen_column_requests.py` is already knob-parameterised
(`BASELINE_KNOBS` is asserted equal to `cold-corner/variants.py`'s `BASELINE`)
so that campaign can reuse this shape unchanged once its size question is
settled.
