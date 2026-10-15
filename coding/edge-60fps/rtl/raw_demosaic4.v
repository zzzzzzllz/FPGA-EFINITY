// Four independent RGB10 pixels from a reflected-border 3x3 Bayer window.
module raw_demosaic4 #(parameter WIDTH=1920, HEIGHT=1080)(
 input clk, rst_n, vs, hs, valid,
 input [39:0] raw4,
 input [1:0] phase,
 output reg out_vs, out_valid,
 output reg [127:0] rgb4,
 output reg [31:0] frames, errors,
 output reg [15:0] measured_width, measured_height,
 output reg [31:0] sum_r, sum_g, sum_b
);
 localparam WORDS=WIDTH/4, AW=$clog2(WORDS);
 reg [39:0] line1[0:WORDS-1],line2[0:WORDS-1];
 reg [AW:0] x;
 reg [15:0] y;
 reg vs_d,hs_d,row_has_data,frame_started;
 wire boundary=vs!=vs_d;
 wire take=frame_started && valid && hs && !boundary && x<WORDS && y<HEIGHT;
 // Replay only the final row during vertical blanking. Reflect H to H-2.
 reg replay;
 reg [AW-1:0] replay_x;
 wire read_enable=take || replay;
 wire [AW-1:0] address=replay?replay_x:x[AW-1:0];
 reg [39:0] upper_q,middle_q,lower_q;
 reg read_valid,write_delay,read_replay;
 reg [AW-1:0] write_x,read_x;
 reg [15:0] read_y;
 reg [1:0] read_phase;
 reg [2:0] vs_pipe;
 always @(posedge clk) begin
  if(take) line1[address]<=raw4;
  if(write_delay) line2[write_x]<=middle_q;
  if(read_enable) begin
   upper_q<=line2[address];middle_q<=line1[address];
   lower_q<=raw4;
  end
 end
 always @(posedge clk) begin
  if(!rst_n) begin
   x<=0;y<=0;vs_d<=0;hs_d<=0;row_has_data<=0;frame_started<=0;
   replay<=0;replay_x<=0;read_valid<=0;write_delay<=0;read_replay<=0;
   read_x<=0;write_x<=0;read_y<=0;read_phase<=0;
   frames<=0;errors<=0;measured_width<=0;measured_height<=0;
   vs_pipe<=0;out_vs<=0;
  end else begin
   vs_d<=vs;hs_d<=hs;vs_pipe<={vs_pipe[1:0],vs};out_vs<=vs_pipe[2];
   read_valid<=read_enable && (replay || y!=0);read_replay<=replay;
   write_delay<=take;write_x<=address;
   read_x<=address;read_y<=replay?HEIGHT-1:y-1'b1;read_phase<=phase;
   if(boundary) begin
    if(y!=0) begin
     frames<=frames+1'b1;measured_height<=y;
     if(y!=HEIGHT || replay) errors<=errors+1'b1;
    end
    x<=0;y<=0;row_has_data<=0;frame_started<=1;
    replay<=0;read_valid<=0;write_delay<=0;
   end else begin
    if(frame_started && valid && hs) begin x<=x+1'b1;row_has_data<=1;end
    if(hs_d && !hs && row_has_data) begin
     measured_width<=x*4;
     if(x!=WORDS) errors<=errors+1'b1;
     if(y==HEIGHT-1) begin replay<=1;replay_x<=0;end
     x<=0;y<=y+1'b1;row_has_data<=0;
    end
    if(replay) begin
     if(replay_x==WORDS-1) replay<=0;
     else replay_x<=replay_x+1'b1;
     if(take) errors<=errors+1'b1;
    end
   end
  end
 end

 // Hold one group until the next group's first pixel supplies its right neighbor.
 wire [39:0] rows[0:2];
 assign rows[0]=read_y==0?lower_q:upper_q;
 assign rows[1]=middle_q;
 assign rows[2]=read_replay?upper_q:lower_q;
 reg [39:0] saved[0:2];
 reg [9:0] left[0:2];
 reg [59:0] window[0:2];
 reg tail,window_valid;
 reg [1:0] tail_phase,window_phase;
 integer row;
 always @(posedge clk) begin
  if(!rst_n || boundary) begin
   tail<=0;window_valid<=0;tail_phase<=0;window_phase<=0;
  end else begin
   window_valid<=0;
   if(tail) begin
    for(row=0;row<3;row=row+1)
     window[row]<={saved[row][29:20],saved[row],left[row]};
    window_phase<=tail_phase;window_valid<=1;tail<=0;
   end else if(read_valid) begin
    for(row=0;row<3;row=row+1) begin
     saved[row]<=rows[row];
     left[row]<=read_x==0?rows[row][19:10]:saved[row][39:30];
     window[row]<={rows[row][9:0],saved[row],left[row]};
    end
    window_phase<=read_phase ^ {read_y[0],1'b0};
    window_valid<=read_x!=0;
    if(read_x==WORDS-1) begin
     tail<=1;tail_phase<=read_phase ^ {read_y[0],1'b0};
    end
   end
  end
 end

 function [29:0] bilinear;
  input [29:0] top,mid,bot;
  input [1:0] color;
  reg [11:0] cross_sum,diagonal;
  reg [10:0] horizontal,vertical;
  reg [9:0] r,g,b,center;
  begin
   center=mid[19:10];
   horizontal={1'b0,mid[9:0]}+mid[29:20]+11'd1;
   vertical={1'b0,top[19:10]}+bot[19:10]+11'd1;
   cross_sum={2'b0,mid[9:0]}+mid[29:20]+top[19:10]+bot[19:10]+12'd2;
   diagonal={2'b0,top[9:0]}+top[29:20]+bot[9:0]+bot[29:20]+12'd2;
   case(color)
    0:begin b=center;g=cross_sum[11:2];r=diagonal[11:2];end
    1:begin g=center;b=horizontal[10:1];r=vertical[10:1];end
    2:begin g=center;r=horizontal[10:1];b=vertical[10:1];end
    3:begin r=center;g=cross_sum[11:2];b=diagonal[11:2];end
   endcase
   bilinear={r,g,b};
  end
 endfunction
 wire [29:0] colors[0:3];
 genvar k;
 generate for(k=0;k<4;k=k+1) begin: pixel
  localparam [1:0] COLUMN_PHASE=k%2;
  assign colors[k]=bilinear(window[0][k*10+:30],window[1][k*10+:30],
                           window[2][k*10+:30],window_phase ^ COLUMN_PHASE);
  always @(posedge clk) rgb4[(3-k)*32+:32]<={2'd0,colors[k]};
 end endgenerate
 reg [31:0] accum_r,accum_g,accum_b;
 always @(posedge clk) begin
  if(!rst_n) begin
   out_valid<=0;accum_r<=0;accum_g<=0;accum_b<=0;
   sum_r<=0;sum_g<=0;sum_b<=0;
  end else if(boundary) begin
   out_valid<=0;
   if(y!=0) begin sum_r<=accum_r;sum_g<=accum_g;sum_b<=accum_b;end
   accum_r<=0;accum_g<=0;accum_b<=0;
  end else begin
   out_valid<=window_valid;
   if(window_valid) begin
    accum_r<=accum_r+colors[0][29:20]+colors[1][29:20]+colors[2][29:20]+colors[3][29:20];
    accum_g<=accum_g+colors[0][19:10]+colors[1][19:10]+colors[2][19:10]+colors[3][19:10];
    accum_b<=accum_b+colors[0][9:0]+colors[1][9:0]+colors[2][9:0]+colors[3][9:0];
   end
  end
 end
endmodule
