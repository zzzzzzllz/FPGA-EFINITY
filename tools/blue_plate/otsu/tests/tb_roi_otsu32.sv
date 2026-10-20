`timescale 1ns/1ps
module tb_roi_otsu32;
    reg clk=0;always #5 clk=~clk;
    reg rst=1,abort=0,start_valid=0,pixel_valid=0,pixel_last=0,result_ready=0;
    reg [15:0] pixel_count=0;
    reg [23:0] rgb0=0,rgb1=0;
    reg [1:0] keep=0;
    wire start_ready,pixel_ready,result_valid;
    wire [4:0] result_threshold;
    wire [2:0] result_status;
    roi_otsu32 dut(.*);
    reg [50:0] beats [0:999999];
    reg [31:0] starts [0:255],lengths [0:255],sizes [0:255];
    reg [7:0] expected [0:255];
    reg [14:0] histograms [0:8191];
    integer count,beat_total,id,j,k,cycles,completed=0,bin_checked=0;
    integer hist_index=0,current_id=0,max_cycles=0,job_cycles=0;
    reg check_hist=0;
    reg [7:0] held;
    always @(posedge clk) begin
        if (!rst && !abort && !start_ready) job_cycles=job_cycles+1;
`ifndef MAPPED_NETLIST
        if (!rst && !abort && check_hist && dut.core.hist_valid && dut.core.hist_ready) begin
            if (dut.core.hist_count !== histograms[current_id*32+hist_index])
                $fatal(1,"hist case %0d bin %0d got %0d expected %0d",current_id,hist_index,dut.core.hist_count,histograms[current_id*32+hist_index]);
            hist_index=hist_index+1;bin_checked=bin_checked+1;
        end
`endif
    end

    task begin_job(input integer n);
        begin
            @(negedge clk);
            while (!start_ready) @(negedge clk);
            pixel_count=n;start_valid=1;hist_index=0;job_cycles=0;
            @(negedge clk);start_valid=0;
        end
    endtask
    task send_beat(input [50:0] value);
        begin
            {pixel_last,keep,rgb0,rgb1}=value;pixel_valid=1;cycles=0;
            while (!pixel_ready) begin
                @(negedge clk);cycles=cycles+1;
                if (cycles>100) $fatal(1,"pixel ready timeout");
            end
            @(negedge clk);pixel_valid=0;
        end
    endtask
    task finish_job(input [7:0] wanted);
        begin
            cycles=0;start_valid=1;pixel_count=65535;
            while (!result_valid) begin
                @(negedge clk);cycles=cycles+1;
                if (cycles>10000) $fatal(1,"result timeout");
            end
            start_valid=0;
            if ({result_status,result_threshold}!==wanted)
                $fatal(1,"case %0d result %h expected %h",current_id,{result_status,result_threshold},wanted);
`ifndef MAPPED_NETLIST
            if (check_hist && sizes[current_id]>0 && sizes[current_id]<=30720 && hist_index!=32)
                $fatal(1,"missing histogram bins");
`endif
            held={result_status,result_threshold};
            repeat (9) begin
                @(negedge clk);
                if (!result_valid || {result_status,result_threshold}!==held || pixel_ready || start_ready)
                    $fatal(1,"unstable held result");
            end
            result_ready=1;@(negedge clk);result_ready=0;
            if (!start_ready || result_valid) $fatal(1,"result not consumed");
            if (job_cycles>max_cycles) max_cycles=job_cycles;
            completed=completed+1;
        end
    endtask
    task run_case(input integer number);
        begin
            current_id=number;check_hist=1;begin_job(sizes[number]);
            for (j=0;j<lengths[number];j=j+1) begin
                if (j%7==0) repeat (3) @(negedge clk);
                send_beat(beats[starts[number]+j]);
            end
            finish_job(expected[number]);check_hist=0;
        end
    endtask
    task abort_task;
        begin
            abort=1;pixel_valid=0;start_valid=0;result_ready=0;check_hist=0;
            #1;if (start_ready || pixel_ready || result_valid) $fatal(1,"abort handshakes");
            @(negedge clk);abort=0;#1;
            if (!start_ready || result_valid) $fatal(1,"abort failed");
        end
    endtask
    initial begin
        if (!$value$plusargs("count=%d",count) || !$value$plusargs("beats=%d",beat_total)) $fatal(1,"missing count");
        $readmemh("beats.mem",beats,0,beat_total-1);
        $readmemh("starts.mem",starts,0,count-1);
        $readmemh("lengths.mem",lengths,0,count-1);
        $readmemh("sizes.mem",sizes,0,count-1);
        $readmemh("expected.mem",expected,0,count-1);
        $readmemh("histograms.mem",histograms,0,count*32-1);
        repeat (3) @(negedge clk);rst=0;
        for (id=0;id<count;id=id+1) run_case(id);
        // Invalid masks, early/missing last and a pair beyond the declared size.
        for (k=0;k<5;k=k+1) begin
            begin_job(k==4 ? 1 : 2);
            case(k)
                0:send_beat({1'b0,2'b00,48'd0});
                1:send_beat({1'b0,2'b10,48'd0});
                2:send_beat({1'b1,2'b01,48'd0});
                3:send_beat({1'b0,2'b11,48'd0});
                4:send_beat({1'b1,2'b11,48'd0});
            endcase
            finish_job(8'h80);
        end
        // Abort during clear, first/second update, core arithmetic, held output.
        begin_job(100);repeat (4) @(negedge clk);abort_task();run_case(count-1);
        for (k=0;k<4;k=k+1) begin
            begin_job(2);send_beat({1'b1,2'b11,24'h123456,24'hffffff});
            repeat (k) @(negedge clk);abort_task();run_case(count-1);
        end
        begin_job(2);send_beat({1'b1,2'b11,24'h000000,24'hffffff});
        repeat (120) @(negedge clk);abort_task();run_case(count-1);
        begin_job(1);send_beat({1'b1,2'b01,24'hffffff,24'h000000});
        while (!result_valid) @(negedge clk);
        abort_task();run_case(count-1);
        // Coordinated reset after some accumulated pixels, then a clean task.
        begin_job(100);send_beat({1'b0,2'b11,48'hffffffffffff});
        rst=1;repeat (2) @(negedge clk);rst=0;run_case(count-1);
        $display("PASS ROI Otsu: %0d completed jobs, %0d histogram bins checked, max %0d task cycles; stalls/malformed streams/abort/reset",completed,bin_checked,max_cycles);
        $finish;
    end
    initial begin #200000000;$fatal(1,"global timeout");end
endmodule
