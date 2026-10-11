// Self-checking SPI -> scheduler -> launch adapter -> phase sequencer bench
// (issue #146). Behavioral, PROPOSED. Real SPI frames configure the ONLY
// scheduler (gc_ctrl_top) while saturated foreground traffic and refresh drive
// the unchanged launch adapter and phase_seq (spi_sched_phase_top.v).
//
// Independent scoreboard. Everything below is derived from sampled port events
// at the falling clock edge and the bench's own model of what it sent over SPI;
// the DUT's refresh_ok / sweep_done / busy flags are cross-checked against it,
// never used to define a completion:
//   * Sequencer execution = q_busy rise..fall, kind inferred from the observed
//     strobe profile, row from q_row. A refresh completes (row timestamp) at
//     the q_busy fall. A scheduler dispatch (op_busy rise) is NOT a refresh.
//   * FINDING DROPPED_LAUNCH     a scheduler launch with no sequencer execution
//                                one LAT later (adapter drop, ignored start)
//   * FINDING SPURIOUS_EXEC      a sequencer execution with no launch
//   * FINDING START_IGNORED      start while the sequencer was busy
//   * FINDING BUDGET_UNDER       scheduler declared the op finished (op_busy
//                                fell) while the sequencer was still busy
//   * FINDING KIND_MISMATCH / ROW_MISMATCH / ROW_UNSTABLE / PROFILE / ORDER
//                                kind, row, phase ordering and durations
//   * FINDING ACCESS_*           accepted foreground request vs executed op
//   * FINDING REFRESH_ORDER      refresh rows are round-robin from row 0
//   * FINDING DEADLINE           per-row age (since sequencer completion of the
//                                last refresh) above the SPI-committed interval
//                                (previous value allowed for T_SETTLE after a
//                                shortening) or above the ratified INTERVAL
//   * FINDING SWEEP_*            each accepted START_SWEEP refreshes every row
//                                (sequencer completions) within T_SWEEP and
//                                yields exactly one sweep_done
//   * FINDING REARM / OK_EARLY   re-enable / reset liveness; refresh_ok high
//                                before every row completed a refresh
//   * FINDING NOT_APPLIED / PARTIAL / CFG_REJECT   SPI-committed vs applied
//   * FINDING REFRESH_WHILE_DISABLED
// The first FINDING line is what the negative controls assert on.
`timescale 1ns/1ps
module tb_spi_sched_phase;
    parameter integer N_ROWS = 32;
    parameter integer INTERVAL = 5029;
    parameter integer GUARD = 2;
    parameter integer P_PRE = 2, P_SENSE = 10, P_WB = 20, P_GUARD = 2, GAP = 0;
    // values derived by coupled_params.py (independent of the RTL)
    parameter integer PY_D_REF = 34, PY_D_RD = 14, PY_D_WR = 22;
    parameter integer PY_T_ROW = 35, PY_T_ACC = 23, PY_GUARD_EFF = 35;
    parameter integer PY_MIN = 1178, PY_SETTLE = 1178;
    parameter integer LAT = 1;
    parameter integer SCLK_HALF_PS = 3700;   // SPI clock half period, ps
    parameter integer PHASE_PS = 130;        // offset of the SPI master timeline vs clk, ps
    parameter integer TRAFFIC = 3;           // 1 saturating reads, 3 saturating random read/write
    parameter integer SEED = 32'h1badcafe;
    parameter integer CHECK_CFG = 1;         // 0 bypasses the pre-traffic gate (negative controls)
    parameter integer T_ROW_X = 0, T_ACC_X = 0, GUARD_X = 0;
    parameter integer MUT = 0, MUT_N = 7;
    parameter integer FAST = 0;              // 1: fewer repetitions
    parameter integer STOP_FIRST = 0;        // 1: end the run at the first finding (negative controls, mutation)
    localparam integer ROW_W = (N_ROWS > 1) ? $clog2(N_ROWS) : 1;
    localparam real H    = SCLK_HALF_PS / 1000.0;
    localparam real PH   = PHASE_PS / 1000.0;
    localparam real TCSH = 4.25;             // cs_n high between frames (>= 4 clk, CONTRACT.md)
    localparam integer T_XFER  = 6;          // commit -> applied, cycles (CONTRACT.md)
    localparam integer T_SWEEP = T_XFER + PY_SETTLE;
    localparam integer T_REARM = T_SWEEP;
    localparam integer MID = (PY_MIN + INTERVAL) / 2;
    localparam [6:0] A_ID=0, A_CTRL=1, A_CMD=2, A_IL=3, A_IH=4, A_ST=5, A_XST=6;

    reg clk = 0, rst_n = 1, sclk = 0, cs_n = 1, mosi = 0;
    always #0.5 clk = ~clk;                  // 1 cycle = 1 ns (ASSUMPTION inherited from the scheduler)

    reg req_valid = 0, req_we = 0; reg [ROW_W-1:0] req_row = 0;
    wire miso, req_accept, op_busy, op_is_refresh, op_is_write, op_done;
    wire en_eff, sweep_active, sweep_done, refresh_ok, data_lost, cfg_reject, busy;
    wire [ROW_W-1:0] op_row; wire [15:0] ivl_eff;
    wire a_start, q_busy, q_done, q_ign, pre_en, rwl_sel, sense_en, wwl_en, bl_drive;
    wire [1:0] a_kind; wire [ROW_W-1:0] a_row, q_row;

    spi_sched_phase_top #(.N_ROWS(N_ROWS), .INTERVAL(INTERVAL), .GUARD(GUARD),
        .P_PRE(P_PRE), .P_SENSE(P_SENSE), .P_WB(P_WB), .P_GUARD(P_GUARD), .GAP(GAP), .LAT(LAT),
        .T_ROW_X(T_ROW_X), .T_ACC_X(T_ACC_X), .GUARD_X(GUARD_X), .MUT(MUT), .MUT_N(MUT_N), .ROW_W(ROW_W)) dut (
        .clk(clk), .rst_n(rst_n), .sclk(sclk), .cs_n(cs_n), .mosi(mosi), .miso(miso),
        .req_valid(req_valid), .req_we(req_we), .req_row(req_row), .req_accept(req_accept),
        .op_busy(op_busy), .op_is_refresh(op_is_refresh), .op_is_write(op_is_write), .op_row(op_row), .op_done(op_done),
        .en_eff(en_eff), .ivl_eff(ivl_eff), .sweep_active(sweep_active), .sweep_done(sweep_done),
        .refresh_ok(refresh_ok), .data_lost(data_lost), .cfg_reject(cfg_reject), .busy(busy),
        .a_start(a_start), .a_kind(a_kind), .a_row(a_row),
        .q_busy(q_busy), .q_done(q_done), .q_ign(q_ign),
        .pre_en(pre_en), .rwl_sel(rwl_sel), .sense_en(sense_en), .wwl_en(wwl_en), .bl_drive(bl_drive), .q_row(q_row));

    // SPI-committed state (protocol model registers), observed only
    wire        spi_en  = dut.u_ctrl.u_spi.refresh_en;
    wire [15:0] spi_ivl = dut.u_ctrl.u_spi.interval;
    wire        spi_tog = dut.u_ctrl.u_spi.sweep_tog;

    // ---------------- bookkeeping ----------------
    integer errors = 0, checks = 0, cyc = 0, k;
    integer n_find = 0;
    task finding(input [255:0] tag, input integer a, input integer b);
        begin
            errors = errors + 1; n_find = n_find + 1;
            if (n_find <= 40) $display("FINDING %0s: a=%0d b=%0d (cycle %0d)", tag, a, b, cyc);
            if (STOP_FIRST != 0) begin $display("TB_RESULT: FAIL (first finding)"); $finish; end
        end
    endtask
    task check(input [255:0] name, input [31:0] got, input [31:0] exp);
        begin checks = checks + 1;
            if (got !== exp) begin
                errors = errors + 1; n_find = n_find + 1;
                if (n_find <= 40) $display("FINDING CHECK_%0s: got %0h expected %0h (cycle %0d)", name, got, exp, cyc);
                if (STOP_FIRST != 0) begin $display("TB_RESULT: FAIL (first finding)"); $finish; end
            end
        end
    endtask

    // counters
    integer n_launch = 0, n_exec = 0, n_abandon = 0, n_resets = 0;
    integer n_exec_k [0:2];
    integer n_sacc = 0, n_sdone = 0, n_ign = 0, n_scancel = 0;
    integer ref_cnt [0:N_ROWS-1];
    // scoreboard state
    reg op_busy_p, q_busy_p;
    reg pend_v; integer pend_cyc; reg [1:0] pend_kind; reg [ROW_W-1:0] pend_row;
    reg in_op; reg [1:0] cur_kind; reg [ROW_W-1:0] cur_row; integer plen, lastph, q_fall_cyc;
    integer pcnt [1:3]; integer sense_cnt; reg [1:0] dkind;
    integer sch_start, exp_ref_row;
    integer age [0:N_ROWS-1];
    reg armed [0:N_ROWS-1], suspect [0:N_ROWS-1], initcov [0:N_ROWS-1], swcov [0:N_ROWS-1];
    reg c_en, c_tog, dis_since_reset; reg [15:0] c_ivl;
    integer last_change = 0, hold_val = 0, hold_until = 0, enable_cyc = 0, dis_cyc = 0;
    integer sweep_chk = 0, sweep_dl = 0, sweep_acc = 0, sd_base = 0, sweep_done_seen = 0;
    integer cur_max_age = 0, D;
    reg [16:0] hist [0:4095]; integer nh = 0, h; reg found;
    reg [16:0] eff_q;
    reg conv_rep, all_cov, rearm_rep;
    integer pcount;
    // observations
    integer min_slack = 1 << 30, max_age_obs = 0, max_apply_lat = 0, max_sweep_lat = 0;
    integer min_margin [0:2]; integer len_obs [0:2]; integer sch_len_obs [0:2];
    integer n_shorten = 0, short_cyc = 0, short_new = 0, trans_obs = 0, lat_obs_min = 99, lat_obs_max = -1;
    integer sd_gap_min = 1 << 30;

    task hist_add(input [16:0] p);
        begin if (nh < 4096) begin hist[nh] = p; nh = nh + 1; end end
    endtask

    // expectation model of what the bench sent over SPI (not read from the DUT)
    reg [15:0] exp_ivl; reg exp_en, exp_lost;

    task bench_reset;   // called while rst_n is low
        begin
            for (k = 0; k < N_ROWS; k = k + 1) begin
                age[k] = 0; armed[k] = 1; suspect[k] = 0; initcov[k] = 0; swcov[k] = 0;
            end
            c_en = 1; c_ivl = INTERVAL; c_tog = 0; dis_since_reset = 0;
            last_change = cyc; hold_val = 0; hold_until = 0; enable_cyc = cyc; dis_cyc = 0;
            if (sweep_chk != 0) n_scancel = n_scancel + 1;
            sweep_chk = 0; conv_rep = 0; rearm_rep = 0;
            if (pend_v) n_abandon = n_abandon + 1;
            if (in_op) n_abandon = n_abandon + 1;
            pend_v = 0; in_op = 0; op_busy_p = 0; q_busy_p = 0; exp_ref_row = 0; q_fall_cyc = cyc;
            hist_add({1'b1, INTERVAL[15:0]}); eff_q = {1'b1, INTERVAL[15:0]};
            exp_ivl = INTERVAL; exp_en = 1; exp_lost = 0;
        end
    endtask

    // ---------------- foreground traffic: saturated ----------------
    reg [31:0] rng; integer sat_rowctr = 0; reg traffic_on = 0;
    function [31:0] xs(input [31:0] s);
        reg [31:0] x; begin
            x = s; x = x ^ (x << 13); x = x ^ (x >> 17); x = x ^ (x << 5); xs = x;
        end
    endfunction
    always @(posedge clk) rng <= xs(rng);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) req_valid <= 0;
        else if (req_accept) req_valid <= 0;
        else if (!req_valid && traffic_on) begin
            req_valid <= 1;
            if (TRAFFIC == 1) begin req_we <= 0; req_row <= sat_rowctr % N_ROWS; sat_rowctr <= sat_rowctr + 1; end
            else begin req_we <= rng[7]; req_row <= rng[20:12] % N_ROWS; end
        end
    end

    // ---------------- independent scoreboard ----------------
    reg launch, qrise, qfall, sfall;
    always @(negedge clk) if (rst_n) begin
        cyc = cyc + 1;
        launch = op_busy && !op_busy_p;
        sfall  = !op_busy && op_busy_p;
        qrise  = q_busy && !q_busy_p;
        qfall  = !q_busy && q_busy_p;

        // ---- SPI-committed configuration changes (bench-observed protocol registers)
        if (spi_en !== c_en || spi_ivl !== c_ivl) begin
            hist_add({spi_en, spi_ivl});
            if (spi_ivl < c_ivl) begin
                if (!(cyc < hold_until && hold_val > c_ivl)) hold_val = c_ivl;
                hold_until = cyc + T_XFER + PY_SETTLE;
                n_shorten = n_shorten + 1; short_cyc = cyc; short_new = spi_ivl;
            end
            if (!c_en && spi_en) begin
                enable_cyc = cyc; rearm_rep = 0;
                for (k = 0; k < N_ROWS; k = k + 1) begin armed[k] = 0; initcov[k] = 0; end
            end
            if (c_en && !spi_en) begin dis_cyc = cyc; if (!dis_since_reset) dis_since_reset = 1; end
            c_en = spi_en; c_ivl = spi_ivl; last_change = cyc; conv_rep = 0;
        end
        // ---- START_SWEEP accepted by the protocol model
        if (spi_tog !== c_tog) begin
            c_tog = spi_tog; n_sacc = n_sacc + 1;
            if (sweep_chk != 0) finding("SWEEP_ACCEPT_WHILE_PENDING", n_sacc, sweep_acc);
            sweep_chk = 1; sweep_acc = cyc; sweep_dl = cyc + T_SWEEP; sd_base = n_sdone; sweep_done_seen = 0;
            for (k = 0; k < N_ROWS; k = k + 1) swcov[k] = 0;
        end

        // ---- scheduler launch (dispatch; NOT a completion)
        if (launch) begin
            n_launch = n_launch + 1;
            if (pend_v) finding("LAUNCH_OVERRUN", pend_cyc, cyc);
            pend_v = 1; pend_cyc = cyc; pend_row = op_row;
            pend_kind = op_is_refresh ? 2'd2 : (op_is_write ? 2'd1 : 2'd0);
            sch_start = cyc;
            if (op_is_refresh) begin
                if (req_accept) finding("REFRESH_WITH_ACCEPT", op_row, 0);
                if (op_row !== exp_ref_row[ROW_W-1:0]) finding("REFRESH_ORDER", op_row, exp_ref_row);
                exp_ref_row = (op_row + 1) % N_ROWS;
                if (!c_en && cyc - dis_cyc > T_XFER + PY_SETTLE && sweep_chk == 0)
                    finding("REFRESH_WHILE_DISABLED", cyc, dis_cyc);
            end else begin
                if (!req_accept) finding("ACCESS_NO_ACCEPT", op_row, 0);
                else if (op_row !== req_row || op_is_write !== req_we) finding("ACCESS_MISMATCH", op_row, req_row);
            end
        end else if (req_accept) finding("ACCEPT_WITHOUT_LAUNCH", req_row, 0);

        // ---- sequencer execution
        if (q_ign) begin n_ign = n_ign + 1; finding("START_IGNORED", cyc, 0); end
        if (qrise) begin
            if (!pend_v) finding("SPURIOUS_EXEC", q_row, 0);
            else begin
                if (cyc - pend_cyc < lat_obs_min) lat_obs_min = cyc - pend_cyc;
                if (cyc - pend_cyc > lat_obs_max) lat_obs_max = cyc - pend_cyc;
                if (cyc - pend_cyc != LAT) finding("LAUNCH_LATENCY", cyc - pend_cyc, LAT);
                in_op = 1; cur_kind = pend_kind; cur_row = pend_row; pend_v = 0;
                plen = 0; lastph = 0; pcnt[1] = 0; pcnt[2] = 0; pcnt[3] = 0; sense_cnt = 0;
            end
        end
        if (pend_v && cyc - pend_cyc >= LAT && !(qrise)) begin
            finding("DROPPED_LAUNCH", pend_row, pend_kind); pend_v = 0;
        end
        if (q_busy && in_op) begin
            plen = plen + 1;
            pcount = pre_en + rwl_sel + wwl_en;
            if (pcount > 1) finding("STROBE_OVERLAP", pcount, 0);
            if (sense_en && !rwl_sel) finding("SENSE_OUTSIDE_RWL", 0, 0);
            if (q_row !== cur_row) finding("ROW_UNSTABLE", q_row, cur_row);
            if (pre_en || rwl_sel || wwl_en) begin
                k = pre_en ? 1 : (rwl_sel ? 2 : 3);
                if (k < lastph) finding("PHASE_ORDER", k, lastph);
                lastph = k; pcnt[k] = pcnt[k] + 1;
            end
        end else if (!q_busy && (pre_en || rwl_sel || wwl_en || bl_drive || sense_en))
            finding("STROBE_WHILE_IDLE", 0, 0);
        if (qfall && in_op) begin
            in_op = 0; q_fall_cyc = cyc;
            dkind = (pcnt[1] > 0 && pcnt[3] > 0) ? 2'd2 : ((pcnt[1] > 0) ? 2'd0 : ((pcnt[3] > 0) ? 2'd1 : 2'd3));
            if (dkind !== cur_kind) finding("KIND_MISMATCH", dkind, cur_kind);
            // phase durations and total busy length, from the independent derivation
            if (cur_kind != 1 && (pcnt[1] != P_PRE || pcnt[2] != P_SENSE)) finding("PROFILE", pcnt[1], pcnt[2]);
            if (cur_kind != 0 && pcnt[3] != P_WB) finding("PROFILE", pcnt[3], P_WB);
            if (plen != ((cur_kind == 2) ? PY_D_REF : (cur_kind == 0) ? PY_D_RD : PY_D_WR))
                finding("SEQ_LENGTH", plen, cur_kind);
            if (cur_kind < 3) begin
                n_exec = n_exec + 1; n_exec_k[cur_kind] = n_exec_k[cur_kind] + 1;
                len_obs[cur_kind] = plen;
            end
            if (cur_kind == 2) begin     // REFRESH completion: timestamp the row
                age[cur_row] = 0; armed[cur_row] = 1; initcov[cur_row] = 1; swcov[cur_row] = 1;
                ref_cnt[cur_row] = ref_cnt[cur_row] + 1;
            end
        end
        // ---- scheduler completion must not precede sequencer completion
        if (sfall) begin
            k = (op_is_refresh) ? 2 : (op_is_write ? 1 : 0);
            if (q_busy) finding("BUDGET_UNDER", cyc - sch_start, k);
            else begin
                if (cyc - q_fall_cyc < min_margin[k]) min_margin[k] = cyc - q_fall_cyc;
                sch_len_obs[k] = cyc - sch_start;
            end
            if (cyc - sch_start != ((k == 2) ? PY_T_ROW : PY_T_ACC)) begin
                // access ops all use T_ACC (the scheduler does not distinguish read/write)
                finding("BUDGET_VALUE", cyc - sch_start, k);
            end
        end
        // ---- sweeps (accepted START_SWEEP) checked on sequencer completions
        if (sweep_done) begin
            n_sdone = n_sdone + 1;
            if (sweep_chk == 0) finding("SPURIOUS_SWEEP_DONE", cyc, 0);
            else begin
                sweep_done_seen = sweep_done_seen + 1;
                all_cov = 1; for (k = 0; k < N_ROWS; k = k + 1) if (!swcov[k]) all_cov = 0;
                if (!all_cov) finding("SWEEP_DONE_BEFORE_ROWS", cyc, 0);
                if (cyc - sweep_acc > max_sweep_lat) max_sweep_lat = cyc - sweep_acc;
                if (sweep_done_seen > 1) finding("SWEEP_DONE_TWICE", cyc, 0);
            end
        end
        if (sweep_chk != 0 && cyc >= sweep_dl) begin
            all_cov = 1; for (k = 0; k < N_ROWS; k = k + 1) if (!swcov[k]) all_cov = 0;
            if (!all_cov) finding("SWEEP_INCOMPLETE", cyc, sweep_acc);
            if (sweep_done_seen != 1) finding("SWEEP_DONE_COUNT", sweep_done_seen, 1);
            sweep_chk = 0;
        end

        // ---- per-row deadline (age since sequencer completion of the last refresh)
        D = c_ivl;
        if (cyc < hold_until && hold_val > D) D = hold_val;
        cur_max_age = 0;
        for (k = 0; k < N_ROWS; k = k + 1) begin
            age[k] = age[k] + 1;      // ages advance after any completion timestamp (age=0) set above
            if (age[k] > INTERVAL) suspect[k] = 1;
            if (c_en && armed[k]) begin
                if (age[k] > cur_max_age) cur_max_age = age[k];
                if (age[k] > max_age_obs) max_age_obs = age[k];
                if (D - age[k] < min_slack) min_slack = D - age[k];
                if (cyc < hold_until && c_ivl == short_new && age[k] > short_new && cyc - short_cyc > trans_obs)
                    trans_obs = cyc - short_cyc;
                if (age[k] > D) finding("DEADLINE", k, age[k]);
                if (age[k] > INTERVAL) finding("DEADLINE_HARD", k, age[k]);
            end
        end
        if (cur_max_age < 0) cur_max_age = 0;
        // ---- re-arm / reset liveness and validity
        if (c_en && cyc - enable_cyc > T_REARM && !rearm_rep) begin
            all_cov = 1; for (k = 0; k < N_ROWS; k = k + 1) if (!armed[k]) all_cov = 0;
            if (!all_cov || !refresh_ok) begin finding("REARM", cyc - enable_cyc, refresh_ok); rearm_rep = 1; end
        end
        if (refresh_ok) begin
            all_cov = 1; for (k = 0; k < N_ROWS; k = k + 1) if (!initcov[k]) all_cov = 0;
            if (!all_cov) finding("OK_EARLY", cyc, 0);
            if (!data_lost) begin
                for (k = 0; k < N_ROWS; k = k + 1) if (suspect[k]) finding("UNNOTICED_INVALID", k, 0);
            end
        end
        if ((dis_since_reset && cyc - dis_cyc > T_XFER && !data_lost) || (!dis_since_reset && data_lost))
            finding("DATA_LOST_FLAG", data_lost, dis_since_reset);
        // ---- application / atomicity
        if (cyc - last_change > T_XFER && {en_eff, ivl_eff} !== {c_en, c_ivl} && !conv_rep) begin
            finding("NOT_APPLIED", ivl_eff, c_ivl); conv_rep = 1;
        end
        if ({en_eff, ivl_eff} !== eff_q) begin
            found = 0;
            for (h = 0; h < nh; h = h + 1) if (hist[h] === {en_eff, ivl_eff}) found = 1;
            if (!found) finding("PARTIAL", ivl_eff, en_eff);
            if ({en_eff, ivl_eff} === {c_en, c_ivl} && cyc - last_change > max_apply_lat) max_apply_lat = cyc - last_change;
            eff_q = {en_eff, ivl_eff};
        end
        if (cfg_reject) finding("CFG_REJECT", cyc, 0);

        op_busy_p = op_busy; q_busy_p = q_busy;
    end

    // ---------------- SPI master (mode 0, MSB first), timed independently of clk ----------------
    reg [15:0] rdv;
    integer bi;
    task bits(input [15:0] w, input integer from, input integer nbits);
        begin
            for (bi = from; bi < from + nbits; bi = bi + 1) begin
                mosi = (bi < 16) ? w[15-bi] : 1'b0;
                #(H) sclk = 1; if (bi < 16) rdv[15-bi] = miso; #(H) sclk = 0;
            end
        end
    endtask
    task frame_lo(input [15:0] w);
        begin rdv = 0; cs_n = 0; #(H); bits(w, 0, 16); #(H); end
    endtask
    task frame_end; begin cs_n = 1; mosi = 0; #(TCSH); end endtask
    task wr(input [6:0] a, input [7:0] d); begin frame_lo({1'b1, a, d}); frame_end; end endtask
    task rdr(input [6:0] a, output [7:0] d); begin frame_lo({1'b0, a, 8'h00}); frame_end; d = rdv[7:0]; end endtask
    reg [7:0] v;
    task rchk(input [255:0] name, input [6:0] a, input [7:0] exp); begin rdr(a, v); check(name, v, exp); end endtask
    task mwait(input integer n); begin repeat (n) @(posedge clk); #(PH); end endtask
    task do_reset(input real low_ns);
        begin rst_n = 0; n_resets = n_resets + 1; bench_reset; #(low_ns); rst_n = 1; end
    endtask

    // interval write over SPI with an independent accept/reject expectation
    reg acc_exp; integer n_ivl_acc = 0, n_ivl_rej = 0;
    task try_ivl(input [15:0] x);
        begin
            acc_exp = (x >= PY_MIN) && (x <= INTERVAL);
            wr(A_IL, x[7:0]); wr(A_IH, x[15:8]);
            if (acc_exp) begin exp_ivl = x; n_ivl_acc = n_ivl_acc + 1; end else n_ivl_rej = n_ivl_rej + 1;
            rchk("ivl_l_readback", A_IL, exp_ivl[7:0]);
            rchk("ivl_h_readback", A_IH, exp_ivl[15:8]);
            rdr(A_ST, v); check("err_range_flag", v[4:0], acc_exp ? 5'h00 : 5'h01);
            wr(A_CMD, 8'h02);
            mwait(T_XFER + 2);
            check("ivl_eff_matches_accept", ivl_eff, exp_ivl);
            check("cfg_reject_clear", cfg_reject, 0);
            rdr(A_XST, v); check("xstat_cfg_reject", v[3], 0);
        end
    endtask
    task setpair(input en, input [15:0] x);   // unconditional legal write used to restore state
        begin wr(A_IL, x[7:0]); wr(A_IH, x[15:8]); exp_ivl = x; wr(A_CTRL, {7'b0, en}); exp_en = en; end
    endtask

    integer t0, polls;
    task poll_idle(input [255:0] name, input integer bound);
        begin
            t0 = cyc; polls = 0;
            rdr(A_ST, v);
            while (v[7] && cyc - t0 < bound) begin rdr(A_ST, v); polls = polls + 1; end
            check(name, v[7], 0);
        end
    endtask
    // hold a commit frame (IH write of tgt) low until the sequencer is 'off' cycles into an op of
    // kind knd (2 refresh, 1 write, 0 read), then release (commit while the op is executing)
    integer lim, wcyc;
    task commit_in_op(input [15:0] tgt, input integer knd, input integer off);
        begin
            wr(A_IL, tgt[7:0]);
            frame_lo({1'b1, A_IH, tgt[15:8]});
            lim = 0;
            while (!(in_op && q_busy && cur_kind == knd && plen == off + 1) && lim < 4 * INTERVAL) begin
                @(negedge clk); #0.1; lim = lim + 1;
            end
            check("commit_in_op_reached", lim < 4 * INTERVAL, 1);
            #(PH); frame_end;
            exp_ivl = tgt;
            mwait(T_XFER + 2);
            check("applied_after_op_commit", ivl_eff, tgt);
        end
    endtask

    integer oi, off, thr, di, dd, ri;
    reg [0:0] tog0; reg [15:0] tgt;
    integer offs [0:11]; integer durs [0:5];
    integer cfg_bad;
    integer kk, kmax;

    initial begin
        rng = SEED;
        for (k = 0; k < 3; k = k + 1) begin n_exec_k[k] = 0; min_margin[k] = 1 << 30; len_obs[k] = 0; sch_len_obs[k] = 0; end
        for (k = 0; k < N_ROWS; k = k + 1) ref_cnt[k] = 0;
        pend_v = 0; in_op = 0; op_busy_p = 0; q_busy_p = 0; q_fall_cyc = 0; exp_ref_row = 0;
        #0.1 rst_n = 0;
        bench_reset; n_resets = 0; n_abandon = 0;
        #(5.1 + PH) rst_n = 1;

        // ---- pre-traffic configuration gate: budgets and every floor against the Python derivation
        cfg_bad = 0;
        if (dut.T_ROW_E < PY_T_ROW) begin $display("CONFIG_%0s: scheduler T_ROW %0d below derived %0d", (CHECK_CFG != 0) ? "REJECT" : "BYPASSED", dut.T_ROW_E, PY_T_ROW); cfg_bad = 1; end
        if (dut.T_ACC_E < PY_T_ACC) begin $display("CONFIG_%0s: scheduler T_ACC %0d below derived %0d", (CHECK_CFG != 0) ? "REJECT" : "BYPASSED", dut.T_ACC_E, PY_T_ACC); cfg_bad = 1; end
        if (dut.u_ctrl.MIN_INTERVAL !== PY_MIN) begin $display("CONFIG_%0s: gc_ctrl_top floor %0d != derived %0d", (CHECK_CFG != 0) ? "REJECT" : "BYPASSED", dut.u_ctrl.MIN_INTERVAL, PY_MIN); cfg_bad = 1; end
        if (dut.u_ctrl.u_spi.MIN_INTERVAL !== PY_MIN) begin $display("CONFIG_%0s: SPI slave floor %0d != derived %0d", (CHECK_CFG != 0) ? "REJECT" : "BYPASSED", dut.u_ctrl.u_spi.MIN_INTERVAL, PY_MIN); cfg_bad = 1; end
        if (dut.u_ctrl.u_sched.MIN_INTERVAL !== PY_MIN) begin $display("CONFIG_%0s: scheduler floor %0d != derived %0d", (CHECK_CFG != 0) ? "REJECT" : "BYPASSED", dut.u_ctrl.u_sched.MIN_INTERVAL, PY_MIN); cfg_bad = 1; end
        if (PY_MIN > INTERVAL) begin $display("CONFIG_REJECT: infeasible: floor %0d exceeds INTERVAL %0d", PY_MIN, INTERVAL); cfg_bad = 1; CHECK_GATE_FORCE; end
        if (CHECK_CFG != 0 && cfg_bad != 0) begin
            $display("TB_RESULT: FAIL (configuration gate)"); $finish;
        end
        $display("CONFIG: INTERVAL=%0d floor=%0d T_ROW=%0d T_ACC=%0d GUARD_EFF=%0d D_REF=%0d D_RD=%0d D_WR=%0d sclk_half_ps=%0d phase_ps=%0d traffic=%0d",
                 INTERVAL, PY_MIN, PY_T_ROW, PY_T_ACC, PY_GUARD_EFF, PY_D_REF, PY_D_RD, PY_D_WR, SCLK_HALF_PS, PHASE_PS, TRAFFIC);
        traffic_on = 1;

        // ---- T1 reset defaults and initialisation sweep through the sequencer
        check("refresh_ok_low_after_reset", refresh_ok, 0);
        mwait(T_REARM);
        rchk("id", A_ID, 8'hA5);
        rchk("ctrl_rst", A_CTRL, 8'h01);
        rchk("ivl_l_rst", A_IL, INTERVAL[7:0]);
        rchk("ivl_h_rst", A_IH, INTERVAL[15:8]);
        rchk("status_rst", A_ST, 8'h00);
        rchk("xstat_rst", A_XST, 8'h01);
        check("ivl_eff_rst", ivl_eff, INTERVAL);

        // ---- T2 interval changes: below floor, at floor, floor+1, max, max+1, zero, mid
        try_ivl(PY_MIN - 1);
        try_ivl(INTERVAL + 1);
        try_ivl(0);
        try_ivl(PY_MIN);                           // legal floor accepted
        mwait(3 * PY_MIN + PY_SETTLE);             // run at the floor under saturated traffic
        try_ivl(PY_MIN - 1);                       // below floor while running at the floor
        mwait(PY_MIN);
        try_ivl(PY_MIN + 1); mwait(2 * PY_MIN);
        try_ivl(INTERVAL);   mwait(2 * INTERVAL);  // maximum accepted
        try_ivl(INTERVAL + 1);
        try_ivl(MID);        mwait(2 * MID);
        try_ivl(INTERVAL - 1); mwait(INTERVAL);
        try_ivl(PY_MIN);     mwait(PY_MIN + PY_SETTLE);
        try_ivl(INTERVAL);   mwait(INTERVAL);

        // ---- T3 no partial commits: low byte alone, then pair, rejected pair, poisoned shadow
        wr(A_IL, MID[7:0]); mwait(3 * T_XFER);
        check("l_only_not_applied", ivl_eff, INTERVAL);
        wr(A_IH, MID[15:8]); exp_ivl = MID; mwait(T_XFER + 2);
        check("pair_applied", ivl_eff, MID);
        wr(A_IL, 8'hFF); wr(A_IH, 8'hFF);          // out of range (> INTERVAL): rejected pair
        mwait(T_XFER + 2); check("bad_pair_not_applied", ivl_eff, MID);
        wr(A_IH, MID[15:8]); mwait(T_XFER + 2);
        check("no_poisoned_shadow_applied", ivl_eff, MID);
        wr(A_CMD, 8'h02);
        setpair(1, INTERVAL); mwait(INTERVAL);

        // ---- T4 shortening near a deadline (commit held until the oldest row is close to urgent)
        offs[0] = 40; offs[1] = 20; offs[2] = 8; offs[3] = 3; offs[4] = 1; offs[5] = 0;
        offs[6] = -1; offs[7] = -3; offs[8] = -10; offs[9] = -20; offs[10] = -30; offs[11] = 5;
        for (oi = 0; oi < ((FAST != 0) ? 4 : 12); oi = oi + 1) begin
            off = offs[oi];
            tgt = (oi % 3 == 2) ? MID : PY_MIN;
            thr = INTERVAL - PY_T_ROW - PY_T_ACC - PY_GUARD_EFF - off;
            wr(A_IL, tgt[7:0]);
            frame_lo({1'b1, A_IH, tgt[15:8]});
            lim = 0;
            while (cur_max_age < thr && lim < 3 * INTERVAL) begin @(negedge clk); lim = lim + 1; end
            #(PH); frame_end; exp_ivl = tgt;
            mwait(T_XFER + 2); check("near_deadline_applied", ivl_eff, tgt);
            mwait(PY_SETTLE + 2 * tgt);
            setpair(1, INTERVAL); mwait(T_XFER + 2);
        end
        mwait(INTERVAL);

        // ---- T5 configuration arriving while the sequencer is busy (refresh, write, read)
        for (oi = 0; oi < ((FAST != 0) ? 3 : 12); oi = oi + 1) begin
            off = (oi % 6 == 0) ? 0 : (oi % 6 == 1) ? 1 : (oi % 6 == 2) ? 5 : (oi % 6 == 3) ? 12 : (oi % 6 == 4) ? 20 : PY_D_REF - 2;
            tgt = (oi % 2 == 0) ? PY_MIN : MID;
            kk = (oi < 6) ? 2 : ((oi % 2) ? 1 : 0);
            kmax = (kk == 2) ? PY_D_REF : (kk == 1) ? PY_D_WR : PY_D_RD;
            commit_in_op(tgt, kk, (off >= kmax) ? kmax - 1 : off);
            mwait(PY_SETTLE + 2 * tgt);
            try_ivl(INTERVAL); mwait(INTERVAL / 4);
        end

        // ---- T6 forced sweeps: busy, refusal while busy, config while the sweep is running
        tog0 = spi_tog; wr(A_CMD, 8'h01);
        check("sweep_accepted", spi_tog ^ tog0, 1);
        rdr(A_ST, v); check("busy_after_sweep_accept", v[7], 1);
        rdr(A_XST, v); check("xstat_sweep_active", v[2], 1);
        tog0 = spi_tog; wr(A_CMD, 8'h01); check("sweep_while_busy_refused", spi_tog ^ tog0, 0);
        rdr(A_ST, v); check("err_busy_flagged", v[3], 1); wr(A_CMD, 8'h02);
        wr(A_IL, PY_MIN[7:0]); wr(A_IH, PY_MIN[15:8]); exp_ivl = PY_MIN;      // config while sweeping
        poll_idle("sweep_busy_clears", T_SWEEP + 4000);
        check("one_completion_per_accept", n_sdone, n_sacc);
        mwait(T_XFER + 2); check("ivl_applied_during_sweep", ivl_eff, PY_MIN);
        tog0 = spi_tog; wr(A_CMD, 8'h01); check("sweep2_accepted", spi_tog ^ tog0, 1);
        wr(A_CTRL, 8'h00); exp_en = 0; exp_lost = 1;                          // disable while sweeping
        poll_idle("sweep2_busy_clears", T_SWEEP + 4000);
        check("running_sweep_completes_disabled", n_sdone, n_sacc);
        mwait(T_XFER + 2); check("disabled_applied", en_eff, 0);
        rdr(A_XST, v); check("xstat_lost_after_disable", v[1], 1); check("xstat_ok_low_disabled", v[0], 0);
        tog0 = spi_tog; wr(A_CMD, 8'h01); check("sweep_when_disabled_accepted", spi_tog ^ tog0, 1);
        poll_idle("sweep3_busy_clears", T_SWEEP + 4000);
        check("sweep_when_disabled_completed", n_sdone, n_sacc);
        rdr(A_XST, v); check("sweep_does_not_set_ok", v[0], 0);
        wr(A_CTRL, 8'h01); exp_en = 1;                                        // re-enable
        mwait(T_REARM + 20);
        rdr(A_XST, v); check("ok_after_reenable", v[0], 1); check("lost_sticky_after_reenable", v[1], 1);
        setpair(1, INTERVAL); mwait(INTERVAL);

        // ---- T7 enable/disable and re-enable sweep with different disabled durations
        durs[0] = 0; durs[1] = 30; durs[2] = 300; durs[3] = 2000; durs[4] = 5; durs[5] = 800;
        for (di = 0; di < ((FAST != 0) ? 3 : 6); di = di + 1) begin
            dd = durs[di];
            wr(A_CTRL, 8'h00); exp_en = 0; exp_lost = 1;
            mwait(dd);
            wr(A_CTRL, 8'h01); exp_en = 1;
            mwait(T_REARM + 20);
            check("reenable_en_eff", en_eff, 1);
            rdr(A_XST, v); check("reenable_ok", v[0], 1); check("reenable_lost_sticky", v[1], 1);
            rchk("reenable_ctrl", A_CTRL, 8'h01);
            mwait(2 * INTERVAL / 3);
        end
        // disable at the floor interval, then re-enable (shortest legal operating point)
        try_ivl(PY_MIN); wr(A_CTRL, 8'h00); mwait(PY_MIN); wr(A_CTRL, 8'h01); mwait(T_REARM + 20 + 2 * PY_MIN);
        setpair(1, INTERVAL); mwait(INTERVAL);

        // ---- T8 reset (data lost cleared, defaults restored, initialisation sweep re-executed)
        for (ri = 0; ri < ((FAST != 0) ? 3 : 6); ri = ri + 1) begin
            case (ri)
              0: begin mwait(100); end
              1: begin tog0 = spi_tog; wr(A_CMD, 8'h01); mwait(400); end                       // reset inside a sweep
              2: begin try_ivl(PY_MIN); mwait(PY_MIN); end                                      // reset at the floor
              3: begin wr(A_CTRL, 8'h00); mwait(50); end                                       // reset while disabled
              4: begin                                                                          // reset inside a refresh
                   lim = 0; while (!(in_op && cur_kind == 2 && plen == 9) && lim < 3 * INTERVAL) begin @(negedge clk); lim = lim + 1; end
                 end
              default: begin                                                                    // reset in the middle of an SPI frame
                   cs_n = 0; #(H); bits({1'b1, A_CTRL, 8'h00}, 0, 9);
                 end
            endcase
            do_reset(7.3 + ri);
            if (ri == 5) begin cs_n = 1; mosi = 0; #(TCSH); end
            mwait(T_REARM + 20);
            rchk("rst_ctrl", A_CTRL, 8'h01);
            rchk("rst_ivl_l", A_IL, INTERVAL[7:0]); rchk("rst_ivl_h", A_IH, INTERVAL[15:8]);
            rchk("rst_status", A_ST, 8'h00); rchk("rst_xstat", A_XST, 8'h01);
            check("rst_ivl_eff", ivl_eff, INTERVAL); check("rst_en_eff", en_eff, 1);
            check("rst_data_lost", data_lost, 0);
            mwait(INTERVAL / 2);
        end

        // ---- T9 final soak with the maximum interval and a floor interval, saturated traffic
        try_ivl(PY_MIN); mwait(4 * PY_MIN);
        try_ivl(INTERVAL); mwait(2 * INTERVAL);

        // ---- end-of-run accounting (independent of DUT flags)
        check("launch_equals_executed_or_inflight", (n_launch - n_exec - n_abandon) <= 1, 1);
        check("saw_reads", n_exec_k[0] > 0, 1);
        check("saw_writes", (TRAFFIC == 1) || (n_exec_k[1] > 0), 1);   // TRAFFIC 1 is read-only
        check("saw_refreshes", n_exec_k[2] > 0, 1);
        found = 1; for (k = 0; k < N_ROWS; k = k + 1) if (ref_cnt[k] < 3) found = 0;
        check("every_row_refreshed_at_least_3x", found, 1);
        check("sweeps_accepted_all_done", n_sacc - n_sdone - n_scancel, 0);
        check("no_ignored_starts", n_ign, 0);
        check("ivl_accepts_seen", n_ivl_acc > 0, 1);
        check("ivl_rejects_seen", n_ivl_rej > 0, 1);
        $display("OBS: launches=%0d executed=%0d (read=%0d write=%0d refresh=%0d) abandoned_by_reset=%0d resets=%0d",
                 n_launch, n_exec, n_exec_k[0], n_exec_k[1], n_exec_k[2], n_abandon, n_resets);
        $display("OBS: seq_busy_len read=%0d write=%0d refresh=%0d ; sched_busy_len access=%0d refresh=%0d",
                 len_obs[0], len_obs[1], len_obs[2], sch_len_obs[0], sch_len_obs[2]);
        $display("OBS: launch->sequencer latency min=%0d max=%0d ; min(sched fall - seq fall) read=%0d write=%0d refresh=%0d",
                 lat_obs_min, lat_obs_max, min_margin[0], min_margin[1], min_margin[2]);
        $display("OBS: min deadline slack=%0d max row age=%0d (ratified bound %0d) ; sweep accept->sweep_done max=%0d (bound %0d)",
                 min_slack, max_age_obs, INTERVAL, max_sweep_lat, T_SWEEP);
        $display("OBS: max SPI commit->applied=%0d cycles (bound %0d) ; shortenings=%0d longest transition above new value=%0d (bound %0d) ; ivl accepted=%0d rejected=%0d ; sweeps=%0d done=%0d cancelled_by_reset=%0d",
                 max_apply_lat, T_XFER, n_shorten, trans_obs, T_XFER + PY_SETTLE, n_ivl_acc, n_ivl_rej, n_sacc, n_sdone, n_scancel);
        $display("SUMMARY: checks=%0d findings=%0d cycles=%0d", checks, errors, cyc);
        if (errors == 0) $display("TB_RESULT: PASS"); else $display("TB_RESULT: FAIL");
        $finish;
    end

    // an infeasible combination is never simulated further, with or without the gate
    task CHECK_GATE_FORCE; begin $display("TB_RESULT: FAIL (infeasible)"); $finish; end endtask

    initial begin #(40_000_000); $display("TB_RESULT: FAIL (timeout)"); $finish; end
endmodule
