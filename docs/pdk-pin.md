# sky130 PDK version pin

Every schematic, netlist, layout, and testbench in this repo resolves the
sky130 PDK from the **same** `open_pdks`/`volare` pin:

| Field | Value |
|---|---|
| `family` | `sky130` |
| `variant` | `sky130A` |
| `open_pdks_commit` | `c6d73a35f524070e85faff4a6a9eef49553ebc2b` |
| `install_command` | `volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b` |
| default `PDK_ROOT` | `~/.volare` |

## Why one pin, everywhere

`design/`, `sim/leakage/`, `sim/bitcell-transient/`, and `sim/retention/`
deliberately share this exact pin, not just a compatible one:

- `sim/bitcell-transient/` cross-checks its transient hold decay against the
  DC leakage numbers recorded in
  [`sim/leakage/results/leakage_results.csv`](../sim/leakage/results/leakage_results.csv);
  a divergent PDK pin between the two testbenches would silently invalidate
  that comparison.
- `design/`'s schematic and its derived netlist
  ([`design/gain_cell_2t.spice`](../design/gain_cell_2t.spice)) must resolve
  against the exact shipped model set the retention/refresh evidence chain
  ([`spec/retention-refresh-budget.md`](../spec/retention-refresh-budget.md))
  was measured against — CLAUDE.md's "Retention claims carry their evidence
  chain" requirement depends on that consistency holding.
- This is also, incidentally, the same pin used across 2AMLogic's sibling
  repos (e.g. `sky130-ldo`, `sky130-bandgap`) — no reason for a
  device-level study on this PDK to diverge from the rest of the fleet's
  pin.

## Where it's consumed

**Python (canonical source):** [`sim/_evidence_common.py`](../sim/_evidence_common.py)
defines `PDK_OPEN_PDKS_COMMIT` and `DEFAULT_PDK_VARIANT` once; every Python
script that needs the pin (`sim/leakage/run_leakage_sweep.py`,
`sim/bitcell-transient/run_bitcell_transient.py`,
`sim/retention/derive_retention.py`) imports them from there rather than
redefining its own copy. `resolve_pdk_root()` in the same module resolves
`PDK_ROOT` from an explicit CLI flag, else the `PDK_ROOT` environment
variable, else the `~/.volare` default above — also shared by all three
scripts.

**Shell/Tcl (design-side mirror):** [`design/env.sh`](../design/env.sh) and
[`design/xschemrc`](../design/xschemrc) restate the same `PDK_ROOT`/`PDK`
defaults for interactive `xschem` use and `design/regen_netlist.sh`. Shell
and Tcl cannot `import` a Python module, so this is the one duplication this
repo cannot eliminate — keep it in sync with the table above by hand if the
pin ever changes. Both files reference this document in a comment so the
sync obligation is discoverable at the point of edit.

## Process corners and temperature grid

`sim/leakage/` and `sim/bitcell-transient/` additionally sweep the same PVT
grid (each script keeps its own `DEFAULT_CORNERS`/`DEFAULT_TEMPS_C`
constants — small, testbench-local defaults rather than shared config, since
each script's CLI already exposes `--corners`/`--temps-c` overrides):

- **Process corners**: `tt`, `ss`, `ff`, `sf`, `fs` — the five MOS process
  corners in the shipped `libs.tech/combined/sky130.lib.spice` for the
  pinned commit above.
- **Temperature**: `-40`, `27`, `125` °C — the grid named in the shipped
  `libs.tech/irsim/sky130A_*_{n40,27,125}.prm` corner files, matching the
  `-40..125 °C` range 2AMLogic/sky130-bandgap's ratified spec uses for
  temperature-corner claims.

## History

Before issue #37, this pin was hand-duplicated across seven independent
locations: three `pdk.json` files (`design/pdk.json`,
`sim/leakage/pdk.json`, `sim/bitcell-transient/pdk.json` — pure
documentation, never read by any script), `sim/_evidence_common.py`, the
shell/Tcl defaults in `design/env.sh`/`design/xschemrc`, and two
per-testbench `DEFAULT_PDK_VARIANT` constants (plus a third, unused, in
`sim/retention/derive_retention.py`). The `pdk.json` files were deleted and
their rationale folded into this document; the Python-side constants were
collapsed into the single `sim/_evidence_common.py` source above. The
pinned values themselves were not changed by that consolidation.
