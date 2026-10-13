`timescale 1ns/1ps
// Self-checking testbench for spi_slave (issue #83). Prints TB_RESULT: PASS/FAIL.
module tb_spi_slave #(
    parameter integer MAX_INTERVAL    // no default: supplied by run_tests.sh from params.py
);
    localparam H = 50;
    reg rst_n = 1, sclk = 0, cs_n = 1, mosi = 0, busy_in = 0;
    wire miso, refresh_en, sweep_tog, err_any;
    wire [15:0] interval;
    spi_slave #(.MAX_INTERVAL(MAX_INTERVAL)) dut(.rst_n(rst_n), .sclk(sclk), .cs_n(cs_n),
        .mosi(mosi), .miso(miso), .busy_in(busy_in), .refresh_en(refresh_en),
        .interval(interval), .sweep_tog(sweep_tog), .err_any(err_any));

    integer errors = 0, checks = 0;
    reg [15:0] rd;
    task check(input [255:0] name, input [31:0] got, input [31:0] exp);
        begin checks = checks + 1;
            if (got !== exp) begin errors = errors + 1;
                $display("FAIL %0s: got %0h expected %0h", name, got, exp); end
        end
    endtask

    // raw frame: nbits clocks of 'word' MSB first; rd collects MISO sampled at rising edges
    task raw(input [15:0] word, input integer nbits);
        integer i;
        begin
            rd = 0; cs_n = 0; #H;
            for (i = 0; i < nbits; i = i + 1) begin
                mosi = (i < 16) ? word[15-i] : 1'b0;
                #H sclk = 1; if (i < 16) rd[15-i] = miso; #H sclk = 0;
            end
            #H cs_n = 1; mosi = 0; #(2*H);
        end
    endtask
    task wr(input [6:0] a, input [7:0] d); raw({1'b1, a, d}, 16); endtask
    task rdr(input [6:0] a, output [7:0] d); begin raw({1'b0, a, 8'h00}, 16); d = rd[7:0]; end endtask
    reg [7:0] v;
    task rchk(input [255:0] name, input [6:0] a, input [7:0] exp);
        begin rdr(a, v); check(name, v, exp); end
    endtask
    localparam A_ID=0, A_CTRL=1, A_CMD=2, A_IL=3, A_IH=4, A_ST=5;
    task setivl(input [15:0] x); begin wr(A_IL, x[7:0]); wr(A_IH, x[15:8]); end endtask

    reg [15:0] prev; reg tog0;
    initial begin
        #(2*H) rst_n = 0; #(2*H) rst_n = 1; #(2*H);
        // 1. reset defaults
        rchk("id", A_ID, 8'hA5);
        rchk("ctrl_rst", A_CTRL, 8'h01);
        check("ivl_rst", interval, MAX_INTERVAL);
        rchk("ivl_l_rst", A_IL, MAX_INTERVAL[7:0]);
        rchk("ivl_h_rst", A_IH, MAX_INTERVAL[15:8]);
        rchk("status_rst", A_ST, 8'h00);
        // 2. round trip
        wr(A_CTRL, 8'h00); rchk("ctrl_rt0", A_CTRL, 8'h00); check("refresh_en0", refresh_en, 0);
        wr(A_CTRL, 8'hFF); rchk("ctrl_rt1", A_CTRL, 8'h01); check("refresh_en1", refresh_en, 1);
        setivl(16'd1000); check("ivl_1000", interval, 1000);
        rchk("ivl_l_1000", A_IL, 8'(1000 & 255)); rchk("ivl_h_1000", A_IH, 8'(1000 >> 8));
        setivl(1); check("ivl_min", interval, 1);
        setivl(MAX_INTERVAL); check("ivl_max_ok", interval, MAX_INTERVAL);
        rchk("status_clean_after_valid", A_ST, 8'h00); check("err_any_clean", err_any, 0);
        // 3. bound: max+1 and zero rejected, prior value kept, flagged
        setivl(1234);
        setivl(MAX_INTERVAL + 1);
        check("ivl_over_rejected", interval, 1234);
        rchk("err_range", A_ST, 8'h01); check("err_any_set", err_any, 1);
        setivl(0); check("ivl_zero_rejected", interval, 1234);
        setivl(16'hFFFF); check("ivl_ffff_rejected", interval, 1234);
        // sticky until cleared; valid write does not clear
        setivl(2000); check("ivl_2000", interval, 2000);
        rchk("err_sticky", A_ST, 8'h01);
        wr(A_CMD, 8'h02); rchk("err_cleared", A_ST, 8'h00); check("err_any_cleared", err_any, 0);
        // 4. sequencing: L alone does not change the committed interval
        wr(A_IL, 8'h07); check("l_only_no_commit", interval, 2000);
        rchk("l_readback_committed", A_IL, 8'(2000 & 255));
        wr(A_IH, 8'h00); check("h_commits_pair", interval, 7);
        // rejected commit must not leave a poisoned shadow
        wr(A_IL, 8'hFF); wr(A_IH, 8'hFF); check("bad_pair", interval, 7);
        wr(A_IH, 8'h00); check("no_poisoned_shadow", interval, 7);
        wr(A_CMD, 8'h02);
        // start-sweep command
        tog0 = sweep_tog; wr(A_CMD, 8'h01); check("sweep_toggled", sweep_tog, {31'b0, ~tog0});
        rchk("status_idle", A_ST, 8'h00);
        busy_in = 1; tog0 = sweep_tog; wr(A_CMD, 8'h01);
        check("sweep_busy_no_toggle", sweep_tog, tog0);
        rchk("status_busy_err", A_ST, 8'h88);
        busy_in = 0; wr(A_CMD, 8'h02); rchk("busy_err_cleared", A_ST, 8'h00);
        wr(A_CMD, 8'h55); rchk("bad_cmd", A_ST, 8'h10); wr(A_CMD, 8'h02);
        rchk("cmd_reads_zero", A_CMD, 8'h00);
        // 5. access errors
        wr(A_ID, 8'h00); rchk("id_ro", A_ID, 8'hA5); rchk("ro_write_flag", A_ST, 8'h04);
        wr(A_CMD, 8'h02);
        wr(7'h7F, 8'h12); rchk("unk_write_flag", A_ST, 8'h04); wr(A_CMD, 8'h02);
        rchk("unk_read_zero", 7'h40, 8'h00); rchk("unk_read_flag", A_ST, 8'h04); wr(A_CMD, 8'h02);
        wr(A_ST, 8'hFF); rchk("status_ro", A_ST, 8'h04); wr(A_CMD, 8'h02);
        // 6. malformed frames: no state change, ERR_FRAME
        prev = interval;
        raw({1'b1, 7'(A_CTRL), 8'h00}, 15); check("short15_no_wr", refresh_en, 1);
        rchk("frame_err_15", A_ST, 8'h02); wr(A_CMD, 8'h02);
        raw({1'b1, 7'(A_CTRL), 8'h00}, 17); check("long17_no_wr", refresh_en, 1);
        rchk("frame_err_17", A_ST, 8'h02); wr(A_CMD, 8'h02);
        raw({1'b1, 7'(A_IH), 8'h00}, 8); check("short8_no_wr", interval, prev);
        rchk("frame_err_8", A_ST, 8'h02); wr(A_CMD, 8'h02);
        tog0 = sweep_tog; raw({1'b1, 7'(A_CMD), 8'h01}, 24); check("long24_no_cmd", sweep_tog, {31'b0, tog0});
        rchk("frame_err_24", A_ST, 8'h02); wr(A_CMD, 8'h02);
        // a start-sweep in a malformed frame must not toggle
        tog0 = sweep_tog; raw({1'b1, 7'(A_CMD), 8'h01}, 12); check("short_cmd_no_toggle", sweep_tog, tog0);
        wr(A_CMD, 8'h02);
        // chip select glitch with zero clocks is not a frame
        cs_n = 0; #H cs_n = 1; #H; rchk("zero_clock_no_err", A_ST, 8'h00);
        // aborted frame followed by good frame
        raw(16'hFFFF, 5); wr(A_CMD, 8'h02); wr(A_CTRL, 8'h00); check("recovers", refresh_en, 0);
        // MISO high-Z when deselected
        check("miso_hiz", miso === 1'bz, 1);
        // 7. async reset restores defaults
        setivl(500); wr(A_CMD, 8'h55);
        #H rst_n = 0; #H rst_n = 1; #H;
        check("rst_ivl", interval, MAX_INTERVAL); check("rst_en", refresh_en, 1);
        rchk("rst_status", A_ST, 8'h00);
        $display("checks=%0d errors=%0d MAX_INTERVAL=%0d", checks, errors, MAX_INTERVAL);
        $display("TB_RESULT: %0s", (errors == 0) ? "PASS" : "FAIL");
        $finish;
    end
    initial begin #50000000; $display("TB_RESULT: FAIL (timeout)"); $finish; end
endmodule
