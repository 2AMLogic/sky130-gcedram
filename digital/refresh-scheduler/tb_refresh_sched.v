// Self-checking testbench for refresh_sched (issue #74).
// Invariant (independent monitor, credits refreshes AND external writes):
//   for every row, cycles since its last write/refresh completion <= INTERVAL.
// SCENARIO 0 idle, 1 saturating back-to-back reads, 2 seeded random traffic.
`timescale 1ns/1ps
module tb_refresh_sched;
    parameter integer N_ROWS = 32;
    parameter integer T_ROW = 34;
    parameter integer T_ACC = 34;
    parameter integer INTERVAL = 5029;
    parameter integer SCENARIO = 0;
    parameter integer SEED = 32'h1badcafe;
    parameter integer N_INTERVALS = 12;
    localparam integer ROW_W = (N_ROWS > 1) ? $clog2(N_ROWS) : 1;
    localparam integer SIM_CYCLES = N_INTERVALS * INTERVAL;

    reg clk = 0, rst_n = 0;
    always #0.5 clk = ~clk;   // 1 cycle = 1 ns (ASSUMPTION)

    reg req_valid = 0, req_we = 0; reg [ROW_W-1:0] req_row = 0;
    wire req_accept, op_busy, op_is_refresh, op_is_write, op_done;
    wire [ROW_W-1:0] op_row;

    refresh_sched #(.N_ROWS(N_ROWS), .T_ROW(T_ROW), .T_ACC(T_ACC), .INTERVAL(INTERVAL))
        dut (.clk(clk), .rst_n(rst_n), .req_valid(req_valid), .req_we(req_we),
             .req_row(req_row), .req_accept(req_accept), .op_busy(op_busy),
             .op_is_refresh(op_is_refresh), .op_is_write(op_is_write),
             .op_row(op_row), .op_done(op_done));

    // ---- seeded xorshift32 (tool-independent determinism) ----
    reg [31:0] rng;
    function [31:0] xs(input [31:0] s);
        reg [31:0] x; begin
            x = s; x = x ^ (x << 13); x = x ^ (x >> 17); x = x ^ (x << 5); xs = x;
        end
    endfunction

    // ---- traffic master ----
    integer wait_cnt = 0, max_stall = 0, n_ext = 0, n_ref = 0, busy_ref = 0;
    integer sat_rowctr = 0;
    reg [1:0] phase = 0;
    integer cyc = 0;
    // free-running PRNG and load-phase selector (every cycle, so traffic is
    // independent of when the previous request was accepted)
    always @(posedge clk) if (rst_n) begin
        rng <= xs(rng);
        if (cyc % 1500 == 0) phase <= rng[9:8];
    end
    always @(posedge clk) if (rst_n) begin
        if (req_valid && !req_accept) wait_cnt <= wait_cnt + 1;
        if (req_accept) begin
            // accept pulse is visible the cycle after the op started
            n_ext <= n_ext + 1;
            if (wait_cnt > max_stall) max_stall <= wait_cnt;
            wait_cnt <= 0; req_valid <= 0;
        end else if (!req_valid) begin
            case (SCENARIO)
              0: req_valid <= 0;
              1: begin req_valid <= 1; req_we <= 0; req_row <= sat_rowctr % N_ROWS;
                       sat_rowctr <= sat_rowctr + 1; end
              default: begin
                       // bursty seeded traffic: the load phase changes every 1500 cycles
                       if ((phase == 0 && rng[5:0] == 0) ||     // light  (~1/64 per cycle)
                           (phase == 1 && rng[2:0] == 0) ||     // medium (~1/8)
                           (phase >= 2))                        // saturating bursts
                       begin
                           req_valid <= 1; req_we <= rng[7]; req_row <= rng[20:12] % N_ROWS;
                       end
                       end
            endcase
        end
    end

    // ---- independent deadline monitor (negedge sampling) ----
    integer age [0:N_ROWS-1];
    integer max_age = 0, errors = 0, k, overlap_err = 0;
    always @(negedge clk) if (rst_n) begin
        cyc = cyc + 1;
        for (k = 0; k < N_ROWS; k = k + 1) age[k] = age[k] + 1;
        if (op_done && (op_is_refresh || op_is_write)) begin
            age[op_row] = 0;
            if (op_is_refresh) n_ref = n_ref + 1;
        end
        if (op_busy && op_is_refresh) busy_ref = busy_ref + 1;
        for (k = 0; k < N_ROWS; k = k + 1) begin
            if (age[k] > max_age) max_age = age[k];
            if (age[k] > INTERVAL) begin
                if (errors < 5) $display("VIOLATION row %0d age %0d > %0d at cycle %0d", k, age[k], INTERVAL, cyc);
                errors = errors + 1;
            end
        end
    end
    // protocol check: an accept must coincide with a started external op
    always @(negedge clk) if (rst_n && req_accept && (!op_busy || op_is_refresh)) overlap_err = overlap_err + 1;

    integer j;
    initial begin
        rng = SEED;
        for (j = 0; j < N_ROWS; j = j + 1) age[j] = 0;   // array assumed initialised at reset
        #5.2 rst_n = 1;
        repeat (SIM_CYCLES) @(posedge clk);
        #1;
        // liveness guards against vacuous passes
        if (n_ref < (N_INTERVALS - 2) * N_ROWS) begin
            $display("LIVENESS: only %0d refreshes completed", n_ref); errors = errors + 1;
        end
        if (SCENARIO != 0 && n_ext == 0) begin
            $display("LIVENESS: no external access ever served"); errors = errors + 1;
        end
        errors = errors + overlap_err;
        $display("RESULT scenario=%0d N=%0d T_ROW=%0d T_ACC=%0d INTERVAL=%0d cycles=%0d refreshes=%0d ext_ops=%0d max_age=%0d slack=%0d max_stall=%0d refresh_busy_pct=%0d.%02d",
                 SCENARIO, N_ROWS, T_ROW, T_ACC, INTERVAL, cyc, n_ref, n_ext, max_age,
                 INTERVAL - max_age, max_stall,
                 (busy_ref * 100) / cyc, ((busy_ref * 10000) / cyc) % 100);
        if (errors == 0) $display("TB_RESULT: PASS"); else $display("TB_RESULT: FAIL (%0d errors)", errors);
        $finish;
    end
endmodule
