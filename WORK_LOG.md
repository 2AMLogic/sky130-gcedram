# Work Log

Chronological record of merged pull requests and closed issues. Maintained by the Loom Guide role.

### 2026-10-10

- **PR #145**: test: include all evidence-checks suites in npm test
- **Issue #78** (closed): CI: npm test omits six evidence-checks suites
- **Issue #143** (closed): Auditor: retain gh-api-rawfield-body-literal-at guard
- **PR #142**: Revalidate refresh sense evidence with matched physical initialization controls (#139)
- **Issue #139** (closed): Revalidate refresh sense evidence with matched physical initialization controls
- **Issue #132** (closed): Auditor guard review: worktree-write-confinement-unresolved-var
- **Issue #138** (closed): Couple scheduler budgets to phase durations and verify executed-refresh deadlines
- **PR #140**: Couple scheduler budgets to phase durations and verify executed-refresh deadlines (#138)
- **PR #137**: feat(sim): RWL driver slew/impedance/release-delay sensitivity of late-RWL refresh restoration (#134)
- **Issue #134** (closed): Characterize late-RWL refresh restoration sensitivity to driver slew and impedance
- **PR #136**: feat(digital): scheduler-to-phase-sequencer integration harness and timing report
- **Issue #135** (closed): Verify scheduler-to-phase-sequencer launch and completion timing in a behavioral integration harness
- **PR #133**: feat(sim): refresh-replay RWL/latch release-order attribution experiment
- **Issue #131** (closed): Isolate refresh restoration failure with controlled RWL and latch release-order experiments
- **PR #129**: feat(sim): replay phase_seq RTL strobes in refresh-op circuit (RTL waveform fails restoration)
- **Issue #128** (closed): Replay phase-sequencer RTL strobes in SPICE to test refresh waveform compatibility
- **PR #126**: docs(sim): narrow 'a PR cannot weaken the check' claim
- **Issue #72** (closed): docs(sim): narrow 'a PR cannot weaken the check' claim for the append-only guard
- **Issue #115** (closed): Quantify refresh energy and standby power of the 2T array at the PVT corners
- **PR #124**: feat(sim): array-boundary refresh energy and standby power of the extracted 4x4 array
- **Issue #119** (closed): Auditor: retain rm-scope rejection for custom-template mktemp cleanup
- **Issue #104** (closed): Auditor: worktree confinement rejects scratch-directory layout validation with shell variables
- **Issue #62** (closed): CI: enforce append-only sim/ results mechanically
- **Issue #110** (closed): Measure t_row_refresh_op with a closed-loop sense and write-back refresh operation
- **PR #122**: sim: closed-loop refresh operation, measured t_row_refresh_op (#110)

### 2026-10-09

- **Issue #92** (closed): Add a reproducible local auditor bootstrap for Python and pinned Icarus Verilog
- **PR #116**: feat(ci): local auditor bootstrap for pinned Icarus Verilog
- **Issue #108** (closed): Define the digital-to-analog phase-control contract with an ordering-checked sequencer model
- **PR #113**: feat(digital): analog phase-control contract, sequencer and mutation suite
- **Issue #109** (closed): Commit the sense latch as a design source (schematic and derived netlist) tied to the sense-stage deck
- **PR #112**: design: sense latch schematic + derived netlist tied to sense-stage deck (#109)
- **Issue #105** (closed): CI: run behavioral SPI and refresh Verilog regressions with a pinned simulator
- **PR #106**: CI: run behavioral SPI and refresh Verilog regressions with pinned Icarus (#105)
- **Issue #68** (closed): docs: define provenance and review for appended evidence corrections
- **PR #103**: docs(sim): define correction-record mechanism for appended evidence
- **Issue #98** (closed): Characterize write disturb of unselected and half-selected cells in the extracted 4x4 array
- **PR #102**: feat(sim): write-disturb study of unselected and half-selected cells (#98)
- **Issue #84** (closed): Auditor guard review: worktree-write-confinement
- **Issue #93** (closed): Integrate SPI configuration with the behavioral refresh scheduler and verify transitions
- **PR #99**: feat(digital): integrate SPI config with runtime refresh scheduler (#93)
- **Issue #97** (closed): Density vs 6T SRAM: compute area-per-bit from the committed 4x4 array and compare against public sources
- **PR #101**: Density vs 6T SRAM: area per bit from committed 4x4 array (#97)
- **Issue #81** (closed): Monte Carlo mismatch study of the sense stage: input-referred offset at the restricted corners
- **PR #95**: Monte Carlo mismatch study of the sense stage: input-referred offset at the restricted corners (#81)
- **Issue #80** (closed): Extract read-bitline and wordline parasitics from the 4x4 array to replace the C_RBL assumption
- **PR #90**: Extract 4x4 array bitline/wordline/sn parasitics; compare to C_RBL and C_SN assumptions (#80)
- **Issue #83** (closed): Propose the SPI control interface spec with a behavioral SPI-slave model and testbench (#24 item 4)
- **PR #87**: feat(digital): proposed SPI control interface model (#83)
- **Issue #82** (closed): Draft macro-level pass conditions for epic #24 items 2-6 as a PROPOSED record
- **PR #86**: docs(spec): PROPOSED macro-level pass conditions for epic #24 items 2-6
- **Issue #74** (closed): Refresh scheduler behavioral model with deadline-invariant testbench (#24 item 3)
- **PR #79**: Refresh scheduler behavioral model with deadline-invariant testbench (#24 item 3)
- **Issue #60** (closed): Sense-stage characterization at the restricted corners (after #56)
- **PR #77**: Sense-stage characterization at the restricted corners (#60)
- **Issue #63** (closed): README: reflect cold-corner finding and restricted operating range by reference (after #56)
- **PR #75**: docs(readme): reference proposed restricted operating range and cold-corner evidence
- **Issue #67** (closed): CI: guard simulation evidence with exact byte-prefix comparisons
- **PR #71**: ci(sim): guard simulation evidence with exact byte-prefix comparisons
- **Issue #56** (closed): spec: write the operating-range restriction for the cold corner as a proposed decision record (outcome C, operator ruling 2026-10-08)
- **PR #70**: spec: proposed operating-range restriction for the cold corner (outcome C)
- **Issue #55** (closed): T1 items 3 and 4: stop the bitcell's DRC/LVS reports grading the unbuilt digital partition
- **PR #69**: fix(signoff): scope T1 items 3/4 evidence to analog partition (met 5 -> 3)
- **Issue #58** (closed): Consolidate duplicated waveform/SPICE helpers in sim runners into _evidence_common
- **PR #66**: refactor(sim): consolidate duplicated SPICE/waveform helpers (#58)
- **Issue #61** (closed): CI: run the evidence-chain Python checks (test_analysis, test_variants, check_evidence_index)
- **PR #64**: ci: run evidence-chain Python checks (test_analysis, test_variants, check_evidence_index)
- **Issue #59** (closed): Refresh-overhead envelope: evaluate the ratified §7 formula over N_rows x t_row_refresh_op
- **PR #65**: feat: refresh-overhead envelope (N_rows x t_row_refresh_op) (#59)

### 2026-10-08

- **Issue #54** (closed): T1 item 11 (analog): declare the array's substrate tie, re-run klt erc and LVS, and cite the power-delivery row
- **PR #57**: feat: cite T1 item 11 (analog) via psub substrate tie; pin klt v0.6.0 (#54)

### 2026-10-07

- **PR #52**: Reliability-source search for 1.8 V NMOS overdrive and junction injection (#51)
- **Issue #51** (closed): [Epic #24] Obtain primary reliability evidence for the sky130 1.8 V NMOS beyond its model-validity range
- **PR #50**: Prepare supply and reliability decision record for the sense-path contract (#49)
- **Issue #49** (closed): [Epic #24] Prepare supply and reliability decision record for the sense-path contract

### 2026-10-05

- **PR #48**: Attribute cold-corner read failure and compare WL-boost / RWL-underdrive remedies
- **Issue #47** (closed): [Epic #24] Resolve cold-corner stored-level failure before sense implementation
- **PR #46**: Characterize loaded four-row column stored levels and read separation (#45)
- **Issue #45** (closed): [Epic #24] Characterize achievable stored levels and loaded-column read separation

### 2026-09-22

- **Issue #35** (closed): Champion: Merge-Risk Hold Digest
- **Issue #16** (closed): Champion: Merge-Risk Hold Digest

### 2026-09-21

- **PR #42**: layout: add klt erc supply spec and report for the shared-tap array (issue #39, T1 item 11)
- **Issue #39** (closed): T1 item 11 (power delivery, structural): no klt erc supply spec or report in this repo
- **PR #41**: feat: add klt signoff block manifest with pinned DRC/LVS evidence
- **Issue #40** (closed): Commit a klt signoff block manifest so this block's T1 state is graded, not hand-read

### 2026-09-15

- **PR #38**: Consolidate duplicated sky130 PDK pin config across pdk.json files and hardcoded defaults
- **Issue #37** (closed): Consolidate duplicated PDK pin config across pdk.json files and hardcoded defaults
- **PR #36**: layout: build a shared-tap 4x4 bitcell array from the ratified 2T-min cell
- **Issue #34** (closed): Build a shared-tap bitcell array from the ratified 2T-min bitcell (#24 item 1)

### 2026-09-12

- **Issue #33** (closed): Deduplicate ngspice helper functions across sim/ driver scripts
- **PR #32**: Deduplicate ngspice-resolution helpers across leakage and bitcell-transient scripts
- **Issue #31** (closed): Deduplicate ngspice-resolution helpers across leakage and bitcell-transient scripts
- **PR #30**: docs: refresh stale README status and maturity-ladder position (#29)
- **Issue #29** (closed): README: refresh stale 'no schematics/layout yet' status (T1 item 10)

### 2026-09-10

- **PR #28**: T1 items 5/9: transient write/read/hold PVT testbench for the 2T-min bitcell
- **Issue #27** (closed): T1 items 5/9: transient write/read/hold PVT testbench for the 2T-min bitcell (ngspice, 15 corners, append-only records)
