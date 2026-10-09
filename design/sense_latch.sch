v {xschem version=3.4.7 file_version=1.2
* sense_latch.sch -- single-ended-reference latch sense stage: cross-coupled
* latch plus footer/header enables (issue #109). Design source of record for
* the stage that sim/sense-stage/ (gen_sense_stage.py), sim/sense-mismatch/
* and sim/loaded-column/ characterize.
*
* SIZES ARE PROVISIONAL FIRST-PASS, NOT OPTIMIZED. They are frozen here
* exactly as sim/sense-stage/gen_sense_stage.py instantiates them (LATCH_N,
* LATCH_P, FOOTER, HEADER) so the characterization decks and this schematic
* cannot drift (design/test_sense_latch.py enforces it). This file records
* provenance; it does not claim a sizing result. A later sizing issue may
* change the numbers.
*
* Devices (all W/L in um; core 1.8 V sky130 flavours):
*   MN1 nfet W=1.0 L=0.15: d=rbl g=ref s=vn b=GND   (latch NMOS)
*   MN2 nfet W=1.0 L=0.15: d=ref g=rbl s=vn b=GND   (latch NMOS)
*   MP1 pfet W=2.0 L=0.15: d=rbl g=ref s=vp b=vdd   (latch PMOS)
*   MP2 pfet W=2.0 L=0.15: d=ref g=rbl s=vp b=vdd   (latch PMOS)
*   MNF nfet W=2.0 L=0.15: d=vn  g=en  s=GND b=GND  (footer)
*   MPH pfet W=4.0 L=0.15: d=vp  g=enb s=vdd b=vdd  (header)
*
* Ports: rbl (inout, read bitline / sense input), ref (inout, reference
* side of the latch), en / enb (ipin, complementary latch enables), vdd.
* GND is the global ground. vn / vp are internal virtual rails.
*
* Deliberately NOT in this cell (testbench elements, kept outside): the
* ideal precharge switch and the matched dummy reference that drive rbl/ref.
}
G {}
V {}
S {}
E {}
C {sky130_fd_pr/nfet_01v8.sym} 0 0 0 0 {name=MN1 W=1 L=0.15 nf=1 mult=1 model=nfet_01v8 spiceprefix=X}
C {sky130_fd_pr/nfet_01v8.sym} 200 0 0 0 {name=MN2 W=1 L=0.15 nf=1 mult=1 model=nfet_01v8 spiceprefix=X}
C {sky130_fd_pr/pfet_01v8.sym} 0 -200 0 0 {name=MP1 W=2 L=0.15 nf=1 mult=1 model=pfet_01v8 spiceprefix=X}
C {sky130_fd_pr/pfet_01v8.sym} 200 -200 0 0 {name=MP2 W=2 L=0.15 nf=1 mult=1 model=pfet_01v8 spiceprefix=X}
C {sky130_fd_pr/nfet_01v8.sym} 400 0 0 0 {name=MNF W=2 L=0.15 nf=1 mult=1 model=nfet_01v8 spiceprefix=X}
C {sky130_fd_pr/pfet_01v8.sym} 400 -200 0 0 {name=MPH W=4 L=0.15 nf=1 mult=1 model=pfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 20 -30 0 0 {name=l1 sig_type=std_logic lab=rbl}
C {devices/lab_pin.sym} -20 0 0 0 {name=l2 sig_type=std_logic lab=ref}
C {devices/lab_pin.sym} 20 30 0 0 {name=l3 sig_type=std_logic lab=vn}
C {devices/gnd.sym} 20 0 0 0 {name=lg4 lab=GND}
C {devices/lab_pin.sym} 220 -30 0 0 {name=l5 sig_type=std_logic lab=ref}
C {devices/lab_pin.sym} 180 0 0 0 {name=l6 sig_type=std_logic lab=rbl}
C {devices/lab_pin.sym} 220 30 0 0 {name=l7 sig_type=std_logic lab=vn}
C {devices/gnd.sym} 220 0 0 0 {name=lg8 lab=GND}
C {devices/lab_pin.sym} 20 -170 0 0 {name=l9 sig_type=std_logic lab=rbl}
C {devices/lab_pin.sym} -20 -200 0 0 {name=l10 sig_type=std_logic lab=ref}
C {devices/lab_pin.sym} 20 -230 0 0 {name=l11 sig_type=std_logic lab=vp}
C {devices/lab_pin.sym} 20 -200 0 0 {name=l12 sig_type=std_logic lab=vdd}
C {devices/lab_pin.sym} 220 -170 0 0 {name=l13 sig_type=std_logic lab=ref}
C {devices/lab_pin.sym} 180 -200 0 0 {name=l14 sig_type=std_logic lab=rbl}
C {devices/lab_pin.sym} 220 -230 0 0 {name=l15 sig_type=std_logic lab=vp}
C {devices/lab_pin.sym} 220 -200 0 0 {name=l16 sig_type=std_logic lab=vdd}
C {devices/lab_pin.sym} 420 -30 0 0 {name=l17 sig_type=std_logic lab=vn}
C {devices/lab_pin.sym} 380 0 0 0 {name=l18 sig_type=std_logic lab=en}
C {devices/gnd.sym} 420 30 0 0 {name=lg19 lab=GND}
C {devices/gnd.sym} 420 0 0 0 {name=lg20 lab=GND}
C {devices/lab_pin.sym} 420 -170 0 0 {name=l21 sig_type=std_logic lab=vp}
C {devices/lab_pin.sym} 380 -200 0 0 {name=l22 sig_type=std_logic lab=enb}
C {devices/lab_pin.sym} 420 -230 0 0 {name=l23 sig_type=std_logic lab=vdd}
C {devices/lab_pin.sym} 420 -200 0 0 {name=l24 sig_type=std_logic lab=vdd}
C {devices/iopin.sym} -100 -30 0 0 {name=p_rbl lab=rbl}
C {devices/iopin.sym} -100 30 0 0 {name=p_ref lab=ref}
C {devices/ipin.sym} -100 90 0 0 {name=p_en lab=en}
C {devices/ipin.sym} -100 150 0 0 {name=p_enb lab=enb}
C {devices/iopin.sym} -100 210 0 0 {name=p_vdd lab=vdd}
C {devices/title.sym} 0 -260 0 0 {name=l_title author="2AM Logic (issue #109: sense latch, provisional first-pass sizes)"}
