# Evidence index: supply and reliability decision package (issue #49)

Epic #24 phase 4. Documentation and evidence only: **no new simulation was
run** (the committed Phase 2/3 data was sufficient to inventory stresses; new
sweeps would not supply the missing reliability limits). Nothing is ratified.

## Deliverables

| Item | File |
|---|---|
| Stress/limit inventory (A, B, C; DOC vs MODEL vs UNAVAILABLE) | [`STRESS_LIMIT_INVENTORY.md`](STRESS_LIMIT_INVENTORY.md) |
| PROPOSED decision record and verdict | [`spec/supply-reliability-decision-PROPOSED.md`](../../../spec/supply-reliability-decision-PROPOSED.md) |
| Sense-characterization input contract | [`SENSE_INPUT_CONTRACT.md`](SENSE_INPUT_CONTRACT.md) |
| Primary-source pin (SkyWater PDK device page) | [`sources/skywater-pdk-device-details-excerpt.md`](sources/skywater-pdk-device-details-excerpt.md) |
| Reference/pin/number check | [`check_evidence_index.py`](check_evidence_index.py) |

## Cited evidence and pins

| Source | Pin |
|---|---|
| Phase 3 study | [`README.md`](README.md) (commit `5fb6729`, PR #48), run ids `20261005T135553Z`, `20261005T141748Z`, analysis `results/summary_20261005T145658Z.json` (SHA-256 `5c449e87c4b492d8a746a7e5edbdf1f247204b57e4ea87b10112570b85d15df4`) and `results/pass_fail_20261005T145658Z.csv` (SHA-256 `42fc77a6d56f82822520ecbc5bd0d0fcb7905e88eeadcedd698885f0a202ae99`) |
| Phase 2 | [`../README.md`](../README.md), run `20261005T102906Z`, [`../results/summary_20261005T102906Z.json`](../results/summary_20261005T102906Z.json) |
| Bitcell netlist | [`design/gain_cell_2t.spice`](../../../design/gain_cell_2t.spice) (schematic sha256 `1e778b71...927e` recorded in the file header) |
| Ratified retention chain | [`spec/retention-refresh-budget.md`](../../../spec/retention-refresh-budget.md) |
| PDK | open_pdks `c6d73a35f524070e85faff4a6a9eef49553ebc2b`, `sky130A` ([`docs/pdk-pin.md`](../../../docs/pdk-pin.md)); combined model library SHA-256 `48de7c677e2c6e7d09b2559279de9f818be71010a4aa933d728eb4db3b133c84` |
| Simulator | ngspice-46 (as stamped on every result row) |
| Primary SKY130 documentation | skywater-pdk `docs/rules/device-details.rst`, last commit `995acd5dfa0589d156619694db011873796a5d2d`; main HEAD at retrieval `7198cf647113f56041e02abf3eb623692820c5e1` |

The `results/*.csv` files are append-only; the check therefore pins immutable
analysis outputs by hash and the append-only CSVs by run id and row count
lower bound.

## Check

```bash
python3 sim/loaded-column/cold-corner/check_evidence_index.py          # offline; exit 0 = pass
python3 sim/loaded-column/cold-corner/check_evidence_index.py --online # also re-fetches the PDK page
```

It verifies (1) every relative Markdown link in the four documents above
resolves, (2) the analysis-file hashes, run ids and row counts, (3) the
PDK pin text agrees across `docs/pdk-pin.md`, `sim/_evidence_common.py`,
the Phase 3 README and, when a PDK is installed, `SOURCES` and the model-library hash,
(4) every number quoted in the inventory/contract/decision record against the
committed summary JSON/CSV, (5) the verbatim PDK validity line in the
excerpt (and live, with `--online`), and (6) that the decision record stays
`PROPOSED` and preserves the ratified values. Exit 1 on any failure.

## Findings that bear on the committed Phase 3 text

* `README.md` section 3 says the under-drive junction current "flows in
  `rwl` ... but not in `rbl`". The committed rows show `rbl` itself reaching
  -0.2 V in 28 of 30 points (the other two reach -0.025 / -0.008 V). See
  inventory section 3. The README is unedited.
* The study used `C_SN` = 0.605354 fF; the ratified retention figure uses an
  assumed 1.106463 fF. Not reconciled here.

## Verdict

**Missing evidence**; see the decision record section 7.

## Issue #51 addendum: reliability-source search (append-only)

Epic #24 phase 5. Research only; **no simulation was run**. The sections above
are unchanged.

| Item | File |
|---|---|
| Search log, source pins, verbatim excerpts, classification | [`sources/reliability-search-log-issue51.md`](sources/reliability-search-log-issue51.md) |
| Inventory update | [`STRESS_LIMIT_INVENTORY.md`](STRESS_LIMIT_INVENTORY.md) section 5.1 |

Pins added: `google/skywater-pdk` HEAD `7198cf647113f56041e02abf3eb623692820c5e1`
(`docs/rules/hv.rst` sha256 `f355ddf478c129661e96b44d4c4509a124e85e2e44d51bd3b072b43aee7e1f98`,
`docs/rules/assumptions.rst` sha256 `99981cebb004a90f7947abc9461f03cdacc4b1906c94f340359c7aeb13f62edc`);
`open_pdks` HEAD `801834fcbf9119e6fd4462f97da9e637f284539a`
(`sky130/magic/sky130.tech` sha256 `5f96a22bd00169807b2228742e17a27e3624e5fb010c523447bbc4fee30a4f97`).

Check additions: the log exists and its links resolve; every pinned hash and
verbatim excerpt is present in the log; the log states the negative result
for (a) and (b); the decision record has the issue #51 evidence status and
remains PROPOSED. With `--online`, `hv.rst` and `assumptions.rst` are
re-fetched from the pinned commit and their sha256 and the quoted excerpts
are verified.

**Verdict after #51**: still missing evidence. No primary reliability source
was found for A or B. Outcome C remains the only option without a missing
stress item; see the decision record section 8.

## Issue #88 addendum: extracted `C_RBL` re-run (append-only)

New simulation evidence on the ideal-periphery baseline. The sections above
are unchanged, and nothing is ratified.

| Item | File |
|---|---|
| Loaded-column re-run, write-up and harness | [`../extracted-crbl/README.md`](../extracted-crbl/README.md) |
| Sense-stage re-run | [`../../sense-stage/README.md`](../../sense-stage/README.md) (section "Issue #88") |
| Contract row (new dated section) | [`SENSE_INPUT_CONTRACT.md`](SENSE_INPUT_CONTRACT.md) "2026-10-11 addendum" |

Pins:

* `C_RBL` source: `layout/gain_cell_2t_array.parasitics.summary.json`
  `comparison.c_rbl.extracted_4row_worst_total_ff` = 0.859179 fF. Extracted
  netlist sha256 `dd2cca26de34d6b7cd39a0d794db64993d6440c5ca7f248cf4d657b6f6b88d33`.
* Loaded column, run `20261011T015419Z`:
  * `summary.json` SHA-256 `77d07c21bcf59aa3c5b81e64c2ceb90026e2ff79788c57a808d4acdd72efe464`;
  * `cases.csv.gz` SHA-256 `48a83f9e2ef56f7f0617eb4c33d241215b35a0ccb549952c9138af8a71f3dbc4`;
  * 10 fleet jobs, 8192 case rows.
* Sense stage:
  * `sense_summary_20261011T015836Z.json` SHA-256 `d171548c93997aa1bd1207f2511d2585eef33bdb1bef4b00781d9779214caa0b` (EXTRACTED-4-ROW);
  * `sense_summary_20261011T020128Z.json` SHA-256 `5a913667308f99335046eb930ecfb5d655e30ba1bb508848ab382deab94a1bda` (2 fF);
  * `sense_summary_20261011T020422Z.json` SHA-256 `39b06ab5d4acba1aa01af6b9b9b8ff5a73c049e87350825312c060a82ff03bad` (EXTRACTED-4-ROW + layout card).

Check additions in `check_evidence_index.py` (`issue88()`):

* the new links resolve;
* the hashes above match;
* the summary records an OK reproduction of the committed Phase 2 run and an
  OK negative control;
* every number quoted in the contract addendum matches the new summaries;
* the original 10 fF contract row and the rules are still present.

**Verdict after #88.** At the bounding extracted load the design-card column
still fails fs/-40 C (0.075 V against the 0.1 V placeholder). ss/-40 C is no
longer marginal. Only the layout-card variant passes the full grid, and only
narrowly. The supply-option decision record is unaffected. Options A and B
were not re-run.
