`timescale 1ns/1ps
// Defaults retain frozen linear0.1; experiments override width, ROM and thresholds.
// Source ROI normalization is upstream. This block consumes features only.
module char_linear #(
    parameter WEIGHT_FILE = "w1-s10.bin",
    parameter BIAS_FILE = "b1.mem",
    parameter signed [31:0] PROVINCE_SCORE = -32'sd1351,
    parameter signed [31:0] PROVINCE_MARGIN = 32'sd4245,
    parameter signed [31:0] ALNUM_SCORE = -32'sd20593,
    parameter signed [31:0] ALNUM_MARGIN = 32'sd3556,
    parameter WEIGHT_BITS = 10
) (
    input wire clk,
    input wire rst,
    input wire start_valid,
    output wire start_ready,
    input wire [2:0] position,
    input wire feature_valid,
    output wire feature_ready,
    input wire [5:0] feature_data,
    output wire result_valid,
    input wire result_ready,
    output reg [6:0] result_id,
    output reg signed [31:0] result_score,
    output reg signed [31:0] result_margin,
    output reg result_accept,
    output reg result_error,
    output wire score_valid,
    output wire [6:0] score_id,
    output wire signed [31:0] score_value
);
    localparam IDLE=0, LOAD=1, BIAS_READ=2, BIAS_LOAD=3,
               READ=4, MAC=5, SCORE=6, FINISH=7, HOLD=8;
    reg [3:0] state;
    reg [2:0] position_q;
    reg [8:0] feature_index;
    reg [6:0] class_id;
    reg [14:0] weight_address;
    (* syn_ramstyle = "block_ram" *) reg [5:0] feature_mem [0:319];
    (* syn_romstyle = "block_rom" *) reg signed [WEIGHT_BITS-1:0] weight_mem [0:20799];
    (* syn_romstyle = "block_rom" *) reg signed [31:0] bias_mem [0:64];
    reg [5:0] feature_q;
    reg signed [WEIGHT_BITS-1:0] weight_q;
    reg signed [31:0] bias_q;
    reg signed [31:0] accumulator;
    reg signed [31:0] best_score, second_score;
    reg [6:0] best_id;
    (* syn_use_dsp = "yes" *) wire signed [WEIGHT_BITS+6:0] product;
    assign product = $signed({1'b0,feature_q}) * weight_q;
    wire signed [31:0] product_extended = product;
    wire class_allowed = (position_q == 0) ? (class_id < 31) :
                         (position_q == 1) ? (class_id >= 31 && class_id < 55) :
                                            (class_id >= 31);
    wire signed [31:0] margin = best_score - second_score;
    assign start_ready = state == IDLE && !rst;
    assign feature_ready = state == LOAD && !rst;
    assign result_valid = state == HOLD && !rst;
    assign score_valid = state == SCORE && !rst;
    assign score_id = class_id;
    assign score_value = accumulator;

    generate if (WEIGHT_BITS != 10 && WEIGHT_BITS != 11) begin: invalid_weight_width
        initial $fatal(1,"WEIGHT_BITS must be 10 or 11");
    end endgenerate

    initial begin
        $readmemb(WEIGHT_FILE, weight_mem, 0, 20799);
        $readmemh(BIAS_FILE, bias_mem, 0, 64);
    end

    // Synchronous read templates match Efinity block memory inference.
    // RAM contents need no reset: every request loads all 320 features.
    always @(posedge clk) begin
        if (state == LOAD && feature_valid && !rst && feature_data <= 32)
            feature_mem[feature_index] <= feature_data;
        if (state == READ) begin
            feature_q <= feature_mem[feature_index];
            weight_q <= weight_mem[weight_address];
        end
        if (state == BIAS_READ)
            bias_q <= bias_mem[class_id];
    end

    always @(posedge clk) begin
        if (rst) begin
            state <= IDLE;
            position_q <= 0;
            feature_index <= 0;
            class_id <= 0;
            weight_address <= 0;
            accumulator <= 0;
            best_score <= -32'sh7fffffff-1;
            second_score <= -32'sh7fffffff-1;
            best_id <= 0;
            result_id <= 0;
            result_score <= 0;
            result_margin <= 0;
            result_accept <= 0;
            result_error <= 0;
        end else begin
            case (state)
                IDLE: if (start_valid) begin
                    position_q <= position;
                    feature_index <= 0;
                    class_id <= 0;
                    weight_address <= 0;
                    best_score <= -32'sh7fffffff-1;
                    second_score <= -32'sh7fffffff-1;
                    best_id <= 0;
                    result_error <= 0;
                    result_accept <= 0;
                    if (position == 7) begin
                        result_error <= 1;
                        result_id <= 0;
                        result_score <= 0;
                        result_margin <= 0;
                        state <= HOLD;
                    end else state <= LOAD;
                end
                LOAD: if (feature_valid) begin
                    if (feature_data > 32) begin
                        result_error <= 1;
                        result_accept <= 0;
                        result_id <= 0;
                        result_score <= 0;
                        result_margin <= 0;
                        state <= HOLD;
                    end else if (feature_index == 319) begin
                        feature_index <= 0;
                        state <= BIAS_READ;
                    end else feature_index <= feature_index + 1'b1;
                end
                BIAS_READ: state <= BIAS_LOAD;
                BIAS_LOAD: begin
                    accumulator <= bias_q;
                    feature_index <= 0;
                    state <= READ;
                end
                READ: state <= MAC;
                MAC: begin
                    accumulator <= accumulator + product_extended;
                    weight_address <= weight_address + 1'b1;
                    if (feature_index == 319) state <= SCORE;
                    else begin
                        feature_index <= feature_index + 1'b1;
                        state <= READ;
                    end
                end
                SCORE: begin
                    // IDs arrive in ascending order. Strict > preserves lower-ID
                    // ties; the second score always comes from a different class.
                    if (class_allowed) begin
                        if (accumulator > best_score) begin
                            second_score <= best_score;
                            best_score <= accumulator;
                            best_id <= class_id;
                        end else if (accumulator > second_score)
                            second_score <= accumulator;
                    end
                    if (class_id == 64) state <= FINISH;
                    else begin
                        class_id <= class_id + 1'b1;
                        state <= BIAS_READ;
                    end
                end
                FINISH: begin
                    result_id <= best_id;
                    result_score <= best_score;
                    result_margin <= margin;
                    result_accept <= (position_q == 0) ?
                        (best_score >= PROVINCE_SCORE && margin >= PROVINCE_MARGIN) :
                        (best_score >= ALNUM_SCORE && margin >= ALNUM_MARGIN);
                    state <= HOLD;
                end
                HOLD: if (result_ready) state <= IDLE;
                default: begin
                    result_error <= 1;
                    result_accept <= 0;
                    state <= HOLD;
                end
            endcase
        end
    end
endmodule
