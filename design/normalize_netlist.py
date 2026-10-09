#!/usr/bin/env python3
"""Normalize an xschem-emitted SPICE netlist (stdlib only; issue #109).

xschem 3.4.7 evaluates the sky130 symbol's ``expr('...')`` geometry
parameters (ad/as/pd/ps/nrd/nrs) while netlisting; older xschem (e.g. 3.4.4)
emits them verbatim. This evaluates any leftover ``expr('...')`` so the
committed netlist is identical regardless of xschem version, then rewraps
continuation lines with one fixed rule (start a new ``+`` line once the
current line is >= 100 chars). Usage: normalize_netlist.py IN OUT
"""
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


def main(src, dst):
    lines = open(src).read().split("\n")
    logical = []
    for ln in lines:
        if ln.startswith("+") and logical:
            logical[-1] += " " + ln[1:].strip()
        else:
            logical.append(ln)
    out = []
    for ln in logical:
        if "expr('" in ln:
            params = dict(re.findall(r"\b(\w+)=([0-9.eE+\-]+)\b", ln))
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
    open(dst, "w").write("\n".join(out))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
