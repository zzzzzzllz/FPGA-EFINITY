`timescale 1ns/1ps
`ifndef QUALITY_DUT
`define QUALITY_DUT raw_full_view
`endif
module tb_quality;
 parameter W=48,H=18,BURST=0,PHASE=0,FRAME_CYCLES=6000,LINE_CYCLES=220;
 localparam N=W*H/4,M=(W*2/3)*(H*2/3);
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,vs=0,hs=0,valid=0;
 reg [39:0] raw4=0;
 reg [39:0] stimulus[0:2*N-1];
 reg [31:0] expected[0:2*M-1];
 reg [31:0] stats[0:5];
 wire ov,ovs;
 wire [63:0] rgb;
 wire [31:0] frames,errors,sr,sg,sb;
 wire [15:0] mw,mh;
 integer x,y,f,k,count=0,cycle=0,start_cycle,line_start,last_output=0,first_output=0;
 integer reconstructed=0,j,site;
 reg [31:0] reconstructed_pixel;
 reg [9:0] measured_component;
 `QUALITY_DUT #(.WIDTH(W),.HEIGHT(H)) dut(
  .clk(clk),.rst_n(rst_n),.vs(vs),.hs(hs),.valid(valid),.raw4(raw4),.phase(2'(PHASE)),
  .gain_r(16'd704),.gain_g(16'd512),.gain_b(16'd758),
  .out_vs(ovs),.out_valid(ov),.rgb2(rgb),.frames(frames),.errors(errors),
  .measured_width(mw),.measured_height(mh),.sum_r(sr),.sum_g(sg),.sum_b(sb));
 always @(posedge clk) cycle=cycle+1;
 always @(negedge clk) if(dut.demosaic.out_valid) begin
  if(reconstructed>=W*H) $fatal(1,"extra reconstructed pixels");
  for(j=0;j<4;j=j+1) begin
   reconstructed_pixel=dut.demosaic.rgb4[(3-j)*32+:32];
   site=((((reconstructed+j)/W)%2)*2+(reconstructed+j)%2)^PHASE;
   case(site)
    0:measured_component=reconstructed_pixel[9:0];
    3:measured_component=reconstructed_pixel[29:20];
    default:measured_component=reconstructed_pixel[19:10];
   endcase
   if(measured_component!==stimulus[f*N+(reconstructed+j)/4][j*10+:10])
    $fatal(1,"CFA sample changed at pixel=%0d phase=%0d",reconstructed+j,PHASE);
  end
  reconstructed=reconstructed+4;
 end
 always @(negedge clk) if(ov) begin
  if(count>=M) $fatal(1,"extra output frame=%0d count=%0d",f,count);
  for(k=0;k<2;k=k+1)
   if(rgb[(1-k)*32+:32]!==expected[f*M+count+k])
    $fatal(1,"frame=%0d pixel=%0d actual=%h expected=%h",f,count+k,rgb[(1-k)*32+:32],expected[f*M+count+k]);
  if(count==0)first_output=cycle;
  count=count+2;last_output=cycle;
 end
 initial begin
  $readmemh("test-work/raw.hex",stimulus);
  $readmemh("test-work/expected.hex",expected);
  $readmemh("test-work/stats.hex",stats);
  repeat(30) @(posedge clk);#1;rst_n=1;
  repeat(100) @(posedge clk);
  for(f=0;f<2;f=f+1) begin
   count=0;reconstructed=0;
   @(posedge clk);#1;vs=1;start_cycle=cycle;
   repeat(40) @(posedge clk);#1;vs=0;
   repeat(40) @(posedge clk);
   for(y=0;y<H;y=y+1) begin
    line_start=cycle;
    for(x=0;x<W/4;x=x+1) begin
     @(posedge clk);#1;hs=1;valid=1;raw4=stimulus[f*N+y*(W/4)+x];
     if(!BURST && x%3!=0)begin @(posedge clk);#1;valid=0;end
    end
    @(posedge clk);#1;valid=0;hs=0;
    while(cycle-line_start<LINE_CYCLES)@(posedge clk);
   end
   // The final reflected row drains through the scaler FIFO in blanking.
   // Keep the same frame deadline rather than assuming a fixed 150-cycle tail.
   while(count<M && cycle-start_cycle<FRAME_CYCLES) @(posedge clk);
   repeat(10) @(posedge clk);#1;
   if(count!=M||reconstructed!=W*H||errors!=0||mw!=W||last_output-start_cycle>=FRAME_CYCLES)
    $fatal(1,"count=%0d errors=%0d width=%0d duration=%0d",count,errors,mw,last_output-start_cycle);
   $display("frame=%0d pixels=%0d first=%0d last=%0d budget=%0d",f,count,first_output-start_cycle,last_output-start_cycle,FRAME_CYCLES);
   while(cycle-start_cycle<FRAME_CYCLES)@(posedge clk);
   #1;vs=1;repeat(20)@(posedge clk);#1;
   if(frames!=f+1||mh!=H||dut.output_frames!=f+1||dut.overflow_count!=0||
      sr!==stats[f*3]||sg!==stats[f*3+1]||sb!==stats[f*3+2])
    $fatal(1,"frame/statistics mismatch: frames=%0d size=%0dx%0d stats=%d/%d/%d",frames,mw,mh,sr,sg,sb);
  end
  $display("PASS: %0dx%0d phase=%0d burst=%0d, two frames, every pixel, RAW stats, FIFO and deadline",W,H,PHASE,BURST);
  $finish;
 end
 initial begin #(FRAME_CYCLES*30);$fatal(1,"timeout");end
endmodule
