#!/usr/bin/env python3
"""Device-inclusive storage-node capacitance of the compact v2 array: deck/request generator + reducer (issue #208).

MEASURED ON THE EXTRACTED NETLIST WITH THE BSIM MODELS IN THE LOOP -- NOT A SPEC CHANGE, NOT A RATIFIED
VALUE, NOT A RULING ON THE RETENTION BUDGET (that stays with the operator). Closes the measurement half of
``spec/retention-refresh-budget.md`` Section 9.6 item 2 for the compact v2 layout of issue #100.

Method (hold-droop slope, charge based). One flat deck holds independent copies of the committed extracted
4x4 v2 array (``layout/compact/gain_cell_2t_v2_array.extract.parasitics.spice``: 32 devices with their drawn
AD/AS/PD/PS, lumped per-net R, ground C and net-to-net coupling C), generic ``nfet`` -> ``sky130_fd_pr__nfet_01v8``.
In each copy ONE storage node is probed: a known constant current ``I_TEST`` is drawn out of its hub node and the
times at which it crosses 1.0, 0.9 ... 0.1 V are measured, so

    C_eff = I_TEST * (t(0.1 V) - t(1.0 V)) / 0.9 V      (and per 0.1 V step: the differential C(V) curve)

which is exactly the charge the node loses per volt over the ratified delta_V = VDD/2 window starting at the
assumed stored '1' (1.0 V, as in ``sim/write-disturb``). Every other node is an ideal source (quiet neighbours,
the same convention as the wiring-only ``total_ff = ground + all coupling``). Because the droop is large-signal,
nonlinear device capacitances (read-gate channel, junctions) are averaged over the window the retention
derivation actually uses, not linearised at one bias. ``I_TEST`` is 3-4 decades above the ~1e-10 A leakage
(<= 0.22 % error, in the conservative direction: the measured C is slightly low).

Double counting (Section 9.6 item 2, second route). The extractor's wiring ground C of the storage node includes
a ``poly`` term; whether it overlaps the read-gate channel (already carried by the BSIM device) is unchecked.
Two decks bracket it WITHOUT having to decide: variant ``a`` keeps the extracted wiring C as is (devices added on
top: UPPER end, may count the channel poly twice), variant ``p`` removes the node's ENTIRE extracted poly ground
term before adding the devices (LOWER end, removes more than any overlap can be). The device-inclusive C_SN lies
between them. Variant ``b`` repeats ``a`` with the read-device terminals grounded (channel formed whenever the
node is above Vt): the bias sensitivity of the read-gate term, a bounding case, not the idle bias.

Controls in the same batch: ``ctl`` is an ideal 1 fF capacitor measured with the same stimulus and reducer
(must read 1 fF); ``rate`` repeats the limiting node of ``a`` at 1/5 the current (C must not depend on rate).

``gen`` writes the deck and ONE ``klt sim`` corner request (5 process x 3 temperature = the 15 PVT points,
``backend: batch``). ``reduce REPORT`` turns a committed ``results/klt_report_<RUN_ID>.json`` into a NEW
``results/compact_device_c_sn_<RUN_ID>.json`` (refuses to overwrite: append-only evidence). ``--check FILE``
recomputes a committed result from its committed inputs.

Usage (repo root; stdlib only):

    python3 -I sim/retention/compact_device_c_sn.py gen
    klt sim sim/retention/compact-device-c-sn/request.json -o ... --report-out sim/retention/results/klt_report_<RUN_ID>.json
    python3 -I sim/retention/compact_device_c_sn.py reduce sim/retention/results/klt_report_<RUN_ID>.json
    python3 -I sim/retention/compact_device_c_sn.py --check-generated
    python3 -I sim/retention/compact_device_c_sn.py --check sim/retention/results/compact_device_c_sn_<RUN_ID>.json
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "leakage"))
sys.path.insert(0, str(REPO / "layout"))
import analyze_geometry_leakage as AN  # noqa: E402
import compact_parasitics as CP  # noqa: E402
from _evidence_common import sha256_prefixed  # noqa: E402
from klt_request import build_request as klt_request  # noqa: E402

OUT = HERE / "compact-device-c-sn"
DECK_PATH = OUT / "compact_device_c_sn.spice"
REQUEST_PATH = OUT / "request.json"
RESULTS = HERE / "results"
V2_NETLIST = REPO / "layout" / "compact" / "gain_cell_2t_v2_array.extract.parasitics.spice"
V2_EXTRACT = REPO / "layout" / "compact" / "gain_cell_2t_v2_array.extract.parasitics.json"
LEAKAGE_POINTS = REPO / "sim" / "leakage" / "compact-geometry" / "results" / "compact_leakage_points_20261020T1716Z.csv"
WIRING_BASELINE = RESULTS / "compact_c_sn_20261020T172043Z.json"
RESULT_PREFIX = "compact_device_c_sn_"
SCHEMA = "gcedram.compact_device_c_sn/1"
LABEL = ("DEVICE-INCLUSIVE C_SN of the compact v2 array measured on the extracted netlist with the BSIM models in "
         "the loop (hold-droop slope over the ratified delta_V window), quiet neighbours, ideal drivers, global "
         "corners only. Retention time uses the existing delta_V = VDD/2 ASSUMPTION and the geometry-matched "
         "compact v2 leakage. Not a spec change, not ratified, not a ruling on the retention budget.")

# ---- scope: the 15 PVT points of the committed leakage studies ----
PROCESS_CORNERS = ["tt", "ss", "ff", "sf", "fs"]
TEMPS_C = [-40, 27, 125]
WORST_CASE = ("sf", 125)
VDD_V = 1.8
VRBL_V = 0.9                   # idle read bitline (as sim/write-disturb)
V_START_V = 1.1                # initial node level: the ramp-in finishes above the first crossing
LEVELS_V = [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1]   # 1.0 V = assumed stored '1'; window = delta_V 0.9 V
DELTA_V_V = LEVELS_V[0] - LEVELS_V[-1]
V_NEIGHBOUR_V = 1.0            # quiet neighbour storage nodes held at the stored '1' level (ASSUMPTION)
I_TEST_A = 50e-9
I_RATE_A = 10e-9
T_RAMP_S = 1e-9                # current switches on at 1 ns over 0.2 ns
V_GATE_V, V_GATE_W_V = 0.05, 0.01   # tanh gate: the current switches itself off below 0.05 V (no forward-biased junction)
C_KNOWN_F = 1e-15
CTL_TOL = 0.005                # ideal-capacitor control must read within 0.5 %
RATE_TOL = 0.01                # 5x lower current must agree within 1 %
T_STOP_S = 300e-9
SIM_OPTIONS = "gmin=1e-15 abstol=1e-15 chgtol=1e-18 reltol=1e-4"
VARIANTS = ("a", "p", "b")


class DeviceCError(ValueError):
    pass


def _f(x: float) -> str:
    return f"{x:.6g}"


def short(net: str) -> str:
    """SPICE-safe lower-case node name: ``\\$20__t0`` -> ``n20__t0``."""
    return net.lstrip("\\").replace("$", "n").lower()


def nn(net: str, inst: str) -> str:
    return "0" if net in ("GND", "vsubs", "0") else f"{short(net)}_{inst}"


def hub_of(net: str) -> str:
    return net.split("__t")[0]


def storage(extraction: dict) -> dict:
    """{net: poly ground C (fF)} for every storage node, found from device connectivity."""
    entries = CP.sn_entries(extraction)
    return {n: float(e["by_layer_ground_ff"].get("poly", 0.0)) for n, e in entries.items()}


def limiting_node(extraction: dict) -> str:
    entries = CP.sn_entries(extraction)
    return min(entries, key=lambda n: (entries[n]["total_ff"], n))


def instances(nodes: list[str], limiting: str) -> list[dict]:
    out = [{"id": f"{v}_{short(n)}", "variant": v, "node": n, "i_a": I_TEST_A} for v in VARIANTS for n in nodes]
    out.append({"id": "rate", "variant": "a", "node": limiting, "i_a": I_RATE_A})
    out.append({"id": "ctl", "variant": "ctl", "node": None, "i_a": I_TEST_A})
    return out


def meas_name(inst: str, level_v: float) -> str:
    return f"t_{inst}_{round(level_v * 1000)}"


def hub_node(inst: dict) -> str:
    return "ctl_hub" if inst["variant"] == "ctl" else nn(inst["node"], inst["id"])


def render_deck() -> str:
    arr = parse_v2()
    ext = json.loads(V2_EXTRACT.read_text())
    poly = storage(ext)
    nodes = sorted(poly, key=lambda n: int(re.sub(r"\D", "", n)))
    insts = instances(nodes, limiting_node(ext))
    L: list[str] = []
    a = L.append
    a("* compact_device_c_sn.spice -- device-inclusive storage-node capacitance, compact v2 extracted array (issue #208).")
    a("* GENERATED by compact_device_c_sn.py; do not edit.")
    a("*")
    a("* CIRCUIT BODY for `klt sim`: no .control/.end; the PDK .lib/.temp cards are appended per corner by klt. Flat and")
    a("* self-contained (the batch fleet receives only this file + request.json).")
    a("*")
    a("* Each instance is the committed extracted array layout/compact/gain_cell_2t_v2_array.extract.parasitics.spice")
    a("* node-for-node with the instance id appended to every net, generic `nfet` -> sky130_fd_pr__nfet_01v8, GND and")
    a("* vsubs tied to ideal ground. Drawn diffusion AD/AS/PD/PS are the extracted ones.")
    a("* Instance ids: a_<n> / p_<n> / b_<n> = variant a / p / b probing storage node <n> (see the generator docstring:")
    a("*   a = extracted wiring C kept, devices on top (may double count channel poly); p = the node's whole extracted poly")
    a("*   ground C removed; b = as a with rbl = rwl = 0 V). rate = limiting node of a at 1/5 the current; ctl = ideal 1 fF.")
    a("* Probed node: a known current is drawn from its hub (tanh-gated off below 0.05 V) and the 1.0 ... 0.1 V crossing")
    a("* times are measured (.meas WHEN). All other storage nodes are ideal sources (quiet neighbours); wl = bl = 0 V.")
    a("* ASSUMPTIONS (labelled; none is a spec value): ideal drivers, stored '1' = 1.0 V, neighbours 1.0 V, no mismatch.")
    a("")
    a(f".options {SIM_OPTIONS}")
    a(f".param VDD = {_f(VDD_V)}")
    a("vdd  vdd  0 dc {VDD}")
    a(f"vrbl vrbl 0 dc {_f(VRBL_V)}")
    a("")
    ics: list[str] = []
    for inst in insts:
        iid = inst["id"]
        if inst["variant"] == "ctl":
            a(f"* ---- instance {iid}: ideal {_f(C_KNOWN_F * 1e15)} fF control ----")
            a(f"cctl_{iid} ctl_hub 0 {_f(C_KNOWN_F)}")
            ics.append(f"v(ctl_hub)={_f(V_START_V)}")
        else:
            a(f"* ---- instance {iid}: variant {inst['variant']}, probed storage node {inst['node']} ----")
            read_idle = 0.0 if inst["variant"] == "b" else None
            for m in arr_mos(arr):
                name, d, g, s, b, par = m
                a(f"xm{name[2:].lower()}_{iid} {nn(d, iid)} {nn(g, iid)} {nn(s, iid)} {nn(b, iid)} sky130_fd_pr__nfet_01v8 "
                  f"L={_f(par['L'])} W={_f(par['W'])} nf=1 ad={_f(par['AD'])} as={_f(par['AS'])} "
                  f"pd={_f(par['PD'])} ps={_f(par['PS'])} mult=1 m=1")
            for nm, n1, n2, ohm in arr["res"]:
                if nm == "Rvsubs_dctie":
                    continue
                a(f"{nm.lower()}_{iid} {nn(n1, iid)} {nn(n2, iid)} {_f(ohm)}")
            for nm, n1, n2, f in arr["cap"]:
                if inst["variant"] == "p" and (n1, n2) == (inst["node"], "vsubs"):
                    f -= poly[inst["node"]] * 1e-15           # whole extracted poly ground term of the probed node
                    if f <= 0:
                        raise DeviceCError(f"{iid}: poly term exceeds the node's ground capacitance")
                a(f"{nm.lower()}_{iid} {nn(n1, iid)} {nn(n2, iid)} {_f(f)}")
            nets = {n for (_n, d, g, s, b, _p) in arr["mos"] for n in (d, g, s, b)} | {
                n for (_n, n1, n2, _o) in arr["res"] for n in (n1, n2)}
            for r in range(4):
                a(f"vdw_{iid}_{r} wl_{r}_{iid} 0 dc 0")
                a(f"vdr_{iid}_{r} rwl_{r}_{iid} {'0' if read_idle == 0.0 else 'vdd'} dc 0")
            for c in range(4):
                a(f"vdb_{iid}_{c} bl_{c}_{iid} 0 dc 0")
                a(f"vdp_{iid}_{c} rbl_{c}_{iid} {'0' if read_idle == 0.0 else 'vrbl'} dc 0")
            for n in nodes:
                if n != inst["node"]:
                    a(f"vdn_{iid}_{short(n)} {nn(n, iid)} 0 dc {_f(V_NEIGHBOUR_V)}")
            for net in sorted(nets):
                base = hub_of(net)
                if net in ("GND", "vsubs", "0"):
                    continue
                if base in poly:
                    val = V_START_V if base == inst["node"] else V_NEIGHBOUR_V
                elif base.startswith("rbl_"):
                    val = 0.0 if read_idle == 0.0 else VRBL_V
                elif base.startswith("rwl_"):
                    val = 0.0 if read_idle == 0.0 else VDD_V
                elif base.startswith(("bl_", "wl_")):
                    val = 0.0
                elif base.startswith("GND"):
                    val = 0.0
                else:
                    raise DeviceCError(f"{iid}: unclassified net {net!r}")
                ics.append(f"v({nn(net, iid)})={_f(val)}")
        hub = hub_node(inst)
        ramp = f"min(1,max(0,(time-{_f(T_RAMP_S)})/0.2n))"
        gate = f"0.5*(1+tanh((v({hub})-{_f(V_GATE_V)})/{_f(V_GATE_W_V)}))"
        a(f"bdr_{iid} {hub} 0 i={_f(inst['i_a'])}*{ramp}*{gate}")
        a("")
    a("* initial conditions (tran uic): probed node at 1.1 V, everything else at its idle level")
    for k in range(0, len(ics), 4):
        a(".ic " + " ".join(ics[k:k + 4]))
    a("")
    return "\n".join(L)


def parse_v2() -> dict:
    """The extracted v2 subcircuit; same parser as sim/write-disturb, but the v2 file."""
    text = re.sub(r"\n\+", " ", V2_NETLIST.read_text())
    mos, res, cap = [], [], []
    in_sub = False
    for ln in (x.strip() for x in text.splitlines()):
        if not ln or ln.startswith("*"):
            continue
        u = ln.upper()
        if u.startswith(".SUBCKT"):
            in_sub = True
            continue
        if u.startswith(".ENDS"):
            in_sub = False
            continue
        if not in_sub:
            continue
        tok = ln.split()
        kind = tok[0][0].upper()
        if kind == "M":
            if tok[5].lower() != "nfet":
                raise DeviceCError(f"unexpected device model in the extracted array: {ln}")
            par = {}
            for t in tok[6:]:
                k, v = t.split("=")
                par[k.upper()] = float(re.sub(r"[UuPp]$", "", v))
            mos.append((tok[0], tok[1], tok[2], tok[3], tok[4], par))
        elif kind == "R":
            res.append((tok[0], tok[1], tok[2], float(tok[3])))
        elif kind == "C":
            cap.append((tok[0], tok[1], tok[2], float(tok[3])))
        else:
            raise DeviceCError(f"unexpected element in the extracted array: {ln}")
    if len(mos) != 32:
        raise DeviceCError(f"expected 32 devices in the extracted v2 array, found {len(mos)}")
    return {"mos": mos, "res": res, "cap": cap}


def arr_mos(arr: dict) -> list:
    return arr["mos"]


def build_request() -> dict:
    ext = json.loads(V2_EXTRACT.read_text())
    insts = instances(sorted(storage(ext), key=lambda n: int(re.sub(r"\D", "", n))), limiting_node(ext))
    meas = [{"name": meas_name(i["id"], v), "unit": "s",
             "spice": f".meas tran {meas_name(i['id'], v)} WHEN v({hub_node(i)})={_f(v)} FALL=1"}
            for i in insts for v in LEVELS_V]
    return klt_request(DECK_PATH.name, {"process": list(PROCESS_CORNERS), "temperature_c": list(TEMPS_C)},
                       f"10p {_f(T_STOP_S * 1e9)}n 0 100p uic", meas, 3600,
                       extra_options={"ngspice_init": ["set measureprec=12", "set numdgt=12"]})


def render_request() -> str:
    return json.dumps(build_request(), indent=1) + "\n"


def check_generated() -> int:
    bad = [p.name for p, want in ((DECK_PATH, render_deck()), (REQUEST_PATH, render_request()))
           if not p.is_file() or p.read_text() != want]
    if bad:
        print(f"STALE: {bad} do not match the committed extraction (re-run `gen`)", file=sys.stderr)
        return 1
    print("OK: committed deck/request match the extraction")
    return 0


# ---------------------------------------------------------------------------
# reduction
# ---------------------------------------------------------------------------
def c_window_ff(times: list[float], i_a: float) -> float:
    """Charge per volt over the whole 1.0 -> 0.1 V window, fF."""
    return i_a * (times[-1] - times[0]) / DELTA_V_V * 1e15


def c_steps_ff(times: list[float], i_a: float) -> list[float]:
    return [i_a * (t1 - t0) / (v0 - v1) * 1e15 for (t0, t1, v0, v1) in
            zip(times, times[1:], LEVELS_V, LEVELS_V[1:])]


def extract_times(report: dict, insts: list[dict]) -> dict:
    """{(corner, temp): {inst id: [t at each level]}} -- exactly the request's Cartesian product."""
    AN.check_identity(report, DECK_PATH)
    if report.get("status") != "pass" or report.get("errored") or report.get("failed"):
        raise AN.AnalysisError(f"report not successful: status={report.get('status')!r} "
                               f"failed={report.get('failed')} errored={report.get('errored')}")
    want = {(p, t) for p in PROCESS_CORNERS for t in TEMPS_C}
    out: dict = {}
    for c in report.get("corners") or []:
        key = (c.get("process"), c.get("temperature_c"))
        if key in out:
            raise AN.AnalysisError(f"duplicate PVT point {key}")
        if c.get("status") != "pass":
            raise AN.AnalysisError(f"corner {key} status {c.get('status')!r}")
        m = {}
        for e in c.get("measurements") or []:
            if e["name"] in m:
                raise AN.AnalysisError(f"corner {key}: duplicate measurement {e['name']}")
            if e.get("status") != "pass" or e.get("unit") != "s":
                raise AN.AnalysisError(f"corner {key}: measurement {e['name']} status/unit {e.get('status')!r}/{e.get('unit')!r}")
            m[e["name"]] = e.get("value")
        out[key] = {}
        for i in insts:
            ts = []
            for v in LEVELS_V:
                x = m.get(meas_name(i["id"], v))
                if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x <= 0:
                    raise AN.AnalysisError(f"corner {key}: {meas_name(i['id'], v)} is {x!r}, not a crossing time")
                ts.append(float(x))
            if any(t1 <= t0 for t0, t1 in zip(ts, ts[1:])):
                raise AN.AnalysisError(f"corner {key}: instance {i['id']} crossing times not increasing: {ts}")
            out[key][i["id"]] = ts
    if set(out) != want:
        raise AN.AnalysisError(f"PVT set mismatch: missing {sorted(want - set(out))}, unexpected {sorted(set(out) - want)}")
    return out


def load_leakage_v2() -> dict:
    with LEAKAGE_POINTS.open() as f:
        return {(r["corner"], int(r["temp_c"])): float(r["i_v2_a"]) for r in csv.DictReader(f)}


def retention_us(c_ff: float, i_leak_a: float) -> float:
    return c_ff * 1e-15 * DELTA_V_V / i_leak_a * 1e6


def reduce_points(times: dict, insts: list[dict], wiring: dict) -> list[dict]:
    leak = load_leakage_v2()
    by_id = {i["id"]: i for i in insts}
    rows = []
    for key in sorted(times, key=lambda k: (PROCESS_CORNERS.index(k[0]), k[1])):
        t = times[key]
        c = {iid: c_window_ff(t[iid], by_id[iid]["i_a"]) for iid in t}
        row = {"corner": key[0], "temp_c": key[1], "i_leak_v2_a": leak[key],
               "control_ideal_1fF_ff": round(c["ctl"], 6)}
        for v in VARIANTS:
            cand = {i["node"]: c[i["id"]] for i in insts if i["variant"] == v and i["id"] != "rate"}
            node = min(cand, key=lambda n: (cand[n], n))
            row[f"{v}_limiting_node"] = node
            row[f"{v}_c_sn_ff"] = round(cand[node], 6)
            row[f"{v}_c_sn_max_node_ff"] = round(max(cand.values()), 6)
            row[f"{v}_retention_us"] = round(retention_us(cand[node], leak[key]), 4)
        lim = row["a_limiting_node"]
        a_lim = c[f"a_{short(lim)}"]
        row["rate_check_ff"] = round(c["rate"], 6)
        row["rate_check_rel_dev"] = round(c["rate"] / a_lim - 1, 6)
        row["a_limiting_c_vs_v_ff"] = [round(x, 6) for x in c_steps_ff(t[f"a_{short(lim)}"], I_TEST_A)]
        row["wiring_only_ff"] = wiring["wiring_ff"]
        row["wiring_only_retention_us"] = round(retention_us(wiring["wiring_ff"], leak[key]), 4)
        row["bounding_wiring_plus_full_cgate_ff"] = wiring["bounding_ff"]
        row["bounding_retention_us"] = round(retention_us(wiring["bounding_ff"], leak[key]), 4)
        rows.append(row)
    return rows


def load_wiring_baseline() -> dict:
    d = json.loads(WIRING_BASELINE.read_text())["layouts"]["compact_v2"]
    return {"wiring_ff": d["at_limiting_node"]["c_sn_ff"],
            "bounding_ff": d["bounding_scenario_wiring_plus_full_cgate"]["c_sn_ff"],
            "limiting_node": d["limiting_node"]}


def verdicts(rows: list[dict]) -> dict:
    ctl = max(abs(r["control_ideal_1fF_ff"] * 1e-15 / C_KNOWN_F - 1) for r in rows)
    rate = max(abs(r["rate_check_rel_dev"]) for r in rows)
    wc = next(r for r in rows if (r["corner"], r["temp_c"]) == WORST_CASE)
    between = all(r["wiring_only_ff"] <= r[f"{v}_c_sn_ff"] for r in rows for v in ("p", "a")) and \
        all(r["p_c_sn_ff"] <= r["a_c_sn_ff"] for r in rows)
    return {"control_max_rel_error": round(ctl, 6), "control_ok": ctl <= CTL_TOL,
            "rate_check_max_abs_rel_dev": round(rate, 6), "rate_check_ok": rate <= RATE_TOL,
            "variant_ordering_p_le_a_and_wiring_le_p_holds_at_every_point": between,
            "worst_case": {"corner": WORST_CASE[0], "temp_c": WORST_CASE[1],
                           "p_c_sn_ff": wc["p_c_sn_ff"], "a_c_sn_ff": wc["a_c_sn_ff"], "b_c_sn_ff": wc["b_c_sn_ff"],
                           "p_retention_us": wc["p_retention_us"], "a_retention_us": wc["a_retention_us"],
                           "b_retention_us": wc["b_retention_us"],
                           "wiring_only_retention_us": wc["wiring_only_retention_us"],
                           "bounding_retention_us": wc["bounding_retention_us"],
                           "ratified_retention_us": 10.05989,
                           "ratified_refresh_interval_us": 5.029945}}


def build_result(report_path: Path, report: dict) -> dict:
    ext = json.loads(V2_EXTRACT.read_text())
    insts = instances(sorted(storage(ext), key=lambda n: int(re.sub(r"\D", "", n))), limiting_node(ext))
    if DECK_PATH.read_text() != render_deck() or REQUEST_PATH.read_text() != render_request():
        raise AN.AnalysisError("generated deck/request do not match the extraction (stale?)")
    times = extract_times(report, insts)
    wiring = load_wiring_baseline()
    rows = reduce_points(times, insts, wiring)
    v = verdicts(rows)
    env = report.get("environment", {})
    rel = lambda p: str(Path(p).resolve().relative_to(REPO))  # noqa: E731
    return {
        "schema": SCHEMA, "issue": 208, "label": LABEL, "n_points": len(rows),
        "method": {"window_v": [LEVELS_V[0], LEVELS_V[-1]], "levels_v": LEVELS_V, "delta_v_v_ASSUMPTION": DELTA_V_V,
                   "i_test_a": I_TEST_A, "i_rate_a": I_RATE_A, "stored_one_v_ASSUMPTION": LEVELS_V[0],
                   "neighbour_v_ASSUMPTION": V_NEIGHBOUR_V, "t_ramp_s": T_RAMP_S, "sim_options": SIM_OPTIONS,
                   "variants": {"a": "extracted wiring C kept + devices (UPPER end; may count channel poly twice)",
                                "p": "node's whole extracted poly ground C removed + devices (LOWER end)",
                                "b": "variant a with rbl = rwl = 0 V (channel formed: bounding bias case, not the idle bias)"}},
        "checks": {k: v[k] for k in v if k != "worst_case"},
        "worst_case": v["worst_case"],
        "points": rows,
        "inputs": {"report": rel(report_path), "report_sha256": sha256_prefixed(report_path),
                   "deck_sha256": sha256_prefixed(DECK_PATH), "request_sha256": sha256_prefixed(REQUEST_PATH),
                   "extraction": rel(V2_EXTRACT), "extraction_sha256": sha256_prefixed(V2_EXTRACT),
                   "extracted_netlist": rel(V2_NETLIST), "extracted_netlist_sha256": sha256_prefixed(V2_NETLIST),
                   "leakage_points": rel(LEAKAGE_POINTS), "leakage_points_sha256": sha256_prefixed(LEAKAGE_POINTS),
                   "wiring_baseline": rel(WIRING_BASELINE), "wiring_baseline_sha256": sha256_prefixed(WIRING_BASELINE)},
        "engine": {"engine": env.get("engine"), "engine_version": env.get("engine_version")},
        "batch": env.get("remote"), "models_lib_sha256": env.get("models_lib_sha256"),
        "pdk_open_pdks_commit": AN.G_pin(), "klt_provenance": report.get("provenance"),
    }


def cmd_reduce(report_path: Path) -> int:
    run_id = report_path.stem.split("klt_report_", 1)[1]
    out = report_path.with_name(f"{RESULT_PREFIX}{run_id}.json")
    if out.exists():
        print(f"refusing to overwrite existing evidence file {out}", file=sys.stderr)
        return 2
    try:
        doc = build_result(report_path, json.loads(report_path.read_text()))
    except (AN.AnalysisError, DeviceCError, CP.CompactError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    out.write_text(json.dumps(doc, indent=1) + "\n")
    for line in summary_lines(doc):
        print(line)
    print(f"wrote {out}")
    return 0


def summary_lines(doc: dict) -> list[str]:
    w = doc["worst_case"]
    return [f"[{doc['label']}]",
            f"checks: {doc['checks']}",
            f"{w['corner']}/{w['temp_c']} C: C_SN {w['p_c_sn_ff']} (p, lower) .. {w['a_c_sn_ff']} (a, upper) fF; bias-b {w['b_c_sn_ff']} fF; "
            f"retention {w['p_retention_us']} .. {w['a_retention_us']} us (wiring-only {w['wiring_only_retention_us']}, "
            f"bounding {w['bounding_retention_us']}, ratified {w['ratified_retention_us']})"]


def cmd_check(path: Path) -> int:
    committed = json.loads(path.read_text())
    report = REPO / committed["inputs"]["report"]
    doc = build_result(report, json.loads(report.read_text()))
    if json.loads(json.dumps(doc)) != committed:
        print(f"DRIFT: {path} does not match a recomputation from the committed inputs", file=sys.stderr)
        return 1
    print(f"OK: {path} reproduces from the committed inputs")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("gen", help="write the deck and klt sim request")
    r = sub.add_parser("reduce", help="reduce a committed klt report into a NEW result file")
    r.add_argument("report", type=Path)
    ap.add_argument("--check-generated", action="store_true")
    ap.add_argument("--check", metavar="FILE", type=Path)
    a = ap.parse_args(argv)
    try:
        if a.check_generated:
            return check_generated()
        if a.check:
            return cmd_check(a.check)
        if a.cmd == "gen":
            OUT.mkdir(exist_ok=True)
            DECK_PATH.write_text(render_deck())
            REQUEST_PATH.write_text(render_request())
            print(f"wrote {DECK_PATH} and {REQUEST_PATH}")
            return 0
        if a.cmd == "reduce":
            return cmd_reduce(a.report)
    except (AN.AnalysisError, DeviceCError, CP.CompactError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
