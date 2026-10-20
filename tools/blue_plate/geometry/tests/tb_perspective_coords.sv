`timescale 1ns/1ps
module tb_perspective_coords;
    reg clk=0;always #5 clk=~clk;
    reg rst=1,abort=0,start_valid=0,coeff_valid=0,sample_ready=0,done_ready=0;
    reg signed [47:0] coeff_data=0;
    wire start_ready,coeff_ready,sample_valid,sample_last,done_valid;
    wire signed [31:0] source_x32,source_y32;
    wire [7:0] dest_x;wire [5:0] dest_y;wire [1:0] done_status;
    perspective_coords dut(.*);
    reg [47:0] coefficients [0:143];
    reg [63:0] expected [0:229375];
    reg [1:0] statuses [0:15];
    integer count,id,i,p,cycles,checked=0,completed=0;
    reg [78:0] held;
    task start_job(input integer number);
        begin
            @(negedge clk);start_valid=1;
            if (!start_ready) $fatal(1,"not ready for start");
            @(negedge clk);start_valid=0;
            for (i=0;i<9;i=i+1) begin
                if (i%3==0) @(negedge clk);
                if (!coeff_ready) $fatal(1,"missing coefficient ready");
                coeff_valid=1;coeff_data=coefficients[number*9+i];
                @(negedge clk);coeff_valid=0;
            end
        end
    endtask
    task run_job(input integer number);
        begin
            start_job(number);p=0;cycles=0;
            start_valid=1;coeff_valid=1;coeff_data=48'h7fffffffffff;
            while (!done_valid) begin
                if (start_ready || coeff_ready) $fatal(1,"busy input accepted");
                if (sample_valid) begin
                    if (p>=14336 || {source_x32,source_y32}!==expected[number*14336+p])
                        $fatal(1,"vector %0d pixel %0d got %h expected %h",number,p,{source_x32,source_y32},expected[number*14336+p]);
                    if (dest_x!==p%224 || dest_y!==p/224 || sample_last!==(p==14335))
                        $fatal(1,"destination metadata mismatch");
                    held={sample_last,dest_x,dest_y,source_x32,source_y32};
                    if (p%97==0) repeat (3) begin
                        @(negedge clk);
                        if (!sample_valid || {sample_last,dest_x,dest_y,source_x32,source_y32}!==held)
                            $fatal(1,"sample changed under stall");
                    end
                    sample_ready=1;@(negedge clk);sample_ready=0;
                    p=p+1;checked=checked+1;cycles=0;
                end else begin
                    @(negedge clk);cycles=cycles+1;
                    if (cycles>200) $fatal(1,"sample timeout");
                end
            end
            start_valid=0;coeff_valid=0;
            if (done_status!==statuses[number] || (done_status==0 && p!=14336)) $fatal(1,"wrong completion");
            repeat (7) begin
                @(negedge clk);
                if (!done_valid || done_status!==statuses[number] || sample_valid || start_ready) $fatal(1,"unstable completion");
            end
            done_ready=1;@(negedge clk);done_ready=0;completed=completed+1;
        end
    endtask
    task cancel;
        begin
            abort=1;coeff_valid=0;start_valid=0;sample_ready=0;done_ready=0;
            #1;if (start_ready || coeff_ready || sample_valid || done_valid) $fatal(1,"abort handshake");
            @(negedge clk);abort=0;#1;
            if (!start_ready) $fatal(1,"abort did not clear");
        end
    endtask
    initial begin
        if (!$value$plusargs("count=%d",count)) $fatal(1,"count missing");
        $readmemh("coefficients.mem",coefficients,0,count*9-1);
        $readmemh("expected.mem",expected,0,count*14336-1);
        $readmemh("statuses.mem",statuses,0,count-1);
        repeat (3) @(negedge clk);rst=0;
        for (id=0;id<count;id=id+1) run_job(id);
        @(negedge clk);start_valid=1;@(negedge clk);start_valid=0;
        coeff_valid=1;coeff_data=0;@(negedge clk);cancel();run_job(0);
        start_job(0);repeat (11) @(negedge clk);cancel();run_job(0);
        start_job(0);while (!sample_valid) @(negedge clk);cancel();run_job(0);
        start_job(0);repeat (25) @(negedge clk);rst=1;repeat (2) @(negedge clk);rst=0;run_job(0);
        $display("PASS perspective coordinates: %0d jobs, %0d exact source pairs, load/output stalls, busy noise, abort/reset",completed,checked);
        $finish;
    end
    initial begin #500000000;$fatal(1,"global timeout");end
endmodule
