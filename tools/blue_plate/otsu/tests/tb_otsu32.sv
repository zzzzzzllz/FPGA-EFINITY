`timescale 1ns/1ps
module tb_otsu32;
    reg clk=0;always #5 clk=~clk;
    reg rst=1,start_valid=0,hist_valid=0,result_ready=0;
    reg [14:0] hist_count=0;
    wire start_ready,hist_ready,result_valid;
    wire [4:0] result_threshold;
    wire [1:0] result_status;
    otsu32 dut(.*);
    reg [14:0] histograms [0:16383];
    reg [6:0] expected [0:511];
    integer count,case_id,i,cycles,maximum_cycles=0,completed=0;
    reg [6:0] held;

    task begin_job;
        begin
            @(negedge clk);
            while (!start_ready) @(negedge clk);
            start_valid=1;
            @(negedge clk);start_valid=0;
        end
    endtask
    task send_histogram;
        input integer vector_id;
        begin
            begin_job();
            for (i=0;i<32;i=i+1) begin
                if ((i+vector_id)%3==0) begin
                    hist_valid=0;
                    @(negedge clk);
                end
                if (!hist_ready) $fatal(1,"histogram not ready at bin %0d",i);
                hist_valid=1;hist_count=histograms[vector_id*32+i];
                @(negedge clk);
            end
            hist_valid=0;
        end
    endtask
    task finish_job;
        input integer vector_id;
        begin
            cycles=0;
            // Busy input noise must not be accepted as another task or histogram.
            start_valid=1;hist_valid=1;hist_count=15'h7fff;
            while (!result_valid) begin
                if (start_ready || hist_ready) $fatal(1,"busy input accepted");
                @(negedge clk);cycles=cycles+1;
                if (cycles>10000) $fatal(1,"threshold timeout");
            end
            start_valid=0;hist_valid=0;
            if ({result_status,result_threshold}!==expected[vector_id])
                $fatal(1,"case %0d got status=%0d threshold=%0d expected=%h",vector_id,result_status,result_threshold,expected[vector_id]);
            held={result_status,result_threshold};
            repeat (7) begin
                @(negedge clk);
                if (!result_valid || {result_status,result_threshold}!==held || start_ready || hist_ready)
                    $fatal(1,"result changed under backpressure");
            end
            result_ready=1;
            @(negedge clk);result_ready=0;
            if (!start_ready || result_valid) $fatal(1,"result handshake did not return idle");
            if (cycles>maximum_cycles) maximum_cycles=cycles;
            completed=completed+1;
        end
    endtask
    task reset_core;
        begin
            @(negedge clk);rst=1;start_valid=0;hist_valid=0;result_ready=0;
            #1;
            if (start_ready || hist_ready || result_valid) $fatal(1,"valid/ready visible in reset");
            repeat (2) @(negedge clk);
            rst=0;
            @(negedge clk);
            if (!start_ready || result_valid) $fatal(1,"reset failed to clear job");
        end
    endtask

    initial begin
        if (!$value$plusargs("count=%d",count)) $fatal(1,"missing vector count");
        $readmemh("histograms.mem",histograms,0,count*32-1);
        $readmemh("expected.mem",expected,0,count-1);
        reset_core();
        for (case_id=0;case_id<count;case_id=case_id+1) begin
            send_histogram(case_id);finish_job(case_id);
        end
        begin_job();hist_valid=1;hist_count=23;
        repeat (4) @(negedge clk);
        reset_core();send_histogram(count-1);finish_job(count-1);
        send_histogram(count-1);
        repeat (12) @(negedge clk);
        reset_core();send_histogram(count-1);finish_job(count-1);
        send_histogram(count-1);
        while (!result_valid) @(negedge clk);
        reset_core();send_histogram(count-1);finish_job(count-1);
        $display("PASS Otsu: %0d jobs, max %0d cycles after histogram; input stalls, busy noise, output stalls, load/compute/hold resets",completed,maximum_cycles);
        $finish;
    end
    initial begin
        #100000000;
        $fatal(1,"global timeout");
    end
endmodule
