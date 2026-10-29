# Work Log

Chronological record of merged pull requests and closed issues. Maintained by the Loom Guide role.

### 2026-10-29

- **Issue #44** (closed): README: embed the fleet burndown chart (one line)

### 2026-10-28

- **PR #256**: refactor: single-source inst_lines/ic_tokens in replay_lib
- **Issue #255** (closed): Dedupe inst_lines/ic_tokens: identical copies in two refresh-replay generators
- **PR #254**: docs: refresh density-vs-sram inputs to post-#244 layout (2.79x drawn)
- **Issue #252** (closed): spec: refresh density-vs-sram inputs for the post-#244 layout (2.79x pitch)
- **PR #251**: sim: re-run five benches on the post-#244 layout as new dated evidence
- **Issue #249** (closed): sim: re-run write-disturb, refresh-op, sense-stage, sense-mismatch, column-periphery on the klt-0.8.0 layout
- **PR #248**: fix: regenerate layout with klt 0.8.0 generators for a DRC-clean cell and array
- **Issue #244** (closed): Layout fails new klt 0.8.0 DRC rules (licon1.ongrid.1, poly.endcap.diff.1); generate --check now red

### 2026-10-27

- **PR #246**: refactor: share klt-report corner/measurement helpers in _evidence_common
- **Issue #245** (closed): Consolidate duplicated klt-report corner/measurement helpers into sim/_evidence_common.py
- **PR #243**: build: pin klayout-tools 0.8.0 and regenerate check evidence
- **Issue #242** (closed): Bump klayout-tools pin c622e8addb36 → 0.8.0
- **PR #241**: refactor: share one GDSII record reader across layout scripts
- **Issue #239** (closed): Consolidate three hand-rolled GDSII readers in layout/ into one shared module
- **PR #225**: ci: wire unlisted test suites into evidence-checks and npm test
- **Issue #224** (closed): CI/npm test: wire sim/test_klt_request.py into evidence-checks
- **PR #238**: docs: scope manifest README grep to json files
- **Issue #220** (closed): manifests/artifacts/README.md: documented no-bucket grep matches the README itself

### 2026-10-26

- **PR #219**: feat: store new run evidence in the fleet artifact store via manifests

### 2026-10-23

- **PR #214**: feat(sim): device-inclusive C_SN of the compact v2 array

### 2026-10-20

- **PR #209**: feat: re-characterise C_SN, parasitics and leakage for the compact bitcell layouts
- **Issue #161** (closed): Re-characterise C_SN and array parasitics for the compact bitcell layouts from #100
- **PR #162**: layout: add reproducible compact 2T bitcell variants (1.95 and 1.40 um^2 drawn pitch)
- **Issue #100** (closed): Decision: 2T bitcell is 2.4x larger than public sky130 6T SRAM cell; README density requirement unmet

### 2026-10-17

- **PR #199**: refactor: share anchor-mutant helpers across integration mutation scripts
- **Issue #197** (closed): Consolidate anchor-style mutant helpers left over after #191 (3 run_mutation scripts)
- **PR #198**: refactor: share klt sim request skeleton across sim generators
- **Issue #196** (closed): Consolidate duplicated klt sim request skeleton across 9 sim gen_ scripts
- **PR #193**: refactor: share mutation-check harness across digital run_mutation.sh scripts
- **Issue #191** (closed): Consolidate duplicated mutation-harness loop across digital/*/run_mutation.sh
- **PR #188**: refactor(sim): share gzip-aware JSON report loader via _evidence_common
- **Issue #187** (closed): Consolidate 6 copies of the gzip-aware JSON report loader into _evidence_common
- **PR #186**: refactor(sim): share sha256 and decided() helpers via _evidence_common
- **Issue #185** (closed): Consolidate duplicated sha256 and decided() helpers into sim/_evidence_common.py

### 2026-10-16

- **PR #181**: sim: re-qualify sense-stage under open_pdks f6eeac7 (results unchanged)
- **Issue #170** (closed): Re-qualify G3 sense-path records under open_pdks f6eeac7
- **PR #183**: feat(sim): re-qualify G1 leakage and retention chain under open_pdks f6eeac7
- **PR #178**: docs(layout): re-qualify G5 layout and sign-off records under open_pdks f6eeac7
- **Issue #172** (closed): Re-verify G5 layout and sign-off evidence under open_pdks f6eeac7

### 2026-10-15

- **PR #176**: docs(pdk): use direct stamped-file counts and add helper row in requalification inventory
- **Issue #175** (closed): docs(pdk): reconcile stamped-file counts in pdk-requalification-inventory.md
- **PR #173**: docs(pdk): inventory reference records to re-qualify under open_pdks f6eeac7
- **PR #167**: feat(pdk): re-pin open_pdks to f6eeac7 via ciel and verify PDK revision on resolve
- **Issue #165** (closed): Re-pin open_pdks to f6eeac7 (ciel) — fleet retires volare c6d73a3
- **Issue #117** (closed): Isolation-gate sizing and offset study: stored-'1' sense input erodes at fs/27 C with the #114 column slice
- **PR #160**: Isolation-gate, reference-matching and driver sweep with MC offset (#117)
- **Issue #114** (closed): Design the column periphery (precharge, write driver, column select) to replace ideal sources in the read/write studies
- **PR #118**: design: column-periphery slice and ideal-vs-real comparison (#114)

### 2026-10-13

- **Issue #149** (closed): Geometry-matched access-device leakage: re-measure with extracted AD/AS/PD/PS (testbench passes none)
- **PR #155**: feat(leakage): geometry-matched access-device leakage at extracted AD/AS/PD/PS (#149)

### 2026-10-11

- **Issue #156** (closed): Guard telemetry: retain confinement for unresolved scratch writes
- **Issue #157** (closed): Define the physical SPI crossing and reset architecture before controller synthesis
- **PR #158**: docs(digital): PROPOSED SPI crossing and reset architecture with protocol model (#157)
- **Issue #91** (closed): Committed 4x4 array GDS no longer reproduces from generate_array.sh with current klt (0.6.0 vs 0.7.0 geometry drift)
- **PR #153**: feat(layout): pin the array generation toolchain and compare --check output with the committed 4x4
- **Issue #146** (closed): Integrate live SPI configuration with the duration-coupled phase sequencer
- **PR #151**: feat(digital): SPI-configured scheduler driving the phase sequencer (#146)
- **Issue #89** (closed): Array-context storage-node capacitance is 17-22% below the single-cell C_SN used by retention
- **PR #150**: Array-context C_SN comparison and proposed retention-input decision (#89)

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
