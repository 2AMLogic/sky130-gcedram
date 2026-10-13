# Analog phase control (behavioral, PROPOSED)

Issue #108. A behavioral sequencer that turns READ / WRITE / REFRESH requests
into non-overlapping analog phase strobes (precharge, read select, sense,
write wordline, bitline drive). Contract and open timing conflicts:
[`CONTRACT.md`](CONTRACT.md). The macro is dynamic and refresh is mandatory; this
is not an SRAM interface. All timing is ASSUMPTION or SOURCED-by-deck. No SPICE.

| File | Role |
|---|---|
| `phase_seq.v` | sequencer |
| `tb_phase_seq.v` | bench: exact cycle compare to an independent reference, plus overlap/order invariants, back-to-back, start-while-busy, reset mid-op; prints (report-only) CONFLICT lines vs `T_ROW`/`T_ACC` |
| `run_tests.sh` | `anchored` and `fast` scenarios x `GAP` 0 and 1 |
| `run_mutation.sh` | 12 sed mutants; each must differ from the source and be killed by a bench VIOLATION |
| `results/` | dated, append-only logs |

Mutants: precharge overlapping RWL, sense before RWL, WWL overlapping RWL,
WWL overlapping sense, write-back before sense done, refresh dropping
write-back / precharge / sense, short sense window, early BL release,
unflagged start-while-busy, missing done.

Run (needs Icarus Verilog on PATH; CI uses the pinned build, see
[`../ci/README.md`](../ci/README.md)):

```bash
digital/phase-control/run_tests.sh
digital/phase-control/run_mutation.sh
```

The `GAP`=1 runs print a CONFLICT (37 > `T_ROW` 34): that is a deliberate
open-item demonstration, not a failure.
