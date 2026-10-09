# Density vs 6T SRAM: area per bit of the committed 4x4 array (issue #97)

**Status: evidence write-up, not a ratified spec change.** No ratified value
in [`retention-refresh-budget.md`](retention-refresh-budget.md) is edited and
the README requirement is not relaxed. It fills the comparison that document
deferred (its Section 8, "Density vs SRAM comparison").

## 1. Result, stated plainly

**The 2T cell as drawn does not beat the public 6T SRAM bitcell on area.** It
is about **2.4x larger** at the drawn-cell level and about **3.4x larger** at
the 4x4 array level (ring included), against the SRAM-rule comparator.
The README requirement ("must beat a 6T SRAM bitcell on area to justify
existing") is therefore **unmet** by the current layout. Consequence filed as
decision issue [#100](https://github.com/2AMLogic/sky130-gcedram/issues/100);
the requirement and the ratified 2T decision are untouched.

## 2. Reproduction

```bash
python3 -I layout/area_density.py          # writes layout/results/density_<date>.json
```

Stdlib only; reads `layout/gain_cell_2t_array.layout.json`,
`layout/gain_cell_2t_array_mos.json` and `layout/gain_cell_2t_array.gds`
(extents cross-check; sha256 of all three recorded in the result). It does
not invoke `klt`, ngspice or any host tool. klt on the host when the result
was written: `klt 0.7.0+gb82427b30c96` (recorded for provenance only). The
array GDS may change when #91 is resolved; if so re-run into a **new** result
file (`--tag`). Result files are never overwritten (the script refuses), and
the committed file is listed in `sim/append_only_inventory.txt` so
`sim/check_append_only.py` protects it. Committed result:
[`layout/results/density_20261009.json`](../layout/results/density_20261009.json).

## 3. Measured from committed layout (three separate figures)

| Figure | Definition | Value |
|---|---|---|
| (a) drawn bitcell pitch area | pitch_x x pitch_y from the uniform device grid (2 nfets per cell, 2.98 um wide x 1.64 um tall) | **4.887 um^2** |
| (b) array area per bit incl. shared tap | composed bbox 13.66 x 8.30 = 113.378 um^2 / 16 bits (GDS extents match the JSON bbox) | **7.086 um^2/bit** |
| (c) extrapolated macro area per bit | see Section 5; ASSUMPTION-driven | 5.4 - 9.8 um^2/bit (ring-free) |

Tap overhead: the one ring around the grid costs 35.2 um^2 for 16 bits, a
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
| (a) drawn pitch area | 2.36x | 2.58x |
| (b) 4x4 array with ring | 3.42x | 3.74x |

**Process-rule caveat.** These bitcells use SRAM-specific (foundry "push")
design rules; the 2T gain cell is drawn in plain logic rules, so this is not
a like-for-like comparison and flatters the SRAM. The issue asked for a
logic-rule 6T comparator as a second, larger figure. **No public logic-rule
6T sky130 area was found that I could verify, so none is quoted.** Instead
the break-even is stated: a logic-rule 6T cell would have to exceed
**4.89 um^2** (drawn) / **7.09 um^2** (4x4 array) before the 2T cell wins;
that is 2.4x the SRAM-rule cell. Whether that is plausible is not asserted
here. The OpenRAM 1.2.48 docs were not found to quote a cell-area figure, so
no number is attributed to them beyond the cell-library file above.

## 5. Macro extrapolation (labelled assumption)

`macro area per bit = array area per bit / (1 - f)`, where `f` is the
fraction of macro area that is periphery (sense amps, row drivers, refresh
controller, decoders, routing). **`f` is an ASSUMPTION**: no periphery is
designed (epic #24). Nominal 0.30, swept 0.10 - 0.50:

| f | ring-free (a) um^2/bit | 4x4 with ring (b) um^2/bit |
|---|---|---|
| 0.10 | 5.43 | 7.87 |
| 0.20 | 6.11 | 8.86 |
| **0.30 (nominal)** | **6.98** | **10.12** |
| 0.40 | 8.15 | 11.81 |
| 0.50 | 9.77 | 14.17 |

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
  cell; its 2.98 x 1.64 um pitch is a generator artifact and a compaction
  study could reduce it. That is a follow-up, not a result here.
- The comparison is cell-to-cell; neither SRAM nor gain-cell periphery is
  designed.
- Literature-based gain-cell-vs-6T density claims at other nodes live in
  `ratification/market-key/comps/gcedram.md` and are not sky130 figures.
