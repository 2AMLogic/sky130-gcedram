// Scheduler -> phase sequencer integration bench (issue #135). Behavioral.
// One cycle-indexed trace (sampled at the falling clock edge, i.e. after the
// non-blocking updates of the preceding rising edge, so a registered output is
// seen in the cycle in which it is visible) feeds a scoreboard that compares
// ACTUAL events; equal numeric durations are never assumed to mean agreement.
//
// Findings are two classes:
//   VIOLATION : the integration lost/duplicated/corrupted an operation, the
//               observed sequencer profile disagrees with its own parameters,
//               or the observed outcome differs from EXP_LOST / EXP_SKEW.
//               Any VIOLATION fails the bench (TB_RESULT: FAIL).
//   CONFLICT  : characterization of the open scheduler/sequencer timing
//               boundary (CONTRACT.md open item 4); expected, report-only.
//                 LOST   launch arrived while phase_seq was busy (start ignored)
//                 SKEW   strobe / busy / done extends past the scheduler's
//                        busy fall / done for an accepted operation
//
// SCEN: 0 isolated READ/WRITE (+ reset-initialisation sweep REFRESH)
//       1 saturating back-to-back READ/WRITE traffic
//       2 saturating traffic across urgent-refresh arbitration (12000 cycles)
//       3 runtime/sweep configuration transitions under traffic
//       4 reset interruption (scoped: abandonment is observed, not repaired)
`timescale 1ns/1ps
`ifndef VERBOSE
`define VERBOSE 0
`endif
module tb_sched_phase #(
    parameter integer SCEN = 0,
    parameter integer P_PRE = 2, P_SENSE = 10, P_WB = 20, P_GUARD = 2, GAP = 0,
    parameter integer MUT = 0, MUT_N = 7,
    parameter integer EXP_LOST = 0,      // 1: at least one LOST launch is expected
    parameter integer EXP_SKEW = 1,      // 1: at least one SKEW is expected
    parameter integer N_ROWS = 32, T_ROW = 34, T_ACC = 34, INTERVAL = 5029, GUARD = 2,
    parameter integer ROW_W = 5
);
    localparam integer MAXL = 4096;
    localparam integer MIN_IVL = N_ROWS * T_ROW + T_ACC + GUARD;

    reg clk = 0;
    reg rst_n = 0;
    always #5 clk = ~clk;

    reg              req_valid = 0, req_we = 0;
    reg  [ROW_W-1:0] req_row = 0;
    reg              cfg_valid = 0, cfg_en = 1, cfg_sweep = 0;
    reg  [15:0]      cfg_interval = INTERVAL;
    wire req_accept, op_busy, op_is_refresh, op_is_write, op_done, sweep_active, cfg_reject;
    wire [ROW_W-1:0] op_row, a_row, q_row;
    wire a_start, q_busy, q_done, q_ign, pre_en, rwl_sel, sense_en, wwl_en, bl_drive;
    wire [1:0] a_kind;

    sched_phase_top #(.N_ROWS(N_ROWS), .T_ROW(T_ROW), .T_ACC(T_ACC), .INTERVAL(INTERVAL), .GUARD(GUARD),
        .P_PRE(P_PRE), .P_SENSE(P_SENSE), .P_WB(P_WB), .P_GUARD(P_GUARD), .GAP(GAP),
        .MUT(MUT), .MUT_N(MUT_N), .ROW_W(ROW_W)) dut (
        .clk(clk), .rst_n(rst_n), .req_valid(req_valid), .req_we(req_we), .req_row(req_row),
        .req_accept(req_accept), .cfg_valid(cfg_valid), .cfg_en(cfg_en),
        .cfg_interval(cfg_interval), .cfg_sweep(cfg_sweep),
        .op_busy(op_busy), .op_is_refresh(op_is_refresh), .op_is_write(op_is_write),
        .op_row(op_row), .op_done(op_done), .sweep_active(sweep_active), .cfg_reject(cfg_reject),
        .a_start(a_start), .a_kind(a_kind), .a_row(a_row),
        .q_busy(q_busy), .q_done(q_done), .q_ign(q_ign),
        .pre_en(pre_en), .rwl_sel(rwl_sel), .sense_en(sense_en), .wwl_en(wwl_en),
        .bl_drive(bl_drive), .q_row(q_row));

    // ---------------------------------------------------------------- trace
    integer tracef = 0;
    reg [1023:0] trace_name;
    initial if ($value$plusargs("TRACE=%s", trace_name)) tracef = $fopen(trace_name, "w");

    // ----------------------------------------------------------- scoreboard
    integer cyc = 0;
    integer viol = 0;
    integer n_conf_lost = 0, n_conf_skew = 0;
    task automatic violation(input [8*72-1:0] what, input integer a, input integer b);
        begin
            viol = viol + 1;
            if (viol <= 20) $display("VIOLATION: %0s (c=%0d a=%0d b=%0d)", what, cyc, a, b);
        end
    endtask

    integer L_cnt = 0;
    integer L_cyc [0:MAXL], L_kind [0:MAXL], L_row [0:MAXL];
    integer L_sfall [0:MAXL], L_sdone [0:MAXL];
    integer L_acc [0:MAXL], L_lost [0:MAXL], L_aband [0:MAXL];
    integer L_qstart [0:MAXL], L_qfall [0:MAXL], L_qdone [0:MAXL], L_last [0:MAXL];
    integer A_list [0:MAXL];
    integer A_cnt = 0, seq_started = 0;
    integer cur_l = 0;         // launch whose scheduler busy window is open
    integer q_cur = 0;         // launch currently/most recently in the sequencer
    reg     s_busy_d = 0, q_busy_d = 0, pend_ign = 0, in_rst = 1;
    integer exp_ref_row = 0;
    integer c_pre, c_rwl, c_sense, c_wwl, c_bl, q_t0, q_lastact;
    integer launch_now, start_now;

    // per-kind statistics: 0 READ, 1 WRITE, 2 REFRESH
    integer K_launch [0:2], K_lost [0:2], K_fin [0:2], K_skew [0:2], K_aband [0:2];
    integer K_dact_min [0:2], K_dact_max [0:2], K_dfall_min [0:2], K_dfall_max [0:2];
    integer K_ddone_min [0:2], K_ddone_max [0:2], K_dur_min [0:2], K_dur_max [0:2];
    integer k;
    initial for (k = 0; k < 3; k = k + 1) begin
        K_launch[k] = 0; K_lost[k] = 0; K_fin[k] = 0; K_skew[k] = 0; K_aband[k] = 0;
        K_dact_min[k] = 9999; K_dact_max[k] = -9999; K_dfall_min[k] = 9999; K_dfall_max[k] = -9999;
        K_ddone_min[k] = 9999; K_ddone_max[k] = -9999; K_dur_min[k] = 9999; K_dur_max[k] = -9999;
    end
    integer n_reset_aband = 0, n_hazard_cycles = 0;
    integer K_mgn_min [0:2];
    initial for (k = 0; k < 3; k = k + 1) K_mgn_min[k] = 9999;

    function integer exp_dur(input integer kd);
        case (kd)
            0: exp_dur = P_PRE + P_SENSE + P_GUARD + 2 * GAP;
            1: exp_dur = P_WB + P_GUARD + GAP;
            default: exp_dur = P_PRE + P_SENSE + P_WB + P_GUARD + 3 * GAP;
        endcase
    endfunction

    task automatic finish_seq_op(input integer l);
        integer kd, inf, dur;
        begin
            kd  = L_kind[l];
            dur = L_qfall[l] - L_qstart[l];
            // observed profile versus the sequencer's own parameters and kind
            inf = (c_wwl > 0 && c_pre > 0) ? 2 : (c_wwl > 0 ? 1 : 0);
            if (inf != kd) violation("kind captured by sequencer differs from launch", kd, inf);
            if (dur != exp_dur(kd)) violation("sequencer busy length != expected phase total", dur, exp_dur(kd));
            if (c_pre != ((kd == 1) ? 0 : P_PRE)) violation("precharge cycles", c_pre, P_PRE);
            if (c_rwl != ((kd == 1) ? 0 : P_SENSE)) violation("read-select cycles", c_rwl, P_SENSE);
            if (c_sense != ((kd == 1) ? 0 : 1)) violation("sense strobes", c_sense, 1);
            if (c_wwl != ((kd == 0) ? 0 : P_WB)) violation("write-wordline cycles", c_wwl, P_WB);
            if (c_bl != ((kd == 0) ? 0 : P_WB + P_GUARD + GAP)) violation("bitline-drive cycles", c_bl, P_WB + P_GUARD + GAP);
            L_last[l] = q_lastact;
            K_fin[kd] = K_fin[kd] + 1;
            if (dur < K_dur_min[kd]) K_dur_min[kd] = dur;
            if (dur > K_dur_max[kd]) K_dur_max[kd] = dur;
        end
    endtask

    wire any_strobe = pre_en | rwl_sel | sense_en | wwl_en | bl_drive;

    always @(negedge clk) begin
        cyc = cyc + 1;
        if (tracef != 0)
            $fdisplay(tracef, "%0d rst=%b req=%b/%b/%0d acc=%b | S busy=%b ref=%b wr=%b row=%0d done=%b | A start=%b kind=%0d row=%0d | Q busy=%b done=%b ign=%b pre=%b rwl=%b sns=%b wwl=%b bl=%b row=%0d",
                cyc, rst_n, req_valid, req_we, req_row, req_accept, op_busy, op_is_refresh, op_is_write, op_row,
                op_done, a_start, a_kind, a_row, q_busy, q_done, q_ign, pre_en, rwl_sel, sense_en, wwl_en, bl_drive, q_row);
        if (!rst_n) begin
            // Reset interruption (scoped): in-flight operations are abandoned.
            if (!in_rst) begin
                in_rst = 1;
                if (s_busy_d || q_busy_d) begin
                    n_reset_aband = n_reset_aband + 1;
                    for (k = (L_cnt > 4 ? L_cnt - 3 : 1); k <= L_cnt; k = k + 1)
                        if (!L_aband[k] && ((L_acc[k] && L_qfall[k] == 0) || (k == cur_l && L_sfall[k] == 0))) begin
                            L_aband[k] = 1; K_aband[L_kind[k]] = K_aband[L_kind[k]] + 1;
                        end
                end
                seq_started = A_cnt; s_busy_d = 0; q_busy_d = 0; pend_ign = 0; cur_l = 0;
                exp_ref_row = 0;
            end
            if (op_busy || q_busy || q_done || any_strobe) violation("activity during reset", op_busy, q_busy);
        end else begin
            in_rst = 0;
            launch_now = op_busy && !s_busy_d;
            start_now  = a_start;
            // ---- ignored-start model: q_ign must follow exactly a start into a busy sequencer
            if (q_ign !== pend_ign) violation("start_ignored flag disagrees with start-while-busy", q_ign, pend_ign);
            pend_ign = start_now && q_busy;
            // ---- scheduler launch
            if (launch_now) begin
                L_cnt = L_cnt + 1; cur_l = L_cnt;
                L_cyc[cur_l] = cyc; L_row[cur_l] = op_row;
                L_kind[cur_l] = op_is_refresh ? 2 : (op_is_write ? 1 : 0);
                L_sfall[cur_l] = 0; L_sdone[cur_l] = 0; L_acc[cur_l] = 0; L_lost[cur_l] = 0; L_aband[cur_l] = 0;
                L_qstart[cur_l] = 0; L_qfall[cur_l] = 0; L_qdone[cur_l] = 0; L_last[cur_l] = 0;
                K_launch[L_kind[cur_l]] = K_launch[L_kind[cur_l]] + 1;
                if (L_kind[cur_l] == 2) begin
                    if (op_row != exp_ref_row) violation("scheduler refresh row not round-robin", op_row, exp_ref_row);
                    exp_ref_row = (op_row + 1) % N_ROWS;
                end
            end
            // ---- exactly one start per launch, kind and row mapped
            if (start_now != launch_now) violation("start/launch mismatch (dropped or duplicated start)", start_now, launch_now);
            if (start_now && launch_now) begin
                if (a_kind != L_kind[cur_l]) violation("adapter kind", a_kind, L_kind[cur_l]);
                if (a_row != op_row) violation("adapter row", a_row, op_row);
                if (q_busy) begin
                    L_lost[cur_l] = 1; K_lost[L_kind[cur_l]] = K_lost[L_kind[cur_l]] + 1; n_conf_lost = n_conf_lost + 1;
                    n_hazard_cycles = n_hazard_cycles + 1;
                end else begin
                    L_acc[cur_l] = 1; A_list[A_cnt] = cur_l; A_cnt = A_cnt + 1;
                end
            end
            // ---- scheduler completion
            if (s_busy_d && !op_busy) begin
                L_sfall[cur_l] = cyc;
                if (cyc - L_cyc[cur_l] != (L_kind[cur_l] == 2 ? T_ROW : T_ACC))
                    violation("scheduler busy length", cyc - L_cyc[cur_l], L_kind[cur_l] == 2 ? T_ROW : T_ACC);
            end
            if (op_done) begin
                L_sdone[cur_l] = cyc;
                if (!(s_busy_d && !op_busy)) violation("scheduler done not coincident with busy fall", cyc, L_sfall[cur_l]);
            end
            // ---- sequencer start (actual event)
            if (q_busy && !q_busy_d) begin
                if (seq_started >= A_cnt) violation("sequencer started without an accepted launch", seq_started, A_cnt);
                else begin
                    q_cur = A_list[seq_started]; seq_started = seq_started + 1;
                    L_qstart[q_cur] = cyc;
                    if (cyc != L_cyc[q_cur] + 1) violation("sequencer start not one cycle after launch", cyc, L_cyc[q_cur]);
                    if (q_row != L_row[q_cur]) violation("row captured by sequencer differs from launch", q_row, L_row[q_cur]);
                    c_pre = 0; c_rwl = 0; c_sense = 0; c_wwl = 0; c_bl = 0; q_lastact = 0;
                end
            end
            // ---- strobes
            if (any_strobe && !q_busy) violation("strobe while sequencer idle", cyc, 0);
            if (q_busy) begin
                c_pre = c_pre + pre_en; c_rwl = c_rwl + rwl_sel; c_sense = c_sense + sense_en;
                c_wwl = c_wwl + wwl_en; c_bl = c_bl + bl_drive;
                if (any_strobe) q_lastact = cyc;
            end
            // ---- sequencer completion
            if (q_busy_d && !q_busy) begin
                L_qfall[q_cur] = cyc;
                finish_seq_op(q_cur);
            end
            if (q_done) begin
                L_qdone[q_cur] = cyc;
                if (!(q_busy_d && !q_busy)) violation("sequencer done not coincident with busy fall", cyc, L_qfall[q_cur]);
            end
            s_busy_d = op_busy; q_busy_d = q_busy;
        end
    end

    // Timing deltas versus the scheduler, computed once both sides are known
    // (positive = sequencer later than the scheduler):
    //   d_lastact : last strobe cycle minus the scheduler's last busy cycle
    //   d_busyfall: sequencer busy-fall cycle minus scheduler busy-fall cycle
    //   d_done    : sequencer done cycle minus scheduler done cycle
    task automatic final_checks;
        integer i, kd, dact, dfall, dd;
        begin
            for (i = 1; i <= L_cnt; i = i + 1) begin
                kd = L_kind[i];
                // margin: next launch cycle minus this op's sequencer busy-fall (idle) cycle;
                // 0 = next launch coincides with the done cycle (accepted); < 0 = launch into a busy sequencer
                if (L_acc[i] && L_qfall[i] != 0 && i < L_cnt && L_cyc[i+1] - L_qfall[i] < K_mgn_min[kd])
                    K_mgn_min[kd] = L_cyc[i+1] - L_qfall[i];
                if (L_acc[i] && !L_aband[i] && i < L_cnt && L_qfall[i] == 0)
                    violation("accepted launch never completed in the sequencer", i, kd);
                if (L_acc[i] && L_qfall[i] != 0 && L_sfall[i] != 0 && L_sdone[i] != 0 && L_qdone[i] != 0) begin
                    dact  = L_last[i] - (L_sfall[i] - 1);
                    dfall = L_qfall[i] - L_sfall[i];
                    dd    = L_qdone[i] - L_sdone[i];
                    if (dact  < K_dact_min[kd])  K_dact_min[kd]  = dact;
                    if (dact  > K_dact_max[kd])  K_dact_max[kd]  = dact;
                    if (dfall < K_dfall_min[kd]) K_dfall_min[kd] = dfall;
                    if (dfall > K_dfall_max[kd]) K_dfall_max[kd] = dfall;
                    if (dd < K_ddone_min[kd]) K_ddone_min[kd] = dd;
                    if (dd > K_ddone_max[kd]) K_ddone_max[kd] = dd;
                    if (dact > 0 || dfall > 0 || dd > 0) begin K_skew[kd] = K_skew[kd] + 1; n_conf_skew = n_conf_skew + 1; end
                    if (`VERBOSE)
                        $display("OPTIME l=%0d kind=%0d row=%0d launch=%0d qstart=%0d lastact=%0d sfall=%0d qfall=%0d sdone=%0d qdone=%0d dact=%0d dfall=%0d ddone=%0d",
                                 i, kd, L_row[i], L_cyc[i], L_qstart[i], L_last[i], L_sfall[i], L_qfall[i], L_sdone[i], L_qdone[i], dact, dfall, dd);
                end
            end
            if (A_cnt - seq_started > 1) violation("accepted launches never started", A_cnt, seq_started);
        end
    endtask

    // ------------------------------------------------------------- stimulus
    reg [15:0] lfsr = 16'hACE1;
    reg        traffic_on = 0;
    always @(posedge clk) begin
        #1;
        lfsr <= {lfsr[14:0], lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
        if (traffic_on) begin
            if (!req_valid || req_accept) begin
                req_valid <= 1; req_row <= lfsr[ROW_W-1:0]; req_we <= lfsr[8];
            end
        end
    end

    task automatic wait_n(input integer n);
        begin repeat (n) @(posedge clk); #2; end
    endtask
    task automatic wait_sweep_done;
        integer t;
        begin
            t = 0;
            while ((sweep_active || op_busy) && t < 20000) begin wait_n(1); t = t + 1; end
        end
    endtask
    task automatic one_req(input we, input [ROW_W-1:0] r);
        begin
            req_valid <= 1; req_we <= we; req_row <= r;
            wait_n(1);
            while (!req_accept) wait_n(1);
            req_valid <= 0;
            wait_n(1);
        end
    endtask
    task automatic cfg(input en, input [15:0] ivl, input sw);
        begin
            cfg_en <= en; cfg_interval <= ivl; cfg_sweep <= sw; cfg_valid <= 1;
            wait_n(1);
            cfg_valid <= 0; cfg_sweep <= 0;
        end
    endtask
    task automatic do_reset(input integer len);
        begin
            #1; rst_n <= 0; req_valid <= 0; cfg_valid <= 0;
            wait_n(len);
            rst_n <= 1;
        end
    endtask
    task automatic wait_inflight(input want_refresh, input integer into);
        integer t;
        begin
            t = 0;
            while (!(op_busy && (op_is_refresh == want_refresh) && dut.u_sched.cnt == into) && t < 20000) begin wait_n(1); t = t + 1; end
        end
    endtask

    integer j;
    initial begin
        rst_n = 0;
        wait_n(4);
        rst_n = 1;
        case (SCEN)
            0: begin
                // reset-initialisation sweep: N_ROWS back-to-back REFRESH ops
                wait_sweep_done;
                wait_n(50);
                one_req(0, 5);  wait_n(100);
                one_req(1, 9);  wait_n(100);
                one_req(0, 31); wait_n(100);
                one_req(1, 0);  wait_n(100);
            end
            1: begin
                traffic_on = 1;               // held request during the sweep, then saturating mix
                wait_n(5000);
            end
            2: begin
                traffic_on = 1;
                wait_n(12000);
            end
            3: begin
                traffic_on = 1;
                wait_sweep_done;
                wait_n(500);
                cfg(1, MIN_IVL, 0);           // shorten to the feasibility floor
                wait_n(3000);
                cfg(1, INTERVAL, 0);          // lengthen back
                wait_n(2000);
                cfg(1, INTERVAL, 1);          // forced sweep request
                wait_n(1800);
                wait_inflight(0, 17);         // snapshot applied mid-operation
                cfg(1, MIN_IVL + 100, 0);
                wait_n(2500);
                cfg(1, 16'd100, 0);           // infeasible: refused whole
                wait_n(200);
                cfg(0, INTERVAL, 0);          // disable refresh (data would be lost)
                wait_n(1500);
                cfg(1, INTERVAL, 0);          // re-enable: re-initialisation sweep
                wait_n(1800);
                wait_inflight(1, 11);
                cfg(1, INTERVAL, 1);          // sweep request during a refresh
                wait_n(1800);
            end
            4: begin
                traffic_on = 1;
                wait_sweep_done;
                wait_n(300);
                wait_inflight(0, 9);          // reset in the middle of a READ/WRITE
                do_reset(3);
                wait_n(40);
                wait_inflight(1, 20);         // reset in the middle of a REFRESH
                do_reset(2);
                wait_n(2500);
            end
        endcase
        traffic_on = 0;
        wait_n(2);
        final_checks;
        report;
        $finish;
    end

    task automatic report;
        integer kd;
        reg [8*7-1:0] nm;
        begin
            $display("INFO: scen=%0d P_PRE=%0d P_SENSE=%0d P_WB=%0d P_GUARD=%0d GAP=%0d MUT=%0d T_ROW=%0d T_ACC=%0d cycles=%0d",
                     SCEN, P_PRE, P_SENSE, P_WB, P_GUARD, GAP, MUT, T_ROW, T_ACC, cyc);
            $display("INFO: launches=%0d starts_accepted=%0d lost=%0d reset_abandoned=%0d", L_cnt, A_cnt, n_conf_lost, n_reset_aband);
            for (kd = 0; kd < 3; kd = kd + 1) begin
                nm = (kd == 0) ? "READ   " : (kd == 1) ? "WRITE  " : "REFRESH";
                $write("KIND %0s launches=%0d completed=%0d lost=%0d abandoned=%0d skew=%0d",
                       nm, K_launch[kd], K_fin[kd], K_lost[kd], K_aband[kd], K_skew[kd]);
                if (K_fin[kd] > 0)
                    $write(" dur=%0d..%0d d_lastact=%0d..%0d d_busyfall=%0d..%0d d_done=%0d..%0d",
                           K_dur_min[kd], K_dur_max[kd], K_dact_min[kd], K_dact_max[kd],
                           K_dfall_min[kd], K_dfall_max[kd], K_ddone_min[kd], K_ddone_max[kd]);
                if (K_mgn_min[kd] != 9999) $write(" next_launch_margin_min=%0d", K_mgn_min[kd]);
                $write("\n");
            end
            if (n_conf_lost > 0)
                $display("CONFLICT: LOST %0d launch(es) arrived while phase_seq was busy (next launch before phase completion; start ignored, operation never executed)", n_conf_lost);
            if (n_conf_skew > 0)
                $display("CONFLICT: SKEW %0d accepted op(s) ended after the scheduler's busy fall / done (d_lastact/d_busyfall/d_done > 0)", n_conf_skew);
            if ((n_conf_lost > 0) != (EXP_LOST != 0)) violation("LOST outcome differs from expectation", n_conf_lost, EXP_LOST);
            if ((n_conf_skew > 0) != (EXP_SKEW != 0)) violation("SKEW outcome differs from expectation", n_conf_skew, EXP_SKEW);
            if (SCEN == 3 && !cfg_reject) violation("infeasible snapshot did not set cfg_reject", 0, 0);
            if (SCEN == 4 && n_reset_aband < 2) violation("reset scenario did not interrupt two in-flight operations", n_reset_aband, 2);
            if (L_cnt < 5) violation("too few launches", L_cnt, 5);
            $display("TB_RESULT: %0s (violations=%0d)", viol == 0 ? "PASS" : "FAIL", viol);
        end
    endtask
endmodule
