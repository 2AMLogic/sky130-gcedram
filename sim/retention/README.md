# Retention-time derivation for candidate 2T/3T geometries (issue #3)

Second and third links in the retention/refresh-budget evidence chain
CLAUDE.md requires: **a storage-node capacitance assumption, explicitly
labelled as an assumption**, combined with the **measured worst-case
access-device leakage** from [`sim/leakage/`](../leakage/README.md) (issue
#2), to produce a **retention-time estimate stated at the worst-case
temperature corner**. Per CLAUDE.md: "a retention number without its chain
is not a result." This document is that chain, end to end, and
[`derive_retention.py`](derive_retention.py) reproduces every number in it.

## What is measured, computed, and assumed here

This derivation deliberately keeps three different kinds of number apart,
because conflating them is exactly the failure mode CLAUDE.md's evidence
chain rule exists to prevent:

| Kind | Value | Source |
|---|---|---|
| **Measured** | Worst-case access-device leakage, `ileak_a` | ngspice simulation against the shipped sky130 BSIM4 model, recorded in [`sim/leakage/results/leakage_results.csv`](../leakage/results/leakage_results.csv) (issue #2) |
| **Computed** (not measured, not assumed) | Read-transistor gate-oxide capacitance, `C_gate` | Closed-form `Cox'' = eps0 * epsrox / toxe` using the `toxe`/`epsrox` parameters read directly out of the shipped sky130 BSIM4 model card -- a real, reproducible number from public PDK model constants, but not itself a simulation result |
| **ASSUMPTION** (explicitly labelled) | Total storage-node capacitance `C_SN`, and the sense margin `delta_V` | No layout exists yet for this macro, so junction/overlap/routing parasitics on the storage node cannot be extracted, and no sense-amplifier design exists yet to derive a validated sense margin from. Both are stated as explicit assumptions with their rationale below, not presented as measured or derived quantities. |

## Candidate geometries

Both candidates reuse the exact access-device sizing already measured in
`sim/leakage/` -- `sky130_fd_pr__nfet_01v8`, W = 0.42 µm, L = 0.15 µm, the
minimum drawn size the shipped model supports (see
[`sim/leakage/README.md`](../leakage/README.md) "Device choice"). This is
the only geometry this repo has a measured leakage number for, so both
candidates trace to the same cited leakage result; what differs between
them is the storage-node capacitance assumption, driven by topology:

- **`2T-min` (2T gain cell)**: write-access transistor M1 (drain = storage
  node) + read transistor M2 (gate = storage node, drain tied directly to
  the read bitline). No dedicated read-select device sits near the storage
  node -- a comparatively compact layout.
- **`3T-min` (3T gain cell)**: adds a dedicated read-access transistor M3
  between M2's drain and the read bitline, isolating the read bitline swing
  from M2 (the classic 3T motivation over 2T). M3 is **not** DC-connected
  to the storage node in this topology -- only M1's drain and M2's gate
  are -- so it does not add leakage into the node; the same measured
  leakage number from #2 applies to both candidates. It does, however, sit
  physically closer to the storage-node routing than the 2T layout, so
  this repo assumes a larger routing/coupling capacitance margin for the
  3T candidate.

## Leakage input (measured, cited from #2)

Per [`sim/leakage/README.md`](../leakage/README.md) "Worst-case corner",
the worst-case (maximum) measured leakage point, as of the sweep recorded
in `sim/leakage/results/leakage_results.csv` (2026-08-20, `open_pdks`
commit `c6d73a35f524070e85faff4a6a9eef49553ebc2b`), is:

**`sf` corner, 125 °C: `ileak_a = 9.898880e-11 A` (~99 pA).**

This is cited directly, not re-simulated, and both candidate geometries
below use this exact number as `I_leak` -- consistent with CLAUDE.md's
"Retention claims are made at the worst-case temperature corner, not
typicals."

## Storage-node capacitance: computed term + ASSUMED margin

**Computed term** -- the read transistor's gate-oxide capacitance, from
the shipped model card for the `sf` corner (the same corner the worst-case
leakage was measured at, so the gate-oxide term uses the same process
corner as the leakage input rather than mixing corners):

```
toxe   = 3.932304e-09 m   (electrical oxide thickness, sf corner,
                            sky130_fd_pr__nfet_01v8__sf.pm3.spice, base term
                            before the MC_MM_SWITCH mismatch offset)
epsrox = 3.9              (oxide relative permittivity, same model card)
eps0   = 8.8541878128e-12 F/m (vacuum permittivity, physical constant)

Cox'' = eps0 * epsrox / toxe = 8.781450 fF/um^2

C_gate = Cox'' * W * L = 8.781450 fF/um^2 * 0.42um * 0.15um
       = 0.553231 fF
```

`toxe` and `epsrox` are read directly out of the public, shipped model
card at `$PDK_ROOT/sky130B/libs.ref/sky130_fd_pr/spice/sky130_fd_pr__nfet_01v8__sf.pm3.spice`
by [`derive_retention.py`](derive_retention.py) -- reproducible from a
stock PDK install, no local model edits. Every W/L geometry bin in that
file shares the same corner-level `toxe` base term (only the mismatch
offset scales with bin geometry, and mismatch is not exercised by this
deterministic derivation), so this term is not geometry-bin-specific.

**ASSUMED margin** -- `C_SN` is expressed as a margin factor over
`C_gate`, covering the storage node's other real contributors (M1's
drain-body junction capacitance, gate-drain/gate-source overlap
capacitance, and local routing) that pre-layout sizing has no extractable
value for:

| Geometry | Topology | Margin factor (ASSUMPTION) | `C_SN` (ASSUMED) |
|---|---|---|---|
| `2T-min` | 2T | 2.0x | 1.106463 fF |
| `3T-min` | 3T | 4.0x | 2.212925 fF |

**These margin factors are explicit engineering assumptions, not
measurements or layout extractions.** No layout exists yet for this macro.
The 3T candidate is assumed to carry roughly double the 2T candidate's
non-gate-oxide parasitics, reflecting the additional read-select
transistor's proximity to the storage-node routing (see "Candidate
geometries" above) -- this is a qualitative topology judgment, not a
derived number, and is exactly the kind of pre-layout sizing assumption
CLAUDE.md requires be labelled as such rather than presented as measured.
**This assumption should be revisited once a layout exists to extract
parasitics from** (tracked as a follow-up, see "Follow-up" below).

## Sense margin (ASSUMPTION)

The retention time is the time for the storage node, written to a logic
'1' at `VDD` = 1.8 V, to decay past the point where a read-side sense
scheme can no longer reliably discriminate a stored '1' from a '0'. No
sense-amplifier design exists yet for this macro, so this repo assumes the
conservative half-`VDD` bound commonly used as a coarse worst-case sizing
rule in SRAM/DRAM sensing design, absent a validated sense-amp
offset/noise budget for this macro's own sense circuit:

```
delta_V_ASSUMPTION = VDD / 2 = 0.9 V
```

This is an explicit ASSUMPTION, independent of the storage-node
capacitance assumption above, and should likewise be revisited once a
sense-amplifier design exists for this macro.

## Retention-time formula

Constant-current (linear-decay) approximation: over the retention window,
the DC leakage current `I_leak` is treated as approximately constant (it is
the measured off-state current at `Vds` = `VDD`, the worst-case bias point
per `sim/leakage/README.md`; as the node discharges, `Vds` decreases,
which for both the subthreshold and reverse-junction leakage components
generally *reduces* leakage current -- so this constant-current
approximation is conservative in the direction of *understating* true
retention time, not overstating it):

```
t_retention = C_SN * delta_V / I_leak
```

## Results

| Geometry | Topology | `C_SN` (ASSUMED, fF) | `delta_V` (ASSUMED, V) | `I_leak` (measured, A) | `t_retention` |
|---|---|---|---|---|---|
| `2T-min` | 2T | 1.106463 | 0.9 | 9.898880e-11 (sf, 125 °C) | **1.005989e-05 s (~10.06 µs)** |
| `3T-min` | 3T | 2.212925 | 0.9 | 9.898880e-11 (sf, 125 °C) | **2.011978e-05 s (~20.12 µs)** |

Both retention-time estimates are stated at the worst-case corner (`sf`,
125 °C) -- the leakage number itself, per `sim/leakage/README.md`, is
already the maximum across all 15 measured PVT points. Raw derivation
output (all intermediate values, machine-readable) is in
[`results/retention_results.csv`](results/retention_results.csv).

## What these numbers say (and do not say)

These are retention estimates for the **candidate bitcell geometries in
isolation** -- a single storage node, a single access device's leakage,
and an assumed sense margin. They are **not** a macro-level or
array-level retention/refresh-interval spec: bitline coupling,
read-disturb during unselected-row access, sense-amplifier offset in a
real design, and process/mismatch variation across an array (this
derivation uses the deterministic, non-mismatch corner point) are all
out of scope here and would each tend to *shorten* the effective
retention window relative to this single-cell estimate. Per CLAUDE.md:
"Never describe the macro as a drop-in SRAM replacement" -- these
microsecond-to-tens-of-microseconds numbers are the dynamic-storage
tradeoff CLAUDE.md's retention/refresh-budget framing exists to make
explicit, not a defect to be explained away.

## Reproducing this derivation

Requires a stock `open_pdks` sky130 install (via `volare`, same pin as
`sim/leakage/pdk.json`) and the leakage results already recorded in
`sim/leakage/results/leakage_results.csv`. No ngspice invocation -- this
script only reads the leakage CSV and the shipped model card.

```bash
# 1. Install/enable the pinned PDK commit (skip if already enabled):
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b

# 2. Point PDK_ROOT at your volare root if it isn't ~/.volare:
export PDK_ROOT=~/.volare   # default; only needed if you installed elsewhere

# 3. Check inputs resolve:
python3 sim/retention/derive_retention.py --check-env

# 4. Run the derivation:
python3 sim/retention/derive_retention.py
```

This **appends** rows to `results/retention_results.csv` (creating it with
a header on first run) -- it never truncates or overwrites prior rows, per
CLAUDE.md's "`sim/` results are append-only evidence." A fresh reproduction
run reads whatever is currently the worst-case row in
`sim/leakage/results/leakage_results.csv` and re-derives against it, so if
issue #2's leakage numbers are ever re-measured (a new sweep appended), a
fresh run of this script automatically re-derives the retention estimate
against the new worst-case point rather than silently reusing a stale
number -- the mechanism satisfying this issue's Test Plan "confirm the
derivation is re-run ... if #2's numbers change."

## Follow-up (out of scope here)

- **Post-layout parasitic re-derivation**: once a layout exists for this
  macro's bitcell, the `C_SN` margin-factor assumption above should be
  replaced with an extracted value and this derivation re-run. Tracked in
  #7 rather than expanding this issue's scope.
- **Sense-amplifier-derived sense margin**: once a sense-amplifier design
  exists for this macro, `delta_V_ASSUMPTION` should be replaced with a
  value validated against that circuit's actual offset/noise budget.
- **Array-level retention/refresh-interval spec**: this document estimates
  single-cell retention only; a macro-level refresh interval must also
  account for bitline coupling, read disturb, and array-wide
  process/mismatch variation (tracked under the parent retention/refresh
  budget issue, #1, and the spec-ratification issue, #5).

## Files

| Path | Purpose |
|---|---|
| `derive_retention.py` | Derivation driver: reads the worst-case leakage row from `sim/leakage/`, computes the gate-oxide capacitance term from the shipped PDK model card, applies the labelled storage-node capacitance and sense-margin assumptions, and appends retention-time results |
| `results/retention_results.csv` | Append-only recorded results (all intermediate values, machine-readable) |
