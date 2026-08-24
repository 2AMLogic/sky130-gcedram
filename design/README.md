# design

First design-sources increment (issue #14, T1 item 1 of the gap tracker,
#13): the 2T gain-cell bitcell schematic and its derived SPICE netlist.
Per [`docs/design-evidence-tiers.md`](https://github.com/2AMLogic/klayout-tools/blob/main/docs/design-evidence-tiers.md),
the pass condition is committed design sources **plus** a derived netlist
that is regenerated on design change -- presence and reproducibility, not a
one-off drop. This directory establishes that convention for the block; it
has no prior xschem usage to pattern-match against.

## What's here

| File | Purpose |
|---|---|
| [`gain_cell_2t.sch`](gain_cell_2t.sch) | xschem schematic: the ratified 2T gain-cell bitcell (see "Topology" below). |
| [`gain_cell_2t.spice`](gain_cell_2t.spice) | SPICE netlist **derived** from the schematic above via [`regen_netlist.sh`](regen_netlist.sh) -- not hand-written. Carries a provenance header (sha256 of the source `.sch`). |
| [`regen_netlist.sh`](regen_netlist.sh) | Regenerates the netlist from the schematic (`--check` verifies the committed netlist is not stale). This is the "reproducible on design change" mechanism. |
| [`xschemrc`](xschemrc) | Project-local xschem config: resolves the sky130 PDK's symbol library without depending on `~/.xschem`. |
| [`env.sh`](env.sh) | Exports `PDK_ROOT`/`PDK` for interactive `xschem` sessions and for `regen_netlist.sh`. |
| [`pdk.json`](pdk.json) | PDK version pin (same `open_pdks` commit as `sim/leakage/pdk.json`). |

## Topology: 2T, ratified

This is the **2T** gain-cell bitcell (`2T-min`), per
[`spec/retention-refresh-budget.md`](../spec/retention-refresh-budget.md)
Section 6 ("this macro's baseline bitcell topology is ratified as 2T
(`2T-min`)"). It is **not** 3T -- the schematic deliberately has no third,
dedicated read-access device between the read transistor's drain and the
read bitline (the classic 3T addition that spec Section 6 explicitly
declines to adopt as the baseline).

Two devices, both `sky130_fd_pr__nfet_01v8` (the sky130 core 1.8 V NMOS --
no other `sky130_fd_pr` flavour appears anywhere in this schematic):

| Device | Gate | Drain | Source | Body | Sizing |
|---|---|---|---|---|---|
| `M_WR` (write-access) | `wl` | `sn` | `bl` | GND | W=0.42 µm, L=0.15 µm |
| `M_RD` (read) | `sn` | `rbl` | `rwl` | GND | W=0.42 µm, L=0.15 µm |

`M_WR`'s geometry is **identical, not merely similar**, to the access
device already measured in
[`sim/leakage/tb_access_leakage.spice.tmpl`](../sim/leakage/tb_access_leakage.spice.tmpl)
(W=0.42 µm, L=0.15 µm, the minimum drawn size the shipped model supports --
see [`sim/leakage/README.md`](../sim/leakage/README.md) "Device choice").
This is a deliberate reuse, not a fresh/independent sizing choice: it keeps
this schematic's write-access device the same physical device the
retention/refresh evidence chain
([`spec/retention-refresh-budget.md`](../spec/retention-refresh-budget.md))
already characterized, so capturing this schematic does not imply or
require a new leakage re-derivation.

`M_RD`'s sizing reuses the same minimum geometry as a first-pass
placeholder. This is **not** yet driven by a read-current or sense-margin
analysis -- no sense-amplifier design exists yet in this repo (the same
pre-design caveat [`sim/retention/README.md`](../sim/retention/README.md)
already carries for its `C_SN`/`delta_V` assumptions). Read-path sizing is
out of scope for this issue and expected to be revisited once sense-amp
work begins.

## Node naming

Kept consistent with [`sim/leakage/README.md`](../sim/leakage/README.md)'s
bias-condition table, since downstream testbenches reference those exact
names:

- **`wl`** -- (write) wordline, gate of `M_WR`. Same name/role as the
  leakage testbench's `wl`.
- **`sn`** -- storage node, drain of `M_WR` / gate of `M_RD`. Same name as
  the leakage testbench's `sn`. **Intentionally not a hierarchical port** --
  it is a genuine internal 2-pin net in the schematic (no external pin),
  matching real silicon, where the storage node has no accessible pin.
- **`bl`** -- (write) bitline, source of `M_WR`. Same name as the leakage
  testbench's `bl`.
- **`rwl`, `rbl`** -- read wordline / read bitline, source/drain of `M_RD`.
  New names (the leakage testbench only exercises the write/access device
  in isolation, so it has no read-path nodes to match); the `r`-prefix
  keeps them unambiguous against `wl`/`bl` while staying in the same
  naming family.

## Wordline drive scheme: plain 1.8 V (not boosted)

Recorded explicitly, per the repo README's "Supply" row ("boosted wordline
is a design decision to record"): **this schematic assumes a plain 1.8 V
wordline** -- `wl` and `rwl` both swing 0 V / `VDD` (the sky130 standard
core rail), **not** a boosted-above-`VDD` scheme.

Consequence, stated rather than silently absorbed: an NMOS pass device
(`M_WR`) driven by a plain-`VDD` wordline can only pull the storage node up
to `VDD - Vgs(M_WR)`, a threshold-voltage drop below a full logic '1' --
confirmed by a DC operating-point smoke check against the shipped `tt`
corner model (`wl = bl = 1.8 V` yields `v(sn) ≈ 1.39 V`, i.e. roughly a
0.4 V drop, consistent with sky130's core NMOS `Vgs,th` plus overdrive at
this bias). This schematic does not attempt to compensate for that drop
(no charge pump / level-shifter is included) -- that is an open item for a
future write-margin analysis, not a claim that plain-`VDD` writing is
lossless. It does **not** change any already-ratified retention number:
[`spec/retention-refresh-budget.md`](../spec/retention-refresh-budget.md)'s
worst-case leakage/retention chain evaluates the storage node held at a
full `VDD` (a written logic '1'), independent of how that level got
written.

## Regenerating the netlist

Requires a stock `open_pdks` sky130 install (via `volare`, pinned in
[`pdk.json`](pdk.json)) and `xschem` on `PATH`.

```bash
# 1. Install/enable the pinned PDK commit (skip if already enabled):
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b

# 2. Export PDK_ROOT / PDK (defaults to ~/.volare / sky130A if unset):
source design/env.sh

# 3. Regenerate design/gain_cell_2t.spice from design/gain_cell_2t.sch:
./design/regen_netlist.sh

# 4. Verify the committed netlist is not stale relative to the schematic
#    (no diff => reproducible; this is the check to run in CI/pre-merge):
./design/regen_netlist.sh --check
```

`regen_netlist.sh` also fails if any device instance in the regenerated
netlist resolves to a `sky130_fd_pr` flavour other than `nfet_01v8` -- a
deliberate deviation from the leakage study's device choice would need
this check updated alongside a PR description explicitly calling it out,
per this issue's acceptance criteria.

Interactive editing:

```bash
source design/env.sh
xschem --rcfile design/xschemrc design/gain_cell_2t.sch
```

## What's out of scope here

Per this issue's non-goals: layout, DRC/LVS, PVT corner sweeps of the full
cell, sense-amplifier design, and array/periphery integration are all
follow-on increments (items 2-7 of the #13 gap tracker) once these design
sources exist. This directory is schematic-capture + netlist-derivation
only.
