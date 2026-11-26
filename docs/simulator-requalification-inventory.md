# Simulator re-qualification inventory under the `ngspice-47` pin

Deliverable of issue #300. **Documentation only: no simulation was run
and no existing record was edited.** Companion to
[`docs/pdk-requalification-inventory.md`](pdk-requalification-inventory.md)
(the `open_pdks` `c6d73a3` -> `f6eeac7` inventory, #166): that document
tracks the PDK half of the toolchain pin, this one the simulator half.

## The pin

`NGSPICE_VERSION_PIN = "ngspice-47"` in
[`sim/_evidence_common.py`](../sim/_evidence_common.py) — what the batch
fleet image actually runs. The check compares the **parsed major
version** (`ngspice-NN` out of the `ngspice --version` banner), never the
full banner, so build options, compile dates and banner formatting are
not false mismatches. It is surfaced from `check_ngspice_available()`,
the same entry point that already verifies the PDK revision, so every
runner inherits it with no new call site. An unparsable banner —
including `ngspice_version()`'s `"unknown"` failure sentinel — is a
mismatch, not a pass: a record cannot be written with absent simulator
provenance and still satisfy the check.

**A simulator-version change triggers re-qualification on the same terms
as a PDK re-pin**: new append-only records, supersession notes, no
in-place edits of existing records (`sim/check_append_only.py` stays
green). Under the `ngspice-47` pin, every record stamped with a
different major version is *awaiting re-qualification*; executing that
is per-group child work on the #166 pattern, not part of #300.

Why the pin is 47 and not 46: pinning 46 would make the batch fleet
unusable while hiding the drift. Pinning 47 makes the obligation visible
— exactly as re-pinning `open_pdks` in #165 marked the `c6d73a3`
records. The measured magnitude that forced the issue: between
ngspice-46 and ngspice-47 the loaded-column characterization moved up to
8.76e-02 V and -26% latency, with the PDK revision ruled out at
`sf`/125 C (issue #300; probe evidence lives with #169's branch).

## Inventory

Derived at `origin/main` @ `321d974`, 2026-11-15. **Point-in-time:
re-derive before acting.** Record stamps take two forms — the literal
`ngspice-NN` banner string (CSV `ngspice_version` columns and klt-report
`version_banner` strings), and the `"engine_version": "NN"` JSON field
the klt-report-derived summaries carry (the three studies the #300
curation listed as "unconfirmed" are confirmed here: their stamps are
`engine_version` fields inside `results/`, which a literal `ngspice-NN`
grep does not match).

| Study | Stamped record files | Version(s) of record | Awaiting re-qualification | Notes |
|---|---|---|---|---|
| `sim/bitcell-transient` | 21 | ngspice-46 | yes | CSV rows + 20 klt reports |
| `sim/leakage` | 2 | ngspice-46, ngspice-47 | ngspice-46 rows | `leakage_results.csv` carries both (30 vs 15 rows); the ngspice-47 rows match the pin |
| `sim/leakage/compact-geometry` | 2 | ngspice-46 | yes | Missed by the #300 curation's table; added on the Champion's re-derivation |
| `sim/leakage/geometry-matched` | 5 | ngspice-46, ngspice-47 | ngspice-46 records | Both point CSVs are ngspice-47; the klt report and one summary are ngspice-46 |
| `sim/loaded-column` | 2 | ngspice-46 | yes | Base run `20261005T102906Z`; the ngspice-47 head run lives on `feature/issue-169` (PR #302), not on `main` |
| `sim/loaded-column/cold-corner` | 3 | ngspice-46 | yes | Three of the nine ngspice-46 record sets #301's cold-corner question touches |
| `sim/retention` | 3 | ngspice-46 | yes | The klt report also embeds a `ngspice-42` *client* banner (see below) |
| `sim/sense-stage` | 1 | ngspice-46 | yes | Client banner `ngspice-42` embedded |
| `sim/write-disturb` | 1 | ngspice-46 | yes | Client banner `ngspice-42` embedded |
| `sim/column-periphery` | 1 | ngspice-46 | yes | Client banner `ngspice-42` embedded |
| `sim/refresh-energy` | 2 | `"46"` | yes | Stamp is `"engine_version": "46"` in `refresh_energy_summary_*.json` |
| `sim/refresh-op` | 2 | `"46"` | yes | `engine_version` fields in `refresh_op_summary_*.json` |
| `sim/sense-mismatch` | 4 | `"46"` | yes | `engine_version` fields in `mismatch*_summary_*.json` |
| `sim/refresh-replay` | 5 | `"46"` | yes | `engine_version` fields in the run summaries, including the nested `driver_sweep_*`/`init_control_*` directories |
| `sim/refresh-overhead` | 0 | none | n/a | Consumes other groups' recorded numbers; no simulator stamp of its own |
| `sim/cold-start` | 0 | none | n/a | No simulator stamp |

Repo-wide literal occurrences in `sim/` at the same commit: `ngspice-46`
12,679, `ngspice-47` 49, `ngspice-42` 5.

### The embedded `ngspice-42` client banners are not the engine of record

In the `klt_report_*.json` files of `sim/retention`, `sim/sense-stage`,
`sim/write-disturb` and `sim/column-periphery`, the literal `ngspice-42`
string sits inside `environment.engine_build.version_banner` — the
banner of the **local client** binary that submitted the job — while
`environment.engine_version` records the fleet worker engine that
actually ran the deck (`"46"`). The same reports carry klt's
`engine_build_comparison: status "mismatch"` warning naming exactly this
distinction. Those runs' simulator of record is ngspice-46.

## Re-derivation commands

```bash
git grep -liE 'ngspice-[0-9]+' origin/main -- 'sim/**/results/**'   # literal banner stamps
git grep -l  'engine_version'       origin/main -- 'sim/**/results/**'  # JSON-field stamps
git grep -hoiE 'ngspice-[0-9]+'     origin/main -- 'sim/' | sort | uniq -c
```

(Note `sim/*/results` as a pathspec matches nothing — only the `**`
forms above reach the nested `results/` directories.)

## Out of scope here

- **Re-running or re-qualifying any study** — the pin declares the
  obligation; per-group child issues on the #166 pattern execute it.
- **`spec/` decision-record rows for the shifted loaded-column
  numbers** — deferred until PR #302 (which carries the ngspice-47 head
  run) merges, so a row would not cite evidence absent from `main`.
- **A `ss`/-40 C PDK-attribution probe** — the "residual is the
  simulator" attribution is measured at `sf`/125 C only and extrapolated
  elsewhere; the cold-corner probe belongs with #169/#302's evidence.
- **Changing any host or fleet simulator version** — host tooling comes
  from the 2AMLogic/2am worker spec; this document records what the repo
  expects, not what is installed.
