#!/usr/bin/env python3
"""Pure helpers for the RTL-strobe replay experiment (issue #128). Stdlib only.

* trace model: ``{"initial": {sig: 0|1}, "edges": [{"t_ns", "signal", "value"}, ...]}``
* PIN_MAP: the explicit logical-strobe -> SPICE-source mapping (polarity, levels, role)
* edges_to_pwl(): deterministic edge -> PWL conversion (no implicit stretching or holding)
* latch_hold_adapter(): the EXPLICIT adapter that stretches the digital sample pulse into an
  analog latch-enable window (its own recorded waveform; never done inside the converter)
* pwl_to_edges() + check_trace_consistency(): reverse-parse a generated deck source / compare edge
  lists so omitted, reordered or shifted control edges are caught
* mutations (negative controls): drop or shorten the write-back strobes

Conventions (ASSUMPTIONS, declared): one cycle = 1 ns; an edge at time T starts a TEDGE (0.1 ns) linear
ramp at T (same convention as sim/refresh-op, so the baseline is matched); edges at exactly t = 0 set the
initial PWL value (no ramp).
"""
from __future__ import annotations

import re

T_EDGE_NS = 0.1
VDD_V = 1.8
SIGNALS = ["pre_en", "rwl_sel", "sense_en", "wwl_en", "bl_drive", "busy", "done"]
TIME_TOL_NS = 1e-6

# logical strobe -> deck source. role text is documentation; `invert` is the pin polarity.
# bl_drive/wbc: the existing circuit has no separate column driver (that is #114/#117); the only
# write-bitline drive is the latch complement node `ref` connected to WBL through the 100 ohm switch,
# so bl_drive closes that switch. rwl is active-LOW at the pin (read select pulls the source to 0 V).
PIN_MAP = {
    "pre_en":   dict(node="ctl",  invert=False, role="precharge switch control (closed = high)"),
    "rwl_sel":  dict(node="rwls", invert=True,  role="read wordline source, selected row; asserted = 0 V (active-low at the pin)"),
    "sense_en": dict(node="en",   invert=False, role="latch enable (n-footer); enb is its exact complement"),
    "wwl_en":   dict(node="wwl",  invert=False, role="write wordline, selected row (active-high)"),
    "bl_drive": dict(node="wbc",  invert=False, role="WBL connect switch control: latch complement node ref -> WBL (closed = high)"),
}
ADAPTER_NODE = "en"      # the node the latch-hold adapter replaces
COMPLEMENT = {"en": "enb"}


def edge(t: float, sig: str, val: int) -> dict:
    return dict(t_ns=round(float(t), 6), signal=sig, value=int(val))


def sorted_edges(edges: list[dict]) -> list[dict]:
    order = {s: i for i, s in enumerate(SIGNALS)}
    return sorted(edges, key=lambda e: (e["t_ns"], order.get(e["signal"], 99), e["value"]))


def parse_vvp_output(text: str) -> dict:
    meta, init, edges, glitches, end = {}, {}, [], None, None
    for ln in text.splitlines():
        f = ln.split()
        if not f:
            continue
        if f[0] == "TRACE_META":
            meta[f[1]] = int(f[2])
        elif f[0] == "TRACE_INIT":
            init[f[1]] = int(f[2])
        elif f[0] == "TRACE_EDGE":
            edges.append(edge(float(f[1]), f[2], int(f[3])))
        elif f[0] == "TRACE_GLITCHES":
            glitches = int(f[1])
        elif f[0] == "TRACE_END":
            end = float(f[1])
    if not edges or end is None:
        raise ValueError("no TRACE_EDGE / TRACE_END lines in simulator output")
    return dict(initial=init, edges=sorted_edges(edges), meta=meta, delta_glitches_not_exported=glitches, end_ns=end)


def trace_signal_edges(trace: dict, sig: str) -> list[tuple[float, int]]:
    return [(e["t_ns"], e["value"]) for e in sorted_edges(trace["edges"]) if e["signal"] == sig]


def level(sig_node: str, val: int, invert: bool) -> str:
    on = (not val) if invert else bool(val)
    return "{VDD}" if on else "0"


def edges_to_pwl(init: int, edges: list[tuple[float, int]], invert: bool) -> list[tuple[float, str]]:
    """Deterministic edge list -> PWL points ``[(t_ns, level), ...]`` (levels are '0' or '{VDD}').

    Value at t=0 is the value after all edges at t<=0. Each later edge at T adds (T, old) and
    (T+TEDGE, new). Edges closer than TEDGE, a repeated value, or a negative time raise ValueError.
    """
    val = init
    pts: list[tuple[float, str]] = []
    later = []
    for t, v in edges:
        if t < -TIME_TOL_NS:
            raise ValueError(f"negative edge time {t}")
        if t <= TIME_TOL_NS:
            val = v
        else:
            later.append((t, v))
    pts.append((0.0, level("", val, invert)))
    last_t = 0.0
    for t, v in later:
        if v == val:
            raise ValueError(f"edge at {t} ns repeats value {v}")
        if t < last_t + T_EDGE_NS - TIME_TOL_NS:
            raise ValueError(f"edge at {t} ns closer than TEDGE to previous point {last_t}")
        pts.append((t, level("", val, invert)))
        pts.append((round(t + T_EDGE_NS, 6), level("", v, invert)))
        last_t = round(t + T_EDGE_NS, 6)
        val = v
    return pts


def absorb_t0(init: int, edges: list[tuple[float, int]]) -> tuple[int, list[tuple[float, int]]]:
    """Apply the converter's t = 0 convention to a logical waveform: edges at t<=0 set the initial value."""
    val, rest = init, []
    for t, v in edges:
        if t <= TIME_TOL_NS:
            val = v
        else:
            rest.append((t, v))
    return val, rest


def pwl_text(pts: list[tuple[float, str]]) -> str:
    return "pwl(" + " ".join(f"{t * 1e-9:.4e} {lv}" for t, lv in pts) + ")"


def complement_pts(pts: list[tuple[float, str]]) -> list[tuple[float, str]]:
    return [(t, "0" if lv == "{VDD}" else "{VDD}") for t, lv in pts]


def pwl_to_edges(text: str, invert: bool) -> tuple[int, list[tuple[float, int]]]:
    """Reverse of edges_to_pwl for a deck ``pwl(...)`` string -> (initial logical value, edges)."""
    m = re.search(r"pwl\((.*)\)", text)
    if not m:
        raise ValueError("no pwl() in source")
    tok = m.group(1).split()
    if len(tok) % 2:
        raise ValueError("odd pwl token count")
    pts = [(float(tok[i]) * 1e9, 1 if tok[i + 1] == "{VDD}" else 0 if tok[i + 1] == "0" else None) for i in range(0, len(tok), 2)]
    if any(p[1] is None for p in pts):
        raise ValueError("pwl level is neither 0 nor {VDD}")
    logical = [(t, (1 - v) if invert else v) for t, v in pts]
    init = logical[0][1]
    out = []
    i = 1
    while i < len(logical):
        # a transition is (T, old) then (T+TEDGE, new)
        t0, v0 = logical[i]
        if i + 1 >= len(logical) or abs(logical[i + 1][0] - t0 - T_EDGE_NS) > 1e-4 or logical[i + 1][1] == v0:
            raise ValueError(f"malformed ramp at {t0} ns")
        out.append((round(t0, 6), logical[i + 1][1]))
        i += 2
    return init, out


def latch_hold_adapter(trace: dict, release_ns: float | None = None) -> dict:
    """EXPLICIT adapter: latch enable = set at the sense_en rising edge, held until busy falls.

    Recorded as its own waveform (``latch_en_held``). The digital sample pulse is 1 cycle; the analog
    sequence of sim/refresh-op holds the enable until after WWL falls (+ guard). Holding to the falling
    edge of ``busy`` is the only choice that does not depend on the write strobes, so the negative
    controls keep a defined release. Adds no delay (0 ns launch/adapter latency, ASSUMPTION).
    """
    rises = [t for t, v in trace_signal_edges(trace, "sense_en") if v == 1]
    busy_fall = [t for t, v in trace_signal_edges(trace, "busy") if v == 0]
    if not rises or not busy_fall:
        raise ValueError("trace lacks sense_en rise or busy fall; cannot apply the latch-hold adapter")
    rel = busy_fall[-1] if release_ns is None else release_ns   # release_ns: experimental #131 override only
    return dict(initial=0, edges=[(rises[0], 1), (rel, 0)])


def retime_edge(trace: dict, signal: str, value: int, new_t_ns: float) -> dict:
    """Experiment helper (#131): move exactly ONE edge (the single ``signal`` edge to ``value``) to ``new_t_ns``.

    Raises unless that edge is unique, so a retiming can never silently touch another edge. All other
    edges, initial levels and signals are copied unchanged.
    """
    hits = [i for i, e in enumerate(trace["edges"]) if e["signal"] == signal and e["value"] == value]
    if len(hits) != 1:
        raise ValueError(f"expected exactly one {signal}->{value} edge, found {len(hits)}")
    edges = [dict(e) for e in trace["edges"]]
    edges[hits[0]]["t_ns"] = round(new_t_ns, 6)
    return dict(trace, edges=sorted_edges(edges))


def diff_node_waveforms(a: dict, b: dict) -> list[dict]:
    """Per-node edge/initial differences between two ``node -> (init, edges, invert)`` maps (b relative to a).
    Used to prove an experiment changed only its intended release edge(s)."""
    out = []
    for node in sorted(set(a) | set(b)):
        if node not in a or node not in b:
            out.append(dict(node=node, kind="node_missing"))
            continue
        (ia, ea, va), (ib, eb, vb) = a[node], b[node]
        if va != vb or ia != ib:
            out.append(dict(node=node, kind="initial_or_polarity"))
        for i in range(max(len(ea), len(eb))):
            x = ea[i] if i < len(ea) else None
            y = eb[i] if i < len(eb) else None
            if x is None or y is None or x[1] != y[1]:
                out.append(dict(node=node, kind="edge_added_removed_or_value", index=i, a=x, b=y))
            elif abs(x[0] - y[0]) > TIME_TOL_NS:
                out.append(dict(node=node, kind="shifted", index=i, from_ns=x[0], to_ns=y[0], value=x[1]))
    return out


def mutate_trace(trace: dict, kind: str) -> dict:
    """Negative-control mutations of an RTL trace (never applied to the golden trace)."""
    edges = [dict(e) for e in trace["edges"]]
    if kind == "missing_wb":
        edges = [e for e in edges if e["signal"] not in ("wwl_en", "bl_drive")]
    elif kind == "short_wb":   # WWL and BL drive collapse to a 0.2 ns pulse, same start
        for sig in ("wwl_en", "bl_drive"):
            rise = [e for e in edges if e["signal"] == sig and e["value"] == 1]
            fall = [e for e in edges if e["signal"] == sig and e["value"] == 0]
            if rise and fall:
                fall[0]["t_ns"] = round(rise[0]["t_ns"] + 0.2, 6)
    elif kind == "shift_wwl":  # shifted control edge (used by the consistency-check tests)
        for e in edges:
            if e["signal"] == "wwl_en":
                e["t_ns"] = round(e["t_ns"] + 1.0, 6)
    elif kind == "reorder":    # WWL rises before RWL falls
        for e in edges:
            if e["signal"] == "wwl_en" and e["value"] == 1:
                e["t_ns"] = round(e["t_ns"] - 1.0, 6)
    else:
        raise ValueError(kind)
    return dict(trace, edges=sorted_edges(edges))


def check_trace_consistency(golden: dict, other: dict, signals: list[str] | None = None) -> list[dict]:
    """Compare two traces; return findings (empty = identical). Kinds: omitted, extra, shifted,
    value_mismatch, reordered, initial_mismatch."""
    sigs = signals or SIGNALS
    out = []
    for s in sigs:
        if golden["initial"].get(s, 0) != other["initial"].get(s, 0):
            out.append(dict(kind="initial_mismatch", signal=s))
        g, o = trace_signal_edges(golden, s), trace_signal_edges(other, s)
        for i in range(max(len(g), len(o))):
            if i >= len(o):
                out.append(dict(kind="omitted", signal=s, index=i, expected=g[i]))
            elif i >= len(g):
                out.append(dict(kind="extra", signal=s, index=i, got=o[i]))
            elif g[i][1] != o[i][1]:
                out.append(dict(kind="value_mismatch", signal=s, index=i, expected=g[i], got=o[i]))
            elif abs(g[i][0] - o[i][0]) > TIME_TOL_NS:
                out.append(dict(kind="shifted", signal=s, index=i, expected=g[i], got=o[i], delta_ns=round(o[i][0] - g[i][0], 6)))
    gseq = [(e["signal"], e["value"]) for e in sorted_edges([e for e in golden["edges"] if e["signal"] in sigs])]
    oseq = [(e["signal"], e["value"]) for e in sorted_edges([e for e in other["edges"] if e["signal"] in sigs])]
    if gseq != oseq and sorted(gseq) == sorted(oseq):
        out.append(dict(kind="reordered", detail="same edges, different cross-signal order"))
    return out


def trace_from_edges(initial: dict, edges: list[dict]) -> dict:
    return dict(initial=dict(initial), edges=sorted_edges(edges))


def digital_duration(trace: dict) -> dict:
    """Operation timing from the trace (t = 0 is the accepting clock edge)."""
    busy_rise = [t for t, v in trace_signal_edges(trace, "busy") if v == 1]
    busy_fall = [t for t, v in trace_signal_edges(trace, "busy") if v == 0]
    done_rise = [t for t, v in trace_signal_edges(trace, "done") if v == 1]
    return dict(busy_rise_ns=busy_rise[0] if busy_rise else None, busy_fall_ns=busy_fall[-1] if busy_fall else None,
                done_rise_ns=done_rise[0] if done_rise else None)

