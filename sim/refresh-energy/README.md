# Refresh energy and standby power of the extracted 4x4 array (issue #115)

Epic #24 item 6. [`sim/refresh-op`](../refresh-op/README.md) measured how
**long** a row refresh takes, and
[`sim/refresh-overhead`](../refresh-overhead/README.md) scales that time into
bandwidth. This study measures what a refresh **costs in energy** at the
array boundary, and what the array draws while idle.

**What the number is.** The *ideal-driver array-boundary energy estimate* of
one row refresh of the committed extracted 4x4 array: a partial cost under
stated assumptions. It **excludes** sense-latch / reference-circuit
dissipation, the controller, real driver losses and distribution circuitry.
It is **not** complete row-refresh energy, **not** a rigorous physical lower
bound (ideal sources recover charge that a real circuit would dissipate), and
**not** macro power. Everything sits under the PROPOSED, unratified operating
range (27 C and 125 C, tt/ss/ff/sf/fs global corners, `VDD` = 1.8 V, no
mismatch); no statistical-yield claim is made. No spec file, ratified value
or prior result record was edited.

**Plain statement.** A gain cell is dynamic: it pays a refresh energy SRAM
does not, in exchange for density. Nothing here compares the macro with SRAM:
an equivalent-capacity SRAM leakage figure is **unmeasured** in this repo and
would need a separately sourced, comparable baseline. Nothing here makes the
macro an SRAM replacement.

## What was built

| File | Role |
|---|---|
| [`gen_refresh_energy.py`](gen_refresh_energy.py) | generates the three files below; constants and ASSUMPTIONs at its top; imports #110's phase definitions from `../refresh-op/gen_refresh_op.py` and the extracted-array parser from `../write-disturb/gen_write_disturb.py` (single sources of truth) |
| [`refresh_energy.spice`](refresh_energy.spice) | flat circuit body for `klt sim`: 10 instances of the extracted array, each with its own sources |
| [`request.json`](request.json) | `klt sim` request: 5 process corners x {27, 125} C = 10 points, one `tran` (max step 20 ps), `backend: batch` |
| [`request_fine.json`](request_fine.json) | the identical deck and grid at a 4x finer max step (5 ps): time-resolution convergence repeat |
| [`analyze_refresh_energy.py`](analyze_refresh_energy.py) | reduces the two committed reports to sources / points / scaling CSVs and a summary JSON (new files only, refuses to overwrite) |
| [`test_refresh_energy.py`](test_refresh_energy.py) | stdlib checks: generator staleness, deck structure and isolation, analytic positive / negative controls, synthetic reduction controls, reproduction of committed results; wired into CI and `npm test` |
| `results/` | append-only evidence (below) |

## The operation (replay of #110 on the extracted array)

Source waveform provenance: the phase definitions of
[`sim/refresh-op/gen_refresh_op.py`](../refresh-op/gen_refresh_op.py)
(`T_PRE_ON` 2 ns, `T_PRE_GAP` 2 ns, `T_LATCH` 1 ns, `T_GUARD` 2 ns, `T_MEAS`
2 ns, 100 ps edges) are imported, not retyped, and `t_row_refresh_op` uses
#110's own formula. With the two PROPOSED ASSUMPTIONS derived from #110 --
**sense basis 10 ns** (the sense-stage contract instant) and a **conservative
10 ns write-back pulse** (#110 measured `w_min` <= 5 ns at FRAC 0.95 and
10 ns sense on its own column deck; that is *not* assumed to transfer, the
restore is re-verified here at every point) -- one operation is:

| Instant | t (ns) | Event |
|---|---:|---|
| `t_start` | 5 | precharge phase begins (initialisation settled; energy window opens) |
| `t_pre_off` | 7 | RBL precharge switches open |
| `t_sel` | 9 | RWL0 falls (row 0 selected for read) |
| `t_en` | 19 | sense instant: V(RBL_c) compared with VREF = VRBL - 100 mV |
| `t_on` | 20 | WWL0 rises; WBL_c driven to the decided value |
| `t_off` | 30 | WWL0 falls |
| `t_rel` | 32 | release: RWL0 back to VDD, WBL back to idle 0 V, precharge reconnected |
| `t_end` | 34 | SN read; energy window closes |

`t_row_refresh_op` = 2 + 2 + 10 + 1 + 10 + 2 = **27 ns** (#110 formula); the
energy window is 29 ns (it also contains #110's 2 ns post-release settle).

### Adaptations to the extracted topology (every one)

#110's waveform is a four-row single column of schematic cells with a
physical latch, ideal switches, extracted single-cell `C_SN` and assumed
10 fF bitline loads. This replay changes:

1. **Array**: the committed extracted 4x4 array
   ([`layout/gain_cell_2t_array.extract.parasitics.spice`](../../layout/gain_cell_2t_array.extract.parasitics.spice):
   32 devices, lumped per-net R, ground C, net-to-net coupling C) re-emitted
   node-for-node per instance, `nfet` -> `sky130_fd_pr__nfet_01v8`. **No
   external `C_RBL`/`C_WBL`** is added: the 10 fF of #110 stands for a longer
   bitline / periphery load outside this boundary. The 4-row bitline is
   therefore short, which speeds signal development relative to a real column.
2. **No latch, no reference node.** The read decision is
   `sign(V(RBL_c) - VREF)` at `t_en`; the write-back drives the **stored bit**
   (an ideal, correct decision). A wrong-polarity read is classified as a
   read failure; that point is not a successful refresh.
3. **WBL** is driven by an ideal source (idle 0 V; the decided value from
   `t_on` to `t_rel`) instead of the latch complement through a 100 ohm switch.
4. **RBL** is standby-precharged to VRBL = 0.9 V through #110's ideal 100 ohm
   switch, released at `t_pre_off` and reconnected at `t_rel` (#110 started
   the bitline at the previous operation's latch rail, a latch artefact
   outside this boundary). Reconnecting at release means the energy to
   return a discharged bitline to standby is **inside** the window, so the
   bitlines end where they started.
5. **Data**: every one of the 16 cells holds its pattern bit (#110: all four
   rows at one level).
6. **GND (body taps) and vsubs (substrate, the extracted capacitances'
   reference)** each return through their own 0 V source (write-disturb tied
   them to ground directly).

Between `t_pre_off` and `t_rel` the RBL is floating; with no latch to drive
it, a bitline discharged by a stored '1' stays low for ~23 ns while the
**deselected** read wordlines sit at VDD. That is the regime the energy
below is measured in (see Results: deselected-row read-path current).

### Patterns (explicit 4x4 maps, row 0 refreshed)

`1` = stored 0.9 V (ASSUMPTION: aged '1', the retention study's `delta_V` =
VDD/2), `0` = 0 V. Rows listed top (row 0) to bottom.

| all-zero | all-one | checkerboard | inverse checkerboard |
|---|---|---|---|
| `0000` | `1111` | `1010` | `0101` |
| `0000` | `1111` | `0101` | `1010` |
| `0000` | `1111` | `1010` | `0101` |
| `0000` | `1111` | `0101` | `1010` |

### Instances (one deck, each instance isolated)

`act_<p>` (the operation), `idl_<p>` (matched idle: same corner, pattern,
bias, duration, every source at its standby level, no pulses), `nop_c`
(control: the active code path with every pulse at its standby level, i.e.
must equal `idl_c` and must be flagged unrestored), `refw` (#110's reference
write: every row-0 SN from 0 V, ideal 1.8 V WBL, 20 ns WWL, same phases; its
energy is **not** measured). Every instance has its own sources; no node
other than ground is shared (`check_isolation`, tested with a bridging
negative control).

## Power boundary, sign and integration

**Boundary inventory** (per instance, every independent source that
exchanges energy with the array; negative terminal of each on ground node 0):

| Source | Port | Standby | Active (row 0 refresh) |
|---|---|---|---|
| `vpre0..3` | RBL precharge/read (through the 100 ohm switch) | dc 0.9 V, switch closed | dc 0.9 V, switch open 7..32 ns |
| `vwbl0..3` | WBL write-back | dc 0 V | '1' columns: 0 -> 1.8 V over 20..32 ns; '0' columns: dc 0 V |
| `vrwl0` | selected RWL | dc 1.8 V | 1.8 -> 0 V over 9..32 ns |
| `vrwl1..3` | deselected RWL | dc 1.8 V | dc 1.8 V |
| `vwwl0` | selected WWL | dc 0 V | 0 -> 1.8 V over 20..30 ns |
| `vwwl1..3` | deselected WWL | dc 0 V | dc 0 V |
| `vbody` | array GND (body taps) | dc 0 V | dc 0 V |
| `vsub` | vsubs (substrate) | dc 0 V | dc 0 V |

The extracted array has no conventional VDD rail; all of its ports are
above. **Excluded** (identified, outside the boundary): `vctl`, the
precharge-switch control (the ideal `sw` model draws no control current).

**Sign.** `p_s(t) = -v_s(t) * i_s(t)` in W, `v_s` positive minus negative
terminal, SPICE current positive *into* the positive terminal; positive =
delivered to the array. Per source and instance the deck emits behavioural
nodes for `p`, `max(p, 0)` and `max(-p, 0)` and integrates them with
`.meas tran INTEG` over [`t_start`, `t_end`] = [5, 34] ns: **net**, **gross
delivered** and **recovered** energy in J, plus the **charge** integral of
`i_s`. Negative net values are kept, never clipped.

**Return path.** Ground node 0 is the common return of every source and is
not itself a source; each port is therefore counted exactly once. GND and
vsubs return through 0 V sources: they exchange no energy (`p = -0 * i`),
and their charge is reported.

**Integration method (pinned).** `.options method=trap gmin=1e-15
abstol=1e-15 chgtol=1e-18` (defaults are of the order of the fA hold
currents), `tran 10p 45n 0 20p uic`; `.meas INTEG` is trapezoidal over the
accepted time points. Convergence: the same deck at `tran 10p 45n 0 5p uic`
(`request_fine.json`); target <= 1 % on every point's net active energy and
incremental energy, and the same restore classification. The power nodes are
in W, unscaled: a 1e12 (pW) scaling was tried in the local debug probe and
made the initial timepoint fail to converge.

**Calculation controls.** (a) per source `net = gross - recovered`
(checked); (b) for every DC source `E_net = -V * Q` from the independent
charge integral (catches a sign inversion or a channel swapped between
instances); (c) `nop_c - idl_c` ~ 0 and `nop_c` flagged unrestored; (d) in
the unit tests: a resistor load (`V^2/R x T`), a source that returns energy
(`net = delivered - recovered`), an exact zero-crossing split, an inverted
polarity, a missing channel, non-monotonic / missing time data and a
mixed-instance value, all against analytic fixtures.

**Idle and incremental energy.** `E_refresh_incremental = E_active_net -
E_idle_net` (same corner, pattern, window); both raw terms are kept. Idle
hold power = `E_idle_net / 29 ns`, reported net and gross. Initialisation
(0..5 ns) and the reference write are excluded.

**Endpoint state (disclosed).** This is an *aged-state restore*, not a
periodic steady state: row 0 starts at 0.9 V / 0 V and ends at its restored
level, so part of the delivered energy is stored on the SNs at `t_end`. The
analyzer reports `sum 1/2 C_SN (V_end^2 - V_start^2)` over all 16 cells
(`C_SN` = 0.605354 fF, layout-extracted single-cell value, linear-capacitor
ASSUMPTION) for active and idle. The bitlines end at their standby levels.

## Restore and failure classification (ASSUMPTIONS from #110)

* read correct: `V(RBL_c) < VREF` for a stored '1', `> VREF` for a '0', at
  `t_en` (VREF = 0.8 V).
* restored '1': read correct and `SN(t_end) >= 0.95 x SN_ref_c`, where
  `SN_ref_c` is the in-deck reference write of the **same corner and column**.
* restored '0': read correct and `SN(t_end) <= 50 mV`.
* a (corner, pattern) point is a **successful refresh** only if all four
  row-0 cells are restored. Failed points keep their energies in the CSVs but
  are excluded from successful-cost maxima and from scaling.
* unselected-row disturbance: max over rows 1-3 of `|SN_act(t_end) -
  SN_idle(t_end)|` and of `|SN_act(t_end) - SN_act(t_start)|`.

## Scaling (ASSUMPTIONS; not simulated geometry)

`E_row` is for the four-column selected row; power is reported for the
16-cell reference array and scaled as

```
P_total = N_rows * E_row_incremental / refresh_interval  +  N_rows * (P_idle_16 / 4)
```

(the idle term added exactly once; `E_row_incremental` already excludes it).
`N_rows` = 4 .. 1024 (powers of two, the refresh-overhead grid), fixed
four-column width. Intervals are read from
[`sim/retention/results/retention_results.csv`](../retention/results/retention_results.csv)
via `refresh_overhead.load_worst_case_retention()`, not retyped: **5.03 us**
(ratified basis, ASSUMED `C_SN`) and **2.75 us** (extracted `C_SN`, newer,
unratified). Linear scaling in rows is an ASSUMPTION: height-dependent
bitline loading (a taller column has a longer, heavier RBL/WBL) is ignored.
Duty factor = `N_rows x t_row_refresh_op / interval`; a configuration with
duty >= 1 is **flagged infeasible** (refresh operations would overlap), not
reported as a power.

Evidence chain behind the interval: device leakage at the worst-case corner
([`sim/leakage`](../leakage/README.md)) -> storage-node capacitance (ASSUMED
margin factor, ratified; or layout-extracted, unratified) -> retention
derivation ([`sim/retention`](../retention/README.md)) -> interval =
`t_retention / 2` (ASSUMED margin, spec Section 7) -> refresh power above.

## How it was run (host rules)

* Each request is **one `klt sim` request on the batch fleet**; nothing was
  looped locally. Main grid: fleet job **`klt-sim-428eb23d9a2b`** (m7i.4xlarge,
  spot, 106 s, 10/10 corners pass). Convergence repeat: fleet job
  **`klt-sim-4380e2ec6bd1`** (c7i.4xlarge, spot, 180 s, 10/10 pass). Both
  recorded in `environment.remote` of the committed reports.
* Before those, the fleet refused the main request five times and the fine
  request twice with `no capacity in any of the 30 pools after 3 attempt(s)`
  (Spot pool capacity; the fleet was at 5 of its 8-instance cap). Each was
  resubmitted unchanged; no local fallback occurred. The refusal is already
  tracked upstream (klayout-tools #3008, #2869).
* **Local single-corner debug probes** (tt/27 C, `--backend local`,
  ngspice-42; scratch, not evidence): (1) validated the deck and found that
  pW-scaled power nodes fail the initial timepoint (W nodes used instead);
  (2) re-ran with `gmin=1e-18`, which cut the 27 C all-zero idle energy from
  ~3.1e-21 J to ~1.2e-21 J and left the active energies unchanged (see the
  idle numerical floor below).
* Client: `uvx --from klayout-tools==0.6.0 klt` (the version the fleet runner
  accepts, as for #110/#98); no host tool was changed. Friction filed:
  klayout-tools **#3033** (no first-class per-source energy measurement) and
  **#3034** (no way to repeat a grid at a finer time step inside one request,
  so the convergence repeat is a second job).
* The committed reports are gzip-compressed with the job bucket name redacted
  (`<redacted-bucket>`); otherwise they are the unmodified klt output.

## Evidence (append-only)

Main run `20261010T055142Z`, fine run `fine_20261010T055550Z`; deck sha256
`9f34e7b150a74f9168c4dd481b32e5ea9e1b3af850e0dfff2c90c8af83d8ce15` (same in
both reports, equal to the committed `refresh_energy.spice`), model library
sha256 `48de7c67...133c84`, ngspice-46, open_pdks per
[`docs/pdk-pin.md`](../../docs/pdk-pin.md).

* `results/klt_report_20261010T055142Z.json.gz`: raw main report (980 measurements x 10 corners)
* `results/klt_report_fine_20261010T055550Z.json.gz`: raw 5 ps convergence report
* `results/refresh_energy_sources_20261010T055142Z.csv`: 1620 rows, one per (corner, energy instance, source): net / gross / recovered J, charge, waveform, both checks
* `results/refresh_energy_points_20261010T055142Z.csv`: 40 rows (10 points x 4 patterns): active / idle / incremental energy, idle power, restore classification, disturbance, endpoint stored-energy delta, convergence
* `results/refresh_energy_scaling_20261010T055142Z.csv`: scoped scaling rows (envelope + per-corner worst pattern, both intervals, N_rows 4..1024, duty factor, feasibility)
* `results/refresh_energy_summary_20261010T055142Z.json`: maxima, 125 C list, failures, controls, convergence, boundary inventory, adaptations, evidence chain, input hashes, claims flags

All six are registered in [`../append_only_inventory.txt`](../append_only_inventory.txt).
Rerun with **new** run ids, never edit these. Reproduce the reduction with
`python3 -I sim/refresh-energy/analyze_refresh_energy.py <main.json.gz> <fine.json.gz>`
on copies in a scratch directory (`test_refresh_energy.py` does exactly that).

## Results

### Incremental row-refresh energy `E_row_incremental` (J), all ten points

`*` = not converged to 1 % between the 20 ps and 5 ps runs; UNRESOLVED =
restore classification differs between the two runs (excluded from successful
costs). Gross / recovered are the all-one active totals. Idle power is the
16-cell array, maximum over patterns; "(floor)" = every pattern at or below
the gmin numerical floor (below).

| Corner | T (C) | all-one | checkerboard | inv. checkerboard | all-zero | all-one gross / recovered | idle P (W) | min '1' restore ratio | max '0' end (V) | max unselected dV vs idle (V) |
|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|
| tt | 27 | 8.61e-13 | 2.11e-13 | 2.11e-13 | 6.93e-17 * | 8.95e-13 / 3.4e-14 | 1.71e-13 (floor) | 0.9577 | 0.0315 | 3.4e-06 |
| ss | 27 | 3.60e-13 | 8.89e-14 | 8.88e-14 | 1.18e-16 * | 3.98e-13 / 3.83e-14 | 1.13e-13 (floor) | 0.9580 | 0.0116 | 5.0e-06 |
| ff | 27 | 1.66e-12 | 4.27e-13 | 4.25e-13 | 6.71e-17 * | 1.69e-12 / 3.2e-14 | 8.09e-13 | 0.9573 | 0.0430 | 4.0e-05 |
| sf | 27 | 2.08e-12 | 5.39e-13 UNRESOLVED | 5.36e-13 | 6.55e-17 UNRESOLVED * | 2.11e-12 / 3.03e-14 | 1.52e-12 | 0.9582 | 0.0505 | 8.8e-05 |
| fs | 27 | 2.15e-13 | 5.26e-14 | 5.25e-14 | 1.08e-16 * | 2.49e-13 / 3.5e-14 | 1.15e-13 (floor) | 0.9579 | 0.0142 | 2.0e-06 |
| tt | 125 | 1.21e-12 | 3.09e-13 | 3.08e-13 | 9.83e-17 * | 1.25e-12 / 3.29e-14 | 5.07e-10 | 0.9548 | 0.0285 | 1.0e-03 |
| ss | 125 | 6.24e-13 | 1.59e-13 | 1.59e-13 | 1.11e-16 * | 6.58e-13 / 3.41e-14 | 4.85e-10 | 0.9536 | 0.0095 | 4.5e-04 |
| ff | 125 | 2.09e-12 | 5.53e-13 | 5.50e-13 | 1.01e-16 * | 2.13e-12 / 3.41e-14 | 6.30e-10 | 0.9554 | 0.0426 | 3.8e-03 |
| sf | 125 | **2.46e-12** | 6.67e-13 | 6.62e-13 | 9.91e-17 * | 2.51e-12 / 4.3e-14 | **7.19e-10** | 0.9560 | 0.0461 | 6.0e-03 |
| fs | 125 | 4.58e-13 | 1.10e-13 | 1.10e-13 | 1.08e-16 * | 4.92e-13 / 3.37e-14 | 4.87e-10 | 0.9540 | 0.0111 | 4.2e-04 |

**Measured maxima over all ten points and four patterns (successful refreshes
only):** `E_row_incremental` = **2.46 pJ** at **sf / 125 C, all-one**
(`E_active_net` 2.46 pJ, gross 2.51 pJ, recovered 0.043 pJ, `E_idle_net`
2.1e-17 J over the 29 ns window). Idle hold power (16 cells) maximum =
**0.72 nW** at sf / 125 C, all-one. Here the maximum *is* at the hottest
temperature, but that was measured, not assumed: at 27 C the largest point is
sf, not ss or fs, and ff/27 C (1.66 pJ) exceeds tt, ss and fs at 125 C.

**125 C results, listed separately:** the 125 C row group above (5 corners x 4
patterns, all restored; all-zero not converged). Largest 125 C value per
pattern: all-one 2.46 pJ (sf), checkerboard 0.667 pJ (sf), inverse
checkerboard 0.662 pJ (sf), all-zero ~1e-16 J (unresolved residual).

### Where the energy goes: deselected-row read-path current

At the maximum point, **99.0 %** of the net active energy (2.44 pJ) is
delivered by the three **deselected** RWL drivers (held at VDD), 1.2 % by the
selected RWL, and the precharge, WBL and WWL sources are each below 0.5 %
in net terms (the precharge source *recovers* net charge: -9.9 fJ net,
7.0 fJ gross). Mechanism: once a stored '1' on row 0 discharges RBL, every
**unselected** cell on that column that also stores a '1' (SN 0.9 V) sees
its read device turn on with RBL as the source (Vgs ~ 0.9 V - V(RBL)), and
conducts from its deselected RWL (1.8 V) into the floating RBL until the
release reconnects the precharge. That is why all-one (three such cells per
column, four columns) costs ~4x the checkerboards (one such cell on each of
two columns), why all-zero costs nothing measurable, and why the read RBL of
a '1' only falls to ~0.2 V rather than 0 V (read margin to VREF 0.23-0.56 V,
'0' columns 0.074-0.081 V). This is an array-boundary energy that a real
periphery would also pay (a latch pulling RBL to 0 V would make the
unselected devices conduct harder). Its duration here is set by the replay's
floating-RBL interval (~23 ns); a shorter sense/write sequence would cut it.

### Restore, failures and disturbance

* Every stored '1' was read correctly and restored to >= 0.9536 x `SN_ref` at
  every point (lowest: ss/125 C); every '0' read correctly.
* **sf / 27 C, all-zero and checkerboard: UNRESOLVED.** Column 3's '0' ends
  at 50.54 mV in the 20 ps run (FAILED against the 50 mV ASSUMPTION) and at
  44.4 mV in the 5 ps run (restored). Neither counted as a successful refresh
  nor as a clean failure; excluded from the maxima and the scaling. The '0'
  ends positive because the RWL0 release edge couples the SN up after WWL0
  has closed (same sequence as #110). All other points are restored at both
  resolutions.
* **The stored-'0' end level is resolution-sensitive by up to 6.2 mV**
  (largest at sf / 27 C; stored-'1' end levels and `SN_ref` move by
  <= 0.13 mV). Three restored points have a '0' within that distance of the
  50 mV ceiling: sf / 125 C (46.1 mV), ff / 27 C (43.0 mV), ff / 125 C
  (42.6 mV). They agree at both resolutions but their '0' margin is of the
  same size as this numerical sensitivity.
* The `nop_c` control is flagged unrestored at every corner (no refresh
  without pulses), as required.
* Unselected rows 1-3: largest `|SN_act - SN_idle|` at `t_end` = **6.0 mV**
  (sf / 125 C, checkerboards; < 0.7 % of `delta_V` = 0.9 V); <= 0.09 mV at 27 C.

### Idle hold power and its numerical floor

The 125 C idle power of the 16-cell array is 0.44-0.72 nW (all corners and
patterns, converged to <= 0.0002 %). At 27 C the idle measurement is at the
**solver's numerical floor**: ngspice shunts every junction with `gmin` =
1e-15 S, which can account for up to 2 x 32 x gmin x VDD^2 = **2.1e-13 W**.
14 of the 20 points at 27 C are at or below that bound (`idle_at_gmin_floor`
in the CSV); the gmin-lowered debug probe confirmed most of the tt/27 C
all-zero value is gmin. Read the 27 C idle numbers as upper bounds, not
measured leakage. (ff and sf at 27 C, 0.4-1.5 pW, are above the floor.)

### Calculation controls and convergence

* `net = gross - recovered`: holds for every source of every instance in both
  runs. `E = -V * Q` against the independent charge integral: holds for every
  DC source in both runs.
* `nop_c - idl_c`: <= 9.1e-11 of the corresponding active energy.
* Convergence (20 ps vs 5 ps max step): all-one / checkerboard /
  inverse-checkerboard incremental energies agree to <= 0.32 % at all ten
  points (target 1 %); idle to <= 0.23 % (27 C, at the gmin floor) and
  <= 0.0002 % at 125 C. **All-zero does not converge** (5-30 %): its net
  (6-12e-17 J) is a 0.5-1 % residual of nearly equal gross and recovered
  wordline-coupling terms (~1.3e-14 J each), so its absolute uncertainty is
  ~3e-17 J, about 1e-5 of the grid maximum. It is reported, not used for any
  maximum. Restore classification agrees at 38 of 40 points (the two sf/27 C
  points above).
* No negative incremental energy occurred; the analyzer would keep one.
* Endpoint stored-energy disclosure: the change of SN electrostatic energy
  (all 16 cells, `C_SN` = 0.605 fF) over the window is <= 2.1 fJ, at most
  0.33 % of `E_active_net` for the all-one refreshes (per point in the CSV).

### Scoped power scaling (ASSUMPTIONS; not macro power)

16-cell reference array (4 rows x 4 columns), grid-maximum energy and idle
(sf / 125 C, all-one): `P_refresh` = 4 x 2.46 pJ / interval = **1.96 uW** at
5.03 us (ratified basis) or **3.58 uW** at 2.75 us (extracted `C_SN`,
unratified), plus idle **0.72 nW**. Refresh dominates standby by more than
three orders of magnitude at 125 C.

Envelope scaled linearly (four-column rows, `t_row` = 27 ns):

| N_rows | `P_total` @ 5.03 us | duty @ 5.03 us | `P_total` @ 2.75 us | duty @ 2.75 us |
|---:|---:|---:|---:|---:|
| 4 | 1.96 uW | 2.1 % | 3.58 uW | 3.9 % |
| 16 | 7.84 uW | 8.6 % | 14.3 uW | 15.7 % |
| 64 | 31.3 uW | 34.4 % | 57.3 uW | 62.8 % |
| 128 | 62.7 uW | 68.7 % | **infeasible** | 125.6 % |
| 256 | **infeasible** | 137.4 % | **infeasible** | 251.2 % |
| 512, 1024 | **infeasible** | > 100 % | **infeasible** | > 100 % |

Infeasible = the refresh operations would overlap within one interval (duty
>= 100 %); no power is claimed for them. Duty above the PROPOSED 50 % limit
of pass condition 3c (an ASSUMPTION) is a separate reading, already covered
by `sim/refresh-overhead`.

**Why the linear scaling probably understates taller arrays.** The dominant
term is the deselected-row read-path current, which is paid by every
*unselected* stored '1' on a column whose RBL is discharged. In an N-row
column there are N-1 such cells, not 3, so `E_row` itself grows with column
height; together with the heavier bitline that the linear model already
ignores, `P_refresh` for N_rows > 4 should be read as a *lower* estimate under
these assumptions, not as a bound. Simulating taller extracted columns is
outside this increment.

## Not shown / limits

Not shown: sense-latch, reference, controller, driver and distribution
energy; any periphery; real (non-ideal) drivers, so charge an ideal source
recovers here may be dissipated in a real one; a latch-driven RBL; boosted
or negative wordlines; supplies other than 1.8 V and temperatures outside
{27, 125} C; mismatch or Monte Carlo; periodic steady state (this is a single
aged-state restore); refresh of rows other than row 0; timing optimisation
(sense and write-back fixed at 10 ns); taller or wider extracted arrays.
Nothing here is a full-macro power figure, a statistical-yield claim, or an
SRAM comparison, and no spec file was changed.
