# sim

ngspice testbenches and PVT-corner results. Everything in this directory
runs from a stock `open_pdks` sky130 install (via `volare`) -- no local
model edits, no uncommitted `.include` paths. Results files are
**append-only evidence** per `CLAUDE.md`: reruns append new rows, they
never overwrite or truncate prior results.

## `leakage/` -- access-device off-state leakage (issue #2)

First link in the retention/refresh budget evidence chain: measures the
candidate 2T/3T gain-cell access device's (`sky130_fd_pr__nfet_01v8`)
off-state leakage (subthreshold conduction + reverse-biased drain-body
junction leakage) against the shipped sky130 models, swept across the 5
shipped MOS process corners (`tt`/`ss`/`ff`/`sf`/`fs`) and the
`-40/27/125 °C` temperature range. See
[`leakage/README.md`](leakage/README.md) for the device-choice rationale,
bias condition, worst-case-corner call-out, and full reproduction
instructions; raw results are in
[`leakage/results/leakage_results.csv`](leakage/results/leakage_results.csv).

Quick start (requires `ngspice` on `PATH` and the PDK pinned in
`leakage/pdk.json` enabled via `volare`):

```bash
python3 sim/leakage/run_leakage_sweep.py --check-env
python3 sim/leakage/run_leakage_sweep.py
```

This is the leakage half of the evidence chain `CLAUDE.md` requires
before any retention-time number can be claimed; the storage-node
capacitance assumption and the retention derivation itself are tracked in
issue #3.

## `retention/` -- retention-time derivation for candidate 2T/3T geometries (issue #3)

Second and third links in the retention/refresh budget evidence chain:
combines the measured worst-case leakage above with an explicitly labelled
storage-node capacitance ASSUMPTION (no layout exists yet to extract one
from) to derive retention-time estimates for a `2T-min` and a `3T-min`
candidate gain-cell geometry, at the worst-case temperature corner. See
[`retention/README.md`](retention/README.md) for the full derivation
(formula, inputs, and which numbers are measured vs. computed vs.
assumed); results are in
[`retention/results/retention_results.csv`](retention/results/retention_results.csv).

Quick start (requires the same PDK install as `leakage/`, no ngspice
invocation needed):

```bash
python3 sim/retention/derive_retention.py --check-env
python3 sim/retention/derive_retention.py
```

## `bitcell-transient/` -- 2T-min bitcell write / read / hold transient (issue #27)

The **first circuit-level simulation of the ratified bitcell**: the two
studies above look at the cell one piece at a time (a DC operating point on
a single access device, then an analytic derivation on top of it), while
this one exercises the whole cell as a circuit in a single `.tran` --
writing a '1' and a '0', reading both, and timing the storage node's decay
-- across the same `tt`/`ss`/`ff`/`sf`/`fs` x `-40/27/125 °C` grid. The deck
`.include`s [`design/gain_cell_2t.spice`](../design/gain_cell_2t.spice)
verbatim rather than transcribing the devices, and loads `sn` with the
post-layout extracted `C_SN` from
[`layout/gain_cell_2t.extract.parasitics.json`](../layout/gain_cell_2t.extract.parasitics.json)
(issue #7, overridable with `--c-sn-ff`). See
[`bitcell-transient/README.md`](bitcell-transient/README.md) for the phase
timing, the `rbl` bias choice, the `.tran` settings and their convergence
check, the worst-case-corner call-out (`sf`/125 °C,
`t_ret_tran` = 2.3958e-05 s), the three corners where the assumed 0.9 V
sense margin turns out to be **unattainable** with a plain-1.8 V wordline,
and the cross-check against `retention/`'s analytic 5.50 µs; raw results are
in
[`bitcell-transient/results/bitcell_transient_results.csv`](bitcell-transient/results/bitcell_transient_results.csv).

Quick start (requires `ngspice` on `PATH`, the PDK pinned in
`bitcell-transient/pdk.json` enabled via `volare`, and the leakage results
above already committed -- the hold window is seeded from them):

```bash
python3 sim/bitcell-transient/run_bitcell_transient.py --check-env
python3 sim/bitcell-transient/run_bitcell_transient.py
```

This is the read-current / written-level / read-disturb evidence the array,
the sense amplifier and the write-margin decision in issue #24 each consume;
it does **not** re-ratify any retention number in
[`spec/retention-refresh-budget.md`](../spec/retention-refresh-budget.md),
which remains a separate, gated spec change.
