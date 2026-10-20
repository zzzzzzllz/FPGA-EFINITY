`timescale 1ns/1ps
// One held-frame ROI: inverse Q32 matrix -> reader commands -> RGB -> Otsu.
// Capture gray_write into a 224x64 gray RAM for the subsequent split stage.
module perspective_roi #(parameter COLOR_OUTPUT=0) (
    input wire clk,rst,abort,
    input wire start_valid,
    output wire start_ready,
    input wire coeff_valid,
    output wire coeff_ready,
    input wire signed [47:0] coeff_data,
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
    output reg [2:0] result_status
);
    // Codes 0..4 are roi_otsu32; 5/6 coordinate denominator/overflow, 7 bad reader stream.
    reg active,holding,failed;
    wire local_abort=abort || failed;
    wire coords_ready,otsu_ready;
    wire start_fire=start_valid && start_ready;
    assign start_ready=!active && coords_ready && otsu_ready && !rst && !abort;
    assign result_valid=holding && !rst && !abort;
    wire sample_valid,sample_ready,sample_last;
    wire signed [31:0] source_x32,source_y32;
    wire [7:0] dest_x;
    wire [5:0] dest_y;
    wire coords_done;wire [1:0] coords_status;
    wire coords_coeff_ready;
    assign coeff_ready=active && !holding && coords_coeff_ready && !abort;
    perspective_coords coords(
        .clk(clk),.rst(rst),.abort(local_abort),.start_valid(start_fire),.start_ready(coords_ready),
        .coeff_valid(coeff_valid && active && !holding),.coeff_ready(coords_coeff_ready),.coeff_data(coeff_data),
        .sample_valid(sample_valid),.sample_ready(sample_ready),.source_x32(source_x32),.source_y32(source_y32),
        .dest_x(dest_x),.dest_y(dest_y),.sample_last(sample_last),
        .done_valid(coords_done),.done_ready(1'b1),.done_status(coords_status));
    wire out_valid,out_ready,out_last,fault;
    wire [23:0] out_rgb;wire [7:0] out_x;wire [5:0] out_y;
    perspective_fetch fetch(.clk(clk),.rst(rst),.abort(local_abort),.*);
    wire otsu_result,otsu_pixel_ready;wire [4:0] otsu_threshold;wire [2:0] otsu_status;
    wire color_accept=!COLOR_OUTPUT || color_ready;
    // Both consumers accept the same pixel, once. The fetch register holds stalls.
    assign out_ready=otsu_pixel_ready && color_accept;
    assign color_valid=COLOR_OUTPUT && out_valid && otsu_pixel_ready && active && !holding && !local_abort && !rst;
    assign color_rgb=out_rgb;
    assign color_address=gray_address;
    assign color_last=out_last;
    roi_otsu32 otsu(.clk(clk),.rst(rst),.abort(local_abort),.start_valid(start_fire),.start_ready(otsu_ready),.pixel_count(16'd14336),
        .pixel_valid(out_valid && color_accept),.pixel_ready(otsu_pixel_ready),.rgb0(out_rgb),.rgb1(24'd0),.keep(2'b01),.pixel_last(out_last),
        .result_valid(otsu_result),.result_ready(active && !holding),.result_threshold(otsu_threshold),.result_status(otsu_status));
    wire [15:0] r={8'd0,out_rgb[23:16]},g={8'd0,out_rgb[15:8]},b={8'd0,out_rgb[7:0]};
    wire [15:0] gray_sum=(r<<6)+(r<<3)+(r<<2)+r+(g<<7)+(g<<4)+(g<<2)+(g<<1)+(b<<4)+(b<<3)+(b<<2)+b;
    assign gray_data=gray_sum[15:8];
    assign gray_address=({8'd0,out_y}<<8)-({8'd0,out_y}<<5)+{6'd0,out_x};
    assign gray_write=out_valid && out_ready && active && !holding && !local_abort && !rst;
    always @(posedge clk) begin
        if (rst || abort) begin
            active<=0;holding<=0;failed<=0;result_threshold<=0;result_status<=0;
        end else begin
            if (start_fire) begin active<=1;result_threshold<=0;result_status<=0;end
            if (active && !holding) begin
                if (fault || (coords_done && coords_status!=0)) begin
                    failed<=1;holding<=1;result_status<=fault ? 3'd7 : coords_status==1 ? 3'd5 : 3'd6;
                end else if (otsu_result) begin
                    holding<=1;result_threshold<=otsu_threshold;result_status<=otsu_status;
                end
            end
            if (result_valid && result_ready) begin active<=0;holding<=0;failed<=0;end
        end
    end
endmodule
