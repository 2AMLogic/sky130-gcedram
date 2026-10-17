#!/usr/bin/env python3
"""Generate the geometry-matched access-leakage deck and `klt sim` request (issue #149).

Stdlib only. Reads the COMMITTED extraction
``layout/gain_cell_2t_array.extract.parasitics.json`` and derives the access
device geometry (W, L, AD, AS, PD, PS) from it -- nothing is hand-typed. Writes,
into ``sim/leakage/geometry-matched/``:

* ``access_leakage_geom.spice``  circuit body for ``klt sim`` (no .control/.end,
  no .lib/.temp: klt appends them per corner). Two independent DUTs per corner:
    - ``xext``  the access device with the EXTRACTED drawn diffusion
                (ad/as/pd/ps from the extraction);
    - ``xleg``  a same-batch CONTROL with the legacy testbench card
                (l=0.15 w=0.42, no diffusion parameters), so geometry is isolated
                from engine/PDK-version confounds.
  Bias is identical to ``sim/leakage/tb_access_leakage.spice.tmpl``: drain (storage
  node) 1.8 V, gate = source = body = 0 V; observable ``abs(i(vsn))``.
* ``request.json``  one ``klt sim`` corner request, backend ``batch``, analysis
  ``op``, 5 process corners x {-40, 27, 125} C = 15 points.

The original template and CSV are untouched historical baselines.

Units: the PDK wrapper ``sky130_fd_pr__nfet_01v8`` is used with numeric
micrometre values because the shipped model library sets ``.option scale=1.0u``
(``libs.tech/combined/continuous/models_global.spice``): l/w/pd/ps are um, ad/as are
um^2. The extraction JSON field names carry the units explicitly (``*_um``,
``*_um2``) and are used as-is; they are NOT rescaled here.

Re-run after editing; ``test_geometry_leakage.py`` fails if committed files are stale.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))
from _evidence_common import sha256_prefixed as sha256_file  # noqa: E402
OUT = HERE / "geometry-matched"
DECK_PATH = OUT / "access_leakage_geom.spice"
REQUEST_PATH = OUT / "request.json"
EXTRACTION_PATH = REPO / "layout" / "gain_cell_2t_array.extract.parasitics.json"

DEVICE = "sky130_fd_pr__nfet_01v8"
VDD_V = 1.8
PROCESS_CORNERS = ["tt", "ss", "ff", "sf", "fs"]
TEMPS_C = [-40, 27, 125]
LEGACY_W_UM = 0.42   # legacy testbench card (sim/leakage/run_leakage_sweep.py)
LEGACY_L_UM = 0.15
MEAS_EXT = "ileak_ext_a"
MEAS_LEG = "ileak_leg_a"

WL_RE = re.compile(r"^wl(_\d+)?$")
BL_RE = re.compile(r"^bl(_\d+)?$")
SN_RE = re.compile(r"^sn(_\d+)*$")
PARAM_KEYS = ("l_um", "w_um", "ad_um2", "as_um2", "pd_um", "ps_um")


class GeometryError(ValueError):
    pass


def select_access_devices(extraction: dict) -> list[dict]:
    """Devices whose gate is a wordline, source a bitline and drain a storage node.

    Selected by terminal connectivity, never by order or class alone: the read
    devices (gate on the storage node) are excluded by construction.
    """
    devs = extraction.get("devices")
    if not isinstance(devs, list) or not devs:
        raise GeometryError("extraction has no 'devices' list")
    out = []
    for d in devs:
        nets = d.get("nets") or {}
        if d.get("class") != "nfet":
            continue
        if (WL_RE.match(str(nets.get("g", ""))) and BL_RE.match(str(nets.get("s", "")))
                and SN_RE.match(str(nets.get("d", "")))):
            out.append(d)
    if not out:
        raise GeometryError("no access device (gate=wl*, source=bl*, drain=sn*) found in extraction")
    return out


def geometry_from_devices(devices: list[dict]) -> dict:
    """Validate and return the single shared parameter set (um / um^2)."""
    seen: dict[tuple, str] = {}
    for d in devices:
        p = d.get("params")
        if not isinstance(p, dict):
            raise GeometryError(f"device {d.get('name')!r}: missing 'params'")
        vals = []
        for k in PARAM_KEYS:
            if k not in p:
                raise GeometryError(f"device {d.get('name')!r}: missing parameter {k!r}")
            v = p[k]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")) or v < 0:
                raise GeometryError(f"device {d.get('name')!r}: invalid {k}={v!r} (need finite non-negative number)")
            vals.append(float(v))
        if vals[0] <= 0 or vals[1] <= 0:
            raise GeometryError(f"device {d.get('name')!r}: l_um/w_um must be > 0")
        seen.setdefault(tuple(vals), d.get("name"))
    if len(seen) != 1:
        raise GeometryError(
            f"heterogeneous access-device geometry ({len(seen)} distinct parameter sets); "
            "the single-DUT study needs exactly one: " + "; ".join(f"{dict(zip(PARAM_KEYS, k))} first on {n}" for k, n in seen.items()))
    (vals,) = seen.keys()
    return dict(zip(PARAM_KEYS, vals))


def load_geometry(path: Path = EXTRACTION_PATH) -> dict:
    ex = json.loads(Path(path).read_text())
    devs = select_access_devices(ex)
    g = geometry_from_devices(devs)
    return {
        "geometry": g,
        "input_path": str(Path(path).resolve().relative_to(REPO)) if Path(path).resolve().is_relative_to(REPO) else str(path),
        "input_sha256": sha256_file(path),
        "device_names": sorted(d["name"] for d in devs),
        "device_count_total": ex.get("device_count"),
    }


def fmt(x: float) -> str:
    return repr(float(x))


def render_deck(g: dict) -> str:
    return f"""* access_leakage_geom.spice -- geometry-matched access-device off-state leakage (issue #149).
* GENERATED by gen_geometry_leakage.py from layout/gain_cell_2t_array.extract.parasitics.json; do not edit.
*
* CIRCUIT BODY for `klt sim`: no .control/.end; the PDK .lib/.temp cards are appended per corner by klt.
* Bias is identical to sim/leakage/tb_access_leakage.spice.tmpl: drain (storage node) = VDD,
* gate = source = body = 0 V; observable abs(i(vsn_*)) (via a B source). Two independent DUTs per corner:
*   xext : extracted drawn diffusion (ad/as/pd/ps from the extraction, um / um^2 via .option scale=1u)
*   xleg : same-batch CONTROL with the legacy testbench card (no ad/as/pd/ps -> wrapper default 0)
.param VDD = {VDD_V}
vsn_ext sn_ext 0 dc {{VDD}}
xext sn_ext 0 0 0 {DEVICE} l={fmt(g['l_um'])} w={fmt(g['w_um'])} ad={fmt(g['ad_um2'])} as={fmt(g['as_um2'])} pd={fmt(g['pd_um'])} ps={fmt(g['ps_um'])}
vsn_leg sn_leg 0 dc {{VDD}}
xleg sn_leg 0 0 0 {DEVICE} l={fmt(LEGACY_L_UM)} w={fmt(LEGACY_W_UM)}
* |I(vsn_*)| as a node voltage (1 V per A) so a .meas card can read it; the dc sweep only
* steps vsn_ext (1.8 -> 1.9 V); both observations are taken AT=1.8 V, the specified bias.
biabs_ext iabs_ext 0 v=abs(i(vsn_ext))
biabs_leg iabs_leg 0 v=abs(i(vsn_leg))
"""


def build_request() -> dict:
    return {
        "netlist": DECK_PATH.name,
        "engine": "ngspice",
        "backend": "batch",
        "models": {"pdk": "sky130A", "lib": "libs.tech/combined/sky130.lib.spice"},
        "corners": {"process": list(PROCESS_CORNERS), "temperature_c": list(TEMPS_C)},
        # A one-point DC sweep at the storage-node bias (VDD) is used instead of ``op`` +
        # ``measurements[].expr``: the fleet runner image (klt 0.5.0) and the older clients
        # compatible with it only accept ``.meas`` cards (see README, first batch attempt).
        "analysis": {"kind": "dc", "args": "vsn_ext 1.8 1.9 0.1"},
        "measurements": [
            {"name": MEAS_EXT, "unit": "A", "spice": f".meas dc {MEAS_EXT} FIND v(iabs_ext) AT=1.8"},
            {"name": MEAS_LEG, "unit": "A", "spice": f".meas dc {MEAS_LEG} FIND v(iabs_leg) AT=1.8"},
        ],
        "options": {"timeout_s": 600, "keep_artifacts": False, "waveforms": False,
                    "ngspice_init": ["set measureprec=12", "set numdgt=12"]},
    }


def render_request() -> str:
    return json.dumps(build_request(), indent=2) + "\n"


def main() -> int:
    info = load_geometry()
    OUT.mkdir(exist_ok=True)
    DECK_PATH.write_text(render_deck(info["geometry"]))
    REQUEST_PATH.write_text(render_request())
    print(f"wrote {DECK_PATH} and {REQUEST_PATH}; geometry {info['geometry']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
