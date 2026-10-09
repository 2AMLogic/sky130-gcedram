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
5. `digital/control-integration/run_tests.sh` (~11 min; includes lockstep
   equivalence, both interval bases, expected-failure negative controls and
   its own mutation suite)

Every suite runs even if an earlier one fails (so all logs exist); the driver
exits non-zero if any failed, which fails the job. Compile errors, a failing
baseline or an undetected mutant make the individual script exit non-zero.

## Timeout and logs

`timeout-minutes: 45` is a provisional bound (integration ~11 min plus source
build and shared-runner slowdown). Revise it from measured hosted-runner
durations. Per-suite logs, `summary.txt` (per-suite exit code and duration)
and `versions.txt` are uploaded as artifact `digital-regression-logs` with
`if: always()`. They are CI artifacts only; nothing is written under the
`results/` directories.

## Running locally

```
digital/ci/install_iverilog.sh "$HOME/iverilog-v13_0"   # optional, needs gperf bison flex
PATH="$HOME/iverilog-v13_0/bin:$PATH" digital/ci/run_digital_regressions.sh /tmp/digital-logs
```

## Recorded CI runs

Not yet recorded. To be filled in from the first CI runs: fresh uncached
duration and versions, cached-run duration and verdicts.

## Demonstrating failure propagation

On a throwaway branch (do not merge), make a bounded fault such as flipping a
comparison in `digital/spi-control/spi_slave.v`; the baseline bench and
`spi-control-tests` must fail and the job go red. For the mutation guard,
add a no-op mutant entry to a `run_mutation.sh` list that the bench cannot
detect; that suite must fail with an undetected mutant.
