# Loaded column and sense stage with the extracted 4-row `C_RBL` (issue #88)

This directory adds new append-only evidence. It re-runs the Phase 2 /
cold-corner loaded-column read (issues #45, #47) with the read-bitline load
extracted from the committed 4x4 array (issue #80) instead of the assumed
10 fF. The companion sense-stage re-run is in
[`../../sense-stage/README.md`](../../sense-stage/README.md), section "Issue #88".
The contract change is a new dated section in
[`../cold-corner/SENSE_INPUT_CONTRACT.md`](../cold-corner/SENSE_INPUT_CONTRACT.md).

**What this is not:**
* It does not edit any past result or `spec/` file.
* It does not ratify a row count. `N_rows` = 4 stays a STUDY-ASSUMPTION.
* It does not reconcile the retention chain or the `C_SN` / device-card
  mismatch. That is issue #89.
* It does not use real periphery. Issue #114 / PR #118 (column periphery
  slice) is still open, so every run here uses the **ideal-periphery
  baseline**: ideal write/read drivers and an ideal precharge switch, the same
  as Phase 2.

## The `C_RBL` value and its label

| Item | Value |
|---|---|
| Source file | [`layout/gain_cell_2t_array.parasitics.summary.json`](../../../layout/gain_cell_2t_array.parasitics.summary.json) |
| Key path | `comparison.c_rbl.extracted_4row_worst_total_ff` (worst `rbl_<c>`, net `rbl_2`; `rbl_0..2` are equal) |
| Value | **0.859179 fF** (0.581168 fF ground + 0.278011 fF coupling) |
| Extracted netlist | `layout/gain_cell_2t_array.extract.parasitics.spice`, sha256 `dd2cca26de34d6b7cd39a0d794db64993d6440c5ca7f248cf4d657b6f6b88d33` |
| Label | **EXTRACTED-4-ROW**. The column is the 4-row STUDY-ASSUMPTION, and `N_rows` is **not ratified**. The per-row extrapolation in #80 stays an ASSUMPTION and is not used here. |

The generator reads the value from that key and does not restate it
(`gen_column_klt.py`, `extracted_c_rbl_ff()`). The tests check it against
the JSON and against `max(per_column.rbl.*.total_ff)`.

**How it is applied (bounding case).** In these decks the lumped `C_RBL` is
the **whole** read-bitline load. The extracted value **replaces** 10 fF and
is **not added** to it, and no other extracted bitline parasitic is added.
The four `M_RD` drain junctions are in the device cards, as in Phase 2. The
extracted number is wiring only: the summary's `convention` field says the
diffusion junctions are carried by the device cards. Removing the 10 fF also
removes whatever share of it was meant as sense-input load ("column wire plus
sense-input load"). This repository does not trace how large that share was.
The 0.859 fF runs are therefore the **lightest-load bound**, not a
prediction. The 2 fF runs are an **ASSUMPTION** mid-point and show only the
trend. The loaded-column deck contains no sense amplifier. In the sense-stage
deck the latch transistors are simulated explicitly, so their own input load
is present there even at 0.859 fF.

## Variants

Each variant is the Phase 2 baseline with only the named knob changed.

| Variant | `C_RBL` | Bitcell card | Purpose |
|---|---|---|---|
| `ref_crbl_10f` | 10 fF, ASSUMPTION (contract) | design | harness reproduction of the committed Phase 2 run |
| `crbl_ext4row` | 0.859179 fF, EXTRACTED-4-ROW | design (`ad=as=0.1218`, `pd=ps=1.42`) | the re-run |
| `crbl_2f` | 2 fF, ASSUMPTION (mid-point) | design | trend |
| `crbl_ext4row_layoutcard` | 0.859179 fF, EXTRACTED-4-ROW | **layout** (`ad=as=0.1974`, `pd=ps=1.78` on `M_WR` and `M_RD`, as drawn in the extracted netlist) | labelled device-card variant (issue #80 mismatch) |
| `nc_write_disabled_ext4row` | 0.859179 fF | design | negative control: the write wordline never rises |

The pass criteria are the cold-corner study's, imported from
`cold-corner/variants.py` and `analyze_variants.evaluate_point()` and not
copied. They are study ASSUMPTIONS, not spec values:

* separation >= 0.1 V;
* every stored-'1' case reaches the 0.1 V droop by `t_sense` = 10 ns;
* |read disturb| <= 0.1 V;
* 64/64 cases.

## How it was run

Host rule and contract rule 4: multi-corner runs go through `klt sim` on the
batch fleet.

The Phase 2 runner cannot be submitted as a `klt sim` request as it stands.
It runs each case in a `.control` loop (`alterparam`/`reset`/`wrdata`) and
post-processes the waveforms in Python, and `klt sim` has no `.param` axis.
That tool gap is already filed as
[2AMLogic/klayout-tools#2894](https://github.com/2AMLogic/klayout-tools/issues/2894)
(item 2). [`gen_column_klt.py`](gen_column_klt.py) therefore re-expresses it:

* **Flattened deck.** All 64 cases (4 selected rows x 16 patterns) become
  independent column instances in one flat deck, one deck per read age.
* **Measurements.** Every quantity Phase 2's `measure()` reads from the
  waveform becomes a `.meas` at the same instant.
* **Latency.** The latency reference (`rbl` at about `t_read` - 0.2 ns) is
  held on an ideal sample-and-hold. A forced crossing after the window marks
  "not reached", so no `.meas` can fail.
* **Not measured.** Per-row read-wordline currents (`i_into_rbl_*`) are not
  measured here.

**Harness reproduction** (`ref_crbl_10f` against committed Phase 2 run
`20261005T102906Z`, all 1920 cases, the same ngspice-46 as Phase 2):

| Check | Result |
|---|---|
| Worst point-separation difference | 5.0e-5 V (declared tolerance 1 mV) |
| PASS/FAIL verdicts | identical at all 30 points |
| Cases where latency is reached vs not reached | 0 mismatches |
| Worst per-case `v_rbl_sense_v` difference | 7.6e-5 V |
| Worst selected read-disturb difference | 4.3e-4 V |
| Worst latency difference | 7 ps (klt prints absolute time to 6 significant digits) |

A local single-corner debug probe (fs/-40 C fresh, host ngspice-42, not
evidence and not committed) agreed with one unchanged Phase 2 batch run under
the same ngspice-42 to within about 6 uV. Its ~9 mV stored-'0' offset against
the committed rows came from ngspice 42 vs 46, not from the harness.

**Fleet jobs.** All jobs were submitted with
`uvx --from "klayout-tools==0.6.0" klt sim --backend batch --format json`
(the client version the fleet runner accepts; no host tool was changed).
Campaign `20261011T015419Z`: 10 requests, 128 corners, all `pass`, 0 errored,
ngspice 46.

| Request | Job | Corners | Elapsed |
|---|---|---:|---:|
| `ref_crbl_10f` fresh / aged | `klt-sim-0fb094387a05` / `klt-sim-a96f58f71946` | 15 / 15 | 154 / 266 s |
| `crbl_ext4row` fresh / aged | `klt-sim-89480241dfb5` / `klt-sim-f50db6af7a99` | 15 / 15 | 144 / 238 s |
| `crbl_2f` fresh / aged | `klt-sim-c5435ceb9ccd` / `klt-sim-ac92bc0e3a3e` | 15 / 15 | 120 / 205 s |
| `crbl_ext4row_layoutcard` fresh / aged | `klt-sim-3266c9889876` / `klt-sim-c7e15279a5f3` | 15 / 15 | 117 / 265 s |
| `nc_write_disabled_ext4row` fresh / aged | `klt-sim-df3a8662ed7a` / `klt-sim-ee23ae299041` | 4 / 4 | 33 / 58 s |

Every job was a first submission. None was refused and nothing fell back to
a local grid. The committed reports are gzip-compressed, with the job bucket
name redacted. The analyzer checks that each report's `netlist_sha256` equals
the sha256 of the committed deck in [`decks/`](decks/).

## Results (append-only: [`results/20261011T015419Z/`](results/20261011T015419Z/))

Separation is the column-wide worst case. "Lat" is the slowest stored-'1'
latency. "NR" means the 0.1 V droop was not reached in the window.

### Old vs new at the contract's named corners

| Point | Phase 2 (10 fF, committed) | 10 fF, this harness | **0.859 fF EXTRACTED-4-ROW** | 2 fF ASSUMPTION | 0.859 fF + layout card |
|---|---|---|---|---|---|
| fs/-40 C fresh | 0.018 V, NR (32/32), **FAIL** | 0.018 V, NR, FAIL | **0.082 V, 11.78 ns, FAIL** | 0.057 V, 17.94 ns, FAIL | 0.116 V, 7.95 ns, **PASS** |
| fs/-40 C aged | 0.017 V, NR (32/32), **FAIL** | 0.017 V, NR, FAIL | **0.075 V, 12.97 ns, FAIL** | 0.052 V, 19.76 ns, FAIL | 0.108 V, 8.68 ns, **PASS** |
| ss/-40 C fresh | 0.121 V, 7.92 ns, PASS (marginal) | 0.121 V, 7.92 ns, PASS | **0.388 V, 1.56 ns, PASS** | 0.303 V, 2.35 ns, PASS | 0.459 V, 1.25 ns, PASS |
| ss/-40 C aged | 0.113 V, 8.55 ns, PASS (marginal) | 0.113 V, 8.55 ns, PASS | **0.370 V, 1.69 ns, PASS** | 0.288 V, 2.54 ns, PASS | 0.441 V, 1.33 ns, PASS |

### Whole grid (15 points x 2 ages)

| Variant | Points PASS | Min separation over grid (point) | Max read disturb |
|---|---:|---|---:|
| Phase 2 committed (10 fF) | 28/30 | **0.017 V** (fs/-40 aged) | 0.067 V |
| `ref_crbl_10f` (this harness) | 28/30 | 0.017 V (fs/-40 aged) | 0.067 V |
| `crbl_ext4row` | 28/30 | **0.075 V** (fs/-40 aged) | 0.069 V |
| `crbl_2f` | 28/30 | 0.052 V (fs/-40 aged) | 0.068 V |
| `crbl_ext4row_layoutcard` | **30/30** | 0.108 V (fs/-40 aged) | 0.058 V |
| `nc_write_disabled_ext4row` | 0/8 (required) | all negative (-1.02 to -1.23 V) | n/a |

At the other 26 points of the `crbl_ext4row` grid (everything except
fs/-40 C and ss/-40 C):

* **Separation moves -0.006 to +0.376 V.** The points that were already wide
  (>= 0.5 V) move by -0.006 to +0.044 V. The slow-NMOS 27 C points gain the
  most: ss/27 C goes from 0.59-0.61 V to 0.68 V, and fs/27 C goes from
  0.27-0.29 V to 0.65-0.66 V.
* **Latency.** The slowest stored-'1' latency falls from up to 2.96 ns to at
  most 0.66 ns.

The negative control fails at every point with negative separation, as
required.

### What moved, and what moved a verdict

* **Read separation, worst case over the grid.**
  * The baseline is 0.017 V (fs/-40 C aged), against the 0.1 V placeholder
    criterion.
  * With the extracted 4-row load it is **0.075 V**: 4.5x larger, still below
    0.1 V, still at fs/-40 C aged.
  * The fs/-40 C stored '1' now reaches the 0.1 V droop (12-13 ns), but after
    `t_sense` = 10 ns.
  * **Verdict unchanged on the design card: fs/-40 C still FAILS** on
    separation and latency, and the grid is 28/30 as before.
* **ss/-40 C sensitivity.**
  * The contract says ss/-40 C is sensitive to `C_RBL`, and it is.
  * Its margin goes from marginal (0.113 V aged, 8.55 ns latency) to
    comfortable (0.370 V, 1.69 ns) at 0.859 fF, and to 0.288 V at 2 fF.
  * It passed before and still passes, so **no verdict change**. The point
    is no longer marginal under the bounding load.
* **fs/-40 C "insensitive to `C_RBL`".** This holds for the pass/fail
  verdict on the design card (5 to 40 fF in cold-corner README 2b, and now
  0.859 fF). It does **not** hold for the value: separation rises from
  0.017 V to 0.075 V. A subthreshold read discharges a much lighter bitline
  further. The mechanism stays as attributed in cold-corner section 2: the
  read device sits about 0.15 V below threshold at sense.
* **Device-card variant, the one verdict flip.**
  * With the layout's own diffusion card on top of the extracted load,
    fs/-40 C **passes** at both ages: 0.116 / 0.108 V and 7.95 / 8.68 ns.
  * The grid becomes **30/30**.
  * The margin is 8 mV over a placeholder 0.1 V criterion, so this is a
    narrow pass, not a robust one.
  * The written stored '1' rises by about 8 mV (fs/-40 C: 0.864 -> 0.872 V).
    A plausible cause, not separately simulated: the larger `M_WR` source
    junction adds capacitance on `sn` and reduces the wordline-fall
    feedthrough.
  * Which card is right is issue #89's question; the result is recorded here
    and not resolved.
* **Stored levels** do not depend on `C_RBL` (identical write path), so the
  contract's stored-level rows are unchanged.
* **Read disturb** stays <= 0.069 V everywhere (0.1 V placeholder).

None of this changes the cold-corner conclusion that the design-card,
ideal-periphery column is **not functional at fs/-40 C** under the
placeholder criteria. The bounding-case load narrows the gap but does not
close it. It is closed only together with the layout card, and only narrowly.

## Files

| File | Role |
|---|---|
| [`gen_column_klt.py`](gen_column_klt.py) | generates [`decks/`](decks/) (10 circuit bodies + 10 `klt sim` requests); `--check` exits 1 if stale |
| [`analyze_column_klt.py`](analyze_column_klt.py) | `--ingest` (redact + gzip + refuse overwrite); reduce a run directory into `cases.csv.gz` + `summary.json` |
| [`test_column_klt.py`](test_column_klt.py) | stdlib tests: decks not stale, `C_RBL` is the cited JSON value and the whole load, Phase 2 connectivity and instants, card/negative-control diffs, analyzer, committed summary reproduces from the committed reports |
| `results/20261011T015419Z/` | 10 klt reports (`.json.gz`), `cases.csv.gz` (8192 rows), `summary.json` (reproduction, negative control, old-vs-new per point) |

## Reproduce

```bash
python3 -I sim/loaded-column/extracted-crbl/gen_column_klt.py --check
# each request is one batch job (KLT_SIM_BACKEND=batch); never a local grid
uvx --from "klayout-tools==0.6.0" klt sim --backend batch --format json \
    sim/loaded-column/extracted-crbl/decks/request_<variant>_<age>.json > /tmp/<variant>_<age>.json
python3 -I sim/loaded-column/extracted-crbl/analyze_column_klt.py --campaign <NEW_RUN_ID> --ingest /tmp/*.json
python3 -I sim/loaded-column/extracted-crbl/analyze_column_klt.py sim/loaded-column/extracted-crbl/results/<NEW_RUN_ID>
python3 -I sim/loaded-column/extracted-crbl/test_column_klt.py
```

## Limitations

* A single 4-row column; `N_rows` = 4 is not ratified.
* Lumped `C_RBL` with no distributed RC. The extracted `rbl` resistance
  (385 ohm) is not modelled.
* Ideal periphery (PR #118 not merged).
* Global corners only: no mismatch, offset or yield.
* The sense-input load share is untraced, so 0.859 fF is a bound.
* Placeholder criteria: 0.1 V separation, 10 ns sense instant.
* `C_SN` is the single-cell 0.605354 fF, while the array value is 17-22%
  lower (issue #89, not reconciled).
* No klayout-tools friction beyond the already-filed #2894 (no `.param`
  axis) and the known runner/client version skew, which was avoided by
  pinning the 0.6.0 client.
