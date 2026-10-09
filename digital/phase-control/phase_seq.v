// Behavioral analog-phase sequencer (PROPOSED, issue #108).
// One operation (READ / WRITE / REFRESH) is expanded into non-overlapping
// analog phase strobes. All durations are ASSUMPTION (see CONTRACT.md); the
// 1 cycle = 1 ns time base is inherited from the refresh scheduler.
// The macro is DYNAMIC: REFRESH is mandatory and is not an SRAM operation.
// Behavioral only: not synthesis, timing or sign-off evidence.
//
//   READ    : PRE -> SENSE -> GUARD
//   WRITE   : WB  -> GUARD
//   REFRESH : PRE -> SENSE -> WB -> GUARD   (read, then write the value back)
// GAP idle cycles (all strobes low) may separate phases (default 0).
module phase_seq #(
    parameter integer P_PRE   = 2,   // ASSUMPTION precharge, cycles
    parameter integer P_SENSE = 10,  // ASSUMPTION RWL select window, cycles
    parameter integer P_WB    = 20,  // ASSUMPTION WWL/BL write pulse, cycles
    parameter integer P_GUARD = 2,   // ASSUMPTION BL release guard, cycles
    parameter integer GAP     = 0,   // ASSUMPTION inter-phase dead cycles
    parameter integer ROW_W   = 5
) (
    input  wire             clk,
    input  wire             rst_n,
    input  wire             start,      // 1-cycle request, honoured only when idle
    input  wire [1:0]       kind,       // 0 READ, 1 WRITE, 2 REFRESH
    input  wire [ROW_W-1:0] row,
    output wire             busy,
    output reg              done,       // 1 cycle after the last guard cycle
    output reg              start_ignored,
    output wire             pre_en,     // read-bitline precharge on
    output wire             rwl_sel,    // read select asserted (active sense)
    output wire             sense_en,   // sample strobe, last cycle of RWL window
    output wire             wwl_en,     // write wordline
    output wire             bl_drive,   // write bitline driven (WWL + guard)
    output reg  [ROW_W-1:0] row_q
);
    localparam [1:0] K_READ = 2'd0, K_WRITE = 2'd1, K_REF = 2'd2;
    localparam [2:0] S_IDLE = 3'd0, S_PRE = 3'd1, S_SENSE = 3'd2, S_WB = 3'd3,
                     S_GUARD = 3'd4, S_GAP = 3'd5;

    initial if (P_PRE < 1 || P_SENSE < 1 || P_WB < 1 || P_GUARD < 1 || GAP < 0) begin
        $display("phase_seq: every phase needs >= 1 cycle"); $finish;
    end

    reg [2:0] st, nxt;
    reg [1:0] kind_q;
    reg [15:0] cnt;

    function integer dur(input [2:0] s);
        case (s)
            S_PRE:   dur = P_PRE;
            S_SENSE: dur = P_SENSE;
            S_WB:    dur = P_WB;
            default: dur = P_GUARD;
        endcase
    endfunction

    function [2:0] next_phase(input [2:0] s, input [1:0] k);
        case (s)
            S_PRE:   next_phase = S_SENSE;
            S_SENSE: next_phase = (k == K_REF) ? S_WB : S_GUARD;   // MUT_REFWB
            S_WB:    next_phase = S_GUARD;
            default: next_phase = S_IDLE;
        endcase
    endfunction

    assign busy     = (st != S_IDLE);
    assign pre_en   = (st == S_PRE);                                // MUT_PRE
    assign rwl_sel  = (st == S_SENSE);                              // MUT_RWL
    assign sense_en = (st == S_SENSE) && (cnt == 0);                // MUT_SENSE
    assign wwl_en   = (st == S_WB);                                 // MUT_WWL
    assign bl_drive = (st == S_WB) ||
                      (kind_q != K_READ && (st == S_GUARD || (st == S_GAP && nxt == S_GUARD))); // MUT_BL

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st <= S_IDLE; nxt <= S_IDLE; kind_q <= K_READ; cnt <= 0;
            done <= 1'b0; start_ignored <= 1'b0; row_q <= {ROW_W{1'b0}};
        end else begin
            done <= 1'b0; start_ignored <= 1'b0;
            if (st == S_IDLE) begin
                if (start) begin
                    row_q <= row; kind_q <= kind;
                    if (kind == K_WRITE) begin st <= S_WB;  cnt <= dur(S_WB) - 1; end
                    else if (kind == K_REF || kind == K_READ) begin   // MUT_FIRST
                        st <= S_PRE; cnt <= dur(S_PRE) - 1;
                    end
                end
            end else begin
                if (start) start_ignored <= 1'b1;                   // MUT_BUSY
                if (cnt != 0) cnt <= cnt - 1;
                else if (st == S_GAP) begin st <= nxt; cnt <= dur(nxt) - 1; end
                else if (next_phase(st, kind_q) == S_IDLE) begin st <= S_IDLE; done <= 1'b1; end  // MUT_DONE
                else if (GAP > 0) begin st <= S_GAP; nxt <= next_phase(st, kind_q); cnt <= GAP - 1; end
                else begin st <= next_phase(st, kind_q); cnt <= dur(next_phase(st, kind_q)) - 1; end
            end
        end
    end
endmodule
