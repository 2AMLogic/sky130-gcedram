// Coupled integration DUT (issue #138): refresh_sched_rt -> launch_adapter ->
// phase_seq, with the scheduler fixed budgets T_ROW / T_ACC DERIVED from the
// configured sequencer phase durations plus the launch/registration latency.
// Behavioral only; all three modules are instantiated unchanged. The
// standalone defaults (T_ROW = T_ACC = 34) and the uncoupled #135 harness
// (sched_phase_top.v) are retained as characterization controls.
//
// Derivation (cycles; 1 cycle = 1 ns is an ASSUMPTION inherited from the scheduler):
//   D_REF = P_PRE + P_SENSE + P_WB + P_GUARD + 3*GAP     REFRESH sequencer busy length
//   D_RD  = P_PRE + P_SENSE + P_GUARD + 2*GAP            READ
//   D_WR  = P_WB + P_GUARD + GAP                         WRITE
//   LAT   = 1   launch/registration latency: the adapter turns the first
//               op_busy cycle into start, phase_seq registers it, so its busy
//               rises one cycle after the scheduler's (MEASURED in #135,
//               TIMING_REPORT.md Sec. 1; re-measured every run by tb_coupled.v)
//   T_ROW = D_REF + LAT          scheduler completion (busy fall / op_done) is
//   T_ACC = max(D_RD, D_WR) + LAT  then at or after sequencer completion (done)
//   GUARD_C = GUARD + N_ROWS + 1   scheduler decision guard with the per-operation
//               decision cycle accounted. refresh_sched_rt spends one decision
//               cycle between operations (an op occupies T+1 cycles), so a
//               saturated back-to-back sweep takes N_ROWS*(T_ROW+1), not N_ROWS*T_ROW,
//               and one in-flight access can delay it by T_ACC+1. With the #74
//               guard (2) the floor N_ROWS*T_ROW + T_ACC + GUARD is only legal when
//               T_ACC + GUARD >= N_ROWS; the coupled durations (T_ACC 8..43 vs
//               N_ROWS 32) break that, and the bench measures a row-deadline miss
//               at the #74 floor (COUPLED_REPORT.md). GUARD_C restores a legal floor:
//                 MIN_INTERVAL = N_ROWS*T_ROW + T_ACC + GUARD_C
//                              = N_ROWS*(T_ROW+1) + (T_ACC+1) + GUARD
//               and shrinks the urgent/eager thresholds identically (conservative).
//               The scheduler RTL, policy and the standalone defaults are unchanged.
// T_ROW_X / T_ACC_X / GUARD_X (> 0) override the derived values. They exist only so
// the bench can build deliberately underbudgeted configurations (negative controls).
module coupled_top #(
    parameter integer N_ROWS = 32, INTERVAL = 5029, GUARD = 2,
    parameter integer P_PRE = 2, P_SENSE = 10, P_WB = 20, P_GUARD = 2, GAP = 0,
    parameter integer LAT = 1,
    parameter integer T_ROW_X = 0, T_ACC_X = 0, GUARD_X = 0,
    parameter integer MUT = 0, MUT_N = 7,
    parameter integer ROW_W = 5
) (
    input  wire             clk,
    input  wire             rst_n,
    input  wire             req_valid,
    input  wire             req_we,
    input  wire [ROW_W-1:0] req_row,
    output wire             req_accept,
    input  wire             cfg_valid,
    input  wire             cfg_en,
    input  wire [15:0]      cfg_interval,
    input  wire             cfg_sweep,
    output wire             op_busy,
    output wire             op_is_refresh,
    output wire             op_is_write,
    output wire [ROW_W-1:0] op_row,
    output wire             op_done,
    output wire             en_eff,
    output wire [15:0]      ivl_eff,
    output wire             sweep_active,
    output wire             sweep_done,
    output wire             refresh_ok,
    output wire             data_lost,
    output wire             cfg_reject,
    output wire             a_start,
    output wire [1:0]       a_kind,
    output wire [ROW_W-1:0] a_row,
    output wire             q_busy,
    output wire             q_done,
    output wire             q_ign,
    output wire             pre_en, rwl_sel, sense_en, wwl_en, bl_drive,
    output wire [ROW_W-1:0] q_row
);
    localparam integer D_REF   = P_PRE + P_SENSE + P_WB + P_GUARD + 3 * GAP;
    localparam integer D_RD    = P_PRE + P_SENSE + P_GUARD + 2 * GAP;
    localparam integer D_WR    = P_WB + P_GUARD + GAP;
    localparam integer D_ACC   = (D_RD > D_WR) ? D_RD : D_WR;
    localparam integer T_ROW_D = D_REF + LAT;
    localparam integer T_ACC_D = D_ACC + LAT;
    localparam integer T_ROW_E = (T_ROW_X > 0) ? T_ROW_X : T_ROW_D;
    localparam integer T_ACC_E = (T_ACC_X > 0) ? T_ACC_X : T_ACC_D;
    // runtime feasibility floor from the SAME effective durations (matches
    // refresh_sched_rt / gc_ctrl_top: N_ROWS*T_ROW + T_ACC + GUARD)
    localparam integer GUARD_C = (GUARD_X > 0) ? GUARD_X : GUARD + N_ROWS + 1;
    localparam integer MIN_IVL_E = N_ROWS * T_ROW_E + T_ACC_E + GUARD_C;
    // An infeasible combination (floor above the interval) is reported through
    // INFEASIBLE so the bench can reject it explicitly BEFORE traffic with a
    // non-zero result. The submodules are elaborated at a clamped interval only
    // so that their own elaboration-time $finish does not pre-empt that report.
    localparam integer INFEASIBLE = (MIN_IVL_E > INTERVAL) || (INTERVAL > 65535);
    localparam integer INTERVAL_S = INFEASIBLE ? MIN_IVL_E : INTERVAL;
    initial if (INFEASIBLE) $display("coupled_top: INFEASIBLE (floor %0d > INTERVAL %0d)", MIN_IVL_E, INTERVAL);

    refresh_sched_rt #(.N_ROWS(N_ROWS), .T_ROW(T_ROW_E), .T_ACC(T_ACC_E), .INTERVAL(INTERVAL_S), .GUARD(GUARD_C)) u_sched (
        .clk(clk), .rst_n(rst_n),
        .req_valid(req_valid), .req_we(req_we), .req_row(req_row), .req_accept(req_accept),
        .op_busy(op_busy), .op_is_refresh(op_is_refresh), .op_is_write(op_is_write),
        .op_row(op_row), .op_done(op_done),
        .cfg_valid(cfg_valid), .cfg_en(cfg_en), .cfg_interval(cfg_interval), .cfg_sweep(cfg_sweep),
        .en_eff(en_eff), .ivl_eff(ivl_eff), .sweep_active(sweep_active), .sweep_done(sweep_done),
        .refresh_ok(refresh_ok), .data_lost(data_lost), .cfg_reject(cfg_reject));

    launch_adapter #(.ROW_W(ROW_W), .MUT(MUT), .MUT_N(MUT_N)) u_adapt (
        .clk(clk), .rst_n(rst_n), .op_busy(op_busy), .op_is_refresh(op_is_refresh),
        .op_is_write(op_is_write), .op_row(op_row),
        .start(a_start), .kind(a_kind), .row(a_row));

    phase_seq #(.P_PRE(P_PRE), .P_SENSE(P_SENSE), .P_WB(P_WB), .P_GUARD(P_GUARD), .GAP(GAP), .ROW_W(ROW_W)) u_seq (
        .clk(clk), .rst_n(rst_n), .start(a_start), .kind(a_kind), .row(a_row),
        .busy(q_busy), .done(q_done), .start_ignored(q_ign),
        .pre_en(pre_en), .rwl_sel(rwl_sel), .sense_en(sense_en),
        .wwl_en(wwl_en), .bl_drive(bl_drive), .row_q(q_row));

    // The SPI path (gc_ctrl_top / spi_slave) takes its floor from the same
    // effective durations. It is instantiated here only so the bench can compare
    // its elaborated MIN_INTERVAL with the independently derived floor; its
    // external pins are tied off and its op outputs are unused.
    wire spi_unused_miso;
    gc_ctrl_top #(.N_ROWS(N_ROWS), .T_ROW(T_ROW_E), .T_ACC(T_ACC_E), .INTERVAL(INTERVAL_S), .GUARD(GUARD_C)) u_ctrl_floor (
        .rst_n(rst_n), .clk(clk), .sclk(1'b0), .cs_n(1'b1), .mosi(1'b0), .miso(spi_unused_miso),
        .req_valid(1'b0), .req_we(1'b0), .req_row({ROW_W{1'b0}}), .req_accept(),
        .op_busy(), .op_is_refresh(), .op_is_write(), .op_row(), .op_done(),
        .en_eff(), .ivl_eff(), .sweep_active(), .sweep_done(),
        .refresh_ok(), .data_lost(), .cfg_reject(), .busy());
endmodule
