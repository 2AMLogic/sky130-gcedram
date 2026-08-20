# sky130-gcedram — agent instructions

Open-source canary block: a 2T/3T gain-cell embedded-DRAM (eDRAM) macro on
SkyWater sky130, a 130 nm open CMOS PDK, designed and verified by AI agents.

- **PDK**: SkyWater sky130 (open PDK, plain CMOS, fully supported by the
  toolchain from a stock open_pdks install). Open-source flow: xschem +
  ngspice for design/sim, klayout-tools (`klt`) for layout work. An array
  macro plus its sense/refresh periphery is a mixed-signal layout workout —
  exactly the friction surface this canary exists to feed.
- **This is a new block, not a port.** Gain-cell eDRAM is a mature, publicly
  documented topology — two decades of academic literature, compatible with a
  standard logic process, no special DRAM process step. What does not exist
  publicly is an implementation on an open PDK. That gap is this repo's
  reason to exist. Start from the published literature and the shipped PDK
  models, not from a sibling repo's schematics — there is no sibling for this
  block.
- **Position it honestly against SRAM.** A gain cell is dynamic: it trades
  SRAM's static hold for density. The retention/refresh budget is therefore
  the centerpiece of the spec, not a footnote. Never describe the macro as a
  drop-in SRAM replacement.
- **Retention claims carry their evidence chain.** Every retention-time
  number rests on: device-level leakage measured against the shipped sky130
  models at temperature corners → a storage-node capacitance assumption,
  explicitly labelled as an assumption → the retention derivation. All three
  links are committed netlists and write-ups, reproducible from a stock PDK
  install. A retention number without its chain is not a result.
- **Cite public sources only.** The academic gain-cell literature, the sky130
  PDK's own model files, and OpenRAM's public docs (if an SRAM comparison is
  needed) are the reference set. Any measured number appearing here must be
  re-derived inside this repo from the public PDK models, with the netlists
  committed.
- **Friction protocol (the canary's job)**: every time klayout-tools is
  awkward, missing a capability, or wrong for what you need, file an issue at
  `2AMLogic/klayout-tools` describing the tool gap generically — that tracker
  is scoped to the tool, so keep design-specific detail out of it and describe
  the gap, not the design.
- **Verification is the product**: no claim without a testbench. Retention
  claims are made at the worst-case temperature corner, not typicals; PVT
  corners on every recorded result; `sim/` results are append-only evidence.
- Spec changes go through `spec/` with a decision record; agents do not relax
  the ratified spec to make results pass.

<!-- BEGIN LOOM ORCHESTRATION -->
This repository uses [Loom](https://github.com/rjwalters/loom) for AI-powered development orchestration — see the Loom repository for the full guide (roles, labels, worktrees, configuration). When installed, Loom also writes a locally-substituted copy of that guide to `.loom/CLAUDE.md`.
<!-- END LOOM ORCHESTRATION -->
