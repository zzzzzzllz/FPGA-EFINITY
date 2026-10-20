`timescale 1ns/1ps
module tb;
    reg clk=0;always #5 clk=~clk;
    reg rst=1,abort=0,start_valid=0;
    wire start_ready;
    reg [133:0] start_identity=0,expected_identity=0;
    reg in_valid=0,in_last=0;
    wire in_ready;
    reg [23:0] in_rgb=0;
    reg [13:0] in_address=0;
    reg source_done_valid=0,source_done_ok=1,sink_done_valid=0,sink_done_ok=1,done_ready=0;
    wire source_done_ready,sink_done_ready,done_valid,out_valid,out_last;
    wire [23:0] out_bgr;
    wire [11:0] out_address;
    wire [133:0] identity;
    wire [2:0] done_status;
    reg force_stall=0;
    integer tick=0,seen=0,stalls=0,mode=0,jobs=0,p,k,unused;
    wire out_ready=!force_stall && tick%197>=67;
    reg was_stalled=0,source_seen=0,sink_seen=0,checking=0;
    reg [36:0] held_output;
    reg [23:0] pixels[0:14335],gold[0:2255];
    ocr_resize_q8 dut(.*);
    always @(posedge clk) begin
        tick<=tick+1;
        if(rst || abort) begin
            was_stalled<=0;
            if(out_valid || in_ready || done_valid)$fatal(1,"reset/abort handshake leaked");
        end else if(checking) begin
            if(identity!==expected_identity)$fatal(1,"source identity changed");
            if(was_stalled && (!out_valid || {out_last,out_address,out_bgr}!==held_output))$fatal(1,"output moved under backpressure");
            was_stalled<=out_valid && !out_ready;
            held_output<={out_last,out_address,out_bgr};
            if(out_valid && !out_ready)stalls=stalls+1;
            if(out_valid && out_ready)begin
                if(seen>=2256 || out_address!==seen || out_last!==(seen==2255) || out_bgr!==gold[seen])
                    $fatal(1,"Q8 pixel %0d got %h exp %h addr %0d",seen,out_bgr,gold[seen],out_address);
                seen=seen+1;
            end
            if(source_done_valid && source_done_ready)source_seen=1;
            if(sink_done_valid && sink_done_ready)sink_seen=1;
            if(done_valid && done_status==0 && (!source_seen || !sink_seen || seen!=2256))$fatal(1,"published partial input");
        end
    end
    task begin_job;begin
        @(negedge clk);
        if(!start_ready)$fatal(1,"start blocked");
        expected_identity={6'd2,32'(jobs+41),32'd3,32'd7,32'(jobs+1000)};
        start_identity=expected_identity;start_valid=1;
        @(negedge clk);start_valid=0;start_identity=~expected_identity;
        seen=0;source_seen=0;sink_seen=0;checking=1;force_stall=0;
        source_done_ok=1;sink_done_ok=1;
    end endtask
    task finish_result(input integer status);begin
        while(!done_valid)@(negedge clk);
        if(done_status!==status)$fatal(1,"status got %0d exp %0d",done_status,status);
        repeat(11)begin @(negedge clk);if(!done_valid || start_ready || out_valid || done_status!==status)$fatal(1,"completion hold");end
        done_ready=1;@(negedge clk);done_ready=0;checking=0;jobs=jobs+1;
    end endtask
    task cancel_job(input integer reset_it);begin
        if(reset_it)rst=1;else abort=1;
        repeat(3)@(negedge clk);
        rst=0;abort=0;force_stall=0;checking=0;in_valid=0;
        repeat(3)@(negedge clk);
        if(out_valid || done_valid || !start_ready)$fatal(1,"cancel did not discard");
        jobs=jobs+1;
    end endtask
    task execute(input integer kind);begin
        begin_job();
        begin: feed
            for(p=0;p<14336;p=p+1)begin
                if(p%17==0)repeat(2)@(negedge clk);
                in_address=(kind==1 && p==500) ? 14'd499 : p;
                in_last=(kind==2 && p==500) || p==14335;in_rgb=pixels[p];in_valid=1;
                if(kind==6 && p==14335)force_stall=1;
                while(!in_ready)@(negedge clk);
                @(negedge clk);in_valid=0;
                if((kind==1 || kind==2) && p==500)begin finish_result(1);disable feed;end
                if((kind==5 || kind==7) && p==1000)begin cancel_job(kind==7);disable feed;end
            end
            if(kind==6)begin
                while(!out_valid || !out_last)@(negedge clk);
                if(seen!=2255 || done_valid)$fatal(1,"last pixel not provisional");
                repeat(19)@(negedge clk);cancel_job(0);disable feed;
            end
            while(!source_done_ready)@(negedge clk);
            if(done_valid)$fatal(1,"completion before source result");
            repeat(9)@(negedge clk);
            source_done_valid=1;source_done_ok=kind!=3;
            @(negedge clk);source_done_valid=0;
            if(kind==3)begin finish_result(2);disable feed;end
            while(!sink_done_ready)@(negedge clk);
            repeat(13)begin @(negedge clk);if(done_valid)$fatal(1,"completion before sink flush");end
            sink_done_valid=1;sink_done_ok=kind!=4;
            @(negedge clk);sink_done_valid=0;
            finish_result(kind==4 ? 3 : 0);
        end
    end endtask
    initial begin
        unused=$value$plusargs("MODE=%d",mode);
        $readmemh("input.mem",pixels);$readmemh("expected.mem",gold);
        repeat(4)@(negedge clk);rst=0;
        if(mode!=0)execute(mode);
        execute(0);
        if(stalls==0)$fatal(1,"no output stalls exercised");
        $display("PASS Q8 input mode=%0d jobs=%0d final_pixels=%0d stalls=%0d",mode,jobs,seen,stalls);$finish;
    end
    initial begin #100000000;$fatal(1,"global timeout");end
endmodule
