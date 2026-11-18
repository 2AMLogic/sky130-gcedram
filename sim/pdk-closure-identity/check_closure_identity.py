#!/usr/bin/env python3
"""Static PDK model-closure identity checker (issue #338).

Compares the model content two open_pdks trees would feed a set of klt
simulation requests, **without running any SPICE**: it resolves the model
closure (`.include` / `.lib` graph) from each request's own ``models.lib``
entry point for every corner section the requests declare, then asks one
question -- *is the model content the referenced decks instantiate
identical between the two trees?*

What it proves when it exits 0, per corner section:

* every file the closure reaches is byte-identical, OR every difference is
  provably **outside** the instantiated-model set: a block name the decks
  instantiate has an identical content multiset on both sides, and every
  differing `.param` definition is not consumed (directly or through other
  parameters) by any instantiated block;
* any closure content line that cannot be attributed to a block or a
  parameter definition differs symmetrically.

What it does NOT prove:

* it is a static file-content argument, not a simulation result; it does not
  supersede per-corner probe evidence;
* it covers only the decks named by the requests it was given;
* it does not compare anything the closure does not reach (files the decks
  never load cannot change a result).

Deliberately conservative direction: unmatched or unclassifiable content
differences are reported as *inside* the instantiated set and fail the check
(exit 1).  Unclear input (missing entry point, absent corner section, a deck
referencing a model absent from the closure) is an error (exit 2), never a
silent pass.

Block comparison is order-independent: same-named `.model`/`.subckt` blocks
are aggregated per side into an unordered multiset of normalized contents
before comparing, so a redefinition of one name in several files (e.g. the
`sky130_fd_pr__nfet_20v0_base.0` 20 V family, or a monolith split into
per-device files) does not read as a delta when the contents agree.

``environment.models_lib_sha256`` caveat (see
``sim/sense-stage/README.md``): klt hashes only the entry-point
``sky130.lib.spice``, so that field cannot discriminate PDK revisions whose
closures differ -- this tool exists because that field is insufficient.

Usage (from the repository root, no network, no simulator)::

    python3 -I sim/pdk-closure-identity/check_closure_identity.py \
        --root-a ~/.volare --root-b ~/.ciel \
        --request sim/loaded-column/klt/request_lc_fresh_sel0.json [...] \
        [--out sim/pdk-closure-identity/results/<record>.json]

Exit status: 0 = all deltas outside the instantiated set; 1 = at least one
delta inside it (details in the report); 2 = input error, nothing concluded.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

SCHEMA_VERSION = 1
TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
EXIT_PASS, EXIT_INSIDE, EXIT_ERROR = 0, 1, 2
MAX_LIST = 12  # cap for lists embedded in the JSON report


class CheckError(Exception):
    """Unclear input; exit 2, nothing concluded."""


def fail(msg: str) -> CheckError:
    return CheckError(msg)


# --------------------------------------------------------------------------
# Normalization and file parsing
# --------------------------------------------------------------------------

def strip_comment_tails(text: str) -> str:
    """Drop `;`/`$` comment tails outside single-quoted expressions."""
    out = []
    in_quote = False
    for ch in text:
        if ch == "'":
            in_quote = not in_quote
        elif not in_quote and ch in ";$":
            break
        out.append(ch)
    return "".join(out)


def directive_lines(raw_lines: list[str]) -> list[str]:
    """Whitespace-normalized lines with full-line comments dropped.

    Keeps directive lines (`.include` / `.lib` / `.endl` / `.param` / ...);
    used where the include graph, not the content, is being walked.
    """
    out = []
    for raw in raw_lines:
        line = raw.strip()
        if not line or line.startswith("*"):
            continue
        out.append(" ".join(line.split()))
    return out


def content_line(raw: str) -> str | None:
    """Normalized content line, or None for comments/blanks/directives.

    Strips full-line `*` comments and unquoted `;`/`$` comment tails, then
    collapses whitespace.  Include-graph directives (`.include`, one- and
    two-argument `.lib`, `.endl`) are structure, not content.
    """
    text = " ".join(strip_comment_tails(raw.strip()).split())
    if not text or text.startswith("*"):
        return None
    low = text.lower()
    if (low.startswith(".include") or low.startswith(".endl")
            or low.startswith(".lib")):
        return None
    return text


def parse_lib_sections(raw_lines: list[str]) -> dict[str, list[str]]:
    """`.lib <name>` ... `.endl` regions keyed by section name.

    One-argument `.lib NAME` opens a named block; two-argument
    `.lib FILE SECTION` is a *reference*, not a definition, and is ignored
    here (the closure walker handles it).
    """
    sections: dict[str, list[str]] = {}
    current = None
    for raw in raw_lines:
        line = " ".join(raw.strip().split())
        if not line or line.startswith("*"):
            continue
        low = line.lower()
        m = re.match(r"^\.lib\s+(\S+)\s*$", low)
        if m:
            current = m.group(1)
            sections.setdefault(current, [])
            continue
        if low.startswith(".endl"):
            current = None
            continue
        if current is not None:
            sections[current].append(line)
    return sections


def split_assignments(text: str) -> list[tuple[str, str]]:
    """Split a `.param` card body into `(name, expr)` pairs.

    Assignments are `name = expr` separated by whitespace and/or commas;
    `name=` and `name =` are both accepted.  Name boundaries are only
    recognized outside single-quoted expressions, and only where the name
    starts a token (so `rcon = ...` never yields a param named `con`).
    """
    bounds: list[tuple[int, int, str]] = []  # (name_start, name_end, name)
    in_quote = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "'":
            in_quote = not in_quote
            i += 1
            continue
        if not in_quote:
            m = TOKEN_RE.match(text, i)
            if m:
                prev = text[i - 1] if i > 0 else " "
                after = re.match(r"\s*=", text[m.end():])
                if after and not (prev.isalnum() or prev in "_."):
                    bounds.append((m.start(), m.end(), m.group(0)))
        i += 1
    pairs = []
    for k, (start, end, name) in enumerate(bounds):
        nxt = bounds[k + 1][0] if k + 1 < len(bounds) else len(text)
        expr = " ".join(text[end:nxt].split())
        if expr.startswith("="):
            expr = expr[1:]
        expr = " ".join(expr.split()).strip(",").strip()
        pairs.append((name, expr))
    return pairs


def segment_file(text: str) -> list[tuple[str, str, list[str]]]:
    """Split a file into ordered segments over normalized content lines.

    Returns `("block", name, lines)`, `("param", "", lines)` and
    `("other", "", lines)` segments.  `.model` blocks run to the end of
    their `+` continuations; `.subckt` blocks run to their `.ends`.
    Include-graph directives are not content.  Same-named blocks are legal
    (redefinition) and are simply separate segments; the comparison
    aggregates them per name.
    """
    lines: list[str] = []
    for raw in text.splitlines():
        c = content_line(raw)
        if c is not None:
            lines.append(c)
    segs: list[tuple[str, str, list[str]]] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        low = line.lower()
        if low.startswith(".model") or low.startswith(".subckt"):
            tok = low.split()
            if len(tok) < 2:
                raise fail(f"malformed {tok[0]!r} card: {line[:80]!r}")
            name = line.split()[1]
            body = [line]
            i += 1
            if low.startswith(".model"):
                while i < n and lines[i].startswith("+"):
                    body.append(lines[i])
                    i += 1
            else:
                closed = False
                while i < n:
                    if lines[i].lower().startswith(".subckt"):
                        raise fail(
                            f"nested .subckt not supported: {lines[i][:80]!r}")
                    body.append(lines[i])
                    if lines[i].lower().startswith(".ends"):
                        closed = True
                        i += 1
                        break
                    i += 1
                if not closed:
                    raise fail(f"unterminated .subckt {name!r}")
            segs.append(("block", name, body))
            continue
        if low.startswith(".param"):
            body = [line]
            i += 1
            while i < n and lines[i].startswith("+"):
                body.append(lines[i])
                i += 1
            segs.append(("param", "", body))
            continue
        segs.append(("other", "", [line]))
        i += 1
    return segs


# --------------------------------------------------------------------------
# Closure resolution
# --------------------------------------------------------------------------

class Closure:
    """Resolved model closure of one (pdk dir, entry, corner section) triple.

    The entry point is loaded with its named `.lib` section selected: only
    directives inside `.lib <section>` ... `.endl` are followed.  Included
    files are loaded whole (a `.lib` region *inside* an included file is a
    named block definition, not a selection, and its body is not loaded --
    matching ngspice `.include` semantics for this library shape).
    Includes resolve relative to the including file's directory and may not
    escape the `<root>/<pdk>/` tree.
    """

    def __init__(self, pdk_dir: Path, entry_rel: str, section: str):
        self.pdk_dir = pdk_dir
        self.entry_rel = entry_rel
        self.section = section
        self.files: dict[str, str] = {}    # relpath (posix) -> file text
        self.digests: dict[str, str] = {}  # relpath -> sha256 of raw bytes
        self._facts: "SideFacts | None" = None
        entry = pdk_dir / entry_rel
        if not entry.is_file():
            raise fail(f"models.lib entry point not found: {entry}")
        self._walk(entry, section, (entry_rel,))

    def _walk(self, path: Path, section: str | None,
              stack: tuple[str, ...]) -> None:
        rel = path.relative_to(self.pdk_dir).as_posix()
        if rel in self.files:
            return
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="replace")
        self.files[rel] = text
        self.digests[rel] = hashlib.sha256(raw).hexdigest()
        here = path.parent
        if section is not None:
            sections = parse_lib_sections(text.splitlines())
            if section not in sections:
                raise fail(
                    f"corner section {section!r} not defined in {rel} "
                    f"(defined sections: {sorted(sections) or 'none'})")
            walk_lines = directive_lines(sections[section])
        else:
            walk_lines = directive_lines(text.splitlines())
        for line in walk_lines:
            m = re.match(r'^\.include\s+"?([^"\s]+)"?$', line, re.IGNORECASE)
            if m:
                self._include(here / m.group(1), None, stack)
                continue
            m = re.match(r"^\.lib\s+(\S+)\s+(\S+)\s*$", line, re.IGNORECASE)
            if m:
                self._include(here / m.group(1), m.group(2), stack)

    def _include(self, target: Path, section: str | None,
                 stack: tuple[str, ...]) -> None:
        target = target.resolve()
        if not self._under(target):
            raise fail(f"include escapes the {self.pdk_dir} tree: {target}")
        rel = target.relative_to(self.pdk_dir).as_posix()
        if rel in stack:
            raise fail("cyclic include: " + " -> ".join(stack + (rel,)))
        if not target.is_file():
            raise fail(f"include target missing: {target} "
                       f"(included from {stack[-1]})")
        self._walk(target, section, stack + (rel,))

    def _under(self, target: Path) -> bool:
        try:
            target.relative_to(self.pdk_dir)
            return True
        except ValueError:
            return False

    def facts(self) -> "SideFacts":
        if self._facts is None:
            self._facts = SideFacts(self)
        return self._facts


# --------------------------------------------------------------------------
# Per-side facts
# --------------------------------------------------------------------------

class SideFacts:
    """Blocks, params and unmatched lines aggregated over a closure."""

    def __init__(self, closure: Closure):
        self.closure = closure
        self.blocks: dict[str, list[str]] = {}   # name -> multiset of contents
        self.params: dict[str, list[str]] = {}   # name -> multiset of exprs
        self.other: Counter = Counter()          # unmatched content lines
        self.content_lines = 0
        for rel, text in closure.files.items():
            for kind, name, body in segment_file(text):
                self.content_lines += len(body)
                if kind == "block":
                    self.blocks.setdefault(name, []).append("\n".join(body))
                elif kind == "param":
                    joined = " ".join(
                        strip_comment_tails(l).strip().lstrip("+").strip()
                        for l in body)
                    joined = joined[len(".param"):].strip()
                    for pname, expr in split_assignments(joined):
                        self.params.setdefault(pname, []).append(expr)
                else:
                    self.other.update(body)


def sha256s(multiset: list[str]) -> list[str]:
    return sorted(hashlib.sha256(c.encode()).hexdigest() for c in multiset)


# --------------------------------------------------------------------------
# Deck parsing
# --------------------------------------------------------------------------

MODEL_CARD_LETTERS = "xmqj"


def deck_model_candidates(text: str) -> list[tuple[str, str]]:
    """Model-name candidates from a deck's element cards.

    For X/M/Q/J cards carrying `key=value` parameters, the model reference
    is the last bare (no `=`) token before the first `=`-carrying token; for
    bare cards, the last token (X cards: the subckt name is last by grammar)
    or the positional 6th token (M cards: `M d g s b model`).  Returns
    `(candidate, card)` pairs; used for the deck-model-absent safety check.
    """
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("*", ".", "+")):
            continue
        letter = line[0].lower()
        if letter not in MODEL_CARD_LETTERS:
            continue
        tokens = line.split()
        eq = next((k for k, t in enumerate(tokens[1:], 1) if "=" in t), None)
        if eq is not None:
            bare = [k for k in range(1, eq) if "=" not in tokens[k]]
            if bare:
                out.append((tokens[bare[-1]], line))
        elif len(tokens) >= 2:
            if letter == "m" and len(tokens) >= 6:
                out.append((tokens[5], line))
            elif letter == "x":
                out.append((tokens[-1], line))
    return out


def deck_tokens(text: str) -> set[str]:
    toks: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("*"):
            continue
        toks.update(TOKEN_RE.findall(line))
    return toks


# --------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------

def consumed_param_names(facts_a: SideFacts, facts_b: SideFacts,
                         instantiated: set[str]) -> set[str]:
    """Parameters whose value flows into an instantiated block.

    Seeds with parameter names appearing in any instantiated block's
    content, then propagates **upstream**: when a consumed parameter's
    definition references another name, that name's value flows into the
    block too, so it is consumed as well (iterated to a fixpoint).  Static
    over-approximation in the safe direction -- a name inside a quoted
    non-parameter context still counts, so such a delta fails the check
    rather than passing silently.
    """
    all_params = set(facts_a.params) | set(facts_b.params)

    def referenced_by(pname: str) -> set[str]:
        refs: set[str] = set()
        for expr in facts_a.params.get(pname, []) + facts_b.params.get(pname, []):
            refs |= set(TOKEN_RE.findall(expr))
        return refs & all_params

    consumed: set[str] = set()
    for name in instantiated:
        for body in facts_a.blocks.get(name, []) + facts_b.blocks.get(name, []):
            consumed |= set(TOKEN_RE.findall(body)) & all_params
    frontier = set(consumed)
    while frontier:
        pname = frontier.pop()
        for ref in referenced_by(pname):
            if ref not in consumed:
                consumed.add(ref)
                frontier.add(ref)
    return consumed


def param_consumers(name: str, facts: SideFacts) -> set[str]:
    return {bname for bname, bodies in facts.blocks.items()
            if any(re.search(rf"\b{re.escape(name)}\b", b) for b in bodies)}


def compare_section(closure_a: Closure, closure_b: Closure,
                    instantiated: set[str]) -> dict:
    fa, fb = closure_a.facts(), closure_b.facts()
    paths_a, paths_b = set(closure_a.files), set(closure_b.files)
    shared = sorted(paths_a & paths_b)
    only_a = sorted(paths_a - paths_b)
    only_b = sorted(paths_b - paths_a)
    byte_diff = {p for p in shared if closure_a.files[p] != closure_b.files[p]}

    block_names = set(fa.blocks) | set(fb.blocks)
    block_diff = sorted(
        n for n in block_names
        if sorted(fa.blocks.get(n, [])) != sorted(fb.blocks.get(n, [])))
    param_names = set(fa.params) | set(fb.params)
    param_delta: dict[str, str] = {}
    for n in sorted(param_names):
        if n not in fa.params:
            param_delta[n] = "only-b"
        elif n not in fb.params:
            param_delta[n] = "only-a"
        elif sorted(fa.params[n]) != sorted(fb.params[n]):
            param_delta[n] = "differing-definitions"

    consumed = consumed_param_names(fa, fb, instantiated)
    inside_blocks = sorted(n for n in block_diff if n in instantiated)
    inside_params = sorted(n for n in param_delta if n in consumed)
    other_asym = (fa.other - fb.other) + (fb.other - fa.other)
    unclassified = sorted(other_asym)

    param_report = []
    for n in sorted(param_delta):
        consumers = param_consumers(n, fa) | param_consumers(n, fb)
        param_report.append({
            "name": n,
            "delta_kind": param_delta[n],
            "classification": "inside" if n in consumed else "outside",
            "definitions_a": sorted(fa.params.get(n, []))[:2],
            "definitions_b": sorted(fb.params.get(n, []))[:2],
            "consumer_blocks": sorted(consumers)[:4],
            "consumer_blocks_count": len(consumers),
            "consumed_by_instantiated_models": bool(consumers & instantiated),
        })

    block_report = []
    for n in block_diff:
        block_report.append({
            "name": n,
            "classification": "inside" if n in instantiated else "outside",
            "instantiated": n in instantiated,
            "occurrences_a": len(fa.blocks.get(n, [])),
            "occurrences_b": len(fb.blocks.get(n, [])),
            "block_sha256_a": sha256s(fa.blocks.get(n, [])),
            "block_sha256_b": sha256s(fb.blocks.get(n, [])),
        })

    path_report = []
    for p in sorted(byte_diff | set(only_a) | set(only_b)):
        def cl(text):
            return Counter(l for l in (content_line(x)
                                       for x in text.splitlines())
                           if l is not None)
        lines_a, lines_b = cl(closure_a.files.get(p, "")), cl(closure_b.files.get(p, ""))
        kind = ("byte-differing" if p in byte_diff
                else "only-a" if p in only_a else "only-b")
        path_report.append({
            "path": p,
            "kind": kind,
            "sha256_a": closure_a.digests.get(p),
            "sha256_b": closure_b.digests.get(p),
            "asymmetric_lines_a": sum((lines_a - lines_b).values()),
            "asymmetric_lines_b": sum((lines_b - lines_a).values()),
        })

    inside_any = bool(inside_blocks or inside_params or unclassified)
    return {
        "closure_files_a": len(paths_a),
        "closure_files_b": len(paths_b),
        "paths_only_a": only_a,
        "paths_only_b": only_b,
        "path_differences": path_report,
        "byte_differing_shared_path_count": len(byte_diff),
        "block_count_a": sum(len(v) for v in fa.blocks.values()),
        "block_count_b": sum(len(v) for v in fb.blocks.values()),
        "block_name_count_a": len(fa.blocks),
        "block_name_count_b": len(fb.blocks),
        "block_name_sets_identical": set(fa.blocks) == set(fb.blocks),
        "block_multiset_differing_names": block_report,
        "param_name_count_a": len(fa.params),
        "param_name_count_b": len(fb.params),
        "param_deltas": param_report,
        "other_lines_a": sum(fa.other.values()),
        "other_lines_b": sum(fb.other.values()),
        "other_lines_asymmetric_distinct": len(unclassified),
        "other_lines_asymmetric_total": sum(other_asym.values()),
        "other_lines_asymmetric_sample": unclassified[:MAX_LIST],
        "instantiated_models_content_identical":
            sorted(n for n in instantiated
                   if sorted(fa.blocks.get(n, [])) == sorted(fb.blocks.get(n, []))),
        "inside_deltas": {
            "blocks": inside_blocks,
            "params": inside_params,
            "unclassified_content_lines": unclassified[:MAX_LIST],
            "unclassified_content_lines_count": len(unclassified),
        },
        "verdict": ("delta-inside-instantiated-set" if inside_any
                    else "all-deltas-outside-instantiated-set"),
    }


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------

def open_pdks_revision(pdk_dir: Path) -> str | None:
    sources = pdk_dir / "SOURCES"
    if not sources.is_file():
        return None
    m = re.search(r"^open_pdks\s+([0-9a-f]{7,40})\s*$",
                  sources.read_text(errors="replace"), re.MULTILINE)
    return m.group(1) if m else None


def klt_version(override: str | None) -> str | None:
    if override:
        return override
    try:
        out = subprocess.run(["klt", "--version"], capture_output=True,
                             text=True, timeout=30)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def load_requests(paths: list[str]) -> list[dict]:
    requests = []
    for p in paths:
        path = Path(p)
        if not path.is_file():
            raise fail(f"request file not found: {path}")
        try:
            req = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            raise fail(f"request {path} is not valid JSON: {e}")
        try:
            pdk = req["models"]["pdk"]
            lib = req["models"]["lib"]
            process = req["corners"]["process"]
            netlist = req["netlist"]
        except (KeyError, TypeError) as e:
            raise fail(f"request {path} lacks required field: {e}")
        deck = (path.parent / netlist).resolve()
        if not deck.is_file():
            raise fail(f"request {path} netlist not found: {deck}")
        requests.append({
            "path": p,
            "pdk": pdk,
            "lib": lib,
            "sections": sorted(set(process)),
            "deck": deck,
        })
    return requests


def rel_if_under_cwd(path: Path) -> str:
    """Repo-relative form when the path is under the CWD, else absolute."""
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return str(path)


def build_record(args: argparse.Namespace) -> tuple[dict, int]:
    requests = load_requests(args.request)
    entries = sorted({(r["pdk"], r["lib"]) for r in requests})
    if len(entries) != 1:
        raise fail(f"requests declare multiple (pdk, lib) entry points: "
                   f"{entries}; run one entry-point group per invocation")
    pdk, lib = entries[0]
    sections = sorted({s for r in requests for s in r["sections"]})
    decks = sorted({r["deck"] for r in requests})

    pdk_dir_a = (Path(args.root_a).expanduser() / pdk).resolve()
    pdk_dir_b = (Path(args.root_b).expanduser() / pdk).resolve()
    for tag, d in (("a", pdk_dir_a), ("b", pdk_dir_b)):
        if not (d / lib).is_file():
            raise fail(f"root-{tag}: models.lib entry point not found: "
                       f"{d / lib}")

    deck_texts = {d: d.read_text(errors="replace") for d in decks}

    closures_a = {s: Closure(pdk_dir_a, lib, s) for s in sections}
    closures_b = {s: Closure(pdk_dir_b, lib, s) for s in sections}

    # Safety check: every deck model reference must exist in some closure.
    known_blocks: set[str] = set()
    for c in list(closures_a.values()) + list(closures_b.values()):
        known_blocks |= set(c.facts().blocks)
    absent = []
    for deck, text in deck_texts.items():
        for cand, card in deck_model_candidates(text):
            if cand not in known_blocks:
                absent.append((deck.name, cand, card))
    if absent:
        for name, cand, card in absent[:5]:
            print(f"error: deck {name} references model {cand!r} absent "
                  f"from both closures: {card[:100]}", file=sys.stderr)
        raise fail(f"{len(absent)} deck model reference(s) absent from the "
                   f"closure; cannot certify identity")

    # Instantiated set: closure block names appearing in deck content.
    instantiated: set[str] = set()
    for text in deck_texts.values():
        instantiated |= deck_tokens(text) & known_blocks
    refs: Counter = Counter()
    for text in deck_texts.values():
        for name in instantiated:
            refs[name] += len(re.findall(rf"\b{re.escape(name)}\b", text))

    section_reports = {s: compare_section(closures_a[s], closures_b[s],
                                          instantiated)
                       for s in sections}

    inst_report = []
    for name in sorted(instantiated):
        identical = all(
            sorted(closures_a[s].facts().blocks.get(name, []))
            == sorted(closures_b[s].facts().blocks.get(name, []))
            for s in sections)
        inst_report.append({
            "name": name,
            "deck_references": refs[name],
            "block_sha256_a": sorted({h for s in sections for h in sha256s(
                closures_a[s].facts().blocks.get(name, []))}),
            "block_sha256_b": sorted({h for s in sections for h in sha256s(
                closures_b[s].facts().blocks.get(name, []))}),
            "content_identical": identical,
        })

    any_inside = any(section_reports[s]["verdict"]
                     != "all-deltas-outside-instantiated-set"
                     for s in sections)
    verdict = ("delta-inside-instantiated-set" if any_inside
               else "all-deltas-outside-instantiated-set")
    exit_code = EXIT_INSIDE if any_inside else EXIT_PASS

    record = {
        "schema_version": SCHEMA_VERSION,
        "tool": "sim/pdk-closure-identity/check_closure_identity.py",
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(
            timespec="seconds"),
        "basis": ("content identity of the model set the decks instantiate; "
                  "static file-content comparison, not a simulation"),
        "klt_version": klt_version(args.klt_version),
        "roots": {
            "a": {
                "pdk_root": str(Path(args.root_a).expanduser().resolve()),
                "pdk": pdk,
                "open_pdks_revision": open_pdks_revision(pdk_dir_a),
                "entry_rel": lib,
                "entry_sha256": closures_a[sections[0]].digests[lib],
            },
            "b": {
                "pdk_root": str(Path(args.root_b).expanduser().resolve()),
                "pdk": pdk,
                "open_pdks_revision": open_pdks_revision(pdk_dir_b),
                "entry_rel": lib,
                "entry_sha256": closures_b[sections[0]].digests[lib],
            },
        },
        "requests": [r["path"] for r in requests],
        "decks": [rel_if_under_cwd(d) for d in decks],
        "corner_sections": sections,
        "instantiated_models": inst_report,
        "sections": section_reports,
        "verdict": verdict,
        "exit_code": exit_code,
    }
    return record, exit_code


def print_summary(record: dict) -> None:
    print(f"closure identity: {record['verdict']}")
    for s in record["corner_sections"]:
        r = record["sections"][s]
        print(f"  section {s}: closure files {r['closure_files_a']} vs "
              f"{r['closure_files_b']}; paths only-a {len(r['paths_only_a'])}, "
              f"only-b {len(r['paths_only_b'])}; byte-differing shared "
              f"{r['byte_differing_shared_path_count']}; block-name deltas "
              f"{len(r['block_multiset_differing_names'])}; param deltas "
              f"{len(r['param_deltas'])} (inside "
              f"{len(r['inside_deltas']['params'])}); unclassified content "
              f"line deltas {r['other_lines_asymmetric_distinct']}")
    for m in record["instantiated_models"]:
        print(f"  instantiated {m['name']}: {m['deck_references']} deck refs, "
              f"content_identical={m['content_identical']}")
    if record["exit_code"] != EXIT_PASS:
        for s in record["corner_sections"]:
            d = record["sections"][s]["inside_deltas"]
            for n in d["blocks"]:
                print(f"  INSIDE: section {s}: instantiated block {n!r} "
                      f"differs between revisions")
            for n in d["params"]:
                print(f"  INSIDE: section {s}: parameter {n!r}, consumed by "
                      f"an instantiated model, differs between revisions")
            for l in d["unclassified_content_lines"]:
                print(f"  INSIDE: section {s}: unclassified content line "
                      f"{l[:80]!r} differs between revisions")


def run(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Static PDK model-closure identity checker (issue #338)")
    ap.add_argument("--root-a", required=True,
                    help="PDK_ROOT of tree A (the directory containing <pdk>/)")
    ap.add_argument("--root-b", required=True,
                    help="PDK_ROOT of tree B")
    ap.add_argument("--request", action="extend", nargs="+", required=True,
                    metavar="JSON", help="klt request JSON (repeatable)")
    ap.add_argument("--out", metavar="PATH",
                    help="write the JSON evidence record to this path")
    ap.add_argument("--klt-version", default=None,
                    help="stamp this klt version instead of auto-detecting")
    args = ap.parse_args(argv)
    record, exit_code = build_record(args)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(record, indent=2) + "\n")
    print_summary(record)
    return exit_code


def main() -> int:
    try:
        return run()
    except CheckError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
