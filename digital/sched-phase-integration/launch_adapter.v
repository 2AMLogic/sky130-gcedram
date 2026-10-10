// Launch adapter: refresh_sched_rt operation interface -> phase_seq request
// (issue #135). PROPOSED, behavioral. Neither production module is changed.
//
// Mapping derived from the actual interfaces:
//   launch  = rising edge of op_busy (the scheduler registers op_busy, op_row,
//             op_is_refresh, op_is_write together on the decision edge, so the
//             first op_busy cycle carries the accepted kind and row);
//   start   = launch, combinational, high for exactly that first busy cycle;
//   kind    = op_is_refresh ? REFRESH(2) : op_is_write ? WRITE(1) : READ(0);
//   row     = op_row (phase_seq latches it into row_q on the accepted start).
// The adapter has no handshake back to the scheduler (the scheduler does not
// wait on completion): a start while phase_seq is busy is ignored by phase_seq
// and flagged by start_ignored.
//
// MUT (bench fault injection only; 0 = real adapter):
//   1 drop the MUT_N-th launch        2 wrong row on the MUT_N-th launch
//   3 duplicate (stretch) the MUT_N-th start to two cycles
module launch_adapter #(
    parameter integer ROW_W = 5,
    parameter integer MUT   = 0,
    parameter integer MUT_N = 7
) (
    input  wire             clk,
    input  wire             rst_n,
    input  wire             op_busy,
    input  wire             op_is_refresh,
    input  wire             op_is_write,
    input  wire [ROW_W-1:0] op_row,
    output wire             start,
    output wire [1:0]       kind,
    output wire [ROW_W-1:0] row
);
    reg        busy_d;
    reg        dup_d;
    integer    n;
    wire       launch = op_busy && !busy_d;
    wire       hit    = launch && (n + 1 == MUT_N);   // n counts launches seen so far

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin busy_d <= 1'b0; n <= 0; dup_d <= 1'b0; end
        else begin
            busy_d <= op_busy;
            if (launch) n <= n + 1;
            dup_d <= (MUT == 3) && hit;
        end
    end

    assign start = ((MUT == 1) ? (launch && !hit) : launch) || dup_d;
    assign kind  = op_is_refresh ? 2'd2 : (op_is_write ? 2'd1 : 2'd0);
    assign row   = (MUT == 2 && hit) ? (op_row ^ {{(ROW_W-1){1'b0}}, 1'b1}) : op_row;
endmodule
