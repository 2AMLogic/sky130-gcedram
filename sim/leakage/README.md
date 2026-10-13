# Access-device off-state leakage (issue #2)

First link in the retention/refresh budget evidence chain CLAUDE.md
requires: **device-level leakage measured against the shipped sky130
models at temperature corners.** The next links -- an explicitly labelled
storage-node capacitance assumption, then the retention-time derivation
that combines the two -- are out of scope here and tracked in #3.

## Device choice

**Candidate access device: `sky130_fd_pr__nfet_01v8`**, the sky130 core
1.8 V NMOS. This is the standard logic transistor the shipped PDK ships
for digital/analog core use -- consistent with CLAUDE.md's framing of
gain-cell eDRAM as built from ordinary logic transistors on a standard
process, no special DRAM step. No dedicated "low-leakage" or `_lvt`
variant is used: `sky130_fd_pr__nfet_01v8_lvt` is a *lower*-threshold
(higher-leakage) device, the wrong direction for a retention-critical
access device, so it is not a candidate here.

**Geometry: W = 0.42 µm, L = 0.15 µm** -- the minimum drawn size the
shipped model supports for this device. This is an explicit **sizing
assumption**, not a ratified spec value: it sits exactly on the model's
own bin boundary (`lmin = 1.5e-07`, and a `wmin = 4.2e-07` bin edge, per
`sky130_fd_pr__nfet_01v8__tt.pm3.spice`), so it is the smallest,
worst-case-leakage candidate the shipped model characterizes. The
retention derivation in #3 may revisit this sizing (e.g. a longer `L` to
trade area for lower subthreshold/DIBL leakage) once a target retention
window is on the table -- this issue only establishes the measured
leakage of the baseline minimum-size device.

## Bias condition

The testbench (`tb_access_leakage.spice.tmpl`) holds the access device off
and biases it at the worst-case retention condition -- a storage node
that was last written to a logic '1', with the access transistor held off
and its bitline sitting at the "unselected" rail:

| Terminal | Node | Bias | Rationale |
|---|---|---|---|
| Gate | `wl` (wordline) | 0 V | Access transistor held OFF |
| Drain | `sn` (storage node) | `VDD` = 1.8 V | Worst case: node holds a charged '1' |
| Source | `bl` (bitline) | 0 V | Unselected bitline, maximizes `Vds` |
| Body | -- | 0 V | Core NMOS, body tied to substrate/VSS |

The measured quantity is the DC current drawn from the storage-node
voltage source (`vsn`) at this operating point -- the total current
discharging the storage node while the access device is off. This is
**not** a single leakage mechanism: sky130's shipped BSIM4 model
(`diomod = 1`) always includes the reverse-biased drain-body junction
diode alongside the transistor's own subthreshold channel conduction, so
a single DC operating-point measurement at the drain terminal captures
both **subthreshold conduction and junction leakage** together, as the
issue requires.

**Known modeling-scope limitation** (not folded into the reported
number): the shipped `sky130_fd_pr__nfet_01v8` model sets
`igcmod = igbmod = 0`, i.e. it does not model gate tunneling current. Gate
leakage is not captured by this testbench. This is a limitation of the
shipped PDK model, not a testbench defect -- it is documented here rather
than silently absorbed into the "total leakage" claim.

**Diffusion-geometry qualification (issue #89 trace, added after the
fact; the recorded results are unchanged).** The `xdut` card passes only
`l` and `w`, with no `ad`/`as`/`pd`/`ps`. The shipped wrapper subcircuit
therefore uses its defaults, `ad = as = pd = ps = 0`. So the junction
diode above is evaluated with **zero drawn drain/source area and
perimeter**, and only the gate-edge sidewall term (which scales with W)
remains. The layout draws `AD = AS = 0.1974 µm²` and `PD = PS = 1.78 µm`;
the schematic uses 0.1218 µm² and 1.42 µm. A matched-geometry sweep is now committed (see
"Geometry-matched re-measurement (issue #149)" below); the recorded
`ileak_a` rows here remain the unchanged legacy-geometry baseline. See
[`../retention/README.md`](../retention/README.md) "Leakage-device geometry
trace" and
[`spec/retention-refresh-budget.md`](../../spec/retention-refresh-budget.md)
Section 9.

## Corner sweep

**Process corners**: `tt`, `ss`, `ff`, `sf`, `fs` -- the five MOS process
corners defined in the shipped
`libs.tech/combined/sky130.lib.spice` (verified against the `.lib`
section names in that file for the pinned `open_pdks` commit; see
[`../../docs/pdk-pin.md`](../../docs/pdk-pin.md)). No local model edits,
no uncommitted `.include` paths --
`tb_access_leakage.spice.tmpl` references only this shipped file, at a
path resolved from `$PDK_ROOT`/`--pdk-root` at run time.

**Temperature**: -40 °C, 27 °C, 125 °C. These are not arbitrary: they are
the temperature points named in the shipped
`libs.tech/irsim/sky130A_{tt,ss,ff}_{low,nom,high}_{n40,27,125}.prm`
corner files (n40/27/125 in the filenames), and they match the
`-40...125 °C` range 2AMLogic/sky130-bandgap's ratified spec already uses
for temperature-corner claims on this same PDK.

5 process corners x 3 temperatures = **15 measurement points** per sweep,
satisfying CLAUDE.md's "PVT corners on every recorded result."

## Worst-case corner

As of the sweep recorded in `results/leakage_results.csv` (2026-08-20,
`open_pdks` commit `c6d73a35f524070e85faff4a6a9eef49553ebc2b`), the
worst-case (maximum) leakage point is:

**`sf` corner, 125 °C: `ileak_a ≈ 9.898880e-11 A` (≈ 99 pA).**

This is the number the retention derivation in #3 should use as its
worst-case leakage input, per CLAUDE.md's "Retention claims are made at
the worst-case temperature corner, not typicals." All 15 points are in
`results/leakage_results.csv`; a brief read of that data:

- Leakage is dominated by temperature, not process corner, at -40 °C and
  27 °C (all five corners cluster within ~2x of each other, ~1.8-2.6 pA).
- At 125 °C the process corners diverge sharply: `tt` reaches ~11.5 pA,
  `ss`/`fs` stay near ~2-3 pA, while `ff` (~66 pA) and `sf` (~99 pA) jump
  by more than an order of magnitude over the room-temperature value.
  This is an as-measured result from the shipped model bins, not
  independently re-derived here -- it is reported, not editorialized.
- `sf` names the NMOS-side bin as its first letter (verified: `sf.spice`
  includes `sky130_fd_pr__nfet_01v8__sf.pm3.spice`), so this is a
  genuine NMOS-corner effect at high temperature in the shipped model,
  not a PMOS artifact leaking into an NMOS-only testbench.

## Reproducing this testbench

Requires a stock `open_pdks` sky130 install (via `volare`, pinned in
[`../../docs/pdk-pin.md`](../../docs/pdk-pin.md)) and `ngspice` on `PATH`.
No local model edits.

```bash
# 1. Install/enable the pinned PDK commit (skip if already enabled):
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b

# 2. Point PDK_ROOT at your volare root if it isn't ~/.volare:
export PDK_ROOT=~/.volare   # default; only needed if you installed elsewhere

# 3. Check the environment resolves correctly:
python3 sim/leakage/run_leakage_sweep.py --check-env

# 4. Run the full sweep (5 corners x 3 temperatures, ~4-5 minutes on a
#    single core -- each ngspice invocation loads the full BSIM4 model
#    set for its corner):
python3 sim/leakage/run_leakage_sweep.py
```

This **appends** rows to `results/leakage_results.csv` (creating it with
a header on first run) -- it never truncates or overwrites prior rows,
per CLAUDE.md's "`sim/` results are append-only evidence." A fresh
reproduction run should append 15 rows whose `ileak_a` values match the
existing rows for the same `(corner, temp_c)` to within simulator/host
floating-point noise; the two independent sweeps that produced this
directory's committed data did reproduce exactly (see script history in
version control).

Useful flags:

```bash
python3 sim/leakage/run_leakage_sweep.py --corners tt --temps-c 27   # single point
python3 sim/leakage/run_leakage_sweep.py --dry-run                   # render netlists, don't simulate
python3 sim/leakage/run_leakage_sweep.py --pdk-root /path/to/.volare --pdk sky130A
```

## Geometry-matched re-measurement (issue #149)

The `xdut` card above passes no `ad`/`as`/`pd`/`ps`, so every row of
`results/leakage_results.csv` was evaluated with zero drawn diffusion (see the
qualification in "Bias condition"). Issue #149 re-measures the same device, bias
and 15 PVT points with the drawn diffusion of the extracted layout. This is a
**separate study with its own files**; the original template, driver and CSV are
unchanged baselines, and nothing ratified (spec Sections 5/7) changes.

* Geometry is **derived, not typed**: `gen_geometry_leakage.py` reads
  `layout/gain_cell_2t_array.extract.parasitics.json`, selects the 16 access
  devices by connectivity (gate on `wl*`, source on `bl*`, drain on `sn*`; the 16
  read devices are excluded), requires one shared parameter set and rejects
  missing/invalid/heterogeneous input. Result: `l=0.15 w=0.42` um,
  `ad = as = 0.1974` um^2, `pd = ps = 1.78` um. Units: the shipped model library sets
  `.option scale=1.0u`, so the wrapper takes numeric micrometres (areas um^2); the
  extraction JSON fields are already `*_um`/`*_um2`, no rescaling.
* Deck `geometry-matched/access_leakage_geom.spice` holds two independent DUTs per
  corner: `xext` (extracted diffusion) and `xleg`, a **same-batch control** with the
  legacy card. Bias and observable are the legacy ones (drain 1.8 V; gate/source/body
  0 V; `abs(i(vsn))`).
* The grid is **one `klt sim` corner request** (`geometry-matched/request.json`:
  `tt,ss,ff,sf,fs` x `-40,27,125` C, backend `batch`, a one-point `dc` sweep read by
  `.meas ... AT=1.8`). No local ngspice grid was run.
* Run `20261011T071229Z`: batch job `klt-sim-75726efdccab` (aws-batch-fleet, c7i.4xlarge, spot,
  101 s), ngspice 46, client klt 0.6.0, PDK open_pdks `c6d73a35`. Raw report:
  `geometry-matched/results/klt_report_20261011T071229Z.json`; derived:
  `geom_leakage_points_20261011T071229Z.csv`, `geom_leakage_summary_20261011T071229Z.json`
  (hashes of deck, request, extraction and the historical CSV are in the summary).

### Result (extracted vs LEGACY TESTBENCH geometry)

| Corner | T (C) | I extracted (A) | I control, legacy geom, same batch (A) | I historical CSV (A) | extracted / control | extracted / historical |
|---|---|---|---|---|---|---|
| tt | -40 | 1.8000e-12 | 1.8100e-12 | 1.8101e-12 | 0.994 | 0.994 |
| tt | 27 | 1.8362e-12 | 1.8452e-12 | 1.8452e-12 | 0.995 | 0.995 |
| tt | 125 | 2.1772e-11 | 1.1521e-11 | 1.1521e-11 | 1.890 | 1.890 |
| ss | -40 | 1.8000e-12 | 1.8100e-12 | 1.8100e-12 | 0.994 | 0.994 |
| ss | 27 | 1.8015e-12 | 1.8106e-12 | 1.8106e-12 | 0.995 | 0.995 |
| ss | 125 | 1.2502e-11 | 2.2509e-12 | 2.2509e-12 | 5.554 | 5.554 |
| ff | -40 | 1.8011e-12 | 1.8111e-12 | 1.8111e-12 | 0.994 | 0.994 |
| ff | 27 | 2.2061e-12 | 2.2151e-12 | 2.2151e-12 | 0.996 | 0.996 |
| ff | 125 | 7.6509e-11 | 6.6258e-11 | 6.6258e-11 | 1.155 | 1.155 |
| sf | -40 | 1.8025e-12 | 1.8125e-12 | 1.8125e-12 | 0.994 | 0.994 |
| sf | 27 | 2.5458e-12 | 2.5549e-12 | 2.5549e-12 | 0.996 | 0.996 |
| sf | 125 | 1.0924e-10 | 9.8989e-11 | 9.8989e-11 | 1.104 | 1.104 |
| fs | -40 | 1.8000e-12 | 1.8100e-12 | 1.8100e-12 | 0.994 | 0.994 |
| fs | 27 | 1.8026e-12 | 1.8116e-12 | 1.8116e-12 | 0.995 | 0.995 |
| fs | 125 | 1.3014e-11 | 2.7626e-12 | 2.7626e-12 | 4.711 | 4.711 |

* **Measured worst case (max extracted current): sf / 125 C, 1.0924e-10 A**, 1.104x
  the same-batch control and the historical row (9.89888e-11 A): +10.4 %. This agrees
  with the +10 % single-probe estimate in #89, but that probe was not evidence; this
  grid is. The worst-case PVT did not move.
* The *largest ratio* is elsewhere: **ss / 125 C, 5.55x** (and fs / 125 C, 4.71x,
  tt / 125 C, 1.89x). Where the channel current is small (slow-N, hot), the
  area/perimeter junction term is a large fraction of a small number. These points
  are still far below the sf/125 C worst case in absolute terms.
* At -40 and 27 C the extracted geometry reads about 0.5 % **lower** (ratio 0.994 to
  0.996) at every corner, with the same-batch control showing the same offset against
  the extracted run; the sign and size were not investigated and are reported as
  measured (the junction contribution is negligible there, so it is a second-order
  model effect, not leakage physics claimed here).
* The same-batch control reproduces the historical CSV to <= 2.3e-6 relative error at
  all 15 points (`control_vs_historical` in the CSV), so the historical ngspice-47
  vs. this ngspice-46 batch run is not a measurable confound; the ratio against the
  CSV and against the control agree.
* Precision: the fleet runner (klt 0.5.0) honours default `.meas` precision only, so
  currents carry about 6 significant figures.

Limitations: DC off-state current only, global corners, one geometry (W=0.42, L=0.15). It
does not measure dynamic retention and authorizes no new refresh deadline; the
retention chain still uses the historical number. Feeding this into the retention
derivation is spec Section 9.6.1 (PROPOSED).

**First batch attempt (kept, failed).** `geometry-matched/results/klt_report_20261011T071027Z.json`
is the first submission (`op` + `measurements[].expr`, client klt 0.7.0): all 15 points
errored with `batch_runner_version_mismatch` (fleet runner klt 0.5.0 vs client 0.7.0),
no simulation ran. The request was then changed to the `dc` + `.meas` form and
resubmitted with client klt 0.6.0. The failed report is retained as the audit record and is
not used by any result.

Reproduce:

```bash
python3 -I sim/leakage/gen_geometry_leakage.py        # rewrite deck + request from the extraction
PDK_ROOT=~/.volare uvx --from "klayout-tools==0.6.0" klt sim --backend batch --format json \
    sim/leakage/geometry-matched/request.json > sim/leakage/geometry-matched/results/klt_report_<RUN_ID>.json
python3 -I sim/leakage/analyze_geometry_leakage.py sim/leakage/geometry-matched/results/klt_report_<RUN_ID>.json
python3 -I sim/leakage/test_geometry_leakage.py
```

## Files

| Path | Purpose |
|---|---|
| `tb_access_leakage.spice.tmpl` | ngspice netlist template (corner/temp substituted at run time) |
| `run_leakage_sweep.py` | Sweep driver: renders netlists, invokes `ngspice -b`, appends results |
| `results/leakage_results.csv` | Append-only recorded results (raw current vs. corner/temperature) |
| `gen_geometry_leakage.py`, `geometry-matched/` | Issue #149: geometry-matched deck + `klt sim` batch request generated from the extraction |
| `analyze_geometry_leakage.py`, `test_geometry_leakage.py` | Report reducer / comparison and its stdlib tests |
| `geometry-matched/results/` | Append-only raw batch report and derived comparison for #149 |

The PDK version pin and corner/temperature set this testbench targets are
documented in [`../../docs/pdk-pin.md`](../../docs/pdk-pin.md) (imported at
run time from `sim/_evidence_common.py`), not a local `pdk.json`.
