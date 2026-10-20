`timescale 1ns/1ps
module tb_perspective_matrix;
    reg clk=0;always #5 clk=~clk;
    reg rst=1,abort=0,start_valid=0,corner_valid=0,coeff_ready=0,done_ready=0;
    reg signed [31:0] corner_data=0;
    wire start_ready,corner_ready,coeff_valid,coeff_last,done_valid;
    wire signed [47:0] coeff_data;wire [1:0] done_status;
    perspective_matrix dut(.*);
    reg [31:0] corners[0:8191];reg [47:0] expected[0:9215];reg [1:0] statuses[0:1023];
    integer count,id,i,j,cycles,max_cycles=0,completed=0,checked=0;
    reg [48:0] held;
    task start_job(input integer number);
        begin
            @(negedge clk);if(!start_ready)$fatal(1,"start not ready");start_valid=1;
            @(negedge clk);start_valid=0;
            for(i=0;i<8;i=i+1)begin
                if(i%2==0)repeat(2)@(negedge clk);
                if(!corner_ready)$fatal(1,"corner not ready");
                corner_valid=1;corner_data=corners[number*8+i];@(negedge clk);corner_valid=0;
            end
        end
    endtask
    task run_job(input integer number);
        begin
            start_job(number);cycles=0;j=0;start_valid=1;corner_valid=1;corner_data=32'h7fffffff;
            while(!done_valid)begin
                if(start_ready || corner_ready)$fatal(1,"busy input accepted");
                if(coeff_valid)begin
                    if(statuses[number]!=0 || j>=9 || coeff_data!==expected[number*9+j] || coeff_last!==(j==8))
                        $fatal(1,"matrix %0d coeff %0d got %h expected %h",number,j,coeff_data,expected[number*9+j]);
                    held={coeff_last,coeff_data};
                    repeat(3)begin @(negedge clk);if(!coeff_valid || {coeff_last,coeff_data}!==held)$fatal(1,"coefficient changed");end
                    coeff_ready=1;@(negedge clk);coeff_ready=0;j=j+1;checked=checked+1;
                end else begin @(negedge clk);cycles=cycles+1;if(cycles>10000)$fatal(1,"solver timeout");end
            end
            start_valid=0;corner_valid=0;
            if(done_status!==statuses[number] || (done_status==0 && j!=9))$fatal(1,"status mismatch %0d got%0d expected%0d",number,done_status,statuses[number]);
            repeat(5)begin @(negedge clk);if(!done_valid || done_status!==statuses[number])$fatal(1,"done changed");end
            done_ready=1;@(negedge clk);done_ready=0;completed=completed+1;
            if(cycles>max_cycles)max_cycles=cycles;
        end
    endtask
    task cancel;
        begin
            abort=1;start_valid=0;corner_valid=0;coeff_ready=0;done_ready=0;
            #1;if(start_ready || corner_ready || coeff_valid || done_valid)$fatal(1,"abort handshake");
            @(negedge clk);abort=0;#1;if(!start_ready)$fatal(1,"abort stuck");
        end
    endtask
    initial begin
        if(!$value$plusargs("count=%d",count))$fatal(1,"missing count");
        $readmemh("corners.mem",corners,0,count*8-1);$readmemh("coefficients.mem",expected,0,count*9-1);$readmemh("statuses.mem",statuses,0,count-1);
        repeat(3)@(negedge clk);rst=0;
        for(id=0;id<count;id=id+1)run_job(id);
        start_valid=1;@(negedge clk);start_valid=0;corner_valid=1;corner_data=0;repeat(2)@(negedge clk);cancel();run_job(0);
        start_job(0);repeat(30)@(negedge clk);cancel();run_job(0);
        start_job(0);while(!coeff_valid)@(negedge clk);cancel();run_job(0);
        start_job(0);repeat(40)@(negedge clk);rst=1;repeat(2)@(negedge clk);rst=0;run_job(0);
        $display("PASS perspective matrix: %0d jobs, %0d exact coefficients, max %0d compute clocks; stalls/invalid/abort/reset",completed,checked,max_cycles);
        $finish;
    end
    initial begin #100000000;$fatal(1,"global timeout");end
endmodule
