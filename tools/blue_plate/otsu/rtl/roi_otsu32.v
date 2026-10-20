`timescale 1ns/1ps
// RGB ROI stream -> exact gray histogram -> otsu32. No image storage.
module roi_otsu32 (
    input wire clk, rst, abort,
    input wire start_valid,
    output wire start_ready,
    input wire [15:0] pixel_count,
    input wire pixel_valid,
    output wire pixel_ready,
    input wire [23:0] rgb0, rgb1,
    input wire [1:0] keep,
    input wire pixel_last,
    output wire result_valid,
    input wire result_ready,
    output reg [4:0] result_threshold,
    output reg [2:0] result_status
);
    // Status 0..3 matches otsu32; 4 means malformed keep/count/last.
    // abort discards a local task; the owner separately drains/releases DDR.
    localparam IDLE=0, CLEAR=1, RECEIVE=2, READ_BIN=3, WRITE_BIN=4,
               START_CORE=5, READ_HIST=6, SEND_HIST=7, WAIT_CORE=8, HOLD=9;
    reg [3:0] state;
    reg [4:0] index, bin, second_bin;
    reg second_pending, last_pending;
    reg [14:0] histogram [0:31];
    reg [14:0] count_read;
    reg [15:0] remaining;
    wire reset_local=rst || abort;
    wire core_start_ready, core_hist_ready, core_result_valid;
    wire [4:0] core_threshold;
    wire [1:0] core_status;

    function [4:0] gray_bin;
        input [23:0] rgb;
        reg [15:0] r,g,b,total;
        begin
            r={8'd0,rgb[23:16]};g={8'd0,rgb[15:8]};b={8'd0,rgb[7:0]};
            total=(r<<6)+(r<<3)+(r<<2)+r
                 +(g<<7)+(g<<4)+(g<<2)+(g<<1)
                 +(b<<4)+(b<<3)+(b<<2)+b;
            gray_bin=total[15:11];
        end
    endfunction

    wire [15:0] beat_count=keep==2'b11 ? 16'd2 : 16'd1;
    wire [4:0] memory_address=(state==CLEAR || state==READ_HIST) ? index : bin;
    always @(posedge clk) begin
        if (!reset_local) begin
            if (state==CLEAR || state==WRITE_BIN)
                histogram[memory_address]<=state==CLEAR ? 15'd0 : count_read+15'd1;
            if (state==READ_BIN || state==READ_HIST)
                count_read<=histogram[memory_address];
        end
    end
    assign start_ready=state==IDLE && !reset_local;
    assign pixel_ready=state==RECEIVE && !reset_local;
    assign result_valid=state==HOLD && !reset_local;
    otsu32 core (
        .clk(clk),.rst(reset_local),
        .start_valid(state==START_CORE && !reset_local),.start_ready(core_start_ready),
        .hist_valid(state==SEND_HIST && !reset_local),.hist_ready(core_hist_ready),
        .hist_count(count_read),
        .result_valid(core_result_valid),.result_ready(state==WAIT_CORE && !reset_local),
        .result_threshold(core_threshold),.result_status(core_status)
    );

    // A completed write always precedes the next read, including equal bins.
    always @(posedge clk) begin
        if (reset_local) begin
            state<=IDLE;result_threshold<=0;result_status<=0;
        end else case (state)
            IDLE: if (start_valid) begin
                result_threshold<=0;result_status<=0;
                if (pixel_count==0) begin result_status<=1;state<=HOLD;end
                else if (pixel_count>30720) begin result_status<=2;state<=HOLD;end
                else begin remaining<=pixel_count;index<=0;state<=CLEAR;end
            end
            CLEAR: begin
                if (index==31) state<=RECEIVE;
                else index<=index+1'b1;
            end
            RECEIVE: if (pixel_valid) begin
                if ((keep!=2'b01 && keep!=2'b11) || remaining<beat_count ||
                    pixel_last!=(remaining==beat_count)) begin
                    result_status<=4;state<=HOLD;
                end else begin
                    remaining<=remaining-beat_count;
                    bin<=gray_bin(rgb0);second_bin<=gray_bin(rgb1);
                    second_pending<=keep[1];last_pending<=pixel_last;
                    state<=READ_BIN;
                end
            end
            READ_BIN: state<=WRITE_BIN;
            WRITE_BIN: begin
                if (second_pending) begin
                    bin<=second_bin;second_pending<=0;state<=READ_BIN;
                end else if (last_pending) state<=START_CORE;
                else state<=RECEIVE;
            end
            START_CORE: if (core_start_ready) begin index<=0;state<=READ_HIST;end
            READ_HIST: state<=SEND_HIST;
            SEND_HIST: if (core_hist_ready) begin
                if (index==31) state<=WAIT_CORE;
                else begin index<=index+1'b1;state<=READ_HIST;end
            end
            WAIT_CORE: if (core_result_valid) begin
                result_threshold<=core_threshold;result_status<={1'b0,core_status};state<=HOLD;
            end
            HOLD: if (result_ready) state<=IDLE;
        endcase
    end
endmodule
