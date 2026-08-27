# gcedram comp data (generated, public-sources-only)

Generated 2026-08-27 from the upstream comp library's `gcedram.md` entry by an internal, private-repo-only tool. This is a derived, filtered copy — regenerate rather than hand-edit. Every row below cites a public vendor datasheet or a public distributor pricing page; nothing internal survived extraction.

## Comparable parts

| Source | Process | Topology | Bias / temp | Retention (DRT) | Density vs 6T SRAM | DOI |
|---|---|---|---|---|---|---|
| Chun, Jain, Kim & Kim, *IEEE JSSC* vol. 47 no. 2, 2012 | 65 nm LP CMOS | asymmetric 2T | 1.1 V, 85 °C | **110 µs**, measured refresh period at 99.9% bit yield (192 kb test chip) | not stated in this paper | [10.1109/JSSC.2011.2168729](https://doi.org/10.1109/JSSC.2011.2168729) |
| Giterman, Shalom, Burg, Fish & Teman, *IEEE Solid-State Circuits Letters* vol. 3, 2020 | 16 nm FinFET | mixed-VT 3T | 600 mV, −40…+125 °C | **77 µs** measured DRT (1-Mbit test chip) | **2× smaller bitcell** than 6T SRAM at similar design rules (abstract, verbatim) | [10.1109/LSSC.2020.3006496](https://doi.org/10.1109/LSSC.2020.3006496) |
| Giterman, Fish, Burg & Teman, *IEEE TCAS-I* vol. 65 no. 4, 2018 | 28 nm FD-SOI | 4T, nMOS-only, internal feedback | 700 mV, 27 °C | **>1.6 ms** measured (8-kb array); "conventional" topologies at the same node inferred **~53 µs** (1.6 ms / 30×, same-paper-derived, not independently confirmed) | **~30% smaller** cell area than single-ported 6T SRAM, same node (abstract, verbatim) | [10.1109/TCSI.2017.2747087](https://doi.org/10.1109/TCSI.2017.2747087) |

