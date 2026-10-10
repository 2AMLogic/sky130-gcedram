// Coupled scheduler/sequencer bench (issue #138). Behavioral.
//
// DUT: coupled_top.v = refresh_sched_rt (T_ROW/T_ACC DERIVED from the sequencer
// phase durations + launch latency) -> launch_adapter -> phase_seq. The
// uncoupled #135 harness (tb_sched_phase.v) is untouched and stays as the
// characterization control that exhibits the skew / lost launches.
//
// Pre-traffic CONFIGURATION GATE (CHECK_CFG=1): an inconsistent configuration
// prints CONFIG_REJECT and ends the run with TB_RESULT: FAIL before any traffic.
//   * the budgets are not below the sequencer durations + launch latency
//   * the RTL derivation and the Python derivation (coupled_params.py) agree
//   * the scheduler / gc_ctrl_top / spi_slave floors equal the independently
//     recomputed floor N_ROWS*T_ROW + T_ACC + GUARD
//   * the floor does not exceed the interval (infeasible combination)
// CHECK_CFG=0 bypasses the gate (negative controls) so the dynamic monitors
// below must catch the same defect on their own.
//
// Dynamic monitors (sampled at the falling clock edge; independent of the
// scheduler's own bookkeeping; every credit comes from an EXECUTED sequencer
// completion (q_done), never from the scheduler's op_done):
//   * launch discipline: exactly one start per launch, no start into a busy
//     sequencer (a rejected launch / start_ignored is a VIOLATION, never a
//     refreshed row), launch-to-start latency equals the coupling constant LAT
//   * completion order: the scheduler's busy fall / op_done is never earlier
//     than the sequencer's done; the sequencer is idle at that point
//   * profile: observed strobe counts and busy length equal the sequencer parameters
//   * row deadline: every armed row's age since its last executed REFRESH/WRITE
//     completion stays within the interval in force (shortening: the previous
//     value is allowed for T_SETTLE cycles, T_SETTLE recomputed from the
//     effective durations) and within the ratified INTERVAL
//   * coverage: refresh_ok only after every row executed a REFRESH since reset /
//     re-enable (and within T_REARM of them); sweep_done only after every row
//     executed a REFRESH after the latest forced request, within T_SETTLE of it
//   * configuration: applied interval / enable / reject / data_lost follow the
//     independently modelled snapshot rules, floor recomputed here
//
// SCEN: 0 idle + isolated READ/WRITE (eager refresh path)
//       1 saturating READ/WRITE traffic (urgent path)
//       2 runtime configuration transitions under saturating traffic: floor
//         accepted, floor-1 and INTERVAL+1 refused, shorten/lengthen, forced
//         sweep, snapshot mid-op, disable, re-enable, sweep during refresh
//       3 reset interruption (mid access, mid refresh) under saturating traffic
`timescale 1ns/1ps
module tb_coupled #(
    parameter integer SCEN = 0,
    parameter integer P_PRE = 2, P_SENSE = 10, P_WB = 20, P_GUARD = 2, GAP = 0,
    parameter integer N_ROWS = 32, INTERVAL = 5029, GUARD = 2,
    parameter integer LAT_B = 1,             // coupling constant (measured in #135); re-measured below
    parameter integer T_ROW_X = 0, T_ACC_X = 0, GUARD_X = 0,   // underbudget overrides (negative controls)
    parameter integer PY_T_ROW = 0, PY_T_ACC = 0, PY_MIN = 0, PY_SETTLE = 0,   // coupled_params.py
    parameter integer CHECK_CFG = 1,
    parameter integer MUT = 0, MUT_N = 7,
    parameter integer ROW_W = 5
);
    // ---- independently derived expectations (bench-side, from the phase parameters)
    localparam integer B_D_REF = P_PRE + P_SENSE + P_WB + P_GUARD + 3 * GAP;
    localparam integer B_D_RD  = P_PRE + P_SENSE + P_GUARD + 2 * GAP;
    localparam integer B_D_WR  = P_WB + P_GUARD + GAP;
    localparam integer B_D_ACC = (B_D_RD > B_D_WR) ? B_D_RD : B_D_WR;
    localparam integer B_T_ROW_MIN = B_D_REF + LAT_B;
    localparam integer B_T_ACC_MIN = B_D_ACC + LAT_B;
    localparam integer E_T_ROW = (T_ROW_X > 0) ? T_ROW_X : PY_T_ROW;
    localparam integer E_T_ACC = (T_ACC_X > 0) ? T_ACC_X : PY_T_ACC;
    localparam integer G_EFF   = GUARD + N_ROWS + 1;                           // per-op decision cycle accounted
    localparam integer MIN_B   = N_ROWS * E_T_ROW + E_T_ACC + G_EFF;          // recomputed legal floor
    localparam integer SETTLE_B = (E_T_ACC + 1) + N_ROWS * (E_T_ROW + 1) + GUARD;   // shortening bound
    localparam integer T_REARM = SETTLE_B + 4;
    localparam integer MID = (MIN_B + INTERVAL) / 2;
    localparam integer MAXL = 8192;

    reg clk = 0;
    reg rst_n = 0;
    always #5 clk = ~clk;                 // 1 cycle = 1 ns (ASSUMPTION; only the cycle count is used)

    reg              req_valid = 0, req_we = 0;
    reg  [ROW_W-1:0] req_row = 0;
    reg              cfg_valid = 0, cfg_en = 1, cfg_sweep = 0;
    reg  [15:0]      cfg_interval = INTERVAL;
    wire req_accept, op_busy, op_is_refresh, op_is_write, op_done, sweep_active, sweep_done;
    wire en_eff, refresh_ok, data_lost, cfg_reject;
    wire [15:0] ivl_eff;
    wire [ROW_W-1:0] op_row, a_row, q_row;
    wire a_start, q_busy, q_done, q_ign, pre_en, rwl_sel, sense_en, wwl_en, bl_drive;
    wire [1:0] a_kind;

    coupled_top #(.N_ROWS(N_ROWS), .INTERVAL(INTERVAL), .GUARD(GUARD),
        .P_PRE(P_PRE), .P_SENSE(P_SENSE), .P_WB(P_WB), .P_GUARD(P_GUARD), .GAP(GAP), .LAT(LAT_B),
        .T_ROW_X(T_ROW_X), .T_ACC_X(T_ACC_X), .GUARD_X(GUARD_X), .MUT(MUT), .MUT_N(MUT_N), .ROW_W(ROW_W)) dut (
        .clk(clk), .rst_n(rst_n), .req_valid(req_valid), .req_we(req_we), .req_row(req_row),
        .req_accept(req_accept), .cfg_valid(cfg_valid), .cfg_en(cfg_en),
        .cfg_interval(cfg_interval), .cfg_sweep(cfg_sweep),
        .op_busy(op_busy), .op_is_refresh(op_is_refresh), .op_is_write(op_is_write),
        .op_row(op_row), .op_done(op_done), .en_eff(en_eff), .ivl_eff(ivl_eff),
        .sweep_active(sweep_active), .sweep_done(sweep_done), .refresh_ok(refresh_ok),
        .data_lost(data_lost), .cfg_reject(cfg_reject),
        .a_start(a_start), .a_kind(a_kind), .a_row(a_row),
        .q_busy(q_busy), .q_done(q_done), .q_ign(q_ign),
        .pre_en(pre_en), .rwl_sel(rwl_sel), .sense_en(sense_en), .wwl_en(wwl_en),
        .bl_drive(bl_drive), .q_row(q_row));

    // ------------------------------------------------------------ bookkeeping
    integer cyc = 0, viol = 0;
    task automatic violation(input [8*100-1:0] what, input integer a, input integer b);
        begin
            viol = viol + 1;
            if (viol <= 20) $display("VIOLATION: %0s (c=%0d a=%0d b=%0d)", what, cyc, a, b);
        end
    endtask

    // ------------------------------------------------ configuration gate
    integer cfg_bad = 0;
    task automatic gate(input ok, input [8*100-1:0] what, input integer a, input integer b);
        begin
            if (!ok) begin
                cfg_bad = cfg_bad + 1;
                if (CHECK_CFG != 0) $display("CONFIG_REJECT: %0s (a=%0d b=%0d)", what, a, b);
                else $display("CONFIG_BYPASSED: %0s (a=%0d b=%0d)", what, a, b);
            end
        end
    endtask
    task automatic config_gate;
        begin
            gate(PY_T_ROW == B_T_ROW_MIN && PY_T_ACC == B_T_ACC_MIN,
                 "python derivation differs from bench derivation (T_ROW/T_ACC)", PY_T_ROW, B_T_ROW_MIN);
            gate(PY_MIN == N_ROWS * PY_T_ROW + PY_T_ACC + G_EFF, "python floor differs from recomputed floor", PY_MIN, N_ROWS * PY_T_ROW + PY_T_ACC + G_EFF);
            gate(dut.GUARD_C == G_EFF, "scheduler decision guard lacks the per-operation decision cycle", dut.GUARD_C, G_EFF);
            gate(PY_SETTLE == (PY_T_ACC + 1) + N_ROWS * (PY_T_ROW + 1) + GUARD, "python shortening bound differs", PY_SETTLE, 0);
            gate(E_T_ROW >= B_T_ROW_MIN, "T_ROW underbudgeted: below sequencer REFRESH cycles + launch latency", E_T_ROW, B_T_ROW_MIN);
            gate(E_T_ACC >= B_T_ACC_MIN, "T_ACC underbudgeted: below sequencer READ/WRITE cycles + launch latency", E_T_ACC, B_T_ACC_MIN);
            gate(dut.T_ROW_E == E_T_ROW && dut.T_ACC_E == E_T_ACC, "RTL effective T_ROW/T_ACC differ from the expected budgets", dut.T_ROW_E, E_T_ROW);
            gate(dut.u_sched.MIN_INTERVAL == MIN_B, "scheduler feasibility floor is stale", dut.u_sched.MIN_INTERVAL, MIN_B);
            gate(dut.u_ctrl_floor.MIN_INTERVAL == MIN_B, "gc_ctrl_top feasibility floor is stale", dut.u_ctrl_floor.MIN_INTERVAL, MIN_B);
            gate(dut.u_ctrl_floor.u_spi.MIN_INTERVAL == MIN_B, "SPI commit floor is stale", dut.u_ctrl_floor.u_spi.MIN_INTERVAL, MIN_B);
        end
    endtask

    // ----------------------------------------------------------- op tracking
    integer L_cnt = 0, A_cnt = 0, X_cnt = 0, n_aband = 0, n_rej_launch = 0;
    integer l_cyc = 0, l_kind = 0, l_row = 0, q_start = 0, q_fall = 0, q_donec = 0;
    reg     cur_open = 0;          // an accepted operation is in flight
    reg     cur_qdone = 0;
    integer c_pre, c_rwl, c_sense, c_wwl, c_bl;
    reg     s_busy_d = 0, q_busy_d = 0, pend_ign = 0, in_rst = 1;
    integer exp_ref_row = 0, last_qfall = 0;
    integer K_launch [0:2], K_exec [0:2], K_mgn_min [0:2], K_mgn_max [0:2], K_nl_min [0:2];
    integer lat_min = 9999, lat_max = -9999;
    integer k;
    initial for (k = 0; k < 3; k = k + 1) begin
        K_launch[k] = 0; K_exec[k] = 0; K_mgn_min[k] = 9999; K_mgn_max[k] = -9999; K_nl_min[k] = 9999;
    end

    function integer exp_dur(input integer kd);
        case (kd)
            0: exp_dur = B_D_RD;
            1: exp_dur = B_D_WR;
            default: exp_dur = B_D_REF;
        endcase
    endfunction

    // ----------------------------------------------------- deadline / coverage
    integer age [0:N_ROWS-1];
    reg armed [0:N_ROWS-1], initcov [0:N_ROWS-1], swcov [0:N_ROWS-1];
    reg m_en, m_lost, m_rej, sw_pend, rearm_pend, all_ok;
    integer m_ivl, hold_val, hold_until, sw_req, rearm_cyc, D_now, max_age, min_slack, last_over, short_cyc;
    integer trans_max, n_short, n_sweeps, n_rearm, n_reset, n_cfg, n_cfg_rej, n_dis, n_en;
    reg     skip_cfg_cmp;
    integer cfg_ok_b;

    task automatic model_reset;
        begin
            for (k = 0; k < N_ROWS; k = k + 1) begin age[k] = 0; armed[k] = 1; initcov[k] = 0; swcov[k] = 0; end
            m_en = 1; m_ivl = INTERVAL; m_lost = 0; m_rej = 0; sw_pend = 0;
            hold_val = 0; hold_until = 0; last_over = 0; short_cyc = 0;
            rearm_pend = 1; rearm_cyc = cyc;
            skip_cfg_cmp = 0;
        end
    endtask

    task automatic finish_profile;
        integer inf, dur;
        begin
            dur = q_fall - q_start;
            inf = (c_wwl > 0 && c_pre > 0) ? 2 : (c_wwl > 0 ? 1 : 0);
            if (inf != l_kind) violation("kind captured by sequencer differs from launch", l_kind, inf);
            if (dur != exp_dur(l_kind)) violation("sequencer busy length != expected phase total", dur, exp_dur(l_kind));
            if (c_pre != ((l_kind == 1) ? 0 : P_PRE)) violation("precharge cycles", c_pre, P_PRE);
            if (c_rwl != ((l_kind == 1) ? 0 : P_SENSE)) violation("read-select cycles", c_rwl, P_SENSE);
            if (c_sense != ((l_kind == 1) ? 0 : 1)) violation("sense strobes", c_sense, 1);
            if (c_wwl != ((l_kind == 0) ? 0 : P_WB)) violation("write-wordline cycles", c_wwl, P_WB);
            if (c_bl != ((l_kind == 0) ? 0 : P_WB + P_GUARD + GAP)) violation("bitline-drive cycles", c_bl, P_WB + P_GUARD + GAP);
        end
    endtask

    wire any_strobe = pre_en | rwl_sel | sense_en | wwl_en | bl_drive;
    integer launch_now, start_now;

    always @(negedge clk) begin
        cyc = cyc + 1;
        if (!rst_n) begin
            if (!in_rst) begin
                in_rst = 1; n_reset = n_reset + 1;
                if (cur_open || s_busy_d || q_busy_d) begin n_aband = n_aband + 1; end
                cur_open = 0; cur_qdone = 0; s_busy_d = 0; q_busy_d = 0; pend_ign = 0; exp_ref_row = 0;
            end
            model_reset;
            if (op_busy || q_busy || q_done || any_strobe) violation("activity during reset", op_busy, q_busy);
        end else begin
            in_rst = 0;
            launch_now = op_busy && !s_busy_d;
            start_now  = a_start;
            // ---- start_ignored may never fire: a rejected launch is an integration failure
            if (q_ign !== pend_ign) violation("start_ignored flag disagrees with start-while-busy", q_ign, pend_ign);
            if (q_ign) begin n_rej_launch = n_rej_launch + 1; violation("REJECTED LAUNCH: sequencer ignored a start (operation not executed)", cyc, 0); end
            pend_ign = start_now && q_busy;
            // ---- scheduler launch
            if (launch_now) begin
                L_cnt = L_cnt + 1;
                if (cur_open) violation("launch before the previous operation was executed", L_cnt, 0);
                l_cyc = cyc; l_row = op_row; l_kind = op_is_refresh ? 2 : (op_is_write ? 1 : 0);
                K_launch[l_kind] = K_launch[l_kind] + 1;
                if (l_kind == 2) begin
                    if (op_row != exp_ref_row) violation("scheduler refresh row not round-robin", op_row, exp_ref_row);
                    exp_ref_row = (op_row + 1) % N_ROWS;
                end
            end
            if (start_now != launch_now) violation("start/launch mismatch (dropped or duplicated start)", start_now, launch_now);
            if (start_now && launch_now) begin
                if (a_kind != l_kind) violation("adapter kind", a_kind, l_kind);
                if (a_row != op_row) violation("adapter row", a_row, op_row);
                if (q_busy) violation("LAUNCH INTO BUSY SEQUENCER (budget shorter than sequencer)", cyc, last_qfall);
                else begin
                    A_cnt = A_cnt + 1; cur_open = 1; cur_qdone = 0;
                    if (last_qfall != 0 && cyc - last_qfall < K_nl_min[l_kind]) K_nl_min[l_kind] = cyc - last_qfall;
                end
            end
            // ---- sequencer start
            if (q_busy && !q_busy_d) begin
                if (!cur_open) violation("sequencer started without an accepted launch", cyc, 0);
                else begin
                    q_start = cyc;
                    if (cyc - l_cyc < lat_min) lat_min = cyc - l_cyc;
                    if (cyc - l_cyc > lat_max) lat_max = cyc - l_cyc;
                    if (cyc - l_cyc != LAT_B) violation("launch-to-start latency differs from the coupling constant LAT", cyc - l_cyc, LAT_B);
                    if (q_row != l_row) violation("row captured by sequencer differs from launch", q_row, l_row);
                    c_pre = 0; c_rwl = 0; c_sense = 0; c_wwl = 0; c_bl = 0;
                end
            end
            if (cur_open && !q_busy && !q_busy_d && cyc > l_cyc + 1 && q_start < l_cyc)
                violation("accepted launch did not start the sequencer (ignored)", cyc, l_cyc);
            // ---- strobes
            if (any_strobe && !q_busy) violation("strobe while sequencer idle", cyc, 0);
            if (q_busy) begin
                c_pre = c_pre + pre_en; c_rwl = c_rwl + rwl_sel; c_sense = c_sense + sense_en;
                c_wwl = c_wwl + wwl_en; c_bl = c_bl + bl_drive;
            end
            // ---- sequencer completion = EXECUTED completion
            if (q_busy_d && !q_busy) begin
                q_fall = cyc; last_qfall = cyc;
                if (cur_open) finish_profile;
            end
            for (k = 0; k < N_ROWS; k = k + 1) age[k] = age[k] + 1;
            if (q_done) begin
                if (!(q_busy_d && !q_busy)) violation("sequencer done not coincident with busy fall", cyc, q_fall);
                if (!cur_open) violation("sequencer done without an accepted launch", cyc, 0);
                else begin
                    q_donec = cyc; cur_qdone = 1; X_cnt = X_cnt + 1; K_exec[l_kind] = K_exec[l_kind] + 1;
                    if (l_kind >= 1) begin age[l_row] = 0; armed[l_row] = 1; end     // WRITE or REFRESH restores the row
                    if (l_kind == 2) begin initcov[l_row] = 1; swcov[l_row] = 1; end
                end
            end
            // ---- scheduler completion must not precede the executed completion
            if (s_busy_d && !op_busy) begin
                if (cyc - l_cyc != (l_kind == 2 ? E_T_ROW : E_T_ACC))
                    violation("scheduler busy length", cyc - l_cyc, l_kind == 2 ? E_T_ROW : E_T_ACC);
                if (q_busy) violation("SCHEDULER COMPLETES WHILE SEQUENCER STILL BUSY", cyc, q_start);
            end
            if (op_done) begin
                if (!(s_busy_d && !op_busy)) violation("scheduler done not coincident with busy fall", cyc, 0);
                if (!cur_open || !cur_qdone) violation("SCHEDULER COMPLETION PRECEDES SEQUENCER COMPLETION", cyc, q_donec);
                else begin
                    if (cyc - q_donec < K_mgn_min[l_kind]) K_mgn_min[l_kind] = cyc - q_donec;
                    if (cyc - q_donec > K_mgn_max[l_kind]) K_mgn_max[l_kind] = cyc - q_donec;
                    cur_open = 0; cur_qdone = 0;
                end
            end
            s_busy_d = op_busy; q_busy_d = q_busy;

            // ---- configuration model: applied state follows the snapshot rules
            if (!skip_cfg_cmp) begin
                if (ivl_eff !== m_ivl[15:0]) violation("applied interval differs from model (floor / range handling)", ivl_eff, m_ivl);
                if (en_eff !== m_en) violation("applied enable differs from model", en_eff, m_en);
                if (cfg_reject !== m_rej) violation("cfg_reject differs from model (infeasible snapshot not refused or feasible refused)", cfg_reject, m_rej);
                if (data_lost !== m_lost) violation("data_lost differs from model", data_lost, m_lost);
            end
            skip_cfg_cmp = 0;
            if (cfg_valid) begin
                n_cfg = n_cfg + 1;
                skip_cfg_cmp = 1;
                cfg_ok_b = (cfg_interval >= MIN_B) && (cfg_interval <= INTERVAL);   // floor recomputed from the durations
                if (!cfg_ok_b) begin m_rej = 1; n_cfg_rej = n_cfg_rej + 1; end
                else begin
                    if (cfg_interval < m_ivl) begin
                        if (!(cyc < hold_until && hold_val > m_ivl)) hold_val = m_ivl;
                        hold_until = cyc + SETTLE_B; short_cyc = cyc; n_short = n_short + 1;
                    end
                    if (m_en && !cfg_en) begin m_lost = 1; n_dis = n_dis + 1; end
                    if (!m_en && cfg_en) begin
                        for (k = 0; k < N_ROWS; k = k + 1) begin armed[k] = 0; initcov[k] = 0; end
                        rearm_pend = 1; rearm_cyc = cyc; n_en = n_en + 1;
                    end
                    if (cfg_sweep) begin
                        for (k = 0; k < N_ROWS; k = k + 1) swcov[k] = 0;
                        sw_pend = 1; sw_req = cyc;
                    end
                    m_ivl = cfg_interval; m_en = cfg_en;
                end
            end

            // ---- independent per-row deadline (executed completions only)
            D_now = (cyc < hold_until && hold_val > m_ivl) ? hold_val : m_ivl;
            if (m_en) begin
                max_age = 0;
                for (k = 0; k < N_ROWS; k = k + 1) if (armed[k]) begin
                    if (age[k] > max_age) max_age = age[k];
                    if (age[k] > D_now) begin
                        violation("ROW DEADLINE: executed-refresh age exceeds the interval in force", k, age[k]);
                    end
                    if (age[k] > INTERVAL) violation("ROW DEADLINE: age exceeds the ratified interval", k, age[k]);
                    if (age[k] > m_ivl && short_cyc != 0) last_over = cyc;
                end
                if (D_now - max_age < min_slack) min_slack = D_now - max_age;
                if (short_cyc != 0 && last_over > short_cyc && last_over - short_cyc > trans_max) trans_max = last_over - short_cyc;
            end
            // ---- coverage
            all_ok = 1;
            for (k = 0; k < N_ROWS; k = k + 1) if (!initcov[k]) all_ok = 0;
            if (refresh_ok && !all_ok) violation("refresh_ok before every row executed a refresh (init/re-enable)", cyc, 0);
            if (rearm_pend && (cyc - rearm_cyc) > T_REARM) begin
                if (m_en && !(all_ok && refresh_ok)) violation("initialisation sweep did not execute every row in time", cyc - rearm_cyc, T_REARM);
                else n_rearm = n_rearm + 1;
                rearm_pend = 0;
            end
            if (sweep_done) begin
                if (!sw_pend) violation("spurious sweep_done", cyc, 0);
                else begin
                    all_ok = 1;
                    for (k = 0; k < N_ROWS; k = k + 1) if (!swcov[k]) all_ok = 0;
                    if (!all_ok) violation("sweep_done before every row executed a refresh after the request", cyc, 0);
                    sw_pend = 0; n_sweeps = n_sweeps + 1;
                end
            end
            if (sw_pend && cyc - sw_req > T_REARM) begin
                violation("forced sweep not completed within the bound", cyc - sw_req, T_REARM);
                sw_pend = 0;
            end
        end
    end

    // --------------------------------------------------------------- stimulus
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

    initial begin
        n_cfg = 0; n_cfg_rej = 0; n_short = 0; n_sweeps = 0; n_rearm = 0; n_reset = 0; n_dis = 0; n_en = 0;
        trans_max = 0; min_slack = 1 << 30; max_age = 0; skip_cfg_cmp = 1;
        model_reset;
        #1;
        if (MIN_B > INTERVAL || INTERVAL > 65535) begin       // infeasible: never bypassable
            $display("CONFIG_REJECT: infeasible: floor exceeds the interval (a=%0d b=%0d)", MIN_B, INTERVAL);
            $display("TB_RESULT: FAIL (infeasible duration/interval combination rejected before traffic)");
            $finish;
        end
        config_gate;
        if (CHECK_CFG != 0 && cfg_bad != 0) begin
            $display("CONFIG: T_ROW=%0d T_ACC=%0d (min %0d/%0d) floor=%0d INTERVAL=%0d", E_T_ROW, E_T_ACC, B_T_ROW_MIN, B_T_ACC_MIN, MIN_B, INTERVAL);
            $display("TB_RESULT: FAIL (configuration rejected before traffic: %0d finding(s))", cfg_bad);
            $finish;
        end
        wait_n(3);
        rst_n = 1;
        case (SCEN)
            0: begin
                wait_sweep_done;
                wait_n(50);
                one_req(0, 5);  wait_n(100);
                one_req(1, 9);  wait_n(100);
                one_req(0, 31); wait_n(100);
                one_req(1, 0);  wait_n(100);
                wait_n(3 * INTERVAL);          // idle: eager refresh keeps every row within the interval
            end
            1: begin
                traffic_on = 1;
                wait_n(2 * INTERVAL + 2000);
            end
            2: begin
                traffic_on = 1;
                wait_sweep_done;
                wait_n(500);
                cfg(1, MIN_B, 0);                 // floor itself is accepted (shorten under saturated traffic)
                wait_n(3000);
                cfg(1, MIN_B - 1, 0);             // one below the recomputed floor: refused whole
                wait_n(300);
                cfg(1, INTERVAL + 1, 0);          // above the ratified bound: refused whole
                wait_n(300);
                cfg(1, INTERVAL, 0);              // lengthen back
                wait_n(2000);
                cfg(1, MID, 0);                   // intermediate shortening
                wait_n(2000);
                cfg(1, INTERVAL, 1);              // forced sweep request
                wait_n(SETTLE_B + 300);
                wait_inflight(0, 3);              // snapshot applied mid-operation
                cfg(1, MIN_B + 100, 0);
                wait_n(2500);
                cfg(0, INTERVAL, 0);              // disable refresh
                wait_n(1500);
                cfg(1, MIN_B, 0);                 // re-enable straight onto the floor interval
                wait_n(SETTLE_B + 1500);
                cfg(1, INTERVAL, 0);
                wait_n(1500);
                wait_inflight(1, 5);
                cfg(1, INTERVAL, 1);              // sweep request during a refresh
                wait_n(SETTLE_B + 300);
            end
            3: begin
                traffic_on = 1;
                wait_sweep_done;
                wait_n(300);
                wait_inflight(0, 3);              // reset in the middle of a READ/WRITE
                do_reset(3);
                wait_n(40);
                wait_inflight(1, 8);              // reset in the middle of a REFRESH
                do_reset(2);
                wait_n(SETTLE_B + 500);
                cfg(1, MIN_B, 0);                 // shorten, then reset restores the ratified interval
                wait_n(500);
                do_reset(2);
                wait_n(2 * INTERVAL);
            end
        endcase
        traffic_on = 0;
        wait_n(2);
        report;
        $finish;
    end

    task automatic report;
        integer kd;
        reg [8*7-1:0] nm;
        begin
            $display("INFO: scen=%0d P_PRE=%0d P_SENSE=%0d P_WB=%0d P_GUARD=%0d GAP=%0d INTERVAL=%0d cycles=%0d",
                     SCEN, P_PRE, P_SENSE, P_WB, P_GUARD, GAP, INTERVAL, cyc);
            $display("CONFIG: T_ROW=%0d T_ACC=%0d (min %0d/%0d, LAT=%0d, observed launch->start %0d..%0d) floor=%0d shorten_bound=%0d cfg_gate=%0s",
                     E_T_ROW, E_T_ACC, B_T_ROW_MIN, B_T_ACC_MIN, LAT_B, lat_min, lat_max, MIN_B, SETTLE_B, (cfg_bad == 0) ? "ok" : "BYPASSED");
            $display("INFO: launches=%0d accepted=%0d executed=%0d rejected=%0d reset_abandoned=%0d", L_cnt, A_cnt, X_cnt, n_rej_launch, n_aband);
            for (kd = 0; kd < 3; kd = kd + 1) begin
                nm = (kd == 0) ? "READ   " : (kd == 1) ? "WRITE  " : "REFRESH";
                $write("KIND %0s launches=%0d executed=%0d", nm, K_launch[kd], K_exec[kd]);
                if (K_exec[kd] > 0)
                    $write(" sched_minus_seq_done=%0d..%0d", K_mgn_min[kd], K_mgn_max[kd]);
                if (K_nl_min[kd] != 9999) $write(" next_launch_margin_min=%0d", K_nl_min[kd]);
                $write("\n");
            end
            $display("DEADLINE: min_slack=%0d cycles; shortenings=%0d max_transition_over_new_interval=%0d (bound %0d); forced_sweeps_done=%0d rearm_ok=%0d resets=%0d cfg=%0d refused=%0d disables=%0d enables=%0d",
                     min_slack, n_short, trans_max, SETTLE_B, n_sweeps, n_rearm, n_reset, n_cfg, n_cfg_rej, n_dis, n_en);
            if (SCEN == 2) begin
                if (n_cfg_rej < 2) violation("scenario 2 did not exercise refused snapshots", n_cfg_rej, 2);
                if (n_sweeps < 2) violation("scenario 2 did not complete its forced sweeps", n_sweeps, 2);
                if (n_en < 1 || n_dis < 1) violation("scenario 2 did not exercise disable/re-enable", n_dis, n_en);
                if (n_short < 2) violation("scenario 2 did not exercise interval shortening", n_short, 2);
                if (trans_max > SETTLE_B) violation("shortening transition longer than the recomputed bound", trans_max, SETTLE_B);
            end
            if (SCEN == 3 && n_aband < 2) violation("reset scenario did not interrupt two in-flight operations", n_aband, 2);
            if (L_cnt < 5) violation("too few launches", L_cnt, 5);
            if (L_cnt - X_cnt - n_aband > 1) violation("launched operations never executed", L_cnt, X_cnt);
            if (K_exec[2] == 0) violation("no executed refresh", 0, 0);
            $display("TB_RESULT: %0s (violations=%0d)", viol == 0 ? "PASS" : "FAIL", viol);
        end
    endtask
endmodule
