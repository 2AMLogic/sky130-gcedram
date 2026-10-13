// Trace exporter for phase_seq (issue #128): runs ONE operation (default REFRESH) and
// prints every strobe edge so a deterministic converter can replay it in SPICE.
// Output lines (parsed by sim/refresh-replay/export_rtl_trace.py):
//   TRACE_META <key> <value>
//   TRACE_INIT <signal> <0|1>          value just before the accepting clock edge
//   TRACE_EDGE <t_ns> <signal> <0|1>   t_ns relative to the clock edge that accepted `start`
//   TRACE_END <t_ns>                   end of the observation window
// Time base 1 cycle = 1 ns (study assumption inherited from the scheduler, not a frequency claim).
// Behavioral only; not synthesis or timing evidence.
`timescale 1ns/1ps
module tb_trace_export;
    parameter integer P_PRE = 2, P_SENSE = 10, P_WB = 20, P_GUARD = 2, GAP = 0;
    parameter integer KIND = 2;   // 0 READ, 1 WRITE, 2 REFRESH
    reg clk = 0, rst_n = 0, start = 0;
    reg [1:0] kind = 0;
    reg [4:0] row = 0;
    wire busy, done, start_ignored, pre_en, rwl_sel, sense_en, wwl_en, bl_drive;
    wire [4:0] row_q;
    phase_seq #(.P_PRE(P_PRE), .P_SENSE(P_SENSE), .P_WB(P_WB), .P_GUARD(P_GUARD), .GAP(GAP))
        dut(.clk(clk), .rst_n(rst_n), .start(start), .kind(kind), .row(row), .busy(busy),
            .done(done), .start_ignored(start_ignored), .pre_en(pre_en), .rwl_sel(rwl_sel),
            .sense_en(sense_en), .wwl_en(wwl_en), .bl_drive(bl_drive), .row_q(row_q));
    always #0.5 clk = ~clk;   // 1 ns period: 1 cycle := 1 ns

    // Edges are taken from values SAMPLED 0.1 ns after each rising clock edge (settled, cycle
    // accurate) and stamped with that clock edge's time. Zero-width delta-cycle glitches inside
    // one time step (e.g. sense_en when the SENSE state loads before its counter) are therefore
    // not edges; they are only counted (TRACE_GLITCHES) so the omission is visible.
    real t0, tg_pre = -1, tg_rwl = -1, tg_sen = -1, tg_wwl = -1, tg_bl = -1;
    integer glitches = 0;
    reg armed = 0;
    reg [6:0] prev, cur;
    integer k;
    always @(pre_en)   begin if ($realtime == tg_pre) glitches = glitches + 1; tg_pre = $realtime; end
    always @(rwl_sel)  begin if ($realtime == tg_rwl) glitches = glitches + 1; tg_rwl = $realtime; end
    always @(sense_en) begin if ($realtime == tg_sen) glitches = glitches + 1; tg_sen = $realtime; end
    always @(wwl_en)   begin if ($realtime == tg_wwl) glitches = glitches + 1; tg_wwl = $realtime; end
    always @(bl_drive) begin if ($realtime == tg_bl)  glitches = glitches + 1; tg_bl = $realtime; end
    always @(posedge clk) if (armed) begin
        #0.1;
        cur = {pre_en, rwl_sel, sense_en, wwl_en, bl_drive, busy, done};
        for (k = 6; k >= 0; k = k - 1) if (cur[k] !== prev[k])
            $display("TRACE_EDGE %0.3f %0s %0d", $realtime - 0.1 - t0,
                     (k == 6) ? "pre_en" : (k == 5) ? "rwl_sel" : (k == 4) ? "sense_en" :
                     (k == 3) ? "wwl_en" : (k == 2) ? "bl_drive" : (k == 1) ? "busy" : "done", cur[k]);
        prev = cur;
    end

    initial begin
        #5.25 rst_n = 1;                     // release reset away from clock edges
        @(negedge clk); kind = KIND; row = 5'd3; start = 1;
        $display("TRACE_META kind %0d", KIND);
        $display("TRACE_META P_PRE %0d", P_PRE); $display("TRACE_META P_SENSE %0d", P_SENSE);
        $display("TRACE_META P_WB %0d", P_WB);   $display("TRACE_META P_GUARD %0d", P_GUARD);
        $display("TRACE_META GAP %0d", GAP);
        $display("TRACE_INIT pre_en %0d", pre_en);   $display("TRACE_INIT rwl_sel %0d", rwl_sel);
        $display("TRACE_INIT sense_en %0d", sense_en); $display("TRACE_INIT wwl_en %0d", wwl_en);
        $display("TRACE_INIT bl_drive %0d", bl_drive); $display("TRACE_INIT busy %0d", busy);
        $display("TRACE_INIT done %0d", done);
        prev = {pre_en, rwl_sel, sense_en, wwl_en, bl_drive, busy, done};
        @(posedge clk); t0 = $realtime; armed = 1;   // accepting edge; the sampler below sees its effect at +0.1 ns
        #0.2 start = 0;
        repeat (80) @(posedge clk);
        $display("TRACE_GLITCHES %0d", glitches);
        $display("TRACE_END %0.3f", $realtime - t0);
        $finish;
    end
endmodule
