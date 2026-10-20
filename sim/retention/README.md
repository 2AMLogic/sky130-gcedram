# Retention-time derivation for candidate 2T/3T geometries (issue #3)

Second and third links in the retention/refresh-budget evidence chain
CLAUDE.md requires: **a storage-node capacitance assumption, explicitly
labelled as an assumption**, combined with the **measured worst-case
access-device leakage** from [`sim/leakage/`](../leakage/README.md) (issue
#2), to produce a **retention-time estimate stated at the worst-case
temperature corner**. Per CLAUDE.md: "a retention number without its chain
is not a result." This document is that chain, end to end, and
[`derive_retention.py`](derive_retention.py) reproduces every number in it.

## What is measured, computed, extracted, and assumed here

This derivation deliberately keeps different kinds of number apart, because
conflating them is exactly the failure mode CLAUDE.md's evidence chain rule
exists to prevent:

| Kind | Value | Source |
|---|---|---|
| **Measured** | Worst-case access-device leakage, `ileak_a` | ngspice simulation against the shipped sky130 BSIM4 model, recorded in [`sim/leakage/results/leakage_results.csv`](../leakage/results/leakage_results.csv) (issue #2) |
| **Computed** (not measured, not assumed) | Read-transistor gate-oxide capacitance, `C_gate` | Closed-form `Cox'' = eps0 * epsrox / toxe` using the `toxe`/`epsrox` parameters read directly out of the shipped sky130 BSIM4 model card -- a real, reproducible number from public PDK model constants, but not itself a simulation result |
| **Extracted** (issue #7, `2T-min` only) | Total storage-node capacitance `C_SN` | Post-layout `klt extract --parasitics --critical-net sn` run against the committed [`layout/gain_cell_2t.gds`](../../layout/gain_cell_2t.gds) (issue #15/PR #18) -- see "Storage-node capacitance" below. Reclassified from ASSUMPTION to extracted now that a `2T-min` layout exists to extract from. |
| **ASSUMPTION** (explicitly labelled) | Total storage-node capacitance `C_SN` for `3T-min`, and the sense margin `delta_V` for both geometries | No `3T-min` layout exists yet for this macro (3T is a documented alternative, not the ratified baseline -- [`spec/retention-refresh-budget.md`](../../spec/retention-refresh-budget.md) Section 6), so its `C_SN` remains a margin-factor assumption. No sense-amplifier design exists yet either, so `delta_V` remains assumed for both geometries. Both are stated as explicit assumptions with their rationale below, not presented as measured or derived quantities. |

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

## Storage-node capacitance: computed term, extracted `2T-min` value, ASSUMED `3T-min` margin

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

**EXTRACTED value, `2T-min` (issue #7)** -- now that a `2T-min` sky130
bitcell layout is committed
([`layout/gain_cell_2t.gds`](../../layout/gain_cell_2t.gds), issue #15/PR
#18), `C_SN` for `2T-min` is read from a post-layout parasitics extraction
run against it, instead of assumed as a margin factor over `C_gate`:

```
$ klt extract layout/gain_cell_2t.gds --deck sky130 \
    --top gain_cell_2t_layout_0 --parasitics --critical-net sn \
    -o layout/gain_cell_2t.extract.parasitics.spice --format json
```

(`--parasitics` extracts first-order lumped RC parasitics -- one series R
+ one ground C per net, from the deck's curated sheet-resistance/
capacitance table; `--critical-net sn` additionally scopes the lateral
(same-layer sidewall) coupling-capacitance pass onto the storage node,
since `sn` couples to the adjacent `bl`/`rwl` routing in the routed
layout. Verified against the locally installed `klt 0.3.0` as of
2026-08-25; see
[docs/cli/extract.md](https://github.com/2AMLogic/klayout-tools/blob/main/docs/cli/extract.md)
in 2AMLogic/klayout-tools for the flag contract.) The committed result is
[`layout/gain_cell_2t.extract.parasitics.json`](../../layout/gain_cell_2t.extract.parasitics.json)
/ [`.spice`](../../layout/gain_cell_2t.extract.parasitics.spice). `sn`'s
entry in the JSON `parasitics.nets[]` block reports:

```
ground capacitance (junction + overlap + routing-to-substrate) = 0.586490 fF
+ lateral coupling to bl                                      = 0.010710 fF
+ lateral coupling to rwl                                     = 0.008154 fF
--------------------------------------------------------------------------
C_SN (EXTRACTED)                                               = 0.605354 fF
```

The two coupling terms are included in `C_SN` because they are real
physical capacitance loading the storage node, even though their far
terminal is a named net (`bl`, `rwl`) rather than ground/substrate --
omitting them would understate the node's true capacitive load. This does
not assume `bl`/`rwl` are held quiescent during the retention window, only
that the capacitance itself is real; a coupling-noise analysis of `bl`/
`rwl` switching during retention is separate, array-level follow-on work
(see "What these numbers say (and do not say)" below), not part of this
single-cell `C_SN` figure. `derive_retention.py`'s `load_extracted_c_sn()`
reproduces this sum directly from the committed JSON -- it does not
re-invoke `klt`.

**ASSUMED margin, `3T-min` only** -- no `3T-min` layout exists yet (3T is
a documented alternative per
[`spec/retention-refresh-budget.md`](../../spec/retention-refresh-budget.md)
Section 6, not the ratified baseline), so its `C_SN` remains expressed as
a margin factor over `C_gate`, covering the storage node's other real
contributors (M1's drain-body junction capacitance, gate-drain/gate-source
overlap capacitance, and local routing) that pre-layout sizing has no
extractable value for:

| Geometry | Topology | `C_SN` source | Margin factor (ASSUMPTION, `3T-min` only) | `C_SN` |
|---|---|---|---|---|
| `2T-min` | 2T | **EXTRACTED** (`klt extract --parasitics`, issue #7) | n/a | 0.605354 fF |
| `3T-min` | 3T | ASSUMED (margin factor over `C_gate`) | 4.0x | 2.212925 fF |

**The `3T-min` margin factor remains an explicit engineering assumption,
not a measurement or layout extraction** -- no `3T-min` layout exists for
this macro, and per the ratified-topology decision it may never be built
(3T-min is optional/secondary, contingent on a future read-disturb study).
It is assumed to carry roughly double the 2T candidate's *previously
assumed* non-gate-oxide parasitics (a qualitative topology judgment, not a
derived number, predating the `2T-min` extraction above) -- exactly the
kind of pre-layout sizing assumption CLAUDE.md requires be labelled as
such rather than presented as measured. **This assumption should be
revisited if a `3T-min` layout is ever built** (tracked as a follow-up,
see "Follow-up" below).

In `sim/retention/results/retention_results.csv`, the
`c_storage_node_margin_factor_ASSUMPTION` / `c_storage_node_ff_ASSUMPTION`
columns are **repurposed, not renamed**, for the extracted `2T-min` rows
(the CSV schema is unchanged so previously-committed rows stay
byte-identical, per CLAUDE.md's append-only convention): the margin-factor
column is left blank (no margin factor was applied) and the `C_SN` column
holds the extracted total; each such row's `notes` column carries the full
extraction provenance (command, `klt` version, input content hash, and the
ground/coupling breakdown) instead of being blank.

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

Both an assumption-based derivation (issue #3, 2026-08-20) and, for
`2T-min`, an extraction-based re-derivation (issue #7, 2026-08-25) are
recorded in `results/retention_results.csv` -- append-only, per CLAUDE.md;
the original assumption-based rows are never overwritten. The
extraction-based `2T-min` row below supersedes the assumption-based
`2T-min` row as this repo's current best `2T-min` retention estimate; both
remain in the CSV as committed evidence.

| Geometry | Topology | `C_SN` source | `C_SN` (fF) | `delta_V` (ASSUMED, V) | `I_leak` (measured, A) | `t_retention` |
|---|---|---|---|---|---|---|
| `2T-min` | 2T | ASSUMED (issue #3, superseded) | 1.106463 | 0.9 | 9.898880e-11 (sf, 125 °C) | 1.005989e-05 s (~10.06 µs) |
| `2T-min` | 2T | **EXTRACTED (issue #7, current)** | 0.605354 | 0.9 | 9.898880e-11 (sf, 125 °C) | **5.503841e-06 s (~5.50 µs)** |
| `3T-min` | 3T | ASSUMED | 2.212925 | 0.9 | 9.898880e-11 (sf, 125 °C) | **2.011978e-05 s (~20.12 µs)** |

The extracted `2T-min` retention time (~5.50 µs) is *shorter* than the
2026-08-20 assumption-based estimate (~10.06 µs) -- the assumed 2.0x
margin factor over `C_gate` (1.106463 fF) turned out to overstate the real
extracted `C_SN` (0.605354 fF) for this geometry, so the assumption was
not conservative in this direction; the extracted value is now this
repo's evidence-backed number for `2T-min`. All retention-time estimates
above are stated at the worst-case corner (`sf`, 125 °C) -- the leakage
number itself, per `sim/leakage/README.md`, is already the maximum across
all 15 measured PVT points. Raw derivation output (all intermediate
values, machine-readable) is in
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

Requires a stock `open_pdks` sky130 install (via `ciel`, same pin as
[`../../docs/pdk-pin.md`](../../docs/pdk-pin.md)), the leakage results already recorded in
`sim/leakage/results/leakage_results.csv`, and (for the `2T-min`
extraction path) the committed
[`layout/gain_cell_2t.extract.parasitics.json`](../../layout/gain_cell_2t.extract.parasitics.json).
No ngspice invocation, and no `klt` invocation either -- this script only
reads the leakage CSV, the shipped model card, and that committed
extraction JSON (it does not re-run `klt extract` itself; see "Storage-node
capacitance" above for the command that produced it).

```bash
# 1. Install/enable the pinned PDK commit (skip if already enabled):
pip install ciel==2.6.1
ciel enable --pdk-family sky130 -l sky130_fd_pr f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7

# 2. Point PDK_ROOT at your ciel root if it isn't ~/.ciel:
export PDK_ROOT=~/.ciel   # default; only needed if you installed elsewhere

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

## Array-context `C_SN`: capacitance-only comparison (issue #89)

**Label: CAPACITANCE-ONLY SENSITIVITY.** This is not measured array
retention, not geometry-matched, not dynamic, not ratified, and not an
array guarantee. The default derivation above is unchanged:
`derive_retention.py` still reads the isolated-cell report (`net sn`) and
`retention_results.csv` gets no new rows. The proposed decision that uses
this comparison is in
[`spec/retention-refresh-budget.md`](../../spec/retention-refresh-budget.md)
Section 9 (PROPOSED, not ratified).

[`compare_array_c_sn.py`](compare_array_c_sn.py) reduces every
`sn_<row>_<col>` net in the committed 4x4 array extraction
([`layout/gain_cell_2t_array.extract.parasitics.json`](../../layout/gain_cell_2t_array.extract.parasitics.json),
issue #80). It uses `load_extracted_c_sn()` itself, so the convention is the
same as the default path: ground plus every coupling capacitor on the net.
It then compares three estimates and keeps them separate:

| Estimate | `C_SN` (fF) | Ratio to isolated cell | `t_retention` | Status |
|---|---|---|---|---|
| Pre-layout (`retention_results.csv` line 2) | 1.106463 (ASSUMED) | n/a | 10.06 µs | **Ratified**, spec Section 5. Not changed here |
| Isolated cell, extracted (line 4) | 0.605354 | 1 | 5.50 µs | Current best single-cell estimate (#7). Not ratified |
| Array, limiting node `sn_3_3` | 0.473620 | 0.782385 | 4.31 µs | Capacitance-only sensitivity |
| Array, largest nodes `sn_1_1`, `sn_1_2`, `sn_2_1`, `sn_2_2` | 0.502000 | 0.829267 | 4.56 µs | Capacitance-only sensitivity |

These figures are a snapshot of the committed inputs. The script
recomputes them, and
[`results/array_c_sn_comparison_20261011T020547Z.json`](results/array_c_sn_comparison_20261011T020547Z.json)
records them. That file also holds the full 16-node distribution, per-node
ratios and times, the minimum and maximum node identities and their ties,
and the inputs' sha256 hashes and klt content hashes. The scaling is
`t_array = t_single * C_array / C_single`, applied to the **extracted**
isolated-cell row, with that row's `I_leak` (sf, 125 °C) and
`delta_V = 0.9 V` ASSUMPTION unchanged. It is not applied to the ratified
pre-layout value.

How the limiting node is chosen: the smallest total, rounded to 1e-9 fF.
Ties go to the lowest `(row, col)`, and every tied node is listed. The
whole distribution is kept, so the limiting node is never swapped for the
largest one. In this 4x4 the minimum is the corner cell `sn_3_3`, which
has the fewest coupled neighbours. Coupling is 8.5% to 14.2% of each
node's total. With coupling dropped, the smallest ground-only value is
0.430576 fF (ratio 0.71128). That is a reference for how much the number
depends on quiet neighbours, not a bound.

### What `C_SN` contains: wiring only

Neither the single-cell nor the array number includes the M_RD gate
capacitance or the M_WR drain-junction capacitance. `by_layer` lists only
poly, li1 and met1 (see [`layout/README.md`](../../layout/README.md),
issue #80 "Convention"). So the ground capacitance row in "Storage-node
capacitance" above, labelled "junction + overlap + routing-to-substrate",
is wiring to substrate. That label comes from issue #7 and is left as
written, since it is historical text.

The comparison is therefore wiring against wiring. It is not the node's
full physical capacitance. The computed gate-oxide term (0.553231 fF) must
not simply be added to these numbers, for two reasons. First, the
extractor's 0.173920 fF poly term has not been checked for overlap with
the channel region, so adding the gate term could count it twice. Second,
junction capacitance depends on voltage and device geometry. The
geometry-matched path in spec Section 9 instead lets the device model
evaluate both terms from the extracted netlist.

### Leakage-device geometry trace (AD/AS/PD/PS)

| Source | AD = AS (µm²) | PD = PS (µm) | Provenance |
|---|---|---|---|
| Leakage testbench `xdut` | **not passed** (wrapper default 0) | **not passed** (wrapper default 0) | [`sim/leakage/tb_access_leakage.spice.tmpl`](../leakage/tb_access_leakage.spice.tmpl) passes only `l=0.15 w=0.42`. The shipped wrapper `.subckt sky130_fd_pr__nfet_01v8` in `$PDK_ROOT/sky130A/libs.tech/combined/continuous/models_fet.spice` (open_pdks `c6d73a35`) declares `.param l = 1 w = 1 nf = 1 ad = 0 as = 0 pd = 0 ps = 0 ...` |
| Schematic `XM_WR`/`XM_RD` | 0.1218 | 1.42 | [`design/gain_cell_2t.spice`](../../design/gain_cell_2t.spice) |
| Extracted, single cell and all 32 array devices | 0.1974 | 1.78 | Device `params` in both `layout/*.extract.parasitics.json` reports |

So the measured `I_leak` = 9.898880e-11 A was evaluated with **zero**
drain/source diffusion area and perimeter. Issue #89 assumed it used the
schematic values; it used neither those nor the extracted ones. The BSIM4
junction terms of `diomod = 1` that scale with drawn diffusion area and
field-edge perimeter therefore contribute nothing to that number. Only the
gate-edge sidewall term, which scales with W, remains. As a result, the
sentence in [`sim/leakage/README.md`](../leakage/README.md) saying the
measurement captures junction leakage needs this qualification; a note
has been added there. Adding reverse-biased junction area can only add
current, so the committed `I_leak` most likely **understates** the leakage
of the drawn device, and every retention figure in this file is optimistic
in that respect. Changing `C_SN` alone does not fix this.

**Update (issue #149): the geometry-matched leakage sweep is now committed**
as new evidence, [`sim/leakage/geometry-matched/`](../leakage/README.md) "Geometry-matched
re-measurement (issue #149)" (batch job `klt-sim-75726efdccab`, run `20261011T071229Z`).
Measured worst case sf / 125 C: 1.0924e-10 A vs the 9.89888e-11 A used above
(+10.4 %); the largest ratio is ss / 125 C (5.55x) at a much smaller absolute current.
The estimates in this file still use the historical legacy-geometry number and are
**unchanged**; adopting the new input is spec Section 9.6.1 (PROPOSED).

*Original statement of the missing evidence (now supplied):* a leakage
sweep using the extracted geometry (`ad = as = 0.1974`, `pd = ps = 1.78`)
over the same 15 PVT points, committed as new append-only evidence. It
should be submitted as a `klt sim` corner request, not a hand-run grid. Tracked in #149.
The full list is in spec Section 9.

```bash
python3 -I sim/retention/compare_array_c_sn.py            # print the summary
python3 -I sim/retention/compare_array_c_sn.py --check sim/retention/results/array_c_sn_comparison_20261011T020547Z.json
python3 -I sim/retention/compare_array_c_sn.py --write    # NEW timestamped file; never overwrites
python3 -I sim/retention/test_compare_array_c_sn.py       # focused tests
```

The script needs only the standard library, with no PDK, ngspice or klt.
`--check` exits 1 if the committed inputs no longer reproduce the
committed file. That covers a changed report, a changed hash, or a changed
baseline row. A regenerated array GDS (#91) needs a new extraction and a
new comparison file. Do not edit this one.

## Re-derivation under open_pdks `f6eeac7` (issue #168)

`derive_retention.py` now reads only leakage rows stamped with the current pin (`PDK_OPEN_PDKS_COMMIT`) and
refuses to run if there are none, so a retention number can never be a maximum over a mix of pins. Each new row's
`notes` cites the leakage row it used (pin, timestamp, simulator, batch job id). It was re-run against the
`f6eeac7` leakage block from `sim/leakage/` (batch job `klt-sim-c2ed3f15ab70`); worst case is again `sf` / 125 C,
`I_leak = 9.898880e-11 A`. `C_SN` is the same labelled ASSUMPTION (`3T-min`, 4.0 x C_gate) or the same extracted
value (`2T-min`, 0.605354 fF), `delta_V = 0.9 V` ASSUMED.

| Geometry | `c6d73a3` chain | `f6eeac7` chain |
|---|---|---|
| `2T-min` (extracted `C_SN`) | 5.503841e-06 s | 5.503841e-06 s |
| `3T-min` (assumed `C_SN`) | 2.011978e-05 s | 2.011978e-05 s |

No change (delta 0). The ratified ~10.06 us in `spec/retention-refresh-budget.md` is unchanged; that section
gets a supersession note only. The bitcell-transient cross-check is **not** yet re-run under `f6eeac7`
(tracked in #182), so the retention chain here is re-derived from leakage but its
transient cross-check still rests on `c6d73a3`.

`compare_array_c_sn.py --check` / `build()` take `retention_as_of` so a committed comparison JSON reproduces against
the CSV as it stood when generated, ignoring rows appended later.

## Compact-layout re-characterisation (issue #161)

**CAPACITANCE-ONLY SENSITIVITY at geometry-matched leakage. Not measured array retention, not a ratified value, no
spec edit.** The compact bitcell layouts of #100 (`layout/compact/`, `v2` = 1.399 um^2/cell drawn, `v1` = 1.950 um^2)
change the geometry around the storage node, so the #7/#80/#89/#149 numbers do not transfer. This section re-runs
the same three-link chain on them. Everything is reproducible from committed inputs; all result files are new and
append-only (registered in `sim/append_only_inventory.txt`).

| Link | What | Committed evidence |
|---|---|---|
| 1. Leakage | Access-device off-state current at the **extracted** drawn diffusion of each layout, 5 corners x {-40, 27, 125} C, one `klt sim` batch request (`backend: batch`, job `klt-sim-d932937e59c3`) | `sim/leakage/compact_geometry_leakage.py`, `sim/leakage/compact-geometry/` (deck, `request.json`, `results/`) |
| 2. `C_SN` (ASSUMPTION-labelled as a total: wiring only) | Per-node ground + all coupling, same convention as `derive_retention.load_extracted_c_sn()` | `layout/compact/gain_cell_2t_{v2,v1}_array.extract.parasitics.{json,spice}`, `layout/compact_parasitics.py`, `layout/results/compact_parasitics_20261020T171849Z.json` |
| 3. Derivation | `t = C_SN * delta_V / I_leak`, `delta_V = 0.9 V` (existing ASSUMPTION), compared with ratified Section 5/7 | `compare_compact_c_sn.py`, `results/compact_c_sn_*.json` |

Reproduce: `klt extract <gds> --deck sky130 --top gain_cell_2t_<v>_array_4x4_layout_0 --parasitics` with
`--critical-net` for every `wl_/rwl_/bl_/rbl_` net **and** `--critical-net-pattern '\$*'` (see below), then
`python3 -I sim/leakage/compact_geometry_leakage.py gen`, `klt sim sim/leakage/compact-geometry/request.json`
(fleet), `... reduce <report>`, `python3 -I layout/compact_parasitics.py --write`,
`python3 -I sim/retention/compare_compact_c_sn.py --leakage-summary <summary> --write`. Each `--check` reproduces
its committed file; `python3 -I sim/retention/test_compare_compact_c_sn.py` covers them.

### Findings

**Storage nodes are unlabelled in the compact layouts.** They extract as anonymous `\$N` nets, so naming `sn_<r>_<c>`
as `--critical-net` (as for the uniform grid) matches nothing and the lateral-coupling pass silently skips them
(the extractor emits a warning). The extraction therefore names the anonymous nets via a `\$*` glob, and
`layout/compact_parasitics.py` identifies the storage nodes from device connectivity (non-bit-line terminal of each
write device, which must also be the gate of exactly one read device). Without this, `C_SN` would omit its coupling
term. The uniform-grid extraction (klt 0.7.0) re-extracts to identical per-net totals with the klt used here.

**`C_SN` (wiring, ground + coupling), fF**

| Layout | min (limiting node) | max | ground | coupling | min / isolated 0.605354 |
|---|---|---|---|---|---|
| Uniform grid 4x4 (#80) | 0.473620 (`sn_3_3`) | 0.502000 | 0.4306-0.4337 | 0.0404-0.0714 | 0.782 |
| Compact `v2` | 0.316892 (`\$20`) | 0.334888 | 0.2915-0.2916 | 0.0253-0.0434 | 0.523 |
| Compact `v1` | 0.308707 (`\$19`) | 0.329304 | 0.2915-0.2916 | 0.0171-0.0378 | 0.510 |

`v2` is 0.669x the uniform-grid limiting node. The 16 `v2` nodes split into tied groups; see `per_node` in the JSON.

**Leakage at the extracted junction geometry (worst case `sf` / 125 C for all three)**

The storage-node-side diffusion shrinks (AD/PD 0.1974/1.78 uniform vs 0.1197/1.41 compact), so the junction term
falls. Subthreshold current is unchanged.

| Geometry (SN-side AD, PD) | `I_leak` worst case | vs uniform-grid geometry |
|---|---|---|
| Uniform grid, extracted (0.1974, 1.78) | 1.0924e-10 A (reproduces #149 exactly) | 1.000 |
| Compact `v2`/`v1`, extracted (0.1197, 1.41) | 1.0595e-10 A | 0.970 |
| Legacy testbench card (no diffusion params) | 9.8989e-11 A | 0.906 |

`v1` and `v2` share the SN-side junction, so their leakage is identical; the bit-line-side diffusion differs but is
held at 0 V. Other corners: `tt`/125 C is 0.849x, `ss`/125 C 0.737x, `ff`/125 C 0.957x (full table in
`sim/leakage/compact-geometry/results/compact_leakage_points_20261020T1716Z.csv`).

**Retention at `sf` / 125 C, geometry-matched leakage, `delta_V = 0.9 V`**

| Layout | limiting `C_SN` | `t_retention` | 2x-safety refresh interval | `C_SN` needed for the ratified 10.06 us |
|---|---|---|---|---|
| Ratified pre-layout (Section 5/7) | 1.106463 fF (ASSUMED, 2.0x `C_gate`) | 10.06 us | 5.03 us | - |
| Uniform grid 4x4 | 0.473620 fF | 3.902 us | 1.951 us | 1.221 fF |
| Compact `v2` | 0.316892 fF | 2.692 us | 1.346 us | 1.184 fF |
| Compact `v1` | 0.308707 fF | 2.622 us | 1.311 us | 1.184 fF |

### Does the ratified budget still hold?

**No, not on this evidence, and that is not new to the compact layouts.** At the geometry-matched worst-case leakage
the limiting `v2` node retains for ~2.69 us (0.27x the ratified 10.06 us), so the ratified 5.03 us refresh interval
would have to shrink to ~1.35 us at the same 2x margin. The uniform grid already fell short (3.90 us); compaction
costs a further ~33% of `C_SN` and gains ~3% from the smaller junction. The ratified value rests on an ASSUMED
`C_SN` (2.0x the computed read-gate capacitance) that the extraction has never supported.

Caveats that bound the claim, not hide it: (a) `C_SN` here is wiring only, as in #89; device gate and
junction capacitance are excluded and the open item of spec Section 9.6 (a node-capacitance convention that includes
device capacitance) is still open. (b) A bounding scenario adding the full computed read-gate capacitance
(0.553231 fF, which may double-count the extractor's poly term) gives 7.39 us for `v2` (0.73x ratified; 8.46 us for the
uniform grid, 0.84x) and still omits the write-device drain-junction capacitance. So the budget is **not shown to
hold** under either reading, and closing the gap needs evidence this issue does not produce (device-inclusive
`C_SN`, dynamic hold droop, #94). (c) `delta_V`, constant-current decay, single worst-case point, no mismatch,
quiet neighbours are the existing ASSUMPTIONS.

**No spec file, README density requirement or ratified value was changed.** Per the issue and CLAUDE.md the
shortfall is reported as an operator decision (filed with this PR).

### Array parasitics (`layout/results/compact_parasitics_20261020T171849Z.json`), 4 rows x 4 columns, worst net, fF

| Net | Uniform grid (#80/#88) | Compact `v2` | `v2` / uniform | Compact `v1` |
|---|---|---|---|---|
| C_RBL (ground+coupling) | 0.859179 | 1.534113 | 1.79x | 1.883834 |
| C_BL | 0.872796 | 0.864084 | 0.99x | 1.477636 |
| C_WL | 2.099047 | 0.330388 | 0.16x | 0.330388 |
| C_RWL | 1.353255 | 0.780991 | 0.58x | 0.765972 |

The compact `RBL` rises 1.79x because the compact layouts run it partly on met2 (0.497 fF of its 0.914 fF ground
term); it stays far below the 10 fF `C_RBL` ASSUMPTION of the sense stage (0.15x at 4 rows), but the row-count
scaling of #88 was **not** redone for the compact layouts (out of scope), so no per-row slope is claimed.

**Word-line resistance (new).** The word line is one continuous 0.15 um poly line per row (drawn 3.635 um long,
24.23 squares). Two numbers are kept apart in the JSON:

- *Extractor-reported*: 655.89 ohm per `wl_<r>`. This is klt's lumped **star** model (the sum of per-gate-terminal leg
  resistances to a hub), not an end-to-end line resistance.
- *Hand calculation*, labelled as such: `rsh x squares` with the PDK `rp1` of the shipped resistor corners (44 / 48.2 /
  55.8 ohm/sq) = 1066 / 1168 / 1352 ohm end to end for a driver at one end. With `C_WL` = 0.33 fF the lumped RC is
  ~0.4 ps, negligible for 4 columns; it scales with the square of the number of columns, so a wide row needs
  strapping (not assessed here).

The uniform grid straps its word line with li1/met1 (434.27 ohm star value, 2.10 fF); no hand end-to-end number is
claimed for it.

## Follow-up (out of scope here)

- **`3T-min` post-layout parasitic re-derivation**: if a `3T-min` layout
  is ever built (optional/secondary per the ratified 2T baseline decision,
  `spec/retention-refresh-budget.md` Section 6), its `C_SN` margin-factor
  assumption above should be replaced with an extracted value the same way
  issue #7 did for `2T-min`.
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
| `derive_retention.py` | Derivation driver: reads the worst-case leakage row from `sim/leakage/`, computes the gate-oxide capacitance term from the shipped PDK model card, reads the extracted `2T-min` storage-node capacitance from `layout/gain_cell_2t.extract.parasitics.json` (issue #7) / applies the labelled `3T-min` margin-factor assumption, applies the sense-margin assumption, and appends retention-time results |
| `results/retention_results.csv` | Append-only recorded results (all intermediate values, machine-readable) |
| `compare_array_c_sn.py` | Issue #89: array-context `C_SN` reduction (all `sn_<r>_<c>`), capacitance-only retention sensitivity against the ratified and isolated-cell baselines, and AD/AS/PD/PS trace. Never writes `retention_results.csv` |
| `results/array_c_sn_comparison_*.json` | Issue #89: append-only comparison snapshots (one new file per `--write`) |
| `test_compare_array_c_sn.py` | Issue #89: focused stdlib tests (reduction, validation, ties, units, reproduction of the committed snapshot) |
| `compare_compact_c_sn.py`, `results/compact_c_sn_*.json` | Issue #161: compact-layout (`layout/compact/`) `C_SN` and retention-budget re-check at geometry-matched leakage; append-only snapshots |
| `test_compare_compact_c_sn.py` | Issue #161: stdlib tests (storage-node identification, orientation, reproduction of committed results) |
