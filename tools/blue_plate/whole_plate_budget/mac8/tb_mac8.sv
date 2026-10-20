`timescale 1ns/1ps
module tb_mac8;
    reg clk=0;
    always #5 clk=~clk;
    reg rst,ce,valid,load;
    reg [7:0] lane_mask;
    reg [135:0] activation;
    reg [63:0] weight;
    reg [255:0] seed;
    wire [255:0] psum;
    wire [7:0] updated,overflow;
    reg [255:0] expected_sum;
    reg [7:0] expected_updated,expected_overflow;
    reg [4095:0] vector_file;
    integer fd,status,cycles=0;
    mac8 dut(.*);
    initial begin
        if (!$value$plusargs("VECTORS=%s",vector_file)) $fatal(1,"Missing VECTORS");
        fd=$fopen(vector_file,"r");
        if (!fd) $fatal(1,"Cannot open vectors");
        while (!$feof(fd)) begin
            @(negedge clk);
            status=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h\n",
                rst,ce,valid,load,lane_mask,activation,weight,seed,
                expected_sum,expected_updated,expected_overflow);
            if (status!=11) $fatal(1,"Malformed vector at cycle %0d: %0d",cycles,status);
            @(posedge clk); #1;
            if (psum!==expected_sum || updated!==expected_updated || overflow!==expected_overflow)
                $fatal(1,"cycle %0d psum=%h expected=%h updated=%h/%h overflow=%h/%h",
                    cycles,psum,expected_sum,updated,expected_updated,overflow,expected_overflow);
            cycles=cycles+1;
            if (cycles%1024==0) begin
                $display("PROGRESS mac8 cycles=%0d",cycles);
                $fflush();
            end
        end
        $fclose(fd);
        $display("PASS mac8 cycles=%0d lane_states=%0d",cycles,cycles*8);
        $finish;
    end
    initial begin #10000000; $fatal(1,"Timeout"); end
endmodule
