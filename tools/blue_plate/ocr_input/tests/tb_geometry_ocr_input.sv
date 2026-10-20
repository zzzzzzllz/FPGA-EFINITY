`timescale 1ns/1ps
module tb;
    reg clk=0;always #5 clk=~clk;
    reg rst=1,job_valid=0,cancel_valid=0,corner_valid=0,done_ready=0;
    wire job_ready,corner_ready,hold_valid,held,release_valid,done_valid;
    reg [5:0] job_slot=0;wire [5:0] held_slot;
    reg [31:0] job_frame_id=0,job_epoch=1,job_generation=2,job_source_time_ms=0;
    reg [31:0] config_epoch=1,config_generation=2;
    wire hold_ready=1,hold_granted=1,release_ready=1;
    wire [133:0] hold_identity,identity;reg [133:0] expected_identity;
    reg signed [31:0] corner_data=0;wire [7:0] done_status;
    wire burst_valid,burst_ready,rsp_valid,rsp_ready,rsp_last,recover_req;
    wire [31:0] burst_addr;wire [7:0] burst_len;wire [127:0] rsp_data;
    reg [1:0] rsp_resp=0;reg recover_ack=0;
    wire sink_valid,sink_ready,sink_last,sink_done_valid,sink_done_ready,sink_cancel_req;
    wire [23:0] sink_bgr;wire [11:0] sink_address;
    reg sink_error=0,sink_cancel_ack=0;wire sink_done_ok=1;
    geometry_ocr_input dut(.*);
    reg [127:0] memory[0:172799];reg [31:0] corners[0:7];
    reg [23:0] real_gold[0:2255],synthetic_gold[0:2255];
    reg real_frame=0,bus_active=0,bus_pause=0,write_pause=0,checking=0,last_seen=0;
    reg source_seen=0,sink_seen=0,was_stalled=0;
    reg [36:0] held_output;
    integer tick=0,base_word=0,bus_index=0,bus_length=0,read_quiet=0;
    integer pending=0,seen=0,colors=0,flush_delay=0,cancel_age=0,holds=0,releases=0,jobs=0,k,watch=0;
    integer stalls=0,early_failures=0,drain_stalls=0;
    assign burst_ready=!bus_active && tick%5!=0;
    assign rsp_valid=bus_active && !bus_pause && tick%7!=0;
    assign rsp_last=bus_index==bus_length;
    assign sink_ready=pending<16 && tick%41>=13;
    assign sink_done_valid=last_seen && pending==0 && flush_delay>=31 && !sink_seen && !sink_cancel_req;
    function [7:0] byte_at(input integer a);
        integer pix,x,y;begin pix=a/3;x=pix%1280;y=pix/1280;
            case(a%3)0:byte_at=x;1:byte_at=y;2:byte_at=x+y;endcase
        end
    endfunction
    function [127:0] word_at(input integer a);
        integer j;begin if(real_frame)word_at=memory[a/16];
            else for(j=0;j<16;j=j+1)word_at[127-j*8-:8]=byte_at(a+j);
        end
    endfunction
    assign rsp_data=word_at((base_word+bus_index)*16);
    always @(posedge clk) begin
        tick<=tick+1;
        if(rst) begin bus_active<=0;recover_ack<=0;read_quiet<=0;sink_cancel_ack<=1;cancel_age=0;end
        else begin
            if(hold_valid && hold_ready)holds=holds+1;
            if(release_valid && release_ready)begin
                if(bus_active || pending!=0 || !held || (!sink_seen && !sink_cancel_ack))$fatal(1,"released before read/write drain");
                releases=releases+1;
            end
            if(burst_valid && burst_ready)begin
                if(!held)$fatal(1,"read without held frame");
                base_word=burst_addr/16;bus_index<=0;bus_length=burst_len;bus_active<=1;
            end
            if(rsp_valid)begin
                if(!rsp_ready)$fatal(1,"response blocked during drain");
                if(rsp_last)bus_active<=0;else bus_index<=bus_index+1;
            end
            if(recover_req && !bus_active && !rsp_valid && !(burst_valid && burst_ready))begin
                read_quiet<=read_quiet+1;recover_ack<=read_quiet>=4;
            end else begin read_quiet<=0;recover_ack<=0;end
            if(pending>0 && !write_pause && tick%97==0)pending=pending-1;
            if(sink_cancel_req)begin
                cancel_age=cancel_age+1;last_seen=0;
                // Start with a stale high: the session must observe low before accepting a fresh acknowledgement.
                sink_cancel_ack<=cancel_age<=3 || (cancel_age>=20 && pending==0);
                if(pending!=0 || bus_active)begin
                    if(job_ready || done_valid || release_valid)$fatal(1,"cleanup published or restarted early");
                    drain_stalls=drain_stalls+1;
                end
            end else begin cancel_age=0;sink_cancel_ack<=pending>0;end
            if(checking)begin
                if(identity!==expected_identity)$fatal(1,"source identity changed");
                if(dut.color_valid && dut.color_ready)colors=colors+1;
                if(was_stalled && !dut.local_abort && (!sink_valid || {sink_last,sink_address,sink_bgr}!==held_output))$fatal(1,"sink data changed under backpressure");
                was_stalled=sink_valid && !sink_ready && !dut.local_abort;
                held_output={sink_last,sink_address,sink_bgr};
                if(sink_valid && !sink_ready)stalls=stalls+1;
                if(sink_valid && sink_ready)begin
                    if(dut.local_abort || sink_cancel_req || seen>=2256 || sink_address!==seen || sink_last!==(seen==2255))$fatal(1,"invalid sink write");
                    if(sink_bgr!==(real_frame ? real_gold[seen] : synthetic_gold[seen]))$fatal(1,"linked Q8 mismatch p=%0d",seen);
                    pending=pending+1;seen=seen+1;if(sink_last)last_seen=1;
                end
                if(dut.geometry_done && dut.geometry_done_ready && dut.geometry_status==0)source_seen=1;
                if(last_seen && pending==0)flush_delay=flush_delay+1;
                if(sink_done_valid && sink_done_ready)sink_seen=1;
                if(done_valid && done_status==0 && (!source_seen || !sink_seen || seen!=2256 || colors!=14336 || pending!=0 || held || bus_active))$fatal(1,"partial success");
            end
        end
    end
    task begin_job(input integer mode);begin
        @(negedge clk);while(!job_ready)@(negedge clk);
        real_frame=mode==0;seen=0;colors=0;pending=0;last_seen=0;flush_delay=0;source_seen=0;sink_seen=0;was_stalled=0;
        config_epoch=1;job_epoch=1;job_frame_id=100+jobs;job_source_time_ms=3000+jobs;
        expected_identity={job_slot,job_frame_id,job_epoch,job_generation,job_source_time_ms};
        job_valid=1;@(negedge clk);job_valid=0;checking=1;
        job_frame_id=32'hdeadbeef;job_source_time_ms=32'hbadbeef;
        while(!corner_ready)@(negedge clk);
        for(k=0;k<8;k=k+1)begin
            corner_valid=1;
            case(k)0,1,3,6:corner_data=0;2,4:corner_data=223*65536;5,7:corner_data=63*65536;endcase
            if(mode==0)corner_data=corners[k];
            if(mode==6)corner_data=0;
            @(negedge clk);
        end
        corner_valid=0;
    end endtask
    task collect(input integer expected);begin
        watch=0;while(!done_valid)begin @(negedge clk);watch=watch+1;if(watch>5000)$fatal(1,"cleanup deadlock state=%0d reader=%0d",dut.state,dut.reader.state);end
        if(done_status!==expected || pending!=0 || bus_active || held || holds!=releases)$fatal(1,"result=%h expected=%h holds=%0d releases=%0d",done_status,expected,holds,releases);
        repeat(9)begin @(negedge clk);if(!done_valid || job_ready || sink_valid || done_status!==expected)$fatal(1,"result hold");end
        job_valid=0;cancel_valid=0;sink_error=0;rsp_resp=0;config_epoch=1;checking=0;
        done_ready=1;@(negedge clk);done_ready=0;jobs=jobs+1;
        $display("linked job=%0d status=%h pixels=%0d colors=%0d",jobs,expected,seen,colors);$fflush();
    end endtask
    task fail_early(input integer kind,input integer expected);begin
        begin_job(kind);
        $display("fault test kind=%0d started",kind);$fflush();
        if(kind!=6)begin
            while(seen<12)@(negedge clk);
            write_pause=1;
            while(seen<13)@(negedge clk);
            while(!bus_active)@(negedge clk);
            bus_pause=1;
            case(kind)
                1:begin rsp_resp=2;bus_pause=0;while(!dut.reader_abort)@(negedge clk);end
                2:begin bus_pause=0;force dut.geometry.keep=2'b00;while(!dut.failed)@(negedge clk);release dut.geometry.keep;end
                3:sink_error=1;
                4:cancel_valid=1;
                5:config_epoch=2;
            endcase
            while(!sink_cancel_req)@(negedge clk);
            $display("fault kind=%0d latched pending=%0d reader=%0d",kind,pending,dut.reader.state);$fflush();
            if(seen>=2256 || pending==0)$fatal(1,"early failure lacked provisional writes");
            early_failures=early_failures+1;
            job_valid=1; // A different live header must not acquire a frame during cleanup.
            repeat(17)@(negedge clk);write_pause=0;bus_pause=0;
        end
        collect(expected);
    end endtask
    initial begin
        $readmemh("frame.mem",memory);$readmemh("corners.mem",corners);
        $readmemh("expected.mem",real_gold);$readmemh("synthetic.mem",synthetic_gold);
        repeat(4)@(negedge clk);rst=0;
        fail_early(1,'h19);fail_early(2,'h27);fail_early(3,'h40);
        fail_early(4,'h50);fail_early(5,'h16);fail_early(6,'h2a);
        begin_job(7);while(seen<2255)@(negedge clk);write_pause=1;
        while(seen<2256)@(negedge clk);
        if(pending==0 || sink_seen || done_valid)$fatal(1,"last write not provisional");
        sink_error=1;repeat(17)@(negedge clk);write_pause=0;collect('h40);
        begin_job(0);while(!done_valid)@(negedge clk);collect(0);
        if(jobs!=8 || holds!=8 || releases!=8 || early_failures!=5 || stalls==0 || drain_stalls==0)$fatal(1,"missing lifecycle coverage");
        $display("PASS linked geometry/Q8 jobs=%0d holds=%0d releases=%0d stalls=%0d drain_stalls=%0d",jobs,holds,releases,stalls,drain_stalls);$finish;
    end
    initial begin #1000000000;$fatal(1,"integration timeout state=%0d reader=%0d seen=%0d",dut.state,dut.reader.state,seen);end
endmodule
