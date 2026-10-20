// Generated configuration wrapper. One shared char_linear implementation.
module geometry11_char_linear (
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
    output wire [6:0] result_id,
    output wire signed [31:0] result_score,
    output wire signed [31:0] result_margin,
    output wire result_accept,
    output wire result_error,
    output wire score_valid,
    output wire [6:0] score_id,
    output wire signed [31:0] score_value
);
    char_linear #(
        .WEIGHT_BITS(11),
        .WEIGHT_FILE("w1-s11.bin"),
        .BIAS_FILE("b1.mem"),
        .PROVINCE_SCORE(174),
        .PROVINCE_MARGIN(4417),
        .ALNUM_SCORE(-21431),
        .ALNUM_MARGIN(4068)
    ) core (.*);
endmodule
