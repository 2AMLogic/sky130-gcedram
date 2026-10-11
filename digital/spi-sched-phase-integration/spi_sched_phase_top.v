// SPI-driven scheduler -> phase-sequencer integration DUT (issue #146).
// Behavioral only; PROPOSED; not synthesis, not CDC, not sign-off.
//
//   SPI pins --> gc_ctrl_top { spi_slave -> cfg_xfer -> refresh_sched_rt } --op_*-->
//   launch_adapter --start/kind/row--> phase_seq --> analog phase strobes
//
// The scheduler inside gc_ctrl_top is the ONLY scheduler: its operation
// interface drives the adapter and the sequencer directly. Every module is
// instantiated unchanged. coupled_top.v (#138) is left as it is; it drives the
// same adapter/sequencer from a runtime scheduler whose configuration comes
// from the cfg_* port, and keeps a tied-off gc_ctrl_top only to compare the
// floor. Here the configuration arrives through real SPI frames.
//
// Budgets are DERIVED exactly as in coupled_top.v (#138, COUPLED_REPORT.md):
//   D_REF = P_PRE+P_SENSE+P_WB+P_GUARD+3*GAP      D_RD = P_PRE+P_SENSE+P_GUARD+2*GAP
//   D_WR  = P_WB+P_GUARD+GAP                      LAT  = 1 (launch/registration)
//   T_ROW = D_REF+LAT   T_ACC = max(D_RD,D_WR)+LAT
//   GUARD_C = GUARD + N_ROWS + 1   (per-operation decision cycle accounted)
// gc_ctrl_top receives T_ROW, T_ACC and GUARD_C, so BOTH its scheduler and the
// SPI slave's commit floor (MIN_INTERVAL = N_ROWS*T_ROW + T_ACC + GUARD_C) use
// the effective values: the SPI feasibility floor is the coupled floor.
// T_ROW_X / T_ACC_X / GUARD_X (> 0) override the derived values for the bench's
// negative controls only. MUT/MUT_N is the adapter's bench fault injection.
module spi_sched_phase_top #(
    parameter integer N_ROWS = 32, INTERVAL = 5029, GUARD = 2,
    parameter integer P_PRE = 2, P_SENSE = 10, P_WB = 20, P_GUARD = 2, GAP = 0,
    parameter integer LAT = 1,
    parameter integer T_ROW_X = 0, T_ACC_X = 0, GUARD_X = 0,
    parameter integer MUT = 0, MUT_N = 7,
    parameter integer ROW_W = 5
) (
    input  wire             clk,
    input  wire             rst_n,
    // SPI
    input  wire             sclk,
    input  wire             cs_n,
    input  wire             mosi,
    output wire             miso,
    // foreground port
    input  wire             req_valid,
    input  wire             req_we,
    input  wire [ROW_W-1:0] req_row,
    output wire             req_accept,
    // scheduler operation interface (observation)
    output wire             op_busy,
    output wire             op_is_refresh,
    output wire             op_is_write,
    output wire [ROW_W-1:0] op_row,
    output wire             op_done,
    // scheduler / control status (observation)
    output wire             en_eff,
    output wire [15:0]      ivl_eff,
    output wire             sweep_active,
    output wire             sweep_done,
    output wire             refresh_ok,
    output wire             data_lost,
    output wire             cfg_reject,
    output wire             busy,
    // adapter and sequencer
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
    localparam integer GUARD_C = (GUARD_X > 0) ? GUARD_X : GUARD + N_ROWS + 1;
    localparam integer MIN_IVL_E = N_ROWS * T_ROW_E + T_ACC_E + GUARD_C;

    // A floor above the ratified interval makes the scheduler stop the
    // simulation at elaboration; run_tests.sh rejects such sets from the
    // Python derivation before simulating, so this is only a backstop.
    gc_ctrl_top #(.N_ROWS(N_ROWS), .T_ROW(T_ROW_E), .T_ACC(T_ACC_E), .INTERVAL(INTERVAL), .GUARD(GUARD_C)) u_ctrl (
        .rst_n(rst_n), .clk(clk), .sclk(sclk), .cs_n(cs_n), .mosi(mosi), .miso(miso),
        .req_valid(req_valid), .req_we(req_we), .req_row(req_row), .req_accept(req_accept),
        .op_busy(op_busy), .op_is_refresh(op_is_refresh), .op_is_write(op_is_write),
        .op_row(op_row), .op_done(op_done),
        .en_eff(en_eff), .ivl_eff(ivl_eff), .sweep_active(sweep_active), .sweep_done(sweep_done),
        .refresh_ok(refresh_ok), .data_lost(data_lost), .cfg_reject(cfg_reject), .busy(busy));

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
