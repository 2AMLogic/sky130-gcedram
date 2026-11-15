#!/usr/bin/env python3
"""Generate the loaded-column `klt sim` decks and batch requests (issue #169).

Stdlib only. Expresses the grid that ``run_loaded_column.py`` (and, with knobs,
``cold-corner/run_variants.py``) runs as a LOCAL ``ngspice -b`` process pool as
committed ``klt sim`` corner requests, so the re-qualification grid goes to the
batch fleet instead of a hand-launched local grid.

Three things differ from the local runners, by necessity, and each is recorded
on every row the reducer writes:

1. **One deck per (knob set, age, selected row); the 16 stored patterns are 16
   INDEPENDENT column instances inside it.** ``klt sim`` has no per-case axis
   for a transient grid (its corner axis is process x temperature only), and a
   ``.control``/``alterparam`` loop is not expressible as a request. Sixteen
   electrically independent 4-row columns in one deck give the same 16 cases in
   one corner unit. The instances share only the write/read wordline sources and
   the precharge control -- all ideal voltage sources, so no instance loads
   another.
2. **Reductions are ``.meas`` cards, not Python interpolation of a waveform.**
   ``klt sim`` returns measurement scalars; a transient request cannot return
   named node vectors (``options.complex_vectors`` is AC-only). Every FIND/AT
   card reads the same instant ``run_loaded_column.measure()`` interpolates at,
   so the two agree to the simulator's own interpolation.
3. **The read-latency threshold is the absolute level ``VRBL - 0.1 V``**, where
   the local runner used the measured pre-read float level minus 0.1 V. ngspice
   cannot reference one ``.meas`` result from another's ``WHEN`` value, so the
   level has to be known when the deck is written. The pre-read float level is
   within ~2 mV of VRBL (it floats for TPRE_GAP only), and the reducer records
   both the threshold it used and the measured float level per row, so the
   difference is visible rather than assumed.

A per-instance 0 V source (``vam_r<r>_p<pp>``) is inserted in series with each
read device's rwl terminal so that cell's read current can be measured with the
wordline sources shared; it is ideal and changes nothing electrically. The local
runner read ``-i(vrwl_r)`` of an unshared source for the same quantity.

Device cards are copied VERBATIM from ``design/gain_cell_2t.spice`` (re-sized by
``run_variants.device_card`` when a knob changes W), never ``.include``d: a batch
worker cannot read a path on the submitting host. The design netlist's sha256 is
written into every deck header and checked by ``test_gen_column_requests.py``.

Usage:
    python3 sim/loaded-column/gen_column_requests.py            # Phase 2 grid
    python3 sim/loaded-column/gen_column_requests.py --check    # staleness only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM = HERE.parent
REPO = SIM.parent
sys.path.insert(0, str(SIM))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "cold-corner"))
import run_loaded_column as R  # noqa: E402  (also sets up sim/ + layout/ imports)
import run_variants as V2  # noqa: E402  (device_card / timing / read_time)
from _evidence_common import PDK_OPEN_PDKS_COMMIT  # noqa: E402
from klt_request import MODELS, ENGINE, BACKEND  # noqa: E402

N_ROWS = R.N_ROWS
PATTERNS = list(range(16))
CORNERS = list(R.CORNERS)
TEMPS_C = list(R.TEMPS_C)
AGES = list(R.AGE_LABELS)
MEAS_INIT = ["set measureprec=12", "set numdgt=12"]
TMAX_S = 0.5e-9  # run_loaded_column.py --tmax-ns default
TSTEP = "10p"

#: `options.timeout_s` per corner unit. A fresh unit is a 135 ns transient of 16
#: columns; an aged unit is the same circuit over the 5.03 us refresh bound. The
#: measured fleet runtimes are ~4 s and ~7 s per unit respectively (job
#: klt-sim-4f3bc98a85da / klt-sim-3eae2770e796, m7i.4xlarge), so these are ~30x
#: headroom AND keep `timeout_s x 15 units + 120 s` under the fleet's 3600 s
#: whole-job ceiling, which a larger value would exceed (klt warns, and a job
#: still running at the ceiling is killed with every unit batch_job_timeout).
TIMEOUT_S = {"fresh": 180, "refresh_bound": 220}

KLT_DIR = HERE / "klt"  # decks and requests live together: a klt request
#: resolves `netlist` relative to its own file.

#: Phase 2 knob set: every value equals cold-corner/variants.py BASELINE, so the
#: same generator renders the cold-corner variants from `variants.knobs(vid)`.
BASELINE_KNOBS = {
    "vwl_v": 1.8,
    "twpulse_s": 20e-9,
    "vrwl_sel_v": 0.0,
    "c_rbl_f": 10e-15,
    "t_sense_s": 10e-9,
    "wr_model": "sky130_fd_pr__nfet_01v8",
    "wr_w_um": 0.42,
    "rd_model": "sky130_fd_pr__nfet_01v8",
    "rd_w_um": 0.42,
    "force": 0,
    "vsn1_v": 0.0,
}


class GenError(ValueError):
    pass


# --------------------------------------------------------------------------- #
# timing
# --------------------------------------------------------------------------- #
def params(knobs: dict) -> dict[str, float]:
    """Timing/bias parameters: the `.param` block of the Phase 2 template with
    the write-pulse-derived instants recomputed for this knob set. At the
    baseline 20 ns pulse this reproduces TWSTEP 25 ns / THOLD0 100 ns exactly."""
    P = R.parse_params(R.TEMPLATE.read_text())
    P.update(V2.timing(knobs))
    return P


def read_time(P: dict, age: str) -> float:
    if age not in AGES:
        raise GenError(f"unknown age {age!r}")
    return V2.read_time(P, age)


def instants(P: dict, knobs: dict, age: str) -> dict:
    """Every measurement instant, derived exactly as run_loaded_column.measure()
    derives it (one place, so the deck and the reducer cannot disagree)."""
    t_read = read_time(P, age)
    return {
        "t_read": t_read,
        "t_wl_off": [P["TW0"] + r * P["TWSTEP"] + P["TWPULSE"] for r in range(N_ROWS)],
        "t_after_write": P["THOLD0"] - 0.5e-9,
        "t_preread": t_read - P["TPRE_GAP"] - 0.5e-9,
        "t_rbl_preread": t_read - 0.2e-9,
        "t_sense": t_read + knobs["t_sense_s"],
        "t_rbl_end": t_read + P["TREAD_PULSE"] - 5 * P["TEDGE"],
        "t_end": t_read + P["TREAD_PULSE"] + P["TTAIL"] - 0.5e-9,
        "tstop": t_read + P["TREAD_PULSE"] + P["TTAIL"],
    }


# --------------------------------------------------------------------------- #
# deck
# --------------------------------------------------------------------------- #
def design_sha256() -> str:
    return hashlib.sha256(R.DESIGN_NETLIST.read_bytes()).hexdigest()


def device_cards(knobs: dict) -> tuple[str, str]:
    """(write, read) device card tails, re-sized from the committed design
    netlist by the cold-corner runner's own re-sizing rule."""
    devs = R.parse_design_devices()
    for name in ("M_WR", "M_RD"):
        if devs[name][0] != BASELINE_KNOBS["wr_model"]:
            raise GenError(f"design {name} model changed: {devs[name][0]}")
    return (
        V2.device_card(devs["M_WR"][1], knobs["wr_model"], knobs["wr_w_um"]),
        V2.device_card(devs["M_RD"][1], knobs["rd_model"], knobs["rd_w_um"]),
    )


def _bl_pwl(pattern: int) -> str:
    """Write-bitline PWL of one instance: row r's data level held for its write
    pulse (identical shape to run_loaded_column.render)."""
    pts = ["0 0"]
    for r in range(N_ROWS):
        bit = (pattern >> r) & 1
        on, off = f"TW0+{r}*TWSTEP", f"TW0+{r}*TWSTEP+TWPULSE"
        pts += [
            f"{{{on}-TEDGE}} 0",
            f"{{{on}}} {{VDD*{bit}}}",
            f"{{{off}+TBL_LAG}} {{VDD*{bit}}}",
            f"{{{off}+TBL_LAG+TEDGE}} 0",
        ]
    return "pwl(" + " ".join(pts) + ")"


def tag(pattern: int) -> str:
    return f"p{pattern:02d}"


def deck_text(knobs: dict, age: str, sel: int, c_sn_f: float,
              patterns: list[int] = PATTERNS) -> str:
    """One `klt sim` circuit body: no .lib/.temp/.control/.end (klt appends the
    PDK cards and the analysis per corner)."""
    if sel not in range(N_ROWS):
        raise GenError(f"selected row {sel} out of range")
    P = params(knobs)
    t_read = read_time(P, age)
    wr, rd = device_cards(knobs)
    L = [
        "* GENERATED by sim/loaded-column/gen_column_requests.py -- DO NOT EDIT BY HAND.",
        "* Loaded four-row 2T gain-cell column, re-qualification grid for issue #169.",
        f"* age={age}  selected_row={sel}  patterns={len(patterns)} independent instances",
        "* Circuit, stimulus and measurement instants come from",
        "* sim/loaded-column/tb_loaded_column.spice.tmpl and run_loaded_column.py;",
        "* the two device cards are copied verbatim from design/gain_cell_2t.spice",
        f"* (sha256:{design_sha256()}), re-sized only when a knob changes W.",
        "* ALL timing / bias / loading below is a labelled ASSUMPTION -- see",
        "* sim/loaded-column/README.md. Nothing here is a ratified spec value.",
        "*",
        "* Instance <tag> = one electrically independent 4-row column holding one",
        "* stored pattern. Instances share only ideal voltage sources, so no",
        "* instance loads another; vam_r<r>_<tag> is a 0 V ammeter in series with",
        "* that cell's read-device rwl terminal (i_into_rbl = +i(vam)).",
        "",
        f".param VDD = {R.VDD}",
        f".param VRBL = {P['VRBL']}",
        f".param TEDGE = {P['TEDGE']:.6e}",
        f".param TW0 = {P['TW0']:.6e}",
        f".param TWSTEP = {P['TWSTEP']:.6e}",
        f".param TWPULSE = {P['TWPULSE']:.6e}",
        f".param TBL_LAG = {P['TBL_LAG']:.6e}",
        f".param THOLD0 = {P['THOLD0']:.6e}",
        f".param TPRE_GAP = {P['TPRE_GAP']:.6e}",
        f".param TREAD_PULSE = {P['TREAD_PULSE']:.6e}",
        f".param TTAIL = {P['TTAIL']:.6e}",
        f".param T_READ = {t_read:.9e}",
        f".param VWL = {knobs['vwl_v']:.6g}",
        f".param VRWL_SEL = {knobs['vrwl_sel_v']:.6g}",
        f".param C_RBL = {knobs['c_rbl_f']:.6e}",
        f".param VSN1 = {knobs['vsn1_v']:.6g}",
        f".param DV_LAT = {R.DV_LATENCY_V:.6g}",
        ".GLOBAL GND",
        "",
        "* shared write wordlines (row r pulses at TW0 + r*TWSTEP)",
    ]
    for r in range(N_ROWS):
        L.append(
            f"vwl_{r} wl_{r} 0 pulse(0 {{VWL}} {{TW0+{r}*TWSTEP}} {{TEDGE}} {{TEDGE}} "
            f"{{TWPULSE-TEDGE}} 1)"
        )
    L += ["", f"* shared read wordlines: row {sel} is the selected row and falls to VRWL_SEL"]
    for r in range(N_ROWS):
        lvl = "{VRWL_SEL}" if r == sel else "{VDD}"
        L.append(
            f"vrwl_{r} rwl_{r} 0 pwl(0 {{VDD}} {{T_READ}} {{VDD}} {{T_READ+TEDGE}} {lvl} "
            f"{{T_READ+TREAD_PULSE}} {lvl} {{T_READ+TREAD_PULSE+TEDGE}} {{VDD}})"
        )
    L += [
        "",
        "* shared precharge: ideal switch from a VRBL source, opened TPRE_GAP before the read",
        "vpre pre 0 dc {VRBL}",
        "vctl ctl 0 pwl(0 {VDD} {T_READ-TPRE_GAP} {VDD} {T_READ-TPRE_GAP+TEDGE} 0)",
        ".model swpre sw(vt=0.9 vh=0.1 ron=100 roff=1e12)",
    ]
    ics = []
    for pattern in patterns:
        g = tag(pattern)
        bits = [(pattern >> r) & 1 for r in range(N_ROWS)]
        L += ["", f"* ---- instance {g}: stored pattern rows3210="
              + "".join(str(bits[r]) for r in reversed(range(N_ROWS)))]
        L.append(f"v_bl_{g} bl_{g} 0 {_bl_pwl(pattern)}")
        for r in range(N_ROWS):
            L.append(f"XM_WR_r{r}_{g} sn_r{r}_{g} wl_{r} bl_{g} GND {wr}")
            L.append(f"vam_r{r}_{g} rwl_{r} rwlx_r{r}_{g} dc 0")
            L.append(f"XM_RD_r{r}_{g} rbl_{g} sn_r{r}_{g} rwlx_r{r}_{g} GND {rd}")
            L.append(f"c_sn_r{r}_{g} sn_r{r}_{g} 0 {c_sn_f:.6e}")
        L.append(f"c_rbl_{g} rbl_{g} 0 {{C_RBL}}")
        L.append(f"spre_{g} pre rbl_{g} ctl 0 swpre")
        # Phase 2: each sn starts at the OPPOSITE of its data (a genuine
        # overwrite). force=1 (attribution only): sn starts AT its data.
        if knobs["force"]:
            lvls = [f"{{VSN1*{bits[r]}}}" for r in range(N_ROWS)]
        else:
            lvls = [f"{{VDD*{1 - bits[r]}}}" for r in range(N_ROWS)]
        ics.append(
            f".ic v(rbl_{g})={{VRBL}} "
            + " ".join(f"v(sn_r{r}_{g})={lvls[r]}" for r in range(N_ROWS))
        )
    L += ["", "* initial conditions (no uic: the operating point honours them as constraints)"]
    L += ics
    L.append("")
    return "\n".join(L)


# --------------------------------------------------------------------------- #
# measurements
# --------------------------------------------------------------------------- #
def measurements(knobs: dict, age: str, sel: int,
                 patterns: list[int] = PATTERNS) -> list[dict]:
    """`.meas` cards equivalent to run_loaded_column.measure(), one block per
    instance. Names are `<tag>__<field>`; the reducer splits on `__`."""
    P = params(knobs)
    T = instants(P, knobs, age)
    out: list[dict] = []

    def add(name: str, unit: str, card: str, **extra) -> None:
        m = {"name": name, "unit": unit, "spice": f".meas tran {name} {card}"}
        m.update(extra)
        out.append(m)

    for pattern in patterns:
        g = tag(pattern)
        for r in range(N_ROWS):
            add(f"{g}__v_sn_r{r}_wl_off_v", "V",
                f"FIND v(sn_r{r}_{g}) AT={T['t_wl_off'][r]:.9e}")
        for r in range(N_ROWS):
            add(f"{g}__v_sn_r{r}_after_write_v", "V",
                f"FIND v(sn_r{r}_{g}) AT={T['t_after_write']:.9e}")
        for r in range(N_ROWS):
            add(f"{g}__v_sn_r{r}_preread_v", "V",
                f"FIND v(sn_r{r}_{g}) AT={T['t_preread']:.9e}")
            add(f"{g}__i_into_rbl_r{r}_preread_a", "A",
                f"FIND i(vam_r{r}_{g}) AT={T['t_preread']:.9e}")
        add(f"{g}__v_rbl_preread_float_v", "V",
            f"FIND v(rbl_{g}) AT={T['t_rbl_preread']:.9e}")
        for r in range(N_ROWS):
            add(f"{g}__i_into_rbl_r{r}_sense_a", "A",
                f"FIND i(vam_r{r}_{g}) AT={T['t_sense']:.9e}")
        add(f"{g}__v_rbl_sense_v", "V", f"FIND v(rbl_{g}) AT={T['t_sense']:.9e}")
        add(f"{g}__v_rbl_end_v", "V", f"FIND v(rbl_{g}) AT={T['t_rbl_end']:.9e}")
        add(f"{g}__v_sn_sel_sense_v", "V",
            f"FIND v(sn_r{sel}_{g}) AT={T['t_sense']:.9e}")
        for r in range(N_ROWS):
            add(f"{g}__v_sn_r{r}_end_v", "V",
                f"FIND v(sn_r{r}_{g}) AT={T['t_end']:.9e}")
        # Absolute-threshold latency (see module docstring item 3). A case whose
        # rbl never falls DV_LAT below VRBL reports a failed measurement, which
        # the reducer records as the local runner's `latency_reason`.
        # `on_unreached: "null"` is the documented opt-in for a WHEN target that
        # the window never reaches: a stored '0' never discharges rbl by DV_LAT,
        # which is a RESULT (the local runner's empty `latency_s` plus a
        # `latency_reason`), not a simulator error.
        add(f"{g}__t_latency_abs_s", "s",
            f"WHEN v(rbl_{g})={{VRBL-DV_LAT}} FALL=1 TD={T['t_read']:.9e}",
            on_unreached="null")
    return out


# --------------------------------------------------------------------------- #
# request
# --------------------------------------------------------------------------- #
def request(netlist: str, knobs: dict, age: str, sel: int,
            points: list[tuple[str, int]], patterns: list[int] = PATTERNS) -> dict:
    """A `klt sim` request over `points` [(process, temp_c), ...]. Points that
    are not the full cross product of the process/temperature axes are removed
    with `exclude`."""
    P = params(knobs)
    T = instants(P, knobs, age)
    procs = sorted({c for c, _ in points}, key=CORNERS.index)
    temps = sorted({t for _, t in points})
    excl = [{"process": c, "temperature_c": t}
            for c in procs for t in temps if (c, t) not in points]
    req = {
        "netlist": netlist,
        "engine": ENGINE,
        "backend": BACKEND,
        "models": dict(MODELS),
        "corners": {"process": procs, "temperature_c": temps},
    }
    if excl:
        req["exclude"] = excl
    req["analysis"] = {
        "kind": "tran",
        "args": f"{TSTEP} {T['tstop']:.6e} 0 {TMAX_S:.3e}",
    }
    req["measurements"] = measurements(knobs, age, sel, patterns)
    req["options"] = {
        "timeout_s": TIMEOUT_S[age],
        "keep_artifacts": False,
        "waveforms": False,
        "ngspice_init": list(MEAS_INIT),
    }
    return req


def phase2_jobs() -> list[dict]:
    """The Phase 2 (loaded-column) grid: 4 selected rows x 2 ages, each over the
    full 15-point PVT grid."""
    pts = [(c, t) for c in CORNERS for t in TEMPS_C]
    return [
        {
            "name": f"lc_{age}_sel{sel}",
            "knobs": dict(BASELINE_KNOBS),
            "age": age,
            "sel": sel,
            "points": pts,
        }
        for age in AGES
        for sel in range(N_ROWS)
    ]


def job_paths(job: dict, klt_dir: Path = KLT_DIR) -> tuple[Path, Path]:
    return (klt_dir / f"{job['name']}.spice",
            klt_dir / f"request_{job['name']}.json")


def render_job(job: dict, c_sn_f: float) -> tuple[str, str]:
    deck, _ = job_paths(job)
    text = deck_text(job["knobs"], job["age"], job["sel"], c_sn_f)
    req = request(deck.name, job["knobs"], job["age"], job["sel"], job["points"])
    return text, json.dumps(req, indent=2) + "\n"


def write_job(job: dict, c_sn_f: float, klt_dir: Path = KLT_DIR) -> tuple[Path, Path]:
    klt_dir.mkdir(parents=True, exist_ok=True)
    deck, reqp = job_paths(job, klt_dir)
    text, req = render_job(job, c_sn_f)
    deck.write_text(text)
    reqp.write_text(req)
    return deck, reqp


def c_sn_farads() -> float:
    c_sn_ff, _prov = R.load_extracted_c_sn(R.EXTRACT_JSON, "sn")
    return c_sn_ff * 1e-15


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if a committed deck/request differs from a fresh render")
    a = ap.parse_args(argv)
    c_sn_f = c_sn_farads()
    stale = []
    for job in phase2_jobs():
        deck, reqp = job_paths(job)
        want_deck, want_req = render_job(job, c_sn_f)
        if a.check:
            for path, want in ((deck, want_deck), (reqp, want_req)):
                if not path.is_file() or path.read_text() != want:
                    stale.append(str(path.relative_to(REPO)))
        else:
            write_job(job, c_sn_f)
            print(f"wrote {deck.relative_to(REPO)} and {reqp.relative_to(REPO)}")
    if a.check:
        if stale:
            print("stale or missing:\n  " + "\n  ".join(stale), file=sys.stderr)
            return 1
        print(f"up to date (PDK pin {PDK_OPEN_PDKS_COMMIT[:7]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
