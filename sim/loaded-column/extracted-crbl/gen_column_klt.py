#!/usr/bin/env python3
"""Loaded four-row column as `klt sim` requests, with the extracted C_RBL (issue #88).

Stdlib only. Re-expresses the Phase 2 / cold-corner loaded-column measurement
(sim/loaded-column/run_loaded_column.py, issue #45; cold-corner/run_variants.py,
issue #47) as FLAT `klt sim` circuit bodies so the multi-corner grid runs on the
batch fleet instead of as a local ngspice grid (SENSE_INPUT_CONTRACT.md rule 4).

Why a new harness: the Phase 2 runner drives one ngspice process per batch with a
`.control` block (alterparam / reset / wrdata) and post-processes waveforms in
Python. A `klt sim` request takes a circuit body (no `.control`) plus `.meas`
lines, so every (selected row, stored pattern) case becomes an INDEPENDENT
parallel column instance inside ONE deck (64 columns per deck, one deck per read
age), and every quantity the Phase 2 `measure()` takes from the waveform is a
`.meas` here. The connectivity (M_WR sn wl bl GND / M_RD rbl sn rwl GND per row),
device cards, stimulus timing and all measurement instants are the Phase 2 ones,
imported from the Phase 2 runner and template, not restated.

Differences from the Phase 2 harness (declared; quantified by the `ref_crbl_10f`
reproduction variant against the committed rows, see README):
  * all 64 cases share one timestep sequence (one tran per deck), not 64 trans;
  * ideal sources are shared between instances (write wordlines, the 16 write
    bitline patterns, selected/deselected read wordline, precharge); per-row
    read-wordline currents (`i_into_rbl_*`) are therefore not measured;
  * the latency reference (rbl at ~t_read - 0.2 ns) is held on an ideal
    sample-and-hold (VCVS buffer, ideal switch, 1 pF), and the search window ends
    3 TEDGE before the case stop time (a forced crossing marks "not reached", so
    no `.meas` can fail on the fleet).

Variants (each changes ONLY the named knob from the Phase 2 baseline):
  ref_crbl_10f            C_RBL 10 fF (ASSUMPTION) -- harness reproduction
  crbl_ext4row            C_RBL 0.859179 fF EXTRACTED-4-ROW (bounding case:
                          no sense-input load share)
  crbl_2f                 C_RBL 2 fF -- ASSUMPTION mid-point (trend only)
  crbl_ext4row_layoutcard EXTRACTED-4-ROW C_RBL + layout diffusion card
                          (AD=AS=0.1974 um^2, PD=PS=1.78 um) on M_WR and M_RD
  nc_write_disabled_ext4row  negative control at EXTRACTED-4-ROW C_RBL: the
                          write wordline never rises, so every cell keeps the
                          inverse of its data; separation must be negative.

N_rows stays the 4-row STUDY-ASSUMPTION; nothing here ratifies a row count.

Usage:
    python3 -I sim/loaded-column/extracted-crbl/gen_column_klt.py           # write decks/
    python3 -I sim/loaded-column/extracted-crbl/gen_column_klt.py --check   # exit 1 if stale
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LC_DIR = HERE.parent
REPO = LC_DIR.parent.parent
sys.path.insert(0, str(LC_DIR))
import run_loaded_column as R  # noqa: E402  (Phase 2 runner: cards, topology, timing)

DECKS = HERE / "decks"
PARASITICS_SUMMARY = REPO / "layout" / "gain_cell_2t_array.parasitics.summary.json"
C_RBL_KEY = ("comparison", "c_rbl", "extracted_4row_worst_total_ff")

N_ROWS = R.N_ROWS
AGES = ["fresh", "refresh_bound"]
T_SENSE_S = R.T_SENSE_S          # ASSUMPTION (Phase 2)
DV_LATENCY_V = R.DV_LATENCY_V    # ASSUMPTION (Phase 2)
T_HOLD_LEAD_S = 0.25e-9          # hold-switch edge starts here before T_READ (opens ~0.19 ns before)
C_HOLD_F = 1e-12
C_RBL_REF_F = 10e-15             # the contract's ASSUMED value
C_RBL_MID_F = 2e-15              # ASSUMPTION: mid-point for the trend (not extracted)

# Diffusion card drawn by the layout (layout/gain_cell_2t_array.extract.parasitics.spice,
# every M$ device): AS=AD=0.1974 um^2, PS=PD=1.78 um. design/gain_cell_2t.spice
# uses ad=as=0.1218, pd=ps=1.42. Reconciling the retention chain is issue #89's scope.
LAYOUT_CARD = {"ad": "0.1974", "as": "0.1974", "pd": "1.78", "ps": "1.78"}

SCOPES = {
    # full Phase 2 grid; includes the two corners SENSE_INPUT_CONTRACT.md names
    # (fs/-40 C insensitive to C_RBL, ss/-40 C sensitive)
    "grid": {"process": ["tt", "ss", "ff", "sf", "fs"], "temperature_c": [-40, 27, 125]},
    # negative control: klt corners are a product, so {fs, tt} x {-40, 27} C
    # (covers the cold-corner study's nc points fs/-40 and tt/27)
    "nc": {"process": ["tt", "fs"], "temperature_c": [-40, 27]},
}


def extracted_c_rbl_ff() -> float:
    d = json.loads(PARASITICS_SUMMARY.read_text())
    v = d
    for k in C_RBL_KEY:
        v = v[k]
    return float(v)


def extracted_provenance() -> dict:
    d = json.loads(PARASITICS_SUMMARY.read_text())
    return {
        "file": str(PARASITICS_SUMMARY.relative_to(REPO)),
        "key": ".".join(C_RBL_KEY),
        "value_ff": extracted_c_rbl_ff(),
        "worst_net": d["comparison"]["c_rbl"]["extracted_4row_worst_net"],
        "netlist": d["source"]["netlist"],
        "netlist_sha256": d["source"]["netlist_sha256"],
        "label": "EXTRACTED-4-ROW (N_rows = 4 is a STUDY-ASSUMPTION, not ratified)",
    }


def variants() -> dict:
    ext = extracted_c_rbl_ff() * 1e-15
    return {
        "ref_crbl_10f": dict(c_rbl_f=C_RBL_REF_F, card="design", vwl_on=True,
                             c_rbl_label="ASSUMPTION (contract value)", cls="reproduction"),
        "crbl_ext4row": dict(c_rbl_f=ext, card="design", vwl_on=True,
                             c_rbl_label="EXTRACTED-4-ROW", cls="extracted_c_rbl"),
        "crbl_2f": dict(c_rbl_f=C_RBL_MID_F, card="design", vwl_on=True,
                        c_rbl_label="ASSUMPTION (mid-point)", cls="trend"),
        "crbl_ext4row_layoutcard": dict(c_rbl_f=ext, card="layout", vwl_on=True,
                                        c_rbl_label="EXTRACTED-4-ROW", cls="device_card_variant"),
        "nc_write_disabled_ext4row": dict(c_rbl_f=ext, card="design", vwl_on=False,
                                          c_rbl_label="EXTRACTED-4-ROW", cls="negative_control"),
    }


# which (variant, scope) requests exist
REQUESTS = [
    (v, a, "grid") for v in ("ref_crbl_10f", "crbl_ext4row", "crbl_2f", "crbl_ext4row_layoutcard")
    for a in AGES
] + [("nc_write_disabled_ext4row", a, "nc") for a in AGES]


def _fmt(x: float) -> str:
    return f"{x:.9g}"


def timing() -> dict:
    return R.parse_params(R.TEMPLATE.read_text())


def t_read(P: dict, age: str) -> float:
    return R.read_time(P, age)


def t_stop(P: dict, age: str) -> float:
    return R.case_tstop(P, t_read(P, age))


def t_late(P: dict, age: str) -> float:
    """End of the latency search window (forced crossing just after it)."""
    return t_stop(P, age) - 3 * P["TEDGE"]


def card(params: str, which: str) -> str:
    if which == "design":
        return params
    out = params
    for k, v in LAYOUT_CARD.items():
        out, n = re.subn(rf"\b{k}=[0-9.eE+-]+", f"{k}={v}", out)
        if n != 1:
            raise RuntimeError(f"card has {n} '{k}=' fields: {params}")
    return out


def cases() -> list[dict]:
    out = []
    for sel in range(N_ROWS):
        for pattern in range(16):
            out.append(dict(sel=sel, pattern=pattern, tag=f"s{sel}p{pattern:02d}"))
    return out


def meas_points(P: dict, age: str, sel: int) -> dict:
    """name prefix -> (node kind, row or None, absolute time). Same instants as R.measure()."""
    tr = t_read(P, age)
    t_pre = tr - P["TPRE_GAP"] - 0.5e-9
    t_end = tr + P["TREAD_PULSE"] + P["TTAIL"] - 0.5e-9
    pts = {
        "wo": ("sn", sel, P["TW0"] + sel * P["TWSTEP"] + P["TWPULSE"]),
        "aw": ("sn", sel, P["THOLD0"] - 0.5e-9),
        "ss": ("sn", sel, tr + T_SENSE_S),
        "rf": ("rbl", None, tr - 0.2e-9),
        "rs": ("rbl", None, tr + T_SENSE_S),
        "re": ("rbl", None, tr + P["TREAD_PULSE"] - 5 * P["TEDGE"]),
    }
    for r in range(N_ROWS):
        pts[f"pr{r}"] = ("sn", r, t_pre)
        pts[f"en{r}"] = ("sn", r, t_end)
    return pts


def build_netlist(vid: str, age: str) -> str:
    V = variants()[vid]
    P = timing()
    devs = R.parse_design_devices()
    (wm, wp), (rm, rp) = devs["M_WR"], devs["M_RD"]
    wp, rp = card(wp, V["card"]), card(rp, V["card"])
    topo = R.build_topology(N_ROWS, R.N_COLS)
    c_sn_ff, _ = R.load_extracted_c_sn(R.EXTRACT_JSON, "sn")
    tr = t_read(P, age)
    L: list[str] = []
    a = L.append
    a(f"* loaded 4-row 2T column, {vid}, age {age} (issue #88). GENERATED by gen_column_klt.py;")
    a("* do not edit. CIRCUIT BODY for `klt sim` (no .control/.end; klt appends .lib/.temp).")
    a("* 64 independent column instances (4 selected rows x 16 stored patterns), one tran.")
    a("* Phase 2 stimulus/timing (sim/loaded-column/tb_loaded_column.spice.tmpl); cards from")
    a(f"* design/gain_cell_2t.spice ({'design' if V['card'] == 'design' else 'LAYOUT diffusion card: ad=as=0.1974 pd=ps=1.78'}).")
    a(f"* C_RBL = {_fmt(V['c_rbl_f'])} F : {V['c_rbl_label']}. Lumped on rbl; no other extracted")
    a("* bitline parasitic is added (the lumped value IS the bitline load, not an addition to it).")
    a("* ASSUMPTIONS: 4-row column (STUDY-ASSUMPTION, N_rows not ratified), ideal drivers and")
    a("* precharge switch, global corners only, t_sense and latency droop per Phase 2.")
    a("")
    for k in ("VDD", "VRBL", "TEDGE", "TW0", "TWSTEP", "TWPULSE", "TBL_LAG", "THOLD0", "TPRE_GAP",
              "TREAD_PULSE", "TTAIL"):
        a(f".param {k} = {_fmt(P[k])}")
    a(f".param T_READ = {_fmt(tr)}")
    a(f".param VWL = {'{VDD}' if V['vwl_on'] else '0'}")
    a(f".param C_RBL = {_fmt(V['c_rbl_f'])}")
    a(f".param C_SN = {c_sn_ff * 1e-15:.6e}")
    a(f".param T_HLEAD = {_fmt(T_HOLD_LEAD_S)}")
    a(f".param T_LATE = {_fmt(t_late(P, age))}")
    a("")
    a("* ---- shared ideal sources ----")
    for r in range(N_ROWS):
        a(f"vwl_{r} wl_{r} 0 pulse(0 {{VWL}} {{TW0+{r}*TWSTEP}} {{TEDGE}} {{TEDGE}} {{TWPULSE-TEDGE}} 1)")
    for pattern in range(16):
        pw = ["0 0"]
        for r in range(N_ROWS):
            b = (pattern >> r) & 1
            on, off = f"TW0+{r}*TWSTEP", f"TW0+{r}*TWSTEP+TWPULSE"
            pw += [f"{{{on}-TEDGE}} 0", f"{{{on}}} {{VDD*{b}}}",
                   f"{{{off}+TBL_LAG}} {{VDD*{b}}}", f"{{{off}+TBL_LAG+TEDGE}} 0"]
        a(f"vblp{pattern:02d} blp{pattern:02d} 0 pwl(" + " ".join(pw) + ")")
    a("vrwls rwls 0 pwl(0 {VDD} {T_READ} {VDD} {T_READ+TEDGE} 0 {T_READ+TREAD_PULSE} 0 "
      "{T_READ+TREAD_PULSE+TEDGE} {VDD})")
    a("vrwld rwld 0 dc {VDD}")
    a("vpre pre 0 dc {VRBL}")
    a("vctl ctl 0 pwl(0 {VDD} {T_READ-TPRE_GAP} {VDD} {T_READ-TPRE_GAP+TEDGE} 0)")
    a("vhctl hctl 0 pwl(0 {VDD} {T_READ-T_HLEAD} {VDD} {T_READ-T_HLEAD+TEDGE} 0)")
    a("vlate late 0 pwl(0 0 {T_LATE} 0 {T_LATE+TEDGE} 2)")
    a(".model swpre sw(vt=0.9 vh=0.1 ron=100 roff=1e12)")
    a("")
    ics: list[str] = []
    for c in cases():
        t, sel, pattern = c["tag"], c["sel"], c["pattern"]

        def node(n: str) -> str:
            m = re.fullmatch(r"(sn)_(\d+)_0", n)
            if m:
                return f"sn{m.group(2)}_{t}"
            if re.fullmatch(r"wl_\d+", n):
                return n
            if n == "bl_0":
                return f"blp{pattern:02d}"
            if n == "rbl_0":
                return f"rbl_{t}"
            m = re.fullmatch(r"rwl_(\d+)", n)
            if m:
                return "rwls" if int(m.group(1)) == sel else "rwld"
            raise RuntimeError(f"unexpected topology node {n}")

        a(f"* ---- case {t}: selected row {sel}, pattern rows3210 {format(pattern, '04b')} ----")
        for d in topo["devices"]:
            a(f"X{d['wr_name']}_{t} {node(d['sn'])} {node(d['wl'])} {node(d['bl'])} GND {wm} {wp}")
            a(f"X{d['rd_name']}_{t} {node(d['rbl'])} {node(d['sn'])} {node(d['rwl'])} GND {rm} {rp}")
        for r in range(N_ROWS):
            a(f"csn{r}_{t} sn{r}_{t} 0 {{C_SN}}")
        a(f"crbl_{t} rbl_{t} 0 {{C_RBL}}")
        a(f"spre_{t} pre rbl_{t} ctl 0 swpre")
        a(f"ehb_{t} hb_{t} 0 rbl_{t} 0 1")
        a(f"shb_{t} hb_{t} hold_{t} hctl 0 swpre")
        a(f"chold_{t} hold_{t} 0 {_fmt(C_HOLD_F)}")
        a(f"bdl_{t} dl_{t} 0 v=v(rbl_{t})-v(hold_{t})+{_fmt(DV_LATENCY_V)}-v(late)")
        ics.append(f"v(rbl_{t})={{VRBL}}")
        ics.append(f"v(hold_{t})={{VRBL}}")
        for r in range(N_ROWS):
            # Phase 2: each sn starts at the OPPOSITE of its data (genuine overwrite)
            b = (pattern >> r) & 1
            ics.append(f"v(sn{r}_{t})={_fmt(R.VDD * (1 - b))}")
        a("")
    a("* initial conditions (Phase 2: .ic, no uic)")
    for k in range(0, len(ics), 6):
        a(".ic " + " ".join(ics[k:k + 6]))
    a("")
    return "\n".join(L)


def build_request(vid: str, age: str, scope: str) -> dict:
    P = timing()
    meas = []
    for c in cases():
        t = c["tag"]
        for name, (kind, row, at) in meas_points(P, age, c["sel"]).items():
            node = f"rbl_{t}" if kind == "rbl" else f"sn{row}_{t}"
            meas.append({"name": f"{name}_{t}", "unit": "V",
                         "spice": f".meas tran {name}_{t} FIND v({node}) AT={at:.9e}"})
        meas.append({"name": f"lat_{t}", "unit": "s",
                     "spice": f".meas tran lat_{t} WHEN v(dl_{t})=0 FALL=1 TD={t_read(P, age):.9e}"})
    return {
        "netlist": f"{vid}_{age}.spice",
        "engine": "ngspice",
        "backend": "batch",
        "models": {"pdk": "sky130A", "lib": "libs.tech/combined/sky130.lib.spice"},
        "corners": SCOPES[scope],
        "analysis": {"kind": "tran", "args": f"10p {t_stop(P, age):.9e} 0 5e-10"},
        "measurements": meas,
        "options": {"timeout_s": 900 if age == "fresh" else 7200, "keep_artifacts": False,
                    "waveforms": False},
    }


def render() -> dict[str, str]:
    files = {}
    for vid, age, scope in REQUESTS:
        files[f"{vid}_{age}.spice"] = build_netlist(vid, age)
        files[f"request_{vid}_{age}.json"] =json.dumps(build_request(vid, age, scope), indent=1) + "\n"
    return files


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if decks/ is stale")
    a = ap.parse_args(argv)
    files = render()
    if a.check:
        stale = [n for n, txt in files.items() if not (DECKS / n).is_file() or (DECKS / n).read_text() != txt]
        for n in stale:
            print(f"stale: decks/{n}", file=sys.stderr)
        return 1 if stale else 0
    DECKS.mkdir(exist_ok=True)
    for old in DECKS.glob("*"):
        if old.name not in files:
            old.unlink()
    for n, txt in files.items():
        (DECKS / n).write_text(txt)
    print(f"wrote {len(files)} files to {DECKS.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
