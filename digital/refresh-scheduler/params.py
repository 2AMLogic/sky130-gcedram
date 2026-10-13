#!/usr/bin/env python3
"""Print the ratified INTERVAL (cycles, 1 cycle = 1 ns ASSUMPTION), read from
the committed retention CSV rather than retyped.  usage: params.py [ratified|extracted]"""
import csv, math, pathlib, sys
CSV = pathlib.Path(__file__).resolve().parents[2] / "sim/retention/results/retention_results.csv"
which = sys.argv[1] if len(sys.argv) > 1 else "ratified"
rows = [r for r in csv.DictReader(CSV.open()) if r["geometry_name"] == "2T-min"
        and r["leakage_source_row"] == "corner=sf,temp_c=125"]
rows.sort(key=lambda r: r["timestamp_utc"])
row = rows[0] if which == "ratified" else rows[-1]   # 2026-08-20 ASSUMED-C_SN row is the ratified one
t_ret = float(row["retention_time_s"])
interval_ns = t_ret / 2 * 1e9               # 2x margin: spec Sec.7 ASSUMPTION
print(math.floor(interval_ns))               # floor = conservative
