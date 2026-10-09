# Work Log

Chronological record of merged pull requests and closed issues. Maintained by the Loom Guide role.

### 2026-10-09

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
