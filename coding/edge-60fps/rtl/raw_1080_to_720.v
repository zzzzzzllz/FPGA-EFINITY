// Separable 3:2 area scaling in RGB10; white balance and clipping follow it.
module raw_full_view #(parameter WIDTH=1920, HEIGHT=1080)(
 input clk, rst_n, vs, hs, valid,
 input [39:0] raw4,
 input [1:0] phase,
 input [15:0] gain_r, gain_g, gain_b,
 output out_vs, output reg out_valid,
 output [63:0] rgb2,
 output [31:0] frames, errors,
 output [15:0] measured_width, measured_height,
 output [31:0] sum_r, sum_g, sum_b
);
 wire dv,dsv;
 wire [127:0] pixels;
 wire [31:0] input_errors;
 raw_demosaic4 #(.WIDTH(WIDTH),.HEIGHT(HEIGHT)) demosaic(
  .clk(clk),.rst_n(rst_n),.vs(vs),.hs(hs),.valid(valid),.raw4(raw4),
  .phase(phase),.out_vs(dsv),.out_valid(dv),.rgb4(pixels),
  .frames(frames),.errors(input_errors),.measured_width(measured_width),
  .measured_height(measured_height),.sum_r(sum_r),.sum_g(sum_g),.sum_b(sum_b));

 // Each 1.5-pixel footprint shares the middle input: (2*a+b)/3, (b+2*c)/3.
 function [9:0] mix_channel;
  input [9:0] a,b;
  reg [11:0] weighted;
  reg [23:0] reciprocal;
  begin
   weighted={1'b0,a,1'b0}+{2'b0,b}+12'd1;
   // floor(n*2731/8192) equals floor(n/3) for the full n=0..3070 range.
   reciprocal=weighted*12'd2731;
   mix_channel=reciprocal[22:13];
  end
 endfunction
 function [31:0] mix;
  input [31:0] a,b;
  begin mix={2'd0,mix_channel(a[29:20],b[29:20]),
                 mix_channel(a[19:10],b[19:10]),mix_channel(a[9:0],b[9:0])};end
 endfunction

 localparam AW=$clog2(WIDTH/4);
 reg [127:0] previous_line[0:(1<<AW)-1];
 reg [127:0] previous_q,current_q,vertical_pixels;
 reg [AW-1:0] x=0;
 reg [10:0] y=0;
 reg [1:0] row_phase=0,row_phase_q=0;
 reg read_valid=0,vertical_valid=0,vs_d=0;
 // Synchronous read-before-write stores rows 0 and 1 of each triplet.
 always @(posedge clk) begin
  if(dv && row_phase!=2) previous_line[x]<=pixels;
  previous_q<=previous_line[x];
  current_q<=pixels;
  row_phase_q<=row_phase;
 end
 integer channel;
 always @(posedge clk) begin
  vs_d<=dsv;
  read_valid<=dv && row_phase!=0;
  vertical_valid<=read_valid;
  for(channel=0;channel<4;channel=channel+1)
   vertical_pixels[channel*32+:32]<=row_phase_q==1 ?
    mix(previous_q[channel*32+:32],current_q[channel*32+:32]) :
    mix(current_q[channel*32+:32],previous_q[channel*32+:32]);
  if(!rst_n || dsv!=vs_d) begin
   x<=0;y<=0;row_phase<=0;read_valid<=0;vertical_valid<=0;
  end else if(dv) begin
   if(x==WIDTH/4-1) begin
    x<=0;y<=y+1'b1;row_phase<=row_phase==2?0:row_phase+1'b1;
   end else x<=x+1'b1;
  end
 end

 reg [1:0] column_phase=0;
 reg [63:0] first_pair=0;
 reg [31:0] extra=0,tail=0;
 reg push=0;
 reg [127:0] push_data=0;
 wire [31:0] p0=vertical_pixels[127:96],p1=vertical_pixels[95:64];
 wire [31:0] p2=vertical_pixels[63:32],p3=vertical_pixels[31:0];
 wire full,empty,pop,fifo_valid,pair_valid;
 wire [127:0] fifo_data;
 wire [63:0] scaled_pair;
 reg [31:0] overflow_count=0,frame_errors=0,output_frames=0;
 reg [31:0] output_pixels=0,last_output_pixels=0;
 always @(posedge clk) begin
  push<=0;
  if(!rst_n) begin
   column_phase<=0;first_pair<=0;extra<=0;tail<=0;
   overflow_count<=0;frame_errors<=0;output_frames<=0;
   output_pixels<=0;last_output_pixels<=0;
  end else begin
   if(push && full) overflow_count<=overflow_count+1'b1;
   if(out_valid) output_pixels<=output_pixels+2;
   if(dsv!=vs_d) begin
    column_phase<=0;first_pair<=0;extra<=0;tail<=0;
    if(output_pixels!=0) begin
     output_frames<=output_frames+1'b1;
     last_output_pixels<=output_pixels;
     if(output_pixels!=(WIDTH*2/3)*(HEIGHT*2/3)) frame_errors<=frame_errors+1'b1;
    end
    output_pixels<=0;
   end else if(vertical_valid) begin
    column_phase<=column_phase==2?0:column_phase+1'b1;
    case(column_phase)
     0:begin first_pair<={mix(p0,p1),mix(p2,p1)};tail<=p3;end
     1:begin
      push<=1;push_data<={first_pair,mix(tail,p0),mix(p1,p0)};
      extra<=mix(p2,p3);tail<=p3;
     end
     2:begin push<=1;push_data<={extra,mix(p0,tail),mix(p1,p2),mix(p3,p2)};end
    endcase
   end
  end
 end
 DC_FIFO #(.FIFO_MODE("Normal"),.DATA_WIDTH(128),.FIFO_DEPTH(512)) queue(
  .Reset(!rst_n),.WrClk(clk),.WrEn(push),.WrData(push_data),.WrFull(full),.WrDNum(),
  .RdClk(clk),.RdEn(pop),.RdData(fifo_data),.RdEmpty(empty),.RdDNum(),.DataVal(fifo_valid));
 vid_par2ser #(.I_VID_WIDTH(128),.O_VID_WIDTH(64)) pairs(
  .clk(clk),.rst_n(rst_n),.frame_period(1'b0),.rd_fifo_rdvalid(fifo_valid),
  .rd_fifo_rddata(fifo_data),.rd_fifo_rdempty(empty),.rd_fifo_rden(pop),
  .tx_fifo_valid(pair_valid),.wr_fifo_full(1'b0),.tx_fifo_wrdata(scaled_pair));
 function [7:0] clip;
  input [25:0] product;
  begin clip=(|product[25:18])?8'hff:product[17:10];end
 endfunction
 reg gain_valid=0;
 always @(posedge clk) begin
  if(!rst_n) begin gain_valid<=0;out_valid<=0;end
  else begin gain_valid<=pair_valid;out_valid<=gain_valid;end
 end
 genvar pixel;
 generate for(pixel=0;pixel<2;pixel=pixel+1) begin: gain
  wire [31:0] c=scaled_pair[pixel*32+:32];
  reg [25:0] r,g,b;
  reg [31:0] rgb;
  always @(posedge clk) begin
   r<=c[29:20]*gain_r;g<=c[19:10]*gain_g;b<=c[9:0]*gain_b;
   rgb<={8'd0,clip(r),clip(g),clip(b)};
  end
  assign rgb2[pixel*32+:32]=rgb;
 end endgenerate
 assign out_vs=dsv;
 assign errors=input_errors+overflow_count+frame_errors;
endmodule
