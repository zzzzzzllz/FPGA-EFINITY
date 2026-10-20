`timescale 1ns/1ps
module tb_requant;
    reg clk=0;always #5 clk=~clk;
    reg rst=0,ce=1,wr_en=0,issue=0,load=0,save=0,restore=0;
    reg [10:0] wr_addr=0,rd_addr=0;
    reg [63:0] wr_data=0;
    reg [135:0] activation=0;
    reg [7:0] lane_mask=255;
    reg [255:0] seed=0;
    reg [5:0] slot=63;
    wire busy,done,read_valid,command_error;
    wire [255:0] psum;
    wire [7:0] updated,overflow;
    reg q_const=0;reg signed [7:0] q_const_value=0;
    reg q_start=0,q_reuse=0,q_relu=0,q_ready=0;
    reg signed [31:0] q_acc=0;
    reg [30:0] q_multiplier=1;
    reg [5:0] q_shift=1;
    reg signed [7:0] q_zero=0;
    wire q_busy,q_valid;
    wire signed [7:0] q_result;
    q31_static_mac8 dut(.*);
    reg [4095:0] path;
    reg signed [7:0] expected;
    reg signed [63:0] expected_product;
    reg [255:0] held,saved;
    reg signed [7:0] held_result;
    integer fd,n,cases=0,constant_cases=0,steps,s,cycles=0,stalls=0,j;
    task tick;begin @(posedge clk);#1;cycles=cycles+1;@(negedge clk);end endtask
    task reset;begin rst=1;ce=0;tick();rst=0;ce=1;if(busy||q_valid||read_valid) $fatal(1,"reset");end endtask
    task bad;begin q_start=1;tick();q_start=0;if(!command_error||q_busy) $fatal(1,"invalid request");tick();end endtask
    initial begin
        reset();q_reuse=1;bad();q_reuse=0;q_multiplier=0;bad();q_multiplier=1;q_shift=0;bad();q_shift=63;bad();q_shift=1;
        // Save all original lanes before the shared MAC is overwritten.
        for(j=0;j<8;j=j+1) seed[j*32 +:32]=32'h81234567+j*12345;
        saved=seed;load=1;tick();load=0;save=1;tick();save=0;
        while(busy) tick();if(!done) $fatal(1,"save completion");tick();
        if(!$value$plusargs("VECTORS=%s",path)) $fatal(1,"vectors required");
        fd=$fopen(path,"r");if(!fd) $fatal(1,"cannot open vectors");
        while(!$feof(fd)) begin
            n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h\n",q_const,q_const_value,q_reuse,q_acc,q_multiplier,q_shift,q_relu,q_zero,expected,expected_product);
            if(n!=10) $fatal(1,"malformed record");
            s=q_shift;held=psum;q_start=1;tick();q_start=0;if(!q_busy||command_error) $fatal(1,"accept case=%0d",cases);
            steps=0;
            while(!q_valid) begin
                // Input changes must not affect an accepted request or its retained original.
                q_acc=32'hdeadbeef;q_multiplier=1;q_shift=1;q_relu=0;q_zero=127;
                if(steps%11==3) begin
                    held=psum;held_result=q_result;ce=0;tick();stalls=stalls+1;ce=1;
                    if(psum!==held || q_result!==held_result || q_valid) $fatal(1,"stall");
                end
                // Rejected commands must not cancel or alter the active arithmetic.
                if(steps==2) begin q_start=1;load=1;end
                tick();steps=steps+1;
                if(steps==3 && !command_error) $fatal(1,"busy rejection");
                q_start=0;load=0;
                if(steps==18 && dut.product!==expected_product) $fatal(1,"product case=%0d actual=%h expected=%h",cases,dut.product,expected_product);
                if(steps>90) $fatal(1,"timeout case=%0d",cases);
            end
            if(steps!=(q_const ? 0 : 25) || q_result!==expected || overflow!=0) $fatal(1,"result case=%0d got=%0d expected=%0d steps=%0d/%0d",cases,q_result,expected,steps,(q_const ? 0 : 25));
            if(q_const) begin constant_cases=constant_cases+1;if(psum!==held) $fatal(1,"constant clobbered MAC");q_const_value=~q_const_value;end
            held_result=q_result;tick();if(!q_valid||q_result!==held_result) $fatal(1,"backpressure");
            ce=0;q_ready=1;tick();if(!q_valid) $fatal(1,"CE output hold");ce=1;tick();q_ready=0;if(q_busy) $fatal(1,"consume");
            cases=cases+1;
        end
        q_const=0;
        // Original RAM slot survives temporary weight writes and MAC arithmetic.
        restore=1;tick();restore=0;while(busy) tick();
        if(psum!==saved) $fatal(1,"saved originals corrupted");tick();
        // Undrained multiplication rejects Q31 while the old read still retires.
        issue=1;rd_addr=2046;tick();issue=0;q_reuse=0;q_multiplier=1;q_shift=1;q_start=1;tick();q_start=0;
        if(!command_error||q_busy||read_valid) $fatal(1,"drain rejection");tick();
        // Reset cancels active work and invalidates the reusable scalar.
        q_start=1;tick();q_start=0;repeat(7) tick();reset();q_reuse=1;bad();
        // Cancel at every new SHIFT boundary, including CE=0 reset.
        for(j=0;j<6;j=j+1) begin
            q_const=0;q_reuse=0;q_shift=62;q_multiplier=31'h7fffffff;q_acc=32'h80000000;
            q_start=1;tick();q_start=0;repeat(18+j) tick();reset();q_reuse=1;bad();
        end
        q_const=1;q_const_value=-128;q_start=1;tick();q_start=0;
        if(!q_valid) $fatal(1,"constant acceptance");reset();q_const=0;q_reuse=1;bad();
        $display("PASS requant cases=%0d constants=%0d cycles=%0d stalls=%0d",cases,constant_cases,cycles,stalls);$finish;
    end
    initial begin #20000000;$fatal(1,"global timeout");end
endmodule
