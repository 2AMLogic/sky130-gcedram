# Reliability-evidence search log and source pins (issue #51)

Epic #24 phase 5. Research only: **no simulation was run**. Public sources
only. Retrieved 2026-10-07. This file is append-only evidence; it extends
[`skywater-pdk-device-details-excerpt.md`](skywater-pdk-device-details-excerpt.md)
(issue #49), which is unchanged.

Question (a): is there a gate-oxide / TDDB / HCI limit for the 1.8 V NMOS
(`sky130_fd_pr__nfet_01v8`) at gate overdrive above 1.95 V (candidate A,
`VWL` = 2.0 V)? Question (b): is there a forward-junction injection or
latch-up bound for source/drain nodes below substrate potential (candidate B,
-0.2 V read wordline and the `rbl` that follows it)?

## 1. Classification used

* **LIMIT**: a documented operating or absolute-maximum limit for the device
  in question.
* **MODEL-RANGE**: a statement of where a SPICE model is valid.
* **MEASURED**: published measurement data.
* **DESIGN-RULE**: a layout/DRC rule (not an electrical limit for a bias).
* **NOT-APPLICABLE**: documented, but for a different device class.

A passing SPICE run is never a LIMIT.

## 2. Pinned sources

Clone location of both repositories: `git clone --depth 1`, HEAD as below.
File hashes are SHA-256 of the file at that HEAD.

| Id | Source | Pin |
|---|---|---|
| S1 | `google/skywater-pdk` | HEAD `7198cf647113f56041e02abf3eb623692820c5e1` (2023-05-29) |
| S1a | `docs/rules/hv.rst` | sha256 `f355ddf478c129661e96b44d4c4509a124e85e2e44d51bd3b072b43aee7e1f98` |
| S1b | `docs/rules/assumptions.rst` | sha256 `99981cebb004a90f7947abc9461f03cdacc4b1906c94f340359c7aeb13f62edc` |
| S1c | `docs/rules/device-details/diodes/diodes-table0.rst` | sha256 `3f16c7dd4f2d9a24c6db99e7750ae588b12664e8c0d350e1a180f49bb8dc0b06` |
| S1d | `docs/rules/device-details.rst` | sha256 `506021827f52b26673daf8b580f8d79d408724af3138a65695bde86e5c1c6e49` |
| S2 | `RTimothyEdwards/open_pdks` (tech file for Magic, HEAD at retrieval) | HEAD `801834fcbf9119e6fd4462f97da9e637f284539a`, `sky130/magic/sky130.tech` sha256 `5f96a22bd00169807b2228742e17a27e3624e5fb010c523447bbc4fee30a4f97` |
| S3 | installed `sky130A` (open_pdks pin `c6d73a35f524070e85faff4a6a9eef49553ebc2b`) | `libs.tech/combined/sky130.lib.spice` sha256 `48de7c677e2c6e7d09b2559279de9f818be71010a4aa933d728eb4db3b133c84` |

Note on S3: an installed-library file; the check script verifies its hash only when a PDK is installed.

## 3. Verbatim excerpts

### E1. S1a `docs/rules/hv.rst` lines 4-5 (DESIGN/METHODOLOGY statement)

```
High Voltage is defined as a voltage outside the range of GND to Vcc.  Any device that is subjected to a voltage outside the range of GND to Vcc is considered a high voltage device.  These devices are subjected to special design rules and biasing conditions.  The biasing conditions of these high voltage devices are detailed in the ETD.
```

Classification: methodology definition, **not a limit**. It bears on both
candidates: with Vcc = 1.8 V, a 2.0 V gate (A) and a -0.2 V node (B) are each
"outside the range of GND to Vcc". The page gives no allowance for them on a
1.8 V device and defers biasing conditions to the "ETD", which is not public.
This is adverse-to-neutral for A and B; it is not an approval or a
prohibition with a number.

### E2. S1a `docs/rules/hv.rst` (NOT-APPLICABLE limits, HV NMOS/PMOS)

```
Transistor Performance Degradation under HV Gate Stress (Section 2.2.2 of EDR)
  The maximum voltage across the gate oxide (gate to channel voltage) is restricted to:

   a. Any HV NMOS device: 7.3 V @ 25C.
   b. Any HV PMOS device: 8.1 V @ 25C.

  These voltages are not operating voltages, but points of failure.
```

and

```
Junction Leakage/breakdown
  The maximum source/drain to substrate junction voltages are restricted to the following:

  a. Any HV NMOS device: 11.0 V @ 25C.
```

Classification: **documented limits, but for HV (high-voltage, thick-gate-class)
devices** (section also lists a VHV block: 5.5 V gate oxide, 16.0 V junction).
Not NOT the 1.8 V `nfet_01v8`. They must not be transferred to it. They show
the foundry publishes failure-point limits per device class and that the
1.8 V class limit is simply absent from the public text.

### E3. S1b `docs/rules/assumptions.rst` Table 3e (DESIGN-RULE)

```
Minimum n+ or p+ - nwell spacing to prevent latch-up,um,0.23,NPNWLU
```

Classification: layout spacing rule (n+/p+ to n-well). Says nothing about
forward-biasing an n+/p-well junction by a sub-ground node, nor a current
bound.

### E4. S1d `docs/rules/device-details.rst` lines 838 and 887 (NOT-APPLICABLE)

```
Using this device must be done in conjunction with the correct guard rings, to avoid potential latchup issues with nearby circuitry. Reverse-active mode operation of the BJT’s are neither modeled nor permitted.
```

Classification: NPN/PNP bipolar device guidance, not the NMOS array. Shows
that where the foundry restricts a bias mode it says so in this page; there
is no such sentence for MOSFET forward junction bias or sub-ground nodes.

### E5. S2 `sky130/magic/sky130.tech` (DESIGN-RULE, DRC)

```
"N-diff distance to P-tap must be < 15.0um (LU.2)"
"N-diff distance to P-tap in deep nwell.must be < 15.0um (LU.2.1)"
"P-diff distance to N-tap must be < 15.0um (LU.3)"
```

Classification: tap-distance DRC rules. Layout hygiene for latch-up; not a
bound on injected forward current or on how far below the substrate a node
may go. The installed pinned PDK's `sky130A.tech` carries the same three
rule texts (lines 4326-4330 at retrieval).

### E6. S1c `diodes-table0.rst` (MEASURED-spec, wrong direction)

```
   * - BVN
     - 11.7
     - 10.7
     - 14.0
     - V
     - N+ breakdown voltage
```

Classification: E-test spec for **reverse** breakdown (nominal/lower/upper
spec limit). It is not a forward-injection bound.

## 4. Search log (every search, including negative results)

| # | Scope | Method / query | Outcome |
|---|---|---|---|
| 1 | skywater-pdk `docs/` and tree, text files | `grep -rIiE` for `TDDB`, `hot.carrier`, `NBTI`, `overstress`, `absolute.max`, `safe operating` | **No match** for any of them. |
| 2 | skywater-pdk | `HCI` | One match: `assumptions.rst` Table 3f `HCIMPA` = "High current" implant angle (0 deg), an implant parameter, not hot-carrier injection. **Negative.** |
| 3 | skywater-pdk | `reliab`, `breakdown`, `oxide` | `hv.rst` (HV/VHV limits, E1, E2), diode E-test table (E6); other matches are layout-rule or field-oxide text. No 1.8 V limit. |
| 4 | skywater-pdk | `latch.?up` | `known_issues.rst` (list item "Latchup and soft design rules": the scripts are only available under NDA), `assumptions.rst` (E3), BJT pages (E4), `periphery-rules.rst` (HV n-well latch-up GUI field). No bound for forward-biased n+/p-well. |
| 5 | skywater-pdk | `SOA` | Matches are the HV (20 V) device pages, whose validity line reads "Operating Voltages where SPICE models are valid, subject to SOA limitations:" (`device-details.rst` lines 437, 475, 513, 557, ...). The 1.8 V NMOS validity line has no SOA qualifier and no SOA table (see the #49 excerpt); that is the only public place an SOA is mentioned, and it is not for this device. |
| 6 | open_pdks (HEAD `801834f`) | same keyword set over all files | `TDDB`, `hot.carrier`, `NBTI`, `overstress`, `absolute.max`, `reliab`, `safe.operating`: no match. `HCI`: only standard-cell names (false positive). `latch.?up`: Magic DRC rules (E5). |
| 7 | installed `sky130.lib.spice` (hash in S3) | `tddb`, `reliab`, `overstress`, `safe.operat`, `absolute max`, `hot.carrier` | **No match.** The model library carries no reliability statement. |
| 8 | arXiv API (`export.arxiv.org`) | `all:sky130 AND all:reliability`; `all:sky130 AND all:oxide`; `all:SkyWater AND all:hot-carrier`; `all:sky130 AND all:latch-up`; `all:sky130 AND all:gain cell` | **0 results each** (also 0 for free-text `sky130 TDDB`, `sky130 hot carrier degradation`, `SkyWater 130nm gate oxide reliability`). |
| 9 | OpenAlex API | `sky130 TDDB`; `sky130 hot carrier injection 1.8V NMOS`; `SkyWater 130nm gate oxide reliability`; `sky130 latch-up forward bias substrate injection` | No relevant hit. Returned titles concern SoC test, capacitance extraction, neuromorphic/accelerator designs, and a 2026 77 K DC cryogenic BSIM4 modelling paper (MEASURED-style DC data at 77 K; not an overdrive, TDDB, HCI or forward-junction study; not retrieved or relied on). The query on HCI returned nothing. |
| 10 | GitHub issue search, `google/skywater-pdk` | `TDDB`; `hot carrier`; `overvoltage 1.8V nfet`; `gate oxide reliability`; `latch-up` | No issue on the first four; `latch-up` returned only #380 (continuous SPICE MOSFET models), unrelated. **Negative.** |
| 11 | GitHub issue search, `RTimothyEdwards/open_pdks` | `TDDB`, `hot carrier`, `overvoltage` | **Search not possible** (API returned "cannot be searched" for the repository slug). Unretrievable, recorded as such; keyword search of the repository tree (row 6) stands in. |
| 12 | Foundry documents referenced by the public text | "ETD" (biasing conditions), "EDR" section 2.2.2, TDR | Referenced by `hv.rst` and `known_issues.rst`; **not public** (NDA per `known_issues.rst`). Unretrievable. |

Limits of this search: a web-search engine was not available to the worker;
arXiv, OpenAlex and repository trees were searched by API/grep. Journal
literature behind paywalls (IEEE/IRPS/IEDM foundry-process reliability papers
for the 130 nm node) was not reachable and is not claimed to be absent.

## 5. Result

* (a) Gate-oxide/TDDB/HCI limit for `nfet_01v8` above 1.95 V: **not found**
  in any public primary source searched.
* (b) Forward-junction injection / latch-up bound for sub-substrate nodes:
  **not found**. Only layout DRC latch-up rules (E3, E5) and unrelated
  reverse-breakdown data (E6).
* The only new relevant text (E1) classifies both a >Vcc gate and a <GND
  node as "high voltage" usage, with biasing conditions held in a
  non-public document.
