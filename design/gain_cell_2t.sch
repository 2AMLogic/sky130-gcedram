v {xschem version=3.4.7 file_version=1.2
* gain_cell_2t.sch -- 2T gain-cell eDRAM bitcell (issue #14, T1 item 1)
*
* Topology: RATIFIED 2T (`2T-min`) per spec/retention-refresh-budget.md
* Section 6 -- "this macro's baseline bitcell topology is ratified as 2T."
* Not 3T: this schematic deliberately omits the third, dedicated
* read-access device that a 3T candidate would add between M_RD's drain
* and the read bitline (see that same spec section's rationale and
* sim/retention/README.md "Candidate geometries" for the 2T-vs-3T
* device-count contrast this schematic follows).
*
* Devices (both sky130_fd_pr__nfet_01v8, the ratified core 1.8V NMOS --
* no other sky130_fd_pr flavour is used anywhere in this schematic):
*   M_WR (write-access transistor): gate=wl, drain=sn, source=bl, body=GND.
*     Gates the storage node onto the write bitline when selected. Sized
*     W=0.42um L=0.15um -- IDENTICAL geometry to the access device already
*     measured in sim/leakage/tb_access_leakage.spice.tmpl (see that file's
*     header and sim/leakage/README.md "Device choice"), reused here
*     unchanged (not a fresh/independent choice) so this schematic's write
*     device is the same physical device the retention evidence chain
*     (spec/retention-refresh-budget.md) already measured -- no new leakage
*     re-derivation is implied or needed by capturing this schematic.
*   M_RD (read transistor): gate=sn, drain=rbl, source=rwl, body=GND. Gate
*     tied to the storage node -- this is the "gain" device: it senses the
*     stored charge as a channel conductance rather than driving current
*     off the node itself, so read access does not discharge sn through
*     M_RD directly (M_RD's gate current is ~0; only M_WR's off-state
*     leakage, already characterized in sim/leakage/, discharges sn).
*     Sizing: same W=0.42um L=0.15um minimum geometry as M_WR. This is a
*     placeholder/first-pass choice, NOT yet driven by a read-current or
*     sense-margin analysis -- no sense-amplifier design exists yet (see
*     sim/retention/README.md's own "ASSUMPTION" framing for C_SN/delta_V,
*     which has the same pre-sense-amp-design caveat). Read-path sizing is
*     out of scope for this issue (T1 item 1, design-sources capture only)
*     and is expected to be revisited once sense-amp work begins.
*
* Node naming -- kept consistent with sim/leakage/README.md's bias-condition
* table (per this issue's acceptance criteria, since downstream testbenches
* reference those exact names):
*   wl  -- (write) wordline. Same role/name as the leakage testbench's `wl`
*          (gate of the access/write device, held 0V when unselected).
*   sn  -- storage node. Same name as the leakage testbench's `sn` (drain of
*          the access/write device). Internal to the cell: no hierarchical
*          port is declared for it below (an unbroken 2-pin net, M_WR
*          drain to M_RD gate, satisfies xschem's ERC without one) --
*          matching real silicon, where the storage node has no pin.
*   bl  -- (write) bitline. Same name as the leakage testbench's `bl`
*          (source of the access/write device).
*   rwl, rbl -- read wordline / read bitline. New names (the leakage
*          testbench only exercises the write/access device in isolation,
*          so it has no read-path nodes to match); prefixed `r` to keep
*          them unambiguous against wl/bl above rather than colliding with
*          them, while still reading as the same wl/bl naming family.
*
* Wordline drive scheme -- EXPLICITLY RECORDED per the repo README's
* "Supply" row ("boosted wordline is a design decision to record"): this
* schematic assumes a PLAIN 1.8V wordline (wl and rwl both swing 0/VDD,
* the sky130 standard core rail -- see README.md "Target specification"),
* NOT a boosted-above-VDD scheme. Consequence, noted here rather than
* silently absorbed: an NMOS pass device (M_WR) driven by a plain-VDD
* wordline can only pull the storage node up to VDD - Vgs(M_WR), a
* threshold-voltage drop below a full logic '1' -- this schematic does not
* attempt to compensate for that drop (e.g. no charge pump/level-shifter is
* included). This is an open item for a future write-margin analysis, not
* a claim that plain-VDD writing is lossless; it is called out explicitly
* here (and in design/README.md) rather than left implicit, and it does not
* change any committed retention number -- spec/retention-refresh-budget.md's
* worst-case leakage/retention chain already evaluates the storage node
* AT VDD (a full logic '1'), independent of how that level is written.
*
* Ports (net labels below, no drawn wires -- xschem joins same-named
* labels, matching this repo-family's existing schematic convention, e.g.
* 2AMLogic/sky130-sar-adc's design/comparator.sch): wl, bl, rwl (ipin,
* externally driven) and rbl (opin, read bitline driven low/pulled by the
* cell's read current during a read access). sn is intentionally NOT a
* port (see "Node naming" above). This is a leaf/core schematic only --
* no on-page stimulus, no VDD rail instance (the 2T cell itself has no
* direct supply connection; VDD only ever appears indirectly, as the
* driven high level on wl/bl/rwl/rbl from array periphery not captured
* here) -- consistent with this issue's non-goals (array/periphery is
* explicitly out of scope; see the issue body).
}
G {}
V {}
S {}
E {}
C {sky130_fd_pr/nfet_01v8.sym} 0 0 0 0 {name=M_WR W=0.42 L=0.15 nf=1 mult=1 model=nfet_01v8 spiceprefix=X}
C {sky130_fd_pr/nfet_01v8.sym} 200 0 0 0 {name=M_RD W=0.42 L=0.15 nf=1 mult=1 model=nfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 20 -30 0 0 {name=l1 sig_type=std_logic lab=sn}
C {devices/lab_pin.sym} -20 0 0 0 {name=l2 sig_type=std_logic lab=wl}
C {devices/lab_pin.sym} 20 30 0 0 {name=l3 sig_type=std_logic lab=bl}
C {devices/gnd.sym} 20 0 0 0 {name=lgnd4 lab=GND}
C {devices/lab_pin.sym} 220 -30 0 0 {name=l5 sig_type=std_logic lab=rbl}
C {devices/lab_pin.sym} 180 0 0 0 {name=l6 sig_type=std_logic lab=sn}
C {devices/lab_pin.sym} 220 30 0 0 {name=l7 sig_type=std_logic lab=rwl}
C {devices/gnd.sym} 220 0 0 0 {name=lgnd8 lab=GND}
C {devices/ipin.sym} -100 -30 0 0 {name=p_wl lab=wl}
C {devices/ipin.sym} -100 30 0 0 {name=p_bl lab=bl}
C {devices/ipin.sym} -100 90 0 0 {name=p_rwl lab=rwl}
C {devices/opin.sym} -100 150 0 0 {name=p_rbl lab=rbl}
C {devices/title.sym} 0 -260 0 0 {name=l_title author="2AM Logic (issue #14: 2T gain-cell bitcell, 2T-min per spec/retention-refresh-budget.md Sec.6)"}
