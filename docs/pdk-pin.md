# sky130 PDK version pin

Every schematic, netlist, layout, and testbench in this repo resolves the
sky130 PDK from the **same** `open_pdks`/`ciel` pin, and every recorded
simulation is produced by the **same pinned simulator major version**:

| Field | Value |
|---|---|
| `family` | `sky130` |
| `variant` | `sky130A` |
| `open_pdks_commit` | `f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7` |
| `install_command` | `pip install ciel==2.6.1` then `ciel enable --pdk-family sky130 -l sky130_fd_pr f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7` |
| default `PDK_ROOT` | `~/.ciel` |
| `simulator` | `ngspice-47` (major version; the batch fleet image's engine) |

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

The same argument covers the simulator row: the simulator produces every
committed number in `sim/` just as the PDK models do, and the two pins
are useless separately — a re-run at the pinned PDK on an unpinned
simulator (or vice versa) conflates the two changes. That is not
hypothetical: between ngspice-46 and ngspice-47, with the PDK revision
ruled out, the loaded-column characterization numbers moved up to
8.76e-02 V and -26% latency (issue #300) — larger than margins quoted in
`spec/operating-range-decision-PROPOSED.md` §5.3.

## Simulator pin (issue #300)

The simulator is pinned by **major version only** — `ngspice-47`, the
batch fleet image's engine — defined as `NGSPICE_VERSION_PIN` in
[`sim/_evidence_common.py`](../sim/_evidence_common.py) beside
`PDK_OPEN_PDKS_COMMIT`. The check parses the `ngspice-NN` token out of
the `ngspice --version` banner (`ngspice_version()` in the same module)
rather than comparing the full banner, so build options, compile dates
and banner formatting are not false mismatches. `ngspice_version()`
returning `"unknown"` (binary present but version unreadable) is a
mismatch, never a pass — a record cannot carry absent simulator
provenance and still satisfy the check. The check is surfaced from
`check_ngspice_available()`, the same entry point every runner already
calls for the PDK revision check, so no runner needed a new call site.

**A simulator-version change triggers re-qualification on the same terms
as a PDK re-pin**: new append-only records, supersession notes, no
in-place edits of existing records. Which studies' committed records
carry which simulator version, and which are awaiting re-qualification
under this pin, is inventoried in
[`docs/simulator-requalification-inventory.md`](simulator-requalification-inventory.md).
There is no override flag: a re-qualification changes the pin constant,
exactly as the PDK re-pin did.

## Where it's consumed

**Python (canonical source):** [`sim/_evidence_common.py`](../sim/_evidence_common.py)
defines `PDK_OPEN_PDKS_COMMIT`, `DEFAULT_PDK_VARIANT` and
`NGSPICE_VERSION_PIN` once; every Python
script that needs the pin (`sim/leakage/run_leakage_sweep.py`,
`sim/bitcell-transient/run_bitcell_transient.py`,
`sim/retention/derive_retention.py`) imports them from there rather than
redefining its own copy. `resolve_pdk_root()` in the same module resolves
`PDK_ROOT` from an explicit CLI flag, else the `PDK_ROOT` environment
variable, else the `~/.ciel` default above — also shared by all three
scripts. `~/.volare` (the retired volare root) is never searched. The same
module's `pdk_revision_problems()` reads the resolved tree's
`<variant>/SOURCES` `open_pdks` line and `ngspice_version_problems()` the
simulator banner's major version; the env checks (`check_ngspice_available()`,
`derive_retention.py --check-env`) fail with a visible mismatch if either is
not the pin above (or `SOURCES` is missing, or the banner is unparsable), so
a stray tree at another revision — or a stray simulator major version —
cannot be used silently.

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

## Mismatch (Monte Carlo) sections

The same `libs.tech/combined/sky130.lib.spice` also ships mismatch-enabled
sections `tt_mm`, `ss_mm`, `ff_mm`, `sf_mm` and `fs_mm` (lines 730, 811,
784, 757, 838 at this pin), each setting `.param MC_MM_SWITCH=1`; the plain
corners above set it to `0`. The file's header comment lists only `tt_mm`,
`ss_mm`, `sf_mm`, `fs_mm`, but `ff_mm` exists. For `nfet_01v8`/`pfet_01v8`
the switch gates a per-instance Vth term only (`AGAUSS`, coefficients in
`continuous/models_global.spice`). The check, with line citations, is in
[`sim/sense-mismatch/README.md`](../sim/sense-mismatch/README.md) (issue #81).

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

### Re-pin to `f6eeac7` (issue #165)

The fleet moved sky130/gf180mcu from `c6d73a35f524070e85faff4a6a9eef49553ebc2b`
(installed with volare, whose release feed stopped in Aug 2025) to
`f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7`, installed with ciel 2.6.1; the default
`PDK_ROOT` moved from `~/.volare` to `~/.ciel`. Records produced under
`c6d73a3` (`sim/**/results/`, manifests/summaries, `layout/*.json` outputs,
"measured at" notes) are append-only and keep naming that revision; their
re-qualification and supersession marking are tracked in #166.
`sim/loaded-column/cold-corner/check_evidence_index.py` keeps `c6d73a3` as its
*evidence-era* constant (it validates the committed index) and skips its
installed-tree hash check when the installed PDK is a different revision.

### Simulator added to the pin set (issue #300)

The pin set grew from the PDK alone to PDK + simulator: `ngspice-47`
(`NGSPICE_VERSION_PIN`), checked from the same `check_ngspice_available()`
entry point as the PDK revision. Until this change the simulator was
stamped per result row but never pinned or checked, and committed
loaded-column numbers moved up to 8.76e-02 V between ngspice-46 and
ngspice-47 unnoticed (PDK revision ruled out at `sf`/125 C). Every
ngspice-46-stamped record is now awaiting re-qualification under the pin —
inventoried in
[`docs/simulator-requalification-inventory.md`](simulator-requalification-inventory.md).
