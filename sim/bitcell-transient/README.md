# 2T-min bitcell transient write / read / hold (issue #27)

The **first circuit-level simulation of this repo's ratified bitcell**.
Everything recorded before this study looked at the cell one piece at a
time: [`sim/leakage/`](../leakage/README.md) is a DC operating point on a
single access device, and [`sim/retention/`](../retention/README.md) is an
analytic `t = C_SN * delta_V / I_leak` derivation on top of it. Neither
exercises the cell **as a circuit** — nothing had ever written it, read it,
or watched it decay. This study does all three in one `.tran`, across the
same 15-point PVT grid the other two use, and appends the result rows as
committed evidence.

It closes gap-to-T1 tracker [#13](https://github.com/2AMLogic/sky130-gcedram/issues/13)
items **5** ("Full corner verification vs a ratified spec") and **9**
("Testbenches shipped") for the bitcell level, and it produces the
read-current, written-level and read-disturb numbers that
[#24](https://github.com/2AMLogic/sky130-gcedram/issues/24) items 1–3 (array,
sense amplifier, write margin) each consume — see "Which #24 items consume
which column" below.

## What is simulated, and what is included rather than transcribed

The design under test is **included, not restated**.
[`tb_bitcell_transient.spice.tmpl`](tb_bitcell_transient.spice.tmpl)
`.include`s [`design/gain_cell_2t.spice`](../../design/gain_cell_2t.spice)
verbatim — the netlist `design/regen_netlist.sh` derives from
`design/gain_cell_2t.sch`. The deck contains no device cards of its own, so
a schematic change reaches this testbench through the regeneration script
rather than through a hand edit. Both devices are
`sky130_fd_pr__nfet_01v8`, W = 0.42 µm, L = 0.15 µm:

| Device | Gate | Drain | Source | Body | Role |
|---|---|---|---|---|---|
| `M_WR` | `wl` | `sn` | `bl` | `GND` | write access |
| `M_RD` | `sn` | `rbl` | `rwl` | `GND` | read |

The included netlist declares `.GLOBAL GND`; ngspice aliases the node name
`gnd` to node 0, so the bodies land on the testbench ground with no extra
source. `design/gain_cell_2t.spice` ends with `.end`, but ngspice does not
treat a `.end` inside an included file as the end of the parent deck
(verified against ngspice-46 — the testbench sources below the `.include`
are parsed normally).

## Read scheme: `rwl` idles HIGH, a read pulses it LOW

`M_RD`'s **source** is `rwl`, so the read-select polarity is a design fact
this deck has to record rather than invent. For a **deselected** row to keep
its read device off while holding a '1', `rwl` must idle at `VDD`:
`Vgs(M_RD) = V(sn) - V(rwl) < 0` whenever `V(sn) < VDD`. A read therefore
pulls `rwl` **low** (active-low read select, `rwl` acting as the row's source
line) and senses the resulting current on `rbl`.

The alternative — `rwl` idling low — is not usable in an array: every
deselected cell holding a '1' would then have `Vgs(M_RD) = V(sn) > 0` and
would dump current onto the shared `rbl` continuously. The
`i_rbl_deselect_a` column measures exactly the current the *chosen* polarity
leaves behind (tens of pA per deselected cell; 1.13 nA at `sf`/125 °C), which
is the number an array column-height budget needs.

Both wordlines still swing **0 V / 1.8 V only** — no boosted level — per
[`design/README.md`](../../design/README.md) "Wordline drive scheme: plain
1.8 V (not boosted)".

## Phase timing (the deck's `.param` block is the single source of truth)

One `.tran` per (corner, temperature, stored value) covers all three phases.
The instants below are `.param` lines in the template;
`run_bitcell_transient.py` **parses those exact lines out of the template at
run time** (`parse_template_params`) and uses them as its measurement
instants, so the waveform and the sampling points cannot drift apart.

| `.param` | Value | Meaning |
|---|---:|---|
| `VDD` | 1.8 V | core rail |
| `VRBL` | 0.9 V (`VDD`/2) | read-bitline bias — see below |
| `TEDGE` | 100 ps | every source rise/fall time |
| `TWL_ON` | 1 ns | write wordline rises |
| `TWL_OFF` | 21 ns | write wordline **starts falling** → **20 ns write pulse** |
| `TBL_OFF` | 23 ns | `bl` released to 0, *after* `wl` is fully low |
| `TRWL_ON` | 30 ns | `rwl` starts falling (read select) |
| `TRWL_OFF` | 50 ns | `rwl` starts rising → **20 ns read pulse** |
| `THOLD_START` | 55 ns | hold phase begins; decay is timed from here |

1. **Write.** `wl` pulses 0 → `VDD` → 0 with `bl` held at the data level for
   the *whole* pulse. `bl` returns to 0 only at `TBL_OFF`, after `wl` is
   fully low, so the cell is never written by a bitline transition.
   - `v_sn_end_wl_pulse_v` = `V(sn)` at `TWL_OFF`, the instant the wordline
     fall begins: the **write ceiling** for this pulse width.
   - `v_sn_after_write_settled_v` = `V(sn)` just before the read pulse: the
     level **actually retained**, i.e. the ceiling minus the
     wordline-to-storage-node feedthrough step. A DC operating point cannot
     see this step at all.
   - Write '1' starts from `V(sn) = 0` and write '0' starts from
     `V(sn) = VDD` (`.ic`), so the '0' measurement is a genuine overwrite of
     the strongest possible stored level, not a no-op.
2. **Read.** `rwl` pulses `VDD` → 0 → `VDD` with `rbl` held at `VRBL` through
   `vrbl`, whose branch current **is** the read current. `i_rbl_deselect_a`
   is sampled just before the pulse (deselected-row contribution);
   `i_read_a` and `v_sn_read_gate_v` are sampled 5·`TEDGE` before the pulse
   ends, i.e. after the edge has settled and before the next one starts.
   `v_sn_read_disturb_v` is `V(sn)` after the read minus `V(sn)` before it.
3. **Hold.** `wl` = 0, `bl` = 0, `rwl` = `VDD`, `rbl` = `VRBL`. This is
   deliberately **the same bias the DC leakage deck measures at**
   (`sim/leakage/tb_access_leakage.spice.tmpl`: gate 0 V, source 0 V, drain
   holding the '1'), so the decay here is directly comparable to that
   measurement. `t_ret_tran_s` is the time from `THOLD_START` for `V(sn)` to
   fall by `delta_V` = 0.9 V below `v_sn_hold_start_v`, linearly interpolated
   between the two bracketing accepted timepoints.

### `rbl` bias: `VDD`/2 = 0.9 V (an explicit choice)

No sense amplifier exists yet (#24 item 2), so there is no designed
bitline precharge level to adopt. `VDD`/2 is chosen because it keeps `M_RD`
in saturation for a stored '1' across the whole corner grid (the retained
'1' levels below run 0.865 V … 1.223 V, and with `rwl` pulled to 0 V the
device sees `Vds` = 0.9 V > `Vgs - Vth`), so `i_read_a` reads as a
*saturation* current — the quantity a current-sensing scheme would use — and
not as a bias-point-dependent triode current. It is overridable with
`--vrbl-v`; the value used is recorded in `vrbl_bias_v` on every row.

## Storage-node capacitance: two bounds, not one number

The deck adds a lumped `c_sn sn 0 <C_SN>`. Its default is the **post-layout
extracted** total for net `sn` from
[`layout/gain_cell_2t.extract.parasitics.json`](../../layout/gain_cell_2t.extract.parasitics.json)
(issue #7) — ground 0.586490 fF + lateral coupling to `bl`/`rwl` 0.018864 fF
= **0.605354 fF**. `run_bitcell_transient.py` reads it through
`sim/retention/derive_retention.py`'s own `load_extracted_c_sn()`, so the two
studies can never disagree about what the extracted `C_SN` is; the full
provenance string (klt version, input content hash, breakdown) lands in every
row's `notes`.

That lumped capacitor is **in addition to** the device models' own
bias-dependent storage-node capacitance (`M_RD`'s gate in inversion, `M_WR`'s
drain junction and gate overlap), which the extraction does not include and
the analytic derivation replaced with a closed-form `Cox * W * L`. Running
`--c-sn-ff 0` removes the lumped capacitor and leaves only the model's own —
i.e. the two runs bracket the real node:

| `C_SN` | `sf`/125 °C retained '1' | `sf`/125 °C `t_ret_tran_s` |
|---|---:|---:|
| 0.605354 fF (extracted, default) | 1.2226 V | 2.3958e-05 s |
| 0 fF (`--c-sn-ff 0`, intrinsic model capacitance only) | 1.0899 V | 1.4108e-05 s |

Both sets of rows are committed (the `--c-sn-ff 0` rows carry
`c_sn_source = override`, for `tt`/`ss`/`ff` × the full temperature grid).
Treating the decay as first-order in the total node capacitance, the ratio
1.6982 implies an effective **intrinsic** node capacitance of ≈ 0.867 fF, so
the transient's total node capacitance is ≈ 1.47 fF — about **2.4x** the
0.605 fF the analytic derivation uses, and about 1.6x the closed-form
`C_gate` = 0.553231 fF that derivation computes for `M_RD`. That 0.867 fF is
an **inference from two simulations**, not a measured or extracted quantity;
it is stated here only because it is the dominant term in the cross-check
below, and it should not be quoted as a `C_SN` value elsewhere.

## Numerics: `.tran` settings and the convergence check

```
tran 10p <tstop> 0 <tmax>
```

- `tstep` = **10 ps**, fixed. In ngspice this is only the suggested
  initial/print step; accepted timepoints are LTE-controlled and breakpoints
  are forced at every source-waveform corner, so the 100 ps write/read edges
  stay resolved even when `tmax` is sized for a millisecond hold window.
- `tmax` = `clamp(hold_window / 2000, 1 ns, 5 µs)`, recorded per row in
  `tmax_s`.
- `tstop` = `THOLD_START + hold_window`, recorded per row in `tstop_s`.
- `hold_window` is **seeded from the DC leakage already recorded for the same
  (corner, temperature)** in
  [`sim/leakage/results/leakage_results.csv`](../leakage/results/leakage_results.csv):
  `12 * (C_SN + 0.30 fF) * delta_V / I_leak`, clamped to [1 µs, 8 ms]. The
  12x slack is there because the transient decay is *expected* to be slower
  than that estimate (the node starts below `VDD`, so its leakage starts
  below the recorded `Vds = VDD` value and falls further as the node
  discharges). If the threshold is still not crossed the window is grown 4x
  and the point re-run, up to 3 attempts. The 0.30 fF term is a window-sizing
  allowance only — it never enters a recorded result.

**Convergence check.** Re-running the worst-case corner with `tmax` forced
49x tighter changes the answer by 0.2 %:

| `sf`/125 °C, stored '1' | `tmax` | `t_ret_tran_s` |
|---|---:|---:|
| default (`hold_window`/2000) | 4.938853e-08 s | 2.395817e-05 s |
| `--tmax-ns 1` | 1.000000e-09 s | 2.400982e-05 s |

Both rows are committed to the results CSV (they are distinguishable by the
`tmax_s` column). Reproduce with:

```bash
python3 sim/bitcell-transient/run_bitcell_transient.py \
    --corners sf --temps-c 125 --tmax-ns 1 --no-grow
```

## Corner sweep

`tt`, `ss`, `ff`, `sf`, `fs` × -40 / 27 / 125 °C = **15 PVT points**, two
stored values each = **30 rows** per full sweep. This is the same grid
`sim/leakage/pdk.json` pins and `sim/leakage/README.md` "Corner sweep"
justifies, against the same `open_pdks` commit
`c6d73a35f524070e85faff4a6a9eef49553ebc2b` — a divergent PDK pin would
silently invalidate the hold-window seeding and the leakage cross-check.

**Both devices in this cell are NMOS**, so the useful ordering of the corner
axis is the NFET `vth0` offset the shipped model applies, not the corner's
`Slow-Fast` name. From
`libs.tech/combined/continuous/parameters_fet_<corner>.spice`:

| Corner | NFET `sw_vth0` offset | Effect on this cell |
|---|---:|---|
| `fs` | +27 mV | **slowest** NMOS — lowest write ceiling, lowest read current |
| `ss` | +15 mV | slow NMOS |
| `tt` | 0 | typical |
| `ff` | -15 mV | fast NMOS |
| `sf` | -27 mV | **fastest** NMOS — highest write ceiling, highest read current *and* highest leakage |

Every result below is monotone in that ordering, which is the main internal
consistency check on the deck. It is also why `sf`/125 °C is the worst-case
retention corner here, exactly as it is in `sim/leakage/` — and why the
*write*-margin failures land at the opposite end, `fs`/`ss` and cold.

## Results — write and read

As of the sweep recorded in `results/bitcell_transient_results.csv`
(2026-09-09, `repo_git_sha` `c972c05`, ngspice-46, extracted `C_SN`,
20 ns write pulse). "retained" is `v_sn_after_write_settled_v` /
`v_sn_hold_start_v`, i.e. after wordline feedthrough.

| Corner | T (°C) | write-'1' ceiling | retained '1' | retained '0' | `i_read_a` '1' | `i_read_a` '0' | ratio | `i_rbl_deselect_a` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `fs` | -40 | 1.012 V | 0.865 V | -0.118 V | 3.444e-08 A | 2.579e-09 A | 13.4 | 5.951e-11 A |
| `fs` | 27 | 1.082 V | 0.934 V | -0.126 V | 5.196e-07 A | 2.489e-09 A | 209 | 7.255e-11 A |
| `fs` | 125 | 1.179 V | 1.030 V | -0.109 V | 3.963e-06 A | 2.194e-09 A | 1.81e+03 | 1.543e-10 A |
| `ss` | -40 | 1.042 V | 0.898 V | -0.125 V | 1.930e-07 A | 2.385e-09 A | 80.9 | 5.256e-11 A |
| `ss` | 27 | 1.108 V | 0.962 V | -0.132 V | 1.535e-06 A | 2.309e-09 A | 665 | 6.209e-11 A |
| `ss` | 125 | 1.198 V | 1.051 V | -0.110 V | 6.586e-06 A | 2.103e-09 A | 3.13e+03 | 1.274e-10 A |
| `tt` | -40 | 1.114 V | 0.961 V | -0.128 V | 1.996e-06 A | 2.683e-09 A | 744 | 4.674e-11 A |
| `tt` | 27 | 1.184 V | 1.030 V | -0.128 V | 7.345e-06 A | 2.563e-09 A | 2.87e+03 | 7.235e-11 A |
| `tt` | 125 | 1.281 V | 1.126 V | -0.089 V | 1.778e-05 A | 2.145e-09 A | 8.29e+03 | 2.011e-10 A |
| `ff` | -40 | 1.179 V | 1.017 V | -0.128 V | 9.145e-06 A | 2.929e-09 A | 3.12e+03 | 4.119e-11 A |
| `ff` | 27 | 1.253 V | 1.090 V | -0.118 V | 1.988e-05 A | 2.791e-09 A | 7.12e+03 | 8.230e-11 A |
| `ff` | 125 | 1.353 V | 1.192 V | -0.059 V | 3.469e-05 A | 2.236e-09 A | 1.55e+04 | 1.187e-10 A |
| `sf` | -40 | 1.217 V | 1.056 V | -0.119 V | 1.694e-05 A | 2.672e-09 A | 6.34e+03 | 3.947e-11 A |
| `sf` | 27 | 1.286 V | 1.126 V | -0.099 V | 2.711e-05 A | 2.530e-09 A | 1.07e+04 | 8.935e-11 A |
| `sf` | 125 | 1.380 V | 1.223 V | -0.034 V | 4.005e-05 A | 1.873e-09 A | 2.14e+04 | 1.132e-09 A |

Reported, not editorialized:

- **The write ceiling is a pulse-width-dependent quantity, not a constant.**
  `design/README.md` previously quoted `v(sn) ≈ 1.39 V` from an uncommitted
  `tt` DC smoke check. That figure is the **`t → ∞` asymptote**; a finite
  wordline pulse never reaches it, because the last few hundred millivolts
  are charged through `M_WR` in subthreshold. At `tt`/27 °C:

  | write pulse | ceiling at `TWL_OFF` | retained after feedthrough |
  |---|---:|---:|
  | 20 ns (this study's default) | 1.184 V | 1.030 V |
  | 200 ns (`--t-wl-pulse-ns 200`) | 1.255 V | 1.101 V |
  | 2000 ns (`--t-wl-pulse-ns 2000`) | 1.319 V | 1.166 V |
  | DC operating point (`t → ∞`) | ≈ 1.39 V (the uncommitted smoke check) | n/a — DC cannot show feedthrough |

  All three transient rows are committed (distinguishable by
  `t_wl_pulse_ns`). The 20 ns default is the number that should be quoted for
  a plausible access time; 1.39 V should not.
- **Wordline feedthrough costs a further ~0.15 V.** When `wl` falls, `M_WR`'s
  gate-drain overlap/inversion capacitance couples the storage node down by
  0.144 V … 0.163 V across the grid — about 8 % of the 1.8 V wordline swing,
  consistent with the ~0.87 fF effective node capacitance inferred above. A
  DC check cannot see this term at all, which is precisely why the committed
  transient record supersedes the smoke check.
- **A written '0' sits *below* the bitline rail**, at -0.089 V … -0.132 V,
  for the same feedthrough reason. It relaxes back toward 0 V over the hold
  window (`v_sn_hold_end_v` on the stored-'0' rows). This slightly *helps*
  the read '0' current and is recorded rather than clipped.
- **Read current spans three decades across the grid**: 34.4 nA at `fs`/-40 °C
  to 40.1 µA at `sf`/125 °C, a **1163x** range. The '0' current is nearly
  corner-independent at ~2 nA (`M_RD` is deeply off with `sn` below the rail),
  so the **'1'/'0' ratio collapses to 13.4 at `fs`/-40 °C** while reaching
  2.1e+04 at `sf`/125 °C.
- **`v_sn_read_disturb_v` is small but not zero**: |disturb| ≤ 1.3 mV at all
  corners for a stored '1' (the read pulse is charge-neutral to first order —
  `rwl`'s falling edge couples `sn` down and its rising edge couples it back
  up). It is largest at the hot corners, where leakage during the 20 ns pulse
  does not fully cancel.

## Results — hold decay, and the worst-case corner

`delta_V` = 0.9 V, the same labelled ASSUMPTION `sim/retention/README.md`
"Sense margin" carries (`VDD`/2, the coarse half-`VDD` bound used absent a
sense-amplifier offset/noise budget). "threshold" is
`v_sn_hold_start_v - 0.9 V`.

| Corner | T (°C) | retained '1' | threshold | `hold_window_s` | `t_ret_tran_s` | `t_ret_linear_extrap_s` |
|---|---:|---:|---:|---:|---:|---:|
| `fs` | -40 | 0.8652 V | -0.0348 V | 5.402e-03 s | **blank — write-margin failure** | 1.4064e-03 s |
| `fs` | 27 | 0.9342 V | +0.0342 V | 5.397e-03 s | **blank — write-margin failure** | 1.2967e-03 s |
| `fs` | 125 | 1.0299 V | +0.1299 V | 3.539e-03 s | 1.5324e-04 s | 1.4291e-04 s |
| `ss` | -40 | 0.8978 V | -0.0022 V | 5.402e-03 s | **blank — write-margin failure** | 1.3274e-03 s |
| `ss` | 27 | 0.9623 V | +0.0623 V | 5.400e-03 s | 3.6773e-03 s *(marginal, see below)* | 1.2341e-03 s |
| `ss` | 125 | 1.0507 V | +0.1507 V | 4.344e-03 s | 1.5175e-04 s | 1.4436e-04 s |
| `tt` | -40 | 0.9610 V | +0.0610 V | 5.402e-03 s | 3.6209e-03 s *(marginal)* | 1.2128e-03 s |
| `tt` | 27 | 1.0299 V | +0.1299 V | 5.299e-03 s | 2.6407e-03 s | 1.1114e-03 s |
| `tt` | 125 | 1.1260 V | +0.2260 V | 8.487e-04 s | 1.0449e-04 s | 8.5036e-05 s |
| `ff` | -40 | 1.0173 V | +0.1173 V | 5.399e-03 s | 2.7443e-03 s | 1.1231e-03 s |
| `ff` | 27 | 1.0903 V | +0.1903 V | 4.414e-03 s | 1.8870e-03 s | 8.9091e-04 s |
| `ff` | 125 | 1.1919 V | +0.2919 V | 1.476e-04 s | 3.8742e-05 s | 2.4846e-05 s |
| `sf` | -40 | 1.0563 V | +0.1563 V | 5.395e-03 s | 2.3511e-03 s | 1.0544e-03 s |
| `sf` | 27 | 1.1256 V | +0.2256 V | 3.827e-03 s | 1.4454e-03 s | 7.3420e-04 s |
| `sf` | **125** | 1.2226 V | +0.3226 V | 9.878e-05 s | **2.3958e-05 s** | 1.5963e-05 s |

### Worst-case corner, called out by name

**`sf` corner, 125 °C: `t_ret_tran` = 2.395817e-05 s (~23.96 µs).**

This is the shortest simulated decay time among the twelve corners where the
0.9 V sense margin is attainable at all, and it is the worst case on the
conservative `t_ret_linear_extrap_s` column too (1.5963e-05 s, ~15.96 µs).
It is the same corner `sim/leakage/README.md` and `sim/retention/README.md`
already name as worst case, but that agreement was **confirmed from this
data, not assumed**: `sf` is the fastest-NMOS bin (`vth0` -27 mV) and 125 °C
is the hottest point, so it maximises the off-state leakage discharging the
node while also producing the *highest* retained level — the two effects push
in opposite directions and the leakage wins.

`t_ret_linear_extrap_s` is `delta_V / |dV/dt|` measured over the first 2 % of
the hold window — the same constant-current linear-decay approximation
`derive_retention.py` uses, but with the slope **measured here** instead of
computed from an assumed `C_SN` and a DC leakage number. It is defined at
every corner (including the write-margin failures) and is always shorter than
`t_ret_tran_s`, because the initial slope is the steepest one: as the node
discharges, its `Vds` falls and so does the leakage. It is therefore the
conservative column of the two.

### Write-margin failures: three corners where the 0.9 V margin is unreachable

This sweep is **not clean everywhere**, and that is the most important
finding in it. At three of the fifteen corners the cell never holds enough
charge for a 0.9 V decay to be defined:

| Corner | T (°C) | retained '1' | 0.9 V threshold would be |
|---|---:|---:|---:|
| `fs` | -40 | 0.8652 V | **-0.0348 V** — below the bitline rail |
| `ss` | -40 | 0.8978 V | **-0.0022 V** — below the bitline rail |
| `fs` | 27 | 0.9342 V | +0.0342 V — inside the 0.05 V asymptotic floor |

`V(sn)` approaches the 0 V bitline rail only asymptotically, so a threshold
at or below `THRESHOLD_FLOOR_V` = 0.05 V is unreachable *in principle*, not
merely unreached within the simulated window; growing the window would never
resolve it. The driver detects this and writes `t_ret_tran_s` **blank**, with
the reason spelled out in that row's `notes` column, rather than emitting a
misleading number. `t_ret_linear_extrap_s` is still recorded for those rows.

Two further rows are *technically* crossings but should be read as marginal,
not as results: `ss`/27 °C (threshold +0.0623 V) and `tt`/-40 °C (threshold
+0.0610 V) both time a decay all the way to within ~60 mV of the rail, deep
into the asymptotic tail — which is why their `t_ret_tran_s` values are
milliseconds while their `t_ret_linear_extrap_s` values are ~1.2 ms. A
millisecond "retention time" at those corners is an artifact of an
unattainable margin, not headroom.

**What this means, stated plainly:** with a plain-1.8 V wordline and a 20 ns
write pulse, the ratified `2T-min` cell **cannot support a 0.9 V sense margin
across the full PVT grid.** The margin is comfortable in the fast-NMOS / hot
quadrant and vanishes in the slow-NMOS / cold quadrant, because the write
ceiling is `VDD - Vth(M_WR)` and `Vth` rises at both `fs`/`ss` and low
temperature. Three responses exist — boost the wordline, lengthen the write
pulse (the 200 ns / 2000 ns rows above buy 0.07 V / 0.14 V), or replace the
`delta_V = VDD/2` assumption with a real sense-amplifier offset/noise budget.
**This study does not pick one** (see "Decision-record candidates" below);
picking one is a spec-level decision, and per `CLAUDE.md` agents do not relax
a ratified spec to make results pass.

## Cross-check against the analytic retention derivation

At the worst-case corner, `sf`/125 °C, with the same extracted
`C_SN` = 0.605354 fF and the same `delta_V` = 0.9 V:

| Source | Retention at `sf`/125 °C | Relative to this study |
|---|---:|---:|
| **This study (transient)**, `results/bitcell_transient_results.csv` | **2.395817e-05 s** (~23.96 µs) | 1.00x |
| `sim/retention/results/retention_results.csv` row 3 (`07612be`), extracted `C_SN` | 5.503841e-06 s (~5.50 µs) | 0.23x |
| `spec/retention-refresh-budget.md` §5 (ratified, assumption-based `C_SN` = 1.106463 fF) | ~10.06 µs (1.005989e-05 s) | 0.42x |
| This study's own conservative column, `t_ret_linear_extrap_s` | 1.5963e-05 s (~15.96 µs) | 0.67x |

The transient result is **4.35x longer** than the analytic figure it is being
compared against. The divergence is expected and decomposes cleanly into
exactly the two effects the issue names:

1. **Bias-dependent node capacitance vs. closed-form `Cox` — a 2.43x factor.**
   `derive_retention.py` uses the extracted `C_SN` = 0.605354 fF alone (and,
   in the superseded assumption-based row, a margin factor over a closed-form
   `C_gate = Cox'' * W * L = 0.553231 fF`). In the transient, the shipped
   BSIM4 models contribute their *own* bias-dependent storage-node
   capacitance — `M_RD`'s gate in inversion plus `M_WR`'s drain junction and
   overlap — **on top of** the lumped extracted value. The `--c-sn-ff 0`
   comparison above puts that intrinsic contribution at ≈ 0.867 fF, for a
   total of ≈ 1.47 fF, i.e. 2.43x the 0.605 fF the analytic path assumes.
2. **Written level below `VDD` — a 1.79x factor.** The analytic derivation
   uses `I_leak` measured at `Vds` = `VDD` = 1.8 V (98.99 pA, the worst-case
   bias per `sim/leakage/README.md`). The transient node never gets to
   1.8 V: it starts the hold phase at 1.2226 V and falls to 0.3226 V, so the
   leakage discharging it is below the DC number for the entire window. The
   effective average current implied by the measured decay is
   `1.47 fF * 0.9 V / 23.96 µs` = **55.3 pA**, or 0.56x the DC figure.

`2.43 * 1.79 = 4.35` — the observed ratio, to three digits. This is the
decomposition, not a coincidence fit: both factors were computed from
committed rows, and the product reproduces the measured discrepancy exactly.

**Direction of the correction.** `sim/retention/README.md` already stated
that its constant-current approximation is conservative "in the direction of
*understating* true retention time, not overstating it." This transient
result confirms that, quantitatively, at the corner where it matters. **It
does not, by itself, license a longer refresh interval.** The 10.06 µs /
5.03 µs numbers in `spec/retention-refresh-budget.md` §5/§7 remain the
ratified values; re-ratifying them against this transient evidence is a
separate, gated spec change (explicitly out of scope for issue #27), and any
such change would have to reckon with the write-margin failures above, which
push in the *opposite* direction.

## What these numbers say (and do not say)

These are single-cell numbers, from a deterministic (non-Monte-Carlo,
`MC_MM_SWITCH = 0`) corner deck, with ideal voltage sources on `wl`, `bl`,
`rwl` and `rbl`. They are **not** an array or macro result. Out of scope
here, each of which would tend to *degrade* the numbers above:

- **No bitline/wordline loading.** Real `bl`/`rwl` drivers have finite
  strength and the lines carry the whole column's/row's capacitance; the
  100 ps edges here are not achievable in an array.
- **No array leakage aggregation.** `i_rbl_deselect_a` is per *one*
  deselected cell; an N-row column sums N of them against the selected
  cell's `i_read_a`. At `sf`/125 °C that is 1.13 nA per cell against a 40 µA
  read '1' — but against a 1.87 nA read '0'.
- **No mismatch.** Local `Vth` mismatch between `M_WR` devices directly
  spreads the written level, and this cell has ≈ 0.15 V of margin to spare at
  the good corners and none at the bad ones.
- **No read disturb over many reads**, no refresh-controller interaction, no
  sense-amplifier offset (#24 items 2–3).
- **`delta_V` = 0.9 V remains an ASSUMPTION**, inherited unchanged from
  `sim/retention/README.md` so the two studies stay comparable. Every
  conclusion about write margin above is a conclusion *about that
  assumption*, and a validated sense-amp budget could change it in either
  direction.

Per `CLAUDE.md`: this is a dynamic cell, and these microsecond-scale
retention numbers with a PVT-dependent write margin are the density/retention
tradeoff the repo exists to make explicit — not a defect to be explained
away, and not grounds to describe the macro as a drop-in SRAM replacement.

## Which #24 items consume which column

[#24](https://github.com/2AMLogic/sky130-gcedram/issues/24) ("Build the full
gain-cell eDRAM macro") is the downstream consumer of this study:

| #24 item | Columns it consumes | Why |
|---|---|---|
| **1. Array** | `i_rbl_deselect_a`, `v_sn_read_disturb_v`, `i_read_a` ('1' and '0') | The deselected-cell current sets the maximum column height before N cells of leakage swamp the selected cell's read current; the read-disturb column bounds how many reads a row tolerates between refreshes. Worst case for column height is `sf`/125 °C (1.132e-09 A deselected vs 1.873e-09 A for a selected '0'). |
| **2. Sense amplifier** | `i_read_a` '1', `i_read_a` '0', `i_read_ratio_1_over_0`, `vrbl_bias_v` | The sense amp must resolve the '1'/'0' current difference at the *worst* corner, not the typical one: `fs`/-40 °C gives 34.4 nA vs 2.58 nA (ratio 13.4), while `sf`/125 °C gives 40.1 µA vs 1.87 nA — a 1163x input dynamic range. `vrbl_bias_v` records the bias these currents were measured at, which the sense amp must reproduce. Replacing `delta_V = VDD/2` with a validated offset/noise budget (#24 item 2's stated goal) directly re-scores the write-margin table above. |
| **3. Refresh controller** | `t_ret_tran_s`, `t_ret_linear_extrap_s`, `v_sn_hold_start_v` | The refresh interval must sit under the worst-case *valid* retention time — 2.3958e-05 s at `sf`/125 °C by simulation, 1.5963e-05 s on the conservative column — while the ratified §7 bound remains 5.03 µs until a spec change says otherwise. |
| **Write margin** (#24 item 2's precondition, and the open item `design/README.md` names) | `v_sn_end_wl_pulse_v`, `v_sn_after_write_settled_v`, `t_wl_pulse_ns` | The ceiling/retained pair across the grid, plus the 20/200/2000 ns settling rows, are the whole input to a boosted-wordline-vs-longer-pulse-vs-smaller-`delta_V` decision. |
| **6. Post-layout PVT sim** | all of the above | This deck is the pre-layout half; the post-layout re-run against `layout/gain_cell_2t.extract.parasitics.spice` is T1 item 7, explicitly out of scope here (that netlist uses the deck's generic `nfet` model name and a `vsubs` node, and needs its own model-mapping decision). |

## Decision-record candidates (recorded here, not decided here)

Per issue #27's "Out of scope", these are written down so they are not lost,
**not** resolved:

1. **Boosted wordline.** A `VDD + Vth` write wordline would remove the
   `VDD - Vth` ceiling and the three write-margin failures in one step, at
   the cost of a charge pump / level shifter and a gate-oxide-reliability
   argument. `design/README.md` currently records plain 1.8 V as the
   assumption.
2. **`M_RD` re-sizing.** `design/README.md` calls the read device's sizing an
   explicit placeholder "not yet driven by a read-current or sense-margin
   analysis." This study is the first read-current analysis; the 13.4x
   worst-corner ratio is the number a re-sizing decision would target. Note
   that widening `M_RD` also raises the storage-node capacitance (its gate is
   `sn`), which *helps* retention — the two effects are coupled and a
   re-sizing study should sweep both.
3. **Write pulse width.** 20 ns is this deck's choice, not a ratified access
   time. The settling table shows what longer pulses buy.
4. **`delta_V`.** Half-`VDD` is inherited from `sim/retention/`. It is the
   single assumption that decides whether three corners "fail".

None of these are actioned here, and `spec/retention-refresh-budget.md` is
deliberately untouched.

## Reproducing this testbench

Requires a stock `open_pdks` sky130 install (via `volare`, pinned in
[`pdk.json`](pdk.json)) and `ngspice` on `PATH`. No local model edits, no
uncommitted `.include` paths. Stdlib-only Python, no virtualenv.

```bash
# 1. Install/enable the pinned PDK commit (skip if already enabled):
volare enable --pdk sky130 c6d73a35f524070e85faff4a6a9eef49553ebc2b

# 2. Point PDK_ROOT at your volare root if it isn't ~/.volare:
export PDK_ROOT=~/.volare   # default; only needed if you installed elsewhere

# 3. Check inputs resolve (ngspice, PDK model library, design netlist,
#    extracted C_SN):
python3 sim/bitcell-transient/run_bitcell_transient.py --check-env

# 4. Run the full sweep (5 corners x 3 temperatures x 2 stored values = 30
#    rows; tens of minutes on a single core -- the cold corners simulate a
#    multi-millisecond hold window, and each ngspice invocation loads the
#    full BSIM4 model set for its corner):
python3 sim/bitcell-transient/run_bitcell_transient.py
```

This **appends** rows to `results/bitcell_transient_results.csv` (creating it
with a header on first run) — it never truncates or overwrites prior rows,
per `CLAUDE.md`'s "`sim/` results are append-only evidence." The hold window
is seeded from `sim/leakage/results/leakage_results.csv`, so that file must
already carry a row for every (corner, temperature) point being run; the
driver fails loudly rather than guessing if one is missing.

Useful flags:

```bash
# single point
python3 sim/bitcell-transient/run_bitcell_transient.py --corners sf --temps-c 125

# render a deck and exit, without simulating
python3 sim/bitcell-transient/run_bitcell_transient.py --dry-run

# intrinsic model capacitance only (no lumped extracted C_SN)
python3 sim/bitcell-transient/run_bitcell_transient.py --c-sn-ff 0

# numerics convergence check (forced .tran tmax)
python3 sim/bitcell-transient/run_bitcell_transient.py \
    --corners sf --temps-c 125 --tmax-ns 1 --no-grow

# write-ceiling settling sensitivity (shifts the read/hold phases with it)
python3 sim/bitcell-transient/run_bitcell_transient.py \
    --corners tt --temps-c 27 --t-wl-pulse-ns 2000 --no-grow

# other overrides: --vrbl-v, --delta-v, --pdk-root, --pdk
```

Rows produced by the override flags stay distinguishable in the CSV without
reading `notes`: `c_sn_ff`/`c_sn_source` for `--c-sn-ff`, `tmax_s` for
`--tmax-ns`, `t_wl_pulse_ns` for `--t-wl-pulse-ns`, `vrbl_bias_v` for
`--vrbl-v`, and `delta_v_sense_margin_v_ASSUMPTION` for `--delta-v`. The
30-row primary sweep is the subset with
`c_sn_source = extracted AND t_wl_pulse_ns = 20.0 AND tmax_s != 1.000000e-09`.

## Files

| Path | Purpose |
|---|---|
| `tb_bitcell_transient.spice.tmpl` | ngspice `.tran` testbench template; includes `design/gain_cell_2t.spice` verbatim, declares the phase timing in a `.param` block the driver parses back out |
| `run_bitcell_transient.py` | Sweep driver: renders decks, invokes `ngspice -b`, measures every recorded scalar, sizes the hold window from `sim/leakage/`, appends rows via `sim/_evidence_common.append_result` |
| `pdk.json` | PDK version pin (same `open_pdks` commit as `sim/leakage/` and `design/`) and the corner/temperature grid |
| `results/bitcell_transient_results.csv` | Append-only recorded results, one row per (corner, temperature, stored value) plus the committed override/sensitivity runs |
