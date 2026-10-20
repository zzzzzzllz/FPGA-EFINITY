`timescale 1ns/1ps
// Raw binary ROI -> one normalization -> frozen 320-feature contract.
module char_preprocess (
 input wire clk,rst,
 input wire start_valid,output wire start_ready,
 input wire [8:0] width,input wire [6:0] height,
 input wire pixel_valid,output wire pixel_ready,input wire pixel_data,pixel_last,
 output wire norm_valid,input wire norm_ready,output wire norm_data,
 output wire [9:0] norm_index,
 output wire feature_valid,input wire feature_ready,
 output reg [5:0] feature_data,output reg [8:0] feature_index,
 output wire done_valid,input wire done_ready,output reg [2:0] error
);
 localparam IDLE=0,LOAD=1,BOUNDS=2,DIVIDE=3,LAYOUT=4,FETCH=5,EMIT=6,
            X_STEP=7,Y_STEP=8,F_READ=9,F_SUM=10,F_EMIT=11,DONE=12;
 reg [3:0] state;
 (* syn_ramstyle="block_ram" *) reg raw_mem[0:32767];
 (* syn_ramstyle="block_ram" *) reg norm_mem[0:1023];
 reg raw_q,norm_q;
 reg [8:0] w,x,min_x,max_x,bw,source_x;
 reg [6:0] h,y,min_y,max_y,bh;
 reg [14:0] write_address,row_base,bbox_row_base,source_row;
 reg [2:0] foreground;
 reg [13:0] numerator;
 reg [8:0] denominator;
 reg [5:0] quotient,nw,nh;
 reg wide;
 reg [4:0] nx,ny,ox,oy;
 reg [8:0] x_remainder,y_remainder;
 reg [5:0] sample,accumulator;
 wire active_y=({1'b0,ny}>={1'b0,oy}) && ({1'b0,ny}<{1'b0,oy}+nh);
 wire active=active_y && ({1'b0,nx}>={1'b0,ox}) && ({1'b0,nx}<{1'b0,ox}+nw);
 wire expected_last=x==w-1'b1 && y==h-1'b1;
 wire [8:0] bbox_w=max_x-min_x+1'b1;
 wire [6:0] bbox_h=max_y-min_y+1'b1;
 wire [9:0] feature_address=feature_index<256 ?
     {feature_index[7:4],sample[1],feature_index[3:0],sample[0]} :
     feature_index<288 ? {sample[4:0],feature_index[4:0]} :
                         {feature_index[4:0],sample[4:0]};
 wire sample_last=feature_index<256 ? sample==3 : sample==31;
 wire [5:0] sum_next=accumulator+{5'd0,norm_q};
 assign start_ready=state==IDLE && !rst;
 assign pixel_ready=state==LOAD && !rst;
 assign norm_valid=state==EMIT && !rst;
 assign norm_data=active ? raw_q : 1'b0;
 assign norm_index={ny,nx};
 assign feature_valid=state==F_EMIT && !rst;
 assign done_valid=state==DONE && !rst;

 // No RAM reset. Valid requests fully overwrite every location they later read.
 always @(posedge clk) begin
  if(pixel_valid && pixel_ready) raw_mem[write_address]<=pixel_data;
  if(state==FETCH && active && !rst) raw_q<=raw_mem[source_row+source_x];
  if(norm_valid && norm_ready) norm_mem[norm_index]<=norm_data;
  if(state==F_READ && !rst) norm_q<=norm_mem[feature_address];
 end

 always @(posedge clk) begin
  if(rst) begin
   state<=IDLE;error<=0;feature_data<=0;feature_index<=0;
   w<=0;h<=0;x<=0;y<=0;min_x<=0;max_x<=0;min_y<=0;max_y<=0;
   bw<=0;bh<=0;foreground<=0;write_address<=0;row_base<=0;bbox_row_base<=0;
   source_row<=0;source_x<=0;numerator<=0;denominator<=0;quotient<=0;wide<=0;
   nw<=0;nh<=0;nx<=0;ny<=0;ox<=0;oy<=0;x_remainder<=0;y_remainder<=0;
   sample<=0;accumulator<=0;
  end else case(state)
   IDLE: if(start_valid) begin
    error<=0;w<=width;h<=height;x<=0;y<=0;write_address<=0;row_base<=0;
    min_x<=511;max_x<=0;min_y<=127;max_y<=0;foreground<=0;bbox_row_base<=0;
    feature_index<=0;feature_data<=0;
    if(width==0 || width>320 || height==0 || height>96) begin error<=1;state<=DONE;end
    else state<=LOAD;
   end
   LOAD: if(pixel_valid) begin
    if(pixel_data) begin
     if(foreground<4) foreground<=foreground+1'b1;
     if(foreground==0) bbox_row_base<=row_base;
     if(x<min_x) min_x<=x;
     if(x>max_x) max_x<=x;
     if(y<min_y) min_y<=y;
     if(y>max_y) max_y<=y;
    end
    if(pixel_last!=expected_last) begin error<=3;state<=DONE;end
    else if(expected_last) state<=BOUNDS;
    else begin
     write_address<=write_address+1'b1;
     if(x==w-1'b1) begin x<=0;y<=y+1'b1;row_base<=row_base+w;end
     else x<=x+1'b1;
    end
   end
   BOUNDS: begin
    if(foreground<4) begin error<=2;state<=DONE;end
    else begin
     bw<=bbox_w;bh<=bbox_h;source_row<=bbox_row_base+min_x;
     wide<=bbox_w>={2'd0,bbox_h};quotient<=0;
     if(bbox_w>={2'd0,bbox_h}) begin
      numerator<=({7'd0,bbox_h}<<5)-({7'd0,bbox_h}<<2)+{5'd0,(bbox_w>>1)};
      denominator<=bbox_w;nw<=28;
     end else begin
      numerator<=({5'd0,bbox_w}<<5)-({5'd0,bbox_w}<<2)+{7'd0,(bbox_h>>1)};
      denominator<={2'd0,bbox_h};nh<=28;
     end
     state<=DIVIDE;
    end
   end
   DIVIDE: if(numerator>={5'd0,denominator}) begin
    numerator<=numerator-{5'd0,denominator};quotient<=quotient+1'b1;
   end else begin
    if(wide) nh<=quotient==0 ? 6'd1 : quotient;
    else nw<=quotient==0 ? 6'd1 : quotient;
    state<=LAYOUT;
   end
   LAYOUT: begin
    ox<=(6'd32-nw)>>1;oy<=(6'd32-nh)>>1;nx<=0;ny<=0;
    source_x<=0;x_remainder<=0;y_remainder<=0;state<=FETCH;
   end
   FETCH: state<=EMIT;
   EMIT: if(norm_ready) begin
    if(nx==31) begin
     nx<=0;source_x<=0;x_remainder<=0;
     if(ny==31) begin
      feature_index<=0;sample<=0;accumulator<=0;state<=F_READ;
     end else begin
      ny<=ny+1'b1;
      if(active_y) begin y_remainder<=y_remainder+{2'd0,bh};state<=Y_STEP;end
      else state<=FETCH;
     end
    end else begin
     nx<=nx+1'b1;
     if(active) begin x_remainder<=x_remainder+bw;state<=X_STEP;end
     else state<=FETCH;
    end
   end
   X_STEP: if(x_remainder>={3'd0,nw}) begin
    x_remainder<=x_remainder-{3'd0,nw};source_x<=source_x+1'b1;
   end else state<=FETCH;
   Y_STEP: if(y_remainder>={3'd0,nh}) begin
    y_remainder<=y_remainder-{3'd0,nh};source_row<=source_row+w;
   end else state<=FETCH;
   F_READ: state<=F_SUM;
   F_SUM: begin
    if(sample_last) begin
     feature_data<=feature_index<256 ? {sum_next[2:0],3'b000} : sum_next;
     state<=F_EMIT;
    end else begin accumulator<=sum_next;sample<=sample+1'b1;state<=F_READ;end
   end
   F_EMIT: if(feature_ready) begin
    if(feature_index==319) state<=DONE;
    else begin feature_index<=feature_index+1'b1;sample<=0;accumulator<=0;state<=F_READ;end
   end
   DONE: if(done_ready) state<=IDLE;
   default: begin error<=4;state<=DONE;end
  endcase
 end
endmodule
