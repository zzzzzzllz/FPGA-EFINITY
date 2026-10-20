`include "plate_defs.vh"
// Source-domain confirmation. The output packet is stable under backpressure.
module plate_confirm #(parameter TTL_MS=500, W=1280, H=720)(
 input clk,rst_n,input [31:0] now_ms,current_epoch,current_generation,
 input in_valid,output in_ready,input [`PD_BITS-1:0] in_packet,
 output reg out_valid,input out_ready,output reg [`PD_BITS:0] out_packet,
 output reg [1:0] count,output reg confirmed
);
 reg [31:0] epoch,generation,last_frame,last_stamp,support_time;
 reg seen,dirty;
 reg [`PD_BITS-1:0] state_packet;
 wire config_same=current_epoch==epoch && current_generation==generation;
 assign in_ready=!dirty && !out_valid && out_ready && config_same && !(count!=0 && !fresh(now_ms,support_time));
 function fresh;
  input [31:0] now_value,stamp;reg [31:0] age;
  begin age=now_value-stamp;fresh=!age[31] && age<TTL_MS;end
 endfunction
 wire [31:0] frame_delta=in_packet[`PD_FRAME]-last_frame;
 wire [31:0] stamp_delta=in_packet[`PD_TIME]-last_stamp;
 wire ordered=!seen || (frame_delta!=0 && !frame_delta[31]);
 wire matching_config=in_packet[`PD_EPOCH]==epoch && in_packet[`PD_GENERATION]==generation;
 wire [11:0] x0={1'b0,in_packet[`PD_X]},x1={1'b0,state_packet[`PD_X]};
 wire [10:0] y0={1'b0,in_packet[`PD_Y]},y1={1'b0,state_packet[`PD_Y]};
 wire [11:0] w0={1'b0,in_packet[`PD_W]},w1={1'b0,state_packet[`PD_W]};
 wire [10:0] h0={1'b0,in_packet[`PD_H]},h1={1'b0,state_packet[`PD_H]};
 wire [11:0] right0=x0+w0,right1=x1+w1;
 wire [10:0] bottom0=y0+h0,bottom1=y1+h1;
 wire box_ok=w0!=0 && h0!=0 && right0<=W && bottom0<=H;
 wire [11:0] left_max=x0>x1?x0:x1,right_min=right0<right1?right0:right1;
 wire [10:0] top_max=y0>y1?y0:y1,bottom_min=bottom0<bottom1?bottom0:bottom1;
 wire [11:0] iw=right_min>left_max?right_min-left_max:12'd0;
 wire [10:0] ih=bottom_min>top_max?bottom_min-top_max:11'd0;
 wire [23:0] area0=w0*h0,area1=w1*h1,intersection=iw*ih;
 wire [12:0] cx0={x0,1'b0}+w0,cx1={x1,1'b0}+w1;
 wire [11:0] cy0={y0,1'b0}+h0,cy1={y1,1'b0}+h1;
 wire [12:0] dx=cx0>cx1?cx0-cx1:cx1-cx0;
 wire [11:0] dy=cy0>cy1?cy0-cy1:cy1-cy0;
 wire same_box=3*intersection>=area0+area1 && dx<=((w0<w1?w0:w1)>>1) && dy<=((h0<h1?h0:h1)>>1);
 reg ids_ok;integer i;reg [6:0] id;
 always @* begin
  ids_ok=1;id=0;
  for(i=0;i<7;i=i+1) begin
   id=in_packet[`PD_IDS_LSB+i*7 +:7];
   if((i==0 && id>=`PD_PROVINCES) || (i==1 && (id<`PD_PROVINCES || id>=`PD_DIGIT_START)) ||
      (i>=2 && (id<`PD_PROVINCES || id>=`PD_CLASSES))) ids_ok=0;
  end
 end
 wire legal=in_packet[`PD_VERSION]==1 && in_packet[`PD_STATUS]==`PD_OK && ids_ok && box_ok &&
            fresh(now_ms,in_packet[`PD_TIME]) && (!seen || !stamp_delta[31]);
 wire same_sequence=count!=0 && same_box && in_packet[`PD_IDS]==state_packet[`PD_IDS] && fresh(in_packet[`PD_TIME],support_time);
 always @(posedge clk or negedge rst_n) begin
  if(!rst_n) begin
   epoch<=0;generation<=0;last_frame<=0;last_stamp<=0;support_time<=0;
   seen<=0;dirty<=1;count<=0;confirmed<=0;state_packet<=0;out_valid<=0;out_packet<=0;
  end else begin
   if(out_valid && out_ready) out_valid<=0;
   if(!out_valid && dirty) begin out_packet<={confirmed,state_packet};out_valid<=1;dirty<=0;end
   if(!config_same) begin
    epoch<=current_epoch;generation<=current_generation;seen<=0;count<=0;confirmed<=0;dirty<=1;
    state_packet<=0;state_packet[`PD_VERSION]<=1;state_packet[`PD_STATUS]<=`PD_CONFIG;
    state_packet[`PD_EPOCH]<=current_epoch;state_packet[`PD_GENERATION]<=current_generation;
   end else if(count!=0 && !fresh(now_ms,support_time)) begin
    count<=0;confirmed<=0;dirty<=1;state_packet[`PD_STATUS]<=`PD_EXPIRED;
   end else if(in_valid && in_ready && matching_config && ordered) begin
    last_frame<=in_packet[`PD_FRAME];seen<=1;
    if(fresh(now_ms,in_packet[`PD_TIME]) && (!seen || !stamp_delta[31])) last_stamp<=in_packet[`PD_TIME];
    state_packet<=in_packet;dirty<=1;
    if(!legal) begin
     count<=0;confirmed<=0;
     if(in_packet[`PD_STATUS]==`PD_OK) state_packet[`PD_STATUS]<=`PD_INVALID;
    end else begin
     support_time<=in_packet[`PD_TIME];
     count<=same_sequence ? (count==3 ? 2'd3 : count+1'b1) : 2'd1;
     confirmed<=same_sequence && count>=2;
    end
   end
  end
 end
endmodule
