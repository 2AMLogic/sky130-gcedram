# Scheduler -> phase-sequencer integration harness (behavioral, PROPOSED)

Issue #135, epic #24. Connects the existing scheduler operation interface
(`../control-integration/refresh_sched_rt.v`, unchanged) to the existing phase
sequencer (`../phase-control/phase_seq.v`, unchanged) through an explicit
launch adapter, and checks launch/completion timing at that boundary with a
scoreboard over one cycle-indexed trace. This closes the measurement gap in
`../phase-control/CONTRACT.md` open item 4. The macro is a dynamic gain-cell
array; this is not an SRAM controller. Behavioral evidence only: no analog
restoration, CDC, synthesis or timing sign-off claim, and no SPICE.

Results and the PROPOSED integration contract: [`TIMING_REPORT.md`](TIMING_REPORT.md).

| File | Role |
|---|---|
| `launch_adapter.v` | scheduler `op_busy` rising edge -> one `start`; kind from `op_is_refresh`/`op_is_write`; row from `op_row`. Has bench-only fault injection (`MUT`) |
| `sched_phase_top.v` | scheduler + adapter + sequencer, exposing every boundary signal |
| `tb_sched_phase.v` | stimulus, cycle-indexed trace (`+TRACE=file`), scoreboard, per-kind timing report |
| `run_tests.sh` | scenarios 0-4 x five phase-timing sets; asserts the expected pass/conflict outcome |
| `run_mutation.sh` | 6 adapter mutants + 4 sequencer early-completion mutants; each must be killed by a `VIOLATION` |
| `results/` | dated, append-only logs |

## What the scoreboard checks

Everything is compared on actual sampled events (sampled at the falling clock
edge, so the nonblocking-assignment delay of every registered output is
included; nothing assumes equal numeric durations mean agreement).

* Exactly one `start` per scheduler launch, in the launch cycle; adapter kind/row
  equal the scheduler's (a dropped or duplicated start is a `VIOLATION`).
* Each accepted start produces exactly one sequencer operation, one cycle
  after launch, with `row_q` equal to the launched row; kind inferred from the
  observed strobe profile equals the launched kind.
* The observed profile (cycles of `pre_en`, `rwl_sel`, `sense_en`, `wwl_en`,
  `bl_drive`, and total busy length) equals the sequencer's own parameters. An
  early completion fails here.
* No strobe while the sequencer is idle; `start_ignored` appears exactly when a
  start hits a busy sequencer; scheduler busy length is `T_ROW`/`T_ACC`;
  scheduler refresh rows are round-robin.
* Reported per kind: sequencer busy length; `d_lastact` (final strobe cycle
  minus the scheduler's last busy cycle), `d_busyfall`, `d_done` (sequencer
  minus scheduler; positive = sequencer later); `next_launch_margin_min` (next
  launch cycle minus this op's sequencer busy-fall; 0 = the launch coincides
  with the done cycle, negative = launch into a busy sequencer).

Conflict classes (report-only, `CONFLICT:` lines; the expected outcome per
timing set is asserted so a regression in either direction fails):

* `LOST`: a launch arrived while the sequencer was busy, the sequencer ignored
  it and the operation (and its row refresh) never executed.
* `SKEW`: an accepted operation's strobes/busy/done extend past the scheduler's
  busy fall / done.

## Scenarios

0 isolated READ/WRITE after the reset-initialisation sweep (32 back-to-back
REFRESH); 1 saturating READ/WRITE traffic with sweep; 2 saturating traffic
across urgent-refresh arbitration (12000 cycles); 3 runtime configuration
transitions under traffic (shorten to the feasibility floor, lengthen, forced
sweep, snapshot applied mid-operation, infeasible snapshot refused, disable,
re-enable, sweep during a refresh); 4 reset interruption.

Scope notes. Configuration is applied on the scheduler's `cfg_*` snapshot port
(the end of the SPI path; SPI -> snapshot transfer is #93's domain and is not
re-verified). Reset interruption is scoped to observation: both modules go
idle, the in-flight operation is abandoned and no completion is produced; the
analog consequence of cutting an operation mid-phase is not addressed.

## Reproduce

Needs the pinned Icarus Verilog (v13_0, built by `../ci/install_iverilog.sh`
into a repo-local prefix; see [`../ci/README.md`](../ci/README.md)) on `PATH`,
plus `bash`. No other dependency, a few seconds total:

```bash
digital/sched-phase-integration/run_tests.sh
digital/sched-phase-integration/run_mutation.sh
# cycle-indexed trace / per-op timing of one case:
iverilog -g2012 -s tb_sched_phase -DVERBOSE=1 -P tb_sched_phase.SCEN=0 -o /tmp/t.vvp \
  digital/sched-phase-integration/{launch_adapter,sched_phase_top,tb_sched_phase}.v \
  digital/control-integration/refresh_sched_rt.v digital/phase-control/phase_seq.v
vvp -n /tmp/t.vvp +TRACE=/tmp/trace.txt
```
