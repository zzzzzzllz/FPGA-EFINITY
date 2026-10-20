`timescale 1ns/1ps
module tb_psum;
    reg clk=0;
    always #5 clk=~clk;
    reg rst,ce,wr_en,issue,load,save,restore;
    reg [10:0] wr_addr,rd_addr;
    reg [63:0] wr_data;
    reg [135:0] activation;
    reg [7:0] lane_mask;
    reg [255:0] seed;
    reg [5:0] slot;
    wire busy,done,command_error,read_valid;
    wire [255:0] psum;
    wire [7:0] updated,overflow;
    reg [255:0] exp_sum;
    reg [7:0] exp_updated,exp_overflow;
    reg exp_busy,exp_done,exp_error,exp_pending;
    reg [4095:0] path;
    integer fd,n,cycles=0;
    psum_weight_mac8 dut(.*);
    initial begin
        if (!$value$plusargs("VECTORS=%s",path)) $fatal(1,"Missing vectors");
        fd=$fopen(path,"r");if(!fd) $fatal(1,"Cannot open vectors");
        while(!$feof(fd)) begin
            @(negedge clk);
            n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",
                rst,ce,wr_en,wr_addr,wr_data,issue,rd_addr,activation,lane_mask,load,seed,
                save,restore,slot,exp_sum,exp_updated,exp_overflow,exp_busy,exp_done,exp_error,exp_pending);
            if(n!=21) $fatal(1,"Malformed vector %0d",cycles);
            @(posedge clk);#1;
            if(psum!==exp_sum || updated!==exp_updated || overflow!==exp_overflow ||
               busy!==exp_busy || done!==exp_done || command_error!==exp_error || read_valid!==exp_pending)
                $fatal(1,"cycle=%0d sum=%h/%h update=%h/%h ov=%h/%h busy=%b/%b done=%b/%b err=%b/%b pending=%b/%b",
                    cycles,psum,exp_sum,updated,exp_updated,overflow,exp_overflow,busy,exp_busy,
                    done,exp_done,command_error,exp_error,read_valid,exp_pending);
            cycles=cycles+1;
            if(cycles%8192==0) begin $display("PROGRESS psum cycles=%0d",cycles);$fflush();end
        end
        $display("PASS psum cycles=%0d lane_states=%0d",cycles,cycles*8);$fclose(fd);$finish;
    end
    initial begin #10000000;$fatal(1,"Timeout");end
endmodule
