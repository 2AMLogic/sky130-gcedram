#!/usr/bin/env python3
"""The issue-#114 sense-input contract gate, shared by both sim/column-periphery/ analyzers.

Stdlib only, matching the "Stdlib only, no virtualenv required" constraint both
callers document for themselves.

`compliance()` is the four-clause gate that decides whether one recorded corner
satisfies the sense-input contract of `docs/SENSE_INPUT_CONTRACT.md`, for both
data values:

    (a) settle time <= the 2 ns precharge phase of t_row_refresh_op `anchored`
    (b) |V(rbl) - 0.9 V| <= 10 mV when the precharge is released
    (c) the latch decides the correct polarity with |d| >= RESOLVE_V
    (d) within T_WINDOW_S of the enable (sense-stage criterion)

It lives here, next to the thresholds it reads, because BOTH analyzers in this
directory gate on it: `analyze_column_periphery.py` reports it per corner for
the #114 slice, and `analyze_isolation_study.py` feeds it into the #117
`all_compliant` aggregate. It used to be declared twice -- two AST-identical
copies above two line-for-line-identical constant blocks -- of which only the
#114 one had the negative-control suite in `test_column_periphery.py`. A
threshold-edge fix (`<` vs `<=`, a None guard) made against the tested copy
therefore reached the #114 summary and silently did not reach the #117 one.
Consolidating the gate and its thresholds here means such a fix applies to both
analyses at once instead of drifting between two copies, the same reason
`sim/_evidence_common.py` exists for the cross-bench helpers (issues #185, #245,
#283).

Scope: this module holds only what both analyzers share. The isolation study's
sub-ground floor (`FLOOR_V`) stays local to `analyze_isolation_study.py`, since
only that study reports it. `decided()` here is the single column-periphery
binding of `_evidence_common.decided()` to this bench's threshold; per-BENCH
threshold bindings remain deliberately separate (sense-stage and sense-mismatch
each keep their own), which is the judgement #245 recorded.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from _evidence_common import decided as _decided  # noqa: E402
import gen_column_periphery as G  # noqa: E402

SETTLE_BUDGET_S = G.T_PRE_BUDGET_S
RELEASE_TOL_V = G.SETTLE_V
RESOLVE_V = 0.9
T_WINDOW_S = 5e-9
T_PRE_MID_S = G.T_PRE_ON_S + G.T_EDGE_S / 2
T_EN_MID_S = G.T_EN_S + G.T_EDGE_S / 2


def decided(dend: float | None) -> str:
    return _decided(dend, RESOLVE_V)


def compliance(r1: dict, r0: dict) -> dict:
    """The four #114 clauses for one corner's stored-'1' and stored-'0' rows.

    Returns a NEW dict on every call: `analyze_column_periphery.summarize()`
    adds its reported-but-not-gating `min_abs_din_v` to the result in place.
    """
    ok_a = all(x["settle_s"] is not None and x["settle_s"] <= SETTLE_BUDGET_S for x in (r1, r0))
    ok_b = all(x["vrel_v"] is not None and abs(x["vrel_v"] - G.VRBL_V) <= RELEASE_TOL_V for x in (r1, r0))
    ok_c = decided(r1["dend_v"]) == "1" and decided(r0["dend_v"]) == "0"
    ok_d = all(x["tdec_s"] is not None and 0 <= x["tdec_s"] <= T_WINDOW_S for x in (r1, r0))
    return dict(settle_within_budget=ok_a, release_level_within_tol=ok_b,
                correct_decision=ok_c, decision_within_window=ok_d,
                compliant=ok_a and ok_b and ok_c and ok_d)
