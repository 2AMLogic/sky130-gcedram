# Write disturb of unselected and half-selected cells (issue #98)

Epic #24 item 6 (write/read functional margin). Retention evidence covers the
*selected* cell surviving to the refresh deadline; this study asks what a
write does to the cells that were **not** being written: the other rows on
the shared write bitline (WBL), and the other columns on the asserted write
wordline (half-selected). **Everything here sits under the PROPOSED,
UNRATIFIED operating range** of
[`spec/operating-range-decision-PROPOSED.md`](../../spec/operating-range-decision-PROPOSED.md)
(tt/ss/ff/sf/fs at 27 C and 125 C, `VDD` = 1.8 V). No spec file, retention
CSV, decision record or refresh bound was edited; failures below are kept,
not tuned away.

## Result in one paragraph

Under 147 back-to-back writes (the most a 34 ns scheduler could issue in the
ratified 5.03 us window) to one column, at **sf / 125 C (ratified worst-case
retention corner)** the worst unselected cell on the shared WBL loses
**147.5 mV = 16.4 % of `delta_V` (0.9 V)** more than the matching no-disturb
control, which the ratified formula reads as **1.65 us of the 10.06 us
retention time**; charging it to the sense margin would move the 2x-margin
refresh interval from 5.03 us to **4.21 us** (a first-order bookkeeping
figure, *not* a proposed spec change). That is over the 10 % screening limit
this study assumes, so sf/125 C is **FLAGGED**. ff/125 C is at the limit
(10.00 %, not over); tt/125 C is 1.6 %; ss, fs at 125 C are 0.2-0.3 %; every
27 C corner is at most 0.12 % (sub-millivolt, near the resolution floor). The
worst case is the *stored '1'* victim when the WBL **idles high and pulses
low** (`rep0`); the idle-low architecture (`rep1`) costs at most 44.5 mV at
sf/125 C. Neighbouring columns (different WBL, coupling through the extracted
parasitics) move by less than 1 uV; half-selected cells on the asserted row
move by up to 0.17 V but **in the benign direction** (see below). A 10x-wider
write device (negative control) is distinguishable from the real device at
every 125 C corner and exceeds the limit at tt, ff and sf (42.1 % at sf).

This is a result for ideal drivers, global corners only, the ASSUMED data
word below, and the extracted array's own storage-node capacitance (not the
ratified 1.106463 fF). It is not a macro-level disturb budget.

## What was built

| File | Role |
|---|---|
| [`gen_write_disturb.py`](gen_write_disturb.py) | generates the two files below from the committed extracted array netlist (all constants live at its top) |
| [`write_disturb.spice`](write_disturb.spice), [`request.json`](request.json) | flat deck: 10 independent instances of the extracted 4x4 array; the 5 global corners x {27, 125} C as one `klt sim` request, `backend: batch`, one 5.1 us `tran` per corner |
| [`analyze_write_disturb.py`](analyze_write_disturb.py) | reduces a committed klt report to a points CSV, a half-select CSV and a summary JSON (writes new files only) |
| [`test_write_disturb.py`](test_write_disturb.py) | stdlib checks, wired into CI: generated files not stale, scope inside the PROPOSED range, extracted array inlined faithfully (32 devices, every R and C), negative control widens exactly the 16 write devices, analyzer unit tests on synthetic reports (no-disturb control reads 0, known disturb recovered as fraction/loss, over-limit flagged and kept, negative control distinguishable / non-discriminating cases, failed report writes nothing, no overwrite), committed summaries reproduce byte-for-byte from the committed reports |
| `results/` | append-only evidence (below) |

## Topology and stimulus

Each instance is the extracted array
[`layout/gain_cell_2t_array.extract.parasitics.spice`](../../layout/gain_cell_2t_array.extract.parasitics.spice)
**as is** (the array storage-node capacitance is not yet reconciled, #89):
32 devices with their extracted drawn diffusion (`AD`/`AS`/`PD`/`PS`), the
lumped per-net R, ground C and every net-to-net coupling C, re-emitted
node-for-node by the generator. Two deliberate translations: the generic
`nfet` becomes `sky130_fd_pr__nfet_01v8`, and `GND`/`vsubs` are tied to ideal
ground (the file's 1 Tohm `vsubs` tie would leave the substrate floating over
5 us).

Idle bias of everything not under test: read wordlines at `VDD` (read device
off), read bitlines at 0.9 V (ideal source), unselected write wordlines at
0 V. Stored levels at t = 0: '1' = 1.0 V, '0' = 0.0 V (ASSUMPTIONS; every
`rwl`/`rbl`/`bl` terminal node is initialised to its idle value). Rows 1-3
of every column hold `1, 0, 1`, so every WBL has victims of both polarities.

| Instance | Row 0 stored / WBL data | Purpose |
|---|---|---|
| `ctl0` | `0000`, all WBLs held at 0 V, WL off | **no-disturb control**, idle-low WBL |
| `ctl1` | `1111`, all WBLs held at `VDD`, WL off | **no-disturb control**, idle-high WBL |
| `rep1` | `0000`; column 1 WBL pulses 0 -> `VDD` with every write, other WBLs 0 V | repeated writes of '1', both polarities of victim on the shared WBL; columns 0, 2, 3 are **half-selected** (WL on, WBL at their own data) on every write |
| `rep0` | `1111`; column 1 WBL pulses `VDD` -> 0, other WBLs `VDD` | mirror image |
| `hs_p1` | `0010`; WBLs `0,pulse-high,VDD,0`, one write | **half-select, polarity 1**: half-selected cells of both polarities between an aggressor column that swings 0 -> `VDD` and one that holds `VDD` |
| `hs_p0` | `1101`; WBLs `VDD,pulse-low,0,VDD`, one write | **half-select, polarity 0** (inverse) |
| `neg_ctl0/1`, `neg_rep1/0` | as above | **negative control**: every write access device 10x wider (`LEAKY_W_FACTOR`, W, AD/AS, PD/PS scaled), with its own matching controls |

Timing (all ASSUMPTIONS): one write op every 34 ns (`T_ROW`, the
[`digital/refresh-scheduler`](../../digital/refresh-scheduler/README.md) and
[`sim/refresh-overhead`](../refresh-overhead/README.md) value), WBL moves
2 ns before the 20 ns WL pulse and returns 2 ns after it (100 ps edges).
`N` = 1, 4, 16, 64 and **147** = floor(5.03 us / 34 ns) consecutive writes; the
stored nodes are sampled at the end of write `N` (WBL back at idle, same
instant in the toggled instance and its control, so coupling offsets cancel).
Writes always hit row 0; a real refresh walks rows, but the WBL stimulus,
which is what the victims see, is the same. Every victim sees the same
per-cell stress regardless of how many rows share the WBL (ideal driver);
the macro has N-1 such victims per WBL, this deck has 3.

Numerical options (`.options gmin=1e-15 abstol=1e-15 chgtol=1e-18`): the
ngspice defaults (`gmin` 1e-12 S, `chgtol` 1e-14 C) are as large as the
27 C off-current and the ~1 fC storage charge being measured. The 27 C
numbers are still tiny; the analyzer marks values under 1 mV as below
resolution and nothing is claimed from them beyond "not measurable here".

## Definitions

* **Erosion** of a victim = how much further its storage node moved, *in the
  direction that destroys the stored data*, than the same node in the
  matching no-disturb control at the same instant: stored '1' loses
  (`ctl - toggled`), stored '0' gains (`toggled - ctl`). Matching control:
  `rep1` -> `ctl0`, `rep0` -> `ctl1`. Negative erosion (stimulus helped) is
  reported, never clipped.
* **Fraction of `delta_V`** = erosion / 0.9 V (the ratified derivation's
  ASSUMED sense margin; [`spec/retention-refresh-budget.md`](../../spec/retention-refresh-budget.md)).
* **Equivalent retention loss** (two forms):
  * `t_loss_ratified_s` = fraction x 10.06 us: what the ratified
    `t = C_SN * delta_V / I_leak` loses if the same fraction of `delta_V` is
    spent. `refresh_bound_derated_s` = 10.06 us x (1 - fraction) / 2.
    First order and linear, and it inherits the ratified 1.106463 fF
    ASSUMPTION; the disturb here was produced with the extracted array
    capacitances, so this is a bookkeeping translation, not a re-derivation.
  * `equiv_hold_time_s` = erosion / the isolated-cell hold drift rate of the
    same node (worst-case control, between the 1st and 147th write). Both
    scale with 1/C_SN, so this is independent of the C_SN assumption: "the
    disturb costs as much data margin as N us of plain hold leakage". It is
    empty where the control does not drift (27 C ss/fs).
* **Flagged** = fraction > `DISTURB_LIMIT_FRAC` = 10 % (an ASSUMPTION for a
  screening line, not a spec value; all fractions are in the CSVs so any other
  limit can be applied).

## Results

Run `20261009T172606Z` (sources: [`results/`](results/)). Fleet job
**`klt-sim-9cd63f28e1c1`** (aws-batch-fleet, m6i.4xlarge, spot, 706 s,
`done`, exit 0), 10/10 corners pass, 0 missing values; client throwaway
`uvx --from klayout-tools==0.6.0 klt sim --backend batch`. A one-corner local
single-unit probe (sf/125 C, `klt sim --backend local`) was run first and its
720 measurements are identical to the batch ones (it is not committed as
evidence).

Worst victim per corner at N = 147 writes, normal devices (both WBL
architectures, shared-WBL, neighbour and half-selected-row victims; the
intentionally written target cell is excluded):

| Corner | T (C) | Worst victim | Erosion | of `delta_V` | `t_loss` (ratified) | derated refresh bound | equiv. hold time | `rep1` worst | Negative control worst |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| tt | 27 | `rep0` row 1, '1' | 0.05 mV | 0.01 % | 0.001 us | 5.030 us | (3.6 us) | 0.02 mV | 2 mV (0.2 %) |
| tt | 125 | `rep0` row 3, '1' | 14.2 mV | 1.58 % | 0.159 us | 4.950 us | 1.13 us | 4.4 mV | 175 mV (19.4 %) **flag** |
| ss | 27 | `rep1` row 1, '1' | 0.00 mV | 0.00 % | 0.000 us | 5.030 us | n/a | 0.00 mV | 0 mV (0.1 %) |
| ss | 125 | `rep0` row 2, '0' | 2.5 mV | 0.28 % | 0.028 us | 5.016 us | 0.61 us | 0.00 mV | 73 mV (8.1 %) |
| ff | 27 | `rep0` row 1, '1' | 0.54 mV | 0.06 % | 0.006 us | 5.027 us | (3.5 us) | 0.20 mV | 7 mV (0.8 %) |
| ff | 125 | `rep0` row 1, '1' | 90.0 mV | 10.00 % | 1.006 us | 4.527 us | 2.68 us | 33.3 mV | 418 mV (46.5 %) **flag** |
| sf | 27 | `rep0` row 1, '1' | 1.11 mV | 0.12 % | 0.012 us | 5.024 us | (3.5 us) | 0.39 mV | 5 mV (0.5 %) |
| **sf** | **125** | `rep0` row 3, '1' | **147.5 mV** | **16.39 %** | **1.649 us** | **4.205 us** | **2.97 us** | 44.5 mV | 379 mV (42.1 %) **flag** |
| fs | 27 | `rep1` row 1, '1' | 0.00 mV | 0.00 % | 0.000 us | 5.030 us | n/a | 0.00 mV | 1 mV (0.1 %) |
| fs | 125 | `rep0` row 2, '0' | 2.0 mV | 0.22 % | 0.022 us | 5.019 us | 0.51 us | -1.3 mV | 76 mV (8.5 %) |

Equivalent hold times in parentheses sit on sub-mV erosions and are not
meaningful. At the worst corner (sf/125 C) the build-up with the number of
consecutive writes, shared-WBL victim:

| N writes | 1 | 4 | 16 | 64 | 147 |
|---|---:|---:|---:|---:|---:|
| `rep0` (WBL idles high), mV | 1.1 | 4.4 | 17.6 | 68.0 | 147.5 |
| `rep1` (WBL idles low), mV | 0.5 | 2.1 | 8.2 | 27.2 | 44.5 |

Roughly linear in the number of writes (each write costs ~1 mV of stored-'1'
margin at the worst corner when the WBL pulses low), with `rep1` sub-linear.
So a smaller number of writes per window scales the disturb down; the 147
figure is the adversarial bound where every operation in the window is a
write to the same WBL.

**Why `rep0` is worst.** In the idle-high architecture the control parks the
WBL at `VDD`, where a stored '1' has no leakage path out; each write drives
the WBL low for 24 of 34 ns, and a stored '1' victim then leaks through its
off write device at Vds ~ 1 V. In the idle-low architecture the control
already has the WBL at 0 V, so pulsing it high mostly *helps* stored '1'
(negative erosion down to -139 mV) and only hurts stored '0', by at most
44.5 mV. The controls are therefore architecture-matched; there is no
comparison across the two idle conventions, and no WBL idle level between
them was run.

**Neighbouring columns.** The WBL swing of column 1 changes columns 0, 2, 3
(rows 1-3) by at most 1 uV (negative control: 1 uV): the coupling capacitors
in the extracted file (e.g. `Ccc_bl_1_sn_*`, ~10 aF) kick the node during an
edge and the kick is gone by the checkpoint. Not a leakage mechanism in this
model; lateral coupling is only modelled for the declared critical nets
(see the model limits in the extraction file).

**Half-select.** Half-selected cells on the asserted row never lose data to
the write in this word-write model. With each half-selected bitline at its own
data (a rewrite): stored '0' cells shift by -0.15 to -0.17 V at 125 C and end
0.12-0.14 V **below ground** (wordline falling-edge undershoot, the same order
as the -0.135 V floor the sense input contract assumes); stored '1' cells
rewritten from about 1.05 V shift by +0.01 to +0.14 V (ending 1.05-1.20 V;
during the pulse they rise to about 1.38 V and relax after the wordline
falls). Both shifts move *away from* the opposite level, so erosion is
negative (benign): the largest erosion of any half-selected cell in the whole
grid is -9.6 mV, and for victims on rows 1-3 of the written columns (one
write) at most 1.9 mV (sf/125 C). During the pulse a stored '0' half-selected
cell is held to its bitline within 1 uV (`min`/`max` columns of the CSV), so
there is no droop or gain *during* the pulse. This is predicated on the rewrite
assumption; **a masked partial-row write with the unwritten bitlines parked at
a level other than their stored data would overwrite those cells, which is not
a disturb but a write**, so a macro with byte/bit writes needs read-modify-write
or per-column write gating. Not designed here.

The negative-undershoot of stored '0' is worth a follow-up: the node sits
below ground until it relaxes, and this study does not follow it past the
first checkpoint or ask what it does to the read device.

## Negative control

The 10x-wide write devices are the "deliberately leaky" control. The
analyzer must be able to tell them from the real device: at every 125 C
corner their worst erosion is 2.6-38x larger than the normal device's (ratio
test `NEG_MIN_RATIO` = 1.5) and above the noise floor, i.e. **valid at all
five hot corners**. It crosses the 10 % limit (**flagged**) at **tt, ff and
sf at 125 C**, including the worst-case retention corner. At ss/125 C and
fs/125 C it reaches 8.1 % and 8.5 %: valid but under the limit. That is a
recorded property of the 10x device, not an adjusted threshold. At 27 C the
deck's erosions are so small that the negative control is not distinguishable
at ss and fs (reported `negative_control_valid: false`); nothing is concluded
at 27 C beyond "not measurable here". The synthetic unit tests exercise the three cases (flagged,
distinguishable but under the limit, indistinguishable).

## Assumptions (explicit)

* Ideal drivers: rail-to-rail WBL and WL with 100 ps edges and zero source
  resistance; ideal 0.9 V read bitline source; read wordlines at `VDD`.
* Storage-node capacitance: the extracted array's wiring C (ground +
  coupling per `sn_<r>_<c>`) plus the BSIM junction/gate capacitances of the
  devices in this deck, with the extracted drawn diffusion (62 % more
  junction area than `design/gain_cell_2t.spice`). **Not** the ratified
  1.106463 fF, and not reconciled with the single-cell 0.605 fF extraction
  (#89 is open). Fractions of `delta_V` scale with 1/C_SN; the
  `equiv_hold_time_s` column does not.
* No mismatch (global corners only), no Monte Carlo, no supply other than
  1.8 V, no temperatures other than 27 and 125 C.
* No read activity (reads and the read bitline capacitance are out of scope;
  #88, #94), no sense amplifier, no refresh logic: a bare write stream.
* Plain 1.8 V wordline. A boosted or negative-off wordline decision, if
  later ratified, requires re-running.
* Stored '1' = 1.0 V, stored '0' = 0.0 V at t = 0 (not the per-corner
  written levels), victim pattern `1,0,1`, 34 ns cadence, 147 writes as the
  adversarial per-window bound, 10 % screening limit.
* The disturb accrues linearly with the hold leakage in the derating
  arithmetic (first order).

  Cross-reference (issue #114): [`sim/column-periphery`](../column-periphery/README.md) compares an ideal write-bitline source and ideal precharge with a designed slice; the ideal-vs-real delta is tabulated there. The text above is the original study assumption and is left as written.

## Append-only handling

Everything in `results/` is protected automatically by
[`../check_append_only.py`](../check_append_only.py) (any path under a
directory named `results`); `append_only_inventory.txt` lists only files
*outside* `results` directories, so no inventory change was needed. A rerun
creates new `<RUN_ID>`-stamped files; the analyzer refuses to overwrite.

## Reproduce

```bash
python3 -I sim/write-disturb/gen_write_disturb.py            # regenerate deck + request
python3 -I sim/write-disturb/test_write_disturb.py           # checks (also in CI)
# corner grid: ONE batch request, never a local loop
uvx --from "klayout-tools==0.6.0" klt sim --backend batch --format json \
    sim/write-disturb/request.json > sim/write-disturb/results/klt_report_<RUN_ID>.json
python3 -I sim/write-disturb/analyze_write_disturb.py sim/write-disturb/results/klt_report_<RUN_ID>.json
```

Provenance of the committed run (tool/PDK) is in
`results/disturb_summary_<RUN_ID>.json` and the klt report's `environment`
block (netlist and model-library sha256, engine version, fleet job).

## Not shown

No column/bank-level victim count (3 victims per WBL here); no WBL idle level
other than 0 and `VDD`; no mismatch; no sense or read activity during the
write stream; no boosted wordline; no write-driver source impedance; no
cold (-40 C) corner; no assessment of the negative-undershoot of stored '0'
beyond the first checkpoint. Nothing here ratifies the proposed range or
changes the 5.03 us refresh bound; any change that follows from the sf/125 C
flag needs a decision record in `spec/`.
