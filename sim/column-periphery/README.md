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
