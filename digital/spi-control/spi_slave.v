// Behavioral SPI control slave (issue #83, epic #24 item 4). PROPOSED, NOT synthesis.
// See SPEC.md for the interface; every element there is tagged ASSUMPTION or sourced.
// A gain cell is dynamic: this block only configures a refresh controller. It
// is not an SRAM-replacement interface.
//
// SPI mode 0, MSB first, 16-bit frame {RW, ADDR[6:0], DATA[7:0]}; RW=1 write.
// Writes/commands commit on the cs_n rising edge, and only if exactly 16 sclk
// rising edges were seen (otherwise ERR_FRAME and no state change).
//
// Additive, parameter-gated extensions (issue #93; defaults reproduce the #83
// behaviour exactly, re-checked by run_tests.sh / run_mutation.sh):
//   MIN_INTERVAL (default 1): commit floor for the interval register. 1 is the
//     original placeholder; digital/control-integration passes the scheduler's
//     feasibility floor N_ROWS*T_ROW + T_ACC + GUARD.
//   XSTAT_EN (default 0): when 1, address 0x06 XSTATUS is a read-only register
//     returning xstat_in; when 0, 0x06 is an unknown address as before and
//     xstat_in is ignored.
module spi_slave #(
    parameter integer MAX_INTERVAL,         // no default: must be supplied (params.py via run_tests.sh)
    parameter integer MIN_INTERVAL = 1,     // #93 additive; 1 = original lower bound
    parameter integer XSTAT_EN     = 0      // #93 additive; 0 = original register map
) (
    input  wire        rst_n,       // async, active low
    input  wire        sclk,
    input  wire        cs_n,
    input  wire        mosi,
    output wire        miso,        // Hi-Z while cs_n high
    input  wire        busy_in,     // sweep busy (from scheduler; ASSUMPTION: pre-synchronised)
    output reg         refresh_en,
    output wire [15:0] interval,    // committed refresh interval, cycles
    output reg         sweep_tog,   // toggles on each accepted START_SWEEP
    output wire        err_any,
    input  wire [7:0]  xstat_in     // #93: extended status (only used when XSTAT_EN=1)
);
    localparam [7:0] ID_VAL = 8'hA5;                    // ASSUMPTION
    localparam [6:0] A_ID=7'h00, A_CTRL=7'h01, A_CMD=7'h02,
                     A_IVL_L=7'h03, A_IVL_H=7'h04, A_STATUS=7'h05,
                     A_XSTAT=7'h06;                     // #93, only if XSTAT_EN

    reg [7:0] ivl_l, ivl_h, sh_l;
    reg [4:0] st;           // sticky: [0]RANGE [1]FRAME [2]ACCESS [3]BUSY [4]CMD
    assign interval = {ivl_h, ivl_l};
    assign err_any  = |st;

    reg [15:0] rx;
    reg [4:0]  cnt;
    reg [7:0]  tx;
    assign miso = cs_n ? 1'bz : tx[7];

    function [7:0] rd(input [6:0] a);
        case (a)
            A_ID:     rd = ID_VAL;
            A_CTRL:   rd = {7'b0, refresh_en};
            A_IVL_L:  rd = ivl_l;
            A_IVL_H:  rd = ivl_h;
            A_STATUS: rd = {busy_in, 2'b0, st};
            A_XSTAT:  rd = (XSTAT_EN != 0) ? xstat_in : 8'h00;   // #93; 0x00 (unknown) by default
            default:  rd = 8'h00;
        endcase
    endfunction

    // shift-in (sampled on rising edge); counter saturates
    always @(posedge sclk or posedge cs_n or negedge rst_n) begin
        if (cs_n || !rst_n) begin rx <= 16'h0; cnt <= 5'd0; end
        else begin
            rx <= {rx[14:0], mosi};
            if (cnt != 5'd31) cnt <= cnt + 5'd1;
        end
    end
    // shift-out (driven on falling edge); read data latched after the 8 command bits
    always @(negedge sclk or posedge cs_n or negedge rst_n) begin
        if (cs_n || !rst_n) tx <= 8'h00;
        else if (cnt == 5'd8) tx <= rx[7] ? 8'h00 : rd(rx[6:0]);   // MUT_RDLATCH
        else if (cnt > 5'd8)  tx <= {tx[6:0], 1'b0};
    end

    // commit on cs_n rising edge
    reg [4:0]  nst;
    reg [15:0] val;
    always @(posedge cs_n or negedge rst_n) begin
        if (!rst_n) begin
            refresh_en <= 1'b1;                 // ASSUMPTION: refresh on at reset
            ivl_l <= MAX_INTERVAL[7:0]; ivl_h <= MAX_INTERVAL[15:8];
            sh_l  <= MAX_INTERVAL[7:0];
            sweep_tog <= 1'b0; st <= 5'b0;
        end else if (cnt != 5'd0) begin
            nst = st;
            if (cnt != 5'd16) nst[1] = 1'b1;               // MUT_FRAME
            else if (rx[15]) begin
                case (rx[14:8])
                    A_CTRL:  refresh_en <= rx[0];
                    A_IVL_L: sh_l <= rx[7:0];
                    A_IVL_H: begin
                        val = {rx[7:0], sh_l};
                        if (val < MIN_INTERVAL) val = 16'd0;   // #93 floor; no-op at MIN_INTERVAL=1
                        if (val == 16'd0 || val > MAX_INTERVAL) begin   // MUT_BOUND
                            nst[0] = 1'b1; sh_l <= ivl_l;
                        end else begin
                            ivl_h <= rx[7:0]; ivl_l <= sh_l;
                        end
                    end
                    A_CMD: case (rx[7:0])
                        8'h01: if (busy_in) nst[3] = 1'b1; else sweep_tog <= ~sweep_tog;
                        8'h02: nst = 5'b0;                           // MUT_CLEAR
                        default: nst[4] = 1'b1;
                    endcase
                    default: nst[2] = 1'b1;     // RO (ID/STATUS) or unknown address
                endcase
            end else if (rd_unknown(rx[14:8])) nst[2] = 1'b1;
            st <= nst;
        end
    end
    function rd_unknown(input [6:0] a);
        rd_unknown = !(a==A_ID || a==A_CTRL || a==A_CMD || a==A_IVL_L || a==A_IVL_H || a==A_STATUS
                       || (XSTAT_EN != 0 && a == A_XSTAT));     // #93

    endfunction
endmodule
