# T1 analog attestation: items 1, 2, 9, 10 attested (issues #192, #229)

**Evidence record, not a spec change.** It changes no ratified value and
relaxes no ratified spec. It records how the analog partition's T1 checklist
items 2, 9 and 10 are graded `met`, why item 1 is not, and how each is
re-attested. `t1_met_count` goes from 3 to **6** (analog items 2, 3, 4, 9, 10,
11); the digital partition is unchanged (all unmet).

Tool: klayout-tools 0.8.0, the pin in `.github/workflows/signoff.yml`. This
change does not touch that pin or any `layout/*.result.json`.

## What is attested

| Item | Inventory / envelope | Binds | Re-attest |
|---|---|---|---|
| 2 Layout | `attest/item2.envelope.json`, written by `attest/make_item2_envelope.py` (klt has no producer for item 2) | `layout/gain_cell_2t.gds`, `layout/gain_cell_2t_array.gds`, `layout/generate.sh`, `layout/generate_array.sh`, `layout/generation_toolchain.py` through `provenance.input.paths` | Re-run the script; the manifest pin is the combined digest, so editing any member makes the row stale |
| 9 Testbenches | `attest/item9.json` -> `attest/item9.envelope.json` | every committed ngspice deck and `klt sim` request under `sim/` (benches, not recorded results), plus the new `sim/cold-start/request.json`; PDK `sky130A` at open_pdks `f6eeac7` (`docs/pdk-pin.md`), klt 0.8.0, ngspice 46 | **Locally** (needs ngspice and the pinned PDK): `klt signoff --attest 9 --inventory attest/item9.json -o attest/item9.envelope.json` |
| 10 Repo hygiene | `attest/item10.json` -> `attest/item10.envelope.json` | `README.md`, `LICENSE`, `spec/README.md`, `docs/pdk-pin.md`, both workflows; 26 `evidence-checks.yml` commands and the 4 `klt drc/lvs --check` commands of `signoff.yml` | `klt signoff --attest 10 --inventory attest/item10.json -o attest/item10.envelope.json`; CI re-runs `--check` |

Item 9's cold start is **one single-corner request** (tt, 125 C) over the
sense-stage deck, run with `klt sim --backend local`, about 40 s. Every other
committed request is a multi-corner grid that belongs on the batch fleet; none
is reused. The cold start is marked `local_only`, so `--check` on a runner
without ngspice skips it and carries the committed outcome. CI therefore
cannot catch a broken cold start; it does catch an edited inventory or an
edited inventoried file, through the manifest hash pin and the envelope check.
Re-attest item 9 locally whenever a bench or the PDK pin changes. No ngspice,
xschem or PDK is installed in CI.

## Item 1 attested (issue #229; was a named gap in #192)

Item 1 (Design sources) is attested by `attest/item1.json` ->
`attest/item1.envelope.json`, pinned as `1.analog`. The freshness chain has two
legs, both declared in the inventory:

- schematic -> raw: `klt netlist design/<cell>.sch -o design/<cell>.raw.spice
  --check` (committed `design/<cell>.raw.spice`, repo-relative `sch_path`).
  `local_only`: it needs xschem >= 3.4.5, which the CI runner lacks, so CI
  carries the committed outcome; workers (xschem 3.4.7) run it for real.
- raw -> normalized: `python3 -I design/normalize_netlist.py --check RAW NORM`,
  a pure function of the committed files that also verifies the header's
  schematic sha256. Runs in CI.

`design/regen_netlist.sh` now goes through `klt netlist` (no raw `xschem`),
and `--check` runs both legs. The committed normalized netlists are
byte-identical to before. The earlier note that 3.4.4 refuses `--check`
no longer applies on workers (3.4.7). Gap to know: klt 0.8.0 pins only the
inventory hash for item 1, so an edited source is caught by `--check`
(CI and `regen_netlist.sh --check`), not by the manifest pin alone.

## Negative controls (scratch, not committed)

Run against the committed envelopes with klt 0.8.0:

- Item 2: appended a line to `layout/generate.sh`. `klt signoff --manifest
  block-manifest.json --check block-manifest.signoff.json` exits **3**
  (`drifted`); the row grades `unmet`, `reason: stale_evidence`.
- Item 10: appended a blank line to `README.md`. `klt signoff --attest 10
  --inventory attest/item10.json --check attest/item10.envelope.json` exits
  **3**.

Both files were restored with `git checkout`; nothing from the controls is
committed.

## Addendum: item 10 also graded for the digital partition (issue #235)

**Evidence record, not a spec change.** `block-manifest.json` now cites the same
`attest/item10.envelope.json` for `10.digital`, so `t1_met_count` goes from 6 to
**7** (digital item 10 `met`; every other digital row stays unmet). klt 0.8.0
is unchanged, no `KLT_REV`/workflow pin bump, nothing under `sim/` touched.

- `attest/item10.json` additionally inventories, by content hash only,
  `.github/workflows/digital-regressions.yml`,
  `digital/ci/run_digital_regressions.sh` and `digital/ci/README.md`.
- The ~17 min digital regression is **not** a graded command: it needs a
  source-built Icarus Verilog, and `evidence-checks.yml` has no such toolchain.
  `README.md` documents the reproduce steps instead.
- Negative control: appending a line to `digital/ci/README.md` makes
  `klt signoff --attest 10 --inventory attest/item10.json --check
  attest/item10.envelope.json` exit **3**. `--manifest ... --check` still exits
  0 in that case, because the manifest pin covers the inventory file, not the
  inventoried files; the envelope `--check` in `signoff.yml` is what catches it.

## Addendum: item 1 negative control (issue #229)

Edited `W=0.42` to `W=0.43` on `M_WR` in `design/gain_cell_2t.sch` (scratch,
reverted): `design/regen_netlist.sh --check` exits **1** with the raw netlist
stale and the normalized header sha256 stale; the other two cells stay OK.
Hand-editing a normalized `.spice` fails `normalize_netlist.py --check`
(`design/test_normalize_netlist.py`). Graded with klt 0.8.0: `t1_met_count`
8 -> 9, `1.analog` `met`.
