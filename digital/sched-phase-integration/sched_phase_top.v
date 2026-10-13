// Integration DUT (issue #135): refresh_sched_rt -> launch_adapter -> phase_seq.
// Behavioral only; both production modules are instantiated unchanged.
module sched_phase_top #(
    parameter integer N_ROWS = 32, T_ROW = 34, T_ACC = 34, INTERVAL = 5029, GUARD = 2,
    parameter integer P_PRE = 2, P_SENSE = 10, P_WB = 20, P_GUARD = 2, GAP = 0,
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
    // scheduler side
    output wire             op_busy,
    output wire             op_is_refresh,
    output wire             op_is_write,
    output wire [ROW_W-1:0] op_row,
    output wire             op_done,
    output wire             sweep_active,
    output wire             cfg_reject,
    // adapter
    output wire             a_start,
    output wire [1:0]       a_kind,
    output wire [ROW_W-1:0] a_row,
    // sequencer side
    output wire             q_busy,
    output wire             q_done,
    output wire             q_ign,
    output wire             pre_en, rwl_sel, sense_en, wwl_en, bl_drive,
    output wire [ROW_W-1:0] q_row
);
    refresh_sched_rt #(.N_ROWS(N_ROWS), .T_ROW(T_ROW), .T_ACC(T_ACC), .INTERVAL(INTERVAL), .GUARD(GUARD)) u_sched (
        .clk(clk), .rst_n(rst_n),
        .req_valid(req_valid), .req_we(req_we), .req_row(req_row), .req_accept(req_accept),
        .op_busy(op_busy), .op_is_refresh(op_is_refresh), .op_is_write(op_is_write),
        .op_row(op_row), .op_done(op_done),
        .cfg_valid(cfg_valid), .cfg_en(cfg_en), .cfg_interval(cfg_interval), .cfg_sweep(cfg_sweep),
        .en_eff(), .ivl_eff(), .sweep_active(sweep_active), .sweep_done(),
        .refresh_ok(), .data_lost(), .cfg_reject(cfg_reject));

    launch_adapter #(.ROW_W(ROW_W), .MUT(MUT), .MUT_N(MUT_N)) u_adapt (
        .clk(clk), .rst_n(rst_n), .op_busy(op_busy), .op_is_refresh(op_is_refresh),
        .op_is_write(op_is_write), .op_row(op_row),
        .start(a_start), .kind(a_kind), .row(a_row));

    phase_seq #(.P_PRE(P_PRE), .P_SENSE(P_SENSE), .P_WB(P_WB), .P_GUARD(P_GUARD), .GAP(GAP), .ROW_W(ROW_W)) u_seq (
        .clk(clk), .rst_n(rst_n), .start(a_start), .kind(a_kind), .row(a_row),
        .busy(q_busy), .done(q_done), .start_ignored(q_ign),
        .pre_en(pre_en), .rwl_sel(rwl_sel), .sense_en(sense_en),
        .wwl_en(wwl_en), .bl_drive(bl_drive), .row_q(q_row));
endmodule
