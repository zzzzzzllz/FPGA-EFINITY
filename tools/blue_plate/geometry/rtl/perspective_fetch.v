`timescale 1ns/1ps
// Fetch four neighbors from the held frame_reader job, then interpolate RGB.
// A command is at most 2x2 pixels; frame_reader owns DDR framing and cancellation.
module perspective_fetch (
    input wire clk,rst,abort,
    input wire sample_valid,
    output wire sample_ready,
    input wire signed [31:0] source_x32,source_y32,
    input wire [7:0] dest_x,
    input wire [5:0] dest_y,
    input wire sample_last,
    output wire cmd_valid,
    input wire cmd_ready,
    output reg [10:0] cmd_x,
    output reg [9:0] cmd_y,
    output reg [8:0] cmd_width,
    output reg [6:0] cmd_height,
    input wire pixel_valid,
    output wire pixel_ready,
    input wire [23:0] rgb0,rgb1,
    input wire [1:0] keep,
    input wire [10:0] pixel_x,
    input wire [9:0] pixel_y,
    input wire line_last,cmd_last,
    input wire cmd_done_valid,
    output wire cmd_done_ready,
    output wire out_valid,
    input wire out_ready,
    output reg [23:0] out_rgb,
    output reg [7:0] out_x,
    output reg [5:0] out_y,
    output reg out_last,
    output wire fault
);
    localparam IDLE=0,WEIGHT_PRODUCT=1,WEIGHTS=2,COMMAND=3,PIXELS=4,
               COMMAND_DONE=5,INTERPOLATE=6,OUTPUT_PIXEL=7,FAILED=8;
    reg [3:0] state;
    reg [4:0] fx,fy;
    reg [9:0] cross_weight;
    reg [10:0] weights [0:3];
    reg [23:0] pixels [0:3];
    reg left_missing,top_missing,row;
    reg [1:0] pixel_index,channel;
    reg [18:0] accumulator;
    wire reset_local=rst || abort;
    wire signed [31:0] ix=source_x32>>>5,iy=source_y32>>>5;
    wire [1:0] write_index={row | top_missing,left_missing};
    wire [23:0] selected=pixels[pixel_index];
    wire [7:0] byte_value=channel==0 ? selected[23:16] : channel==1 ? selected[15:8] : selected[7:0];
    wire [10:0] factor_a=state==WEIGHT_PRODUCT ? {6'd0,fx} : weights[pixel_index];
    wire [7:0] factor_b=state==WEIGHT_PRODUCT ? {3'd0,fy} : byte_value;
    wire [18:0] product=factor_a*factor_b;
    wire [18:0] sum=(pixel_index==0 ? 19'd0 : accumulator)+product;
    wire [18:0] rounded_sum=sum+19'd512;
    assign sample_ready=state==IDLE && !reset_local;
    assign cmd_valid=state==COMMAND && !reset_local;
    assign pixel_ready=state==PIXELS && !reset_local;
    assign cmd_done_ready=state==COMMAND_DONE && !reset_local;
    assign out_valid=state==OUTPUT_PIXEL && !reset_local;
    assign fault=state==FAILED && !reset_local;
    integer i;
    always @(posedge clk) begin
        if (reset_local) begin
            state<=IDLE;out_rgb<=0;out_x<=0;out_y<=0;out_last<=0;
            cmd_x<=0;cmd_y<=0;cmd_width<=0;cmd_height<=0;
        end else case(state)
            IDLE: if (sample_valid) begin
                out_x<=dest_x;out_y<=dest_y;out_last<=sample_last;out_rgb<=0;
                if (ix < -1 || ix>=1280 || iy < -1 || iy>=720) state<=OUTPUT_PIXEL;
                else begin
                    fx<=source_x32[4:0];fy<=source_y32[4:0];
                    left_missing<=ix==-1;top_missing<=iy==-1;row<=0;
                    cmd_x<=ix==-1 ? 11'd0 : ix[10:0];
                    cmd_y<=iy==-1 ? 10'd0 : iy[9:0];
                    cmd_width<=ix==-1 || ix==1279 ? 9'd1 : 9'd2;
                    cmd_height<=iy==-1 || iy==719 ? 7'd1 : 7'd2;
                    for (i=0;i<4;i=i+1) pixels[i]<=0;
                    state<=WEIGHT_PRODUCT;
                end
            end
            WEIGHT_PRODUCT: begin cross_weight<=product[9:0];state<=WEIGHTS;end
            WEIGHTS: begin
                weights[0]<=11'd1024-({6'd0,fx}<<5)-({6'd0,fy}<<5)+{1'b0,cross_weight};
                weights[1]<=({6'd0,fx}<<5)-{1'b0,cross_weight};
                weights[2]<=({6'd0,fy}<<5)-{1'b0,cross_weight};
                weights[3]<={1'b0,cross_weight};state<=COMMAND;
            end
            COMMAND: if (cmd_ready) state<=PIXELS;
            PIXELS: if (pixel_valid) begin
                if (keep!=(cmd_width==2 ? 2'b11 : 2'b01) || !line_last ||
                    cmd_last!=(row==cmd_height-1'b1) || pixel_x!=cmd_x || pixel_y!=cmd_y+row)
                    state<=FAILED;
                else begin
                    pixels[write_index]<=rgb0;
                    if (keep[1]) pixels[write_index+1'b1]<=rgb1;
                    if (cmd_last) state<=COMMAND_DONE;else row<=1;
                end
            end
            COMMAND_DONE: if (cmd_done_valid) begin
                pixel_index<=0;channel<=0;accumulator<=0;state<=INTERPOLATE;
            end
            INTERPOLATE: begin
                accumulator<=sum;
                if (pixel_index==3) begin
                    case(channel)
                        0:out_rgb[23:16]<=rounded_sum[17:10];
                        1:out_rgb[15:8]<=rounded_sum[17:10];
                        2:out_rgb[7:0]<=rounded_sum[17:10];
                    endcase
                    pixel_index<=0;
                    if (channel==2) state<=OUTPUT_PIXEL;else channel<=channel+1'b1;
                end else pixel_index<=pixel_index+1'b1;
            end
            OUTPUT_PIXEL: if (out_ready) state<=IDLE;
            FAILED: ; // Owner cancels the frame_reader job, then aborts this stage.
        endcase
    end
endmodule
