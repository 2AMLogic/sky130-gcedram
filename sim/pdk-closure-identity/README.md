# `pdk-closure-identity/` -- static PDK model-closure identity check (issue #338)

A checker plus a committed evidence record that answer one question without
running any SPICE: **do the two open_pdks revisions used around the
ngspice-46 -> ngspice-47 upgrade feed the loaded-column decks identical
model content?** Because a PDK revision can only change a simulation result
through the model content a deck actually instantiates, content identity of
that set -- established statically from the two PDK trees -- excludes the
PDK revision as a cause at **every** corner of the grid, not just the
probed ones. This is the basis on which
[`spec/operating-range-decision-PROPOSED.md`](../../spec/operating-range-decision-PROPOSED.md)
section 11 extends the PDK-revision exclusion grid-wide.

## What it does

[`check_closure_identity.py`](check_closure_identity.py) takes two PDK roots
plus one or more committed klt request JSONs and, for **each corner section
those requests declare**, resolves the model closure recursively from the
request's own `models.lib` entry point (never a hardcoded directory),
honouring `.lib <section>` ... `.endl` gating and relative `.include`s. It
then reports, per section:

* the closure file count per root, the path-set difference, and per-path
  byte differences (sha256 both sides);
* the PDK models the referenced decks **instantiate** (parsed from the
  decks' element cards), with content identity per instantiated model --
  comparing same-named `.model`/`.subckt` blocks as an **unordered
  multiset**, so redefining one name in several files (the
  `sky130_fd_pr__nfet_20v0_base.0` 20 V family, or the
  `models_fet.spice` monolith-to-split refactor) does not read as a delta;
* every closure delta classified **inside** or **outside** the
  instantiated-model set, where "inside" means: an instantiated block's
  content multiset differs, **or** a `.param` whose value flows into an
  instantiated model differs -- including parameters defined in files that
  hold no instantiated block, reached by tracing parameter consumption
  transitively (a `.param` referenced by a consumed parameter's definition
  is itself consumed);
* any differing content line attributable to neither a block nor a
  parameter definition (unclassified) is treated as **inside** -- the check
  fails loudly rather than pass on content it cannot attribute.

Exit status: `0` = every delta outside the instantiated set (the two trees
are equivalent for these decks); `1` = at least one delta inside (a future
PDK bump that touches a model the decks use fails here); `2` = unclear
input (missing entry point, corner section absent from one tree, a deck
referencing a model absent from the closure) -- never a silent pass.

## Committed evidence record

[`results/closure_identity_c6d73a3_vs_f6eeac7_20261116.json`](results/closure_identity_c6d73a3_vs_f6eeac7_20261116.json)
compares open_pdks `c6d73a3` (`~/.volare`, retired tree, read deliberately
-- the same convention as the per-corner probes) against `f6eeac7`
(`~/.ciel`) over all ten committed loaded-column requests (all five process
sections ss/sf/tt/fs/ff; the eight `lc_*.spice` decks). It records both
`open_pdks` revisions (from each tree's `SOURCES`), both tree paths, the
klt version, the generation date, and per section:

* closure files **119 vs 141** per section -- `f6eeac7` splits the
  42186-line `continuous/models_fet.spice` monolith into a 36-line include
  stub plus 22 per-device files (the exact 22-path difference);
* exactly **two byte-differing shared paths**: `models_fet.spice` (the
  split) and `rescap/res_typical__cap_typical.spice`;
* block-name sets identical (290 blocks over 287 names per side) and every
  block's content multiset identical, including the redefined
  `sky130_fd_pr__nfet_20v0_base.0`;
* `sky130_fd_pr__nfet_01v8` -- the **only** PDK model the eight decks
  instantiate, 1024 deck references -- content-identical (same block
  sha256 on both sides, every section);
* 299 `.param` deltas, all `only-b` and all **outside**: the added
  interconnect-capacitance coefficient block (`cp*`/`cl*`/`cm*`/`crdl*`,
  `rrdl`, `rcrdlcon`, ...) is consumed only by the R/C models in
  `models_resistors.spice` / `models_capacitors.spice`, which no deck
  instantiates;
* verdict `all-deltas-outside-instantiated-set`, exit 0.

Evidence here is append-only like every `results/` file: a re-run that must
be recorded writes a **new** dated record; a committed one is never edited.

## What it does not prove

* It is a **static file-content argument, not a simulation**. It does not
  supersede the committed per-corner probes
  (`sim/loaded-column/results/pin-attribution/`) -- those remain the direct
  numerical evidence and stay exactly as recorded.
* It covers **this deck set only**: the eight `lc_*.spice` decks, which
  instantiate exactly `sky130_fd_pr__nfet_01v8`. Other studies' decks
  (sense-stage, refresh-energy, leakage, retention, ...) instantiate
  different devices and are **not** covered unless the checker is run over
  their own requests and passes.
* It does not retire the PDK-attribution question in the per-group
  re-qualification issues (#166, #171, #182, #301); #182/#301 are
  `loom:operator` and a human's.
* Nothing is concluded about files the closure does not reach, or about
  *why* ngspice-47 moves numbers (tracked in #300).

## The `models_lib_sha256` caveat

`environment.models_lib_sha256` in klt reports is a hash of the **entry
point file only** (`sha256_file(models_lib)`, klt `sim.py:4451`; klt issue
#2522). Both revisions' entry point is byte-identical (`48de7c67...`), so
that field is the **same on both sides despite the closures differing** --
it must not be cited as PDK-revision evidence. This is the same caveat
already recorded at [`sim/sense-stage/README.md`](../sense-stage/README.md)
("It hashes only the top-level `sky130.lib.spice`, so it does not
distinguish the two revisions"). The relevant klt capability gap (a
closure-wide models hash) is a tool issue, not a design one, and belongs
in the `2AMLogic/klayout-tools` tracker per the friction protocol.

## Reproduce

Requires the two open_pdks trees on the host; no ngspice, no klt run, no
network (the klt version is stamped into the record via `klt --version`
when available, or `--klt-version`):

```bash
python3 -I sim/pdk-closure-identity/check_closure_identity.py \
    --root-a ~/.volare --root-b ~/.ciel \
    --request sim/loaded-column/klt/request_*.json \
    --out /tmp/closure_identity_new.json   # compare against the committed record
python3 -I sim/pdk-closure-identity/test_check_closure_identity.py
```

The tests run entirely over small synthetic PDK trees in temporary
directories (monolith-split refactor, additive outside `.param`, same-name
redefinition order, an in-set model delta that must fail, a
corner-section-gated include, the parameter-provenance cases, and the
error edges) -- no PDK install needed.
