// Self-checking integration bench (issue #93): real SPI frames into
// gc_ctrl_top (spi_slave -> cfg_xfer -> refresh_sched_rt), foreground traffic,
// and monitors that are independent of the DUT's internal bookkeeping.
// Prints TB_RESULT: PASS / FAIL. PROPOSED contract: see CONTRACT.md.
//
// Independent monitors (negedge clk, every cycle):
//   M1 per-row deadline: for every armed row while refresh is committed on,
//      age <= D(t), where D is the SPI-committed interval, except that after a
//      shortening the previous (longer) value is still allowed for T_SETTLE
//      cycles (the documented transition bound). Also age <= INTERVAL (the
//      ratified bound) unconditionally for armed rows.
//      age resets on refresh or write completion of that row (as #74).
//      A row is "armed" from reset, and after a re-enable from its first
//      refresh/write after the re-enable commit.
//   M2 re-arm liveness: T_REARM cycles after reset / re-enable every row must
//      be armed and refresh_ok must be 1.
//   M3 sweeps: every START_SWEEP accepted by the SPI slave (sweep_tog toggle)
//      must produce exactly one sweep_done within T_SWEEP, and every row must
//      have completed a refresh between acceptance and sweep_done. Otherwise
//      LOST / spurious / incomplete. Reset cancels outstanding sweeps.
//   M4 validity: refresh_ok only after every row has been refreshed since the
//      last reset / re-enable; refresh_ok && !data_lost never while any row is
//      suspect (aged past INTERVAL since its last write/refresh); data_lost
//      must be set within T_XFER of a disable and only after one.
//   M5 application: T_XFER cycles after the SPI-committed {enable, interval}
//      last changed, the scheduler's applied pair must equal it (no lost
//      configuration); every applied pair must be one the SPI slave actually
//      held (no partial / mixed snapshot); cfg_reject must never fire.
`timescale 1ns/1ps
module tb_ctrl_integ;
    parameter integer N_ROWS = 32;
    parameter integer T_ROW = 34;
    parameter integer T_ACC = 34;
    parameter integer GUARD = 2;
    parameter integer INTERVAL = 5029;      // supplied by run_tests.sh from params.py
    parameter integer MIN_INTERVAL = 1124;  // supplied by run_tests.sh from params.py (Python)
    parameter integer SCLK_HALF_PS = 3700;  // SPI clock half period, ps
    parameter integer PHASE_PS = 130;       // offset of the SPI master timeline vs clk, ps
    parameter integer TRAFFIC = 1;          // 0 none, 1 saturating reads, 2 seeded random
    parameter integer NEG_SPACING = 0;      // 1: violate the frame spacing (negative control, must FAIL)
    parameter integer SEED = 32'h1badcafe;
    localparam integer ROW_W = (N_ROWS > 1) ? $clog2(N_ROWS) : 1;
    localparam real H    = SCLK_HALF_PS / 1000.0;
    localparam real PH   = PHASE_PS / 1000.0;
    localparam real TCSH = 4.25;            // cs_n high between frames (>= 4 clk, CONTRACT.md)
    // contract bounds, cycles (CONTRACT.md)
    localparam integer T_XFER   = 6;        // commit -> applied (2FF + edge + strobe = 4) + sampling slack
    // an op occupies T+1 cycles (one decision cycle between ops, as in #74):
    // one in-flight external op, then N_ROWS back-to-back refreshes
    localparam integer T_TRANS  = (T_ACC + 1) + N_ROWS * (T_ROW + 1) + GUARD;
    localparam integer T_SETTLE = T_XFER + T_TRANS;
    localparam integer T_SWEEP  = T_XFER + T_TRANS;
    localparam integer T_REARM  = T_SWEEP;
    localparam integer MID = (MIN_INTERVAL + INTERVAL) / 2;
    localparam [6:0] A_ID=0, A_CTRL=1, A_CMD=2, A_IL=3, A_IH=4, A_ST=5, A_XST=6;

    reg clk = 0, rst_n = 1, sclk = 0, cs_n = 1, mosi = 0;   // rst_n falls at 0.1 ns (async edge for the SPI slave)
    always #0.5 clk = ~clk;                 // 1 cycle = 1 ns (ASSUMPTION)

    reg req_valid = 0, req_we = 0; reg [ROW_W-1:0] req_row = 0;
    wire miso, req_accept, op_busy, op_is_refresh, op_is_write, op_done;
    wire en_eff, sweep_active, sweep_done, refresh_ok, data_lost, cfg_reject, busy;
    wire [ROW_W-1:0] op_row; wire [15:0] ivl_eff;

    gc_ctrl_top #(.N_ROWS(N_ROWS), .T_ROW(T_ROW), .T_ACC(T_ACC), .INTERVAL(INTERVAL), .GUARD(GUARD)) dut (
        .rst_n(rst_n), .clk(clk), .sclk(sclk), .cs_n(cs_n), .mosi(mosi), .miso(miso),
        .req_valid(req_valid), .req_we(req_we), .req_row(req_row), .req_accept(req_accept),
        .op_busy(op_busy), .op_is_refresh(op_is_refresh), .op_is_write(op_is_write),
        .op_row(op_row), .op_done(op_done),
        .en_eff(en_eff), .ivl_eff(ivl_eff), .sweep_active(sweep_active), .sweep_done(sweep_done),
        .refresh_ok(refresh_ok), .data_lost(data_lost), .cfg_reject(cfg_reject), .busy(busy));

    // SPI-committed state (the protocol model's registers), observed only
    wire        spi_en  = dut.u_spi.refresh_en;
    wire [15:0] spi_ivl = dut.u_spi.interval;
    wire        spi_tog = dut.u_spi.sweep_tog;

    // ---------------- bookkeeping ----------------
    integer errors = 0, checks = 0, cyc = 0, k;
    integer n_viol = 0, n_hard = 0, n_lost = 0, n_spur = 0, n_cov = 0, n_okcov = 0;
    integer n_unnoticed = 0, n_lostflag = 0, n_conv = 0, n_partial = 0, n_reject = 0;
    integer n_rearm = 0, n_proto = 0;
    integer n_ref = 0, n_ext = 0, n_acc = 0, n_done = 0, n_cancel = 0, n_resets = 0;
    integer n_near_hit = 0, n_near_try = 0, n_shorten = 0;
    integer short_cyc = 0, short_new = 0, trans_obs = 0;   // observed shortening transition length
    integer age [0:N_ROWS-1];
    reg armed [0:N_ROWS-1], suspect [0:N_ROWS-1], initcov [0:N_ROWS-1], swcov [0:N_ROWS-1];
    reg c_en, c_tog, dis_since_reset; reg [15:0] c_ivl;
    integer last_change = 0, hold_val = 0, hold_until = 0, enable_cyc = 0, dis_cyc = 0, outstanding = 0, oldest_acc = 0;
    integer cur_max_age = 0, min_slack = 1 << 30, min_hard_slack = 1 << 30, D;
    reg [16:0] hist [0:4095]; integer nh = 0, h; reg found;
    reg [16:0] eff_q;
    reg conv_rep, all_cov, rej_rep;

    task check(input [255:0] name, input [31:0] got, input [31:0] exp);
        begin checks = checks + 1;
            if (got !== exp) begin errors = errors + 1;
                $display("FAIL %0s: got %0h expected %0h (cycle %0d)", name, got, exp, cyc); end
        end
    endtask

    task hist_add(input [16:0] p);
        begin if (nh < 4096) begin hist[nh] = p; nh = nh + 1; end end
    endtask

    // bench-side model reset (called while rst_n is low)
    task bench_reset;
        begin
            for (k = 0; k < N_ROWS; k = k + 1) begin
                age[k] = 0; armed[k] = 1; suspect[k] = 0; initcov[k] = 0; swcov[k] = 0;
            end
            c_en = 1; c_ivl = INTERVAL; c_tog = 0; dis_since_reset = 0;
            last_change = cyc; hold_val = 0; hold_until = 0; enable_cyc = cyc;
            dis_cyc = 0; n_cancel = n_cancel + outstanding; outstanding = 0; oldest_acc = cyc;
            hist_add({1'b1, INTERVAL[15:0]}); eff_q = {1'b1, INTERVAL[15:0]}; conv_rep = 0;
        end
    endtask

    // ---------------- foreground traffic (as #74 scenarios 1/2) ----------------
    reg [31:0] rng; reg [1:0] tphase = 0; reg traffic_on = 0; integer sat_rowctr = 0;
    function [31:0] xs(input [31:0] s);
        reg [31:0] x; begin
            x = s; x = x ^ (x << 13); x = x ^ (x >> 17); x = x ^ (x << 5); xs = x;
        end
    endfunction
    always @(posedge clk) begin
        rng <= xs(rng);
        if (cyc % 1500 == 0) tphase <= rng[9:8];
    end
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) req_valid <= 0;
        else if (req_accept) req_valid <= 0;
        else if (!req_valid && traffic_on) begin
            case (TRAFFIC)
              1: begin req_valid <= 1; req_we <= 0; req_row <= sat_rowctr % N_ROWS;
                       sat_rowctr <= sat_rowctr + 1; end
              2: if ((tphase == 0 && rng[5:0] == 0) || (tphase == 1 && rng[2:0] == 0) || (tphase >= 2)) begin
                       req_valid <= 1; req_we <= rng[7]; req_row <= rng[20:12] % N_ROWS;
                 end
              default: req_valid <= 0;
            endcase
        end
    end

    // ---------------- independent monitors ----------------
    always @(negedge clk) if (rst_n) begin
        cyc = cyc + 1;
        // SPI-committed configuration changes
        if (spi_en !== c_en || spi_ivl !== c_ivl) begin
            hist_add({spi_en, spi_ivl});
            if (spi_ivl < c_ivl) begin
                if (!(cyc < hold_until && hold_val > c_ivl)) hold_val = c_ivl;
                hold_until = cyc + T_SETTLE;
                n_shorten = n_shorten + 1; short_cyc = cyc; short_new = spi_ivl;
            end
            if (!c_en && spi_en) begin
                enable_cyc = cyc;
                for (k = 0; k < N_ROWS; k = k + 1) begin armed[k] = 0; initcov[k] = 0; end
            end
            if (c_en && !spi_en && !dis_since_reset) begin dis_since_reset = 1; dis_cyc = cyc; end
            c_en = spi_en; c_ivl = spi_ivl; last_change = cyc; conv_rep = 0;
        end
        // START_SWEEP accepted by the protocol model
        if (spi_tog !== c_tog) begin
            c_tog = spi_tog; n_acc = n_acc + 1;
            if (outstanding == 0) begin
                oldest_acc = cyc;
                for (k = 0; k < N_ROWS; k = k + 1) swcov[k] = 0;
            end
            outstanding = outstanding + 1;
        end
        // ages and op completions
        for (k = 0; k < N_ROWS; k = k + 1) age[k] = age[k] + 1;
        if (op_done && op_is_refresh) begin
            age[op_row] = 0; armed[op_row] = 1; initcov[op_row] = 1; swcov[op_row] = 1;
            n_ref = n_ref + 1;
        end
        if (op_done && op_is_write) begin
            age[op_row] = 0; armed[op_row] = 1; suspect[op_row] = 0;
        end
        if (req_accept) n_ext = n_ext + 1;
        if (req_accept && (!op_busy || op_is_refresh)) begin
            errors = errors + 1; n_proto = n_proto + 1;
        end
        // M3 sweeps
        if (sweep_done) begin
            if (outstanding == 0) begin
                errors = errors + 1; n_spur = n_spur + 1;
                if (n_spur <= 3) $display("SPURIOUS sweep_done at cycle %0d", cyc);
            end else begin
                all_cov = 1;
                for (k = 0; k < N_ROWS; k = k + 1) if (!swcov[k]) all_cov = 0;
                if (!all_cov) begin
                    errors = errors + 1; n_cov = n_cov + 1;
                    if (n_cov <= 3) $display("INCOMPLETE sweep: sweep_done before every row was refreshed, cycle %0d", cyc);
                end
                outstanding = outstanding - 1; n_done = n_done + 1;
                oldest_acc = cyc;
                for (k = 0; k < N_ROWS; k = k + 1) swcov[k] = 0;
            end
        end
        if (outstanding > 0 && cyc - oldest_acc > T_SWEEP) begin
            errors = errors + 1; n_lost = n_lost + 1;
            if (n_lost <= 3) $display("LOST START_SWEEP: accepted at cycle %0d, no completion within %0d cycles", oldest_acc, T_SWEEP);
            outstanding = outstanding - 1; oldest_acc = cyc;
        end
        // M1 deadline
        D = c_ivl;
        if (cyc < hold_until && hold_val > D) D = hold_val;
        cur_max_age = 0;
        for (k = 0; k < N_ROWS; k = k + 1) begin
            if (age[k] > INTERVAL) suspect[k] = 1;
            if (c_en && armed[k]) begin
                if (age[k] > cur_max_age) cur_max_age = age[k];
                if (D - age[k] < min_slack) min_slack = D - age[k];
                if (INTERVAL - age[k] < min_hard_slack) min_hard_slack = INTERVAL - age[k];
                if (cyc < hold_until && c_ivl == short_new && age[k] > short_new && cyc - short_cyc > trans_obs)
                    trans_obs = cyc - short_cyc;   // a row still above the new value this long after the commit
                if (age[k] > D) begin
                    errors = errors + 1; n_viol = n_viol + 1;
                    if (n_viol <= 5) $display("VIOLATION row %0d age %0d > deadline %0d at cycle %0d", k, age[k], D, cyc);
                end
                if (age[k] > INTERVAL) begin errors = errors + 1; n_hard = n_hard + 1; end
            end
        end
        // M2 re-arm liveness
        if (c_en && cyc - enable_cyc > T_REARM) begin
            all_cov = 1;
            for (k = 0; k < N_ROWS; k = k + 1) if (!armed[k]) all_cov = 0;
            if (!all_cov || !refresh_ok) begin
                errors = errors + 1; n_rearm = n_rearm + 1;
                if (n_rearm <= 3) $display("REARM: rows not all refreshed / refresh_ok low %0d cycles after (re)enable, cycle %0d", T_REARM, cyc);
                enable_cyc = cyc;          // report at most once per window
            end
        end
        // M4 validity
        if (refresh_ok) begin
            all_cov = 1;
            for (k = 0; k < N_ROWS; k = k + 1) if (!initcov[k]) all_cov = 0;
            if (!all_cov) begin
                errors = errors + 1; n_okcov = n_okcov + 1;
                if (n_okcov <= 3) $display("REFRESH_OK before every row was refreshed since (re)init, cycle %0d", cyc);
            end
            if (!data_lost) begin
                all_cov = 0;
                for (k = 0; k < N_ROWS; k = k + 1) if (suspect[k]) all_cov = 1;
                if (all_cov) begin
                    errors = errors + 1; n_unnoticed = n_unnoticed + 1;
                    if (n_unnoticed <= 3) $display("UNNOTICED invalid data: refresh_ok && !data_lost with a row past its deadline, cycle %0d", cyc);
                end
            end
        end
        if ((dis_since_reset && cyc - dis_cyc > T_XFER && !data_lost) || (!dis_since_reset && data_lost)) begin
            errors = errors + 1; n_lostflag = n_lostflag + 1;
            if (n_lostflag <= 3) $display("DATA_LOST flag wrong (%0d, disabled_since_reset=%0d) at cycle %0d", data_lost, dis_since_reset, cyc);
        end
        // M5 application / atomicity
        if (cyc - last_change > T_XFER && {en_eff, ivl_eff} !== {c_en, c_ivl} && !conv_rep) begin
            errors = errors + 1; n_conv = n_conv + 1; conv_rep = 1;
            if (n_conv <= 3) $display("NOT APPLIED: committed en=%0d ivl=%0d, applied en=%0d ivl=%0d, cycle %0d",
                                      c_en, c_ivl, en_eff, ivl_eff, cyc);
        end
        if ({en_eff, ivl_eff} !== eff_q) begin
            found = 0;
            for (h = 0; h < nh; h = h + 1) if (hist[h] === {en_eff, ivl_eff}) found = 1;
            if (!found) begin
                errors = errors + 1; n_partial = n_partial + 1;
                if (n_partial <= 3) $display("PARTIAL/FOREIGN config applied en=%0d ivl=%0d, cycle %0d", en_eff, ivl_eff, cyc);
            end
            eff_q = {en_eff, ivl_eff};
        end
        if (cfg_reject && !rej_rep) begin errors = errors + 1; n_reject = n_reject + 1; rej_rep = 1; end
    end

    // ---------------- SPI master (mode 0, MSB first), timed independently of clk ----------------
    reg [15:0] rdv;
    integer bi;
    task bits(input [15:0] w, input integer from, input integer nbits);   // cs_n already low
        begin
            for (bi = from; bi < from + nbits; bi = bi + 1) begin
                mosi = (bi < 16) ? w[15-bi] : 1'b0;
                #(H) sclk = 1; if (bi < 16) rdv[15-bi] = miso; #(H) sclk = 0;
            end
        end
    endtask
    task frame_lo(input [15:0] w);   // full 16-bit frame body, leaves cs_n LOW
        begin rdv = 0; cs_n = 0; #(H); bits(w, 0, 16); #(H); end
    endtask
    task frame_end; begin cs_n = 1; mosi = 0; #(TCSH); end endtask
    task wr(input [6:0] a, input [7:0] d); begin frame_lo({1'b1, a, d}); frame_end; end endtask
    task rdr(input [6:0] a, output [7:0] d); begin frame_lo({1'b0, a, 8'h00}); frame_end; d = rdv[7:0]; end endtask
    reg [7:0] v;
    task rchk(input [255:0] name, input [6:0] a, input [7:0] exp); begin rdr(a, v); check(name, v, exp); end endtask
    task setivl(input [15:0] x); begin wr(A_IL, x[7:0]); wr(A_IH, x[15:8]); end endtask
    task mwait(input integer n); begin repeat (n) @(posedge clk); #(PH); end endtask
    task do_reset(input real low_ns);
        begin rst_n = 0; n_resets = n_resets + 1; bench_reset; #(low_ns); rst_n = 1; end
    endtask

    // wait (bounded) until refresh BUSY reads 0 over SPI; returns cycles waited
    integer t0, polls;
    task poll_idle(input [255:0] name, input integer bound);
        begin
            t0 = cyc; polls = 0;
            rdr(A_ST, v);
            while (v[7] && cyc - t0 < bound) begin rdr(A_ST, v); polls = polls + 1; end
            check(name, v[7], 0);
        end
    endtask

    reg [0:0] tog0; integer off, oi, lim, thr; integer offs [0:11];
    reg [15:0] tgt;

    initial begin
        rng = SEED;
        #0.1 rst_n = 0;
        bench_reset; n_resets = 0; n_cancel = 0; rej_rep = 0;
        #(5.1 + PH) rst_n = 1;
        traffic_on = (TRAFFIC != 0);

        if (NEG_SPACING) begin
            // NEGATIVE CONTROL: two START_SWEEP frames separated by a cs_n high
            // pulse shorter than one clk period, placed between clk edges, so
            // the synchroniser never sees the first commit. Violates CONTRACT.md
            // frame spacing; the bench must report a LOST START_SWEEP.
            mwait(T_REARM);
            frame_lo({1'b1, A_CMD, 8'h01});
            @(posedge clk); #0.1 cs_n = 1; #0.3 cs_n = 0;
            #(H); bits({1'b1, A_CMD, 8'h01}, 0, 16); #(H);
            frame_end;
            mwait(3 * T_SWEEP);
        end else begin
        // ---- T1 reset defaults and initialisation ----
        check("refresh_ok_low_after_reset", refresh_ok, 0);
        mwait(T_REARM);
        rchk("id", A_ID, 8'hA5);
        rchk("ctrl_rst", A_CTRL, 8'h01);
        rchk("ivl_l_rst", A_IL, INTERVAL[7:0]);
        rchk("ivl_h_rst", A_IH, INTERVAL[15:8]);
        rchk("status_rst", A_ST, 8'h00);
        rchk("xstat_rst", A_XST, 8'h01);                  // REFRESH_OK only
        check("ivl_eff_rst", ivl_eff, INTERVAL);

        // ---- T2 infeasible values rejected with the scheduler's own floor ----
        setivl(MIN_INTERVAL - 1);
        check("below_floor_rejected", spi_ivl, INTERVAL);
        rchk("below_floor_err_range", A_ST, 8'h01);
        mwait(T_XFER + 2); check("below_floor_not_applied", ivl_eff, INTERVAL);
        wr(A_CMD, 8'h02);
        setivl(INTERVAL + 1); check("above_max_rejected", spi_ivl, INTERVAL);
        rchk("above_max_err_range", A_ST, 8'h01); wr(A_CMD, 8'h02);
        setivl(0); check("zero_rejected", spi_ivl, INTERVAL); wr(A_CMD, 8'h02);
        setivl(MIN_INTERVAL); check("floor_accepted", spi_ivl, MIN_INTERVAL);
        rchk("floor_no_err", A_ST, 8'h00);
        mwait(T_XFER + 2); check("floor_applied", ivl_eff, MIN_INTERVAL);
        mwait(3 * MIN_INTERVAL + T_SETTLE);                // run at the minimum feasible interval

        // ---- T3 no partial commits ----
        wr(A_IL, MID[7:0]); mwait(3 * T_XFER);
        check("l_only_spi", spi_ivl, MIN_INTERVAL); check("l_only_applied", ivl_eff, MIN_INTERVAL);
        wr(A_IH, MID[15:8]); check("pair_spi", spi_ivl, MID);
        mwait(T_XFER + 2); check("pair_applied", ivl_eff, MID);
        wr(A_IL, 8'hFF); wr(A_IH, 8'hFF);                  // rejected pair
        mwait(T_XFER + 2); check("bad_pair_not_applied", ivl_eff, MID);
        wr(A_IH, MID[15:8]); mwait(T_XFER + 2);
        check("no_poisoned_shadow_applied", ivl_eff, MID);
        wr(A_CMD, 8'h02);
        mwait(2 * MID);

        // ---- T4 interval changes under traffic ----
        setivl(INTERVAL); mwait(2 * INTERVAL);
        setivl(MIN_INTERVAL); mwait(2 * MIN_INTERVAL + T_SETTLE);
        setivl(MID); mwait(2 * MID);
        setivl(MIN_INTERVAL + 1); mwait(2 * MIN_INTERVAL + T_SETTLE);
        setivl(INTERVAL - 1); mwait(2 * INTERVAL);
        setivl(INTERVAL); mwait(INTERVAL);

        // ---- T5 shortening near a deadline ----
        // The SPI commit (cs_n rise) is held until the oldest row is within
        // 'off' cycles of the scheduler's urgent threshold (negative: past it,
        // refresh already running). Target MIN_INTERVAL, then MID.
        offs[0] = 40; offs[1] = 34; offs[2] = 20; offs[3] = 8; offs[4] = 3; offs[5] = 1;
        offs[6] = 0; offs[7] = -1; offs[8] = -3; offs[9] = -10; offs[10] = -20; offs[11] = -30;
        for (oi = 0; oi < 14; oi = oi + 1) begin
            off = (oi < 12) ? offs[oi] : ((oi == 12) ? 2 : -5);
            tgt = (oi < 12) ? MIN_INTERVAL : MID;
            thr = INTERVAL - T_ROW - T_ACC - GUARD - off;
            wr(A_IL, tgt[7:0]);
            frame_lo({1'b1, A_IH, tgt[15:8]});             // cs_n held low: commit not yet
            lim = 0;
            while (cur_max_age < thr && lim < 3 * INTERVAL) begin @(negedge clk); lim = lim + 1; end
            n_near_try = n_near_try + 1;
            if (cur_max_age >= thr) n_near_hit = n_near_hit + 1;
            #(PH); frame_end;                              // commit
            check("near_deadline_spi", spi_ivl, tgt);
            mwait(T_SETTLE + 2 * tgt);
            check("near_deadline_applied", ivl_eff, tgt);
            setivl(INTERVAL); mwait(T_XFER + 2);
        end
        mwait(INTERVAL);

        // ---- T6 forced sweep: busy and completion contract ----
        tog0 = spi_tog; wr(A_CMD, 8'h01);
        check("sweep_accepted", spi_tog ^ tog0, 1);
        rdr(A_ST, v); check("busy_after_sweep_accept", v[7], 1);
        rdr(A_XST, v); check("xstat_sweep_active", v[2], 1);
        poll_idle("sweep_busy_clears", T_SWEEP + 4000);
        check("sweep_completed_when_idle", n_done, n_acc);
        // START_SWEEP while busy: refused (ERR_BUSY), not queued, not lost
        tog0 = spi_tog; wr(A_CMD, 8'h01); check("sweep2_accepted", spi_tog ^ tog0, 1);
        tog0 = spi_tog; wr(A_CMD, 8'h01); check("sweep_while_busy_refused", spi_tog ^ tog0, 0);
        rdr(A_ST, v); check("err_busy_flagged", v[3], 1);
        poll_idle("sweep2_busy_clears", T_SWEEP + 4000);
        check("one_completion_per_accept", n_done, n_acc);
        wr(A_CMD, 8'h02); rchk("busy_err_cleared", A_ST, 8'h00);
        // back-to-back: next START right after idle is accepted and executed
        tog0 = spi_tog; wr(A_CMD, 8'h01); check("sweep3_accepted", spi_tog ^ tog0, 1);
        poll_idle("sweep3_busy_clears", T_SWEEP + 4000);
        check("sweep3_completed", n_done, n_acc);

        // ---- T7 back-to-back configuration commands at minimum spacing ----
        setivl(MID); wr(A_CMD, 8'h01); setivl(MIN_INTERVAL); setivl(INTERVAL);
        wr(A_IL, MID[7:0]); wr(A_IH, MID[15:8]); wr(A_CTRL, 8'h01);
        mwait(T_SETTLE); check("b2b_final_applied", ivl_eff, MID);
        poll_idle("b2b_sweep_done", T_SWEEP + 4000); check("b2b_sweep_completed", n_done, n_acc);
        setivl(INTERVAL); mwait(INTERVAL);

        // ---- T8 disable / re-enable ----
        wr(A_CTRL, 8'h00); mwait(T_XFER + 2);
        check("disabled_applied", en_eff, 0);
        rchk("xstat_disabled", A_XST, 8'h02);                  // !REFRESH_OK, DATA_LOST
        mwait(INTERVAL + 2 * T_SWEEP);                         // rows age past the deadline
        tog0 = spi_tog; wr(A_CMD, 8'h01); check("sweep_while_disabled_accepted", spi_tog ^ tog0, 1);
        poll_idle("sweep_while_disabled_done", T_SWEEP + 4000);
        check("sweep_while_disabled_completed", n_done, n_acc);
        rchk("xstat_still_lost", A_XST, 8'h02);
        setivl(MID); mwait(T_XFER + 2); check("ivl_while_disabled", ivl_eff, MID);
        wr(A_CTRL, 8'h01);
        rdr(A_XST, v); check("reinit_not_ok_yet", v[0], 0); check("reinit_lost_kept", v[1], 1);
        rdr(A_ST, v); check("reinit_busy", v[7], 1);
        poll_idle("reinit_done", T_REARM + 4000);
        rchk("xstat_reenabled", A_XST, 8'h03);                 // REFRESH_OK, DATA_LOST (sticky)
        mwait(2 * MID);
        // short disable/enable pair back to back
        wr(A_CTRL, 8'h00); wr(A_CTRL, 8'h01);
        poll_idle("reinit2_done", T_REARM + 4000); rchk("xstat_reenabled2", A_XST, 8'h03);
        setivl(INTERVAL); mwait(INTERVAL);

        // ---- T9 reset during transfer ----
        // (a) reset asserted mid-frame (CTRL=0 write), frame completes during reset
        cs_n = 0; #(H); bits({1'b1, A_CTRL, 8'h00}, 0, 10);
        rst_n = 0; n_resets = n_resets + 1; bench_reset;
        bits({1'b1, A_CTRL, 8'h00}, 10, 6); #(H); cs_n = 1; #(3.3 + PH); rst_n = 1;
        mwait(4); check("rst_mid_frame_no_commit", spi_en, 1); check("rst_mid_frame_en", en_eff, 1);
        rchk("rst_mid_frame_status_busy_init", A_ST, 8'h80);   // BUSY: reset init sweep
        mwait(T_REARM); rchk("rst_mid_frame_xstat", A_XST, 8'h01);   // DATA_LOST cleared by reset
        // (b) reset pulse inside a frame; the frame tail alone is malformed
        cs_n = 0; #(H); bits({1'b1, A_CTRL, 8'h00}, 0, 5);
        do_reset(2.7);
        bits({1'b1, A_CTRL, 8'h00}, 5, 11); #(H); frame_end;
        check("rst_tail_no_commit", spi_en, 1);
        rchk("rst_tail_frame_err", A_ST, 8'h82);        // ERR_FRAME + BUSY (init sweep)
        wr(A_CMD, 8'h02);
        mwait(T_REARM);
        // (c) commit, then reset before the snapshot can be applied
        frame_lo({1'b1, A_CTRL, 8'h00}); cs_n = 1; #(1.3); do_reset(2.2); #(TCSH);
        mwait(4); check("rst_after_commit_spi", spi_en, 1); check("rst_after_commit_en", en_eff, 1);
        check("rst_after_commit_lost", data_lost, 0);
        mwait(T_REARM); rchk("rst_after_commit_xstat", A_XST, 8'h01);
        // (d) reset during a forced sweep: the sweep is cancelled, no phantom later
        tog0 = spi_tog; wr(A_CMD, 8'h01); check("sweep_before_rst_accepted", spi_tog ^ tog0, 1);
        mwait(300); do_reset(4.4);
        mwait(2 * T_SWEEP);
        check("no_phantom_sweep", n_done + n_cancel, n_acc);
        rchk("rst_sweep_xstat", A_XST, 8'h01);

        // ---- T10 final steady run ----
        mwait(2 * INTERVAL);
        end

        // final accounting
        #1;
        if (outstanding != 0) begin errors = errors + 1; n_lost = n_lost + outstanding;
            $display("LOST START_SWEEP: %0d outstanding at end", outstanding); end
        if (!NEG_SPACING) begin
            if (n_acc != n_done + n_cancel) begin errors = errors + 1;
                $display("SWEEP ACCOUNTING: accepted=%0d done=%0d cancelled=%0d", n_acc, n_done, n_cancel); end
            if (TRAFFIC != 0 && n_ext == 0) begin errors = errors + 1; $display("LIVENESS: no external access served"); end
            if (n_ref < 10 * N_ROWS) begin errors = errors + 1; $display("LIVENESS: only %0d refreshes", n_ref); end
            if (n_near_hit < 8) begin errors = errors + 1; $display("COVERAGE: near-deadline commit hit only %0d/%0d", n_near_hit, n_near_try); end
        end
        $display("RESULT INTERVAL=%0d MIN_INTERVAL=%0d sclk_half_ps=%0d phase_ps=%0d traffic=%0d neg=%0d cycles=%0d checks=%0d refreshes=%0d ext_ops=%0d sweeps_accepted=%0d sweeps_done=%0d sweeps_cancelled_by_reset=%0d resets=%0d shortenings=%0d max_transition_obs=%0d bound_T_SETTLE=%0d near_deadline_hits=%0d/%0d min_slack_vs_committed=%0d min_slack_vs_INTERVAL=%0d",
                 INTERVAL, MIN_INTERVAL, SCLK_HALF_PS, PHASE_PS, TRAFFIC, NEG_SPACING, cyc, checks,
                 n_ref, n_ext, n_acc, n_done, n_cancel, n_resets, n_shorten, trans_obs, T_SETTLE, n_near_hit, n_near_try,
                 min_slack, min_hard_slack);
        $display("ERRORS total=%0d deadline=%0d hard=%0d lost_sweep=%0d spurious=%0d incomplete_sweep=%0d ok_early=%0d unnoticed_invalid=%0d data_lost_flag=%0d not_applied=%0d partial=%0d cfg_reject=%0d rearm=%0d protocol=%0d",
                 errors, n_viol, n_hard, n_lost, n_spur, n_cov, n_okcov, n_unnoticed, n_lostflag,
                 n_conv, n_partial, n_reject, n_rearm, n_proto);
        if (errors == 0) $display("TB_RESULT: PASS"); else $display("TB_RESULT: FAIL (%0d errors)", errors);
        $finish;
    end
    initial begin #20000000; $display("TB_RESULT: FAIL (timeout)"); $finish; end
endmodule
