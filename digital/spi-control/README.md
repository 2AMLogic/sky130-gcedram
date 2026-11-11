# SPI control behavioral model (issue #83, epic #24 item 4)

A **PROPOSED**, behavioral (not synthesised, no timing) SPI slave that
configures a refresh controller for a dynamic gain-cell macro. It is not an
SRAM-replacement interface. Interface definition and the ASSUMPTION/sourced tags
are in [`SPEC.md`](SPEC.md). `spec/` is not edited.

| File | Purpose |
|---|---|
| `SPEC.md` | proposed frame format, register map, bound, errors, re-check list |
| `spi_slave.v` | behavioral slave (`MAX_INTERVAL` parameter, no default: must be supplied; #93 added `MIN_INTERVAL` (default 1) and `XSTAT_EN` (default 0), which leave standalone behaviour unchanged, re-run in `results/*_issue93.txt`) |
| `tb_spi_slave.v` | self-checking TB: reset values, round trip, sequencing, bound, malformed frames, async reset; prints `TB_RESULT: PASS/FAIL` |
| `params.py` | refresh-interval bound, reusing `../refresh-scheduler/params.py` (reads the committed retention CSV; nothing retyped) |
| `run_tests.sh` | iverilog `-g2012` + vvp at the ratified and extracted-C_SN stress bounds, each read from `params.py` (`params.py ratified`, `params.py extracted`) |
| `run_mutation.sh` | 8 deliberately broken slaves must all fail the TB |
| `results/` | dated run output (append-only; add new files) |

Run: `./run_tests.sh` then `./run_mutation.sh`.

Limits: protocol model only; `sclk`/`cs_n` are used directly as clocks, so no
CDC, timing or synthesis claims. All interface choices are ASSUMPTIONs until
the challenge rules and a real scheduler fix them (SPEC.md Sec. 5).

## Reset / clear structure (issue #273)

Every flop has exactly one asynchronous control (Yosys `proc` rejects two):

| Flops | Clock | Async clear |
|---|---|---|
| `rx`, `cnt` | `posedge sclk` | `clr_n = rst_n & ~cs_n` (low = clear) |
| `tx` | `negedge sclk` | `clr_n` |
| commit state (`refresh_en`, `ivl_*`, `sh_l`, `sweep_tog`, `st`) | `posedge cs_n` | `rst_n` |

`cs_n` high or `rst_n` low clears the frame state without any `sclk` edge.
Simulation: the commit block reads `rx`/`cnt` on the same `cs_n` edge that
clears them; the clear is a nonblocking assignment, so the commit sees the
pre-clear values. How that race resolves in gates is part of the CDC work and
is **not** solved here. A synchronous `cs_n` clear was rejected: `sclk` does
not run while `cs_n` is high. Sim note: `clr_n` is already 0 at time 0 (`cs_n`
high), so the testbenches apply the power-on reset with `cs_n` low (no edge
otherwise; real flops are level-sensitive).

Synthesis: `spi_slave.synth.request.json` (`klt synthesize`, sv2v frontend,
`sky130_fd_sc_hd`, `MAX_INTERVAL=5029`) completes through `proc` and maps to
library cells (259 instances, no warnings); report and netlist in
`results/*_2026-11-11_issue273.*`.

**Not yet verified:** timing (recovery/removal of `clr_n` against `sclk`,
glitches on the combinational `clr_n`), CDC, gate-level behaviour of the commit
race, and `gc_ctrl_top` synthesis (#230).

## CI

CI: `.github/workflows/digital-regressions.yml` runs this under the pinned
Icarus Verilog (see [`digital/ci/README.md`](../ci/README.md)). Behavioral
regression only; not physical CDC, synthesis, timing or macro sign-off.
