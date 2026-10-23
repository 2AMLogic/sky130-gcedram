"""Shared `klt sim` request skeleton for the sim/*/gen_*.py generators.

Every generator emits the same engine / backend / PDK-models / options
scaffold around its own netlist, corners, analysis and measurements. Keeping
one copy here means a change to the backend, the PDK lib path or the
Monte Carlo quantiles lands everywhere at once instead of silently diverging
the committed `request*.json` evidence. Stdlib only.

Key order is the committed request-file order (dict insertion order is what
`json.dumps` serialises), so the output stays byte-identical.
"""

from __future__ import annotations

ENGINE = "ngspice"
BACKEND = "batch"
MODELS = {"pdk": "sky130A", "lib": "libs.tech/combined/sky130.lib.spice"}
MC_QUANTILES = [2.5, 50, 97.5]


def mc_block(n: int, seed: int) -> dict:
    """Mismatch-only Monte Carlo block shared by the MC studies."""
    return {"n": n, "seed": seed, "vary": "mismatch", "quantiles": list(MC_QUANTILES)}


def build_request(netlist: str, corners: dict, analysis_args: str, measurements: list[dict],
                  timeout_s: int, *, kind: str = "tran", exclude: list[dict] | None = None,
                  monte_carlo: dict | None = None, extra_options: dict | None = None) -> dict:
    req = {
        "netlist": netlist,
        "engine": ENGINE,
        "backend": BACKEND,
        "models": dict(MODELS),
        "corners": corners,
    }
    if exclude:
        req["exclude"] = exclude
    if monte_carlo is not None:
        req["monte_carlo"] = monte_carlo
    req["analysis"] = {"kind": kind, "args": analysis_args}
    req["measurements"] = measurements
    req["options"] = {"timeout_s": timeout_s, "keep_artifacts": False, "waveforms": False,
                      **(extra_options or {})}
    return req
