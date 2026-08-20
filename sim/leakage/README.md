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

## Corner sweep

**Process corners**: `tt`, `ss`, `ff`, `sf`, `fs` -- the five MOS process
corners defined in the shipped
`libs.tech/combined/sky130.lib.spice` (verified against the `.lib`
section names in that file for the pinned `open_pdks` commit; see
`pdk.json`). No local model edits, no uncommitted `.include` paths --
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
`pdk.json`) and `ngspice` on `PATH`. No local model edits.

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

## Files

| Path | Purpose |
|---|---|
| `tb_access_leakage.spice.tmpl` | ngspice netlist template (corner/temp substituted at run time) |
| `run_leakage_sweep.py` | Sweep driver: renders netlists, invokes `ngspice -b`, appends results |
| `pdk.json` | PDK version pin and corner/temperature set this testbench targets |
| `results/leakage_results.csv` | Append-only recorded results (raw current vs. corner/temperature) |
