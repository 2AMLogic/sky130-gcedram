# Repeated closed-loop refresh: does data survive many cycles? (issue #147)

Epic #24 items 3 and 6. The single-operation studies ([`sim/refresh-replay`](../refresh-replay/README.md),
[`sim/refresh-energy`](../refresh-energy/README.md), [`sim/aged-read`](../aged-read/README.md)) each reset the
storage node with an initial condition or an ideal level. This study **writes the data once**, then lets one
continuous transient age it and refresh it **closed-loop** for 10 cycles: the actual latch decision (right or
wrong) drives the write-back and the resulting level is carried into the next cycle. No `.ic` after t = 0, no
ideal expected-data source after the initial write. Everything is under the **PROPOSED, UNRATIFIED** operating
range (27/125 C, tt/ss/ff/sf/fs, 1.8 V; [`spec/operating-range-decision-PROPOSED.md`](../../spec/operating-range-decision-PROPOSED.md)).
No spec, contract, overlap rule, scheduler value or prior result was edited; the ratified 5.03 us bound is only read.

## Result in one paragraph

**At the ratified interval (5.03 us) the closed loop does not survive at sf / 125 C: 6 of 32 main rows are read
wrong at their very first read, and a wrong read is then written back.** The other 9 corners stay correct and
restored for all 10 cycles at 5.03 us, and all 10 corners stay correct at the shorter 2.5 us dwell. At the 8 us
dwell the same corner fails more rows (9 of 32) and the other 9 corners are still clean. In every healthy corner
the stored-'1' post-refresh level is flat to within +/-0.04 V first-to-last cycle (no accumulating loss over the
tested horizon). The failures are not the single-operation read failing: the same stored-'1' level (pre-read
~0.97 V) reads correctly in rows refreshed *earlier* in the cycle (rows 0/1) and incorrectly in rows refreshed
*after* neighbouring stored-'1' rows were restored to ~1.63 V (rows 2/3). That is consistent with the restored
neighbours' read devices conducting onto the shared read bitline of the next read (unselected `rwl` at VDD,
`rbl` precharged to 0.9 V, so Vgs = 1.63 - 0.9 > Vt) -- **consistent with, not isolated** (no run changed only
that factor). It is invisible to every single-operation study because they never read a row next to a freshly
restored row. This is a result about the *ideal-driver* circuit with the baseline analog waveform; it is not a
statement about the macro, and nothing here is a refresh-bound sign-off or a yield claim. Failed corners and
trajectories are kept in the CSVs. A finite pass is a pass over 10 cycles only, **not** indefinite stability.

## What was built

| File | Role |
|---|---|
| [`gen_closed_loop.py`](gen_closed_loop.py) | generates the 4 decks + requests below (constants / ASSUMPTIONs at its top), plus the issue-#373 paired diagnostic `d5030nbr` |
| `closed_loop_<variant>.spice`, `request_<variant>.json` | flat deck; 5 corners x {27,125} C as one `klt sim` request per variant (`d5030nbr`: 1 corner, sf/125 C, paired arms) |
| [`analyze_closed_loop.py`](analyze_closed_loop.py) | reduces a klt report to a per-cycle CSV + summary (writes new files only, refuses to overwrite) |
| [`test_closed_loop.py`](test_closed_loop.py) | stdlib checks, wired into CI and `npm test` (not stale, scope, no state reset, schedule, analyzer on synthetic failing/healthy/control reports) |
| `results/` | append-only evidence |

Variants (one deck each; the dwell is the select-edge-to-select-edge interval of a row, the first age is exactly the dwell):

| Variant | Dwell | Cycles | Role |
|---|---:|---:|---|
| `d2500` | 2.5 us | 10 | shorter than the ratified bound |
| `d5030` | 5.03 us | 10 | the ratified bound |
| `d8000` | 8 us | 10 | longer (1.6x) |
| `d60000` | 60 us | 2 | **excessive-dwell control** (12x) |

**Horizon.** 10 cycles per row is a declared, finite choice: long enough that a per-cycle drift separates from a
one-cycle offset and a wrong write-back feeds 9 later reads, short enough that each corner stays one fleet job. 10 cycles at 5.03 us is ~50 us of simulated retention history; it says nothing about 10^6 cycles.

**Circuit** (the #94 column plus the refresh-op write-back path): 4 rows on one bitline pair; `design/gain_cell_2t.spice`
with the layout's drawn `AD/AS/PD/PS`; corrected `design/sense_latch.spice`; extracted 4-row `C_RBL` and array-minimum
`C_SN` (as #94); `C_WBL` = 10 fF (**ASSUMPTION, not extracted**, as refresh-op); ideal matched dummy reference,
`VREF = VRBL - 100 mV`. **Ideal periphery retained:** wordline/read-select/enable drivers, the 100 ohm precharge and
WBL-connect switches, and the ideal bitline driver used for the initial write only (it is disconnected during every
write-back; the latch complement node alone drives WBL). No physical column (#114/#117) or row driver, no mismatch.

**Each row**: written once through `M_WR` (cell starts at the opposite of its data, 20 ns WWL, 40 ns slots), then
refreshed every dwell by the sim/refresh-op sequence: precharge -> select -> latch enable -> latch COMPLEMENT drives
WBL -> WWL pulse -> release. Rows are refreshed in order 0..3, 40 ns apart.

**Waveforms**, all reused from committed evidence, none re-derived here:

| key | Source | Role |
|---|---|---|
| `ana` | sim/refresh-op analog baseline (SENSE 10 ns, WWL 20 ns, RWL and latch held through write-back) | **MAIN**; 8 patterns |
| `rtl` | the **unchanged** committed phase-sequencer strobes (`sim/refresh-replay/results/20261115T120746Z/rtl_trace.json`) + the explicit latch-hold adapter | control; single-op replay restores 0/10 corners |
| `late` | `rtl` with RWL released after WWL falls (refresh-replay `rwl_late_hold`) | **EXPERIMENTAL, UNAPPROVED**; reverses the non-overlap rule; not a contract change |
| `nowb` | `ana` with the write-back WWL pulses deleted | **negative control** (missing write-back) |

Patterns (row0..row3 data): main `1111 0000 1000 0111 1010 0101 1101 0010`; controls `1111 0000 1010 0101` (nowb:
`1111 1010`). A starting set of mixed-neighbour patterns, **not** a proven worst-case enumeration.

## Per-cycle record

`results/closed_loop_points_<variant>_<RUN>.csv`: one row per corner x instance x row x cycle with `written_v`,
`pre_read_v`, signed `dec_v` and `decision` (`d = V(rbl) - V(ref)` just before the write-back WWL rises; a stored '1'
must be <= -0.9 V, a '0' >= +0.9 V), `correct` (against the **original** data, so a wrong value that is later
rewritten and read "consistently" stays a failure from its first wrong read), `post_refresh_v`, `restore_fraction`
(stored '1': `post_refresh / sn_ref`, where `sn_ref` is the per-corner in-deck reference write of the committed
refresh-replay run -- **the same denominator as the 0.90/0.95/0.98 gates there**; stored '0': signed `post <= 50 mV`,
undershoot below 0 V is not a failure, as there), `restore_fraction_vs_written` (vs this deck's own post-write level, 0.5 ns
after the WWL fall; reported for transparency, **not comparable** to refresh-replay fractions), `restored_090/095/098`,
`interval_loss_v`. The summary JSON has `first_failure_cycle_by_row` (first wrong read) and
`first_unrestored_cycle_by_row` (first post-refresh level failing the 0.95 gate) per kind and corner.

## Results (run `20261118T220449Z`; 10/10 corners pass for all 4 requests)

Main case, per dwell (32 rows = 8 patterns x 4 rows, 10 cycles each):

| Dwell | corners with every read correct and restored (0.95) | failing corner | rows read wrong at the first read |
|---|---|---|---|
| 2.5 us | 10/10 | none | 0/32 |
| 5.03 us | 9/10 | **sf / 125 C** | 6/32 (`1111` r2,r3; `0111` r3; `1010` r2; `0101` r3; `1101` r3) |
| 8 us | 9/10 | **sf / 125 C** | 9/32 |

Healthy corners (all 10 at 2.5 us, 9 at 5.03/8 us): min stored-'1' restore fraction 1.02-1.06 of `sn_ref`; worst
stored-'1' pre-read level in those corners 0.91 V (ff/125, 8 us); max first-to-last-cycle stored-'1' post-refresh
change magnitude 0.04 V (all waveforms). **No monotone loss trend was seen over
10 cycles; this is a finite-horizon statement.** At the failing corner a wrong row's post-refresh level is about
-0.06 V (a '0' is written back) -- the corruption is permanent in the trajectory.

Controls (these prove the analyzer is not counting simulator completion as success):

| Control | Result |
|---|---|
| missing write-back (`nowb`) | detected in 10/10 corners at every dwell: all 6 stored-'1' rows per corner fail the 0.95 gate (min fraction 0.78-0.83 at 27 C, 0.005-0.59 at 125 C); at 125 C the level keeps decaying and reads go wrong where the horizon allows (first wrong read at cycle 2-9, e.g. sf/125: cycle 7 at 2.5 us, 3-4 at 5.03 us, 2 at 8 us; not every 125 C corner decays that far in 10 cycles at 2.5 us); at 27 C reads stay correct over 10 cycles but the level stays unrestored |
| excessive dwell (60 us, 2 cycles) | corruption detected in **5/5 corners at 125 C** (first read wrong, row decayed to ~0 V and '0' written back); **not** detected at 27 C (no decay in the model in 60 us), so the control is meaningful at hot corners only |
| unchanged RTL + latch-hold adapter (`rtl`) | restoration gate fails for the stored-'1' rows in every corner/dwell (fraction 0.876-0.922 of `sn_ref`, as the single-op 0.87); **reads nevertheless stay correct for all 10 cycles in every corner and dwell** -- the level is never restored to the reference but does not decay further either; that finite-horizon read pass is reported beside the failed restoration gate, not as a restoration pass |
| experimental `late` (unapproved) | restores like `ana` and fails at the same corner (sf/125) with the same first-read mechanism (2/16 rows at 5.03 us, 5/16 at 8 us) |

**Mechanism observation.** The `rtl` control restores neighbours only to ~1.36 V at sf/125 and never fails a read;
the `ana`/`late` waveforms restore to ~1.63 V and do. That contrast, plus the row-order dependence above, is the
evidence for the neighbour-conduction explanation. It was not isolated (it would need a run that changes only the
neighbour level or the unselected `rwl` level, or a physical row driver, #114/#117). **Issue #373 provides that
run: see the isolation section below.** Also untested: other row orders, more neighbours than 3, a reference that
tracks the column, and mismatch.

## Neighbour-level isolation (issue #373, run `20261119T024944Z`)

The hypothesis above was isolated with **one paired comparison**: variant `d5030nbr` -- the `d5030` schedule,
pattern `1111`, **cycle 1 only**, corner **sf / 125 C**, two instances in one deck:

* `ana_1111` -- instrumented **baseline** arm;
* `anb_1111` -- identical circuit plus a **DIAGNOSTIC ideal clamp** that holds the two already-restored
  neighbours (rows 0, 1) at the RTL-control restore level (**1.36 V**, inside the committed sf/125
  `control_rtl_unchanged` stored-'1' post-refresh range 1.35869..1.39556 V of run `20261118T220449Z`) through
  the victim row-2 read window (open 5127.1 ns, settled 5128.1 ns, released 5165.1 ns -- after row 1's op end
  and its post-refresh probe, before row 3's precharge drops).

Everything else is shared and byte-identical between the arms: the `ana` RWL / latch / write-back waveform
(the read select is **never touched** -- RWL is active LOW, so driving a neighbour's RWL low would select it
and add a discharge path), the write/refresh history through row 1's write-back, the victim's age, precharge,
loading and reference. The clamp is an intervention no physical periphery provides and is labelled DIAGNOSTIC
ONLY in the deck. Both arms carry the same instrumentation: 0 V ammeters in every RWL rail (positive
`i(vmeas)` = that row's RWL rail sourcing current into its read device, i.e. onto the shared RBL -- the
injection direction; negative = the rail sinking that row's read discharge), neighbour storage-node probes at
the victim-select instant (`npre`), and RBL / REF / d across the victim's pre-latch sensing window
(select edge -> latch enable, 5131.1..5141.1 ns).

**The instrumented baseline reproduces the recorded cycle-1 decisions** (the deck adds only 0 V sources):
row 1 dec -1.61837 V vs recorded -1.61829 V, row 2 dec +1.72263 V vs recorded +1.72257 V (both within 0.1 mV),
same pass/fail.

| cycle-1, row-2 read of `ana_1111`, sf/125 C, 5.03 us | baseline | neighbours clamped to 1.36 V |
|---|---|---|
| neighbour SN before the victim select (`npre` r0 / r1) | 1.6742 / 1.6570 V | 1.3600 / 1.3600 V |
| neighbour read-branch current `iavg` (r0 / r1) | +6.08 / +5.14 uA | +4.52 / +4.52 uA |
| victim read-branch current `iavg` (r2) | -11.5 uA | -9.3 uA |
| row-3 (unrestored neighbour) `iavg` | +0.24 nA | +1.8 nA |
| RBL at latch enable | 0.835 V | 0.638 V |
| REF at latch enable | 0.818 V | 0.881 V |
| d = RBL - REF at latch enable | **+17 mV** | **-243 mV** |
| row-2 decision (existing pre-write-back sample) | **'0' -- WRONG** (written back) | **'1' -- correct** |
| row-3 decision (secondary observation) | '0' -- WRONG | '1' -- correct |

The measured refutation did **not** occur: lowering only the neighbours' storage-node level changed the
injection current, the differential at latch enable, and the final decision, and the victim then read
correctly. Mechanism reading, at the level these measurements support: at the victim's select the restored
neighbours sit ~0.77 V above the precharged RBL and inject ~11 uA combined while the victim's own discharge
sinks ~11.5 uA -- the two nearly cancel, so RBL erodes only to 17 mV above the reference by the enable instant
and the latch resolves in the '0' direction. With the neighbours at 1.36 V their early-window vgs drops to
~0.46 V (sub-threshold), the victim's discharge dominates, RBL crosses below the reference, and the latch
resolves '1'. At 1.36 V the neighbours do **not** switch off: once RBL falls their vgs recovers and they still
conduct ~4.5 uA each late in the window -- the level change reduces the early-window erosion, it does not
remove the conduction path, which is why the RBL - REF swing (-243 mV) is smaller than a healthy single-op read.
Row 3's read also passes in the clamped arm (secondary observation, same mechanism; not the recorded
comparison). The baseline neighbours' SN relaxes upward between the recorded post-refresh sample and the
victim-select instant (+40.3 / +41.2 mV; `baseline_neighbour_relaxation_v` in the summary), so the recorded
`post_refresh_v` values are not the levels at the victim's select -- both are recorded, at their own instants.

**Claimed: the neighbour storage-node LEVEL is the controlling factor of the cycle-1 first-read failure of
`ana_1111` row 2 at sf/125 C at the ratified 5.03 us dwell, in this deck (ideal drivers, this latch, this
model set).** Not claimed: anything about other patterns/rows/corners, the physical column or row drivers
(#114/#117), a reference that tracks the column, mismatch, or a revised refresh bound -- the sf/125 result at
the ratified interval still stands as recorded and still needs its own spec/ decision record. The paired
comparison is `clean_comparison=true` (baseline reproduced, clamp achieved its level, controls passed) with
`verdict=supported` in `closed_loop_summary_d5030nbr_20261119T024944Z.json`.

Run **locally** (single corner, so within the host rule for local runs): `klt sim --backend local`, ngspice-47,
model library sha256 `48de7c67...133c84` (the pin of `docs/pdk-pin.md`; klt's first-match warning about
`~/.ciel` vs `~/.volare` applies as in the fleet run -- the tree read is at open_pdks `f6eeac7`), ~6 s wall.
Reproduce: `python3 -I sim/closed-loop-refresh/gen_closed_loop.py`, then
`klt sim --backend local --format json sim/closed-loop-refresh/request_d5030nbr.json > sim/closed-loop-refresh/results/klt_report_d5030nbr_<NEW_RUN>.json`,
then `python3 -I sim/closed-loop-refresh/analyze_closed_loop.py d5030nbr sim/closed-loop-refresh/results/klt_report_d5030nbr_<NEW_RUN>.json`.
The committed reduction is byte-reproducible from the committed raw report in a fresh output location.

## Not claimed

No full-macro, yield or mismatch claim; no refresh-bound sign-off (the sf/125 result at the ratified interval is a
finding under ideal drivers and global corners, not a derived bound, and a revised interval needs its own decision
record); no stability beyond 10 cycles; no statement about the physical column/row drivers; the proposed operating
range and the experimental `late` waveform remain unratified/unapproved.

## How it was run (host rules)

Four `klt sim` requests on the **batch fleet** (`KLT_SIM_BACKEND=batch`, `--wait-for-capacity 600 --hosts 10`, one
job per corner). Three concurrent client launches used distinct `-o` directories because `klt` locks its default
output directory per request directory (a first attempt of those three failed with `outdir_locked` and was
re-launched; nothing from it is used). A single local single-corner debug probe (sf/125 C, 2 cycles, short dwell,
`--backend local`, ~10 s) checked the deck; it is not recorded as evidence. Fleet job ids are in each
`closed_loop_summary_*` (`batch_fleet_jobs`); engine ngspice-47; model library sha256 `48de7c67...133c84` (the pin of
`docs/pdk-pin.md`; the host resolves `~/.ciel` first-match, a klt warning).

## Evidence (append-only)

`results/` for run `20261118T220449Z`, per variant `d2500 d5030 d8000 d60000`:

* `klt_report_<variant>_<RUN>.json.gz` raw klt report (gzipped; `analyze_closed_loop.py` reads it directly)
* `closed_loop_points_<variant>_<RUN>.csv` per-cycle record
* `closed_loop_summary_<variant>_<RUN>.json` per-corner/kind reductions, assumptions, claims flags, provenance

Reproduce: `python3 -I sim/closed-loop-refresh/gen_closed_loop.py`, then per variant
`KLT_SIM_BACKEND=batch klt sim --wait-for-capacity 600 --hosts 10 --format json sim/closed-loop-refresh/request_<variant>.json > sim/closed-loop-refresh/results/klt_report_<variant>_<NEW_RUN>.json`,
then `python3 -I sim/closed-loop-refresh/analyze_closed_loop.py <variant> <that report>`. Re-runs use a new run id.
