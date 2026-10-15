// RAW10 -> integer edge-aware RGB10 -> rounded 2x2 area -> existing WB/RGB8.
// Four RAW pixels in, two RGB pixels out. No DDR or downstream changes.
module raw_full_view #(parameter WIDTH=2560, HEIGHT=1440)(
 input clk,rst_n,vs,hs,valid,
 input [39:0] raw4,
 input [1:0] phase,
 input [15:0] gain_r,gain_g,gain_b,
 output reg out_vs,out_valid,
 output reg [63:0] rgb2,
 output wire [31:0] frames,errors,
 output reg [15:0] measured_width,measured_height,
 output wire [31:0] sum_r,sum_g,sum_b
);
 localparam WORDS=WIDTH/4, AW=$clog2(WORDS);
 reg [39:0] line1[0:WORDS-1],line2[0:WORDS-1];
 wire [AW:0] x;
 wire [15:0] y;
 wire [47:0] position[0:1];
 wire line_end=hs_d && !hs && row_has_data;
 wire [1:0] position_enable={line_end,valid && hs};
 wire [1:0] position_reset={!rst_n || boundary,!rst_n || boundary || line_end};
 genvar axis;
 generate for(axis=0;axis<2;axis=axis+1) begin: input_position
  EFX_DSP48 #(.SIGNED(0),.M_SEL("C"),.N_SEL("W"),.W_REG(1),.RST_SYNC(1)) acc(
   .A(19'd0),.B(18'd0),.C(18'd1),.CASCIN(48'd0),.OP(2'd0),
   .SHIFT_ENA(1'b0),.CLK(clk),.CE(position_enable[axis]),.RST(position_reset[axis]),
   .O(position[axis]),.CASCOUT(),.OVFL());
 end endgenerate
 assign x=position[0][AW:0];assign y=position[1][15:0];
 reg vs_d,hs_d,row_has_data;
 wire boundary=vs!=vs_d;
 wire take=valid && hs && !boundary && x<WORDS && y<HEIGHT;
 reg [11:0] vs_pipe,end_pipe;
 reg [15:0] end_height;
 reg area_valid,gain_valid;
 wire [47:0] accum_dsp[0:2];
 wire [31:0] accum_r=accum_dsp[0][31:0],accum_g=accum_dsp[1][31:0],accum_b=accum_dsp[2][31:0];
 wire [10:0] pair_r={1'b0,c0[29:20]}+c1[29:20];
 wire [10:0] pair_g={1'b0,c0[19:10]}+c1[19:10];
 wire [10:0] stat_b={1'b0,c0[9:0]}+c1[9:0];
 wire [10:0] pair_sum[0:2];
 assign pair_sum[0]=pair_r;assign pair_sum[1]=pair_g;assign pair_sum[2]=stat_b;
 genvar ch;
 generate for(ch=0;ch<3;ch=ch+1) begin: statistics
  EFX_DSP48 #(.SIGNED(0),.M_SEL("C"),.N_SEL("W"),.W_REG(1),.RST_SYNC(1)) acc(
   .A(19'd0),.B(18'd0),.C({7'd0,pair_sum[ch]}),.CASCIN(48'd0),.OP(2'd0),
   .SHIFT_ENA(1'b0),.CLK(clk),.CE(area_valid),.RST(!rst_n || end_pipe[11]),
   .O(accum_dsp[ch]),.CASCOUT(),.OVFL());
 end endgenerate

 wire bad_line=!boundary && hs_d && !hs && row_has_data && x!=WORDS;
 wire bad_frame=boundary && y!=0 && y!=HEIGHT;
 wire [47:0] counter[0:1];
 wire [1:0] count_enable={bad_line || bad_frame,end_pipe[11]};
 generate for(ch=0;ch<2;ch=ch+1) begin: status_counter
  EFX_DSP48 #(.SIGNED(0),.M_SEL("C"),.N_SEL("W"),.W_REG(1),.RST_SYNC(1)) acc(
   .A(19'd0),.B(18'd0),.C(18'd1),.CASCIN(48'd0),.OP(2'd0),
   .SHIFT_ENA(1'b0),.CLK(clk),.CE(count_enable[ch]),.RST(!rst_n),
   .O(counter[ch]),.CASCOUT(),.OVFL());
 end endgenerate
 assign frames=counter[0][31:0];assign errors=counter[1][31:0];
 ea_regs #(96) published_sums(clk,end_pipe[11],!rst_n,{accum_r,accum_g,accum_b},{sum_r,sum_g,sum_b});

 reg v1,v2,v3;
 wire [AW-1:0] x1,x2,x3;
 wire [15:0] y1,y2,y3;
 wire [1:0] ph1,ph2,ph3;
 reg [39:0] l1q,l2q;
 wire [39:0] raw1,raw2,raw3,prev1_2,prev1_3,prev2_3;
 ea_regs #(40+AW+18) row1_regs(clk,take,1'b0,{raw4,x[AW-1:0],y,phase},{raw1,x1,y1,ph1});
 ea_regs #(80+AW+18) row2_regs(clk,v1,1'b0,{l1q,raw1,x1,y1,ph1},{prev1_2,raw2,x2,y2,ph2});
 ea_regs #(120+AW+18) row3_regs(clk,v2,1'b0,{l2q,prev1_2,raw2,x2,y2,ph2},{prev2_3,prev1_3,raw3,x3,y3,ph3});
 // Each RAM has one synchronous read and one write; no array reset.
 always @(posedge clk) begin
  if(take) begin
   l1q<=line1[x[AW-1:0]]; line1[x[AW-1:0]]<=raw4;

  end
  if(v1) begin
   l2q<=line2[x1];line2[x1]<=l1q;

  end

 end

 wire [39:0] saved[0:2];
 wire [9:0] left[0:2];
 wire [39:0] rows[0:2];
 assign rows[0]=prev2_3;assign rows[1]=prev1_3;assign rows[2]=raw3;
 wire [59:0] win[0:2];
 reg tail,tail_border,tail_emit;
 reg window_emit,cb_emit;
 reg [AW-1:0] window_x,cb_x;
 reg [1:0] tail_phase;
 reg window_valid,left_border,right_border,vertical_border;
 reg [1:0] window_phase;
 reg [15:0] frame_r,frame_g,frame_b;

 wire eligible=v3 && y3>=2;
 wire [149:0] saved_in,saved_out;
 wire [179:0] win_in,win_out;
 genvar row;
 generate for(row=0;row<3;row=row+1) begin: window_data
  assign saved_in[row*50+:50]={rows[row],x3==0?10'd0:saved[row][39:30]};
  assign {saved[row],left[row]}=saved_out[row*50+:50];
  assign win_in[row*60+:60]={tail?10'd0:rows[row][9:0],saved[row],left[row]};
  assign win[row]=win_out[row*60+:60];
 end endgenerate
 ea_regs #(150) saved_regs(clk,rst_n && eligible && !tail,1'b0,saved_in,saved_out);
 ea_regs #(180) window_regs(clk,rst_n && (eligible || tail),1'b0,win_in,win_out);
 always @(posedge clk) begin
  if(!rst_n) begin
   tail<=0;window_valid<=0;left_border<=0;right_border<=0;vertical_border<=0;
   window_phase<=0;frame_r<=0;frame_g<=0;frame_b<=0;
  end else begin
   window_valid<=0;
   if(tail) begin
    window_valid<=1;left_border<=0;right_border<=1;
    vertical_border<=tail_border;window_phase<=tail_phase;tail<=0;window_emit<=tail_emit;window_x<=WORDS-1;
   end else if(eligible) begin
    window_valid<=x3!=0;left_border<=x3==1;right_border<=0;
    vertical_border<=y3==2 || y3==HEIGHT-1;
    window_phase<=ph3 ^ {~y3[0],1'b0};
    window_emit<=!y3[0] || y3==HEIGHT-1;window_x<=x3-1'b1;
    if(x3==0 && y3==2) begin frame_r<=gain_r;frame_g<=gain_g;frame_b<=gain_b;end
    if(x3==WORDS-1) begin
     tail<=1;tail_border<=y3==2 || y3==HEIGHT-1;tail_phase<=ph3 ^ {~y3[0],1'b0};tail_emit<=!y3[0] || y3==HEIGHT-1;
    end
   end
  end
 end

 wire mirror=window_phase[0]^window_phase[1];
 wire [59:0] norm[0:2];
 wire [29:0] colors[0:3],color_next[0:3];
 reg color_valid,cb_left,cb_right,cb_vertical,cb_mirror,cb_swap;
 wire [11:0] a[0:11],b[0:11],o[0:11];
 wire [10:0] ps[0:11];
 genvar rr,cc,k;
 generate for(rr=0;rr<3;rr=rr+1) begin: normalize_row
  for(cc=0;cc<6;cc=cc+1) begin: normalize_column
   assign norm[rr][cc*10+:10]=mirror?win[rr][(5-cc)*10+:10]:win[rr][cc*10+:10];
  end
 end
 for(cc=0;cc<4;cc=cc+1) begin: neighbors
  assign a[cc]={1'b0,norm[1][cc*10+:10],1'b1};assign b[cc]={1'b0,norm[1][(cc+2)*10+:10],1'b1};
  assign a[4+cc]={1'b0,norm[0][(cc+1)*10+:10],1'b1};assign b[4+cc]={1'b0,norm[2][(cc+1)*10+:10],1'b1};
  assign a[8+cc]={1'b0,norm[(cc%2)*2][(cc/2)*20+:10],1'b1};
  assign b[8+cc]={1'b0,norm[(cc%2)*2][(cc/2)*20+20+:10],1'b1};
 end
 for(k=0;k<3;k=k+1) begin: neighbor_sums
  ea_add4 add(.a({a[k*4+3],a[k*4+2],a[k*4+1],a[k*4]}),
   .b({b[k*4+3],b[k*4+2],b[k*4+1],b[k*4]}),.o({o[k*4+3],o[k*4+2],o[k*4+1],o[k*4]}));
 end
 for(k=0;k<12;k=k+1) begin: pair_sums
  assign ps[k]=o[k][11:1];
 end endgenerate
 wire [47:0] diag;
 ea_add4 diagonal(.a({24'd0,1'b0,ps[10],1'b0,ps[8]}),.b({24'd0,1'b0,ps[11],1'b0,ps[9]}),.o(diag));
 generate for(cc=0;cc<4;cc=cc+1) begin: decode
  wire [9:0] ha=ps[cc][10:1],va=ps[4+cc][10:1],center=norm[1][(cc+1)*10+:10];
  if(cc%2==0) begin: chromatic
   wire [9:0] l=norm[1][cc*10+:10],r=norm[1][(cc+2)*10+:10];
   wire [9:0] u=norm[0][(cc+1)*10+:10],d=norm[2][(cc+1)*10+:10];
   wire signed [10:0] sh,sv;
   ea_difference horizontal(l,r,sh);ea_difference vertical(u,d,sv);
   wire [9:0] dh=sh[10]?-sh:sh,dv=sv[10]?-sv:sv;
   wire [9:0] green=dh>dv?va:ha;
   assign color_next[cc]={diag[(cc/2)*12+2+:10],green,center};
  end else begin: green
   assign color_next[cc]={va,center,ha};
  end
 end endgenerate
 ea_regs #(120) color_regs(clk,1'b1,1'b0,{color_next[3],color_next[2],color_next[1],color_next[0]},
  {colors[3],colors[2],colors[1],colors[0]});

 // Each cycle reconstructs one row. Keep the horizontal sums from
 // the preceding even row in RAM; combine them on the following odd row.
 // The +1 in each horizontal sum supplies the final +2 rounding exactly.
 wire [29:0] color0=cb_left?colors[1]:colors[0];
 wire [29:0] color3=cb_right?colors[2]:colors[3];
 wire [29:0] ha0[0:1],hb0[0:1];
 assign ha0[0]=color0;assign hb0[0]=colors[1];assign ha0[1]=colors[2];assign hb0[1]=color3;
 wire [11:0] pa[0:7],pb[0:7],po[0:7];
 generate for(k=0;k<8;k=k+1) begin: horizontal_inputs
  if(k<6) begin: used
   assign pa[k]={1'b0,ha0[k/3][(k%3)*10+:10],1'b1};
   assign pb[k]={1'b0,hb0[k/3][(k%3)*10+:10],1'b1};
  end else begin: unused
   assign pa[k]=0;assign pb[k]=0;
  end
 end
 for(k=0;k<2;k=k+1) begin: horizontal_sums
  ea_add4 add(.a({pa[k*4+3],pa[k*4+2],pa[k*4+1],pa[k*4]}),
   .b({pb[k*4+3],pb[k*4+2],pb[k*4+1],pb[k*4]}),.o({po[k*4+3],po[k*4+2],po[k*4+1],po[k*4]}));
 end endgenerate
 wire [32:0] h0={po[2][11:1],po[1][11:1],po[0][11:1]};
 wire [32:0] h1={po[5][11:1],po[4][11:1],po[3][11:1]};
 wire [32:0] ordered0=cb_mirror?h1:h0,ordered1=cb_mirror?h0:h1;
 wire [32:0] part0=cb_swap?{ordered0[10:0],ordered0[21:11],ordered0[32:22]}:ordered0;
 wire [32:0] part1=cb_swap?{ordered1[10:0],ordered1[21:11],ordered1[32:22]}:ordered1;
 reg [65:0] partial_row[0:WORDS-1];
 reg [65:0] previous_pair;
 always @(posedge clk) begin
  if(window_valid) previous_pair<=partial_row[window_x];
  if(color_valid && !cb_emit) partial_row[cb_x]<={part0,part1};
 end
 wire [65:0] previous=cb_vertical?{part0,part1}:previous_pair;
 wire [65:0] partials={part0,part1};
 wire [11:0] va0[0:7],vb0[0:7],vo0[0:7];
 generate for(k=0;k<8;k=k+1) begin: vertical_inputs
  if(k<6) begin: used
   assign va0[k]={1'b0,partials[k*11+:11]};assign vb0[k]={1'b0,previous[k*11+:11]};
  end else begin: unused
   assign va0[k]=0;assign vb0[k]=0;
  end
 end
 for(k=0;k<2;k=k+1) begin: vertical_sums
  ea_add4 add(.a({va0[k*4+3],va0[k*4+2],va0[k*4+1],va0[k*4]}),
   .b({vb0[k*4+3],vb0[k*4+2],vb0[k*4+1],vb0[k*4]}),.o({vo0[k*4+3],vo0[k*4+2],vo0[k*4+1],vo0[k*4]}));
 end endgenerate
 reg [29:0] c0,c1;

 reg [25:0] r0,g0,b0,r1,g1,b1;
 function [7:0] clip;
  input [25:0] product;
  begin clip=(|product[25:18])?8'hff:product[17:10];end
 endfunction
 always @(posedge clk) begin
  color_valid<=window_valid;cb_left<=mirror?right_border:left_border;
  cb_right<=mirror?left_border:right_border;cb_vertical<=vertical_border;
  cb_mirror<=mirror;cb_swap<=window_phase[1];cb_emit<=window_emit;cb_x<=window_x;
  c0<={vo0[5][11:2],vo0[4][11:2],vo0[3][11:2]};
  c1<={vo0[2][11:2],vo0[1][11:2],vo0[0][11:2]};
  area_valid<=color_valid && cb_emit;gain_valid<=area_valid;out_valid<=gain_valid;
  r0<=c0[29:20]*frame_r;g0<=c0[19:10]*frame_g;b0<=c0[9:0]*frame_b;
  r1<=c1[29:20]*frame_r;g1<=c1[19:10]*frame_g;b1<=c1[9:0]*frame_b;
  rgb2<={8'd0,clip(r0),clip(g0),clip(b0),8'd0,clip(r1),clip(g1),clip(b1)};
  if(!rst_n) begin color_valid<=0;area_valid<=0;gain_valid<=0;out_valid<=0;rgb2<=0;end
 end

 always @(posedge clk) begin
  if(!rst_n) begin
   vs_d<=0;hs_d<=0;row_has_data<=0;v1<=0;v2<=0;v3<=0;
   vs_pipe<=0;end_pipe<=0;out_vs<=0;end_height<=0;
   measured_width<=0;measured_height<=0;
  end else begin
   vs_d<=vs;hs_d<=hs;v1<=take;v2<=v1;v3<=v2;
   vs_pipe<={vs_pipe[10:0],vs};out_vs<=vs_pipe[11];
   end_pipe<={end_pipe[10:0],boundary && y!=0};
   if(boundary) begin
    if(y!=0) end_height<=y;
    row_has_data<=0;
   end else begin
    if(valid && hs) row_has_data<=1;
    if(hs_d && !hs && row_has_data) begin
     measured_width<=x*4;
     row_has_data<=0;
    end
   end
   if(end_pipe[11]) begin
    measured_height<=end_height;

   end
  end
 end
endmodule

module ea_regs #(parameter WIDTH=48)(input clk,ce,rst,input [WIDTH-1:0] d,output [WIDTH-1:0] q);
 localparam N=(WIDTH+35)/36;
 wire [N*36-1:0] padded={{(N*36-WIDTH){1'b0}},d};
 wire [N*36-1:0] result;
 assign q=result[WIDTH-1:0];
 genvar n;
 generate for(n=0;n<N;n=n+1) begin: words
  ea_reg36 reg36(clk,ce,rst,padded[n*36+:36],result[n*36+:36]);
 end endgenerate
endmodule

// Independent additions use the normal multiplier-by-one and C adder inputs.
module ea_add4(input [47:0] a,b,output [47:0] o);
 genvar i;
 generate for(i=0;i<4;i=i+1) begin: lane
  wire [47:0] result;
  EFX_DSP48 #(.SIGNED(0),.M_SEL("P"),.N_SEL("C")) add(
   .A({7'd0,a[i*12+:12]}),.B(18'd1),.C({6'd0,b[i*12+:12]}),
   .CASCIN(48'd0),.OP(2'd0),.SHIFT_ENA(1'b0),.CLK(1'b0),.CE(1'b0),.RST(1'b0),.O(result),.CASCOUT(),.OVFL());
  assign o[i*12+:12]=result[11:0];
 end endgenerate
endmodule

// A*2^17+C concatenates 19 and 17 input bits without overlap or carry.
module ea_reg36(input clk,ce,rst,input [35:0] d,output [35:0] q);
 wire [47:0] result;
 EFX_DSP48 #(.SIGNED(0),.A_REG(1),.C_REG(1),.RST_SYNC(1),.M_SEL("P"),.N_SEL("C")) data_register(
  .A(d[35:17]),.B(18'h20000),.C({1'b0,d[16:0]}),
  .CASCIN(48'd0),.OP(2'd0),.SHIFT_ENA(1'b0),.CLK(clk),.CE(ce),.RST(rst),.O(result),.CASCOUT(),.OVFL());
 assign q=result[35:0];
endmodule

module ea_difference(input [9:0] a,b,output [10:0] d);
 wire [47:0] result;
 EFX_DSP48 #(.SIGNED(0),.M_SEL("P"),.N_SEL("C")) difference(
  .A({9'd0,a}),.B(18'd1),.C({8'd0,b}),.CASCIN(48'd0),.OP(2'd1),
  .SHIFT_ENA(1'b0),.CLK(1'b0),.CE(1'b0),.RST(1'b0),.O(result),.CASCOUT(),.OVFL());
 assign d=result[10:0];
endmodule
