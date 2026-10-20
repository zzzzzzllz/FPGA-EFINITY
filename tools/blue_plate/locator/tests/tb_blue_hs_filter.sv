`timescale 1ns/1ps
module tb_blue_hs_filter;
    reg clk=0;always #5 clk=~clk;
    reg rst=1,abort=0,in_valid=0,out_ready=0,value_allowed=0;
    reg [23:0] rgb=0;
    wire in_ready,out_valid,blue;
    blue_hs_filter dut(.*);
    reg [255:0] expected[0:65535];
    integer queue_id[0:7];reg queue_gate[0:7];
    integer head=0,tail=0,checked=0,ticks=0,i,identifier;
    reg blocked=0,saved_blue;
    always @(posedge clk)begin
        ticks=ticks+1;
        if(rst || abort)begin head=0;tail=0;blocked=0;end
        else begin
            if(blocked && (!out_valid || blue!==saved_blue))$fatal(1,"unstable result");
            blocked=out_valid && !out_ready;saved_blue=blue;
            if(in_valid && in_ready)begin
                queue_id[tail%8]={rgb[7:0],rgb[23:16],rgb[15:8]};
                queue_gate[tail%8]=value_allowed;tail=tail+1;
            end
            if(out_valid && out_ready)begin
                if(head>=tail)$fatal(1,"unsolicited output");
                identifier=queue_id[head%8];
                if(blue !== (expected[identifier>>8][identifier&255] & queue_gate[head%8]))
                    $fatal(1,"mask mismatch index=%0d gate=%0d got=%b",identifier,queue_gate[head%8],blue);
                head=head+1;checked=checked+1;
            end
        end
    end
    task drive(input integer id,input reg gate);begin
        rgb={id[15:8],id[7:0],id[23:16]};value_allowed=gate;
    end endtask
    task drain;begin
        @(negedge clk);in_valid=0;out_ready=1;
        while(head!=tail)@(negedge clk);
        repeat(3)@(negedge clk);
        if(out_valid)$fatal(1,"extra output after drain");
    end endtask
    initial begin
        $readmemh("expected.mem",expected);
        repeat(3)@(negedge clk);rst=0;
        // Cancel two occupied stages while the output is held, then recover.
        in_valid=1;drive(24'hc81040,1);
        repeat(4)@(negedge clk);abort=1;in_valid=0;
        repeat(2)@(negedge clk);
        if(out_valid || in_ready)$fatal(1,"abort handshake leaked");
        abort=0;repeat(3)@(negedge clk);
        if(out_valid)$fatal(1,"cancelled pixel escaped");
        i=0;
        while(i<16777216)begin
            @(negedge clk);in_valid=ticks%13!=0;out_ready=ticks%17>=5;
            drive(i,1);@(posedge clk);if(in_valid && in_ready)i=i+1;
        end
        drain();
        i=0;
        while(i<10000)begin
            @(negedge clk);in_valid=ticks%11!=0;out_ready=ticks%7>=2;
            drive((i*7919)&24'hffffff,i%3!=0);
            @(posedge clk);if(in_valid && in_ready)i=i+1;
        end
        drain();
        @(negedge clk);in_valid=1;out_ready=0;drive(24'hb03050,1);
        repeat(4)@(negedge clk);rst=1;in_valid=0;
        repeat(2)@(negedge clk);rst=0;
        repeat(3)@(negedge clk);if(out_valid)$fatal(1,"reset pixel escaped");
        // Reset recovery includes an accepted and a rejected pixel.
        i=0;while(i<2)begin
            @(negedge clk);out_ready=1;in_valid=1;drive(24'hb03050,i==0);
            @(posedge clk);if(in_ready)i=i+1;
        end
        drain();
        if(checked!=16787218)$fatal(1,"wrong check count %0d",checked);
        $display("PASS blue mask RGB=%0d mixed_gate=10000 recovery=2 checked=%0d cycles=%0d",16777216,checked,ticks);
        $finish;
    end
    initial begin #1000000000;$fatal(1,"timeout");end
endmodule
