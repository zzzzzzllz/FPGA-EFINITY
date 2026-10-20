`timescale 1ns/1ps
// One held-frame geometry/Q8 job. The external sink owns provisional writes and drain.
module geometry_ocr_input (
    input wire clk,rst,
    input wire job_valid,output wire job_ready,
    input wire [5:0] job_slot,
    input wire [31:0] job_frame_id,job_epoch,job_generation,job_source_time_ms,
    input wire [31:0] config_epoch,config_generation,
    output wire hold_valid,input wire hold_ready,hold_granted,
    output wire [133:0] hold_identity,
    output wire held,output wire [5:0] held_slot,
    output wire [133:0] identity,
    input wire corner_valid,output wire corner_ready,input wire signed [31:0] corner_data,
    input wire cancel_valid,
    output wire burst_valid,input wire burst_ready,
    output wire [31:0] burst_addr,output wire [7:0] burst_len,
    input wire rsp_valid,output wire rsp_ready,input wire [127:0] rsp_data,
    input wire rsp_last,input wire [1:0] rsp_resp,
    output wire recover_req,input wire recover_ack,
    output wire release_valid,input wire release_ready,
    output wire sink_valid,input wire sink_ready,
    output wire [23:0] sink_bgr,output wire [11:0] sink_address,output wire sink_last,
    input wire sink_error,sink_done_valid,sink_done_ok,output wire sink_done_ready,
    output wire sink_cancel_req,input wire sink_cancel_ack,
    output wire done_valid,input wire done_ready,output reg [7:0] done_status
);
    localparam BOOT=0,IDLE=1,START=2,ACTIVE=3,CLEANUP=4,DONE=5;
    reg [2:0] state;
    reg failed,sink_quiet,sink_ack_armed;
    wire reader_ready,reader_abort,reader_done,reader_release;
    wire [3:0] reader_status,reader_abort_status;
    wire running=state==START || state==ACTIVE || state==CLEANUP;
    wire local_abort=failed || (running && (reader_abort || sink_error || cancel_valid));
    wire finish_valid=state==CLEANUP && !failed && !local_abort;
    wire finish_ready;
    wire cmd_valid,cmd_ready,pixel_valid,pixel_ready,line_last,cmd_last,cmd_done_valid,cmd_done_ready;
    wire [10:0] cmd_x,pixel_x;wire [9:0] cmd_y,pixel_y;
    wire [8:0] cmd_width;wire [6:0] cmd_height;
    wire [23:0] rgb0,rgb1;wire [1:0] keep;
    assign job_ready=state==IDLE && reader_ready && !rst;
    assign release_valid=reader_release && sink_quiet;
    assign sink_cancel_req=!rst && (state==BOOT || (running && failed));
    assign done_valid=state==DONE && !rst;
    frame_reader reader (
        .clk(clk),.rst(rst),.job_valid(job_valid && state==IDLE),.job_ready(reader_ready),
        .job_slot(job_slot),.job_frame_id(job_frame_id),.job_epoch(job_epoch),
        .job_generation(job_generation),.job_source_time_ms(job_source_time_ms),
        .hold_valid(hold_valid),.hold_ready(hold_ready),.hold_granted(hold_granted),.hold_identity(hold_identity),
        .held(held),.held_slot(held_slot),.identity(identity),
        .config_epoch(config_epoch),.config_generation(config_generation),
        .cmd_valid(cmd_valid),.cmd_ready(cmd_ready),.full_scan(1'b0),.cmd_x(cmd_x),.cmd_y(cmd_y),
        .cmd_width(cmd_width),.cmd_height(cmd_height),.pixel_valid(pixel_valid),.pixel_ready(pixel_ready),
        .rgb0(rgb0),.rgb1(rgb1),.keep(keep),.pixel_x(pixel_x),.pixel_y(pixel_y),.line_last(line_last),.cmd_last(cmd_last),
        .cmd_done_valid(cmd_done_valid),.cmd_done_ready(cmd_done_ready),
        .finish_valid(finish_valid),.finish_ready(finish_ready),.finish_status(4'd0),
        .cancel_valid(failed),.cancel_status(4'd4),.abort_valid(reader_abort),.abort_status(reader_abort_status),
        .burst_valid(burst_valid),.burst_ready(burst_ready),.burst_addr(burst_addr),.burst_len(burst_len),
        .rsp_valid(rsp_valid),.rsp_ready(rsp_ready),.rsp_data(rsp_data),.rsp_last(rsp_last),.rsp_resp(rsp_resp),
        .recover_req(recover_req),.recover_ack(recover_ack),
        .release_valid(reader_release),.release_ready(release_ready && sink_quiet),
        .job_done_valid(reader_done),.job_done_ready(state==CLEANUP && sink_quiet),.status(reader_status));
    wire geometry_ready,resize_ready;
    wire start_fire=state==START && held && geometry_ready && resize_ready && !local_abort && !rst;
    wire geometry_corner_ready,geometry_done,geometry_done_ready;
    wire [3:0] geometry_status;wire [4:0] geometry_threshold;
    wire color_valid,color_ready,color_last,gray_write;
    wire [23:0] color_rgb;wire [13:0] color_address,gray_address;wire [7:0] gray_data;
    assign corner_ready=geometry_corner_ready && state==ACTIVE;
    perspective_quad #(.COLOR_OUTPUT(1)) geometry (
        .clk(clk),.rst(rst),.abort(local_abort),.start_valid(start_fire),.start_ready(geometry_ready),
        .corner_valid(corner_valid && state==ACTIVE),.corner_ready(geometry_corner_ready),.corner_data(corner_data),
        .cmd_valid(cmd_valid),.cmd_ready(cmd_ready),.cmd_x(cmd_x),.cmd_y(cmd_y),.cmd_width(cmd_width),.cmd_height(cmd_height),
        .pixel_valid(pixel_valid),.pixel_ready(pixel_ready),.rgb0(rgb0),.rgb1(rgb1),.keep(keep),
        .pixel_x(pixel_x),.pixel_y(pixel_y),.line_last(line_last),.cmd_last(cmd_last),
        .cmd_done_valid(cmd_done_valid),.cmd_done_ready(cmd_done_ready),
        .gray_write(gray_write),.gray_address(gray_address),.gray_data(gray_data),
        .color_valid(color_valid),.color_ready(color_ready),.color_rgb(color_rgb),.color_address(color_address),.color_last(color_last),
        .result_valid(geometry_done),.result_ready(geometry_done_ready),.result_threshold(geometry_threshold),.result_status(geometry_status));
    wire resize_done;wire [2:0] resize_status;wire [133:0] resize_identity;
    ocr_resize_q8 resize (
        .clk(clk),.rst(rst),.abort(local_abort),.start_valid(start_fire),.start_ready(resize_ready),.start_identity(identity),
        .in_valid(color_valid),.in_ready(color_ready),.in_rgb(color_rgb),.in_address(color_address),.in_last(color_last),
        .source_done_valid(geometry_done && geometry_status==0),.source_done_ok(1'b1),.source_done_ready(geometry_done_ready),
        .out_valid(sink_valid),.out_ready(sink_ready),.out_bgr(sink_bgr),.out_address(sink_address),.out_last(sink_last),.identity(resize_identity),
        .sink_done_valid(sink_done_valid),.sink_done_ok(sink_done_ok),.sink_done_ready(sink_done_ready),
        .done_valid(resize_done),.done_ready(state==ACTIVE),.done_status(resize_status));

    always @(posedge clk) begin
        if(rst) begin
            state<=BOOT;failed<=0;sink_quiet<=0;sink_ack_armed<=0;done_status<=0;
        end else begin
            if(!sink_cancel_req) sink_ack_armed<=0;
            else if(!sink_cancel_ack) sink_ack_armed<=1;
            else if(sink_ack_armed) sink_quiet<=1;
            if(sink_done_valid && sink_done_ready && sink_done_ok) sink_quiet<=1;
            case(state)
                BOOT: if(sink_quiet) state<=IDLE;
                IDLE: if(job_valid && job_ready) begin
                    failed<=0;sink_quiet<=0;done_status<=0;state<=START;
                end
                START: if(start_fire) state<=ACTIVE;
                ACTIVE: if(resize_done && resize_status==0) state<=CLEANUP;
                CLEANUP: if(reader_done && sink_quiet) begin
                    if(!failed && reader_status!=0) done_status<={4'h1,reader_status};
                    state<=DONE;
                end
                DONE: if(done_ready) begin failed<=0;state<=IDLE;end
                default: state<=BOOT;
            endcase
            // Latch geometry failure before aborting it: result_valid is itself abort-gated.
            if(running && !failed && (cancel_valid || sink_error || reader_abort ||
                (geometry_done && geometry_status!=0) || (resize_done && resize_status!=0))) begin
                failed<=1;sink_quiet<=0;state<=CLEANUP;
                if(cancel_valid) done_status<=8'h50;
                else if(sink_error) done_status<=8'h40;
                else if(reader_abort) done_status<={4'h1,reader_abort_status};
                else if(geometry_done && geometry_status!=0) done_status<={4'h2,geometry_status};
                else done_status<={5'b00110,resize_status};
            end
        end
    end
endmodule
