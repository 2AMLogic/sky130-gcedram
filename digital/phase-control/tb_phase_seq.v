// Testbench for phase_seq: exact cycle-by-cycle comparison to an independent
// reference model, plus standalone ordering/overlap invariants, back-to-back
// ops, start-while-busy, reset mid-op. Prints CONFLICT lines (report only,
// never fail) comparing op length with the scheduler's T_ROW / T_ACC.
`timescale 1ns/1ps
module tb_phase_seq;
    parameter integer P_PRE = 2, P_SENSE = 10, P_WB = 20, P_GUARD = 2, GAP = 0;
    parameter integer T_ROW = 34, T_ACC = 34;   // ASSUMPTION, from refresh_sched.v
    reg clk = 0, rst_n = 0, start = 0;
    reg [1:0] kind = 0;
    reg [4:0] row = 0;
    wire busy, done, start_ignored, pre_en, rwl_sel, sense_en, wwl_en, bl_drive;
    wire [4:0] row_q;
    phase_seq #(.P_PRE(P_PRE), .P_SENSE(P_SENSE), .P_WB(P_WB), .P_GUARD(P_GUARD), .GAP(GAP))
        dut(.clk(clk), .rst_n(rst_n), .start(start), .kind(kind), .row(row), .busy(busy),
            .done(done), .start_ignored(start_ignored), .pre_en(pre_en), .rwl_sel(rwl_sel),
            .sense_en(sense_en), .wwl_en(wwl_en), .bl_drive(bl_drive), .row_q(row_q));
    always #1 clk = ~clk;   // 2 ns period is irrelevant: 1 cycle := 1 ns by assumption

    integer errors = 0;
    task err(input [255:0] msg); begin errors = errors + 1; $display("VIOLATION: %0s t=%0t", msg, $time); end endtask

    // ---- reference model: vec = {pre,rwl,sense,wwl,bl}
    function integer ph_on(input [1:0] k, input integer p);   // phase included?
        case (p) 0: ph_on = (k != 1); 1: ph_on = (k != 1); 2: ph_on = (k != 0); default: ph_on = 1; endcase
    endfunction
    function integer ph_len(input integer p);
        case (p) 0: ph_len = P_PRE; 1: ph_len = P_SENSE; 2: ph_len = P_WB; default: ph_len = P_GUARD; endcase
    endfunction
    function integer total(input [1:0] k);
        integer p, pos, first;
        begin pos = 0; first = 1;
            for (p = 0; p < 4; p = p + 1) if (ph_on(k, p)) begin
                if (!first) pos = pos + GAP;
                pos = pos + ph_len(p); first = 0;
            end
            total = pos;
        end
    endfunction
    function [4:0] ref_vec(input [1:0] k, input integer c);
        integer p, pos, first;
        reg [4:0] v;
        begin pos = 0; first = 1; v = 5'b0;
            for (p = 0; p < 4; p = p + 1) if (ph_on(k, p)) begin
                if (!first) begin
                    if (c >= pos && c < pos + GAP) v = (p == 3 && k != 0) ? 5'b00001 : 5'b0;
                    pos = pos + GAP;
                end
                if (c >= pos && c < pos + ph_len(p)) case (p)
                    0: v = 5'b10000;
                    1: v = (c == pos + ph_len(p) - 1) ? 5'b01100 : 5'b01000;
                    2: v = 5'b00011;
                    default: v = (k != 0) ? 5'b00001 : 5'b0;
                endcase
                pos = pos + ph_len(p); first = 0;
            end
            ref_vec = v;
        end
    endfunction

    // ---- standalone invariants (contract Sec. 3), sampled every negedge
    reg [1:0] cur_kind = 0;
    reg sense_seen = 0;
    always @(negedge clk) if (rst_n) begin
        if (pre_en && (rwl_sel || sense_en || wwl_en || bl_drive)) err("precharge overlaps another phase");
        if (sense_en && !rwl_sel) err("sense enable without RWL");
        if (wwl_en && (rwl_sel || sense_en || pre_en)) err("WWL overlaps RWL/sense/precharge");
        if (bl_drive && (rwl_sel || sense_en || pre_en)) err("BL drive overlaps RWL/sense/precharge");
        if (wwl_en && !bl_drive) err("WWL without BL drive");
        if (!busy && (pre_en || rwl_sel || sense_en || wwl_en || bl_drive)) err("strobe while idle");
        if (busy && cur_kind == 2 && (wwl_en || bl_drive) && !sense_seen) err("write-back before sense completed");
        if (busy && cur_kind == 0 && (wwl_en || bl_drive)) err("READ drives write phase");
        if (busy && cur_kind == 1 && (pre_en || rwl_sel || sense_en)) err("WRITE runs read phase");
        if (sense_en) sense_seen <= 1;
        if (!busy) sense_seen <= 0;
    end

    task run_op(input [1:0] k, input [4:0] r, input integer inject_start);
        integer c, n, ig;
        reg [4:0] v;
        begin
            @(negedge clk); kind = k; row = r; start = 1; cur_kind = k;
            @(negedge clk); start = 0; ig = 0;   // posedge between: op accepted
            n = total(k);
            for (c = 0; c < n; c = c + 1) begin
                v = ref_vec(k, c);
                if ({pre_en, rwl_sel, sense_en, wwl_en, bl_drive} !== v) begin
                    errors = errors + 1;
                    $display("VIOLATION: kind=%0d cycle=%0d got=%b exp=%b", k, c, {pre_en,rwl_sel,sense_en,wwl_en,bl_drive}, v);
                end
                if (!busy) err("busy low mid-op");
                if (row_q !== r) err("row not held");
                if (done) err("done early");
                if (inject_start && c == n/2) begin kind = (k == 2) ? 0 : 2; start = 1; end
                if (c == n/2 + 1) start = 0;
                if (start_ignored) ig = 1;
                @(negedge clk);
            end
            start = 0;
            if (!done || busy) err("done pulse missing after last cycle");
            if (inject_start && !ig) err("start while busy not flagged");
            @(negedge clk);
            if (done) err("done longer than one cycle");
            if ({pre_en,rwl_sel,sense_en,wwl_en,bl_drive} !== 5'b0) err("strobe after done");
        end
    endtask

    integer i;
    initial begin
        #5 rst_n = 1;
        @(negedge clk);
        if (busy) err("busy after reset");
        $display("INFO: phases pre=%0d sense=%0d wb=%0d guard=%0d gap=%0d", P_PRE, P_SENSE, P_WB, P_GUARD, GAP);
        $display("INFO: cycles READ=%0d WRITE=%0d REFRESH=%0d (T_ROW=%0d T_ACC=%0d)", total(0), total(1), total(2), T_ROW, T_ACC);
        if (total(2) > T_ROW) $display("CONFLICT: REFRESH needs %0d cycles > scheduler T_ROW=%0d (op_done would precede last phase)", total(2), T_ROW);
        else if (total(2) == T_ROW) $display("CONFLICT: REFRESH needs %0d cycles == T_ROW=%0d (zero slack)", total(2), T_ROW);
        else $display("CONFLICT: REFRESH needs %0d cycles < T_ROW=%0d (%0d cycles unused slack)", total(2), T_ROW, T_ROW - total(2));
        if (total(0) > T_ACC || total(1) > T_ACC) $display("CONFLICT: external op needs READ=%0d WRITE=%0d > T_ACC=%0d", total(0), total(1), T_ACC);
        for (i = 0; i < 3; i = i + 1) run_op(i, 5'd3 + i, 0);
        for (i = 0; i < 3; i = i + 1) run_op(i, 5'd20 + i, 1);   // start while busy
        // back to back with no idle cycle in between
        run_op(2, 5'd31, 0); run_op(2, 5'd0, 0); run_op(0, 5'd7, 0); run_op(1, 5'd8, 0);
        // asynchronous reset mid-op
        @(negedge clk); kind = 2; row = 5'd9; start = 1; cur_kind = 2;
        @(negedge clk); start = 0; repeat (4) @(negedge clk);
        rst_n = 0; #0.1;
        if (busy || pre_en || rwl_sel || sense_en || wwl_en || bl_drive) err("reset did not clear");
        @(negedge clk); rst_n = 1; @(negedge clk);
        run_op(2, 5'd10, 0);
        if (errors == 0) $display("TB_RESULT: PASS"); else $display("TB_RESULT: FAIL errors=%0d", errors);
        $finish;
    end
    initial begin #100000; $display("TB_RESULT: FAIL timeout"); $finish; end
endmodule
