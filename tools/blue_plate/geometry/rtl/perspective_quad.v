`timescale 1ns/1ps
// Autonomous corner-to-ROI front end. Frame ownership stays with its caller.
module perspective_quad #(parameter COLOR_OUTPUT=0) (
    input wire clk,rst,abort,
    input wire start_valid,
    output wire start_ready,
    input wire corner_valid,
    output wire corner_ready,
    input wire signed [31:0] corner_data,
    output wire cmd_valid,
    input wire cmd_ready,
    output wire [10:0] cmd_x,
    output wire [9:0] cmd_y,
    output wire [8:0] cmd_width,
    output wire [6:0] cmd_height,
    input wire pixel_valid,
    output wire pixel_ready,
    input wire [23:0] rgb0,rgb1,
    input wire [1:0] keep,
    input wire [10:0] pixel_x,
    input wire [9:0] pixel_y,
    input wire line_last,cmd_last,
    input wire cmd_done_valid,
    output wire cmd_done_ready,
    output wire gray_write,
    output wire [13:0] gray_address,
    output wire [7:0] gray_data,
    output wire color_valid,
    input wire color_ready,
    output wire [23:0] color_rgb,
    output wire [13:0] color_address,
    output wire color_last,
    output wire result_valid,
    input wire result_ready,
    output reg [4:0] result_threshold,
    output reg [3:0] result_status
);
    // 0..7: perspective_roi; 9/10/11: bad corners/degenerate/overflow matrix.
    reg active,roi_started,holding,failed;
    wire local_abort=abort || failed;
    wire matrix_ready,roi_ready;
    assign start_ready=!active && matrix_ready && roi_ready && !rst && !abort;
    assign result_valid=holding && !rst && !abort;
    wire start_fire=start_valid && start_ready;
    wire coeff_valid,coeff_ready,coeff_last;
    wire signed [47:0] coeff_data;
    wire matrix_done;wire [1:0] matrix_status;
    perspective_matrix solver(.clk(clk),.rst(rst),.abort(local_abort),.start_valid(start_fire),.start_ready(matrix_ready),
        .corner_valid(corner_valid),.corner_ready(corner_ready),.corner_data(corner_data),
        .coeff_valid(coeff_valid),.coeff_ready(coeff_ready),.coeff_data(coeff_data),.coeff_last(coeff_last),
        .done_valid(matrix_done),.done_ready(1'b1),.done_status(matrix_status));
    wire roi_start=coeff_valid && !roi_started && active;
    wire roi_result;wire [4:0] roi_threshold;wire [2:0] roi_status;
    perspective_roi #(.COLOR_OUTPUT(COLOR_OUTPUT)) roi(.clk(clk),.rst(rst),.abort(local_abort),.start_valid(roi_start),.start_ready(roi_ready),
        .result_valid(roi_result),.result_ready(active && !holding),.result_threshold(roi_threshold),.result_status(roi_status),.*);
    always @(posedge clk) begin
        if (rst || abort) begin
            active<=0;roi_started<=0;holding<=0;failed<=0;result_threshold<=0;result_status<=0;
        end else begin
            if (start_fire) begin active<=1;result_threshold<=0;result_status<=0;end
            if (roi_start && roi_ready) roi_started<=1;
            if (active && !holding) begin
                if (matrix_done && matrix_status!=0) begin
                    holding<=1;failed<=1;result_status<=4'd8+{2'd0,matrix_status};
                end else if (roi_result) begin
                    holding<=1;result_threshold<=roi_threshold;result_status<={1'b0,roi_status};
                end
            end
            if (result_valid && result_ready) begin active<=0;roi_started<=0;holding<=0;failed<=0;end
        end
    end
endmodule
