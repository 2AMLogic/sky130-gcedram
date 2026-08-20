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
