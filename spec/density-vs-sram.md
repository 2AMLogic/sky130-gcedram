# Density vs 6T SRAM: area per bit of the committed 4x4 array (issue #97)

**Status: evidence write-up, not a ratified spec change.** No ratified value
in [`retention-refresh-budget.md`](retention-refresh-budget.md) is edited and
the README requirement is not relaxed. It fills the comparison that document
deferred (its Section 8, "Density vs SRAM comparison").

> **Refreshed 2026-10-28 (issue #252).** Sections 1-7 and the addendum's
> baseline column now quote the post-#244 layout (klt 0.8.0 generators), from
> [`layout/results/density_20261028_v244.json`](../layout/results/density_20261028_v244.json).
> The superseded pre-#244 figures are kept only as history in
> [`density-inputs-refresh-PROPOSED.md`](density-inputs-refresh-PROPOSED.md)
> (PROPOSED, not ratified). The conclusion is unchanged in sign; the 2T cell
> got larger relative to the quoted SRAM cell.

## 1. Result, stated plainly

**The 2T cell as drawn does not beat the public 6T SRAM bitcell on area.** It
is about **2.8x larger** at the drawn-cell level and about **4.1x larger** at
the 4x4 array level (ring included), against the SRAM-rule comparator.
The README requirement ("must beat a 6T SRAM bitcell on area to justify
existing") is therefore **unmet** by the current layout. Consequence filed as
decision issue [#100](https://github.com/2AMLogic/sky130-gcedram/issues/100);
the requirement and the ratified 2T decision are untouched.

## 2. Reproduction

```bash
python3 -I layout/area_density.py          # writes layout/results/density_<date>.json
python3 -I layout/area_density.py --tag v244 --issue 244   # post-#244 result (see below)
```

Stdlib only; reads `layout/gain_cell_2t_array.layout.json`,
`layout/gain_cell_2t_array_mos.json` and `layout/gain_cell_2t_array.gds`
(extents cross-check; sha256 of all three recorded in the result). It does
not invoke `klt`, ngspice or any host tool. klt on the host when the result
was written: `klt 0.7.0+gb82427b30c96`; for the post-#244 result it was
`klt 0.8.1.dev522+g7c3bcd3cc4d8` (both recorded for provenance only). The
array GDS may change when #91 is resolved; if so re-run into a **new** result
file (`--tag`). Result files are never overwritten (the script refuses), and
the committed file is listed in `sim/append_only_inventory.txt` so
`sim/check_append_only.py` protects it. Committed result:
[`layout/results/density_20261028_v244.json`](../layout/results/density_20261028_v244.json)
(post-#244, current); the 2026-10-09 file
[`density_20261009.json`](../layout/results/density_20261009.json) is the
superseded pre-#244 result and stays committed as append-only evidence.

## 3. Measured from committed layout (three separate figures)

| Figure | Definition | Value |
|---|---|---|
| (a) drawn bitcell pitch area | pitch_x x pitch_y from the uniform device grid (2 nfets per cell, 2.98 um wide x 1.94 um tall) | **5.7812 um^2** |
| (b) array area per bit incl. shared tap | composed bbox 13.91 x 9.75 = 135.6225 um^2 / 16 bits (GDS extents match the JSON bbox) | **8.4764 um^2/bit** |
| (c) extrapolated macro area per bit | see Section 5; ASSUMPTION-driven | 6.42 - 11.56 um^2/bit (ring-free) |

Tap overhead: the one ring around the grid costs 43.1233 um^2 for 16 bits, a
fixed cost that shrinks per bit as the array grows, so (a) is the ring-free
limit and (b) a small-array worst case. A real macro needs periodic tap
rows/columns; their pitch is not designed and so is not modeled. The honest
bracket for the array fabric is therefore (a) to (b).

## 4. Public SRAM comparators (quoted-not-measured)

Nothing below was measured in this repo; each number is a LEF `SIZE` line in
a public file. Retrieved 2026-10-09.

| Cell | W x H (um) | Area (um^2) | Source |
|---|---|---|---|
| `sky130_fd_bd_sram__sram_sp_cell_opt1` (primary: the cell OpenRAM's sky130 port instantiates with `version="opt1"`) | 1.31 x 1.58 | **2.070** | [`cells/sram_sp_cell_opt1/...magic.lef`](https://github.com/google/skywater-pdk-libs-sky130_fd_bd_sram), commit `be33adbc` (2021-10-20); OpenRAM [`technology/sky130/custom/sky130_bitcell.py`](https://github.com/VLSIDA/OpenRAM/blob/stable/technology/sky130/custom/sky130_bitcell.py), latest release v1.2.48 (2024-01-21) |
| `sky130_fd_bd_sram__openram_sp_cell` (smaller same-family variant) | 1.20 x 1.58 | 1.896 | same repo/commit, `cells/openram_sp_cell/...magic.lef` |

| Ratio (2T / SRAM) | vs 2.070 | vs 1.896 |
|---|---|---|
| (a) drawn pitch area | 2.793x | 3.049x |
| (b) 4x4 array with ring | 4.095x | 4.471x |

**Process-rule caveat.** These bitcells use SRAM-specific (foundry "push")
design rules; the 2T gain cell is drawn in plain logic rules, so this is not
a like-for-like comparison and flatters the SRAM. The issue asked for a
logic-rule 6T comparator as a second, larger figure. **No public logic-rule
6T sky130 area was found that I could verify, so none is quoted.** Instead
the break-even is stated: a logic-rule 6T cell would have to exceed
**5.78 um^2** (drawn) / **8.48 um^2** (4x4 array) before the 2T cell wins;
that is 2.8x the SRAM-rule cell. Whether that is plausible is not asserted
here. The OpenRAM 1.2.48 docs were not found to quote a cell-area figure, so
no number is attributed to them beyond the cell-library file above.

## 5. Macro extrapolation (labelled assumption)

`macro area per bit = array area per bit / (1 - f)`, where `f` is the
fraction of macro area that is periphery (sense amps, row drivers, refresh
controller, decoders, routing). **`f` is an ASSUMPTION**: no periphery is
designed (epic #24). Nominal 0.30, swept 0.10 - 0.50:

| f | ring-free (a) um^2/bit | 4x4 with ring (b) um^2/bit |
|---|---|---|
| 0.10 | 6.42 | 9.42 |
| 0.20 | 7.23 | 10.60 |
| **0.30 (nominal)** | **8.26** | **12.11** |
| 0.40 | 9.64 | 14.13 |
| 0.50 | 11.56 | 16.95 |

The same `f` applies to an SRAM macro, so it largely cancels in the ratio;
the cell-level ratio (Section 4) is the fair headline. The gain-cell macro
additionally needs refresh control and a sense path on every read, so a
nominal `f` equal to SRAM's is if anything optimistic for the 2T macro. The
sweep does not change the sign of the result.

## 6. Not a drop-in SRAM replacement

A gain cell is dynamic. The ratified worst-case refresh bound is about
5.03 us ([`retention-refresh-budget.md`](retention-refresh-budget.md) Sections
5 and 7), so every row is rewritten thousands of times per millisecond and
that work competes with external access; see the refresh-cost envelope in
[`sim/refresh-overhead/README.md`](../sim/refresh-overhead/README.md). Area
parity, had it been achieved, would still have to be weighed against that
overhead. Here area parity is not achieved either, so on area alone the
macro currently has no advantage over SRAM at this node and rules.

## 7. Limits and honest context

- The array is a uniform `mos_array` grid composed by klt, not a hand-packed
  cell; its 2.98 x 1.94 um pitch is a generator artifact and a compaction
  study could reduce it. That is a follow-up, not a result here.
- The comparison is cell-to-cell; neither SRAM nor gain-cell periphery is
  designed.
- Literature-based gain-cell-vs-6T density claims at other nodes live in
  `ratification/market-key/comps/gcedram.md` and are not sky130 figures.

---

## Addendum (2026-10-15, issue #100): bitcell-compaction research

**Status: evidence, not a spec change.** The README requirement and
[`retention-refresh-budget.md`](retention-refresh-budget.md) are untouched
(operator ruling on [#100](https://github.com/2AMLogic/sky130-gcedram/issues/100):
keep the requirement, run bounded compaction research). Sections 1-7 above
are not edited; they describe the committed uniform-grid layout, which also
still stands. The topology is unchanged in every variant: two
`sky130_fd_pr__nfet_01v8`, W = 0.42 um, L = 0.15 um, `M_WR` gate = WL /
source = BL / drain = SN, `M_RD` gate = SN / drain = RBL / source = RWL.

### A.1 What was built

`klt gen mos_array` cannot be compacted by any parameter set: it places
isolated unit devices on a fixed grid and exposes no pitch, shared-diffusion
or mirror control (tool gap filed generically as
[klayout-tools#3299](https://github.com/2AMLogic/klayout-tools/issues/3299)).
The variants are therefore generated by
[`layout/compact/gen_compact.py`](../layout/compact/gen_compact.py) with
KLayout's Python API (no hand-drawn GDS; byte-reproducible, gated by
`layout/compact/generate.sh --check`). Two of the three permitted variants
were needed; the threshold was met by the second and no third was drawn.

| Variant | What changes | Drawn pitch (um) | Area (um^2) |
|---|---|---|---|
| baseline (committed, post-#244) | uniform `mos_array` grid | 2.98 x 1.94 | 5.7812 |
| `v1` | each device is its own vertical diffusion with the sky130 minimum S/D extension; WR stacked above RD in one column; the word line is one continuous poly line per row, the RD gate is a short poly riser to a landing pad beside the column | 0.985 x 1.98 | **1.950** |
| `v2` | `v1` plus vertical diffusion sharing: the two `M_WR` of a row pair share one BL contact, the two `M_RD` between two WR pairs share one RBL contact (stack for 4 rows: RD, WR pair, RD pair, WR pair, RD); each SN link is a short li1 jog | 0.985 x 1.42 (2-row period 2.84) | **1.399** |

Results: [`density_20261015_v1.json`](../layout/results/density_20261015_v1.json),
[`density_20261015_v2.json`](../layout/results/density_20261015_v2.json),
produced by `python3 -I layout/area_density.py --tag <v> --issue 100
--layout-json ... --mos-json ... --gds ...` (the same script and the same
three figures as Section 3; its default run still reproduces
`density_20261009.json` exactly).

### A.2 Against the quoted comparator (both figures reported, neither redefined)

The comparator is still the **quoted, not measured**
`sky130_fd_bd_sram__sram_sp_cell_opt1`, 2.070 um^2, SRAM-specific rules.

| | baseline | `v1` | `v2` |
|---|---|---|---|
| (a) drawn pitch area, um^2 | 5.7812 | 1.950 | **1.399** |
| (a) / 2.070 (opt1) | 2.793x | 0.942x | **0.676x** |
| (a) / 1.896 (openram_sp_cell) | 3.049x | 1.029x | 0.738x |
| (b) 4x4 array incl. tap ring, um^2/bit | 8.4764 | 3.451 | 2.842 |
| (b) / 2.070 | 4.095x | 1.667x | 1.373x |
| 4x4 core without ring, um^2/bit | 5.7812 | 1.901 | 1.485 |

Break-even per Section 4, restated for the best variant: a logic-rule 6T
cell would have to exceed **1.40 um^2** (drawn) for the compacted 2T cell to
win; that is below the quoted SRAM-rule cell itself. **The logic-rule 6T
comparison remains unresolved**: no public logic-rule 6T sky130 area was
verified, so none is quoted here, exactly as in Section 4.

Reading the numbers honestly:

- At the drawn-cell level `v2` meets the success threshold stated in #100
  (drawn pitch area <= 2.070 um^2); `v1` meets it narrowly. That is a
  cell-to-cell comparison between plain logic rules and SRAM-specific
  rules; it is the figure the README requirement is worded in, not proof
  that the requirement is satisfied in a macro.
- At the 4x4 array level including the one tap ring, `v2` is still 1.37x the
  comparator (the ring is a fixed 21.7 um^2 cost that shrinks per bit with
  array size; the ring-free 4x4 core is 1.485 um^2/bit, 0.086 above (a)
  because the two end RD devices have no mirrored partner). No periodic tap
  rows were drawn.
- With the Section 5 assumption (periphery fraction f, nominal 0.30, applied
  equally to SRAM) the ring-free macro figure for `v2` is 2.00 um^2/bit
  (0.965x of the comparator at the same f). f is an assumption and no
  periphery is designed.

### A.3 Rule status of the variants (what "clean" means here)

Each variant is checked by four independent engines, all committed beside
it in [`layout/compact/`](../layout/compact/) and re-run by
`generate.sh`: `klt drc --deck sky130` (clean), `klt lvs` against a
generated 32-device reference (match; 32/32 devices, 33/33 nets),
the `sky130A_mr.drc` KLayout runset shipped with the pinned PDK (0
violations), and the gate-level rules of the pinned PDK's own magic tech
file (`drc(full)`, 0 violations; run on a check-only copy that adds
synthetic implant/npc shapes, see `layout/compact/magic_drc.py`), plus a
small gate-level checker (`check_extra_rules.py`: poly-diff spacing,
endcap, licon spacing, enclosure, licon-to-gate, poly-licon-to-diff; 0
violations).

Two things matter for interpreting the baseline column:

- **The committed baseline is clean under the klt deck but not under the
  PDK's own magic deck**: `drc(full)` on `gain_cell_2t_array.gds` reports
  192 violations (poly overhang `poly.8`, S/D overhang `poly.7`, poly-to-
  diffusion spacing `poly.4`). The curated klt deck has no gate-level rules,
  so it cannot see them. The same gaps are tracked generically as
  klayout-tools#2936 and #3115. The baseline's 5.7812 um^2 is therefore not
  a rule-clean figure; its files were not touched. The compacted variants'
  smaller area does not come from skipping a rule: they pass every check
  the baseline fails.
- Like the committed layout, no implant, npc or well layers are drawn
  (klt's sky130 deck recognises an nfet from diffusion x poly). A
  foundry-ready cell needs them; they were added only to a check-only copy
  for the magic run. Not run: klt erc / a tap-tie check on the variants,
  antenna, density, or any sign-off flow.

### A.4 What limited further compaction

The x pitch 0.985 um is exactly the sum of four rules and one fixed device
dimension: W 0.42 (ratified) + poly-to-diffusion 0.075 + a 0.15 poly riser
+ poly spacing 0.21 + gate endcap 0.13. The RD gate must leave the column
through a riser and land on a pad outside the diffusion
(poly-contact-to-diffusion 0.19). By the same rules, mirroring alternate
columns (not drawn) moves the riser into a different gap and gives the same
average pitch. The y period 2.84 um
per two rows is two shared-contact diffusion runs (2 x 1.15, each 2 x 0.285
S/D extension for contact + contact-to-gate + enclosure, 2 x 0.15 gate and
one 0.28 shared contact) plus two diffusion spaces (2 x 0.27).
Getting below this would need a different cell construction, which is
beyond this bounded study; it was not attempted.

### A.5 Not evaluated (needs its own follow-up)

The compact layouts change the geometry around the storage node and the
shared BL/RBL contacts, so none of the committed retention or parasitics
numbers transfer to them by assumption: C_SN, C_BL/C_RBL, the junction area
of the SN diffusion, and the resistance of a word line that is one
continuous poly line per row (a macro would strap it) were not extracted.
Tracked as [#161](https://github.com/2AMLogic/sky130-gcedram/issues/161).
Row-count even-ness (mirrored pairs) and the single-device ends of `v2` are
also array-size constraints for any macro floorplan (epic #24).

**Verdict (2026-10-15): threshold MET at the drawn-cell level** by `v2`
(drawn pitch 0.985 x 1.42 = 1.399 um^2, 0.676x of the quoted 2.070 um^2) and,
narrowly, by `v1` (1.950 um^2). No failure-path operator-decision issue is
needed. The logic-rule 6T comparison remains unresolved, the array-level
(b) figure including the tap ring remains above the comparator, and the
electrical impact of the compact layouts is not yet characterised
(#161).
