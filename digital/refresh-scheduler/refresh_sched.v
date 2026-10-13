// Behavioral refresh scheduler (issue #74, part of epic #24 item 3).
//
// NOT synthesis, NOT a macro claim. A gain-cell array is dynamic; this model
// only checks that a controller CAN keep every row inside the ratified refresh
// interval (spec/retention-refresh-budget.md Section 7) while external
// accesses compete. It is not an SRAM-replacement controller.
//
// Policy (lazy, deadline-driven, round-robin):
//   * one op at a time (refresh or external), non-preemptible;
//   * rows are refreshed in order 0,1,..,N-1,0,..; the pointer row is always
//     the oldest row (by refresh timestamp);
//   * the pointer row is "urgent" when starting an external access now could
//     push its refresh past INTERVAL; urgent refresh beats external requests;
//   * after reset one initialisation sweep refreshes every row once, so the
//     'pointer row is oldest' ordering holds from then on (array contents
//     are assumed written by that sweep; the testbench starts all ages at 0);
//   * when no external request is pending, refresh starts "eagerly" once the
//     pointer row is old enough that a full back-to-back pass still fits.
// Conservative: external writes are NOT credited as refreshes by the
// scheduler (the testbench monitor does credit them, independently).
//
// All times are in clock cycles. 1 cycle = 1 ns is an ASSUMPTION of the
// surrounding README, not of this module.
module refresh_sched #(
    parameter integer N_ROWS   = 32,    // ASSUMPTION (array not designed)
    parameter integer T_ROW    = 34,    // ASSUMPTION t_row_refresh_op, cycles
    parameter integer T_ACC    = 34,    // ASSUMPTION external op duration
    parameter integer INTERVAL = 5029,  // spec Sec.7 interval, cycles (floored)
    parameter integer GUARD    = 2,     // decision-latency guard, cycles
    parameter integer ROW_W    = (N_ROWS > 1) ? $clog2(N_ROWS) : 1
) (
    input  wire             clk,
    input  wire             rst_n,
    // external request (hold until req_accept)
    input  wire             req_valid,
    input  wire             req_we,
    input  wire [ROW_W-1:0] req_row,
    output reg              req_accept,     // 1-cycle pulse: ext op started
    // array-side operation
    output reg              op_busy,
    output reg              op_is_refresh,
    output reg              op_is_write,
    output reg [ROW_W-1:0]  op_row,
    output reg              op_done         // 1-cycle pulse: op complete
);
    localparam integer URGENT_AGE = INTERVAL - T_ROW - T_ACC - GUARD;
    localparam integer EAGER_AGE  = INTERVAL - (N_ROWS * T_ROW) - T_ACC - GUARD;

    // elaboration-time feasibility check (N_rows*t_row must fit the interval)
    initial if (EAGER_AGE < 0 || URGENT_AGE < 0) begin
        $display("refresh_sched: INFEASIBLE parameters (N_ROWS*T_ROW+T_ACC+GUARD >= INTERVAL)");
        $finish;
    end

    reg [31:0]        now;
    reg [31:0]        last_ref [0:N_ROWS-1];
    reg [ROW_W-1:0]   ptr;
    reg [31:0]        cnt;
    reg               init_done;   // reset triggers one initialisation sweep
    integer           i;

    wire [31:0] age     = now - last_ref[ptr];
    wire        urgent  = !init_done || (age >= URGENT_AGE);
    wire        eager   = !req_valid && (age >= EAGER_AGE);    // MUT_EAGER

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            now <= 0; ptr <= 0; cnt <= 0; init_done <= 0;
            op_busy <= 0; op_done <= 0; req_accept <= 0;
            op_is_refresh <= 0; op_is_write <= 0; op_row <= 0;
            for (i = 0; i < N_ROWS; i = i + 1) last_ref[i] <= 0;
        end else begin
            now        <= now + 1;
            op_done    <= 0;
            req_accept <= 0;
            if (op_busy) begin
                cnt <= cnt - 1;
                if (cnt == 1) begin
                    op_busy <= 0;
                    op_done <= 1;
                    if (op_is_refresh) begin
                        last_ref[op_row] <= now;
                        ptr <= (ptr == N_ROWS-1) ? 0 : ptr + 1;    // MUT_PTR
                        if (ptr == N_ROWS-1) init_done <= 1;
                    end
                end
            end else if (urgent || eager) begin
                op_busy <= 1; op_is_refresh <= 1; op_is_write <= 0;
                op_row <= ptr; cnt <= T_ROW;
            end else if (req_valid) begin
                op_busy <= 1; op_is_refresh <= 0; op_is_write <= req_we;
                op_row <= req_row; cnt <= T_ACC; req_accept <= 1;
            end
        end
    end
endmodule
