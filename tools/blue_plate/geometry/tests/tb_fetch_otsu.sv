`timescale 1ns/1ps
module tb_fetch_otsu;
    reg clk=0;always #5 clk=~clk;
    reg rst=1;
    reg job_valid=0;wire job_ready,hold_valid,held;wire [5:0] held_slot;
    wire [133:0] identity,hold_identity;
    wire cmd_valid,cmd_ready;wire [10:0] cmd_x;wire [9:0] cmd_y;
    wire [8:0] cmd_width;wire [6:0] cmd_height;
    wire pixel_valid,pixel_ready;wire [23:0] rgb0,rgb1;wire [1:0] keep;
    wire [10:0] pixel_x;wire [9:0] pixel_y;wire line_last,cmd_last;
    wire cmd_done_valid,cmd_done_ready;
    reg finish_valid=0;wire finish_ready,abort_valid;wire [3:0] abort_status;
    wire burst_valid,burst_ready;wire [31:0] burst_addr;wire [7:0] burst_len;
    wire rsp_valid,rsp_ready,rsp_last;wire [127:0] rsp_data;
    wire recover_req;reg recover_ack=0;wire release_valid,job_done_valid;wire [3:0] status;
    frame_reader reader(.clk(clk),.rst(rst),.job_valid(job_valid),.job_ready(job_ready),
        .job_slot(6'd0),.job_frame_id(32'd36),.job_epoch(32'd1),.job_generation(32'd2),.job_source_time_ms(32'd1234),
        .hold_valid(hold_valid),.hold_ready(1'b1),.hold_granted(1'b1),.hold_identity(hold_identity),
        .held(held),.held_slot(held_slot),.identity(identity),.config_epoch(32'd1),.config_generation(32'd2),
        .cmd_valid(cmd_valid),.cmd_ready(cmd_ready),.full_scan(1'b0),.cmd_x(cmd_x),.cmd_y(cmd_y),.cmd_width(cmd_width),.cmd_height(cmd_height),
        .pixel_valid(pixel_valid),.pixel_ready(pixel_ready),.rgb0(rgb0),.rgb1(rgb1),.keep(keep),.pixel_x(pixel_x),.pixel_y(pixel_y),.line_last(line_last),.cmd_last(cmd_last),
        .cmd_done_valid(cmd_done_valid),.cmd_done_ready(cmd_done_ready),.finish_valid(finish_valid),.finish_ready(finish_ready),.finish_status(4'd0),
        .cancel_valid(1'b0),.cancel_status(4'd4),.abort_valid(abort_valid),.abort_status(abort_status),
        .burst_valid(burst_valid),.burst_ready(burst_ready),.burst_addr(burst_addr),.burst_len(burst_len),
        .rsp_valid(rsp_valid),.rsp_ready(rsp_ready),.rsp_data(rsp_data),.rsp_last(rsp_last),.rsp_resp(2'b00),
        .recover_req(recover_req),.recover_ack(recover_ack),.release_valid(release_valid),.release_ready(1'b1),
        .job_done_valid(job_done_valid),.job_done_ready(1'b1),.status(status));
    wire sample_ready;
`ifdef GENERATED_COORDS
    wire sample_valid;wire signed [31:0] source_x32,source_y32;
    wire [7:0] dest_x;wire [5:0] dest_y;wire sample_last;
    reg coords_start=0,coeff_valid=0;wire coords_ready,coeff_ready,coords_done;wire [1:0] coords_status;
    reg signed [47:0] coeff_data=0;reg [47:0] coefficients[0:8];
`ifdef QUAD_SOLVER
    reg corner_valid=0;wire corner_ready;reg signed [31:0] corner_data=0;reg [31:0] corners[0:7];
`endif
`ifndef INTEGRATED_ROI
    perspective_coords coords(.clk(clk),.rst(rst),.abort(abort_valid),.start_valid(coords_start),.start_ready(coords_ready),
        .coeff_valid(coeff_valid),.coeff_ready(coeff_ready),.coeff_data(coeff_data),.sample_valid(sample_valid),.sample_ready(sample_ready),
        .source_x32(source_x32),.source_y32(source_y32),.dest_x(dest_x),.dest_y(dest_y),.sample_last(sample_last),
        .done_valid(coords_done),.done_ready(1'b1),.done_status(coords_status));
`endif
    localparam PARTS=1;
`else
    reg sample_valid=0;reg signed [31:0] source_x32=0,source_y32=0;
    reg [7:0] dest_x=0;reg [5:0] dest_y=0;reg sample_last=0;
    localparam PARTS=2;
`endif
    wire out_valid,out_ready,out_last,fault;wire [23:0] out_rgb;wire [7:0] out_x;wire [5:0] out_y;
`ifndef INTEGRATED_ROI
    perspective_fetch fetch(.clk(clk),.rst(rst),.abort(abort_valid),.*);
`endif
    reg start_valid=0;wire start_ready;reg [15:0] pixel_count=0;
    wire result_valid;reg result_ready=0;wire [4:0] result_threshold;
`ifdef QUAD_SOLVER
    wire [3:0] result_status;
`else
    wire [2:0] result_status;
`endif
`ifdef INTEGRATED_ROI
    wire gray_write;wire [13:0] gray_address;wire [7:0] gray_data;
`ifdef QUAD_SOLVER
    perspective_quad quad(.color_ready(1'b1),.color_valid(),.color_rgb(),.color_address(),.color_last(),.clk(clk),.rst(rst),.abort(abort_valid),.*);
    assign coords_done=quad.roi.coords_done;assign coords_status=quad.roi.coords_status;assign fault=quad.roi.fault;
`else
    perspective_roi roi(.color_ready(1'b1),.color_valid(),.color_rgb(),.color_address(),.color_last(),.clk(clk),.rst(rst),.abort(abort_valid),.*);
    assign coords_done=roi.coords_done;assign coords_status=roi.coords_status;assign fault=roi.fault;
`endif
`else
    roi_otsu32 otsu(.clk(clk),.rst(rst),.abort(abort_valid),.start_valid(start_valid),.start_ready(start_ready),.pixel_count(pixel_count),
        .pixel_valid(out_valid),.pixel_ready(out_ready),.rgb0(out_rgb),.rgb1(24'd0),.keep(2'b01),.pixel_last(out_last),
        .result_valid(result_valid),.result_ready(result_ready),.result_threshold(result_threshold),.result_status(result_status));
`endif
    reg [127:0] memory [0:172799];reg [63:0] coordinates [0:16383];reg [23:0] expected [0:16383];
    reg [15:0] lengths [0:1];reg [7:0] thresholds [0:1];
    integer tick=0,base_word=0,bus_index=0,bus_length=0,bursts=0,commands=0,holds=0,releases=0;
    integer part=0,offset=0,p=0,seen=0,cycles=0,start_tick=0,total=0;
    reg bus_active=0;
    assign burst_ready=!bus_active && !recover_req && tick%5!=0;
    assign rsp_valid=bus_active && tick%7!=0;
    assign rsp_data=memory[base_word+bus_index];
    assign rsp_last=bus_index==bus_length;
    always @(posedge clk) begin
        tick<=tick+1;
        if (!rst) begin
            if (hold_valid) holds=holds+1;
            if (release_valid) begin
                if (bus_active || !held) $fatal(1,"unsafe release");releases=releases+1;
            end
            if (held && identity!=={6'd0,32'd36,32'd1,32'd2,32'd1234}) $fatal(1,"identity changed");
            if (abort_valid || fault) $fatal(1,"unexpected stream fault");
            if (burst_valid && burst_ready) begin
                if (!held || burst_addr[3:0]!=0 || burst_len>31 || burst_addr+(burst_len+1)*16>2764800)
                    $fatal(1,"unsafe burst");
                base_word=burst_addr/16;bus_length=burst_len;bus_index<=0;bus_active<=1;bursts=bursts+1;
            end
            if (rsp_valid) begin
                if (!rsp_ready) $fatal(1,"response backpressure");
                if (rsp_last) bus_active<=0;else bus_index<=bus_index+1;
            end
            if (cmd_done_valid && cmd_done_ready) commands=commands+1;
`ifdef INTEGRATED_ROI
            if (gray_write) begin
                if (gray_address!==seen || gray_data!==((77*expected[offset+seen][23:16]+150*expected[offset+seen][15:8]+29*expected[offset+seen][7:0])>>8))
                    $fatal(1,"gray cache write mismatch %0d",seen);
                seen=seen+1;
            end
`else
            if (out_valid && out_ready) begin
                if (out_rgb!==expected[offset+seen] || out_x!==seen%224 || out_y!==seen/224 || out_last!==(seen==lengths[part]-1))
                    $fatal(1,"sample %0d/%0d got %h expected %h",part,seen,out_rgb,expected[offset+seen]);
                seen=seen+1;
            end
`endif
        end
    end
    initial begin
        $readmemh("frame.mem",memory);
`ifdef GENERATED_COORDS
        $readmemh("coefficients.mem",coefficients);
`endif
`ifdef QUAD_SOLVER
        $readmemh("corners.mem",corners);
`endif
        $readmemh("lengths.mem",lengths);$readmemh("thresholds.mem",thresholds);
        total=lengths[0]+lengths[1];
        $readmemh("coordinates.mem",coordinates,0,total-1);$readmemh("pixels.mem",expected,0,total-1);
        repeat (3) @(negedge clk);rst=0;
        repeat (3) @(negedge clk);recover_ack=1;@(negedge clk);recover_ack=0;
        while (!job_ready) @(negedge clk);
        job_valid=1;@(negedge clk);job_valid=0;
        for (part=0;part<PARTS;part=part+1) begin
            seen=0;pixel_count=lengths[part];start_valid=1;start_tick=tick;
            if (!start_ready) $fatal(1,"Otsu not idle");
            @(negedge clk);start_valid=0;
`ifdef GENERATED_COORDS
            coords_start=1;@(negedge clk);coords_start=0;
`ifdef QUAD_SOLVER
            for (p=0;p<8;p=p+1) begin
                corner_valid=1;corner_data=corners[p];
                if (!corner_ready) $fatal(1,"corner handshake failed");
                @(negedge clk);
            end
            corner_valid=0;
`else
            for (p=0;p<9;p=p+1) begin
                coeff_valid=1;coeff_data=coefficients[p];
                if (!coeff_ready) $fatal(1,"coefficient handshake failed");
                @(negedge clk);
            end
            coeff_valid=0;
`endif
            while (seen!=lengths[part]) begin
                @(negedge clk);
                if (coords_done && coords_status!=0) $fatal(1,"coordinate failure");
            end
`else
            for (p=0;p<lengths[part];p=p+1) begin
                {source_x32,source_y32}=coordinates[offset+p];dest_x=p%224;dest_y=p/224;
                sample_last=p==lengths[part]-1;sample_valid=1;cycles=0;
                while (!sample_ready) begin
                    @(negedge clk);cycles=cycles+1;
                    if (cycles>500) $fatal(1,"fetch timeout");
                end
                @(negedge clk);sample_valid=0;
            end
`endif
            cycles=0;
            while (!result_valid) begin @(negedge clk);cycles=cycles+1;if(cycles>10000)$fatal(1,"Otsu timeout");end
            if (seen!=lengths[part] || {result_status,result_threshold}!==thresholds[part]) $fatal(1,"threshold mismatch");
            $display("METRIC part %0d pixels %0d cycles %0d",part,seen,tick-start_tick);
            repeat (9) @(negedge clk);result_ready=1;@(negedge clk);result_ready=0;
            offset=offset+lengths[part];
        end
        finish_valid=1;while (!finish_ready) @(negedge clk);
        @(negedge clk);finish_valid=0;
        while (!job_done_valid) @(negedge clk);
        if (status!=0 || holds!=1 || releases!=1 || held) $fatal(1,"frame lifecycle mismatch");
        $display("PASS held-frame RGB fetch/interpolation/Otsu: %0d pixels, %0d commands, %0d bursts, one hold/release",offset,commands,bursts);
        $finish;
    end
    initial begin #100000000;$fatal(1,"global timeout");end
endmodule
