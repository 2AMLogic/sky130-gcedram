# Column periphery: ideal sources vs a designed slice (issue #114)

Epic #24 items 2, 3 and 6 need a real column path. Until now every read/write
study used ideal sources for it (ideal 100 ohm precharge switch in
[`sim/sense-stage`](../sense-stage/README.md) and
[`sim/loaded-column`](../loaded-column/README.md), ideal write-bitline sources
in [`sim/write-disturb`](../write-disturb/README.md) and the loaded column,
borrowed phase durations in [`sim/refresh-overhead`](../refresh-overhead/README.md)).
This directory replaces the precharge and the write source with a designed
slice and records what that changes. It is a **schematic-level** result:
no layout, no extracted parasitics, global corners only (no mismatch, no Monte
Carlo), **PROPOSED/UNRATIFIED** restricted range
([`spec/operating-range-decision-PROPOSED.md`](../../spec/operating-range-decision-PROPOSED.md)):
27 C and 125 C, tt/ss/ff/sf/fs, `VDD` = 1.8 V. No spec file was edited.

## What was built

| File | Role |
|---|---|
| [`../../design/column_periphery.sch`](../../design/column_periphery.sch) / [`.spice`](../../design/column_periphery.spice) | the slice: xschem schematic and the netlist derived from it by `design/regen_netlist.sh` |
| [`gen_column_periphery.py`](gen_column_periphery.py) | generates the two files below (all constants and ASSUMPTIONs at its top) |
| [`column_periphery.spice`](column_periphery.spice) | flat circuit body for `klt sim` (8 instances; device cards copied from the three `design/` netlists) |
| [`request.json`](request.json) | the `klt sim` request: 5 process corners x {27, 125} C = 10 corners, one `tran` each, `backend: batch` |
| [`analyze_column_periphery.py`](analyze_column_periphery.py) | reduces the committed klt report to per-point CSV + summary JSON (writes new files only) |
| [`test_column_periphery.py`](test_column_periphery.py), [`../../design/test_column_periphery.py`](../../design/test_column_periphery.py) | stdlib checks, wired into CI (generated files not stale, scope, summary reproduces from the report, netlist-vs-schematic-vs-deck consistency) |
| `results/` | append-only evidence |

### The slice (`design/column_periphery.sch`)

All devices are `sky130_fd_pr__nfet_01v8` / `pfet_01v8`, L = 0.15 um.

| Block | Devices (W um) | Function |
|---|---|---|
| RBL precharge | `MPPRE` pfet 4.0, d=`rbl`, s=body=`vpre` (0.9 V rail), gate `pre_b` (active low) | precharges the read bitline to `VRBL` = 0.9 V |
| WBL write driver | `MPU1`/`MPU2` pfet 1.0 and `MND2`/`MND1` nfet 0.5: tri-state inverter, `wbl` = NOT `dinb` while `wen`; `MNI` nfet 0.42 pulls `wbl` to 0 V when `wen` is low | drives the write bitline rail to rail; idles at 0 V as in the existing decks |
| Column select / isolation | `MNS` nfet 1.0 + `MPS` pfet 2.0 transmission gate `rbl` -> `sbl` (latch input); matched dummy gate `MNSR`/`MPSR` `ref` -> `sref` | isolates the array bitline from the latch before the enable so the latch regenerates on its own capacitance |

Not in the slice (testbench elements, unchanged from sense-stage): the
sense latch ([`design/sense_latch.sch`](../../design/sense_latch.sch)), the
reference-side precharge and dummy load (still an ideal switch and cap), the
control edges (ideal 100 ps), and the 0.9 V `vpre` rail (ASSUMED ideal;
generating `VDD`/2 is out of scope).

## Test bench

One `tran` per corner, eight independent instances (4-row column, 2T cells
from `design/gain_cell_2t.spice`, `C_SN` extracted 0.605354 fF as in
sense-stage, `C_RBL` = `C_WBL` = 10 fF **ASSUMED, not extracted**; the
extracted value replaces them once #88 lands). Timeline per instance:

1. `rbl` starts at 0 V (fully discharged, worst case after a stored-'1' read);
   precharge asserts at 1 ns. Settling is measured here.
2. 10-34 ns: write of row 0 (bitline 2 ns before the wordline, 20 ns wordline
   pulse, existing convention). Row 0 starts at the opposite value
   (genuine overwrite); rows 1-3 hold the data level (STUDY-ASSUMPTION as in
   sense-stage). Stored level sampled at 45 ns.
3. Precharge released 2 ns before the select edge at 60 ns (contract); latch
   enable at +10 ns (contract sense instant); isolation gates open 0.5 ns
   before the enable (ASSUMPTION). Reference = 0.8 V (`VRBL` - 0.1 V,
   sense-stage ASSUMPTION).

Instances: `ideal_w1/w0` (existing ideal sources, latch on `rbl`),
`real_w1/w0` (the slice), `sw_0100/0200/0400/0800` (precharge width sweep,
W x 100 um; `sw_0400` is the chosen design).

### Contract compliance gates (analysis; per corner, both data values)

(a) precharge settle (first time `rbl` is within 10 mV of 0.9 V after the
assert edge) <= 2 ns, the precharge phase of the `anchored` `t_row_refresh_op`
scenario in [`sim/refresh-overhead`](../refresh-overhead/README.md);
(b) `rbl` within 10 mV of 0.9 V at release; (c) latch decides the correct
polarity with |d| >= 0.9 V; (d) within 5 ns of the enable. The 2 ns, 10 mV and
5 ns values are ASSUMPTIONS inherited from the existing phase budget and
sense-stage criterion, not spec values.

## Sizing rationale

* **Requirement**: settle within the 2 ns precharge phase at every corner of
  the restricted set, with margin. The ideal 100 ohm switch settles in ~11 ps,
  so the budget says nothing about the ideal; the real device decides it.
* **Why the well sits on `vpre`**: first pass, `MPPRE` with its well at `vdd`
  (the convention for the latch pfets) sources a 0.9 V rail at 0.9 V reverse
  body bias; a local tt/27 C probe with W = 1.0 um took ~8 ns to settle
  (about 2.4 ns with the well on `vpre`). The well is therefore on `vpre`,
  which costs a separate n-well and tap in layout (a later layout issue).
  That probe was a single-corner debug run, not recorded as evidence.
* **Width sweep (recorded, ns, per corner; run `20261009T205913Z`)**: the
  slowest corner is the cold one (sf/27 C and ss/27 C), not 125 C - the 125 C
  worst case for retention is not the worst case for precharge speed.
  In parentheses: the **superseded** first sweep, run `20261009T204412Z`, in
  which the swept `MPPRE` scaled W, `ad`/`as` and `pd`/`ps` but kept
  `nrd`/`nrs` at the W = 4 um value (0.0725) for every width, so the W = 1, 2
  and 8 um points were not a consistent resizing of the schematic device.
  The corrected sweep uses the single-finger convention of the `design/`
  netlists, `nrd` = `nrs` = 0.29/W (0.29, 0.145, 0.0725, 0.03625), and
  `design/test_column_periphery.py` now checks every geometry parameter.
  The superseded run's files are kept unchanged (append-only); do not cite
  its W = 1, 2, 8 um columns.

| corner | W=1 um | W=2 um | W=4 um | W=8 um |
|---|---|---|---|---|
| ff/27C | 1.49 (1.43) | 0.90 (0.88) | 0.55 (0.55) | 0.36 (0.37) |
| ff/125C | 0.81 (0.76) | 0.47 (0.45) | 0.29 (0.29) | 0.20 (0.21) |
| fs/27C | 1.68 (1.60) | 1.02 (0.99) | 0.62 (0.62) | 0.39 (0.40) |
| fs/125C | 1.09 (1.02) | 0.61 (0.59) | 0.37 (0.37) | 0.23 (0.25) |
| sf/27C | 3.78 (3.73) | 2.39 (2.37) | 1.52 (1.52) | 0.99 (1.00) |
| sf/125C | 1.02 (0.98) | 0.62 (0.60) | 0.39 (0.39) | 0.27 (0.27) |
| ss/27C | 4.07 (3.98) | 2.59 (2.56) | 1.62 (1.62) | 0.99 (1.01) |
| ss/125C | 1.59 (1.52) | 0.89 (0.87) | 0.53 (0.53) | 0.34 (0.35) |
| tt/27C | 2.37 (2.30) | 1.48 (1.46) | 0.92 (0.92) | 0.57 (0.59) |
| tt/125C | 1.14 (1.07) | 0.65 (0.63) | 0.39 (0.39) | 0.26 (0.27) |

  The correction moves W = 1 um by +0.05 to +0.09 ns, W = 2 um by +0.02 to
  +0.03 ns (both slower: more source/drain squares at narrow width), W = 8 um
  by -0.01 to -0.02 ns, and leaves W = 4 um unchanged (its geometry was
  already correct). **The sizing conclusion does not change**: W = 4.0 um is
  the smallest swept width that meets 2 ns everywhere (worst 1.62 ns at
  ss/27 C, 19 % margin); W = 2 um still fails at sf/27 C (2.39 ns) and
  ss/27 C (2.59 ns), W = 1 um additionally at tt/27 C (2.37 ns). Wider costs
  gate/overlap charge on `rbl` for speed the budget does not need.
* **Write driver**: not speed limited. The written '1' level is set by the
  access device and `C_SN`, not the driver (table below: |delta| < 0.1 mV), so
  the driver is sized for a modest on-resistance only (series pfet pair 1.0 um,
  nfet pair 0.5 um, idle pull-down 0.42 um = the access-device width). It is
  **not optimized**; no claim that it is minimal.
* **Isolation gate** (nfet 1.0 / pfet 2.0): first-pass choice, same widths as
  the latch devices it drives. Not swept; see the din finding below.

All sizes are provisional first-pass values, frozen in the schematic and
checked against the deck by `design/test_column_periphery.py`.

## Evidence (append-only)

Two runs, same request scope (10 corners), both submitted once as a `klt sim`
request on the batch backend (client `uvx --from klayout-tools==0.6.0 klt`,
the version the fleet runner accepts; the host `klt` 0.7.0 was not used for
a submit and no host tool was changed). Nothing was looped locally. Both
committed reports have the bucket name redacted. Model library sha256
`48de7c67...133c84`, ngspice-46, open_pdks `c6d73a35...`
([`docs/pdk-pin.md`](../../docs/pdk-pin.md)) for both.

| run | fleet job | status | cites |
|---|---|---|---|
| `20261009T205913Z` (current) | **`klt-sim-e8a94973d1fc`** (m7i.4xlarge, spot, `done`, 65 s) | 10/10 corners pass, netlist sha256 `93296003...a4f420` = the committed deck | everything in this README |
| `20261009T204412Z` (**superseded** for the width sweep) | `klt-sim-7a36d3a319c2` (c7i.8xlarge, spot, `done`, 44 s) | 10/10 corners pass, netlist sha256 `f005f9b4...c9eb85` | parenthesised sweep values only |

The superseded run differs from the current deck only in `nrd`/`nrs` of
`XMPPRE_sw_0100/0200/0800`. The ideal/real instances (`ideal_w*`, `real_w*`,
`sw_0400`) are the same circuit in both runs; their values differ only at
solver-noise level (settle <= 0.2 ps, `din`/`sn` <= 25 uV; the flat deck is
one transient, so time-step control is shared across instances) and every
number in the ideal-vs-real table below is identical at the quoted precision
in both runs. Two **local single-corner debug probes** (tt/27 C and ss/125 C,
`--backend local`) were run while sizing; they are not recorded as evidence.

* `results/klt_report_20261009T205913Z.json` raw klt report (current)
* `results/periphery_points_20261009T205913Z.csv` 80 rows (10 corners x 8 instances)
* `results/periphery_summary_20261009T205913Z.json` per-corner metrics, deltas, compliance flags
* `results/*_20261009T204412Z.*` the superseded run, kept unchanged

Reproduce (new run id, never edit these): `python3 -I sim/column-periphery/gen_column_periphery.py`,
`uvx --from klayout-tools==0.6.0 klt sim --format json sim/column-periphery/request.json > sim/column-periphery/results/klt_report_<NEW_RUN_ID>.json`
(`KLT_SIM_BACKEND=batch`), then `analyze_column_periphery.py` on it.

## Results: ideal vs real (tabulated delta)

Settle = time from the precharge assert edge (50 %) to `rbl` within 10 mV of
0.9 V. `sn` = stored level of row 0, 13 ns after the write wordline fell.
`din` = latch input difference `V(sbl) - V(sref)` at the enable instant
(negative = '1' read). delta = real - ideal.

| corner | settle ideal (ps) | settle real (ns) | sn '1' ideal (V) | sn '1' real (V) | delta sn '1' (mV) | sn '0' ideal (V) | sn '0' real (V) | delta sn '0' (mV) | din '1' ideal / real (V) | din '0' ideal / real (V) | compliant |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ff/27C | 11 | 0.55 | 1.0883 | 1.0883 | -0.02 | -0.1284 | -0.1485 | -20.1 | -0.306 / -0.337 | +0.101 / +0.185 | yes |
| ff/125C | 11 | 0.29 | 1.1900 | 1.1900 | -0.02 | -0.1199 | -0.1376 | -17.7 | -0.372 / -0.421 | +0.119 / +0.231 | yes |
| fs/27C | 11 | 0.62 | 0.9322 | 0.9322 | -0.01 | -0.1219 | -0.1442 | -22.3 | -0.120 / -0.019 | +0.102 / +0.184 | yes |
| fs/125C | 11 | 0.37 | 1.0275 | 1.0275 | -0.02 | -0.1294 | -0.1495 | -20.1 | -0.380 / -0.433 | +0.114 / +0.220 | yes |
| sf/27C | 11 | 1.52 | 1.1236 | 1.1236 | -0.03 | -0.1199 | -0.1371 | -17.2 | -0.305 / -0.322 | +0.101 / +0.163 | yes |
| sf/125C | 11 | 0.39 | 1.2210 | 1.2210 | -0.03 | -0.1079 | -0.1264 | -18.6 | -0.309 / -0.343 | +0.103 / +0.194 | yes |
| ss/27C | 11 | 1.62 | 0.9604 | 0.9604 | -0.02 | -0.1282 | -0.1504 | -22.2 | -0.326 / -0.289 | +0.102 / +0.165 | yes |
| ss/125C | 11 | 0.53 | 1.0485 | 1.0485 | -0.02 | -0.1334 | -0.1525 | -19.1 | -0.362 / -0.405 | +0.103 / +0.193 | yes |
| tt/27C | 11 | 0.92 | 1.0279 | 1.0279 | -0.02 | -0.1290 | -0.1511 | -22.1 | -0.329 / -0.356 | +0.102 / +0.174 | yes |
| tt/125C | 11 | 0.39 | 1.1237 | 1.1237 | -0.02 | -0.1270 | -0.1458 | -18.8 | -0.361 / -0.408 | +0.106 / +0.205 | yes |

What the delta says:

* **Precharge**: the ideal switch hid a 0.3-1.6 ns term (real, versus ~11 ps
  ideal). It fits the 2 ns phase at every corner, including 125 C
  (0.29-0.53 ns), but is the dominant part of the budget at the cold corners.
  `vrel` (the level at release) is within 0.4 mV of 0.9 V everywhere.
* **Write-'1' level at the storage node**: unchanged. delta < 0.05 mV at all
  ten corners; the written '1' (0.93-1.22 V) is set by the access device, so
  the driver does **not** erode it. This holds for the tested 10 fF `C_WBL` and
  20 ns pulse only.
* **Write-'0' level**: 17-22 mV *deeper* undershoot with the real driver
  than with the ideal source (sub-ground, -0.108 to -0.153 V). Not
  investigated further here; it does not hurt retention of a '0' but it
  matters for the sub-ground floor in `SENSE_INPUT_CONTRACT.md` (-0.135 V).
* **Sense-input contract compliance**: all four gates hold at all ten
  corners for both data values. **But** the slice changes the margin
  asymmetrically: `din` for '0' *improves* by 0.06-0.12 V, while for '1' it
  *erodes* at two corners: fs/27 C (-0.120 V ideal -> -0.019 V real, i.e.
  a 19 mV input to the latch) and ss/27 C (-0.326 -> -0.289 V). The other
  corners improve '1' by 0.02-0.05 V. At fs/27 C the latch still resolves
  (systematic only, no mismatch), but 19 mV is well below any plausible
  offset budget (see [`sim/sense-mismatch`](../sense-mismatch/README.md)).
  The mechanism (charge injection / coupling of the isolation gate pair
  versus the matched dummy on the reference side) is a hypothesis; it was not
  separated here. The compliance flag is a systematic-only statement and is
  **not** an offset/yield claim.
* Latch decision time after the enable is 0.05-0.15 ns real versus
  0.08-0.17 ns ideal.

## Limits (read before citing)

* Schematic-level: `C_RBL`/`C_WBL` are the 10 fF assumption (extracted value
  pending #88); no layout of the slice exists.
* Global corners only; no Monte Carlo, so no offset, no device-mismatch effect
  on the precharge or isolation gates.
* `vpre` is an ideal rail; the reference side keeps its ideal switch and
  dummy cap, so reference-side settling and its charge injection are not
  captured (the matched dummy gate captures only the gate coupling).
* The isolation timing (0.5 ns before enable) and the 10 mV settle tolerance
  are assumptions; the gate sizes other than `MPPRE` were not swept.
* One column of four rows; all rows at one stored level (STUDY-ASSUMPTION).

## Issue #117: isolation-gate sizing, reference-side matching, driver sizing and offset

Follow-up to the finding above (stored-'1' `din` eroded at fs/27 C and ss/27 C,
write-'0' undershoot deeper than the ideal source). New run ids, nothing above
was edited. **The sizes quoted in "Sizing rationale" for the isolation gate
(nfet 1.0 / pfet 2.0) and the write driver are superseded** by the schematic
now in `design/column_periphery.sch` (final point `f00`, below).

Files (all new):

* `gen_isolation_study.py` -> `isolation_study.spice` + `request_isolation.json` (global-corner sweep,
  52 variants x 2 data values + ideal controls, 10 corners) and `isolation_mc.spice` +
  `request_isolation_mc.json` (Monte Carlo on `ideal` / `i00` (the #114 slice) / `f00`).
  `gen_column_periphery.py` now holds the frozen #114 slice cards (`SLICE_114_CARDS`) so the #114 deck
  stays reproducible from the design #114 simulated; the schematic has moved on.
* `analyze_isolation_study.py` reduces a report to `isolation[_mc]_points_<RUN>.csv` and
  `isolation[_mc]_summary_<RUN>.json` (refuses to overwrite).
* Results: `results/isolation_klt_report_20261015T080004Z.json` (sweep, fleet job `klt-sim-b172041b161b`,
  10/10 corners), `results/isolation_mc_klt_report_20261015T084700Z.json.gz` (MC, fleet job
  `klt-sim-568d0e135a5e`, c7i.8xlarge spot, 873 s, 160/160 units pass), plus their points/summary files.
  Bucket name redacted in both. Both submitted once as `klt sim` on the batch backend; nothing looped
  locally (a single-corner local debug probe was run while building the deck; not recorded).
  The MC submit emitted the client warning that the serial job bound (160 units x 3000 s) exceeds the
  fleet 3600 s ceiling; the job completed in 873 s regardless, so no sharding was needed.

### What the sweep found (mechanism)

Hypothesis from #114 was charge injection of the rbl isolation pair versus the dummy gate. The sweep
(`i*` isolation width/lead/dummy-scale, `p*` precharge release, `m*` matched reference precharge,
`c*` combinations, `d*` write driver) refutes it as the dominant cause:

* Isolation timing (lead 0.1 .. 2 ns), isolation widths (0.42 .. 2.0 um, nfet-only, pfet-only, TG) and
  dummy scale (0.5 .. 1.5x) move fs/27 C `din` for '1' only between -0.034 and +0.009 V (baseline
  -0.019 V); none restores the ideal -0.120 V. Wider gates are worse (`i07`: +0.006 V), narrower
  slightly better.
* The large lever is the **reference side**: #114's bench gave the reference an ideal switch, so the
  real rbl carried the precharge pfet's release disturbance with no counterpart on `ref`. Giving `ref`
  a matched precharge pfet (a dummy reference column has one; `XMPPREF`, now in the schematic with a
  `vref` pin) cancels most of it: `m00` fs/27 C `din` -0.076 V, ss/27 C -0.334 V, at the baseline
  isolation. Dummy switches on rbl alone (`p04`, `p05`) only reach -0.037 / -0.029 V.
* Remaining lever: the nfet-only 0.42 um isolation gate (passes the 0.9 V precharge level, no pfet to
  inject opposite charge) and a bigger precharge pfet (5 um, so settling stays <= 2 ns).
* Write driver: stack `MND1/MND2` 4.0 um, `MNI` 2.0 um (was 0.5 / 0.42) pulls the write-'0' undershoot in
  to within 5 mV of the ideal source; 8.0 / 4.0 (`d06`) to within 3 mV (see below).

### Final point `f00` versus ideal source, all ten corners (sweep run `20261015T080004Z`)

`din` for stored '1' (mV; more negative = more signal; "shortfall" = f00 - ideal, positive is worse
than ideal) and the write-'0' minimum on the storage node (floor -135 mV):

| corner | ideal din '1' | #114 slice din '1' | f00 din '1' | f00 shortfall | ideal snmin '0' | #114 snmin '0' | f00 snmin '0' | f00 margin to floor |
|---|---|---|---|---|---|---|---|---|
| ff/27C | -305.9 | -337.1 | -382.1 | -76.1 | -128.4 | -148.6 | -132.3 | +2.7 |
| ff/125C | -371.7 | -420.9 | -471.0 | -99.3 | -122.2 | -141.6 | -126.3 | +8.7 |
| **fs/27C** | -119.9 | -18.9 | **-101.5** | **+18.4** | -121.9 | -144.2 | -127.1 | +7.9 |
| fs/125C | -379.7 | -432.9 | -488.2 | -108.5 | -130.5 | -151.3 | -136.2 | **-1.2** |
| sf/27C | -304.9 | -321.8 | -362.5 | -57.6 | -119.8 | -137.2 | -122.9 | +12.1 |
| sf/125C | -309.4 | -343.2 | -390.7 | -81.2 | -111.3 | -132.4 | -115.0 | +20.0 |
| **ss/27C** | -326.1 | -289.4 | **-369.5** | **-43.4** | -128.2 | -150.4 | -133.5 | +1.5 |
| ss/125C | -362.0 | -404.7 | -451.8 | -89.8 | -134.7 | -154.5 | -140.2 | **-5.2** |
| tt/27C | -328.8 | -355.6 | -399.3 | -70.5 | -129.0 | -151.2 | -133.9 | +1.1 |
| tt/125C | -360.9 | -408.3 | -453.6 | -92.6 | -128.5 | -148.2 | -133.3 | +1.7 |

All #114 compliance gates (settle <= 2 ns, release within 10 mV, correct decision, within 5 ns) hold at
all ten corners, both data values (worst settle 1.80 ns, sf/27 C, stored 0). Worst-case 125 C corners retained.

### Acceptance reading

1. **din '1' at ss/27 C: met** (-369.5 mV against ideal -326.1 mV, 43 mV better). **At fs/27 C: not met,
   closed from a 101 mV shortfall to 18 mV** (-101.5 mV against ideal -119.9 mV); the 18 mV is the
   written trade-off, with its sized evidence:
   * Every `f00` stored-'1' input is at least 101 mV, five times the best case of #114's 19 mV, and
     9 of 10 corners exceed 360 mV.
   * The residual 18 mV is a property of the ideal-source reference: `f04` (array-side `rbl`
     capacitance 6.26 fF so total rbl load is 10 fF with the 3.74 fF periphery, the "C_RBL is the
     total" reading of the 10 fF assumption, pending #88) gives fs/27 C -131 mV, a shortfall of
     -11 mV, i.e. met. The load definition is #88's to settle; this study does not choose it.
   * Matching the reference side costs a second 5 um precharge pfet per column and a `vref` rail.
2. **Offset (Monte Carlo)** below.
3. **Write-'0' undershoot against -135 mV: met at 8 of 10 corners, not at fs/125 C (-136.2 mV, 1.2 mV
   short) and ss/125 C (-140.2 mV, 5.2 mV short).** The ideal source itself is only 0.3 mV inside the
   floor at ss/125 C (-134.7 mV) and 4.5 mV inside at fs/125 C, so there is essentially no budget for
   any real driver at the two worst-case corners. Driver sweep (worst over ten corners): #114 driver
   -154.5 mV (9 corners below floor), 2.0/1.0 um -144.7 mV, **4.0/2.0 um (chosen) -140.2 mV**,
   8.0/4.0 um -137.6 mV (only ss/125 C below floor, by 2.6 mV). Larger stacks cost area on every
   column for a few mV and still do not reach the floor at ss/125 C, so 4.0/2.0 um is kept. The
   residual shortfall is reported, not hidden: the contract floor in `SENSE_INPUT_CONTRACT.md` is
   unchanged, and accepting 1.2 / 5.2 mV at two 125 C corners, or tightening the write-'0' level by
   other means, is a spec decision (needs a decision record under `spec/`), not made here.

### Monte Carlo: offset contributed by the isolation pair (run `20261015T084700Z`)

`klt sim` with `monte_carlo` n = 40, seed 2026101517, `vary: mismatch`, 4 replicas per sample
(160 independent instances per cell), PDK `_mm` sections at the four `sim/sense-mismatch` corners
(tt/27, fs/27, ss/125, sf/125). Instances: `ideal` (latch directly on rbl, the control), `i00` (the #114
slice), `f00` (final).

The stored-'1' `din` spread is dominated by the **cell** read-device mismatch (ideal source: sigma(din)
= 51 .. 153 mV, which is not an isolation effect and is the same in every variant). The isolation pair's
own contribution is isolated by `ddin = din - dpre`, the change from just before the isolation gates
close to the latch enable, and is cleanest for stored '0' (read device off):

| corner | sigma(ddin '0') ideal | #114 slice | **f00** | mean ddin '0' f00 | sigma(ddin '1') f00 (ideal) | latch sigma, sense-mismatch | RSS of latch sigma and f00 '0' |
|---|---|---|---|---|---|---|---|
| tt_mm/27C | 0.02 mV | 2.39 mV | **2.42 mV** | +3.2 mV | 2.41 mV (0.63) | 17.7 mV | 17.9 mV |
| fs_mm/27C | 0.01 mV | 2.83 mV | **1.50 mV** | +1.6 mV | 8.87 mV (3.40) | 16.3 mV | 16.4 mV |
| ss_mm/125C | 0.02 mV | 2.65 mV | **2.17 mV** | +2.7 mV | 2.80 mV (0.52) | 17.6 mV | 17.7 mV |
| sf_mm/125C | 0.02 mV | 2.99 mV | **2.33 mV** | +3.4 mV | 2.06 mV (0.09) | 19.2 mV | 19.3 mV |

* The final isolation pair adds a **random offset of 1.5 .. 2.4 mV sigma** (at most 2.8 mV in '1' outside
  fs/27 C) and a **systematic shift of +1.6 .. +3.4 mV** for '0' (`ddin` mean) and -6.9 .. -15.2 mV for
  '1' (the helpful sign: more signal). Added in quadrature to the 16.3 .. 19.2 mV latch sigma of
  `sim/sense-mismatch` the total moves by <= 0.2 mV: **the isolation pair is not an offset budget
  issue.** Against #114's slice the random closing spread is unchanged or smaller, and the stored-'1'
  spread at fs/27 C falls from 26.3 mV to 8.9 mV (the part of that above ideal's 3.4 mV is the
  residual cell-signal movement during the 0.5 ns lead at the lowest-signal corner).
* **Open finding, not diagnosed: fs_mm/27 C stored-'0' tail.** In `f00`, 4 of 160 stored-'0' instances at
  fs_mm/27 C have a pre-isolation difference `dpre` far from the ~97 mV median (-255, -227, -101, -70 mV)
  and 5 of 160 decide wrongly (sigma(din '0') 44 mV, against 3.0 mV for `i00` and 0.4 mV for ideal).
  The other three MC corners show no such tail for '0' (0 wrong decisions of 160 each), and the
  deterministic global fs/27 C corner is clean. The effect is already present in `dpre`, i.e. before the
  isolation gates close; a likely candidate is the rbl / ref precharge settling of the matched 5 um
  pfets under mismatch at slow-pfet fast-nfet, which the global corners (settle 1.80 ns worst, budget 2 ns)
  do not stress, but this was not verified. Treat `f00` as **not yet MC-robust at fs_mm/27 C** until that
  is understood.
* Stored-'1' wrong decisions at fs_mm/27 C (ideal 38/160, `i00` 79/160, `f00` 48/160) are a cell
  read-signal-versus-mismatch fact of this corner at the 10 fF load (the ideal source already fails on 24%),
  not a slice effect; `f00` is better than `i00` and close to ideal. The other three corners have no
  wrong decisions for either data value.
* No yield or BER claim is made from n = 40 x 4 draws; sigma intervals are in the summary JSON (normal-theory
  95 % CI).

### Limits of this addition

* The matched reference-side precharge is an architectural change (extra pfet and `vref` rail per
  column), judged by the testbench's one-reference-column model; layout cost is not estimated.
* `C_RBL` is still the 10 fF assumption (extracted load pending #88); `f04` shows the fs/27 C result
  depends on how that load is read.
* Write-'0' floor residual at two 125 C corners (above); the spec is untouched.
* MC covers four corners and one slice instance structure; the fs_mm/27 C stored-'0' tail is open.

> Historical (open_pdks \`c6d73a3\`): not re-run under \`f6eeac7\`; no spec citation (issue #170, see \`docs/pdk-requalification-inventory.md\`).
