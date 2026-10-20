`timescale 1ns/1ps
module tb_weight_mac8;
    reg clk=0;
    always #5 clk=~clk;
    reg rst,ce,wr_en,issue,load;
    reg [10:0] wr_addr,rd_addr;
    reg [63:0] wr_data;
    reg [135:0] activation;
    reg [7:0] lane_mask;
    reg [255:0] seed;
    wire [63:0] weight_data;
    wire read_valid,command_error;
    wire [255:0] psum;
    wire [7:0] updated,overflow;
    reg [63:0] exp_weight;
    reg exp_valid,exp_error;
    reg [255:0] exp_psum;
    reg [7:0] exp_updated,exp_overflow;
    reg [4095:0] path;
    integer fd,n,cycles=0;
    weight_mac8 dut(.*);
    initial begin
        if (!$value$plusargs("VECTORS=%s",path)) $fatal(1,"Missing VECTORS");
        fd=$fopen(path,"r");
        if (!fd) $fatal(1,"Cannot open vectors");
        while (!$feof(fd)) begin
            @(negedge clk);
            n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",
                rst,ce,wr_en,wr_addr,wr_data,issue,rd_addr,activation,lane_mask,load,seed,
                exp_weight,exp_valid,exp_error,exp_psum,exp_updated,exp_overflow);
            if (n!=17) $fatal(1,"Malformed vector %0d",cycles);
            @(posedge clk); #1;
            if (weight_data!==exp_weight || read_valid!==exp_valid || command_error!==exp_error ||
                psum!==exp_psum || updated!==exp_updated || overflow!==exp_overflow)
                $fatal(1,"cycle=%0d weight=%h/%h valid=%b/%b error=%b/%b psum=%h/%h update=%h/%h overflow=%h/%h",
                    cycles,weight_data,exp_weight,read_valid,exp_valid,command_error,exp_error,
                    psum,exp_psum,updated,exp_updated,overflow,exp_overflow);
            cycles=cycles+1;
            if (cycles%2048==0) begin $display("PROGRESS weight_mac8 cycles=%0d",cycles); $fflush(); end
        end
        $display("PASS weight_mac8 cycles=%0d lane_states=%0d",cycles,cycles*8);
        $fclose(fd);$finish;
    end
    initial begin #10000000; $fatal(1,"Timeout"); end
endmodule
