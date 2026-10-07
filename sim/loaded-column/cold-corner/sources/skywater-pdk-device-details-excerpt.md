# Excerpt: SkyWater PDK "Device Details" page (primary SKY130 documentation)

Public source, quoted verbatim for the 1.8 V NMOS (`sky130_fd_pr__nfet_01v8`)
and its low-Vt flavour. Retrieved for issue #49 on 2026-10-07; this is a
**pin of what was read**, not a copy of the page.

| Field | Value |
|---|---|
| URL | https://skywater-pdk.readthedocs.io/en/main/rules/device-details.html |
| Source file | `docs/rules/device-details.rst` in https://github.com/google/skywater-pdk |
| Last commit touching that file (GitHub API, 2026-10-07) | `995acd5dfa0589d156619694db011873796a5d2d` (2022-10-31) |
| `google/skywater-pdk` `main` HEAD at retrieval | `7198cf647113f56041e02abf3eb623692820c5e1` (2023-05-29) |
| SHA-256 of the HTML as retrieved (a live page may drift; the verbatim text below is the pinned evidence) | `0a7ec55952b9d164421ece31221ce05727db96c1a4e34de0abb77ad6bea6c959` |

Verbatim text (whitespace-normalised) under "1.8V NMOS FET / Spice Model Information":

```
Cell Name: sky130_fd_pr__nfet_01v8
Model Name: sky130_fd_pr__nfet_01v8
Operating Voltages where SPICE models are valid
V_DS = 0 to 1.95V   V_GS = 0 to 1.95V   V_BS = +0.3 to -1.95V
```

The identical three-line voltage statement appears for
`sky130_fd_pr__nfet_01v8_lvt`.

## What this does and does not say

* It is a **SPICE-model validity range**. The page does not call it an
  absolute-maximum rating, a reliability (oxide/hot-carrier) limit, or a
  recommended operating condition.
* No lifetime, duty-cycle, temperature or TDDB/HCI statement for the 1.8 V
  device was found on this page or on the `assumptions`, `layers`,
  `periphery` and `summary` pages of the same documentation set (keyword
  search for reliab/TDDB/hot-carrier/breakdown/overstress/1.95 on the
  fetched text; only a metal-fuse sentence matched "reliably").
* The same page sets the expected signs of the arguments (`V_GS = 0 to
  1.95 V`), yet the Phase 2 baseline already drives deselected-row read
  devices at negative `V_GS` (gate `sn`, source `rwl` = 1.8 V). The range
  statement is therefore a nominal-convention statement and is not, on its
  own, a complete limit set.
