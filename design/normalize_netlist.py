#!/usr/bin/env python3
"""Normalize an xschem-emitted SPICE netlist (stdlib only; issue #109).

xschem 3.4.7 evaluates the sky130 symbol's ``expr('...')`` geometry
parameters (ad/as/pd/ps/nrd/nrs) while netlisting; older xschem (e.g. 3.4.4)
emits them verbatim. This evaluates any leftover ``expr('...')`` so the
committed netlist is identical regardless of xschem version, then rewraps
every long device card (not only those that held an expr()) with one fixed
rule, so xschem 3.4.4 and 3.4.7 agree byte for byte (start a new ``+`` line once the
current line is >= 100 chars).

Usage:
  normalize_netlist.py IN OUT            write the normalized netlist body
  normalize_netlist.py --check RAW NORM  exit 0 iff the committed NORM equals
                                         normalize(RAW) (issue #229): the
                                         provenance header is skipped, the body
                                         is compared byte for byte, and the
                                         header's schematic sha256 is verified.
                                         Needs no xschem: a pure function of the
                                         committed raw netlist and schematic.
"""
import hashlib
import os
import re
import sys

EXPR = re.compile(r"(\w+)=expr\('([^']*)'\)")
TOKEN = re.compile(r"(?:[^\s']|'[^']*')+")


def _eval(expr, params):
    e = re.sub(r"@(\w+)", lambda m: repr(float(params[m.group(1)])), expr)
    if not re.fullmatch(r"[0-9eE+\-*/(). \tint]*", e):
        raise ValueError(f"unsupported expr: {expr}")
    return eval(e, {"__builtins__": {}}, {"int": int})  # noqa: S307 (charset-checked)


def _fmt(x):
    return f"{x:.14g}"


def normalize_text(text):
    lines = text.split("\n")
    logical = []
    for ln in lines:
        if ln.startswith("+") and logical:
            logical[-1] += " " + ln[1:].strip()
        else:
            logical.append(ln)
    out = []
    for ln in logical:
        if "expr('" in ln or (ln[:1].isalpha() and len(ln) >= 100):
            params = dict(re.findall(r"\b(\w+)=([0-9.eE+\-]+)\b", ln))
            if "expr('" in ln:
                ln = EXPR.sub(lambda m: f"{m.group(1)}={_fmt(_eval(m.group(2), params))}", ln)
            toks = TOKEN.findall(ln)
            cur, rows = toks[0], []
            for t in toks[1:]:
                if len(cur) >= 100:
                    rows.append(cur)
                    cur = "+"
                    cur += " " + t
                else:
                    cur += " " + t
            rows.append(cur)
            out.extend(rows)
        else:
            out.append(ln)
    return "\n".join(out)


def rewrite_paths(text):
    """Repo-relative ``** sch_path:`` / ``** sym_path:`` (as regen_netlist.sh)."""
    return re.sub(r"(?m)^(\*\* s(?:ch|ym)_path: ).*/(design/.*)$", r"\1\2", text)


def main(src, dst):
    with open(src) as f:
        text = f.read()
    with open(dst, "w") as f:
        f.write(normalize_text(text))


SCH_HASH = re.compile(r"^\*\s+(design/\S+\.sch): sha256:([0-9a-f]{64})$", re.M)


def check(raw_path, norm_path):
    """Return a list of problems (empty when NORM is fresh against RAW)."""
    with open(raw_path) as f:
        expected = rewrite_paths(normalize_text(f.read()))
    with open(norm_path) as f:
        committed = f.read()
    # The provenance header is the leading single-star comment block; the body
    # starts at the first line beginning with "**" (xschem's sch_path comment).
    m = re.search(r"(?m)^\*\*", committed)
    if not m:
        return [f"{norm_path}: no netlist body found (no '**' line)"]
    header, body = committed[: m.start()], committed[m.start():]
    problems = []
    if body != expected:
        problems.append(f"{norm_path}: body is stale against normalize({raw_path})")
    hashes = SCH_HASH.findall(header)
    if not hashes:
        problems.append(f"{norm_path}: header has no schematic sha256 provenance line")
    root = os.path.dirname(os.path.dirname(os.path.abspath(norm_path)))
    for rel, digest in hashes:
        with open(os.path.join(root, rel), "rb") as f:
            actual = hashlib.sha256(f.read()).hexdigest()
        if actual != digest:
            problems.append(f"{norm_path}: header sha256 for {rel} is stale (file is {actual})")
    return problems


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--check":
        found = check(sys.argv[2], sys.argv[3])
        for p in found:
            print(f"FAIL: {p}", file=sys.stderr)
        if not found:
            print(f"OK: {sys.argv[3]} is fresh against {sys.argv[2]}")
        sys.exit(1 if found else 0)
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
