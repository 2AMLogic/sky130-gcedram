// Combined behavioral control path (issue #93, epic #24 items 3-4). PROPOSED,
// behavioral, NOT synthesis, NOT a CDC sign-off, NOT a macro specification.
// A gain cell is dynamic: this configures refresh; it is not an
// SRAM-replacement controller.
//
//   SPI master --(sclk, cs_n, mosi/miso)--> spi_slave (#83, MIN_INTERVAL and
//   XSTATUS enabled) --{refresh_en, interval, sweep_tog}--> cfg_xfer (#93)
//   --cfg snapshot--> refresh_sched_rt (#93, derived from #74) --> array ops.
//
// busy_in (STATUS[7]) = transfer pending OR sweep active.
// XSTATUS (0x06): [0] REFRESH_OK [1] DATA_LOST [2] SWEEP_ACTIVE [3] CFG_REJECT.
// Status returned to the SPI domain is assumed synchronised (as #83 already
// assumes for busy_in); see CONTRACT.md.
module gc_ctrl_top #(
    parameter integer N_ROWS   = 32,
    parameter integer T_ROW    = 34,
    parameter integer T_ACC    = 34,
    parameter integer INTERVAL = 5029,   // ratified bound (reset value + SPI MAX_INTERVAL)
    parameter integer GUARD    = 2,
    parameter integer ROW_W    = (N_ROWS > 1) ? $clog2(N_ROWS) : 1
) (
    input  wire             rst_n,
    input  wire             clk,
    // SPI
    input  wire             sclk,
    input  wire             cs_n,
    input  wire             mosi,
    output wire             miso,
    // external access port
    input  wire             req_valid,
    input  wire             req_we,
    input  wire [ROW_W-1:0] req_row,
    output wire             req_accept,
    // array-side operation
    output wire             op_busy,
    output wire             op_is_refresh,
    output wire             op_is_write,
    output wire [ROW_W-1:0] op_row,
    output wire             op_done,
    // observability (status pins; also readable through XSTATUS)
    output wire             en_eff,
    output wire [15:0]      ivl_eff,
    output wire             sweep_active,
    output wire             sweep_done,
    output wire             refresh_ok,
    output wire             data_lost,
    output wire             cfg_reject,
    output wire             busy
);
    // Scheduler feasibility floor: the #74 elaboration constraint
    // (EAGER_AGE = INTERVAL - N_ROWS*T_ROW - T_ACC - GUARD >= 0) for a runtime value.
    localparam integer MIN_INTERVAL = N_ROWS * T_ROW + T_ACC + GUARD;   // MUT_TOP_FLOOR

    wire        spi_en, spi_tog, err_any, xfer_pending;
    wire [15:0] spi_ivl;
    wire        cfg_valid, cfg_en, cfg_sweep;
    wire [15:0] cfg_interval;

    assign busy = xfer_pending || sweep_active;                         // MUT_BUSY

    spi_slave #(.MAX_INTERVAL(INTERVAL), .MIN_INTERVAL(MIN_INTERVAL), .XSTAT_EN(1)) u_spi (
        .rst_n(rst_n), .sclk(sclk), .cs_n(cs_n), .mosi(mosi), .miso(miso),
        .busy_in(busy), .refresh_en(spi_en), .interval(spi_ivl), .sweep_tog(spi_tog),
        .err_any(err_any),
        .xstat_in({4'b0, cfg_reject, sweep_active, data_lost, refresh_ok}));

    cfg_xfer u_xfer (
        .clk(clk), .rst_n(rst_n), .cs_n(cs_n),
        .spi_en(spi_en), .spi_ivl(spi_ivl), .spi_tog(spi_tog),
        .cfg_valid(cfg_valid), .cfg_en(cfg_en), .cfg_interval(cfg_interval),
        .cfg_sweep(cfg_sweep), .pending(xfer_pending));

    refresh_sched_rt #(.N_ROWS(N_ROWS), .T_ROW(T_ROW), .T_ACC(T_ACC),
                       .INTERVAL(INTERVAL), .GUARD(GUARD)) u_sched (
        .clk(clk), .rst_n(rst_n),
        .req_valid(req_valid), .req_we(req_we), .req_row(req_row), .req_accept(req_accept),
        .op_busy(op_busy), .op_is_refresh(op_is_refresh), .op_is_write(op_is_write),
        .op_row(op_row), .op_done(op_done),
        .cfg_valid(cfg_valid), .cfg_en(cfg_en), .cfg_interval(cfg_interval), .cfg_sweep(cfg_sweep),
        .en_eff(en_eff), .ivl_eff(ivl_eff), .sweep_active(sweep_active), .sweep_done(sweep_done),
        .refresh_ok(refresh_ok), .data_lost(data_lost), .cfg_reject(cfg_reject));
endmodule
