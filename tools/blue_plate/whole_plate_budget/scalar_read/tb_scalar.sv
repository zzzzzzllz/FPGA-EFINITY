`timescale 1ns/1ps
module tb_scalar;
    reg clk=0;always #5 clk=~clk;
    reg rst=0,ce=1,wr_en=0,issue=0,load=0,save=0,restore=0;
    reg [10:0] wr_addr=0,rd_addr=0;reg [63:0] wr_data=0;
    reg [135:0] activation=0;reg [7:0] lane_mask=255;
    reg [255:0] seed=0;reg [5:0] slot=0;
    wire busy,done,read_valid,command_error;wire [255:0] psum;wire [7:0] updated,overflow;
    reg scalar_read=0,scalar_ready=0;reg [2:0] scalar_lane=0;
    wire scalar_valid;wire signed [31:0] scalar_data;
    reg q_start=0,q_reuse=0,q_relu=0,q_ready=0,q_const=0;
    reg signed [7:0] q_const_value=0,q_zero=0;
    reg signed [31:0] q_acc=0;reg [30:0] q_multiplier=1;reg [5:0] q_shift=1;
    wire q_busy,q_valid;wire signed [7:0] q_result;
    q31_scalar_mac8 dut(.*);
    integer cycles=0,reads=0,checks=0,qchecks=0,stalls=0,s,l,j,t,start_cycle,steps;
    integer fd,n,op,record_slot,record_lane;
    reg [4095:0] path;
    reg [255:0] held,expected_sum;
    reg signed [31:0] expected_acc;
    reg [30:0] record_m;reg [5:0] record_shift;reg record_relu;
    reg signed [7:0] record_zero,expected_q;
    reg signed [63:0] expected_product;
    function [31:0] pattern(input integer a,input integer b);
        pattern=32'h81234567+(a*8+b)*32'h00123457;
    endfunction
    task tick;begin @(posedge clk);#1;cycles=cycles+1;@(negedge clk);end endtask
    task clear_commands;begin wr_en=0;issue=0;load=0;save=0;restore=0;scalar_read=0;q_start=0;end endtask
    task reset;begin
        clear_commands();rst=1;ce=0;tick();rst=0;ce=1;scalar_ready=0;q_ready=0;
        if(busy||scalar_valid||q_valid||read_valid) $fatal(1,"reset did not cancel");
    end endtask
    task select_command(input integer k);begin
        clear_commands();case(k)
            0:wr_en=1;1:issue=1;2:load=1;3:save=1;4:restore=1;5:scalar_read=1;6:q_start=1;
        endcase
    end endtask
    task save_group(input integer a);begin
        slot=a;save=1;tick();save=0;t=0;
        while(busy) begin tick();t=t+1;if(t>9) $fatal(1,"save timeout");end
        if(t!=8||!done||scalar_valid) $fatal(1,"save timing");
    end endtask
    task start_read(input integer a,input integer b,input [31:0] value);begin
        if(busy||scalar_valid) $fatal(1,"read requires idle");
        held=psum;slot=a;scalar_lane=b;scalar_read=1;tick();scalar_read=0;
        if(!busy||scalar_valid||command_error||done) $fatal(1,"read acceptance");
        slot=~a;scalar_lane=~b;tick();
        if(!scalar_valid||scalar_data!==value||psum!==held||done) $fatal(1,"read data expected=%h got=%h",value,scalar_data);
        reads=reads+1;
    end endtask
    task consume;begin
        scalar_ready=1;tick();scalar_ready=0;
        if(busy||scalar_valid) $fatal(1,"stale scalar valid");
    end endtask
    task check_q;begin
        q_start=1;ce=0;tick();ce=1;stalls=stalls+1;
        if(q_busy||scalar_valid!==(op==6)) $fatal(1,"CE blocked handoff");
        tick();q_start=0;scalar_ready=0;
        if(!q_busy||scalar_valid||command_error) $fatal(1,"Q handoff");
        if(dut.original!==expected_acc) $fatal(1,"original source %h/%h",dut.original,expected_acc);
        steps=0;
        while(!q_valid) begin
            q_acc=32'hdeadbeef;q_multiplier=1;q_shift=1;q_zero=127;q_relu=0;
            if(steps==2) scalar_read=1;
            tick();steps=steps+1;
            if(steps==3 && (!command_error||scalar_valid)) $fatal(1,"scalar during Q");scalar_read=0;
            if(steps==18 && dut.product!==expected_product) $fatal(1,"full product");
            if(steps>25) $fatal(1,"Q timeout");
        end
        if(steps!=25||q_result!==expected_q) $fatal(1,"Q value %0d/%0d steps=%0d",q_result,expected_q,steps);
        scalar_read=1;tick();scalar_read=0;
        if(!command_error||!q_valid||scalar_valid||q_result!==expected_q) $fatal(1,"Q output hold");
        q_ready=1;ce=0;tick();ce=1;stalls=stalls+1;
        if(!q_valid||q_result!==expected_q) $fatal(1,"Q output CE hold");
        q_ready=1;tick();q_ready=0;
        if(q_busy||scalar_valid) $fatal(1,"Q consume");qchecks=qchecks+1;
    end endtask
    initial begin
        reset();
        // Every slot/lane, signed words, and address changes after acceptance.
        for(s=0;s<64;s=s+1) begin
            for(l=0;l<8;l=l+1) seed[l*32 +:32]=pattern(s,l);
            load=1;tick();load=0;save_group(s);
        end
        for(s=63;s>=0;s=s-1) for(l=7;l>=0;l=l-1) begin
            start_cycle=cycles;start_read(s,l,pattern(s,l));
            if((s+l)%17==0) begin
                ce=0;scalar_ready=1;tick();stalls=stalls+1;
                if(!scalar_valid||scalar_data!==pattern(s,l)||psum!==held) $fatal(1,"CE hold");
                ce=1;scalar_ready=0;tick();
                if(!scalar_valid||scalar_data!==pattern(s,l)) $fatal(1,"ready hold");
            end
            consume();
            if((s+l)%17!=0 && cycles-start_cycle!=3) $fatal(1,"scalar cycle count");
            checks=checks+1;
        end
        scalar_read=1;ce=0;tick();ce=1;scalar_read=0;stalls=stalls+1;
        if(busy||scalar_valid) $fatal(1,"read accepted with CE=0");
        // All commands conflict with a new read. Nothing is forwarded.
        for(j=0;j<7;j=j+1) if(j!=5) begin
            held=psum;select_command(j);scalar_read=1;tick();clear_commands();
            if(!command_error||busy||scalar_valid||psum!==held) $fatal(1,"idle conflict %0d",j);
            tick();
        end
        // Every new command is rejected during read and output hold.
        for(j=0;j<7;j=j+1) begin
            slot=0;scalar_lane=0;scalar_read=1;tick();scalar_read=0;
            ce=0;tick();ce=1;stalls=stalls+1;if(scalar_valid) $fatal(1,"premature valid");
            select_command(j);tick();clear_commands();
            if(!command_error||!scalar_valid||scalar_data!==pattern(0,0)) $fatal(1,"read conflict %0d",j);
            select_command(j);tick();clear_commands();
            if(!command_error||!scalar_valid||scalar_data!==pattern(0,0)) $fatal(1,"hold conflict %0d",j);
            consume();
        end
        // An ordinary rejected command cannot cancel a ready old response.
        start_read(0,1,pattern(0,1));load=1;scalar_ready=1;tick();load=0;scalar_ready=0;
        if(!command_error||scalar_valid||busy) $fatal(1,"ready with rejected command");tick();
        // An invalid Q handoff retains the response. No stale value is consumed.
        start_read(0,2,pattern(0,2));q_multiplier=0;q_reuse=0;q_const=0;q_shift=1;
        scalar_ready=1;q_start=1;tick();q_start=0;scalar_ready=0;
        if(!command_error||!scalar_valid||q_busy) $fatal(1,"invalid Q consumed scalar");
        q_multiplier=1;q_reuse=1;scalar_ready=1;q_start=1;tick();q_start=0;scalar_ready=0;q_reuse=0;
        if(!command_error||!scalar_valid||q_busy) $fatal(1,"reuse consumed scalar");
        q_const=1;scalar_ready=1;q_start=1;tick();q_start=0;scalar_ready=0;q_const=0;
        if(!command_error||!scalar_valid||q_busy) $fatal(1,"constant consumed scalar");consume();
        // Reject reads during group transfers; original save/restore remain 9/17 cycles.
        for(j=0;j<2;j=j+1) begin
            slot=60;save=(j==0);restore=(j==1);tick();save=0;restore=0;t=0;
            while(busy) begin scalar_read=1;tick();scalar_read=0;t=t+1;
                if(!command_error||scalar_valid) $fatal(1,"group conflict");end
            if(t!=(j==0?8:16)||!done) $fatal(1,"group timing");tick();
        end
        // Pending MAC must retire before a scalar request can be accepted.
        wr_en=1;wr_addr=0;wr_data=64'h0101010101010101;tick();wr_en=0;
        issue=1;rd_addr=0;activation=0;tick();issue=0;scalar_read=1;tick();scalar_read=0;
        if(!command_error||busy||scalar_valid||read_valid) $fatal(1,"undrained conflict");tick();
        // Reset before and after RAM read, including CE=0, preserves stored words.
        slot=0;scalar_lane=3;scalar_read=1;tick();scalar_read=0;reset();
        start_read(0,3,pattern(0,3));reset();start_read(0,3,pattern(0,3));consume();
        q_reuse=1;q_start=1;tick();q_start=0;q_reuse=0;
        if(!command_error||q_busy) $fatal(1,"reset original valid");tick();
        // Ready already high: acceptance and RAM read still precede consumption.
        scalar_ready=1;start_read(0,4,pattern(0,4));tick();scalar_ready=0;
        if(scalar_valid||busy) $fatal(1,"ready-high consume");
        if(!$value$plusargs("VECTORS=%s",path)) $fatal(1,"vectors required");
        fd=$fopen(path,"r");if(!fd) $fatal(1,"real vectors open");
        while(!$feof(fd)) begin
            n=$fscanf(fd,"%h",op);if(n!=1) $fatal(1,"opcode");
            case(op)
                1:begin n=$fscanf(fd,"%h %h\n",wr_addr,wr_data);if(n!=2) $fatal(1,"write record");wr_en=1;tick();wr_en=0;end
                2:begin n=$fscanf(fd,"%h\n",seed);if(n!=1) $fatal(1,"seed record");load=1;tick();load=0;end
                3:begin n=$fscanf(fd,"%h %h %h\n",rd_addr,activation,lane_mask);if(n!=3) $fatal(1,"MAC record");issue=1;tick();issue=0;end
                4:begin n=$fscanf(fd,"%h\n",expected_sum);tick();if(psum!==expected_sum||read_valid) $fatal(1,"real MAC sum");end
                5:begin n=$fscanf(fd,"%h\n",record_slot);save_group(record_slot);end
                6,7:begin
                    n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h\n",record_slot,record_lane,expected_acc,record_m,record_shift,record_relu,record_zero,expected_q,expected_product);
                    if(n!=9) $fatal(1,"Q record");start_cycle=cycles;
                    if(op==6) begin start_read(record_slot,record_lane,expected_acc);scalar_ready=1;end
                    else begin
                        // Constant bypass between the real tap2 consumers must preserve raw int32.
                        q_const=1;q_const_value=31;q_start=1;tick();q_start=0;
                        if(!q_valid||q_result!=31) $fatal(1,"interposed constant");
                        q_ready=1;tick();q_ready=0;q_const=0;start_cycle=cycles;
                    end
                    q_reuse=(op==7);q_acc=32'hdeadbeef;q_multiplier=record_m;q_shift=record_shift;q_relu=record_relu;q_zero=record_zero;
                    check_q();q_reuse=0;
                    // Three explicit protocol-test cycles: two CE stalls and one result hold.
                    if(cycles-start_cycle!=(op==6?32:30)) $fatal(1,"combined cycle count");
                end
                default:$fatal(1,"unknown opcode %d",op);
            endcase
        end
        $display("PASS scalar cycles=%0d all_address_checks=%0d scalar_reads=%0d real_q_outputs=%0d stalls=%0d",cycles,checks,reads,qchecks,stalls);$finish;
    end
    initial begin #20000000;$fatal(1,"global timeout");end
endmodule
