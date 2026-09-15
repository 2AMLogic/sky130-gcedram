# layout

First layout increment (issue #15, T1 item 2 of the gap tracker, #13): the
sky130 geometry for the ratified 2T gain-cell bitcell, built from the
schematic/netlist committed by issue #14
([`design/gain_cell_2t.sch`](../design/gain_cell_2t.sch),
[`design/gain_cell_2t.spice`](../design/gain_cell_2t.spice)). Per
[`docs/design-evidence-tiers.md`](https://github.com/2AMLogic/klayout-tools/blob/main/docs/design-evidence-tiers.md)
item 2, the pass condition is a committed GDS **plus** reproducibility from
sources -- presence and reproducibility, not a one-off manual drop, the same
bar item 1 (#14) already established for the schematic/netlist pair.

**Scope**: geometry capture only. This is *not* a formal, reported-and-signed
-off DRC/LVS pass, a PVT corner sweep, or characterization -- those are
separate, later T1 items (#13's checklist items 3-8). The informal `klt
drc`/`klt extract`/`klt lvs` iteration below exists to get the geometry
right, per this issue's own non-goals. Post-layout storage-node *parasitic
extraction* (previously also out of scope here) was added by issue #7 --
see [`gain_cell_2t.extract.parasitics.json`](gain_cell_2t.extract.parasitics.json)
below and [`sim/retention/README.md`](../sim/retention/README.md) for how
it feeds the retention-time re-derivation.

## What's here

| File | Purpose |
|---|---|
| [`gain_cell_2t.gds`](gain_cell_2t.gds) | The `2T-min` bitcell layout -- the top cell (`gain_cell_2t_layout_0`) this issue delivers. |
| [`generate.sh`](generate.sh) | Regenerates every artifact in this directory from `design/gain_cell_2t.spice`'s topology via `klt gen`/`klt gen-compose` (this is the "reproducible from sources" mechanism -- not a one-off manual drop). `--check` reruns into a scratch directory and asserts DRC-clean + LVS-match without touching the committed files. |
| [`gain_cell_2t_mos.gds`](gain_cell_2t_mos.gds) / [`.json`](gain_cell_2t_mos.json) | Intermediate `klt gen mos_array` block: the two transistors (`U0`=`M_WR`, `U1`=`M_RD`), before placement/routing. |
| [`gain_cell_2t_tap.gds`](gain_cell_2t_tap.gds) / [`.json`](gain_cell_2t_tap.json) | Intermediate `klt gen guard_ring` block: a P-substrate tap (`add_well=false`), so extraction resolves both devices' body terminal to a real `GND` net instead of the deck's synthesized global substrate net -- see "Topology mapping" below. |
| [`gain_cell_2t.layout.request.json`](gain_cell_2t.layout.request.json) | `klt gen-compose` request: places the two blocks above, routes the `sn` net, and labels `wl`/`bl`/`rwl`/`rbl`/`GND` as top-level pins. |
| [`gain_cell_2t.layout.json`](gain_cell_2t.layout.json) | `klt gen-compose` response for `gain_cell_2t.gds` -- placement/routing/port record. |
| [`gain_cell_2t.lvs_reference.spice`](gain_cell_2t.lvs_reference.spice) | Hand-transcribed plain-element (schematic-equivalent) copy of `design/gain_cell_2t.spice`'s two devices, in the shape `klt lvs` requires (see "Informal DRC/LVS iteration" below). A check fixture, not a second design source. |
| [`gain_cell_2t.lvs.request.json`](gain_cell_2t.lvs.request.json) | `klt lvs` request comparing `gain_cell_2t.gds` against `gain_cell_2t.lvs_reference.spice`. |
| [`gain_cell_2t.drc.result.json`](gain_cell_2t.drc.result.json), [`gain_cell_2t.extract.spice`](gain_cell_2t.extract.spice) / [`.json`](gain_cell_2t.extract.json), [`gain_cell_2t.lvs.result.json`](gain_cell_2t.lvs.result.json) | Captured results of the informal `klt drc`/`klt extract`/`klt lvs` iteration used to get this geometry right -- see below. Informal evidence, not a formal sign-off record. |
| [`gain_cell_2t.extract.parasitics.spice`](gain_cell_2t.extract.parasitics.spice) / [`.json`](gain_cell_2t.extract.parasitics.json) | Issue #7: post-layout first-order lumped RC parasitics extraction (`klt extract --parasitics --critical-net sn`) against this GDS, feeding the extracted `2T-min` storage-node capacitance (`C_SN`) used in [`sim/retention/derive_retention.py`](../sim/retention/derive_retention.py)'s retention-time re-derivation. Not part of the informal DRC/LVS iteration below (a separate, later extraction run against the same committed geometry). |

## Topology mapping: exactly #14's 2T schematic, no extra devices

`gain_cell_2t.gds`'s top cell (`gain_cell_2t_layout_0`) draws exactly the two
`sky130_fd_pr__nfet_01v8` devices `design/gain_cell_2t.sch` declares, same
connectivity, same sizing (W=0.42 um, L=0.15 um) -- built from two `klt gen
mos_array` unit devices (`U0`, `U1`), not a hand-drawn or one-off layout:

| Schematic device (#14) | Layout instance | Gate | Drain | Source | Body |
|---|---|---|---|---|---|
| `M_WR` (write-access) | `mos_array` unit `U0` | `wl` | `sn` | `bl` | `GND` (via the tap block) |
| `M_RD` (read) | `mos_array` unit `U1` | `sn` | `rbl` | `rwl` | `GND` (via the tap block) |

No third device is drawn -- this is the ratified `2T-min` topology per
[`spec/retention-refresh-budget.md`](../spec/retention-refresh-budget.md)
Section 6, not the 3T alternative that section explicitly declines to adopt
as baseline. `klt extract --deck sky130` against `gain_cell_2t.gds` confirms
`device_count: 2`, both class `nfet`:

```
$ klt extract gain_cell_2t.gds --deck sky130 --top gain_cell_2t_layout_0 -o gain_cell_2t.extract.spice
.SUBCKT gain_cell_2t_layout_0 GND bl rbl rwl sn wl
M$1 sn wl bl GND nfet L=0.15U W=0.42U AS=0.1974P AD=0.1974P PS=1.78U PD=1.78U
M$2 rbl sn rwl GND nfet L=0.15U W=0.42U AS=0.1974P AD=0.1974P PS=1.78U PD=1.78U
.ENDS gain_cell_2t_layout_0
```

`M$1`'s `d/g/s/b` = `sn/wl/bl/GND` and `M$2`'s `d/g/s/b` = `rbl/sn/rwl/GND`
match `design/gain_cell_2t.spice`'s `XM_WR sn wl bl GND ...` / `XM_RD rbl sn
rwl GND ...` node-for-node (`sn` is `M_WR`'s drain **and** `M_RD`'s gate in
both the schematic and this extraction, exactly the "gain" connection
[`design/README.md`](../design/README.md) describes). Both devices'
`b` (body) terminal resolves to the real net `GND`, matching the schematic's
explicit `body=GND` on both instances -- sky130's curated deck otherwise ties
an un-tapped NMOS body to a synthesized global substrate net rather than a
named one (see `klt extract`'s own "NMOS body" documentation in
[2AMLogic/klayout-tools](https://github.com/2AMLogic/klayout-tools/blob/main/docs/cli/extract.md)),
which is exactly why `generate.sh` composes a P-substrate tap
(`gain_cell_2t_tap.gds`, `add_well=false`) alongside the two transistors and
labels it `GND`.

`sn` (the storage node) is **not** promoted as a top-level pin here either --
consistent with `design/gain_cell_2t.sch`'s own choice (see that schematic's
"Node naming": no hierarchical port for `sn`, matching real silicon, where
the storage node has no accessible pin). `klt extract`'s default behaviour
promotes every top-level-labelled net to a `.SUBCKT` pin regardless
(`sn` included, above) -- a layout-tool-level difference from the schematic's
own pin list, not a topology difference; every *device* connection is
unchanged.

## Bill of devices / layers (informational)

`gain_cell_2t.gds`'s bounding box is `5.42 x 1.84` um -- a `mos_array` block
(`U0`/`U1`, `2.58 x 1.24` um) placed beside a `guard_ring` substrate-tap
block (`1.84 x 1.84` um), 1.0 um apart, per
[`gain_cell_2t.layout.request.json`](gain_cell_2t.layout.request.json)'s
`placement.strategy: "row"`. This is a single bitcell in isolation, not an
array cell with a shared tap row -- array/periphery integration (sharing one
tap ring across many bitcells) was explicitly out of scope for *this*
issue (see `design/README.md`'s own "What's out of scope here", items 2-7 of
the #13 gap tracker). A first, proof-of-technique shared-tap array built
from this same ratified cell now exists (issue #34, "Array (issue #34)"
below) -- see that section for how the shared tap changes this picture; full
macro-level array/periphery integration remains out of scope here.

## Regenerating the layout

Requires `klt` (klayout-tools) on `PATH` and a resolvable sky130A PDK (same
pin as `design/`'s -- see [`design/pdk.json`](../design/pdk.json)):

```bash
# 1. Install/enable the pinned PDK commit (skip if already enabled) and
#    export PDK_ROOT/PDK:
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b
source design/env.sh

# 2. Regenerate every layout/*.gds/*.json artifact in place:
./layout/generate.sh

# 3. Check-only mode: regenerate into a scratch directory and assert
#    DRC-clean + LVS-match, without touching the committed files:
./layout/generate.sh --check
```

`generate.sh` runs, in order: `klt gen mos_array` (the two transistors),
`klt gen guard_ring` (the substrate tap), `klt gen-compose` (placement +
routing + pin labelling), then the informal `klt drc`/`klt extract`/`klt lvs`
iteration below -- failing loudly (nonzero exit) if DRC is not `clean` or LVS
is not `match`, so "reproducible from sources" is a checkable fact here too,
the same spirit as `design/regen_netlist.sh --check`'s staleness gate (though
not a byte-for-byte diff: a GDSII stream embeds a generation timestamp per
the format's own spec, so unlike `design/gain_cell_2t.spice`'s plain-text
netlist, a fresh `gain_cell_2t.gds` is not expected to diff byte-identical
against the committed one -- DRC/LVS status is the reproducibility gate
instead).

### Manual visual verification

Open the committed layout directly in KLayout to confirm the topology above
by eye (device count, gate/source/drain routing, the `sn` connection from
`M_WR`'s drain to `M_RD`'s gate):

```bash
klayout layout/gain_cell_2t.gds
```

## Informal DRC/LVS iteration (not a formal sign-off)

Per this issue's non-goals, the results below are the informal iteration
used to get this geometry right -- not a formally reported, signed-off
verification pass (that is a separate, later T1 item). Captured by
`generate.sh`, reproducible via `./layout/generate.sh --check`:

- **`klt drc --deck sky130`**
  ([`gain_cell_2t.drc.result.json`](gain_cell_2t.drc.result.json)): `status:
  "clean"`, `violation_count: 0`.
- **`klt extract --deck sky130`**
  ([`gain_cell_2t.extract.json`](gain_cell_2t.extract.json) /
  [`.spice`](gain_cell_2t.extract.spice)): `device_count: 2`, both `nfet`,
  connectivity as shown above.
- **`klt lvs`**
  ([`gain_cell_2t.lvs.result.json`](gain_cell_2t.lvs.result.json)) against
  [`gain_cell_2t.lvs_reference.spice`](gain_cell_2t.lvs_reference.spice) (a
  plain-element transcription of `design/gain_cell_2t.spice`'s two devices,
  in the schematic-equivalent shape `klt lvs` requires -- see that file's own
  header comment for why a transcription is needed rather than comparing
  against `design/gain_cell_2t.spice` directly): `status: "match"`,
  `devices: 2/2 matched`, `nets: 6/6 matched`. The nonzero `mismatch_count:
  2` is two `severity: "warning"` `topology` entries for the deck's
  always-registered-but-unused `pfet` device class (this bitcell is
  NMOS-only) -- the same known, non-blocking quirk
  [2AMLogic/klayout-tools' own worked example](https://github.com/2AMLogic/klayout-tools/blob/main/examples/design-pipeline/README.md)
  documents, not a real mismatch.

## Post-layout storage-node parasitic extraction (issue #7)

Not part of the informal DRC/LVS iteration above -- a separate, later
extraction run against the same committed `gain_cell_2t.gds`, feeding
`sim/retention/derive_retention.py`'s retention-time re-derivation:

```
$ klt extract layout/gain_cell_2t.gds --deck sky130 \
    --top gain_cell_2t_layout_0 --parasitics --critical-net sn \
    -o layout/gain_cell_2t.extract.parasitics.spice --format json \
    > layout/gain_cell_2t.extract.parasitics.json
```

Verified against the locally installed `klt 0.3.0` as of 2026-08-25 --
matches the flags documented in
[docs/cli/extract.md](https://github.com/2AMLogic/klayout-tools/blob/main/docs/cli/extract.md)
in 2AMLogic/klayout-tools, no discrepancy to file. `--parasitics` adds one
series R + one ground C per net (from the deck's curated sheet-resistance/
capacitance table); `--critical-net sn` additionally scopes the lateral
(same-layer sidewall) coupling-capacitance pass onto the storage node,
since `sn` couples to the adjacent `bl`/`rwl` routing. The storage node
`sn`'s reported parasitics
([`gain_cell_2t.extract.parasitics.json`](gain_cell_2t.extract.parasitics.json)'s
`parasitics.nets[]` entry for `sn`):

| Component | Value |
|---|---|
| Ground capacitance (junction + overlap + routing-to-substrate) | 0.586490 fF |
| Lateral coupling to `bl` | 0.010710 fF |
| Lateral coupling to `rwl` | 0.008154 fF |
| **Total `C_SN` (extracted)** | **0.605354 fF** |
| Series resistance (star, both device terminals) | 170.3519 Ω |

See [`sim/retention/README.md`](../sim/retention/README.md) "Storage-node
capacitance" for how this total feeds the retention-time re-derivation.

## klayout-tools friction encountered

None blocking. `klt gen`/`klt gen-compose` (headless PCell generation +
placement/routing, see
[docs/cli/gen.md](https://github.com/2AMLogic/klayout-tools/blob/main/docs/cli/gen.md)
/
[docs/cli/gen-compose.md](https://github.com/2AMLogic/klayout-tools/blob/main/docs/cli/gen-compose.md)
in that repo) covered this two-transistor cell's geometry capture directly --
no hand-drawn polygons were needed. Two non-blocking rough edges worth
recording here for context (neither filed against klayout-tools: both are
already-documented, expected behaviour of shipped features, not gaps):

- `gen-compose`'s router rejects a same-block self-net (here, `sn`: `M_WR`'s
  drain to `M_RD`'s gate, both unit ports of the *same* `mos_array` block)
  on the base metal layer, since the Manhattan backbone would cross the
  intervening unit's own pad and draw a silent short -- resolved by routing
  that one net on a second metal level via `routing.cross_block_layer_role`
  (documented under gen-compose.md's "Cross-block bus routing"), not by
  filing anything.
- `klt lvs` requires the plain-element (schematic-equivalent) netlist form;
  `design/gain_cell_2t.spice` is in the simulation (X-card subcircuit-call)
  form with its `.subckt`/`.ends` wrapper deliberately commented out (`sn`
  has no external pin), so a hand-transcribed
  [`gain_cell_2t.lvs_reference.spice`](gain_cell_2t.lvs_reference.spice) was
  written for this comparison instead -- the same pattern
  klayout-tools' own worked example
  ([`examples/design-pipeline/07-reference.spice`](https://github.com/2AMLogic/klayout-tools/blob/main/examples/design-pipeline/07-reference.spice))
  already uses for exactly this reason, documented in `klt lvs`'s own
  "Netlist form" section rather than a surprise.

**Issue #7 (post-layout parasitics extraction) update**: no friction. `klt
extract --parasitics --critical-net sn` (see "Post-layout storage-node
parasitic extraction" above) behaved exactly as documented in
`docs/cli/extract.md` -- flag names, JSON `parasitics` block shape, and the
per-net ground/coupling capacitance breakdown all matched with no surprises.
Nothing filed against 2AMLogic/klayout-tools for this step.

## Array (issue #34): a shared-tap N_ROWS x N_COLS bitcell array

A second layout artifact, built from the **same** ratified 2T-min bitcell
above, replicated into a shared-tap array -- the first step of #24's item 1
("Array") toward a Chipalooza-submittable macro. This is a
**proof-of-technique increment, not a macro-sized array**: it demonstrates
that a shared substrate tap and per-row/per-column bus routing compose
cleanly from the same ratified device, at a size chosen to exercise that
technique -- it is explicitly **not** a ratification of
[`spec/retention-refresh-budget.md`](../spec/retention-refresh-budget.md)
Section 7's `N_rows`/`t_row_refresh_op` (that section states plainly neither
is ratified "until an array/periphery design lands" -- this is that design's
first increment, not its sign-off). Sense amplifier, refresh controller, SPI
interface, and formal macro-level DRC/LVS sign-off (#24 items 2-5) are all
still out of scope here.

### What's here

| File | Purpose |
|---|---|
| [`array_topology.py`](array_topology.py) | Single source of truth for the array's net map (row/column buses, per-cell `sn`), consumed by both the `klt gen-compose` request and the generated LVS reference netlist below -- so those two artifacts can never silently drift apart. Run standalone (`python3 array_topology.py --help`) or via `generate_array.sh`. |
| [`generate_array.sh`](generate_array.sh) | Regenerates every `gain_cell_2t_array*` artifact from `design/gain_cell_2t.spice`'s topology, mirroring [`generate.sh`](generate.sh)'s pattern (`klt gen mos_array` -> `klt gen-compose` -> `klt drc`/`extract`/`lvs`). `--check` reruns into a scratch directory and asserts DRC-clean + LVS-match without touching committed files. `N_ROWS`/`N_COLS` env vars override the default `4x4` (verified sizes: `2x2` and `4x4` -- see "Array dimensions" below). |
| [`gain_cell_2t_array_mos.gds`](gain_cell_2t_array_mos.gds) / [`.json`](gain_cell_2t_array_mos.json) | The intermediate `klt gen mos_array` block: all `2 * N_ROWS * N_COLS` transistors on one uniform grid, `add_guard_ring=true` -- **one** shared substrate tap ring around the whole array (contrast with the single-cell layout's own per-cell tap, "Bill of devices/layers" above). |
| [`gain_cell_2t_array.layout.request.json`](gain_cell_2t_array.layout.request.json) | `klt gen-compose` request generated by `array_topology.py --emit compose-request`: places the one `mos_array` block and routes every `wl_<r>`/`rwl_<r>`/`bl_<c>`/`rbl_<c>`/`sn_<r>_<c>` net. |
| [`gain_cell_2t_array.layout.json`](gain_cell_2t_array.layout.json) | `klt gen-compose` response for `gain_cell_2t_array.gds` -- placement/routing/port record; `unrouted_nets: []`. |
| [`gain_cell_2t_array.gds`](gain_cell_2t_array.gds) | The array layout -- the top cell (`gain_cell_2t_array_<R>x<C>_layout_0`) this issue delivers. |
| [`gain_cell_2t_array.lvs_reference.spice`](gain_cell_2t_array.lvs_reference.spice) | **Generated** (not hand-transcribed) plain-element LVS reference netlist -- `array_topology.py --emit lvs-reference` mechanically replicates `design/gain_cell_2t.spice`'s two-device subcircuit `N_ROWS x N_COLS` times with the same row/column bus net renaming the compose request uses, mirroring [`design/regen_netlist.sh`](../design/regen_netlist.sh)'s and [`gain_cell_2t.lvs_reference.spice`](gain_cell_2t.lvs_reference.spice)'s own precedent (a generated/transcribed check fixture, never a second hand-authored design source). Carries a sha256 provenance header against `design/gain_cell_2t.spice`, same convention as `design/gain_cell_2t.spice`'s own header. |
| [`gain_cell_2t_array.lvs.request.json`](gain_cell_2t_array.lvs.request.json), [`gain_cell_2t_array.drc.result.json`](gain_cell_2t_array.drc.result.json), [`gain_cell_2t_array.lvs.result.json`](gain_cell_2t_array.lvs.result.json) | Captured results of the informal `klt drc`/`klt lvs` iteration -- see below. Informal evidence, not a formal macro-level sign-off record (that is #24 item 5). |

### Array dimensions chosen, and why

`generate_array.sh` defaults to **`N_ROWS=4, N_COLS=4`** (32 transistors, 16
bitcells). This repo verified the technique at two sizes during this issue:

- **`2x2`** first, to validate the shared-tap + bus-routing mechanism with
  the smallest non-trivial case (every row/column bus still has 2 distinct
  endpoints, i.e. is a genuine multi-cell shared net, not a single pin).
- **`4x4`** next (`N_ROWS=2 N_COLS=2 ./layout/generate_array.sh --check` and
  the default `./layout/generate_array.sh --check` both pass as of this
  commit), chosen as the **committed** size because it is the larger of the
  two sizes issue #34's own implementation guidance suggested prototyping,
  and because it exercises a genuine 4-endpoint bus per row/column (not just
  2), a materially stronger proof that the technique -- not merely a
  2-cell special case -- generalizes.

Neither size is a macro-level commitment: `spec/retention-refresh-budget.md`
Section 7 explicitly defers ratifying `N_rows`/`t_row_refresh_op` to a later
array/periphery design pass, and this issue's own non-goals exclude that
ratification. `4x4` is a size chosen to be checkable in one CI-speed `klt
drc`/`klt lvs` iteration, nothing more.

### Topology mapping

Every bitcell (row `r`, column `c`) is exactly the single-cell layout's own
`M_WR`/`M_RD` pair (same device sizing, same connectivity shape), replicated
onto a `rows=N_ROWS, cols=2*N_COLS` `mos_array` grid (`topology="array"`,
row-major unit numbering): grid column `2*c` is `M_WR`, grid column `2*c+1`
is `M_RD` (unit index `idx = r*(2*N_COLS) + grid_col`) -- see
`array_topology.py`'s `mos_idx()`. This is the single-cell `mos_array`
shape (`cols=2`, `U0`=`M_WR`, `U1`=`M_RD`) tiled `N_ROWS x N_COLS` times, not
a new indexing scheme.

| Net | Connects | Shared across |
|---|---|---|
| `wl_<r>` | every `M_WR` gate in row `r` | every column `c` in that row |
| `rwl_<r>` | every `M_RD` source in row `r` | every column `c` in that row |
| `bl_<c>` | every `M_WR` source in column `c` | every row `r` in that column |
| `rbl_<c>` | every `M_RD` drain in column `c` | every row `r` in that column |
| `sn_<r>_<c>` | that one bitcell's `M_WR` drain to its own `M_RD` gate | nothing -- per-cell, internal |
| `GND` | the shared tap ring's `TAP_W` port | the whole array (one ring, not one tap per cell) |

`sn_<r>_<c>` is **not** promoted as a top-level pin (no `pins[]` entry) --
matching `design/gain_cell_2t.sch`'s and the single-cell layout's own
convention for `sn` ("Topology mapping" above). `klt gen-compose` still
labels every routed `connectivity[]` net (including `sn_<r>_<c>`) with its
net name, and `klt extract`'s default behaviour promotes every labelled net
to a `.SUBCKT` pin regardless -- the same layout-tool-level (not
topology-level) quirk already documented above for the single cell, not new
here. Every device's body terminal resolves to the real net `GND` via the
one shared tap ring, the same check "Topology mapping" above performs for
the single cell's own dedicated tap.

### Bill of devices/layers (informational, `4x4`)

`gain_cell_2t_array.gds`'s bounding box is `13.66 x 8.30` um (`bbox_um`
`{-1.07, -1.07}` to `{12.59, 7.23}`) -- one `mos_array` block (32 transistors
on a uniform grid, `add_guard_ring=true`) with its own shared tap ring drawn
around it. `klt extract --deck sky130` confirms `device_count: 32`, all
class `nfet`, matching `2 * N_ROWS * N_COLS = 2*4*4 = 32`.

### Regenerating the array layout

Same prerequisites as the single-cell layout above (`klt` on `PATH`,
`source design/env.sh`):

```bash
# Regenerate every gain_cell_2t_array* artifact in place (default 4x4):
./layout/generate_array.sh

# Check-only mode (scratch dir, does not touch committed files):
./layout/generate_array.sh --check

# A different array size (only 2x2/4x4 verified as of this commit):
N_ROWS=2 N_COLS=2 ./layout/generate_array.sh --check
```

### Informal DRC/LVS iteration (not a formal sign-off), `4x4`

Same informal bar as the single-cell layout above -- not a formally
reported, signed-off verification pass (#24 item 5):

- **`klt drc --deck sky130`**
  ([`gain_cell_2t_array.drc.result.json`](gain_cell_2t_array.drc.result.json)):
  `status: "clean"`, `violation_count: 0`.
- **`klt lvs`**
  ([`gain_cell_2t_array.lvs.result.json`](gain_cell_2t_array.lvs.result.json))
  against the generated
  [`gain_cell_2t_array.lvs_reference.spice`](gain_cell_2t_array.lvs_reference.spice):
  `status: "match"`, `devices: 32/32 matched`, `nets: 33/33 matched`. The
  nonzero `mismatch_count: 2` is the same two `severity: "warning"`
  `topology` entries for the deck's always-registered-but-unused `pfet`
  device class already documented above for the single cell -- not a real
  mismatch, not new to the array.

### klayout-tools friction encountered

Real friction this time, but **already tracked upstream** -- nothing new
filed against [2AMLogic/klayout-tools](https://github.com/2AMLogic/klayout-tools):

- Routing the four `wl_<r>`/`rwl_<r>`/`bl_<c>`/`rbl_<c>` buses plus every
  per-cell `sn_<r>_<c>` net in one `gen-compose` call, all as same-block
  self-nets on one `mos_array` block, hit exactly the two gaps
  [2AMLogic/klayout-tools#1467](https://github.com/2AMLogic/klayout-tools/issues/1467)
  ("no track or layer assignment between nets, so the first routed net
  rejects the rest") and
  [2AMLogic/klayout-tools#1531](https://github.com/2AMLogic/klayout-tools/issues/1531)
  ("`mos_array`'s own multi-row/column footprint blocks routing to interior
  unit pins") already describe -- both closed (`completed`) the same day
  this issue was built, independently of this repo's own work. Naively
  routing the buses and every `sn_<r>_<c>` together (any connectivity
  order, with or without `routing.cross_block_layer_role`) left some subset
  of `sn_<r>_<c>` nets `unrouted` (`crosses already-routed net '<bus>'`),
  or, once forced onto a caller-chosen path via `connectivity[].waypoints_um`
  to dodge that, tripped an `li1.space.1` `klt drc` violation against a
  neighbouring unit's own gate-contact landing pad -- exactly the "single
  generator's own emitted geometry making some of its own declared pins
  structurally unreachable" and "no track assignment between nets"
  symptoms those two issues already document.
- **Workaround used** (matches the workaround pattern those issues
  describe, not a new technique): route the four bus types first, left to
  `gen-compose`'s own automatic same-block routing (every bus composed
  cleanly with no explicit help, at both `2x2` and `4x4`); route each
  per-cell `sn_<r>_<c>` net **last**, with one explicit
  `connectivity[].waypoints_um` point (`M_WR`'s own drain x + a small fixed
  clearance, `M_RD`'s own gate y -- see `array_topology.py`'s
  `SN_WAYPOINT_X_OFFSET_UM`) forcing a "rise, then jog" backbone shape that
  reaches `M_RD`'s gate without crossing the neighbouring unit's own pads or
  the already-routed buses. The `0.2um` offset was tuned by `klt drc`
  iteration (the smallest of a few tried values that cleared
  `li1.space.1`) -- `array_topology.py`'s own comment on that constant
  records this was not derivable from a value `klt gen-compose` exposes to
  a caller, itself an instance of the gap those two upstream issues
  describe.
