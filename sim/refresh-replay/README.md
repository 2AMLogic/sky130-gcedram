# RTL-strobe replay: does the phase-sequencer REFRESH waveform restore data? (issues #128, #131)

Epic #24 item 3 / integration prerequisite for item 6. The phase sequencer
([`digital/phase-control`](../../digital/phase-control/CONTRACT.md)) and the closed-loop refresh study
([`sim/refresh-op`](../refresh-op/README.md)) use different waveforms, so their separate passes do not show that
controller-driven refresh restores data. This study exports the **actual edges** of one `phase_seq` REFRESH,
converts them deterministically to PWL sources and replays them in the **same circuit** as `sim/refresh-op`.
**PROPOSED, unratified scope** (27/125 C, tt/ss/ff/sf/fs, 1.8 V, no mismatch, ideal drivers). No spec,
contract, scheduler timing, overlap rule or prior result was changed. 1 cycle = 1 ns is a study assumption.

## Headline result (run `20261010T094617Z`)

**The unmodified RTL waveform does not restore the stored level at any of the 10 corners** (0/10 at restore
fractions 0.90, 0.95 and 0.98), with or without the explicit latch-hold adapter. The latch decision itself is
correct everywhere (10/10, all four patterns), the PWL conversion is valid (10/10), and the matched baseline
(the existing analog sequence at SENSE 10 ns / WWL 20 ns, same deck) restores at 10/10 and agrees with the prior
`sim/refresh-op` report to 1e-5 V. The failure is preserved, not tuned away; see "Proposed follow-up".

Stored '1' pre-read 0.9 V, SN(end) in V (SN_ref = in-deck reference write; fraction of SN_ref in brackets):

| Corner | T (C) | SN_ref | baseline analog | RTL + latch-hold adapter | RTL raw (1-cycle sample pulse) |
|---|---:|---:|---:|---:|---:|
| tt | 27 | 1.284 | 1.325 (1.03) | 1.112 (0.866) | 1.015 (0.790) |
| tt | 125 | 1.410 | 1.463 | 1.229 (0.872) | 1.105 (0.784) |
| ss | 27 | 1.179 | 1.202 | 1.024 (0.868) | 0.969 (0.822) |
| ss | 125 | 1.295 | 1.328 | 1.128 (0.871) | 1.039 (0.802) |
| ff | 27 | 1.377 | 1.437 | 1.192 (0.866) | 1.063 (0.772) |
| ff | 125 | 1.508 | 1.584 | 1.317 (0.873) | 1.156 (0.767) |
| sf | 27 | 1.436 | 1.505 | 1.249 (0.870) | 1.104 (0.768) |
| sf | 125 | 1.563 | 1.644 | 1.366 (0.874) | 1.180 (0.755) |
| fs | 27 | 1.138 | 1.154 | 0.988 (0.868) | 0.957 (0.841) |
| fs | 125 | 1.262 | 1.291 | 1.098 (0.870) | 1.020 (0.808) |

All four patterns are in `results/20261010T094617Z/points.csv` (stored '1' at 0.9 V and 1.0 V, stored '0' at
-0.1 V and 0.0 V). Stored '0' is "restored" by the sim/refresh-op criterion (<= 50 mV) in every RTL variant, but note it
ends at about **-0.11 to -0.14 V** (baseline: ~0 V): a signed observation worth knowing, not a failure of the criterion.

What the probes show (diagnostic, not an isolated cause): with the hold adapter the WBL is driven to 1.8 V and
SN just before WWL falls (1.08-1.37 V) is close to the baseline's value at the same point. In the baseline SN
then *rises* 0.08-0.27 V after WWL falls (RWL, still held low, is released afterwards); in the RTL sequence RWL
was released 20 ns earlier, WWL falls last and SN *drops* by 0.01-0.10 V. In the raw variant the 1 ns enable
lets the latch decide but then floats: the latch complement node shares charge with WBL
(WBL 1.28-1.36 V before WWL falls instead of 1.8 V). Whether the RWL-hold ordering or the WWL-fall
feedthrough dominates was **not** isolated; that needs a separate experiment.

## Release-order attribution experiment (issue #131, run `20261010T130000Z`)

Question left open above: is the restoration failure caused by the RWL release ordering, by the latch-enable
release, or by ideal-driver coupling? The RTL, `CONTRACT.md`, scheduler defaults, restoration criteria
(0.90/0.95/0.98 of the in-deck SN_ref; stored '0' <= 50 mV) and the circuit are unchanged. Five **experimental**
waveforms were added to the same deck (10 variants x 4 patterns + reference write = 41 instances, 5 corners x
27/125 C, 1.8 V). They are experiments, **not** approved overlap-rule changes. Run-pinned provenance as before
(klt 0.6.0, ngspice 46, model lib sha256 `48de7c67...133c84`, open_pdks `c6d73a35...`; deck sha256 equals klt's
`netlist_sha256`). Ten of ten corners simulated for every variant; failures are preserved in `points.csv` and `summary.json`.

| Variant | Parent | Only change (verified: `consistency_check.json` -> `experiment_diff`) |
|---|---|---|
| `rwl_late_raw` | `rtl_raw` | RWL release 12 -> 34 ns (2 ns after WWL falls at 32; coincident with BL-drive release / `busy` fall) |
| `rwl_late_hold` | `rtl_hold` | RWL release 12 -> 34 ns; latch-hold adapter unchanged |
| `latch_early_hold` | `rtl_hold` | latch-enable release 34 -> 30 ns (before WWL fall); RWL unchanged |
| `latch_late_hold` | `rtl_hold` | latch-enable release 34 -> 36 ns (after WWL fall and BL release); RWL unchanged |
| `combined_hold` | `rtl_hold` | both late releases (RWL 34, latch 36), run only after the individual controls |

Write-pulse width (WWL 12-32 = 20 ns), precharge, initial levels, sense edge, WWL/BL-drive edges and circuit are
identical across variants. Tests (`Experiments`) prove each control moves only its intended edge(s), that the
individual controls leave the other node untouched, that `combined_hold` is exactly their composition, and that an
unintended extra change is flagged. The deck-to-waveform check still passes for 41/41 instances (10/10 corners conversion-valid for every variant).

### Results (restore at 0.95 / 0.90 / 0.98; corners restored out of 10)

| Variant | restore 0.95 | 0.90 | 0.98 | sense | worst stored-1 SN/SN_ref (mean over corners) | stored-0 SN_end range (V) | op end / `done` seen / settled meas. (ns) |
|---|---:|---:|---:|---:|---:|---|---|
| `baseline_analog` | 10 | 10 | 10 | 10 | 1.03 | -0.015 .. +0.027 | 37 / 37 / 39 |
| `rtl_raw` | 0 | 0 | 0 | 10 | 0.79 | -0.140 .. -0.027 | 34 / 35 / 36 |
| `rtl_hold` | 0 | 0 | 0 | 10 | 0.87 | -0.139 .. -0.113 | 34 / 35 / 36 |
| `rwl_late_raw` | 8 | 9 | 0 | 10 | 0.97 | -0.021 .. +0.114 | 34 / 35 / 36 |
| `rwl_late_hold` | **10** | 10 | 10 | 10 | 1.03 | -0.015 .. +0.027 | 34 / 35 / 36 |
| `latch_early_hold` | 0 | 0 | 0 | 10 | 0.88 | -0.169 .. -0.144 | 34 / 35 / 36 |
| `latch_late_hold` | 0 | 0 | 0 | 10 | 0.87 | -0.139 .. -0.113 | 36 / 37 / 38 |
| `combined_hold` | 10 | 10 | 10 | 10 | 1.03 | -0.015 .. +0.027 | 36 / 37 / 38 |
| `neg_missing_wb` | 0 | 0 | 0 | 10 | 0.73 | +0.03 .. +0.15 | negative control OK 10/10 |
| `neg_short_wb` | 0 | 0 | 0 | 10 | 0.72 | | negative control OK 10/10 |

Reproduced controls: the baseline restores 10/10 and matches the prior `sim/refresh-op` report (<= 0.01 V,
`baseline_matches_prior_all_corners` true); `rtl_raw`/`rtl_hold` fail 0/10, as in run `20261010T094617Z`. The
`rwl_late_raw` failures at 0.95 are `ff/125` (a stored '0' ends above 50 mV) and `sf/125` (stored '1').

SN probes, stored '1' from 0.9 V, tt/27 C (V; SN_ref 1.284): SN just before / after WWL falls: baseline 1.175 / 1.051,
`rtl_hold` 1.179 / 1.042, `rwl_late_hold` 1.175 / 1.051 -- the write itself and the WWL-fall drop (0.12-0.14 V) are the
same in all of them. RWL release: `rtl_hold` releases at 12 ns (SN 0.77 -> 1.03, before the write, which then overwrites it);
`rwl_late_hold` releases after the write: SN 1.051 -> 1.269 (+0.22 V) within 0.2 ns and settles at 1.325-1.340. Latch
state after WWL falls is still decided in all variants (`dla`), but with the latch released early the WBL overshoots to 1.89-1.95 V
(charge injection of the latch turning off through the open write-back switch) and gains only +0.01 of SN/SN_ref.

### Causal attribution (`summary.json` -> `causal_attribution`; mechanical labels over all 10 corners)

| Question | Evidence | Verdict |
|---|---|---|
| RWL release **after** WWL fall | `rwl_late_hold` vs `rtl_hold`: +0.15..+0.18 of SN_ref in every corner, 0 -> 10/10 restored; `rwl_late_raw` vs `rtl_raw`: +0.13..+0.21, 0 -> 8/10 | **Isolated, sufficient** (with the latch held); the dominant effect |
| Latch-hold (enable 11 -> 34) | with RWL early: +0.03..+0.11, 0/10 -> 0/10; with RWL late: +0.04..+0.11, 8/10 -> 10/10 | **Contributing, not sufficient alone**; needed to restore the ff/sf 125 C corners and the 0.98 fraction |
| Latch-enable release 30 vs 34 vs 36 ns | +0.012 / reference / 0.000 of SN_ref; `combined_hold` = `rwl_late_hold` to 1e-4 | **No resolvable effect** of the release edge itself (early release disturbs WBL, +0.01 only) |
| Combined ordering | `combined_hold` 10/10, identical to `rwl_late_hold` and to the analog baseline (SN_end within 0.1 mV of baseline at the same point) | Adds nothing beyond the RWL release; costs +2 ns |

Mechanism consistent with the traces (**not** separately isolated): the read-select (read-device source) edge couples onto
SN through the read device; an RWL release after WWL fall lifts SN by about 0.2 V and cancels the WWL-fall droop, whereas
releasing it at 12 ns spends that coupling before the write. This is a **capacitive-coupling effect in the ideal-driver
circuit** (0.1 ns ideal edge, 100 ohm switches, C_RBL = C_WBL = 10 fF assumed, extracted C_SN, one row's RWL driven ideally).
The stored-'1' end level of the restoring variants is 1.01-1.05 x SN_ref because SN_ref is written with the read select idle (no bootstrap);
so passing the criterion partly reflects the lifting edge, not a larger write-back. Which share is intrinsic to the cell
and which follows from the ideal edge rate/driver impedance remains **confounded** (needs the physical column/row driver
work, #114/#117, and extracted loads, #88/#89). Also untested: RWL release times between WWL fall (32 ns) and 34 ns.
Stored-0 levels also improve with the late release (no more -0.11..-0.14 V undershoot), except `rwl_late_raw` which can exceed +50 mV.

### Timing budget (provisional `T_ROW` = 34, ASSUMPTION; ideal 0 ns adapter/launch latency)

`rwl_late_hold` ends at 34 ns (the RWL release shares the existing `busy`-fall edge): op end fits with **zero slack**, `done`
observed at 35, settled measurement at 36 -- identical to `rtl_hold`, i.e. the ordering change that restores costs no
additional operation cycles *in this ideal model*, but it requires the 34-cycle window to include the post-write RWL hold and
(by the same accounting as before) does not fit once the `done` cycle or the 2 ns settle is counted. `combined_hold`/`latch_late_hold` end at 36 (+2 over budget).
The analog baseline needs 37. Nothing in `scheduler`/`CONTRACT.md` was changed.

### Contract implications (PROPOSED, requires a separate approved decision; none applied)

* The restoring ordering moves read-select release from the end of the sense phase (12 cycles) to at/after WWL fall
  (RWL overlaps the whole 20-cycle write). That reverses the current non-overlap rule in `CONTRACT.md` and must be decided separately.
* The latch enable must be held through the write-back (the explicit adapter, which has no RTL counterpart today).
* Both are valid only for this ideal-driver circuit. They are **not** evidence of a working macro: a physical read-select
  driver (finite edge rate/impedance), column driver and extracted RBL/WBL loads must be checked before any macro claim.
  No ratified specification or digital overlap rule was revised.

## Files

| File | Role |
|---|---|
| [`../../digital/phase-control/tb_trace_export.v`](../../digital/phase-control/tb_trace_export.v) | runs one operation of the committed `phase_seq.v` and prints every strobe edge (sampled 0.1 ns after each rising clock edge; relative to the accepting edge) |
| [`export_rtl_trace.py`](export_rtl_trace.py) | runs iverilog/vvp, writes the JSON trace with source/tool pins (refuses to overwrite) |
| [`replay_lib.py`](replay_lib.py) | `PIN_MAP`, edge -> PWL converter, latch-hold adapter, reverse PWL parser, trace-consistency check, negative-control mutations |
| [`gen_refresh_replay.py`](gen_refresh_replay.py) | builds a NEW `results/<RUN_ID>/` with deck, `klt sim` request, waveforms, consistency check, manifest |
| [`analyze_refresh_replay.py`](analyze_refresh_replay.py) | reduces the klt report into `points.csv` + `summary.json` (refuses to overwrite) |
| [`test_refresh_replay.py`](test_refresh_replay.py) | stdlib tests (converter, consistency check, analysis logic, committed-run self-consistency); wired into `evidence-checks.yml` |

## Pin mapping (explicit; `replay_lib.PIN_MAP`)

| RTL strobe | Deck source (per instance) | Polarity | Meaning in the unchanged circuit |
|---|---|---|---|
| `pre_en` | `vctl` -> switch control `ctl` | active-high | closes the 100 ohm precharge switches (rbl -> VRBL, ref -> VREF) |
| `rwl_sel` | `vrs` -> `rwls` (read-device source of the selected row) | **inverted**: asserted = 0 V, idle = VDD | read select |
| `sense_en` | `ven` -> `en`; `venb` is its exact complement | active-high | latch footer/header enable |
| `wwl_en` | `vww` -> `wwl` | active-high | write wordline of the selected row |
| `bl_drive` | `vwc` -> `wbc` | active-high | closes the switch connecting the latch complement node `ref` to WBL. The existing circuit has no separate column driver; that is #114/#117, out of scope |

Converter rules (no implicit behaviour): an edge at T starts a 0.1 ns linear ramp at T (same as sim/refresh-op);
edges at exactly t = 0 set the initial value; edges closer than 0.1 ns, repeated values and negative times are errors.
Nothing is stretched, delayed or held by the converter.

## Variants (same deck, circuit, initial levels, loads, criteria; only the control PWL differs)

| Variant | Waveform |
|---|---|
| `baseline_analog` | the sim/refresh-op sequence for SENSE 10 ns / WWL 20 ns: precharge 0-2 ns, 2 ns dead gap, select at 4 ns, enable at 14 ns held with RWL and bitline connect until 2 ns after WWL falls (37 ns) |
| `rtl_raw` | the RTL edges only: PRE 0-2, RWL 2-12, 1-cycle `sense_en` at 11-12, WWL 12-32, BL drive 12-34 |
| `rtl_hold` | `rtl_raw` plus the **explicit adapter** `latch_en_held`: enable set at the `sense_en` rise (11 ns), cleared at the `busy` fall (34 ns). Recorded as its own waveform in `waveforms.json`. 0 ns added latency (assumption). RWL is deliberately NOT held (that would change the RTL ordering) |
| `neg_missing_wb` | `rtl_hold` with the `wwl_en`/`bl_drive` edges deleted (negative control) |
| `neg_short_wb` | `rtl_hold` with a 0.2 ns write-back pulse (negative control) |

## Consistency checks and negative controls

* `consistency_check.json` (per instance): `deck_matches_trace` re-parses the generated deck's PWL sources
  and compares them to the variant's edge list; `trace_matches_golden_rtl` compares the variant's edges with the
  golden RTL export. The checker reports `omitted`, `extra`, `shifted`, `value_mismatch`, `reordered`, `initial_mismatch`.
  Unit tests cover each kind and a tampered deck.
* The negative controls differ from the golden trace by design: `neg_missing_wb` is flagged `omitted` (4 edges),
  `neg_short_wb` `shifted`. `negative_control_ok` additionally requires every stored-'1' pattern to be
  flagged **not restored**: true at 10/10 corners for both. Simulator success never counts as restoration.

## Machine-readable result (`summary.json`, `points.csv`)

Per (corner, variant): `simulator_ok`, `conversion_valid`, `sense_correct` (+ per pattern), `restore_success` (headline
FRAC 0.95; also 0.90/0.98 and per pattern), `duration`, `overall_pass` = all four verdicts. Also the run pins:
generated-deck sha256 (equals klt's `netlist_sha256`), request sha256, git head and source file sha256s,
phase_seq/testbench sha256, iverilog version, report provenance (klt 0.6.0, ngspice 46, model library sha256
`48de7c67...133c84`, open_pdks `c6d73a35...` per [`docs/pdk-pin.md`](../../docs/pdk-pin.md)), batch job id.

## Duration vs the provisional 34-cycle budget (`T_ROW` = 34, ASSUMPTION)

| Variant | Last control edge / op end | Completion observed (`done` rise + 1 cycle) | SN read at (end + 2 ns) | Fits 34 ns? |
|---|---:|---:|---:|---|
| `rtl_raw`, `rtl_hold` | 34 ns (busy fall) | 35 ns | 36 ns | op end: yes, **zero slack**; with the `done` observation cycle: no (35); with the 2 ns settle used for the restore measurement: no (36) |
| `baseline_analog` | 37 ns | 37 ns (no digital completion strobe) | 39 ns | no (+3 ns) |

Launch, adapter and completion latency are modelled as 0 ns (ideal; stated assumption), so these are lower
bounds; the `done`-cycle row is the only completion delay in the RTL. These numbers say nothing about whether a
restoring waveform fits: the RTL waveform fits the budget but did not restore; the waveform that restores (baseline) does not fit.
Scheduler timing was not changed.

## Proposed follow-up (not done here; needs its own issue and evidence)

Because the RTL waveform fails restoration, a contract change must be proposed separately with evidence.
Candidates this data motivates, none applied: (a) hold the read select until after WWL falls (overlap rule
change), (b) a latch-hold adapter plus a post-write settle/RWL-release phase, (c) re-defining the restore
measurement point. The 0.08-0.27 V post-WWL-fall rise that lifts the baseline is a candidate cause
of the difference and may be an artifact of the ideal-driver study circuit; that matters before any contract is
changed (#114/#117, #88/#89 for physical drivers and loads, #94 for mixed-pattern trajectories).

## Notes on reproducibility and the host

* Fleet: the 10-corner grid is **one `klt sim` batch request**. Job `klt-sim-d93e7ee207ea` (c7i.4xlarge spot,
  94 s). Earlier submissions of the same request were refused (`batch_no_capacity`; then "8 instance(s) already
  running ... exceeds BATCH_MAX_CONCURRENT_INSTANCES=8") and one failed with `batch_runner_version_mismatch`
  (runner klt 0.5.0 vs client 0.7.0, job `klt-sim-ecd96902de94`); the accepted run used
  `uvx --from klayout-tools==0.6.0 klt`. Log: `results/20261010T094617Z/fleet_attempts.json`. No local fallback
  of the grid occurred. The only local run was an uncommitted tt/27 C single-corner probe on an earlier deck revision.
* The committed report is gzip-compressed with the bucket name redacted.
* klayout-tools friction (already known, tool gap not design): the installed client (0.7.0) is rejected by
  the fleet runner (0.5.0); the working client had to be pinned to 0.6.0.

```
python3 -I sim/refresh-replay/export_rtl_trace.py /tmp/rtl_trace.json
python3 -I sim/refresh-replay/gen_refresh_replay.py /tmp/rtl_trace.json          # new results/<RUN_ID>/
uvx --from klayout-tools==0.6.0 klt sim --backend batch --format json results/<RUN_ID>/request.json   # from the repo root
python3 -I sim/refresh-replay/analyze_refresh_replay.py sim/refresh-replay/results/<RUN_ID>
python3 -I sim/refresh-replay/test_refresh_replay.py
```

Run `20261010T130000Z` (issue #131): one `klt sim` batch request (`uvx --from klayout-tools==0.6.0 klt sim --backend batch --format json`,
job `klt-sim-b8ad51731243`, c7i.4xlarge spot, 95 s, 10/10 corners; first and only submission, no local simulation, no fallback;
`fleet_attempts.json`). The report arrived on stdout (the `-o` file was not written by this client); the bucket name is redacted in the gzip.

Rerun with a **new** run id; never edit `results/`.
