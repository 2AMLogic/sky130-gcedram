# Cold-corner stored-level failure: attribution and remedy comparison (issue #47)

Epic #24 phase 3. This gate sits between Phase 2 (the loaded-column
characterization in [`../README.md`](../README.md), issue #45) and any
sense-amplifier work. Phase 2 found that at `fs / -40 C` the stored '1' is
only ~0.864 V, the worst-case column separation is 0.017-0.018 V, and the
0.1 V `rbl` droop is never reached in 32 of 128 stored-'1' points. `ss / -40 C`
is marginal. This directory reproduces that failure, attributes it, compares
remedies, and proposes a next design contract.

**What this is not:** it does not implement a sense amplifier or validate
offset or yield, and it does not change or ratify any spec value. All
Phase 2 evidence (`../results/`) is unchanged; this directory only adds
files. Every failing variant and both negative controls are kept in the
evidence.

## Files

| File | Role |
|---|---|
| [`variants.py`](variants.py) | Declared variant set. Each variant is the Phase 2 baseline with one named knob changed, plus its scope (which points it runs at). The pass criteria are defined here. |
| [`tb_cold_variant.spice.tmpl`](tb_cold_variant.spice.tmpl) | The Phase 2 deck with the knobs exposed (`VWL`, `TWPULSE`, `VRWL_SEL`, `C_RBL`, device cards, and the attribution-only `FORCE/VSN1` mode) |
| [`run_variants.py`](run_variants.py) | Variant runner. It imports the Phase 2 runner's waveform reader and `measure()` unchanged and adds `v_sn_sel_sense_v` (selected `sn` at the sense instant). |
| [`extract_vth.py`](extract_vth.py) | Constant-current Vth of `nfet_01v8` / `nfet_01v8_lvt` at the bitcell W/L, all 15 points, at Vsb = 0 and 0.9 V |
| [`analyze_variants.py`](analyze_variants.py) | Coverage/provenance, reproduction check, per-point PASS/FAIL, negative-control check, gates, summary JSON + pass/fail CSV |
| [`test_variants.py`](test_variants.py) | Tests: coverage/provenance/knob drift, criteria, reproduction tolerance, negative controls, impossible threshold (synthetic and committed data) |
| `results/phase2_reproduction.csv` | Append-only. The **unchanged** Phase 2 runner re-run at fs and ss, -40 C, both ages (256 points) |
| `results/variant_results.csv` | Append-only. Run `20261005T135553Z` holds the harness baseline, the attribution variants and the negative control (3456 points). Run `20261005T141748Z` holds the remedies (6720 points). |
| `results/vth_results.csv` | Append-only. Device Vth (60 rows) |
| `results/summary_20261005T145658Z.json`, `results/pass_fail_20261005T145658Z.csv` | Machine-readable analysis of all of the above, including Phase 2 re-evaluated against the same criteria as pseudo-variant `phase2_baseline` |

## Provenance

* **Source and models**: the bitcell device cards are parsed from
  [`design/gain_cell_2t.spice`](../../../design/gain_cell_2t.spice), and
  connectivity comes from `layout/array_topology.py`, both through the Phase 2
  runner. The storage-node capacitance is the extracted 0.605354 fF. The
  models are the shipped sky130 combined ngspice library at open_pdks
  `c6d73a35f524070e85faff4a6a9eef49553ebc2b` (`sky130A`), with no edits. The
  only other flavour used is the PDK's own `sky130_fd_pr__nfet_01v8_lvt`.
* **Tool**: ngspice-46 and Python 3 stdlib. Every row is stamped with
  `run_id`, `timestamp_utc`, `repo_git_sha`, `pdk_open_pdks_commit` and
  `ngspice_version`. Variant rows also carry `variant_sha` (a hash of the full
  knob set and scope), `template_sha`, `changed_knobs` and every knob value.
  `repo_git_sha` is `2b7fee1` (the branch base) on every row. The harness
  that produced the rows is committed on this branch. `run_variants.py` and
  the template have not changed since those runs (`template_sha`
  `f47cd6ea234b0a61`). The analyzer rejects any row whose `variant_sha` does
  not match the current definition, so a knob edit after a run cannot pass
  silently.
* **Load and timing**: identical to Phase 2 unless a variant names the knob:
  `C_RBL` = 10 fF (assumed, not extracted), `t_sense` = 10 ns after the
  select edge, 0.1 V latency droop, 20 ns write pulse, fresh read at 110 ns,
  aged read at row 0 write end + 5.029945 us (the ratified refresh bound,
  [`spec/retention-refresh-budget.md`](../../../spec/retention-refresh-budget.md)
  section 7). Each point covers 4 selected rows x 16 stored patterns, so
  every row sees both stored values under all 8 other-row patterns.
* **Run cost**: the reproduction took ~7.5 min with 8 jobs. The attribution
  run took ~22 min with 8 jobs, and the remedies took ~38 min with 14 jobs.
  All ran on a shared 18-core host at load ~30. There were 0
  `sim_failed` points in any run.

### Pass criteria (study ASSUMPTIONS, not spec values)

Each (variant, corner, temperature, age) point is evaluated over all 64
cases. A point PASSES only if all four of these hold:

1. **separation**: column-wide worst-case signed separation
   `min V(rbl | 0) - max V(rbl | 1)` at `t_sense` is >= `SEP_MIN_V` = 0.1 V.
   The sign convention is Phase 2's (positive means a '1' discharged `rbl`
   further).
2. **latency**: every stored-'1' case reaches the 0.1 V droop no later than
   `t_sense`.
3. **read disturb**: |read disturb| on the selected `sn` and the worst
   unselected `sn` is <= `DISTURB_MAX_V` = 0.1 V.
4. **complete**: 64/64 cases were simulated.

0.1 V is a placeholder until a sense circuit has an offset budget. All raw
values are in the CSV/JSON, so a different threshold can be re-applied
without re-simulating.

## Reproduce

```bash
python3 sim/loaded-column/cold-corner/run_variants.py --check-env
# 1. Phase 2 failure, with the UNCHANGED Phase 2 runner
python3 sim/loaded-column/run_loaded_column.py --corners fs ss --temps-c -40 \
    --results-csv sim/loaded-column/cold-corner/results/phase2_reproduction.csv
# 2. attribution + harness baseline + negative control (cold points)
python3 sim/loaded-column/cold-corner/run_variants.py --variants $(python3 sim/loaded-column/cold-corner/run_variants.py --list | awk '$1 !~ /^rem_/ {print $1}')
# 3. remedies (full 15-point grid, both ages; rem_rd_lvt fresh-only)
python3 sim/loaded-column/cold-corner/run_variants.py --variants rem_vwl_2p0 rem_rwl_m0p2 rem_wr_lvt rem_rd_lvt
# 4. device thresholds
python3 sim/loaded-column/cold-corner/extract_vth.py
# analysis, gates, tests
python3 sim/loaded-column/cold-corner/analyze_variants.py                       # exit 0
python3 sim/loaded-column/cold-corner/analyze_variants.py --no-summary --require-pass rem_vwl_2p0 rem_rwl_m0p2   # exit 0
python3 sim/loaded-column/cold-corner/analyze_variants.py --no-summary --require-pass phase2_baseline           # exit 2 (fs/-40 C fails)
python3 sim/loaded-column/cold-corner/analyze_variants.py --no-summary --min-separation-v 50                    # exit 2 (impossible)
python3 sim/loaded-column/cold-corner/test_variants.py
```

Analyzer exit codes:

* **0**: coverage, provenance, reproduction and negative-control checks all pass.
* **1**: a point is missing or duplicated, provenance is missing, a
  `variant_sha` has drifted, the reproduction check fails, or a negative
  control passes.
* **2**: a requested gate (`--min-separation-v`, `--require-pass`) is not met.

Failing engineering points are reported, and they do not by themselves
change the exit code.

## 1. Reproduction of the Phase 2 failure

* **Unchanged Phase 2 runner**: all 256 fs/ss -40 C points (both ages, every
  row and pattern) are **bit-identical** to the committed run
  `20261005T102906Z` in every measured field.
* **Variant harness baseline**: the same 256 points re-rendered through
  `tb_cold_variant.spice.tmpl` match Phase 2 to within one unit in the last
  written digit (worst relative difference 7.3e-7). 104/256 rows are
  bit-identical. The remaining rows differ only by rounding from
  equal-valued parameter expressions. The analyzer enforces a relative
  tolerance of 2e-6, and a 1e-4 change fails it (tested).
* **Re-evaluated against the criteria above**: Phase 2 passes **28/30**
  points. **fs/-40 C fails at both ages** on separation (0.018 / 0.017 V)
  and latency (32 stored-'1' cases never reach the droop). ss/-40 C passes,
  but only just: separation is 0.121 / 0.113 V (fresh / aged) against the
  0.1 V criterion, and the slowest latency is 7.9 / 8.6 ns against
  `t_sense` = 10 ns.

## 2. Attribution: what limits the cold point

### 2a. The stored-'1' level chain at fs/-40 C (baseline)

These are minimums over the 32 stored-'1' cases.

| Stage | fs/-40 C | ss/-40 C | Mechanism |
|---|---:|---:|---|
| Write-wordline high level | 1.800 V | 1.800 V | Phase 2 write drive |
| `sn` at the start of the wordline fall | 1.011 V | 1.041 V | `M_WR` is a source follower and cuts off near `VWL - Vth(Vsb ~ sn)`. Vth(Vsb = 0.9 V) is 1.001 / 0.969 V (`vth_results.csv`). |
| `sn` after the wordline fall | 0.864 V | 0.896 V | Wordline feedthrough and channel-charge injection: -0.147 / -0.145 V |
| `sn` before the read at the refresh bound | 0.860 V | 0.893 V | Hold leakage at -40 C is negligible (-0.004 V) |
| `sn` at the sense instant | 0.714 V | 0.736 V | The read wordline falls 1.8 -> 0 V and couples `sn` down through `M_RD`: -0.150 / -0.160 V |
| Read-device Vth (Vsb = 0) | 0.862 V | 0.823 V | `vth_results.csv` |
| **Read Vgs - Vth at sense** | **-0.148 V** | **-0.087 V** | Subthreshold read, so `rbl` moves ~0.02 V in 10 ns |

### 2b. One-assumption-at-a-time sweeps

All cases are fresh, all 4 rows x 16 patterns per point. Stored '1' is the
pre-read and at-sense minimum. Source: `summary_20261005T145658Z.json`.

| Variant | Changed knob | fs/-40 sep (V) | fs/-40 stored '1' pre-read / at sense (V) | fs/-40 max latency | ss/-40 sep (V) | ss/-40 max latency | PASS fs / ss |
|---|---|---:|---:|---:|---:|---:|---|
| `baseline` | (none) | 0.018 | 0.864 / 0.714 | not reached (32/32) | 0.121 | 7.92 ns | FAIL / PASS |
| `attr_vwl_2p0` | write WL 2.0 V | 0.431 | 1.024 / 0.830 | 1.49 ns | 0.679 | 0.54 ns | PASS / PASS |
| `attr_vwl_2p2` | write WL 2.2 V | 0.658 | 1.184 / 0.930 | 0.24 ns | 0.647 | 0.17 ns | PASS / PASS |
| `attr_vwl_2p4` | write WL 2.4 V | 0.612 | 1.344 / 1.061 | 0.13 ns | 0.586 | 0.12 ns | PASS / PASS |
| `attr_twpulse_40n` | write pulse 40 ns | 0.030 | 0.881 / 0.730 | not reached (32/32) | 0.165 | 5.50 ns | FAIL / PASS |
| `attr_twpulse_100n` | write pulse 100 ns | 0.054 | 0.904 / 0.749 | 19.74 ns | 0.233 | 3.59 ns | FAIL / PASS |
| `attr_wr_lvt` | `M_WR` low-Vt | 0.206 | 0.977 / 0.798 | 4.11 ns | 0.540 | 1.05 ns | PASS / PASS |
| `attr_rd_w_0p84` | `M_RD` W 0.84 um | 0.029 | 0.887 / 0.647 | not reached (32/32) | 0.128 | 7.10 ns | FAIL / PASS |
| `attr_rd_w_1p68` | `M_RD` W 1.68 um | 0.012 | 0.912 / 0.576 | not reached (32/32) | 0.046 | not reached (32/32) | FAIL / FAIL |
| `attr_rd_lvt` | `M_RD` low-Vt | 0.103 | 0.858 / 0.695 | 9.61 ns | 0.395 | 1.68 ns | PASS / PASS |
| `attr_rwl_m0p2` | selected RWL -0.2 V | 0.872 | 0.864 / 0.615 | 0.44 ns | 0.863 | 0.24 ns | PASS / PASS |
| `attr_rwl_m0p4` | selected RWL -0.4 V | 1.015 | 0.864 / 0.534 | 0.12 ns | 0.989 | 0.12 ns | PASS / PASS |
| `attr_crbl_5f` | `C_RBL` 5 fF | 0.032 | 0.864 / 0.713 | not reached (32/32) | 0.194 | 4.44 ns | FAIL / PASS |
| `attr_crbl_20f` | `C_RBL` 20 fF | 0.010 | 0.864 / 0.714 | not reached (32/32) | 0.070 | 14.87 ns | FAIL / FAIL |
| `attr_crbl_40f` | `C_RBL` 40 fF | 0.005 | 0.864 / 0.715 | not reached (32/32) | 0.038 | not reached (32/32) | FAIL / FAIL |
| `attr_tsense_5n` | `t_sense` 5 ns | 0.009 | 0.864 / 0.715 | not reached (32/32) | 0.065 | 7.92 ns | FAIL / FAIL |
| `attr_tsense_15n` | `t_sense` 15 ns | 0.027 | 0.864 / 0.713 | not reached (32/32) | 0.170 | 7.92 ns | FAIL / PASS |
| `attr_tsense_19n` | `t_sense` 19 ns | 0.034 | 0.864 / 0.713 | not reached (32/32) | 0.204 | 7.92 ns | FAIL / PASS |

Read-path transfer with the write bypassed: each `sn` is initialised to
`VSN1` for a '1' or 0 V for a '0', and the read is otherwise identical.

| Forced stored '1' | 0.8 V | 0.9 V | 1.0 V | 1.1 V | 1.2 V | 1.4 V | 1.8 V |
|---|---:|---:|---:|---:|---:|---:|---:|
| fs/-40 sep (V) | 0.003 | 0.048 | 0.323 | 0.677 | 0.655 | 0.590 | 0.386 |
| ss/-40 sep (V) | 0.011 | 0.130 | 0.512 | 0.672 | 0.652 | 0.576 | 0.366 |
| fs/-40 latency | not reached | not reached | 2.28 ns | 0.51 ns | 0.22 ns | 0.12 ns | 0.09 ns |

### 2c. Attribution result

* **Limiting mechanism.** The read device does not get enough gate
  overdrive at the slow-NMOS cold corner. Two effects lower the written
  '1':
  * `M_WR`'s body-effected threshold (Vth(Vsb = 0.9 V) = 1.00 V at fs/-40 C)
    stops the charge at ~1.01 V.
  * Wordline feedthrough then takes another ~0.15 V.

  The falling read wordline couples another ~0.15 V out of `sn` during the
  read. The read device is then ~0.15 V **below** its own threshold at the
  sense instant. ss/-40 C is the same mechanism with ~0.09 V less deficit.
* **The cold point needs a stored '1' of about 0.92-1.0 V.** In the forced
  transfer, separation crosses 0.1 V between 0.9 V (0.048 V) and 1.0 V
  (0.323 V), about 0.92 V by linear interpolation. The latency criterion is
  met at 1.0 V but not at 0.9 V. The Phase 2 write delivers 0.864 V, about
  0.06-0.14 V short. The cells written by the boosted-wordline and low-Vt
  write variants land on the same transfer curve: 0.977 V gives 0.206 V
  separation and 1.024 V gives 0.431 V.
* **Write drive and read drive are strong levers.** 0.2 V on either the
  write-wordline high level or the selected read-wordline low level
  restores >0.4 V separation.
* **Bitline load and sense time are not the cause.** Across `C_RBL` from 5
  to 40 fF and `t_sense` from 5 to 19 ns, fs/-40 C stays at 0.005-0.034 V
  separation and never reaches the droop. A subthreshold read current
  cannot be rescued by a lighter load or by waiting longer. These knobs do
  matter at the margin for ss/-40 C: it fails at 20 fF and at 5 ns.
* **Longer write pulses are weak.** A 5x longer pulse adds only 0.04 V,
  because the source follower's subthreshold tail grows only
  logarithmically with time.
* **A wider read device makes it worse.** Its larger gate couples `sn`
  further down at the read-wordline fall: `sn` at sense is 0.647 V at
  W = 0.84 um and 0.576 V at W = 1.68 um, against 0.714 V for the baseline.
  These failed variants are kept.
* **More stored level is not always better.** Above ~1.1 V the worst-case
  separation falls again (0.386 V at 1.8 V). Deselected rows storing '1'
  start sourcing current into a discharged `rbl` (pattern `1111` becomes
  the worst case). Any level-raising remedy therefore costs margin at the
  hot/fast corners (see 3).

## 3. Remedy comparison

There are two remedy classes, each with a device-flavour alternative.
Knob values are the smallest attribution step that cleared fs/-40 C. They
are not optimised. All variants except `rem_rd_lvt` ran the full
15-point x 2-age grid.

| Variant | Class | Points PASS | Min sep (point) | Common window over all 15 points x 2 ages | Hot-corner min sep (125 C) | Max latency | Max abs read disturb | Min stored '1' after write / pre-read |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `phase2_baseline` | (reference) | 28/30 | 0.017 V (fs/-40 aged) | 0.017 V | 0.515 V | not reached at fs/-40 | 0.067 V | 0.864 / 0.860 V |
| `rem_vwl_2p0` | write path: WL boost to 2.0 V | **30/30** | 0.413 V (fs/-40 aged) | **0.412 V** (centre 0.69 V, UNVALIDATED) | 0.435 V | 1.6 ns | 0.067 V | 1.024 / 1.020 V |
| `rem_rwl_m0p2` | read path: selected RWL -0.2 V | **30/30** | 0.604 V (sf/125 fresh) | **0.604 V** (centre 0.60 V, UNVALIDATED) | 0.604 V | 0.46 ns | 0.082 V | 0.864 / 0.860 V |
| `rem_wr_lvt` | write path: low-Vt `M_WR` | 26/30 **FAIL** | ~0.000 V (sf/125 aged) | none | ~0.000 V | not reached at ff/sf 125 aged | 0.113 V | 0.977 / **0.063 V** |
| `rem_rd_lvt` | read path: low-Vt `M_RD` (fresh screen only) | 15/15 fresh | 0.103 V (fs/-40 fresh) | 0.102 V | 0.465 V | 9.6 ns | 0.075 V | 0.858 / 0.858 V |

Per-point detail for every variant is in
`pass_fail_20261005T145658Z.csv`: signed separation, the worst-case
selected row and other-row pattern, latency, read disturb and the
stored-level chain.

**Tradeoffs:**

* **Write-wordline boost (`rem_vwl_2p0`)** passes every point at both
  ages, with a minimum separation of 0.41 V at fs/-40 C aged.
  * It fixes the root cause: the cold stored '1' becomes 1.02 V, above
    the ~0.92-1.0 V the read needs.
  * **Costs:**
    * A 2.0 V wordline supply (boost/charge pump or a separate rail) and
      a level-shifting WL driver.
    * The 1.8 V core `M_WR` sees up to 2.0 V gate-source during a '0'
      write. The shipped SPICE models have no oxide-reliability model, so
      this evidence cannot judge that overdrive. It needs a reliability
      source before adoption.
    * The higher stored level makes deselected '1' rows source more
      current at the sense instant (up to 38 uA vs 24 uA at sf/125 C
      fresh). This lowers the hot-corner minimum separation from 0.515 V
      to 0.435 V.
  * Hold-leakage decay at the refresh bound is larger in absolute terms
    (sf/125 C: 1.377 -> 1.086 V), but the separation still passes there.
* **Read-wordline under-drive (`rem_rwl_m0p2`)** passes every point at both
  ages, with the largest margin (min 0.60 V) and the fastest latency
  (<= 0.46 ns).
  * It does **not** raise the stored level. The cold stored '1' stays at
    0.864 V, below the `delta_V = VDD/2` reference that the ratified
    retention derivation assumes.
  * **Costs:**
    * A negative read-wordline supply and level shifter. Every selected
      row's `rwl` goes below ground for the 20 ns read.
    * The selected `M_RD` source/p-well junction is forward-biased by
      0.2 V during the read. Its current flows in `rwl` (it is included
      in the selected row's `i_into_rbl_*` column, which is therefore not
      a pure channel current for this variant) but not in `rbl`.
    * The maximum read disturb rises from 0.067 V to 0.082 V (sf/125 C),
      closer to the 0.1 V criterion.
    * A stored '1' discharges `rbl` almost to ground at cold
      (0.026-0.035 V).
* **Low-Vt write device (`rem_wr_lvt`)** is a **failed variant, kept as
  evidence.**
  * It clears fs/-40 C (0.19 V aged). But at ff and sf / 125 C the stored
    '1' decays to 0.392 V and 0.063 V by the 5.03 us refresh bound, so
    the separation collapses to ~0 V and the latency is never reached.
  * At those corners the fresh read disturb also exceeds 0.1 V (0.100 V
    and 0.113 V).
  * The storage-node leakage is incompatible with the ratified refresh
    bound. Adopting it would also invalidate the leakage link of the
    ratified retention chain, which was measured on `nfet_01v8`.
* **Low-Vt read device (`rem_rd_lvt`)** passes the fresh screen, but only
  just: 0.103 V separation and 9.6 ns latency at fs/-40 C, against 0.1 V
  and 10 ns criteria. It was not carried into the aged campaign. Phase 2
  loses ~0.001-0.008 V of separation at the bound, so it is not a
  credible standalone contract.

### Negative controls

* **`nc_write_disabled`**: the write wordline never rises, so every cell
  keeps the inverse of its intended data. The analyzer requires every
  point to FAIL with negative separation, and it reports 1 if not. Result:
  fs/-40 C -0.978 V and tt/27 C -1.169 V, both FAIL.
* **Impossible threshold**: `--min-separation-v 50` exits 2 on the
  committed evidence and on synthetic data (`test_variants.py`). The
  Phase 2 analyzer's own impossible-threshold test is unchanged and still
  passes.

## 4. Proposed next design contract (PROPOSAL, not ratified)

This proposal is for the normal two-key specification process
([`spec/`](../../../spec/README.md), with the `ratification/` keys). This
issue ratifies nothing, and no spec file is edited.

1. **Bitcell sizing and read-device flavour stay unchanged.** The evidence
   shows the cold failure is neither fixed by read-device width nor caused
   by bitline load or sense time.
2. **Adopt one supply-assisted periphery option and carry it into the
   sense-amplifier work:**
   * **Option A, write-wordline boost** (`VWL` >= 2.0 V on the write
     wordline only). It restores the stored level itself (>= 1.02 V at
     every point), which also bears on the retention budget's `delta_V`
     assumption. It is gated on a reliability justification for overdriving
     the 1.8 V `M_WR` gate.
   * **Option B, read-wordline under-drive** (selected `rwl` <= -0.2 V). It
     gives the largest measured margin (min 0.60 V, common window 0.60 V)
     with no gate overdrive. Its costs are a negative rail, a forward-biased
     source junction during the read, and an unchanged (low) stored level.

   Both options give positive usable separation (>= 0.41 V) at every
   required point under the Phase 2 assumptions. The choice is a
   periphery-supply and reliability tradeoff for the ratification keys,
   not something this simulation settles. The exact knob values (the
   smallest step tested) are proposals and would need their own
   minimum-value sweep.
3. **If neither supply can be accepted, the alternative is a clearly
   scoped limitation**: with the Phase 2 periphery the macro is
   **not functional at fs/-40 C** and marginal at ss/-40 C. That would
   have to be ratified as an operating-range restriction, for example
   excluding -40 C on the slow-NMOS corners. It must not be presented as a
   full-PVT design.
4. **Whichever is chosen, the sense work must re-verify against it.** These
   results rest on the assumed 10 fF `C_RBL`, a fixed 10 ns sense instant,
   a 4-row column, global corners (no mismatch) and the placeholder 0.1 V
   separation criterion. Extracted bitline parasitics, longer columns and
   a sense-amplifier offset budget are still required before any sense
   reference (the `common_reference_v_UNVALIDATED` values above) is used.

## Limitations

* This is a single 4-row column with schematic-level `C_RBL`, an ideal
  write driver and ideal precharge, and global process corners only.
* The fixed write order means row 0 is the oldest row.
* Remedy knob values were not minimised.
* The low-Vt read variant was screened fresh only.
* Supply-generation circuits (boost or negative pump) were not designed or
  simulated, so their area, power and settling costs are qualitative here.
* `M_WR` gate overdrive (option A) cannot be judged from SPICE models.
* No klayout-tools friction arose: this increment is simulation-only.
