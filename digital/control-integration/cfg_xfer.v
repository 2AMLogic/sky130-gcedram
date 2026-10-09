// Behavioral SPI -> scheduler configuration transfer (issue #93). PROPOSED.
//
// NOT a CDC sign-off. iverilog has no metastability model: this module shows
// the *protocol* (what is captured when, and why nothing is lost under the
// documented frame spacing), not that the physical crossing is safe.
//
// Scheme: bundled data qualified by cs_n.
//   * The SPI-domain bundle {spi_en, spi_ivl, spi_tog} is quasi-static: the
//     SPI slave changes it only at a cs_n rising edge (frame commit).
//   * cs_n is passed through a two-flop synchroniser (cs_s[1:0]) plus one
//     history flop (cs_s[2]). A synchronised rising edge means a frame ended
//     at least two clk edges ago; the whole bundle is captured on that cycle
//     into one snapshot and handed to the scheduler as a single cfg_valid
//     pulse on the next cycle. The bundle cannot change again before the next
//     cs_n rising edge.
//   * START_SWEEP is the toggle spi_tog; a snapshot carries cfg_sweep = 1 when
//     the captured toggle differs from the last captured one. Two accepted
//     toggles between captures would cancel; that is prevented by the frame
//     spacing below together with the SPI slave refusing START_SWEEP while
//     busy_in (ERR_BUSY) -- pending is part of busy_in.
//   * pending covers the window from the synchronised cs_n rise to the cycle
//     the snapshot is applied, so the scheduler's sweep_active takes over
//     busy without a gap.
//
// Documented frame spacing (ASSUMPTION, see CONTRACT.md): cs_n must stay
// high for >= 4 clk periods between frames and low for >= 4 clk periods per
// frame. Every commit is then captured (the high pulse is seen by the
// synchroniser) and busy is visible before the next frame can commit.
// The negative-control run in run_tests.sh violates this on purpose and the
// bench must report the resulting lost START_SWEEP.
module cfg_xfer (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        cs_n,          // SPI chip select, asynchronous to clk
    input  wire        spi_en,        // quasi-static SPI-domain bundle
    input  wire [15:0] spi_ivl,
    input  wire        spi_tog,
    output reg         cfg_valid,     // 1-cycle snapshot strobe (clk domain)
    output reg         cfg_en,
    output reg  [15:0] cfg_interval,
    output reg         cfg_sweep,
    output wire        pending
);
    reg [2:0] cs_s;
    reg       tog_seen;
    wire      cs_rise = cs_s[1] && !cs_s[2];                           // MUT_EDGE

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cs_s <= 3'b111; tog_seen <= 1'b0;   // spi_slave resets sweep_tog to 0 too
            cfg_valid <= 1'b0; cfg_en <= 1'b1; cfg_interval <= 16'd0; cfg_sweep <= 1'b0;
        end else begin
            cs_s      <= {cs_s[1:0], cs_n};
            cfg_valid <= 1'b0;
            cfg_sweep <= 1'b0;
            if (cs_rise) begin
                cfg_valid    <= 1'b1;
                cfg_en       <= spi_en;
                cfg_interval <= spi_ivl;
                cfg_sweep    <= (spi_tog != tog_seen);                  // MUT_TOG
                tog_seen     <= spi_tog;
            end
        end
    end

    assign pending = (cs_s[0] && !cs_s[2]) || cfg_valid;                // MUT_PENDING
endmodule
