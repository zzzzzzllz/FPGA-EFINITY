`timescale 1ns/1ps
module tb_edgeaware_area;
 parameter W=16,H=8;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,vs=0,hs=0,valid=0;
 reg [39:0] raw4=0;
 reg [1:0] phase=0;
 reg [15:0] gr=389,gg=256,gb=427;
 wire ov,ovsync;wire [63:0] rgb;
 wire [31:0] frames,errors,sr,sg,sb;wire [15:0] mw,mh;
 raw_full_view #(.WIDTH(W),.HEIGHT(H)) dut(clk,rst_n,vs,hs,valid,raw4,phase,gr,gg,gb,
  ovsync,ov,rgb,frames,errors,mw,mh,sr,sg,sb);
`ifdef EA_CYCLE_REFERENCE
 wire ref_vs,ref_valid;
 wire [63:0] ref_rgb;
 wire [31:0] ref_frames,ref_errors,ref_r,ref_g,ref_b;
 wire [15:0] ref_width,ref_height;
 raw_full_view_reference #(.WIDTH(W),.HEIGHT(H)) ref_dut(clk,rst_n,vs,hs,valid,raw4,phase,gr,gg,gb,
  ref_vs,ref_valid,ref_rgb,ref_frames,ref_errors,ref_width,ref_height,ref_r,ref_g,ref_b);
 always @(negedge clk) if(rst_n) begin
  if({ovsync,ov,frames,errors,mw,mh,sr,sg,sb}!=={ref_vs,ref_valid,ref_frames,ref_errors,ref_width,ref_height,ref_r,ref_g,ref_b})
   $fatal(1,"cycle mismatch in validity, sync, counters or RAW sums");
  if(ov && rgb!==ref_rgb) $fatal(1,"cycle mismatch in RGB output");
 end
`endif
 reg [39:0] source[0:W*H/4-1];
 reg [63:0] expected[0:W*H/8-1];
 reg [31:0] sums[0:2];
 integer count=0,gcount=0,x,y,k,run,phase_arg,gain_arg,gap_arg,unused;
 reg [1023:0] directory;
 reg previous_vs=0;
 reg checking=0;
 reg [19:0] pair_index=0;
 reg [15:0] pair_x=0;
 wire gv,gs,gl,ge;wire [63:0] gp;wire [31:0] gid,epoch;
 always @(posedge clk) begin
  previous_vs<=ovsync;
  if(!rst_n || previous_vs!=ovsync) begin pair_index<=0;pair_x<=0;end
  else if(ov) begin pair_index<=pair_index+1;pair_x<=pair_x==W/4-1?0:pair_x+1;end
 end
 rgb_to_gray gray(.clk(clk),.rst_n(rst_n),.in_valid(ov),.in_ready(),.in_rgb(rgb),
  .in_sof(pair_index==0),.in_eol(pair_x==W/4-1),.in_eof(pair_index==W*H/8-1),
  .in_frame_id(frames+32'd1),.in_epoch(32'd1),.out_valid(gv),.out_ready(1'b1),
  .out_rgby(gp),.out_sof(gs),.out_eol(gl),.out_eof(ge),.out_frame_id(gid),.out_epoch(epoch));
 always @(negedge clk) begin
  if(checking && ov) begin
   if(count>=W*H/8) $fatal(1,"extra output");
   if(rgb!==expected[count]) $fatal(1,"frame %0d pair %0d got %h expected %h",run,count,rgb,expected[count]);
   count=count+1;
  end
  if(checking && gv) begin
   if(gid!=run+1 || gs!==(gcount==0) || gl!==(gcount%(W/4)==W/4-1) || ge!==(gcount==W*H/8-1))
    $fatal(1,"gray metadata frame=%0d id=%0d pair=%0d flags %b%b%b",run,gid,gcount,gs,gl,ge);
   if({gp[55:32],gp[23:0]}!=={expected[gcount][55:32],expected[gcount][23:0]}) $fatal(1,"gray RGB changed");
   gcount=gcount+1;
  end
 end
 initial begin
  if(!$value$plusargs("DIR=%s",directory)) $fatal(1,"DIR required");
  unused=$value$plusargs("PHASE=%d",phase_arg);phase=phase_arg;
  unused=$value$plusargs("GAIN=%d",gain_arg);
  unused=$value$plusargs("GAPS=%d",gap_arg);
  if(gain_arg==1) begin gr=256;gg=256;gb=256;end
  if(gain_arg==2) begin gr=65535;gg=0;gb=1024;end
  $readmemh({directory,"/raw.hex"},source);$readmemh({directory,"/rgb.hex"},expected);
  $readmemh({directory,"/sums.hex"},sums);
  repeat(4) @(negedge clk);rst_n=1;
`ifdef EA_CYCLE_REFERENCE
  // Exercise an incomplete row and frame, then reset before normal frames.
  @(negedge clk);hs=1;valid=1;raw4=40'hffffffffff;
  @(negedge clk);valid=0;
  @(negedge clk);hs=0;
  repeat(3) @(negedge clk);
  if(errors!=1) $fatal(1,"short row was not reported");
  vs=1;
  repeat(16) @(negedge clk);
  if(errors!=2 || frames!=1) $fatal(1,"short frame was not reported");
  rst_n=0;
  repeat(4) @(negedge clk);
  vs=0;hs=0;valid=0;raw4=0;
  repeat(4) @(negedge clk);
  rst_n=1;
`endif
  checking=1;
  for(run=0;run<3;run=run+1) begin
   count=0;gcount=0;
   if(run==0 || run==2) begin
    @(negedge clk);vs=1;
    @(negedge clk);vs=0;
   end
   repeat(16) @(negedge clk);
   for(y=0;y<H;y=y+1) begin
    for(x=0;x<W/4;x=x+1) begin
     @(negedge clk);hs=1;valid=1;raw4=source[y*(W/4)+x];
     if(gap_arg && (x+y+run)%7==0) begin @(negedge clk);valid=0;end
    end
    @(negedge clk);hs=0;valid=0;
   end
   // End sync immediately after the single-clock horizontal blank.
   @(negedge clk);vs=~vs;
   repeat(20) @(negedge clk);
   if(count!=W*H/8 || gcount!=W*H/8 || frames!=run+1 || errors!=0 || mw!=W || mh!=H)
    $fatal(1,"frame counters count=%0d gray=%0d frames=%0d errors=%0d size=%0dx%0d",count,gcount,frames,errors,mw,mh);
   if(sr!==sums[0] || sg!==sums[1] || sb!==sums[2]) $fatal(1,"RAW10 channel sums %0d %0d %0d",sr,sg,sb);
  end
  $display("PASS: %0dx%0d phase=%0d gains=%0d gaps=%0d three frames, pixels/sums/gray metadata",W,H,phase,gain_arg,gap_arg);
  $finish;
 end
 initial begin #200000000;$fatal(1,"timeout");end
endmodule
