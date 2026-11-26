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

> Pre-#244 layout (0.859179 fF, `C_SN` 0.605354 fF). Kept as history; the post-#244 re-run is the "Issue #261 addendum" below, and its verdicts differ.

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

## Issue #261 addendum: #88 re-run on the post-#244 layout (append-only)

PR #248 (issue #244) regenerated the layout, so the extracted `C_RBL` moved from 0.859179 to **0.955559 fF** and the extracted `C_SN` from 0.605354 to 0.672741 fF. The #88 evidence above is pre-#244 history and is not edited. New dated runs, same ideal-periphery baseline; nothing is ratified.

| Item | File |
|---|---|
| Loaded-column re-run (section "Issue #261") | [`../extracted-crbl/README.md`](../extracted-crbl/README.md) |
| Sense-stage re-run | [`../../sense-stage/README.md`](../../sense-stage/README.md) (section "Issue #261") |
| Contract row (new dated section) | [`SENSE_INPUT_CONTRACT.md`](SENSE_INPUT_CONTRACT.md) "2026-10-29 addendum" |

Pins:

* `C_RBL` source: `layout/gain_cell_2t_array.parasitics.summary.json`
  `comparison.c_rbl.extracted_4row_worst_total_ff` = 0.955559 fF. Extracted
  netlist sha256 `6469896a403d9da6ba5f7d0ba10616fd0aa1a04470699460893c67b8e44f9e1f`.
* Loaded column, run `20261029T203633Z` (decks in `../extracted-crbl/decks_p244/`):
  * `summary.json` SHA-256 `74243b13d42e702582fcb0bb73db41a64ea71d113a17096f2395db5eae163244`;
  * `cases.csv.gz` SHA-256 `7ab7d170c747e55217f561e269ffb3b19371c65bd657a0ef29deabaafeb49f70`;
  * 10 fleet jobs, 8192 case rows.
* Sense stage:
  * `sense_summary_20261029T194412Z.json` SHA-256 `35762c8fc4a43ed996ab0180d271bd5cc766c5b972835551a1b307e2442fd7ef` (EXTRACTED-4-ROW);
  * `sense_summary_20261029T194413Z.json` SHA-256 `95f2a0116c974f7f8b82955cdef45bb80b91ce094578fb99db30ce136807d71a` (2 fF);
  * `sense_summary_20261029T194414Z.json` SHA-256 `03a33440ef47b82edcc3d15b6b5b5f20b57e0347cf09e643b90d18fcd2c1d66a` (EXTRACTED-4-ROW + layout card).

Check additions in `check_evidence_index.py` (`issue261()`): the hashes above
match; the summary records an OK reproduction of the committed Phase 2 run and
an OK negative control; the run used the cited `C_RBL`; every number quoted in
the contract addendum matches the new summaries. The `issue88()` checks now
read the cited value and netlist hash from the frozen 2026-10-11 summary
instead of the live layout JSON.

**Verdict after #261.** At the bounding extracted load the design-card column
now passes the full grid (30/30). The fs/-40 C aged point is the minimum at
0.102 V against the 0.1 V placeholder, a 2 mV margin, so this is marginal
and not a robust pass. The 2 fF trend variant still fails fs/-40 C
(0.075 V), and the 10 fF reproduction is unchanged. The sense-stage verdicts
did not change (sf/125 C best-reference droop verdict stays `met`). The
supply-option decision record is unaffected.

## Issue #169 addendum: Phase 2 re-qualified under open_pdks `f6eeac7` (append-only)

Group G2a of the #166 re-qualification. **Supersession, not a correction**: the
Phase 2 study ([`../README.md`](../README.md), issue #45) was re-run unchanged
in scope under the forward PDK pin, so the Phase 2 pin cited in "Cited evidence
and pins" above is superseded **for Phase 2 only**. Every section above is
unedited and every record it pins is byte-unchanged; the Phase 3 records in
this directory are **not** superseded -- they remain `c6d73a3` / ngspice-46
(see [`README.md`](README.md) section "PDK pin status" and #301).

| Item | Value |
|---|---|
| Superseded | Phase 2 run `20261005T102906Z` (open_pdks `c6d73a3`, ngspice-46) |
| Superseding | Phase 2 run `20261114T091445Z` (open_pdks `f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7`, ngspice-47) |
| Where | [`../results/loaded_column_results.csv`](../results/loaded_column_results.csv) -- 1920 rows **appended**, 0 `sim_failed`; the `c6d73a3` block is unchanged and remains a byte prefix |
| Summary | [`../results/summary_20261114T091445Z.json`](../results/summary_20261114T091445Z.json) (SHA-256 `77dbd0535d8e1d4961319784a74c462676aec5059e6d3fe92ce991cea3047855`) |
| Executed by | `klt sim` on the AWS batch fleet, 8 requests x 15 corners = 120 units, all `pass`; jobs `klt-sim-79cbeb8482ff`, `0076e86a56b6`, `2347ba3b15f5`, `f5cd4b1fee75`, `602978304e45`, `9a613789fd90`, `c071ae6a92be`, `bfacea7f99c0` |
| PDK gate | worker stamp `open_pdks f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7`, `pdk_stamp_comparison: match` on all eight reports; `../reduce_column_results.py` refuses anything else |
| Decks / requests | [`../klt/`](../klt) (generated by [`../gen_column_requests.py`](../gen_column_requests.py); `--check` fails if committed copies are stale) |

Raw fleet reports (immutable, gzipped):

| File (under `../results/`) | SHA-256 |
|---|---|
| `klt_report_lc_fresh_sel0_20261114T091445Z.json.gz` | `e23f30ce74bb82de31837f45dac413ed7ca7b3016420d08f3d538c85d469ef95` |
| `klt_report_lc_fresh_sel1_20261114T091445Z.json.gz` | `94b8cc47a4d0953e97fddc8a0ba10b71a087d892e5b4377adc552c3e4becd265` |
| `klt_report_lc_fresh_sel2_20261114T091445Z.json.gz` | `af4c4618dc076ecf4a3c88fe76a645230a308f156499fe034d3f2b2e5b4ae04a` |
| `klt_report_lc_fresh_sel3_20261114T091445Z.json.gz` | `5e817ac86d3bd4a44da28341b80ec7a0eb90abe806b492b7f52d7289c233feba` |
| `klt_report_lc_refresh_bound_sel0_20261114T091445Z.json.gz` | `f2ee55005d8a21b595e5c89d4ed843893606863d3b1b2034ecd5b1e503e328c6` |
| `klt_report_lc_refresh_bound_sel1_20261114T091445Z.json.gz` | `1d264394a5db7fb74c3cf5129c2b06e9e4537d19dc3f0dbe3fb45452b95ae73f` |
| `klt_report_lc_refresh_bound_sel2_20261114T091445Z.json.gz` | `38ef5bb004a4ce73a5a5829d5cd4a76f43e1236f7366da6ed515a185cf414447` |
| `klt_report_lc_refresh_bound_sel3_20261114T091445Z.json.gz` | `723cbdb2825e33b4267ba58bb7f4b5f1281e8f6133f767bb120d2ca38c3ce3d1` |

PDK-revision attribution probes (two local single-corner runs differing only in
which open_pdks tree `$PDK_ROOT` resolved to; **456 of 456 valued measurements
bit-identical**, so the model revision moves nothing for this circuit at
sf/125 C):

| File (under `../results/`) | SHA-256 |
|---|---|
| `pin-attribution/klt_report_local_sf125_c6d73a3_ngspice47_20261114T091445Z.json.gz` | `a0f12794450093c1b029809b80162ecbef8721282fc918e8df48af9540399d0e` |
| `pin-attribution/klt_report_local_sf125_f6eeac7_ngspice47_20261114T091445Z.json.gz` | `6b7d61094161d49f208320602b7426302c4b7afe83c7f10c5fba8b624d00fac3` |

Deck-reshape equivalence artifacts (the check that validates differences (1)
and (2) of the re-qualification -- 16 `.control` cases reshaped into 16
independent instances, `.meas` cards replacing waveform interpolation -- at
tt/27 C, fresh, selected row 0, all 16 patterns, same `~/.ciel` open_pdks
`f6eeac7` tree and same ngspice-47 on both sides; worst relative deviation
7.3e-04, within the 1e-03 bound declared in `compare_pins.py`):

| File (under `../results/`) | SHA-256 |
|---|---|
| `equivalence/klt_report_local_tt27_f6eeac7_ngspice47_20261115T101029Z.json.gz` | `e65e731295fb8a077ff1943c3a6454bc8ed6b21ba54555612e97e5af8fdd59f7` |
| `equivalence/run_loaded_column_tt27_fresh_sel0.csv` | `c846ee1be2a1edcfc6acf0a1773181aae84afcc602eee5f59feab424b6840a3f` |

Tabulate it with `python3 -I sim/loaded-column/compare_pins.py --compare-equiv
<report.json.gz> <csv>`.

Verdict unchanged: 150/150 groups still have a positive worst-case separation,
the cold-corner written-level shortfall persists (worst stored '1' storage node
0.8697 V), and no spec threshold was altered. What did move -- up to
8.76e-02 V on `v_rbl_sense_v` and -26% on `latency_s` -- is attributed to the
simulator upgrade (ngspice-46 -> ngspice-47), tracked in **#300**, not absorbed
here. Tabulate it with `python3 -I sim/loaded-column/compare_pins.py`, which
exits 1 while any field is outside its declared comparison tolerance.

