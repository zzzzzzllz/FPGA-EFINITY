`timescale 1ns/1ps
// Fixed BGR u8 -> tightly packed HWC i8. A response completes each write.
module ocr_hwc_writer (
    input wire clk,rst,enabled,
    input wire start_valid,output wire start_ready,
    input wire [133:0] start_identity,output reg [133:0] identity,
    input wire [31:0] feature_region_base,input wire [1:0] feature_slot,
    input wire [31:0] config_epoch,config_generation,
    input wire in_valid,output wire in_ready,input wire [23:0] in_bgr,
    input wire [11:0] in_address,input wire in_last,
    input wire cancel_req,output wire cancel_ack,
    output wire done_valid,input wire done_ready,output reg [3:0] done_status,
    output wire error,isolation_required,
    output wire [3:0] awid,output reg [31:0] awaddr,
    output wire [7:0] awlen,output wire [2:0] awsize,output wire [1:0] awburst,
    output wire awvalid,input wire awready,
    output wire [127:0] wdata,output wire [15:0] wstrb,
    output wire wvalid,wlast,input wire wready,
    input wire bvalid,output wire bready,input wire [3:0] bid,input wire [1:0] bresp
);
    localparam IDLE=0,PACK=1,ISSUE=2,RESPONSE=3,DONE=4,CANCEL=5,LOCKED=6;
    // Status: 0 OK, 1 descriptor, 2 framing, 3 cancel, 4 config, 5 BRESP, 6 protocol, 7 state.
    reg [3:0] state;
    reg [127:0] packed_word;
    reg [23:0] pixel;
    reg [1:0] remaining;
    reg [3:0] filled;
    reg [11:0] pixels;
    reg [8:0] beat;
    reg cancelled,poisoned,aw_sent,w_sent;
    wire live=state==PACK || state==ISSUE || state==RESPONSE || state==DONE;
    wire config_changed=live && (identity[95:64]!=config_epoch || identity[63:32]!=config_generation);
    wire unexpected_b=bvalid && (state!=RESPONSE && state!=LOCKED || state==RESPONSE && bid!=0);
    wire [32:0] region_end={1'b0,feature_region_base}+33'd524288;
    wire bad_descriptor=feature_region_base[3:0]!=0 || feature_slot>1 || region_end>33'h100000000 ||
        start_identity[95:64]!=config_epoch || start_identity[63:32]!=config_generation;
    assign isolation_required=poisoned || unexpected_b;
    assign error=done_status!=0 || config_changed || unexpected_b;
    assign start_ready=state==IDLE && enabled && !rst && !cancel_req && !bvalid && !poisoned;
    assign in_ready=state==PACK && remaining==0 && !rst && !cancel_req && !config_changed && !poisoned && !unexpected_b;
    assign done_valid=state==DONE && !rst && !cancel_req && !bvalid && !poisoned && (!config_changed || done_status!=0);
    assign cancel_ack=state==CANCEL && !rst && !bvalid && !poisoned;
    // ponytail: single-beat writes avoid a new RAM; use the existing shared write block only if measured throughput needs bursts.
    assign awid=0;assign awlen=0;assign awsize=4;assign awburst=1;
    assign awvalid=state==ISSUE && !aw_sent && !rst;
    assign wvalid=state==ISSUE && !w_sent && !rst;
    assign wdata=packed_word;assign wstrb=16'hffff;assign wlast=1;
    assign bready=(state==RESPONSE || state==LOCKED) && !rst;

    always @(posedge clk) begin
        if(rst) begin
            state<=IDLE;identity<=0;awaddr<=0;done_status<=0;packed_word<=0;
            pixel<=0;remaining<=0;filled<=0;pixels<=0;beat<=0;cancelled<=0;poisoned<=0;aw_sent<=0;w_sent<=0;
        end else begin
            if(cancel_req && live) cancelled<=1;
            if(unexpected_b) poisoned<=1;
            case(state)
                IDLE: begin
                    if(cancel_req) state<=CANCEL;
                    else if(start_valid && start_ready) begin
                        identity<=start_identity;awaddr<=feature_region_base+({30'd0,feature_slot}<<18);
                        done_status<=bad_descriptor ? 1 : 0;state<=bad_descriptor ? DONE : PACK;
                        remaining<=0;filled<=0;pixels<=0;beat<=0;packed_word<=0;cancelled<=0;
                    end
                end
                PACK: begin
                    if(cancel_req || cancelled) state<=CANCEL;
                    else if(config_changed || done_status!=0) state<=DONE;
                    else if(remaining!=0) begin
                        // Sixteen shifts place the earliest byte in lane zero.
                        packed_word<={pixel[23:16],packed_word[127:8]};
                        pixel<=pixel<<8;remaining<=remaining-1'b1;
                        if(filled==15) begin filled<=0;aw_sent<=0;w_sent<=0;state<=ISSUE;end
                        else filled<=filled+1'b1;
                    end else if(in_valid && in_ready) begin
                        if(in_address!=pixels || in_last!=(pixels==2255)) begin done_status<=2;state<=DONE;end
                        else begin pixel<=in_bgr ^ 24'h808080;remaining<=3;pixels<=pixels+1'b1;end
                    end
                end
                ISSUE: begin
                    if(awvalid && awready) aw_sent<=1;
                    if(wvalid && wready) w_sent<=1;
                    if((aw_sent || awready) && (w_sent || wready)) state<=RESPONSE;
                end
                RESPONSE: if(bvalid) begin
                    if(poisoned || unexpected_b) state<=LOCKED;
                    else if(cancel_req || cancelled) state<=CANCEL;
                    else if(config_changed || done_status!=0 || bresp!=0) state<=DONE;
                    else if(beat==422) begin
                        if(pixels!=2256 || remaining!=0 || filled!=0) done_status<=2;
                        state<=DONE;
                    end else begin beat<=beat+1'b1;awaddr<=awaddr+16;state<=PACK;end
                    if(done_status==0 && bresp!=0) done_status<=5;
                end
                DONE: begin
                    if(cancel_req) state<=CANCEL;
                    else if(done_valid && done_ready) begin state<=IDLE;done_status<=0;end
                end
                CANCEL: if(!cancel_req) begin state<=IDLE;done_status<=0;cancelled<=0;end
                LOCKED: ; // Only a shared controller/writer reset restores response ownership.
                default: begin state<=LOCKED;poisoned<=1;done_status<=7;end
            endcase
            if(unexpected_b && state!=ISSUE && state!=RESPONSE) state<=LOCKED;
            if(done_status==0) begin
                if(unexpected_b) done_status<=6;
                else if(live && cancel_req) done_status<=3;
                else if(config_changed) done_status<=4;
            end
        end
    end
endmodule
