`timescale 1ns/1ps
module tb;
    reg clk=0;always #5 clk=~clk;
    reg rst=1,enabled=1,start_valid=0,in_valid=0,in_last=0,cancel_req=0,done_ready=0;
    wire start_ready,in_ready,cancel_ack,done_valid,error,isolation_required;
    reg [133:0] start_identity=0,expected_identity=0;wire [133:0] identity;
    reg [31:0] feature_region_base=32'h1000fff0,config_epoch=1,config_generation=2;
    reg [1:0] feature_slot=0;reg [23:0] in_bgr=0;reg [11:0] in_address=0;
    wire [3:0] done_status,awid;wire [31:0] awaddr;wire [7:0] awlen;
    wire [2:0] awsize;wire [1:0] awburst;
    wire awvalid,awready,wvalid,wready,wlast,bvalid,bready;
    wire [127:0] wdata;wire [15:0] wstrb;wire [3:0] bid;wire [1:0] bresp;
    ocr_hwc_writer dut(.*);
    reg [23:0] pixels[0:2255];reg [7:0] golden[0:6767],memory[0:6799];
    reg aw_pause=0,w_pause=0,b_pause=0,last_b_pause=0,together=0;
    reg have_aw=0,have_w=0,pending_response=0,bus_bvalid=0;
    reg [31:0] accepted_address=0,target=0;reg [127:0] accepted_data=0;
    reg [1:0] bus_bresp=0,response_code=0;reg [3:0] bus_bid=0;
    reg extra_b=0,wrong_id=0,checking=0,was_aw_stalled=0,was_w_stalled=0;
    reg [31:0] held_address;reg [144:0] held_data;
    integer tick=0,delay_count=0,aw_count=0,w_count=0,b_count=0,error_at=0;
    integer tests=0,i,j,p,watch,aw_stalls=0,w_stalls=0,address_first=0,data_first=0,simultaneous=0;
    assign awready=!have_aw && !bus_bvalid && !aw_pause && (together || tick%7>=2);
    assign wready=!have_w && !bus_bvalid && !w_pause && (together || tick%11>=3);
    assign bvalid=bus_bvalid || extra_b;
    assign bid=extra_b ? 4'd0 : bus_bid;
    assign bresp=extra_b ? 2'd0 : bus_bresp;
    always @(posedge clk)begin
        tick<=tick+1;
        if(rst)begin
            have_aw=0;have_w=0;pending_response=0;bus_bvalid<=0;delay_count=0;
            aw_count=0;w_count=0;b_count=0;was_aw_stalled=0;was_w_stalled=0;
        end else begin
            if(checking && identity!==expected_identity)$fatal(1,"writer identity changed");
            if(was_aw_stalled && (!awvalid || awaddr!==held_address))$fatal(1,"AW withdrawn or changed during stall/cancel");
            if(was_w_stalled && (!wvalid || {wlast,wstrb,wdata}!==held_data))$fatal(1,"W withdrawn or changed during stall/cancel");
            was_aw_stalled=awvalid && !awready;held_address=awaddr;
            was_w_stalled=wvalid && !wready;held_data={wlast,wstrb,wdata};
            if(was_aw_stalled)aw_stalls=aw_stalls+1;
            if(was_w_stalled)w_stalls=w_stalls+1;
            if(awvalid && awready && wvalid && wready)simultaneous=simultaneous+1;
            else begin
                if(awvalid && awready && !have_w)address_first=address_first+1;
                if(wvalid && wready && !have_aw)data_first=data_first+1;
            end
            if(awvalid && awready)begin
                if(awid!=0 || awlen!=0 || awsize!=4 || awburst!=1 || awaddr[3:0]!=0 || awaddr!==target+aw_count*16 || aw_count>=423)$fatal(1,"AW contract/range");
                have_aw=1;accepted_address=awaddr;aw_count=aw_count+1;
            end
            if(wvalid && wready)begin
                if(wstrb!==16'hffff || !wlast || w_count>=423)$fatal(1,"W framing");
                have_w=1;accepted_data=wdata;w_count=w_count+1;
            end
            if(have_aw && have_w && !pending_response)begin
                for(j=0;j<16;j=j+1)begin
                    if(accepted_data[j*8+:8]!==golden[accepted_address-target+j])$fatal(1,"HWC byte mismatch offset=%0d",accepted_address-target+j);
                    memory[16+accepted_address-target+j]=accepted_data[j*8+:8];
                end
                pending_response=1;delay_count=0;
            end
            if(pending_response && !bus_bvalid)begin
                delay_count=delay_count+1;
                if(delay_count>=29 && !b_pause && !(last_b_pause && aw_count==423))begin
                    bus_bvalid<=1;bus_bresp<=aw_count==error_at ? response_code : 0;bus_bid<=wrong_id ? 4'd9 : 0;
                end
            end
            if(bus_bvalid && bready && !extra_b)begin
                b_count=b_count+1;bus_bvalid<=0;have_aw=0;have_w=0;pending_response=0;
            end
            if(cancel_ack && (have_aw || have_w || pending_response || bus_bvalid || awvalid || wvalid))$fatal(1,"cancel ack before bus drained");
            if(done_valid && done_status==0 && (b_count!=423 || aw_count!=423 || w_count!=423 || pending_response || bus_bvalid))$fatal(1,"success before all B responses");
        end
    end
    task begin_job;begin
        @(negedge clk);if(!start_ready)$fatal(1,"writer not ready");
        if(have_aw || have_w || pending_response || bus_bvalid)$fatal(1,"test started with old transaction");
        aw_count=0;w_count=0;b_count=0;target=feature_region_base+({30'd0,feature_slot}<<18);
        for(i=0;i<6800;i=i+1)memory[i]=8'ha5;
        expected_identity={6'd3,32'(100+tests),config_epoch,config_generation,32'(2000+tests)};
        start_identity=expected_identity;start_valid=1;
        @(negedge clk);start_valid=0;start_identity=~expected_identity;checking=1;
    end endtask
    task feed(input integer count,input integer malformed);begin
        for(p=0;p<count;p=p+1)begin
            while(!in_ready)begin @(negedge clk);if(error)$fatal(1,"unexpected error while feeding p=%0d status=%0d",p,done_status);end
            in_address=(malformed==1 && p==3) ? 12'd2 : p;
            in_last=(p==2255 && malformed!=3) || (malformed==2 && p==10);
            in_bgr=pixels[p];in_valid=1;@(negedge clk);in_valid=0;
        end
    end endtask
    task collect(input integer status);begin
        watch=0;while(!done_valid)begin @(negedge clk);watch=watch+1;if(watch>1000)$fatal(1,"completion timeout state=%0d",dut.state);end
        if(done_status!==status || isolation_required)$fatal(1,"status got=%0d expected=%0d",done_status,status);
        if(status==0)for(i=0;i<6768;i=i+1)if(memory[16+i]!==golden[i])$fatal(1,"memory image mismatch");
        for(i=0;i<16;i=i+1)if(memory[i]!==8'ha5 || memory[6784+i]!==8'ha5)$fatal(1,"guard overwritten");
        repeat(9)begin @(negedge clk);if(!done_valid || start_ready || done_status!==status)$fatal(1,"done hold");end
        checking=0;done_ready=1;@(negedge clk);done_ready=0;tests=tests+1;
        $display("writer test=%0d status=%0d AW=%0d W=%0d B=%0d",tests,status,aw_count,w_count,b_count);$fflush();
    end endtask
    task collect_cancel(input integer status);begin
        watch=0;while(!cancel_ack)begin @(negedge clk);watch=watch+1;if(watch>1000)$fatal(1,"cancel drain timeout");end
        if(done_valid || aw_count!=w_count || w_count!=b_count || done_status!==status)$fatal(1,"cancel completion mismatch status=%0d",done_status);
        repeat(9)begin @(negedge clk);if(!cancel_ack || start_ready || done_valid)$fatal(1,"cancel hold");end
        checking=0;cancel_req=0;@(negedge clk);@(negedge clk);tests=tests+1;
        $display("writer test=%0d cancelled=%0d drained=%0d",tests,status,b_count);$fflush();
    end endtask
    task quarantined;begin
        while(!isolation_required)@(negedge clk);
        cancel_req=1;
        repeat(17)begin @(negedge clk);if(start_ready || cancel_ack || done_valid || !isolation_required)$fatal(1,"stale response escaped isolation");end
        checking=0;extra_b=0;wrong_id=0;cancel_req=0;aw_pause=0;w_pause=0;b_pause=0;
        // Shared reset clears both model queues and writer ownership, never writer alone.
        rst=1;repeat(4)@(negedge clk);rst=0;repeat(3)@(negedge clk);tests=tests+1;
        $display("writer test=%0d protocol isolation/reset",tests);$fflush();
    end endtask
    initial begin
        $readmemh("input.mem",pixels);$readmemh("expected-bytes.mem",golden);
        repeat(4)@(negedge clk);rst=0;repeat(3)@(negedge clk);
        begin_job();feed(2256,0);collect(0);
        begin_job();feed(1,0);repeat(5)@(negedge clk);cancel_req=1;collect_cancel(3);
        aw_pause=1;begin_job();feed(6,0);while(!awvalid || w_count!=1)@(negedge clk);
        cancel_req=1;repeat(19)@(negedge clk);if(!awvalid || cancel_ack)$fatal(1,"cancelled pending AW");aw_pause=0;collect_cancel(3);
        w_pause=1;begin_job();feed(6,0);while(!wvalid || aw_count!=1)@(negedge clk);
        cancel_req=1;repeat(19)@(negedge clk);if(!wvalid || cancel_ack)$fatal(1,"cancelled pending W");w_pause=0;collect_cancel(3);
        b_pause=1;begin_job();feed(6,0);while(!pending_response)@(negedge clk);
        cancel_req=1;repeat(19)@(negedge clk);if(cancel_ack)$fatal(1,"cancelled before B");b_pause=0;collect_cancel(3);
        last_b_pause=1;begin_job();feed(2256,0);while(w_count<423 || aw_count<423)@(negedge clk);
        cancel_req=1;repeat(19)@(negedge clk);if(done_valid || cancel_ack)$fatal(1,"published before final B");last_b_pause=0;collect_cancel(3);
        error_at=2;response_code=2;begin_job();feed(11,0);collect(5);
        response_code=3;begin_job();feed(11,0);collect(5);error_at=0;response_code=0;
        begin_job();feed(4,1);collect(2);
        begin_job();feed(11,2);collect(2);
        begin_job();feed(2256,3);collect(2);
        feature_region_base=32'h1000fff1;begin_job();collect(1);
        feature_region_base=32'h1000fff0;feature_slot=2;begin_job();collect(1);
        feature_slot=0;feature_region_base=32'hfff80010;begin_job();collect(1);
        feature_region_base=32'hfff80000;feature_slot=1;begin_job();if(error)$fatal(1,"valid capacity boundary rejected");cancel_req=1;collect_cancel(3);
        feature_region_base=32'h1000fff0;feature_slot=0;
        extra_b=1;quarantined();
        wrong_id=1;begin_job();feed(6,0);quarantined();
        aw_pause=1;w_pause=1;begin_job();feed(6,0);while(!awvalid || !wvalid)@(negedge clk);
        extra_b=1;repeat(7)@(negedge clk);if(!awvalid || !wvalid)$fatal(1,"fault withdrew offered request");
        aw_pause=0;w_pause=0;while(!bready)@(negedge clk);@(negedge clk);extra_b=0;quarantined();
        b_pause=1;begin_job();feed(6,0);while(!pending_response)@(negedge clk);
        config_epoch=2;@(negedge clk);cancel_req=1;repeat(17)@(negedge clk);b_pause=0;collect_cancel(4);
        together=1;feature_slot=1;begin_job();feed(2256,0);collect(0);
        if(tests!=20 || address_first==0 || data_first==0 || simultaneous==0 || aw_stalls==0 || w_stalls==0)$fatal(1,"coverage missing tests=%0d",tests);
        $display("PASS OCR HWC writer tests=%0d AWfirst=%0d Wfirst=%0d together=%0d AWstalls=%0d Wstalls=%0d",tests,address_first,data_first,simultaneous,aw_stalls,w_stalls);$finish;
    end
    initial begin #20000000;$fatal(1,"writer test timeout state=%0d tests=%0d",dut.state,tests);end
endmodule
