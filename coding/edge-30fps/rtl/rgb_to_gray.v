// Two adjacent RGB pixels become RGBY; metadata advances with the pixels.
module rgb_to_gray (
    input clk, rst_n,
    input in_valid,
    output in_ready,
    input [63:0] in_rgb,
    input in_sof, in_eol, in_eof,
    input [31:0] in_frame_id, in_epoch,
    output reg out_valid,
    input out_ready,
    output reg [63:0] out_rgby,
    output reg out_sof, out_eol, out_eof,
    output reg [31:0] out_frame_id, out_epoch
);
    function [7:0] luma;
        input [23:0] rgb;
        reg [15:0] sum;
        begin
            sum = 16'd77*rgb[23:16] + 16'd150*rgb[15:8]
                + 16'd29*rgb[7:0] + 16'd128;
            luma = sum[15:8];
        end
    endfunction

    assign in_ready = !out_valid || out_ready;
    always @(posedge clk) begin
        if (!rst_n) begin
            out_valid <= 0;
            out_rgby <= 0;
            out_sof <= 0; out_eol <= 0; out_eof <= 0;
            out_frame_id <= 0; out_epoch <= 0;
        end else if (in_ready) begin
            out_valid <= in_valid;
            if (in_valid) begin
                out_rgby <= {luma(in_rgb[55:32]), in_rgb[55:32],
                             luma(in_rgb[23:0]), in_rgb[23:0]};
                out_sof <= in_sof; out_eol <= in_eol; out_eof <= in_eof;
                out_frame_id <= in_frame_id; out_epoch <= in_epoch;
            end
        end
    end
endmodule
