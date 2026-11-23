# `klt pex` schematic-vs-extracted delta: the drawn bitcell and the 4x4 array (issue #383)

The first `klt pex` evidence in this repo, and the first T1 item 7
(`7.analog`, post-layout verification) citation attempt. Two runs — one per
layout, on the ratified retention row — each extract a fresh PDK-bound
parasitic netlist from the GDS, re-run the stored-'1 write/read/hold
sequence of [`sim/bitcell-transient/`](../bitcell-transient/README.md) on
both legs, and report the per-corner schematic-vs-extracted delta of one
spec row, `t_ret_tran_s`, through klt 0.9.1's
`--measure-command` interface (the crossing is not expressible as a single
`.meas` card).

Closes the "no `klt pex` request or report exists" gap of
[#383](https://github.com/2AMLogic/sky130-gcedram/issues/383) at the
baseline-cell level; the full-macro GDS remains the pending item-7 scope
(see [`docs/ROADMAP.md`](../../docs/ROADMAP.md)).

## Outcome (the row of #383's table that applied)

**Comparable run; both cells cited; the graded item-7 row stays `unmet`,
now `check_failed` instead of `no_evidence`.**

- Both cells ran to a comparable record: stamps matched on every leg, the
  interface/model/bulk checks below are green, and both envelopes carry all
  15 requested corner rows — 5 with a paired, passing measurement and 10
  with an explicit unresolved outcome and its cause (see "Why 10 of 15
  rows are unresolved").
- Both PEX envelopes are cited under `evidence["7.analog"]` in
  [`block-manifest.json`](../../block-manifest.json), each pinned to its
  layout's content hash. The regenerated
  [`block-manifest.signoff.json`](../../block-manifest.signoff.json)
  (pinned klt 0.9.2, the signoff workflow pin) grades item 7 analog **`unmet` / `check_failed`** with
  both citations graded `unmet` / `check_failed`: item 7 requires the
  cited envelope's own `status` to be `pass`, and each envelope's status is
  `error` because the 10 unresolved rows render as `error` delta rows —
  never a fabricated pass. `t1_met_count` stays 9. The unmet reason is
  recorded in [#13](https://github.com/2AMLogic/sky130-gcedram/issues/13)
  as well, per #383.
- Nothing in this study relaxes or re-qualifies anything: #182
  (bitcell-transient re-qualification) and #208 (retention budget vs the
  device-inclusive C_SN) stay with their owners; the schematic leg exists
  only for this comparison, and the array's benchmark use is comparison
  only.

## The two runs

| | bitcell | 4x4 array |
|---|---|---|
| Layout | `layout/gain_cell_2t.gds` (`sha256:ae17e5fa…`) | `layout/gain_cell_2t_array.gds` (`sha256:2bcd6e1b…`) |
| Envelope (unedited) | `results/klt_pex_bitcell_20261121T051134Z.json` | `results/klt_pex_array_20261121T051134Z.json` |
| Reference (schematic leg) | `reference/gain_cell_2t_schematic.spice` | `reference/gain_cell_2t_array_4x4_schematic.spice` |
| Fresh PDK-bound extraction | 2 devices, 6 nets, 33 pins' worth of RC | 32 devices, 33 nets |
| Measured cell | the bitcell (`sn`) | `sn_0_0` (row 0 / column 0) |
| klt / PDK / engine | 0.9.1 / open_pdks `f6eeac7…` (`--pdk-root`) / ngspice-47 on every leg | same |

Both invocations are `run_pex.sh` (reproduce below): `klt pex <gds> --deck
sky130 --pdk sky130A --pdk-root "$PDK_ROOT" --backend batch
--measure-command 'python3 -I sim/pex_bitcell_array/measure_pex_retention.py
--cell <cell>' --reference-netlist <reference> --measure-timeout-s 7200
--outdir work/<cell> --envelope-out results/klt_pex_<cell>_<RUN_ID>.json`.
The bitcell ran first, per #383's guidance. Each leg is one `klt sim
--backend batch --wait-for-capacity 600` request per temperature (5 process
corners each); the 12 native reports with job IDs, worker PDK stamps and
simulator versions are committed under `results/native/`. Every one of the
12 reports shows `pdk_stamp_comparison.status = "match"` on
`open_pdks f6eeac7dad…` (the repo pin), `engine_build_comparison = match`
on ngspice-47, and all 60 corner units passed.

## Both legs

**Schematic leg** — study-local, regenerated mechanically from named
sources by `gen_reference_netlists.py` (the test fails if stale):

- *bitcell*: the two SKY130 X cards of
  [`design/gain_cell_2t.spice`](../../design/gain_cell_2t.spice) verbatim,
  wrapped in an active `.SUBCKT gain_cell_2t_layout_0 GND bl rbl rwl sn
  wl` whose name and ORDERED pin list are the committed extraction's own
  header. The source's commented wrapper and top-level terminator are
  omitted. It instantiates `sky130_fd_pr__nfet_01v8` **2x**.
- *array*: all 32 D/G/S/B tuples of
  [`layout/gain_cell_2t_array.lvs_reference.spice`](../../layout/gain_cell_2t_array.lvs_reference.spice)
  (there is no array schematic in `design/`), each instantiated as the
  source bitcell's matching WR/RD SKY130 X card **with its schematic
  geometry** (`L=0.15 W=0.42` bare micrometres per the SKY130 subcircuit
  convention, `ad/as/pd/ps/nrd/nrs/sa/sb/sd` unchanged; numerically
  cross-checked against the LVS cards' `0.15U/0.42U`), wrapped in the
  committed extraction's ORDERED 33-pin header `GND bl_0..3 rbl_0..3
  rwl_0..3 sn_0_0..sn_3_3 wl_0..3`. It instantiates
  `sky130_fd_pr__nfet_01v8` **32x**.

**Extracted leg** — the fresh `klt extract --parasitics --pdk sky130A`
netlist `klt pex` itself drove and handed to the same measure command. Its
devices are PDK-bound X cards (`X$1 … sky130_fd_pr__nfet_01v8 L=0.15
W=0.42 AS=0.1974 …`) with the **extracted junction geometry** (AS/AD/PS/PD
0.1974/1.78, vs the schematic's 0.1218/1.42 — the representation delta the
comparison is meant to expose), plus the wiring R/C and the vertical-
overlap coupling capacitors.

Checks applied to BOTH legs before either is cited (`pex_bench.dut_problems`,
enforced in-harness and by the committed tests):

- flat top name and ORDERED pin list equal the committed extraction's
  header (33 pins for the array, 6 for the bitcell);
- `sky130_fd_pr__nfet_01v8` instance count exactly 2 / 32 — the envelopes'
  `model_mismatch` is `null` on both cells (the multisets agree);
- every MOS body net reaches the GND pin through the resistor network
  (bitcell: `RGND_t0 GND__t0 GND 73.19` ties; array: the shared-tap
  network) — the extractor's `.GLOBAL vsubs` reference alone would not
  establish it. The bench binds the GND formal to SPICE node 0 and anchors
  `vsubs` with an explicit 0 V source on both legs;
- `pin_count_mismatch` / `flat_dut_mismatch` / `pin_order_mismatch` are
  `null` (in `--measure-command` mode these are the harness's
  responsibility, discharged by the ordered-header assertion above).

Both envelopes quote `body_bias` as
`{"status": "biased", "unbiased_device_count": 0, "unbiased_nets": [],
"unbiased_pmos_body_nets": []}` — every device body had a drawn DC path.

`extraction.model` (verbatim, both cells; `critical_nets` is `[]` and
`distributed_rc` is `false` — no `--critical-net`/`--distributed-rc` flags
were requested):

> **capacitance**: net-to-ground for every net's own (non-coupled)
> area/perimeter, plus net-to-net for the vertical-overlap coupling
> `coupling` describes below -- a coupled net pair gets a direct capacitor
> between their two hub nodes, not just capacitors to the deck's
> ground/substrate net
>
> **coupling**: vertical overlap (crossover) unconditionally -- where one
> net's conductor on an adjacent metal level sits directly over another
> *distinct* net's conductor, that overlap area is charged between the two
> nets instead of to ground (issue #760) -- plus lateral (same-layer,
> sidewall) coupling, but only for a net pair naming one of the caller's
> declared `--critical-net` nets (issue #976) … Any same-layer pair with
> neither side named `--critical-net`, and fringe shielding in general,
> are still not modelled
>
> **resistance**: single lumped series resistance per net, distributed as
> a star across that net's device terminals (issue #592) -- not a
> per-segment, distributed RC ladder …
>
> **frequency**: quasi-static -- one frequency-independent R and C per
> net; no skin effect, no distributed transmission-line behavior

(`parasitic_integrity`: 6/6 bitcell nets and 33/33 array nets checked, 0
findings.)

## What is measured, and against what

`t_ret_tran_s`, stored-'1 hold decay, in seconds: the elapsed time from
hold start (55 ns; `wl`=`bl`=0 V, `rwl`=1.8 V, `rbl`=0.9 V — the same
stimulus, initialization, window and crossing rule on both legs) to the
first subsequent falling crossing of **that leg's own** hold-start
`V(SN)` minus the 0.9 V sense margin, cubic-interpolated over the 4
nearest crossed rungs of the fixed `.meas` level ladder — the crossing
reduction of [`sim/bitcell-transient/`](../bitcell-transient/README.md)
reused verbatim (`reduce_bitcell_transient.ladder_crossing`; the ladder
`WHEN … TD` values are relative to the hold start, validated by that
study's `.meas`-vs-Python equivalence probe). The template's lumped
extracted `c_sn` is omitted on both legs, so the fresh extract supplies
the storage node's wiring capacitance exactly once; the schematic leg is
the pre-layout circuit (device capacitance only).

The array bench drives the selected row 0 / column 0 with the single-cell
sequence; unselected `wl_*`=0 and `bl_*`=0 (write path off), unselected
`rwl_*`=1.8 V (rows deselected — the deck's active-low read polarity),
every `rbl_*` at 0.9 V. All 16 storage nodes start empty (`.ic` 0 V; the
neighbours are documented stored-'0'), and every `sn_*` stays observable
and electrically free during hold (no source touches one).

Limit: the ratified §5 single-cell benchmark
[`spec/retention-refresh-budget.md`](../../spec/retention-refresh-budget.md),
`min = 1.005989e-5 s` (worst case sf/125 °C), over tt/ss/ff/sf/fs ×
−40/27/125 °C — 15 points per leg. **sf/125 °C is the worst-case corner of
that spec and is called out below.** The array uses this benchmark for
comparison only; §7's 5.03 µs refresh interval measures a different
quantity. Hold windows are sized once per temperature from the
current-pin leakage rows (12× the analytic seed, `HOLD_WINDOW_SLACK`),
identically for both legs and both cells (5.804e-3 s at −40 °C, 5.802e-3
s at 27 °C, 4.667e-3 s at 125 °C) — the window sizes the observation only,
never the value.

## Results

All five resolved corner pairs **pass** the ratified benchmark on both
legs and on both cells; the extracted leg's retention is consistently
*longer* (the fresh wiring capacitance slows the decay):

| corner | bitcell schematic | bitcell extracted | Δ% | array schematic | array extracted | Δ% |
|---|---:|---:|---:|---:|---:|---:|
| ff/27C | 1.644940e-03 | 2.027855e-03 | +23.278 | 1.644916e-03 | 1.913751e-03 | +16.343 |
| sf/27C | 1.103583e-03 | 1.557920e-03 | +41.169 | 1.103582e-03 | 1.452716e-03 | +31.636 |
| tt/125C | 5.985424e-05 | 8.978413e-05 | +50.005 | 5.985423e-05 | 8.081821e-05 | +35.025 |
| ff/125C | 2.366406e-05 | 3.800902e-05 | +60.619 | 2.366754e-05 | 3.454042e-05 | +45.940 |
| **sf/125C (worst case)** | 1.416885e-05 | 2.442921e-05 | **+72.415** | 1.417744e-05 | 2.210830e-05 | **+55.940** |

(All values seconds. The schematic columns are the pre-layout leg; the
27 °C corners retain their charge for milliseconds, the 125 °C corners for
tens of microseconds — retention shortens monotonically with temperature,
so the ratified worst case is sf/125 °C.)

**sf/125 °C audit trail** (the Test Plan's required row), from
`results/native/audit_*.json` and the native reports:

- *bitcell schematic*: hold start `V(sn)` = 1.089889 V → threshold
  0.189889 V; bracketing rungs 0.175/0.200/0.225 V crossed at
  1.458e-05/1.389e-05/1.320e-05 s; cubic crossing **1.416885e-05 s**
  ≥ 1.005989e-5 → pass (fleet job `klt-sim-795e2f1701f6`, stamp `match`).
- *bitcell extracted*: hold start 1.232862 V → threshold 0.332862 V;
  rungs 0.175/0.200/0.225 V at 3.187e-05/3.059e-05/2.932e-05 s; cubic
  crossing **2.442921e-05 s** → pass (job `klt-sim-4f9db259e694`). Signed
  PEX delta **+72.415 %**.
- *array schematic*: 1.089882 V → 0.189882 V → **1.417744e-05 s** (job
  `klt-sim-0e7e8c8a2e70`); *array extracted*: 1.210530 V → 0.310530 V →
  **2.210830e-05 s** (job `klt-sim-c64bc82e6934`); delta **+55.940 %**.

Cross-check: the schematic leg's resolved/unresolved pattern and values
reproduce the committed intrinsic-only (`c_sn_ff = 0`) rows of
`sim/bitcell-transient/results/bitcell_transient_results.csv` (same 5
resolved corners; sf/125 there is 1.410819e-05 on the old `c6d73a3` pin
with ngspice-46 and linear interpolation, vs 1.416885e-05 here on
`f6eeac7` with ngspice-47 and the cubic ladder — 0.4 % apart), and the extracted
leg lands next to the committed fleet rows that carried the old lumped
`c_sn = 0.672741 fF` (tt/27: 2.835e-03 here vs 2.720e-03 there — the
extracted leg additionally carries the extracted junction geometry
AS/AD = 0.1974, which the lumped rows did not). The fresh bitcell
extraction
gives net `sn` 0.655 fF to ground plus 0.007 fF of rwl coupling; the
array's selected `sn_0_0` carries 0.502 fF to ground plus 0.005 fF of
wl_0 coupling (the array cell's own wiring is shorter, its neighbour
coupling lands on other nets' hubs) — both consistent with those bounds.

### Why 10 of 15 rows are unresolved (and why that is the record, not a gap)

The pre-layout (schematic) leg carries only the devices' own capacitance,
so its written level — `VDD − Vth(M_WR)` — falls **below the 0.9 V sense
margin** at 10 of 15 corners: at those corners the threshold
`hold_start − 0.9 V` is at or below the study's 0.05 V floor and the
crossing never happens. That is the bitcell-transient study's documented
write-margin failure mode ("a WRITE-margin failure, not a retention
result"), not a simulation defect; the committed intrinsic-only rows blank
the same 10 corners. The extracted leg, carrying ~0.6 fF of extracted
wiring capacitance, resolves 12 of 15 (its three blanks — ss/−40, fs/−40,
fs/27 — are the same write-margin floor, now biting only the
lowest-ceiling corners). Each unresolved row is `null` with its cause and
observation window in the envelope (message: "threshold … V at or below
the 0.05 V floor: written level below delta_v (write-margin failure, not a
retention result); observation window … s"), which `klt pex` renders as an
`error` delta row — never a fabricated pass — and that is why the
envelopes' status is `error` and why the item-7 grade is `check_failed`
rather than `met`. No measured value fell below the ratified benchmark
(`failed = 0` in both envelopes).

## Files

| Path | Purpose |
|---|---|
| `run_pex.sh` | The reproducible per-cell `klt pex` invocations (builds the pinned 0.9.1 venv under `work/`, regenerates the references, runs bitcell then array) |
| `gen_reference_netlists.py`, `reference/*.spice` | The two schematic-leg DUTs, regenerated from `design/gain_cell_2t.spice` and `layout/gain_cell_2t_array.lvs_reference.spice` with provenance headers |
| `pex_bench.py` | Shared bench construction + DUT checks (ordered pins, model counts, body-to-ground union-find) + the crossing reduction |
| `measure_pex_retention.py` | The `--measure-command` harness: builds each leg's bench, runs the `klt sim` batch grid stamp-gated, prints the measurement document |
| `test_pex_bitcell_array.py` | Offline checks (references fresh, bench geometry, reduction rules) — wired into `.github/workflows/evidence-checks.yml` |
| `results/klt_pex_*.json` | The two unedited PEX envelopes (cited by `block-manifest.json`) |
| `results/native/` | Per-leg benches, `klt sim` requests, the 12 native batch reports (job IDs, stamps, simulator versions) and per-side audit JSONs |
| `work/` (gitignored) | Fresh extractions, pinned-klt venv, pex stdout/stderr |

## Reproduce

```bash
PDK_ROOT=~/.ciel bash sim/pex_bitcell_array/run_pex.sh
python3 -I sim/pex_bitcell_array/test_pex_bitcell_array.py
```

The run needs `uv` (study-local venv pinned to klt 0.9.1, the version that produced the committed envelopes), the pinned open_pdks install,
and the batch fleet (`--wait-for-capacity 600` on every `klt sim`). A
rerun writes a new RUN_ID's envelopes and native reports; nothing
committed is ever overwritten. To regenerate the manifest grade after a
citation change: `klt signoff --manifest block-manifest.json --format json
> block-manifest.signoff.json` on the pinned klt, then
`python3 -I sim/check_append_only.py` and
`python3 -I sim/check_item9_inventory.py`.
