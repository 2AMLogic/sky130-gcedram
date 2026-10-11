# SPI crossing and reset architecture (PROPOSED)

Status: **PROPOSED** (issue #157, epic #24 items 3 and 4). Nothing here is
ratified, `spec/` is not edited, and no existing RTL, testbench or committed
result is changed. The macro is a **dynamic** gain-cell array; this is
control-path architecture for its refresh controller, not an SRAM-replacement
interface.

| File | Content |
|---|---|
| [`DESIGN.md`](DESIGN.md) | The design record: crossing inventory, mailbox, reservation, snapshot, stopped-sclk and reset behaviour, compatibility table, latency derivations, open decisions, blockers |
| [`xing_model.v`](xing_model.v) | Small behavioral protocol model (SPI side, clk side, top) with a `NOACK` negative-control switch |
| [`tb_xing.v`](tb_xing.v) | Deterministic testbench |
| [`run_tests.sh`](run_tests.sh) | Positive runs over sclk/clk phase relationships (each must show the T5 mailbox refusals) plus the negative control, which the script asserts must fail, including a config-bundle scoreboard error |

## What the evidence is, and is not

* **Protocol checks (here, Icarus Verilog):** exactly-once delivery, bundle
  atomicity, BUSY exactness, paused and restarted `sclk`, reset cancellation,
  commit-to-applied latency, and the mailbox refusal path under a violated
  ack-latency obligation (TB T5: refused, ERR_BUSY, bundle untouched, retry).
* **Structural CDC review (not done):** reviewed synchroniser cells, the
  single-bit-only rule on every asynchronous wire, bundle-stability paths.
* **Physical timing / MTBF (not done):** bundle skew constraints, synchroniser
  MTBF, `cs_n`-as-clock timing, reset-release timing.

Icarus has no metastability model. Nothing in this directory is CDC or MTBF
evidence. Pin: Icarus Verilog `v13_0` as in [`../ci/`](../ci/README.md).

## Reproduce

```
digital/spi-crossing/run_tests.sh      # serial, no -j; exit 0 = all pass
```

Reference behavioral harness, unchanged and still authoritative for the
current scheme: [`../control-integration/`](../control-integration/CONTRACT.md),
[`../spi-control/`](../spi-control/SPEC.md),
[`../spi-sched-phase-integration/`](../spi-sched-phase-integration/README.md).
