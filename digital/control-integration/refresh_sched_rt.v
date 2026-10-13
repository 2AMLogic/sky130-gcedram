// Runtime-configurable behavioral refresh scheduler (issue #93, epic #24).
// PROPOSED, behavioral, NOT synthesis. A gain-cell array is dynamic; this is a
// refresh controller model, not an SRAM-replacement controller.
//
// Derived from digital/refresh-scheduler/refresh_sched.v (#74), which is left
// unchanged. Same policy (lazy, deadline-driven, round-robin, one
// non-preemptible op at a time, urgent refresh beats external requests, eager
// refresh when idle). With cfg_valid never asserted this module is
// cycle-for-cycle identical to refresh_sched; tb_equiv.v checks that in
// lockstep for every output, at both sourced intervals and all three #74
// traffic scenarios.
//
// Additions (proposed contract, see CONTRACT.md):
//   * The interval is a register (ivl_eff), reset to INTERVAL. INTERVAL is
//     therefore both the reset value and the upper bound (the ratified
//     refresh interval in the integration).
//   * Runtime feasibility floor MIN_INTERVAL = N_ROWS*T_ROW + T_ACC + GUARD:
//     exactly the #74 elaboration check (EAGER_AGE >= 0, which implies
//     URGENT_AGE >= 0) evaluated for a runtime value. A snapshot outside
//     [MIN_INTERVAL, INTERVAL] is refused whole and sets sticky cfg_reject.
//   * A snapshot (cfg_valid pulse) is applied whole in one cycle: interval,
//     enable and a sweep request together (no partial application).
//   * Interval change takes effect immediately in the urgent/eager thresholds.
//     Lengthening is trivially safe. Shortening is a BOUNDED TRANSITION: the
//     pointer row is the oldest, so every row now older than the new urgent
//     threshold is refreshed back to back from the pointer; the old deadline
//     still holds for every row during that burst, and the new deadline holds
//     for every row from T_ACC + GUARD + N_ROWS*T_ROW cycles after
//     application (the bench checks a bound that includes T_ROW of slack).
//   * Sweep: N_ROWS back-to-back refreshes starting at the pointer (oldest)
//     row, with priority over external requests. Used for the reset
//     initialisation (as in #74), for re-initialisation after re-enable, and
//     for a forced START_SWEEP. A sweep request while a sweep is running
//     restarts the count, so every row is refreshed after the latest request.
//     sweep_done pulses when a sweep that contained a forced request ends.
//   * Disable: no urgent/eager refresh starts (a running op or sweep
//     completes). Disabling sets sticky data_lost (cleared only by reset).
//     Re-enable starts a re-initialisation sweep; refresh_ok stays low until
//     it has completed. refresh_ok = enabled and (re)initialisation complete.
//
// All times are clock cycles; 1 cycle = 1 ns is an ASSUMPTION of the README.
module refresh_sched_rt #(
    parameter integer N_ROWS   = 32,    // ASSUMPTION (array not designed)
    parameter integer T_ROW    = 34,    // ASSUMPTION t_row_refresh_op, cycles
    parameter integer T_ACC    = 34,    // ASSUMPTION external op duration
    parameter integer INTERVAL = 5029,  // reset value and upper bound, cycles
    parameter integer GUARD    = 2,     // decision-latency guard, cycles
    parameter integer ROW_W    = (N_ROWS > 1) ? $clog2(N_ROWS) : 1
) (
    input  wire             clk,
    input  wire             rst_n,
    // external request (hold until req_accept)                 -- as #74
    input  wire             req_valid,
    input  wire             req_we,
    input  wire [ROW_W-1:0] req_row,
    output reg              req_accept,
    // array-side operation                                      -- as #74
    output reg              op_busy,
    output reg              op_is_refresh,
    output reg              op_is_write,
    output reg [ROW_W-1:0]  op_row,
    output reg              op_done,
    // configuration snapshot (scheduler clock domain)           -- #93
    input  wire             cfg_valid,      // 1-cycle: apply {cfg_en, cfg_interval, cfg_sweep}
    input  wire             cfg_en,
    input  wire [15:0]      cfg_interval,
    input  wire             cfg_sweep,
    output reg              en_eff,         // applied enable
    output reg  [15:0]      ivl_eff,        // applied interval, cycles
    output wire             sweep_active,
    output reg              sweep_done,     // 1-cycle: a forced sweep completed
    output wire             refresh_ok,     // enabled and (re)initialisation sweep complete
    output reg              data_lost,      // sticky: refresh was disabled since reset
    output reg              cfg_reject      // sticky: an infeasible snapshot was refused
);
    localparam integer MIN_INTERVAL = N_ROWS * T_ROW + T_ACC + GUARD;

    initial if (INTERVAL < MIN_INTERVAL || INTERVAL > 65535) begin
        $display("refresh_sched_rt: INFEASIBLE parameters (N_ROWS*T_ROW+T_ACC+GUARD > INTERVAL or INTERVAL > 16 bit)");
        $finish;
    end

    reg [31:0]        now;
    reg [31:0]        last_ref [0:N_ROWS-1];
    reg [ROW_W-1:0]   ptr;
    reg [31:0]        cnt;
    reg [31:0]        sw_left;     // rows still to refresh in the current sweep
    reg               sw_forced;   // current sweep contains a forced request
    reg               reinit;      // current sweep is a (re)initialisation
    integer           i;

    wire [31:0] urgent_age = ivl_eff - T_ROW - T_ACC - GUARD;                 // MUT_URGENT
    wire [31:0] eager_age  = ivl_eff - (N_ROWS * T_ROW) - T_ACC - GUARD;
    wire [31:0] age        = now - last_ref[ptr];
    wire        sweeping   = (sw_left != 0);
    wire        urgent     = sweeping || (en_eff && (age >= urgent_age));
    wire        eager      = en_eff && !req_valid && (age >= eager_age);
    wire        cfg_ok     = (cfg_interval >= MIN_INTERVAL) && (cfg_interval <= INTERVAL);  // MUT_FLOOR

    assign sweep_active = sweeping;
    assign refresh_ok   = en_eff && !reinit;                                  // MUT_OK

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            now <= 0; ptr <= 0; cnt <= 0;
            op_busy <= 0; op_done <= 0; req_accept <= 0;
            op_is_refresh <= 0; op_is_write <= 0; op_row <= 0;
            for (i = 0; i < N_ROWS; i = i + 1) last_ref[i] <= 0;
            sw_left <= N_ROWS; sw_forced <= 0; reinit <= 1;   // reset initialisation sweep (#74)
            en_eff <= 1; ivl_eff <= INTERVAL;
            sweep_done <= 0; data_lost <= 0; cfg_reject <= 0;
        end else begin
            now        <= now + 1;
            op_done    <= 0;
            req_accept <= 0;
            sweep_done <= 0;
            if (op_busy) begin
                cnt <= cnt - 1;
                if (cnt == 1) begin
                    op_busy <= 0;
                    op_done <= 1;
                    if (op_is_refresh) begin
                        last_ref[op_row] <= now;
                        ptr <= (ptr == N_ROWS-1) ? 0 : ptr + 1;
                        if (sw_left == 1) begin
                            reinit     <= 0;
                            sweep_done <= sw_forced;
                            sw_forced  <= 0;
                        end
                        if (sw_left != 0) sw_left <= sw_left - 1;
                    end
                end
            end else if (urgent || eager) begin
                op_busy <= 1; op_is_refresh <= 1; op_is_write <= 0;
                op_row <= ptr; cnt <= T_ROW;
            end else if (req_valid) begin
                op_busy <= 1; op_is_refresh <= 0; op_is_write <= req_we;
                op_row <= req_row; cnt <= T_ACC; req_accept <= 1;
            end
            // Configuration snapshot: applied whole, after the scheduling
            // decision of this cycle (later non-blocking assignments win).
            if (cfg_valid) begin
                if (!cfg_ok) cfg_reject <= 1;          // refuse the whole snapshot
                else begin
                    ivl_eff <= cfg_interval;            // MUT_APPLY_IVL
                    en_eff  <= cfg_en;
                    if (en_eff && !cfg_en) data_lost <= 1;                      // MUT_LOST
                    if (!en_eff && cfg_en) begin sw_left <= N_ROWS; reinit <= 1; end  // MUT_REINIT
                    if (cfg_sweep) begin sw_left <= N_ROWS; sw_forced <= 1; end // MUT_SWEEP
                end
            end
        end
    end
endmodule
