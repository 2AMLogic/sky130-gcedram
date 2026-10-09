// Lockstep equivalence bench (issue #93): refresh_sched_rt with its
// configuration port idle (cfg_valid = 0) must be cycle-for-cycle identical to
// the unchanged #74 refresh_sched on every #74 output, under the #74 traffic
// scenarios (0 idle, 1 saturating reads, 2 seeded random). This is what ties
// the integration's scheduler core back to the #74 evidence.
`timescale 1ns/1ps
module tb_equiv;
    parameter integer N_ROWS = 32;
    parameter integer T_ROW = 34;
    parameter integer T_ACC = 34;
    parameter integer GUARD = 2;
    parameter integer INTERVAL = 5029;
    parameter integer SCENARIO = 0;
    parameter integer SEED = 32'h1badcafe;
    parameter integer N_INTERVALS = 12;
    localparam integer ROW_W = (N_ROWS > 1) ? $clog2(N_ROWS) : 1;
    localparam integer SIM_CYCLES = N_INTERVALS * INTERVAL;

    reg clk = 0, rst_n = 0;
    always #0.5 clk = ~clk;

    reg req_valid = 0, req_we = 0; reg [ROW_W-1:0] req_row = 0;
    wire g_acc, g_busy, g_ref, g_wr, g_done; wire [ROW_W-1:0] g_row;
    wire r_acc, r_busy, r_ref, r_wr, r_done; wire [ROW_W-1:0] r_row;
    wire r_en, r_sw, r_swd, r_ok, r_lost, r_rej; wire [15:0] r_ivl;

    refresh_sched #(.N_ROWS(N_ROWS), .T_ROW(T_ROW), .T_ACC(T_ACC), .INTERVAL(INTERVAL), .GUARD(GUARD))
        gold (.clk(clk), .rst_n(rst_n), .req_valid(req_valid), .req_we(req_we), .req_row(req_row),
              .req_accept(g_acc), .op_busy(g_busy), .op_is_refresh(g_ref), .op_is_write(g_wr),
              .op_row(g_row), .op_done(g_done));
    refresh_sched_rt #(.N_ROWS(N_ROWS), .T_ROW(T_ROW), .T_ACC(T_ACC), .INTERVAL(INTERVAL), .GUARD(GUARD))
        rt (.clk(clk), .rst_n(rst_n), .req_valid(req_valid), .req_we(req_we), .req_row(req_row),
            .req_accept(r_acc), .op_busy(r_busy), .op_is_refresh(r_ref), .op_is_write(r_wr),
            .op_row(r_row), .op_done(r_done),
            .cfg_valid(1'b0), .cfg_en(1'b1), .cfg_interval(16'd0), .cfg_sweep(1'b0),
            .en_eff(r_en), .ivl_eff(r_ivl), .sweep_active(r_sw), .sweep_done(r_swd),
            .refresh_ok(r_ok), .data_lost(r_lost), .cfg_reject(r_rej));

    // ---- traffic: same generator as tb_refresh_sched.v (#74) ----
    reg [31:0] rng;
    function [31:0] xs(input [31:0] s);
        reg [31:0] x; begin
            x = s; x = x ^ (x << 13); x = x ^ (x >> 17); x = x ^ (x << 5); xs = x;
        end
    endfunction
    integer sat_rowctr = 0, cyc = 0;
    reg [1:0] phase = 0;
    always @(posedge clk) if (rst_n) begin
        rng <= xs(rng);
        if (cyc % 1500 == 0) phase <= rng[9:8];
    end
    always @(posedge clk) if (rst_n) begin
        if (g_acc) req_valid <= 0;
        else if (!req_valid) begin
            case (SCENARIO)
              0: req_valid <= 0;
              1: begin req_valid <= 1; req_we <= 0; req_row <= sat_rowctr % N_ROWS;
                       sat_rowctr <= sat_rowctr + 1; end
              default:
                       if ((phase == 0 && rng[5:0] == 0) || (phase == 1 && rng[2:0] == 0) || (phase >= 2)) begin
                           req_valid <= 1; req_we <= rng[7]; req_row <= rng[20:12] % N_ROWS;
                       end
            endcase
        end
    end

    integer mism = 0, n_ref = 0, n_ext = 0, n_ok_rise = 0;
    reg ok_q = 0;
    always @(negedge clk) if (rst_n) begin
        cyc = cyc + 1;
        if ({g_acc, g_busy, g_ref, g_wr, g_done, g_row} !== {r_acc, r_busy, r_ref, r_wr, r_done, r_row}) begin
            if (mism < 5) $display("MISMATCH cycle %0d gold=%b rt=%b", cyc,
                {g_acc, g_busy, g_ref, g_wr, g_done, g_row}, {r_acc, r_busy, r_ref, r_wr, r_done, r_row});
            mism = mism + 1;
        end
        if (g_done && g_ref) n_ref = n_ref + 1;
        if (g_acc) n_ext = n_ext + 1;
        if (r_ok && !ok_q) n_ok_rise = n_ok_rise + 1;
        ok_q = r_ok;
        if (r_en !== 1'b1 || r_ivl !== INTERVAL || r_lost !== 1'b0 || r_rej !== 1'b0 || r_swd !== 1'b0) begin
            if (mism < 5) $display("MISMATCH cycle %0d: config state moved without cfg_valid", cyc);
            mism = mism + 1;
        end
    end

    initial begin
        rng = SEED;
        #5.2 rst_n = 1;
        repeat (SIM_CYCLES) @(posedge clk);
        #1;
        if (n_ref < (N_INTERVALS - 2) * N_ROWS) begin $display("LIVENESS: only %0d refreshes", n_ref); mism = mism + 1; end
        if (SCENARIO != 0 && n_ext == 0) begin $display("LIVENESS: no external op"); mism = mism + 1; end
        if (n_ok_rise != 1) begin $display("refresh_ok rose %0d times (expected once, after the init sweep)", n_ok_rise); mism = mism + 1; end
        $display("EQUIV scenario=%0d INTERVAL=%0d cycles=%0d refreshes=%0d ext_ops=%0d mismatches=%0d",
                 SCENARIO, INTERVAL, cyc, n_ref, n_ext, mism);
        if (mism == 0) $display("TB_RESULT: PASS"); else $display("TB_RESULT: FAIL (%0d)", mism);
        $finish;
    end
endmodule
