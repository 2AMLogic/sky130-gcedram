v {xschem version=3.4.7 file_version=1.2
* column_periphery.sch -- column-periphery slice between the 2T gain-cell
* column and the sense latch (issue #114, revised by issue #117). Replaces the
* ideal precharge switch and ideal write-bitline source that sim/sense-stage,
* sim/loaded-column and sim/write-disturb use. Sizing rationale and the
* issue-#117 sweep: sim/column-periphery/README.md.
*
* SIZES ARE PROVISIONAL. They are frozen here exactly as
* sim/column-periphery/gen_isolation_study.py instantiates the FINAL variant
* (f00) so the testbench and this schematic cannot drift
* (design/test_column_periphery.py enforces it).
*
* Devices (all W/L in um; core 1.8 V sky130 flavours):
*   MPPRE  pfet: d=rbl  g=pre_b s=vpre b=vpre  read-bitline precharge (active low), 5.0 um (issue #117; was 4.0);
*                                              n-well tied to the 0.9 V rail, NOT vdd (see below)
*   MPPREF pfet: d=ref  g=pre_b s=vref b=vref  reference-side precharge, a copy of MPPRE incl. 5.0 um (issue #117)
*   MPU1   pfet: d=x    g=dinb  s=vdd  b=vdd   write driver: tri-state inverter
*   MPU2   pfet: d=wbl  g=wenb  s=x    b=vdd     (wbl = NOT dinb while wen=1)
*   MND2   nfet: d=wbl  g=wen   s=y    b=GND   4.0 um (issue #117; was 0.5)
*   MND1   nfet: d=y    g=dinb  s=GND  b=GND   4.0 um (issue #117; was 0.5)
*   MNI    nfet: d=wbl  g=wenb  s=GND  b=GND   idle pull-down (wbl idles at 0 V), 2.0 um (was 0.42)
*   MNS    nfet: rbl <-> sbl   column-select / isolation gate, 0.42 um, nfet only (issue #117;
*                              was a 1.0/2.0 transmission gate)
*   MNSR   nfet: ref <-> sref  matched dummy gate on the reference side, 0.42 um
*
* Ports: rbl (array read bitline), sbl (sense-latch input side of the
* isolation gate), ref / sref (reference side, matched), wbl (array write
* bitline), pre_b (active-low precharge, shared by MPPRE and MPPREF), vpre
* (precharge rail, 0.9 V, ASSUMED ideal supply -- generating VDD/2 is out of
* scope), vref (reference-side precharge rail, VRBL - 0.1 V, ASSUMED ideal),
* dinb (inverted write data), wen / wenb, sel (isolation gates, active high),
* vdd. GND is the global ground.
*
* Why the isolation gate is nfet only and 0.42 um: the issue-#117 study found
* that the gates erode the stored-'1' sense input by LOADING the read bitline
* (the transmission gate and the precharge device add 8.6 fF, against the
* assumed 10 fF array bitline), not by charge injection when they close.
* The pfet half of the old transmission gate was most of that load.
*
* MPPREF: the #114 testbench precharged the reference with an ideal switch,
* which hid the +50 to +80 mV step that releasing MPPRE puts on rbl. A real
* reference column releases its own precharge device at the same edge, so
* the step is common-mode. MPPREF is that device.
*
* MPPRE body: with the well at vdd the precharge device sources a 0.9 V rail
* at a reverse body bias of 0.9 V, which raises |Vth| and makes the last
* tens of mV of settling slow (sim/column-periphery/README.md sizing
* evidence). Tying its well to vpre is a layout consequence: MPPRE needs its
* own n-well with a vpre tap (a later layout issue); the same holds for MPPREF
* with vref.
*
* Deliberately NOT in this cell: the sense latch (design/sense_latch.sch),
* the array, the reference level generation, and all control timing -- these
* are testbench elements.
}
G {}
V {}
S {}
E {}
C {sky130_fd_pr/pfet_01v8.sym} 0 0 0 0 {name=MPPRE W=5 L=0.15 nf=1 mult=1 model=pfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 20 30 0 0 {name=l1 sig_type=std_logic lab=rbl}
C {devices/lab_pin.sym} -20 0 0 0 {name=l2 sig_type=std_logic lab=pre_b}
C {devices/lab_pin.sym} 20 -30 0 0 {name=l3 sig_type=std_logic lab=vpre}
C {devices/lab_pin.sym} 20 0 0 0 {name=l4 sig_type=std_logic lab=vpre}
C {sky130_fd_pr/pfet_01v8.sym} 200 0 0 0 {name=MPU1 W=1 L=0.15 nf=1 mult=1 model=pfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 220 30 0 0 {name=l5 sig_type=std_logic lab=x}
C {devices/lab_pin.sym} 180 0 0 0 {name=l6 sig_type=std_logic lab=dinb}
C {devices/lab_pin.sym} 220 -30 0 0 {name=l7 sig_type=std_logic lab=vdd}
C {devices/lab_pin.sym} 220 0 0 0 {name=l8 sig_type=std_logic lab=vdd}
C {sky130_fd_pr/pfet_01v8.sym} 400 0 0 0 {name=MPU2 W=1 L=0.15 nf=1 mult=1 model=pfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 420 30 0 0 {name=l9 sig_type=std_logic lab=wbl}
C {devices/lab_pin.sym} 380 0 0 0 {name=l10 sig_type=std_logic lab=wenb}
C {devices/lab_pin.sym} 420 -30 0 0 {name=l11 sig_type=std_logic lab=x}
C {devices/lab_pin.sym} 420 0 0 0 {name=l12 sig_type=std_logic lab=vdd}
C {sky130_fd_pr/nfet_01v8.sym} 600 0 0 0 {name=MND2 W=4 L=0.15 nf=1 mult=1 model=nfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 620 -30 0 0 {name=l13 sig_type=std_logic lab=wbl}
C {devices/lab_pin.sym} 580 0 0 0 {name=l14 sig_type=std_logic lab=wen}
C {devices/lab_pin.sym} 620 30 0 0 {name=l15 sig_type=std_logic lab=y}
C {devices/gnd.sym} 620 0 0 0 {name=lg16 lab=GND}
C {sky130_fd_pr/nfet_01v8.sym} 800 0 0 0 {name=MND1 W=4 L=0.15 nf=1 mult=1 model=nfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 820 -30 0 0 {name=l17 sig_type=std_logic lab=y}
C {devices/lab_pin.sym} 780 0 0 0 {name=l18 sig_type=std_logic lab=dinb}
C {devices/gnd.sym} 820 30 0 0 {name=lg19 lab=GND}
C {devices/gnd.sym} 820 0 0 0 {name=lg20 lab=GND}
C {sky130_fd_pr/nfet_01v8.sym} 0 400 0 0 {name=MNI W=2 L=0.15 nf=1 mult=1 model=nfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 20 370 0 0 {name=l21 sig_type=std_logic lab=wbl}
C {devices/lab_pin.sym} -20 400 0 0 {name=l22 sig_type=std_logic lab=wenb}
C {devices/gnd.sym} 20 430 0 0 {name=lg23 lab=GND}
C {devices/gnd.sym} 20 400 0 0 {name=lg24 lab=GND}
C {sky130_fd_pr/nfet_01v8.sym} 200 400 0 0 {name=MNS W=0.42 L=0.15 nf=1 mult=1 model=nfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 220 370 0 0 {name=l25 sig_type=std_logic lab=sbl}
C {devices/lab_pin.sym} 180 400 0 0 {name=l26 sig_type=std_logic lab=sel}
C {devices/lab_pin.sym} 220 430 0 0 {name=l27 sig_type=std_logic lab=rbl}
C {devices/gnd.sym} 220 400 0 0 {name=lg28 lab=GND}
C {sky130_fd_pr/nfet_01v8.sym} 600 400 0 0 {name=MNSR W=0.42 L=0.15 nf=1 mult=1 model=nfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 620 370 0 0 {name=l33 sig_type=std_logic lab=sref}
C {devices/lab_pin.sym} 580 400 0 0 {name=l34 sig_type=std_logic lab=sel}
C {devices/lab_pin.sym} 620 430 0 0 {name=l35 sig_type=std_logic lab=ref}
C {devices/gnd.sym} 620 400 0 0 {name=lg36 lab=GND}
C {sky130_fd_pr/pfet_01v8.sym} 1000 0 0 0 {name=MPPREF W=5 L=0.15 nf=1 mult=1 model=pfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 1020 30 0 0 {name=l41 sig_type=std_logic lab=ref}
C {devices/lab_pin.sym} 980 0 0 0 {name=l42 sig_type=std_logic lab=pre_b}
C {devices/lab_pin.sym} 1020 -30 0 0 {name=l43 sig_type=std_logic lab=vref}
C {devices/lab_pin.sym} 1020 0 0 0 {name=l44 sig_type=std_logic lab=vref}
C {devices/iopin.sym} -100 -30 0 0 {name=p_rbl lab=rbl}
C {devices/iopin.sym} -100 30 0 0 {name=p_sbl lab=sbl}
C {devices/iopin.sym} -100 90 0 0 {name=p_ref lab=ref}
C {devices/iopin.sym} -100 150 0 0 {name=p_sref lab=sref}
C {devices/iopin.sym} -100 210 0 0 {name=p_wbl lab=wbl}
C {devices/ipin.sym} -100 270 0 0 {name=p_pre_b lab=pre_b}
C {devices/iopin.sym} -100 330 0 0 {name=p_vpre lab=vpre}
C {devices/ipin.sym} -100 390 0 0 {name=p_dinb lab=dinb}
C {devices/ipin.sym} -100 450 0 0 {name=p_wen lab=wen}
C {devices/ipin.sym} -100 510 0 0 {name=p_wenb lab=wenb}
C {devices/ipin.sym} -100 570 0 0 {name=p_sel lab=sel}
C {devices/iopin.sym} -100 630 0 0 {name=p_vdd lab=vdd}
C {devices/iopin.sym} -100 690 0 0 {name=p_vref lab=vref}
C {devices/title.sym} 0 -260 0 0 {name=l_title author="2AM Logic (issues #114, #117: column periphery slice, provisional sizes)"}
