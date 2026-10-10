# Digital regression CI

`.github/workflows/digital-regressions.yml` runs the behavioral Verilog
regressions on every push to `main` and every pull request (forks included;
read-only token, no secrets).

**Scope: behavioral regression only.** It catches breakage of row deadlines,
configuration transfer and SPI error handling in simulation. It is not
physical CDC/metastability, synthesis, timing, maximum `sclk` rate or macro
sign-off evidence, and it does not change any provisional timing value.

## Toolchain pin

* Icarus Verilog `v13_0`, git commit `dfeee909ed9f20b4870dd93423156c0170c0e1ff`
  (peeled tag), built from source by `digital/ci/install_iverilog.sh`.
* Integrity: the source is fetched by exact commit and the checked-out `HEAD`
  must equal the pinned id (a content hash), otherwise the build fails. The
  GitHub tag tarball `v13_0.tar.gz` has sha256
  `c897bbfa9848688982c6d5c30529fc29d68df0b9ff22ffa73bad89db73a7ce49`
  (recorded for reference; the commit id is what is enforced).
* Build dependencies come from the runner's apt (`gperf bison flex g++ make`)
  and only on a cache miss; they affect the build, not the pinned source.
* Cache: `actions/cache` keyed by `runner.os`, `runner.arch` and the hash of
  `install_iverilog.sh` (which contains the pin). Changing the pin changes the
  key. A cache miss rebuilds from source; the uncached path is always valid.
* Versions (`iverilog -V`, `vvp -V`, `python3 --version`) are written to
  `versions.txt` in the log artifact.

## What runs (serial, `digital/ci/run_digital_regressions.sh`)

1. `digital/refresh-scheduler/run_tests.sh` (~35 s locally)
2. `digital/refresh-scheduler/run_mutation.sh` (~100 s)
3. `digital/spi-control/run_tests.sh`
4. `digital/spi-control/run_mutation.sh`
5. `digital/phase-control/run_tests.sh` and `run_mutation.sh` (seconds;
   behavioral analog phase sequencer, issue #108)
6. `digital/control-integration/run_tests.sh` (~11 min; includes lockstep
   equivalence, both interval bases, expected-failure negative controls and
   its own mutation suite)
7. `digital/sched-phase-integration/run_tests.sh` and `run_mutation.sh`
   (seconds; scheduler-to-sequencer launch/completion timing, issue #135)

Every suite runs even if an earlier one fails (so all logs exist); the driver
exits non-zero if any failed, which fails the job. Compile errors, a failing
baseline or an undetected mutant make the individual script exit non-zero.

## Timeout and logs

`timeout-minutes: 45` is a provisional bound (integration ~12 min plus source
build and shared-runner slowdown). It is justified from measured hosted-runner
durations under "Recorded CI runs" below. Per-suite logs, `summary.txt` (per-suite exit code and duration)
and `versions.txt` are uploaded as artifact `digital-regression-logs` with
`if: always()`. They are CI artifacts only; nothing is written under the
`results/` directories.

## Running locally

### Local auditor setup (Ubuntu 24.04)

Supported local host: Ubuntu 24.04 LTS. Python policy: use the distro
`python3` (3.12 series); the tests are stdlib-only, so no pip environment or
virtualenv is needed. Package versions are whatever apt provides; record them
(below) rather than assuming they are immutable. The simulator is the only
pinned tool: Icarus Verilog `v13_0`, commit
`dfeee909ed9f20b4870dd93423156c0170c0e1ff`, defined solely in
`digital/ci/install_iverilog.sh` and verified there (fetched `HEAD` must equal
that commit).

1. Packages (needs root once; the bootstrap never installs anything itself):

   ```
   sudo apt-get update
   sudo apt-get install -y --no-install-recommends python3 git gperf bison flex g++ make
   ```

2. Build the pinned simulator into a user-writable prefix, with the prefix and
   scratch build tree both absolute and outside the checkout. The script
   checks prerequisites first and exits non-zero with the apt command above if
   any is missing; it creates nothing in that case. The prefix must not
   contain whitespace (Icarus `configure` rejects it); the build dir may. Builds use
   `IVERILOG_JOBS` parallel jobs (installer default 2).

   ```
   digital/ci/bootstrap_auditor.sh "$HOME/iverilog-v13_0" /tmp/iverilog-build
   ```

3. Put the simulator on `PATH` for the current shell (no shell startup file is
   edited) and check that both tools resolve to the prefix:

   ```
   export PATH="$HOME/iverilog-v13_0/bin:$PATH"
   command -v iverilog vvp
   ```

4. Capture versions and run the two baseline runners, with logs and exit
   status outside the checkout:

   ```
   logs=/tmp/digital-logs; mkdir -p "$logs"
   { head -2 /etc/os-release; python3 --version; iverilog -V | head -1
     vvp -V | head -1; git rev-parse HEAD; } > "$logs/versions.txt" 2>&1
   for s in refresh-scheduler spi-control; do
     rc=0; digital/$s/run_tests.sh > "$logs/$s.log" 2>&1 || rc=$?
     echo "$s exit=$rc" >> "$logs/summary.txt"
   done
   cat "$logs/summary.txt"; grep -c 'ALL PASS' "$logs"/*.log
   git status --porcelain   # must be unchanged
   ```

   Each runner covers both interval bases (ratified and extracted) and must
   exit 0 with a final `ALL PASS` line.

The bootstrap does not run any suite. For the full serial driver (optional):

```
digital/ci/run_digital_regressions.sh /tmp/digital-logs
```

## Recorded CI runs

Hosted `ubuntu-latest` runner, numbers from the job step timestamps and the
`digital-regression-logs` artifact (`summary.txt`, `versions.txt`).

### Fresh uncached run

[Run 37970944541](https://github.com/2AMLogic/sky130-gcedram/actions/runs/37970944541)
([job](https://github.com/2AMLogic/sky130-gcedram/actions/runs/37970944541/job/113957090066)),
PR #106 head `dda1575`, conclusion **success**. Cache miss; the cache was saved
afterwards as `iverilog-Linux-X64-4e342da7…`.

* Versions: `Icarus Verilog version 13.0 (stable) (dfeee90)`,
  `Icarus Verilog runtime version 13.0 (stable) (dfeee90)`, `Python 3.12.3`.
* Step durations: apt build deps 11 s (18:06:22 to 18:06:33 UTC); source
  build 2 min 21 s (18:06:33 to 18:08:54); serial regressions 13 min 51 s
  (18:08:54 to 18:22:45); whole run 16 min 38 s.
* Per-suite verdicts (`summary.txt`, exit code and duration):

  | Suite | Exit | Duration |
  |---|---|---|
  | refresh-scheduler-tests | 0 | 16 s |
  | refresh-scheduler-mutation | 0 (5/5 mutants killed) | 100 s |
  | spi-control-tests | 0 | 0 s |
  | spi-control-mutation | 0 (8/8 mutants killed) | 2 s |
  | control-integration | 0 (`ALL PASS`, incl. its mutation check) | 713 s |
  | overall | PASS | |

### Cache-hit run

[Run 37973154779](https://github.com/2AMLogic/sky130-gcedram/actions/runs/37973154779)
([job](https://github.com/2AMLogic/sky130-gcedram/actions/runs/37973154779/job/113964644946)),
PR #106 head `2bd9108` (docs-only change, same installer and therefore same
cache key), conclusion **success**. Cache hit: "Install build dependencies"
and "Build pinned Icarus Verilog" were skipped.

* Versions: identical to the uncached run (`13.0 (stable) (dfeee90)` for
  `iverilog` and `vvp`, `Python 3.12.3`).
* Step durations: serial regressions 10 min 12 s (18:25:27 to 18:35:39 UTC);
  whole run 10 min 22 s.
* Per-suite verdicts: all exit 0, `overall: PASS`, the same verdicts as the
  uncached run (refresh-scheduler-tests 11 s, refresh-scheduler-mutation
  71 s, spi-control-tests 0 s, spi-control-mutation 1 s,
  control-integration 529 s).

The regression step itself varied between the two hosted runs (13 min 51 s
and 10 min 12 s). That variation is runner noise, not a caching effect,
because the cache only replaces the build steps.

### Timeout

The slowest measured run, the uncached one, took 16 min 38 s end to end, and
the slowest regression step took 13 min 51 s. So `timeout-minutes: 45` is
about 2.7x the slowest measured run. That headroom covers shared-runner
slowdown of the integration suite, which took 529 to 713 s in the runs above.
The bound stays **provisional**: three hosted runs are not a distribution.
Lower it only once more runs are recorded.

### Injected-fault demonstration

A throwaway branch `throwaway/issue-105-fault-injection` was created off
`feature/issue-105` at `2bd9108`. It was opened as draft PR #107 only to
trigger the workflow, then closed unmerged and the branch was deleted. It
carried one fault in `digital/spi-control/spi_slave.v`: the interval upper
bound check was changed from `val > MAX_INTERVAL` to `val >= MAX_INTERVAL`,
so a valid maximum interval was rejected.

[Run 37973105340](https://github.com/2AMLogic/sky130-gcedram/actions/runs/37973105340)
([job](https://github.com/2AMLogic/sky130-gcedram/actions/runs/37973105340/job/113964485126)),
head `3d50fad`, conclusion **failure**. The "Behavioral regressions (serial)"
step failed, and the logs were still uploaded. In `summary.txt`:

| Suite | Exit | Evidence in log |
|---|---|---|
| refresh-scheduler-tests | 0 | unaffected |
| refresh-scheduler-mutation | 0 | unaffected |
| spi-control-tests | 1 | `FAIL ivl_max_ok`, `status_clean_after_valid` and `err_any_clean` at both interval bases (`errors=3` each), `SOME FAIL` |
| spi-control-mutation | 2 | `baseline does not pass` |
| control-integration | 1 | integration bench `TB_RESULT: FAIL`, then `baseline does not pass`, `SOME FAIL` |
| overall | FAIL | |

This shows that a baseline failure propagates through the driver to a red
job. Every suite still ran. This run was a cache miss, because a PR ref cannot
read another PR's cache. Its "Post Cache" step was skipped because the job
failed.

## Demonstrating failure propagation

The recorded result is under "Injected-fault demonstration" above. To repeat
it, on a throwaway branch (do not merge), make a bounded fault such as flipping a
comparison in `digital/spi-control/spi_slave.v`; the baseline bench and
`spi-control-tests` must fail and the job go red. For the mutation guard,
add a no-op mutant entry to a `run_mutation.sh` list that the bench cannot
detect; that suite must fail with an undetected mutant.
