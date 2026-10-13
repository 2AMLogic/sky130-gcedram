// Protocol testbench for the PROPOSED SPI crossing (issue #157). Deterministic,
// no random numbers. Parameters: SHALF_PS (sclk half period, ps), PHASE_PS
// (master start offset vs the 1 ns clk), GAP_CLK (cs_n high between frames, clk
// periods), NEG (1 = negative control, ack/reservation omitted).
// Prints "TB_RESULT: PASS" or "TB_RESULT: FAIL errors=N". Error lines start
// with LOSS / DUP / STALE / MISMATCH / BUSY_GAP / BUSY_STUCK / TORN / RESET /
// REFUSE / LATENCY.
`timescale 1ns/1ps
module tb_xing;
    parameter integer SHALF_PS = 3700;
    parameter integer PHASE_PS = 130;
    parameter integer GAP_CLK  = 4;
    parameter integer NEG      = 0;

    reg clk = 0, rst_n = 1, sclk = 0, cs_n = 1, mosi = 0;
    wire miso;
    always #0.5 clk = ~clk;

    xing_top #(.NOACK(NEG), .SW_LEN(40)) dut (.rst_n(rst_n), .clk(clk), .sclk(sclk), .cs_n(cs_n), .mosi(mosi), .miso(miso));

    integer errors = 0;
    integer sw_off = 0;   // sweeps cancelled by reset (never complete)
    integer b_acc = 0, b_app = 0, b_sw_acc = 0, b_start = 0, b_done = 0;
    real half, gap_ns;     // runtime-changeable; T5 overrides both
    initial begin half = SHALF_PS / 1000.0; gap_ns = GAP_CLK * 1.0; end

    task err(input [639:0] tag, input integer a, input integer b);
        begin errors = errors + 1; $display("%0s a=%0d b=%0d t=%0t", tag, a, b, $time); end
    endtask

    // one SPI frame. nedges < 16 makes a short (aborted) frame. pause_at >= 0
    // stops sclk (low, cs_n low) for pause_clk clk periods after that many edges.
    reg [7:0] last_rd;
    task frame(input rw, input [6:0] addr, input [7:0] data, input integer nedges,
               input integer pause_at, input integer pause_clk);
        reg [15:0] w; integer i;
        begin
            w = {rw, addr, data}; last_rd = 8'h00;
            #(gap_ns);                 // cs_n already high; enforce the high-time obligation
            cs_n = 0; #(half);
            for (i = 0; i < nedges; i = i + 1) begin
                mosi = w[15 - i]; #(half);
                if (i >= 8) last_rd = {last_rd[6:0], miso};
                sclk = 1; #(half);
                sclk = 0;
                if (i + 1 == pause_at) #(pause_clk * 1.0);
            end
            #(half); cs_n = 1;
        end
    endtask

    task wr(input [6:0] a, input [7:0] d); frame(1'b1, a, d, 16, -1, 0); endtask
    task rdr(input [6:0] a);               frame(1'b0, a, 8'h00, 16, -1, 0); endtask

    // coherence check of an XSTATUS byte
    task chk_snap(input [7:0] s);
        begin
            if (s[1] !== ~s[7] || s[0] !== ^s[6:3]) err("TORN snapshot", s, 0);
        end
    endtask

    // exactly-once / atomicity scoreboard against the SPI-side accept log
    task settle; begin #(300.0); end endtask
    task base; begin
        b_acc = dut.u_spi.acc_cnt; b_app = dut.u_clk.n_applied; b_sw_acc = dut.u_spi.acc_sw;
        b_start = dut.u_clk.n_started; b_done = dut.u_clk.n_done; end endtask
    task check_exact(input [639:0] tag);
        integer i, na, nb;
        begin
            settle;
            na = dut.u_spi.acc_cnt - b_acc; nb = dut.u_clk.n_applied - b_app;
            if (nb < na) err("LOSS mailbox requests", na, nb);
            if (nb > na) err("DUP mailbox requests", na, nb);
            for (i = 0; i < ((na < nb) ? na : nb); i = i + 1)
                if (dut.u_spi.acc_log[b_acc + i] !== dut.u_clk.app_log[b_app + i])
                    err("STALE/MISMATCH bundle", i, 0);
            na = dut.u_spi.acc_sw - b_sw_acc;
            if ((dut.u_clk.n_started - b_start) < na) err("LOSS sweep start", na, dut.u_clk.n_started - b_start);
            if ((dut.u_clk.n_started - b_start) > na) err("DUP sweep start", na, dut.u_clk.n_started - b_start);
            if ((dut.u_clk.n_done - b_done) < na) err("LOSS sweep completion", na, dut.u_clk.n_done - b_done);
            if ((dut.u_clk.n_done - b_done) > na) err("DUP sweep completion", na, dut.u_clk.n_done - b_done);
            $display("  [%0s] accepted=%0d applied=%0d sweeps acc/start/done=%0d/%0d/%0d refused(total)=%0d",
                tag, dut.u_spi.acc_cnt - b_acc, dut.u_clk.n_applied - b_app, dut.u_spi.acc_sw - b_sw_acc,
                dut.u_clk.n_started - b_start, dut.u_clk.n_done - b_done, dut.u_spi.refuse_cnt);
            base;
        end
    endtask

    // measured commit -> applied latency (clk period is 1 ns, so ns == clk edges)
    real t_req = 0.0, lat_max = 0.0;
    reg  lat_exempt = 0;   // set only in NEG builds of T5, where commits overrun the clk side by design
    always @(dut.req_tog) t_req = $realtime;
    always @(dut.u_clk.n_applied) begin
        if ($realtime - t_req > lat_max) lat_max = $realtime - t_req;
        if ($realtime - t_req > 3.001 && !lat_exempt) err("LATENCY commit->applied exceeds 3 clk edges", $realtime - t_req, 0);
    end

    // universal monitor: a new START_SWEEP must never be accepted while an
    // earlier accepted one has not completed (stale-command acceptance)
    always @(dut.u_spi.acc_sw)
        if (dut.u_spi.acc_sw - dut.u_clk.n_done - sw_off > 1)
            err("STALE START_SWEEP accepted while previous outstanding", dut.u_spi.acc_sw, dut.u_clk.n_done + sw_off);

    // poll STATUS until BUSY clears; BUSY must never read 0 while a sweep is outstanding
    task poll_idle(input integer maxn);
        integer k; reg done;
        begin
            done = 0;
            for (k = 0; k < maxn && !done; k = k + 1) begin
                rdr(7'h05);
                if (!last_rd[7]) begin
                    if (dut.u_clk.n_done + sw_off != dut.u_spi.acc_sw) err("BUSY_GAP read 0 with sweep outstanding", dut.u_clk.n_done + sw_off, dut.u_spi.acc_sw);
                    done = 1;
                end
            end
            if (!done) err("BUSY_STUCK", maxn, 0);
        end
    endtask

    task cfg_retry(input [6:0] a, input [7:0] d);   // master retry discipline
        integer k; reg ok;
        begin
            ok = 0;
            for (k = 0; k < 8 && !ok; k = k + 1) begin
                wr(a, d); rdr(7'h05);
                if (last_rd[3]) wr(7'h02, 8'h02); else ok = 1;   // ERR_BUSY -> CLEAR_STATUS, retry
            end
            if (!ok) err("BUSY_STUCK cfg retry", a, 0);
        end
    endtask

    task do_reset(input integer dur_ns);
        begin sw_off = dut.u_spi.acc_sw - dut.u_clk.n_done; rst_n = 0; #(dur_ns * 1.0); rst_n = 1; #(10.0); end
    endtask

    integer j, a0, m0, mbx;
    reg [15:0] ivl0;
    initial begin
        #1.0; rst_n = 0; #(10.0); rst_n = 1; #(PHASE_PS / 1000.0 + 10.0);
        base;

        // T1: back-to-back configuration frames, no polling (refusals allowed)
        for (j = 0; j < 6; j = j + 1) begin
            wr(7'h01, j[0] ? 8'h01 : 8'h00);
            wr(7'h03, 8'h10 + j);
            wr(7'h04, 8'h08 + j);
        end
        check_exact("T1 back-to-back");
        // T1b: with retry discipline the final configuration is exactly the last intended one
        cfg_retry(7'h01, 8'h00); cfg_retry(7'h03, 8'h34); cfg_retry(7'h04, 8'h12);
        settle; rdr(7'h01);
        if (dut.u_clk.cfg_en !== 1'b0 || dut.u_clk.cfg_ivl !== 16'h1234) err("MISMATCH final cfg", dut.u_clk.cfg_ivl, dut.u_clk.cfg_en);
        cfg_retry(7'h01, 8'h01);
        check_exact("T1b retry");

        // T2: two START_SWEEP back to back, then poll; repeat 3 times
        for (j = 0; j < 3; j = j + 1) begin
            wr(7'h02, 8'h01); a0 = dut.u_spi.acc_sw;
            wr(7'h02, 8'h01);
            rdr(7'h05);                       // BUSY must be visible already
            if (!last_rd[7] && dut.u_clk.n_done + sw_off != dut.u_spi.acc_sw) err("BUSY_GAP right after START_SWEEP", 0, 0);
            poll_idle(400);
            check_exact("T2 sweep");
        end

        // T3: status transitions around reads: XSTATUS coherent on every read,
        // fresh within a bounded number of frames, BUSY does not flap.
        wr(7'h02, 8'h01);
        for (j = 0; j < 12; j = j + 1) begin rdr(7'h06); chk_snap(last_rd); end
        poll_idle(400);
        for (j = 0; j < 4; j = j + 1) begin rdr(7'h06); chk_snap(last_rd); end
        if (last_rd[2] !== 1'b0) err("STALE XSTATUS sweep_active after idle", last_rd, 0);
        if (last_rd[6:3] !== dut.u_clk.applied_cnt) err("STALE XSTATUS applied_cnt", last_rd[6:3], dut.u_clk.applied_cnt);
        for (j = 0; j < 4; j = j + 1) begin rdr(7'h05); if (last_rd[7]) err("BUSY_GAP flap after completion", j, 0); end
        check_exact("T3 status");

        // T4: stopped / restarted sclk
        //  (a) sclk stopped mid-frame, cs_n low, across several clk periods
        frame(1'b1, 7'h02, 8'h01, 16, 5, 300);
        poll_idle(400);
        frame(1'b1, 7'h01, 8'h00, 16, 11, 500);
        cfg_retry(7'h01, 8'h01);
        check_exact("T4a pause mid-frame");
        //  (b) sweep completes while sclk is stopped; first read afterwards is exact
        wr(7'h02, 8'h01);
        #(400.0);                             // no sclk edges for 400 clk periods
        rdr(7'h05);
        if (last_rd[7]) err("STALE BUSY after sclk stopped across completion", 1, 0);
        for (j = 0; j < 3; j = j + 1) begin rdr(7'h05); if (last_rd[7]) err("BUSY_GAP flap after restart", j, 0); end
        //  (c) config applied while sclk stopped, next frame sees ack
        wr(7'h01, 8'h00); #(400.0); wr(7'h01, 8'h01);
        check_exact("T4b/c stopped sclk");
        //  (d) aborted short frames produce no request
        frame(1'b1, 7'h02, 8'h01, 7, -1, 0); frame(1'b1, 7'h01, 8'h00, 15, -1, 0);
        check_exact("T4d aborted frames");

        // T5: VIOLATED ack-latency obligation (DESIGN.md Sec. 8.2) -> mailbox refusal.
        // sclk half period 50 ps and cs_n high 0.1 ns make one frame 1.8 ns,
        // commit to commit. The clk side cannot capture a request in under
        // 2 Tc (rq_s[0], rq_s[1], capture edge), so the mailbox commit that
        // immediately follows an accepted one ALWAYS finds req_tog != ack_s[1],
        // independently of PHASE_PS. The one after that has >= 5 sclk edges
        // after the ack and finds the mailbox free. Expected: commits A and B
        // accepted, the IVL_H and START_SWEEP commits refused BY THE MAILBOX
        // (sweep reservation is clear), ERR_BUSY set, bundle and applied
        // configuration untouched by the refused commits, exactly-once intact,
        // then the master's retry succeeds.
        wr(7'h02, 8'h02); settle; base;                     // clear ERR_BUSY, quiet start
        m0 = dut.u_spi.refuse_mbx; ivl0 = dut.u_spi.b_ivl;
        if (NEG) lat_exempt = 1;
        half = 0.05; gap_ns = 0.1;
        wr(7'h03, 8'h5A);                                   // SPI-local shadow, no mailbox
        wr(7'h01, 8'h00);                                   // A: accepted (mailbox free)
        wr(7'h04, 8'h77);                                   // A + 1.8 ns: mailbox occupied -> refused
        wr(7'h01, 8'h01);                                   // B: accepted (ack seen)
        wr(7'h02, 8'h01);                                   // B + 1.8 ns: START_SWEEP refused by the mailbox
        half = SHALF_PS / 1000.0; gap_ns = GAP_CLK * 1.0;
        #(0.05);                                            // let the last cs_n-rise commit evaluate
        mbx = dut.u_spi.refuse_mbx - m0;
        if (mbx != 2) err("REFUSE mailbox refusals at violated obligation (expected 2)", mbx, 2);
        if (dut.u_spi.b_ivl !== ivl0 || dut.u_spi.b_sw !== 1'b0 || dut.u_spi.b_en !== 1'b1)
            err("REFUSE refused commit altered the mailbox bundle", dut.u_spi.b_ivl, ivl0);
        if (dut.u_spi.acc_sw != b_sw_acc) err("REFUSE refused START_SWEEP was accepted", dut.u_spi.acc_sw, b_sw_acc);
        settle;
        if (dut.u_clk.cfg_ivl !== ivl0 || dut.u_clk.cfg_en !== 1'b1)
            err("REFUSE refused commit reached the clk domain", dut.u_clk.cfg_ivl, ivl0);
        rdr(7'h05); if (last_rd[3] !== 1'b1) err("REFUSE ERR_BUSY not set by mailbox refusal", last_rd, 0);
        check_exact("T5 violated obligation");
        lat_exempt = 0;
        wr(7'h02, 8'h02);                                   // CLEAR_STATUS, then master retry
        cfg_retry(7'h04, 8'h77); cfg_retry(7'h02, 8'h01); poll_idle(400);
        settle;
        if (dut.u_clk.cfg_ivl !== 16'h775A || dut.u_clk.cfg_en !== 1'b1) err("MISMATCH cfg after T5 retry", dut.u_clk.cfg_ivl, dut.u_clk.cfg_en);
        check_exact("T5 retry");
        $display("T5_MAILBOX_REFUSALS=%0d", mbx);

        // T6: reset while a transfer is pending or a sweep is running
        //  (i) START_SWEEP just committed (not yet consumed), reset immediately
        a0 = dut.u_clk.n_started;
        wr(7'h02, 8'h01); #(0.2); do_reset(5); #(100.0);
        if (dut.u_clk.n_started != a0 + 1 && dut.u_clk.n_started != a0) err("RESET stale start count", a0, dut.u_clk.n_started);
        if (dut.u_clk.sweep_active !== 1'b0 || dut.u_clk.sdone_tog !== 1'b0 || dut.u_spi.sw_tog !== 1'b0) err("RESET sweep not cancelled", 0, 0);
        base;
        rdr(7'h05); if (last_rd[7]) err("RESET busy after recovery", 0, 0);
        settle; if (dut.u_clk.n_applied != b_app) err("STALE command executed after reset", b_app, dut.u_clk.n_applied);
        wr(7'h02, 8'h01); poll_idle(400); check_exact("T6i recover");
        //  (ii) reset in the middle of a running sweep
        wr(7'h02, 8'h01); wait (dut.u_clk.sweep_active === 1'b1); #(10.0);
        do_reset(5); #(100.0);
        if (dut.u_clk.sweep_active !== 1'b0 || dut.u_spi.sw_tog !== 1'b0) err("RESET running sweep not cancelled", 0, 0);
        base;
        rdr(7'h05); if (last_rd[7]) err("RESET busy after mid-sweep recovery", 0, 0);
        wr(7'h02, 8'h01); poll_idle(400); check_exact("T6ii recover");
        //  (iii) pending configuration write cancelled
        wr(7'h01, 8'h00); #(0.2); do_reset(5); #(100.0);
        if (dut.u_clk.cfg_en !== 1'b1 || dut.u_spi.b_en !== 1'b1) err("RESET pending cfg survived", dut.u_clk.cfg_en, 0);
        base; cfg_retry(7'h01, 8'h00); check_exact("T6iii recover");

        $display("SUMMARY refused_commits=%0d mailbox_refusals=%0d accepted_total=%0d max_apply_clk_edges=%0.2f", dut.u_spi.refuse_cnt, dut.u_spi.refuse_mbx, dut.u_spi.acc_cnt, lat_max);
        if (errors == 0) $display("TB_RESULT: PASS");
        else $display("TB_RESULT: FAIL errors=%0d", errors);
        $finish;
    end

    initial begin #2000000.0; $display("TB_RESULT: FAIL timeout"); $finish; end
endmodule
