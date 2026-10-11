// Protocol model of the PROPOSED SPI <-> scheduler crossing (issue #157).
// PROPOSED, behavioral, NOT synthesis, NOT a CDC sign-off. Icarus has no
// metastability model: this file shows WHAT is delivered, in which order and
// how often, under stated master obligations. It does not show that a
// physical synchroniser is safe. See README.md / DESIGN.md.
//
// Scope: a deliberately small register subset of ../spi-control/SPEC.md
// (CTRL, CMD, IVL_L/IVL_H, STATUS, XSTATUS). Interval range/floor checks are
// SPI-local and unchanged, so they are omitted here. The scheduler is reduced
// to a configuration register plus a fixed-length sweep counter (SW_LEN clk
// cycles); it is NOT the #74/#93 scheduler.
//
// Mechanism (see DESIGN.md Sec. 3-5):
//  * request mailbox  : bundle {sw, en, ivl} + toggle req_tog, held stable until
//                       ack_tog (clk -> SPI) shows it was consumed.
//  * command reservation: sw_tog (SPI-local) vs sdone_tog (clk -> SPI) gives a
//                       START_SWEEP reservation that spans commit..completion.
//  * diagnostic snapshot: snap_req/snap_ack handshake; the clk domain freezes
//                       snap_hold, the SPI domain copies it whole at a frame end.
// NOACK=1 is the NEGATIVE CONTROL: the SPI side ignores ack/reservation.
`timescale 1ns/1ps

module xing_spi #(
    parameter integer NOACK    = 0,
    parameter [15:0]  RST_IVL  = 16'd5029   // mirrors the existing reset default (assumption)
) (
    input  wire        rst_n,
    input  wire        sclk,
    input  wire        cs_n,
    input  wire        mosi,
    output wire        miso,
    input  wire        ack_tog_in,     // clk domain, single-bit level
    input  wire        sdone_tog_in,   // clk domain, single-bit level
    input  wire        snap_ack_in,    // clk domain, single-bit level
    input  wire [7:0]  snap_hold_in,   // clk domain, bundled with snap_ack
    output reg         req_tog,
    output reg         b_en,
    output reg  [15:0] b_ivl,
    output reg         b_sw,
    output reg         snap_req
);
    reg  [15:0] rx;
    reg  [4:0]  cnt;
    reg  [7:0]  tx;
    reg  [1:0]  ack_s, sd_s, sa_s;     // clocked by sclk only
    reg         sw_tog;
    reg  [7:0]  snap_sh;
    reg  [7:0]  sh_l;
    reg         st_busy;               // sticky ERR_BUSY (STATUS[3])

    // TB-only bookkeeping (not reset by rst_n, not hardware)
    integer     acc_cnt, acc_sw, refuse_cnt;
    reg [17:0]  acc_log [0:1023];
    initial begin acc_cnt = 0; acc_sw = 0; refuse_cnt = 0; end

    assign miso = cs_n ? 1'bz : tx[7];

    // BUSY = reservation only (exact); diagnostic sweep state is XSTATUS.
    wire busy = (req_tog != ack_s[1]) | (sw_tog != sd_s[1]);

    function [7:0] rd(input [6:0] a);
        case (a)
            7'h00: rd = 8'hA5;
            7'h01: rd = {7'b0, b_en};
            7'h03: rd = b_ivl[7:0];
            7'h04: rd = b_ivl[15:8];
            7'h05: rd = {busy, 3'b0, st_busy, 3'b0};
            7'h06: rd = snap_sh;
            default: rd = 8'h00;
        endcase
    endfunction

    // shift / frame counter (cs_n high clears)
    always @(posedge sclk or posedge cs_n) begin
        if (cs_n) cnt <= 5'd0;
        else begin rx <= {rx[14:0], mosi}; cnt <= (cnt == 5'd31) ? cnt : cnt + 5'd1; end
    end
    always @(negedge sclk or negedge rst_n) begin
        if (!rst_n) tx <= 8'h00;
        else if (!cs_n) begin
            if (cnt == 5'd8 && !rx[7]) tx <= rd(rx[6:0]);
            else tx <= {tx[6:0], 1'b0};
        end
    end

    // return-path synchronisers advance ONLY on sclk edges (sclk may stop)
    always @(posedge sclk or negedge rst_n) begin
        if (!rst_n) begin ack_s <= 2'b00; sd_s <= 2'b00; sa_s <= 2'b00; end
        else begin
            ack_s <= {ack_s[0], ack_tog_in};
            sd_s  <= {sd_s[0],  sdone_tog_in};
            sa_s  <= {sa_s[0],  snap_ack_in};
        end
    end

    // commit event: cs_n rising edge
    reg        mfree, sfree, nen, nsw, ok;
    reg [15:0] nivl;
    always @(posedge cs_n or negedge rst_n) begin
        if (!rst_n) begin
            req_tog <= 1'b0; b_en <= 1'b1; b_ivl <= RST_IVL; b_sw <= 1'b0;
            sw_tog <= 1'b0; snap_req <= 1'b0; snap_sh <= 8'h80; sh_l <= RST_IVL[7:0];
            st_busy <= 1'b0;
        end else begin
            if (cnt == 5'd16 && rx[15]) begin
                mfree = NOACK || (req_tog == ack_s[1]);
                sfree = NOACK || (sw_tog == sd_s[1]);
                nen = b_en; nivl = b_ivl; nsw = 1'b0; ok = 1'b0;
                case (rx[14:8])
                    7'h01: begin
                        if (mfree) begin nen = rx[0]; ok = 1'b1; end else begin st_busy <= 1'b1; refuse_cnt = refuse_cnt + 1; end
                    end
                    7'h03: sh_l <= rx[7:0];
                    7'h04: begin
                        if (mfree) begin nivl = {rx[7:0], sh_l}; ok = 1'b1; end else begin st_busy <= 1'b1; refuse_cnt = refuse_cnt + 1; end
                    end
                    7'h02: begin
                        if (rx[7:0] == 8'h01) begin
                            if (mfree && sfree) begin nsw = 1'b1; ok = 1'b1; sw_tog <= ~sw_tog; acc_sw = acc_sw + 1; end
                            else begin st_busy <= 1'b1; refuse_cnt = refuse_cnt + 1; end
                        end else if (rx[7:0] == 8'h02) st_busy <= 1'b0;
                    end
                    default: ;
                endcase
                if (ok) begin
                    b_en <= nen; b_ivl <= nivl; b_sw <= nsw; req_tog <= ~req_tog;
                    acc_log[acc_cnt] = {nsw, nen, nivl}; acc_cnt = acc_cnt + 1;
                end
            end
            // diagnostic snapshot handshake at every non-empty frame end
            if (cnt != 5'd0 && snap_req == sa_s[1]) begin
                snap_sh <= snap_hold_in; snap_req <= ~snap_req;
            end
        end
    end
endmodule

module xing_clk #(
    parameter integer SW_LEN  = 40,
    parameter [15:0]  RST_IVL = 16'd5029
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        req_tog_in,
    input  wire        b_en,
    input  wire [15:0] b_ivl,
    input  wire        b_sw,
    input  wire        snap_req_in,
    output reg         ack_tog,
    output reg         sdone_tog,
    output reg         snap_ack,
    output reg  [7:0]  snap_hold,
    output reg         cfg_en,
    output reg  [15:0] cfg_ivl,
    output reg         sweep_active
);
    reg [1:0]  rq_s, sr_s;
    reg        seen, cmd_sw;
    reg [15:0] swcnt;
    reg [3:0]  applied_cnt;

    // TB-only bookkeeping
    integer    n_applied, n_started, n_done;
    reg [17:0] app_log [0:1023];
    initial begin n_applied = 0; n_started = 0; n_done = 0; end

    // snapshot byte: {cfg_en, applied_cnt[3:0], sweep_active, ~cfg_en, ^applied_cnt}
    // bits 1 and 0 are redundant checks that expose a torn (incoherent) snapshot.
    function [7:0] mk(input en, input [3:0] ac, input sa);
        mk = {en, ac, sa, ~en, ^ac};
    endfunction

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rq_s <= 2'b00; sr_s <= 2'b00; seen <= 1'b0; cmd_sw <= 1'b0; swcnt <= 16'd0;
            applied_cnt <= 4'd0; ack_tog <= 1'b0; sdone_tog <= 1'b0; snap_ack <= 1'b0;
            cfg_en <= 1'b1; cfg_ivl <= RST_IVL; sweep_active <= 1'b0; snap_hold <= mk(1'b1, 4'd0, 1'b0);
        end else begin
            rq_s <= {rq_s[0], req_tog_in};
            sr_s <= {sr_s[0], snap_req_in};
            if (sweep_active) begin
                if (swcnt == 16'd1) begin
                    sweep_active <= 1'b0;
                    if (cmd_sw) begin sdone_tog <= ~sdone_tog; n_done = n_done + 1; cmd_sw <= 1'b0; end
                end else swcnt <= swcnt - 16'd1;
            end
            if (rq_s[1] != seen) begin               // mailbox has priority over snapshot
                seen <= rq_s[1];
                cfg_en <= b_en; cfg_ivl <= b_ivl; applied_cnt <= applied_cnt + 4'd1;
                ack_tog <= ~ack_tog;
                app_log[n_applied] = {b_sw, b_en, b_ivl}; n_applied = n_applied + 1;
                if (b_sw) begin sweep_active <= 1'b1; swcnt <= SW_LEN; cmd_sw <= 1'b1; n_started = n_started + 1; end
            end else if (sr_s[1] != snap_ack) begin
                snap_hold <= mk(cfg_en, applied_cnt, sweep_active);
                snap_ack  <= sr_s[1];
            end
        end
    end
endmodule

module xing_top #(
    parameter integer NOACK  = 0,
    parameter integer SW_LEN = 40
) (
    input  wire rst_n, input wire clk,
    input  wire sclk, input wire cs_n, input wire mosi, output wire miso
);
    wire req_tog, b_en, b_sw, snap_req, ack_tog, sdone_tog, snap_ack, cfg_en, sweep_active;
    wire [15:0] b_ivl, cfg_ivl;
    wire [7:0] snap_hold;
    xing_spi #(.NOACK(NOACK)) u_spi (
        .rst_n(rst_n), .sclk(sclk), .cs_n(cs_n), .mosi(mosi), .miso(miso),
        .ack_tog_in(ack_tog), .sdone_tog_in(sdone_tog), .snap_ack_in(snap_ack), .snap_hold_in(snap_hold),
        .req_tog(req_tog), .b_en(b_en), .b_ivl(b_ivl), .b_sw(b_sw), .snap_req(snap_req));
    xing_clk #(.SW_LEN(SW_LEN)) u_clk (
        .clk(clk), .rst_n(rst_n), .req_tog_in(req_tog), .b_en(b_en), .b_ivl(b_ivl), .b_sw(b_sw),
        .snap_req_in(snap_req), .ack_tog(ack_tog), .sdone_tog(sdone_tog), .snap_ack(snap_ack),
        .snap_hold(snap_hold), .cfg_en(cfg_en), .cfg_ivl(cfg_ivl), .sweep_active(sweep_active));
endmodule
