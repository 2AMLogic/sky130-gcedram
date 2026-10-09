# SPI control behavioral model (issue #83, epic #24 item 4)

A **PROPOSED**, behavioral (not synthesised, no timing) SPI slave that
configures a refresh controller for a dynamic gain-cell macro. It is not an
SRAM-replacement interface. Interface definition and the ASSUMPTION/sourced tags
are in [`SPEC.md`](SPEC.md). `spec/` is not edited.

| File | Purpose |
|---|---|
| `SPEC.md` | proposed frame format, register map, bound, errors, re-check list |
| `spi_slave.v` | behavioral slave (`MAX_INTERVAL` parameter) |
| `tb_spi_slave.v` | self-checking TB: reset values, round trip, sequencing, bound, malformed frames, async reset; prints `TB_RESULT: PASS/FAIL` |
| `params.py` | refresh-interval bound, reusing `../refresh-scheduler/params.py` (reads the committed retention CSV; nothing retyped) |
| `run_tests.sh` | iverilog `-g2012` + vvp at ratified (5029) and extracted-C_SN stress (2751) bounds |
| `run_mutation.sh` | 8 deliberately broken slaves must all fail the TB |
| `results/` | dated run output (append-only; add new files) |

Run: `./run_tests.sh` then `./run_mutation.sh`.

Limits: protocol model only; `sclk`/`cs_n` are used directly as clocks, so no
CDC, timing or synthesis claims. All interface choices are ASSUMPTIONs until
the challenge rules and a real scheduler fix them (SPEC.md Sec. 5).
