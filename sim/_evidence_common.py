"""Shared helpers for the retention/refresh evidence-chain scripts.

Used by both `sim/leakage/run_leakage_sweep.py` (link 1) and
`sim/retention/derive_retention.py` (links 2/3) of the evidence chain
CLAUDE.md requires. Kept stdlib-only, matching the "Stdlib only, no
virtualenv required" constraint both callers document for themselves.

These are small, evidence-chain-integrity-critical helpers -- in
particular `append_result()` is what both scripts rely on to honor
CLAUDE.md's "sim/ results are append-only evidence." Consolidating them
here means a fix to that guarantee (or to PDK-root resolution, or to the
git-sha provenance stamp written into every result row) applies to both
scripts at once instead of silently drifting between two copies.
"""

from __future__ import annotations

import bisect
import csv
import gzip
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from shutil import which

# Canonical sky130 PDK pin (family/variant/open_pdks commit) for every
# script under sim/ -- the single Python-side source of truth issue #37
# consolidated this to, out of what were previously 7 independently
# hand-maintained copies (three now-deleted sim/*/pdk.json and
# design/pdk.json documentation files, design/env.sh's and
# design/xschemrc's shell/Tcl fallback defaults, and two per-testbench
# DEFAULT_PDK_VARIANT constants). See docs/pdk-pin.md for the full
# rationale and the shell/Tcl-side mirror this cannot eliminate (Python
# constants aren't importable from design/env.sh or design/xschemrc).
#
# sky130 flavor directory to use (A/B differ in metal stack only;
# irrelevant to a device-level SPICE sim or to schematic capture).
DEFAULT_PDK_VARIANT = "sky130A"

# sky130A path to the combined ngspice model library, relative to a PDK
# root's variant directory (e.g. `$PDK_ROOT/sky130A/...`).
DEFAULT_NGSPICE_LIB_REL = "libs.tech/combined/sky130.lib.spice"

# The open_pdks commit the shipped model library is pinned to, quoted in
# the install hint and revision check `check_ngspice_available()` runs.
PDK_OPEN_PDKS_COMMIT = "f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7"

# The simulator major version every runner is pinned to (issue #300) --
# what the batch fleet image actually runs. Pinned and checked exactly
# like the PDK revision above, closing the asymmetry that let committed
# characterization numbers move up to 8.8e-02 V between ngspice-46 and
# ngspice-47 unnoticed (the version was stamped per row, never checked).
# Compared as the major version parsed out of the `ngspice --version`
# banner, not the full banner, so a build-date or banner-format change is
# not a false mismatch. A simulator-version change triggers
# re-qualification on the same terms as a PDK re-pin; see
# docs/pdk-pin.md and docs/simulator-requalification-inventory.md.
NGSPICE_VERSION_PIN = "ngspice-47"


# Default PDK root: where `ciel enable` installs (`~/.ciel/<variant>`). The
# retired volare root (`~/.volare`) is deliberately never searched -- a
# leftover tree there is at a different open_pdks revision.
DEFAULT_PDK_ROOT = "~/.ciel"

# The retired volare PDK root; only named in diagnostics, never resolved to.
STRAY_PDK_ROOT = "~/.volare"

PDK_INSTALL_HINT = (
    "  Install the pinned PDK with ciel, e.g.:\n"
    "    pip install ciel==2.6.1\n"
    f"    ciel enable --pdk-family sky130 -l sky130_fd_pr {PDK_OPEN_PDKS_COMMIT}"
)

# Canonical PROPOSED supply pair for every bench under sim/ -- the same
# consolidation issue #37 did for the PDK pin, applied to the next
# spec-derived constant of that class (out of what were previously 20
# independently hand-maintained copies in five spellings). `VDD_V` quotes
# spec/operating-range-decision-PROPOSED.md:130 ("Proposed interval:
# junction temperature 27 C to 125 C at `VDD` = 1.8 V") and :148 ("the
# grid is `VDD` = 1.8 V only"); both are NOT-RATIFIED, so a ratification
# is one edit here, not twenty. `DELTA_V_V` is the retention-derivation
# half-supply margin, ASSUMED exactly as the spec states it
# (spec/operating-range-decision-PROPOSED.md:19: "`delta_V` = `VDD`/2 =
# 0.9 V ASSUMED"; spec/retention-refresh-budget.md:266 keeps it an open
# ASSUMPTION). Stored levels that merely coincide with 0.9 V (an aged
# stored-'1' grid point, a refreshed-cell pre-read level) are deliberately
# NOT derived from DELTA_V_V -- a level is not the threshold.
VDD_V = 1.8
DELTA_V_V = VDD_V / 2


def resolve_pdk_root(
    cli_pdk_root: str | None,
    env_var: str = "PDK_ROOT",
    default: str = DEFAULT_PDK_ROOT,
) -> Path:
    """Resolve the sky130 PDK root: an explicit CLI override, else the
    named environment variable, else the given default (`~/.ciel`).
    `~/.volare` is never selected implicitly; the resolved tree's
    open_pdks revision is verified against the pin by `pdk_revision_problems`
    (called from the env checks)."""
    if cli_pdk_root:
        return Path(cli_pdk_root).expanduser()
    env_root = os.environ.get(env_var)
    if env_root:
        return Path(env_root).expanduser()
    return Path(default).expanduser()


def repo_git_sha(cwd: Path) -> str:
    """`git rev-parse --short HEAD` run from `cwd`, for the provenance
    stamp written into every appended result row. Returns "unknown" on
    any failure (e.g. no git binary, not a git checkout) rather than
    raising, so evidence collection is never blocked by a missing repo."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=10,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def read_open_pdks_commit(variant_dir: Path) -> str | None:
    """open_pdks revision recorded in `<variant_dir>/SOURCES` (the
    `open_pdks <sha>` line), or None if the file or the line is absent.
    Same parse as `pdk_identity` in layout/generation_toolchain.py."""
    sources = variant_dir / "SOURCES"
    if not sources.is_file():
        return None
    for line in sources.read_text(errors="replace").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "open_pdks":
            return parts[1]
    return None


def pdk_revision_problems(
    variant_dir: Path, expected: str = PDK_OPEN_PDKS_COMMIT
) -> list[str]:
    """Mismatch messages (empty list = the installed variant tree is at the
    pinned open_pdks revision). Missing `SOURCES` is a failure, not a pass:
    an unidentifiable tree cannot back an evidence record."""
    actual = read_open_pdks_commit(variant_dir)
    if actual == expected:
        return []
    sources = variant_dir / "SOURCES"
    if actual is None:
        found = (
            f"no `open_pdks <sha>` line in {sources}"
            if sources.is_file()
            else f"{sources} not found"
        )
        return [f"cannot verify the PDK revision: {found}"]
    return [f"PDK revision mismatch ({sources}): expected open_pdks {expected}, actual {actual}"]


def check_pdk_revision(variant_dir: Path) -> bool:
    """Print `pdk_revision_problems` plus the install hint to stderr;
    True if the tree is at the pin."""
    problems = pdk_revision_problems(variant_dir)
    for p in problems:
        print(f"ERROR: {p}", file=sys.stderr)
    if problems:
        print(PDK_INSTALL_HINT, file=sys.stderr)
        print(
            "  or set PDK_ROOT to an open_pdks sky130A install at that revision.",
            file=sys.stderr,
        )
    return not problems


def resolve_ngspice_lib(pdk_root: Path, variant: str) -> Path:
    """Resolve the combined sky130 ngspice model library path for a given
    PDK root and variant (e.g. "sky130A")."""
    return pdk_root / variant / DEFAULT_NGSPICE_LIB_REL


def ngspice_major_version(version_banner: str) -> str | None:
    """The `ngspice-NN` token parsed out of a `ngspice --version` banner
    line (case-insensitive; e.g. "ngspice-46" out of
    "** ngspice-46 : Circuit level simulation program"), or None if the
    banner carries no parsable version -- including the "unknown"
    sentinel `ngspice_version()` returns on failure. Only the major
    number is kept, so build options, compile date and banner formatting
    are not part of the comparison."""
    m = re.search(r"ngspice-(\d+)", version_banner, re.IGNORECASE)
    return f"ngspice-{m.group(1)}" if m else None


def ngspice_version_problems(
    version_banner: str, expected: str = NGSPICE_VERSION_PIN
) -> list[str]:
    """Mismatch messages (empty list = the simulator that would stamp new
    rows is at the pinned major version), mirroring
    `pdk_revision_problems`'s return convention. An unparsable banner --
    including `ngspice_version()`'s "unknown" failure sentinel -- is a
    failure, not a pass: a record cannot be written with absent simulator
    provenance and still satisfy the check (issue #300)."""
    actual = ngspice_major_version(version_banner)
    if actual == expected:
        return []
    if actual is None:
        return [
            "cannot verify the ngspice version: no parsable `ngspice-NN` "
            f"in the version banner {version_banner!r} (expected {expected})"
        ]
    return [f"ngspice version mismatch: expected {expected}, actual {actual}"]


def check_ngspice_version(version_banner: str) -> bool:
    """Print `ngspice_version_problems` plus a remediation hint to stderr;
    True if the simulator is at the pin."""
    problems = ngspice_version_problems(version_banner)
    for p in problems:
        print(f"ERROR: {p}", file=sys.stderr)
    if problems:
        print(
            f"  Run on the batch fleet, whose image runs {NGSPICE_VERSION_PIN};",
            file=sys.stderr,
        )
        print(
            "  a simulator-version change is re-qualified on the same terms as a PDK re-pin "
            "(docs/pdk-pin.md, docs/simulator-requalification-inventory.md).",
            file=sys.stderr,
        )
    return not problems


def check_ngspice_available(ngspice_lib: Path) -> bool:
    """Check that the sky130 ngspice model library exists and `ngspice`
    is on PATH, printing an install hint on failure. Callers with
    additional environment checks (e.g. a testbench template or design
    netlist) run those separately and AND the result with this one.
    Also verifies the PDK revision (issue #165) and the simulator major
    version (issue #300) against their pins, so every runner already
    calling this inherits both checks with no new call site."""
    ok = True
    if not ngspice_lib.is_file():
        print(
            f"ERROR: sky130 ngspice model library not found: {ngspice_lib}",
            file=sys.stderr,
        )
        print(PDK_INSTALL_HINT, file=sys.stderr)
        print(
            "  or set PDK_ROOT to an open_pdks sky130A install at that revision.",
            file=sys.stderr,
        )
        if Path(STRAY_PDK_ROOT).expanduser().is_dir():
            print(
                f"  NOTE: {STRAY_PDK_ROOT} exists but is not searched (retired volare root).",
                file=sys.stderr,
            )
        ok = False
    else:
        # lib = <pdk_root>/<variant>/libs.tech/combined/sky130.lib.spice
        variant_dir = ngspice_lib.parents[len(Path(DEFAULT_NGSPICE_LIB_REL).parts) - 1]
        ok = check_pdk_revision(variant_dir)
    if not which("ngspice"):
        print("ERROR: `ngspice` not found on PATH.", file=sys.stderr)
        ok = False
    elif not check_ngspice_version(ngspice_version()):
        ok = False
    return ok


def ngspice_version() -> str:
    """`ngspice --version`'s banner line naming the version, for the
    provenance stamp written into every appended result row. Returns
    "unknown" on any failure rather than raising."""
    try:
        out = subprocess.run(
            ["ngspice", "--version"], capture_output=True, text=True, timeout=10
        )
        # Line 1 of `ngspice --version` is a "******" banner rule; the
        # actual "ngspice-NN : Circuit level simulation program" line is
        # the first line containing "ngspice".
        for line in (out.stdout or "").splitlines():
            if "ngspice" in line.lower():
                return line.strip()
        return "unknown"
    except Exception:
        return "unknown"


def append_result(results_csv: Path, csv_fields: list[str], row: dict) -> None:
    """Append a single result row immediately, so partial runs (e.g. an
    interrupted sweep) still leave committed-quality evidence for the
    points that did complete, instead of losing everything to an
    all-at-the-end write. Never truncates or rewrites existing rows, per
    CLAUDE.md's 'sim/ results are append-only evidence.'"""
    results_csv.parent.mkdir(parents=True, exist_ok=True)
    write_header = not results_csv.exists()
    with results_csv.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, lineterminator="\n")
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def sha256_hex(path: Path) -> str:
    """Bare hex SHA-256 digest of a file's bytes."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sha256_prefixed(path: Path) -> str:
    """`"sha256:"`-prefixed SHA-256 digest of a file's bytes."""
    return "sha256:" + sha256_hex(path)


def fmt_g6(x: float) -> str:
    """`%.6g` formatting for every value a generator interpolates into a
    committed deck (`.param` cards, PWL vertices, ICs, `.meas` bounds).
    One definition so the deck-emitting generators cannot drift apart on
    number spelling."""
    return f"{x:.6g}"


def load_json(path: Path):
    """Parse a JSON report, gzip-decompressing when the file name ends in
    `.gz` (klt reports are committed as `.json` or `.json.gz`)."""
    path = Path(path)
    opener = gzip.open if path.name.endswith(".gz") else open
    with opener(path, "rt") as fh:
        return json.load(fh)


def corner_key(c: dict) -> tuple[str, int]:
    """(process, temperature_c) key of one klt-report corner."""
    return c["process"], int(c["temperature_c"])


def measurements_of(c: dict, strict: bool = False) -> dict[str, float | None]:
    """`{name: value}` for one klt-report corner's measurements. A
    measurement with no `value` key (or a null one) maps to None, which
    `decided()` reads as "none". With `strict=True` a measurement whose
    `value` key is absent raises ValueError instead, for benches that
    treat a malformed report as a hard failure rather than a missing
    sample."""
    out: dict[str, float | None] = {}
    for m in c.get("measurements") or []:
        if strict and "value" not in m:
            raise ValueError(f"corner {c.get('corner_id')}: measurement {m.get('name')!r} has no value")
        out[m["name"]] = m.get("value")
    return out


def load_clean_corners(report: dict) -> dict[tuple[str, int], dict[str, float | None]]:
    """Measurements of every corner in a loaded klt report keyed by
    `corner_key`; exits if any corner's status is not `pass`."""
    out = {}
    for c in report["corners"]:
        if c.get("status") != "pass":
            raise SystemExit(f"corner {corner_key(c)} status {c.get('status')}: not a clean run")
        out[corner_key(c)] = measurements_of(c)
    return out


def decided(dend: float | None, threshold_v: float) -> str:
    """Classify a sense-amp differential into the recorded bit: `"1"` if
    dend <= -threshold_v, `"0"` if dend >= +threshold_v, `"unresolved"`
    between, `"none"` when there is no measurement. Shared so a
    threshold-edge fix reaches every bench at once."""
    if dend is None:
        return "none"
    if dend <= -threshold_v:
        return "1"
    if dend >= threshold_v:
        return "0"
    return "unresolved"


def tdec_in_window(tdec: float | None, window_s: float) -> bool:
    """True only for a measured decision time `0 < tdec <= window_s`.

    `tdec` is the difference of two independently-located ngspice crossings
    (latch enable, then the |d| target). A non-positive value means the target
    crossed at or before the enable -- not a decision time -- so it must not
    count as a fast resolve. Shared so every bench uses one definition."""
    return tdec is not None and 0 < tdec <= window_s


# --------------------------------------------------------------------------
# Design-netlist card parsing (issue #293) -- the {device: (nets, model,
# params)} view of a committed design/*.spice netlist that deck generators
# emit device cards from, so a simulated device can never drift from the
# schematic-derived netlist (design/regen_netlist.sh --check keeps that
# file fresh). Moved from gen_column_periphery.py, which had been the sole
# definition; the sense-stage / sense-mismatch / refresh-op / refresh-replay
# generators previously retyped the latch geometry and silently dropped the
# nrd/nrs/sa/sb/sd tokens the design netlist carries.
# --------------------------------------------------------------------------

def join_lines(text: str) -> str:
    return re.sub(r"\n\+", " ", text)


def parse_cards(path: Path) -> dict[str, tuple[list[str], str, str]]:
    """{device: (nets[D G S B], model, trailing params)} for every X card."""
    out = {}
    for line in join_lines(path.read_text()).splitlines():
        if line.startswith("*"):
            continue
        t = line.split()
        if t and t[0].startswith("XM"):
            out[t[0][1:]] = (t[1:5], t[5], " ".join(t[6:]))
    return out


# --------------------------------------------------------------------------
# Worker PDK stamp gate (issue #377 / #171) -- the fail-closed check a
# reducer runs on a `klt sim` batch report before letting it qualify a new
# evidence record. `run_leakage_sweep.py` carries the original inline copy
# (kept: its docstring names the #168 incident); this shared shape exists
# so the G4 refresh reducers apply the identical rule instead of retyping
# it: only `environment.remote.worker_environment.pdk_stamp_comparison
# .status == "match"` qualifies, and a missing block or stamp text that
# does not name the pinned commit is a failure, never a pass.
# --------------------------------------------------------------------------

def worker_pdk_stamp_problems(rep: dict, expected: str = PDK_OPEN_PDKS_COMMIT) -> list[str]:
    """Mismatch messages (empty list = the report's batch worker executed
    the pinned open_pdks revision). Fail closed, exactly like the leakage
    guard: a report with no `pdk_stamp_comparison` block, a status other
    than "match" (mismatch, not_comparable, client_stamp_unavailable ...),
    or a worker stamp text that does not name `expected` cannot back a
    qualified record."""
    remote = (rep.get("environment") or {}).get("remote") or {}
    worker_env = remote.get("worker_environment") or {}
    stamp_cmp = worker_env.get("pdk_stamp_comparison") or {}
    stamp_text = (worker_env.get("pdk") or {}).get("stamp_text", "unknown")
    if stamp_cmp.get("status") != "match":
        return [
            f"worker PDK stamp comparison status={stamp_cmp.get('status')!r} "
            f"(worker stamp {stamp_text!r}); the worker's open_pdks revision is "
            f"not proven at the pin {expected}"
        ]
    if expected not in str(stamp_text):
        return [
            f"worker PDK stamp comparison is 'match' but the worker stamp text "
            f"{stamp_text!r} does not name the pinned commit {expected}"
        ]
    return []


# --------------------------------------------------------------------------
# Evidence-summary preamble (issue #292) -- the spec-derived status/scope
# literals and the klt provenance envelope that the sim/*/analyze_*.py
# summaries re-spelled inline, eight copies across two drift-grown spellings.
# The operating-range decision is PROPOSED, not ratified: when
# ratification/ee-key/ and ratification/market-key/ sign, the status and
# every scope string must flip together, and this is the one edit point that
# makes that flip reach every bench at once (same rationale as decided()
# above). The emitted bytes are pinned by each bench's committed summary
# (sim/check_append_only.py), so key spellings and field order here are
# contract, not style.
# --------------------------------------------------------------------------

PROPOSED_RANGE_STATUS = "PROPOSED_OPERATING_RANGE_NOT_RATIFIED"

PROPOSED_RANGE_SCOPE = (
    "27 C and 125 C, tt/ss/ff/sf/fs global corners, VDD=1.8 V, "
    "per spec/operating-range-decision-PROPOSED.md"
)

# The refresh-replay family's committed summaries pre-date the "=" spelling
# above and append per-bench tails ("no mismatch", "ideal drivers", the
# "(PROPOSED range, not ratified)" tag); their shared prefix stays under its
# own constant until a ratified value replaces both spellings together.
PROPOSED_RANGE_SCOPE_REPLAY_PREFIX = (
    "27 C and 125 C, tt/ss/ff/sf/fs global corners, VDD 1.8 V"
)


def klt_provenance(
    rep: dict,
    *,
    hash_prefix: str = "",
    engine: bool = False,
    status_key: str = "klt_status",
    pre_batch: dict | None = None,
) -> dict:
    """Provenance envelope of one loaded klt report, in the field order the
    committed summaries pin: `status_key`, `corner_count`, any `pre_batch`
    extras, `batch_job_id`, `batch_instance_type`,
    `{hash_prefix}netlist_sha256`, `{hash_prefix}models_lib_sha256`, an
    optional `engine`, `engine_version`.

    `hash_prefix="report_"` reproduces the refresh-replay family's key
    spellings (their summaries prefix the two report hashes); `engine=True`
    adds the `engine` key those summaries carry next to `engine_version`;
    `status_key="status"` reproduces refresh-energy's nested `klt.main` /
    `klt.fine` spelling; `pre_batch` inserts extra keys after
    `corner_count` (sense-mismatch's `klt_errored`/`monte_carlo`,
    refresh-energy's `klt_version`). Insertion order is part of the
    contract: summaries are dumped with json.dumps, so a reordered key is
    a changed evidence byte."""
    env = rep.get("environment", {})
    remote = env.get("remote", {})
    out = {status_key: rep.get("status"), "corner_count": rep.get("corner_count")}
    if pre_batch:
        out.update(pre_batch)
    out["batch_job_id"] = remote.get("job_id")
    out["batch_instance_type"] = remote.get("instance_type")
    out[f"{hash_prefix}netlist_sha256"] = env.get("netlist_sha256")
    out[f"{hash_prefix}models_lib_sha256"] = env.get("models_lib_sha256")
    if engine:
        out["engine"] = env.get("engine")
    out["engine_version"] = env.get("engine_version")
    return out


# Repo root (the directory containing sim/), for the repo-relative
# provenance paths recorded below. Derived from __file__ so it is correct
# in any checkout, worktree or CI runner.
REPO_ROOT = Path(__file__).resolve().parent.parent


def c_sn_provenance_json(prov: dict) -> dict:
    """JSON-ready copy of a `load_extracted_c_sn` provenance dict, safe to
    embed in emitted evidence: `extract_json_path` (which the loader
    returns as a Path) is rewritten to a repo-root-relative POSIX string,
    the machine-independent shape refresh-energy summaries already record
    (an absolute path differs between worktrees / CI runners). Every other
    key passes through unchanged and in the same order. A report resolving
    outside REPO_ROOT is refused with a clear message instead of a
    traceback mid-generation -- recording a machine-specific absolute path
    there would poison the evidence chain this field exists to carry."""
    out = dict(prov)
    path = Path(out["extract_json_path"]).resolve()
    try:
        out["extract_json_path"] = path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        raise SystemExit(
            f"ERROR: extracted-C_SN report {path} resolves outside the repo root "
            f"{REPO_ROOT}; refusing to record a machine-specific absolute path "
            "in evidence (c_sn_provenance_json)"
        ) from None
    return out


# --------------------------------------------------------------------------
# SPICE number / waveform helpers (issue #58) -- shared by
# sim/bitcell-transient/run_bitcell_transient.py and
# sim/loaded-column/run_loaded_column.py (and, via the latter, the
# cold-corner variant runner). Stdlib only, no numpy.
# --------------------------------------------------------------------------

SI_SUFFIX = {
    "f": 1e-15,
    "p": 1e-12,
    "n": 1e-9,
    "u": 1e-6,
    "m": 1e-3,
    "k": 1e3,
    "meg": 1e6,
    "g": 1e9,
}


def spice_number(text: str) -> float:
    """Parse a SPICE numeric literal with an optional engineering suffix
    (`100p`, `21n`, `1.8`, `1meg`). Raises ValueError on anything else
    (including an unknown suffix) -- a silently mis-parsed timing
    parameter would move a measurement instant. Callers that want to skip
    non-numeric `.param` values catch ValueError."""
    m = re.fullmatch(r"([+-]?[0-9]*\.?[0-9]+(?:[eE][+-]?[0-9]+)?)\s*([A-Za-z]*)", text)
    if not m:
        raise ValueError(f"not a SPICE numeric literal: {text!r}")
    value = float(m.group(1))
    suffix = m.group(2).lower()
    if not suffix:
        return value
    if suffix.startswith("meg"):
        return value * SI_SUFFIX["meg"]
    if suffix[0] in SI_SUFFIX:
        return value * SI_SUFFIX[suffix[0]]
    raise ValueError(f"unknown SPICE suffix in {text!r}")


def read_wrdata(path: Path, min_points: int) -> list[list[float]]:
    """Parse an ngspice `wrdata` ASCII table into columns.

    `wrdata out v(a) v(b) ...` emits one (x, y) column PAIR per vector, so
    a row is [t, y1, t, y2, ...]. Returns `[t, y1, y2, ...]` (the shared
    time column once, then each vector's y column). Rows with fewer than 4
    fields or non-numeric fields are skipped. Raises RuntimeError if fewer
    than `min_points` timepoints were parsed (the caller picks the limit:
    3 for the bitcell transient, 10 for the loaded column).
    """
    cols: list[list[float]] | None = None
    for line in Path(path).read_text().splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            row = [float(x) for x in parts]
        except ValueError:
            continue
        if cols is None:
            cols = [[] for _ in range(len(row) // 2 + 1)]
        cols[0].append(row[0])
        for i in range(len(row) // 2):
            cols[i + 1].append(row[2 * i + 1])
    if cols is None or len(cols[0]) < min_points:
        raise RuntimeError(f"ngspice produced too few timepoints in {path}")
    return cols


def interp_at(t: list[float], y: list[float], tq: float) -> float:
    """Linear interpolation of y(tq) on a non-decreasing t, clamped to the
    end values outside the sampled window. Duplicate timestamps do not
    divide by zero."""
    if tq <= t[0]:
        return y[0]
    if tq >= t[-1]:
        return y[-1]
    hi = bisect.bisect_right(t, tq)
    lo = hi - 1
    if t[hi] == t[lo]:
        return y[lo]
    frac = (tq - t[lo]) / (t[hi] - t[lo])
    return y[lo] + frac * (y[hi] - y[lo])


def first_crossing_below(
    t: list[float], y: list[float], threshold: float, t_from: float
) -> float | None:
    """ABSOLUTE time of the first fall to `threshold` at or after `t_from`,
    linearly interpolated between the bracketing timepoints. If the first
    sample at/after `t_from` is already <= threshold, that sample's time is
    returned (no interpolation from `t_from`). None if never reached.
    Contrast `first_below()`."""
    prev_t = None
    prev_y = None
    for ti, yi in zip(t, y):
        if ti < t_from:
            continue
        if prev_t is not None and yi <= threshold < prev_y:
            if prev_y == yi:
                return ti
            frac = (prev_y - threshold) / (prev_y - yi)
            return prev_t + frac * (ti - prev_t)
        if prev_t is None and yi <= threshold:
            return ti
        prev_t, prev_y = ti, yi
    return None


def first_below(t: list[float], y: list[float], t0: float, level: float) -> float | None:
    """Time RELATIVE to `t0` at which y first reaches <= level (linear
    interpolation, bracket starting at max(t[i-1], t0)). Returns 0.0 if y
    is already <= level at t0; None if never reached. Contrast
    `first_crossing_below()` (absolute time, different already-below and
    bracketing behaviour, different argument order)."""
    if interp_at(t, y, t0) <= level:
        return 0.0
    for i in range(1, len(t)):
        if t[i] <= t0:
            continue
        if y[i] <= level:
            ta = max(t[i - 1], t0)
            ya = interp_at(t, y, ta)
            return ta + (level - ya) / (y[i] - ya) * (t[i] - ta) - t0
    return None
