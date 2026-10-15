`timescale 1ns/1ps
module tb_threshold_sobel;
    parameter W=32,H=12,T=32,STALL=1,STEP=32;
 reg clk=0; always #10 clk=~clk;
 reg rst_n=0,iv=0,sof=0,eol=0,eof=0,ready=1;
 wire ir,ov,os,ol,oe;
 reg [63:0] data;
 reg [31:0] fid,epoch;
 wire [63:0] result;
 wire [31:0] ofid,oepoch;
 reg [10:0] requested=32;
 wire [10:0] actual;
 integer previous_count=2147483647,edge_count=0;
 integer f,p,got=0,cycles=0,seed=31,k,xx,yy,ff;
 reg [63:0] expected,held;
 reg [66:0] held_meta;
 reg stalled=0;
 sobel_pair #(.WIDTH(W),.HEIGHT(H)) dut(
  .clk(clk),.rst_n(rst_n),.in_valid(iv),.in_ready(ir),.in_rgby(data),.threshold(requested),.out_threshold(actual),
  .in_sof(sof),.in_eol(eol),.in_eof(eof),.in_frame_id(fid),.in_epoch(epoch),
  .out_valid(ov),.out_ready(ready),.out_rgbe(result),.out_sof(os),.out_eol(ol),
  .out_eof(oe),.out_frame_id(ofid),.out_epoch(oepoch));
 function integer threshold_for;
  input integer frame;
  begin case(frame)
   0:threshold_for=0;1:threshold_for=16;2:threshold_for=32;3:threshold_for=64;
   4:threshold_for=128;5:threshold_for=256;6:threshold_for=512;7:threshold_for=2040;
  endcase end
 endfunction
 function integer pixel;
  input integer frame,x,y;
  integer cx,cy;
  begin
   cx=x<0?0:(x>=W?W-1:x); cy=y<0?0:(y>=H?H-1:y);
   case(6)
    0: pixel=85;
    1: pixel=cx>=W/2?255:0;
    2: pixel=cy>=H/2?255:0;
    3: pixel=cx>=W/4 && cx<3*W/4 && cy>=H/4 && cy<3*H/4?255:0;
    4: pixel=((cx/3+cy/3)%2)*255;
    5: pixel=cx>=W/2?STEP:0; // Interior gradient is exactly 4*STEP.
    6: pixel=(cx*71+cy*137+cx*cy*13)%256;
    7: pixel=0; // Detect stale row contents from the previous frame.
   endcase
  end
 endfunction
 function [31:0] word;
  input integer frame,x,y;
  reg [7:0] value,r,g,b;
  begin
   value=pixel(frame,x,y); r=x%256; g=y%256; b=(x+y+frame)%256;
   word={value,r,g,b};
  end
 endfunction
 function integer reference_gx;
  input integer frame,x,y;
  begin reference_gx= -pixel(frame,x-1,y-1)+pixel(frame,x+1,y-1)
   -2*pixel(frame,x-1,y)+2*pixel(frame,x+1,y)
   -pixel(frame,x-1,y+1)+pixel(frame,x+1,y+1); end
 endfunction
 function integer reference_gy;
  input integer frame,x,y;
  begin reference_gy= -pixel(frame,x-1,y-1)-2*pixel(frame,x,y-1)-pixel(frame,x+1,y-1)
   +pixel(frame,x-1,y+1)+2*pixel(frame,x,y+1)+pixel(frame,x+1,y+1); end
 endfunction
 function [31:0] reference;
  input integer frame,x,y;
  integer dx,dy,g;
  reg [31:0] source;
  begin
   dx=reference_gx(frame,x,y); dy=reference_gy(frame,x,y);
   g=(dx<0?-dx:dx)+(dy<0?-dy:dy); source=word(frame,x,y);
   reference={8'h00,source[23:0]};
   if(x>0 && x<W-1 && y>0 && y<H-1 && g>threshold_for(frame)) reference[31:24]=255;
  end
 endfunction
 integer gradients=0,gf,gxpos,gypos;
 always @(posedge clk) if(rst_n) begin
  cycles=cycles+1;
  if(cycles>W*H*40) $fatal(1,"timeout");
  if(stalled && (!ov || result!==held || {os,ol,oe,ofid,oepoch}!==held_meta))
   $fatal(1,"output changed under backpressure");
  stalled=ov && !ready; held=result; held_meta={os,ol,oe,ofid,oepoch};
  if(dut.s_valid && dut.advance) begin
   gf=gradients/(W*H/2); gxpos=(gradients%(W/2))*2; gypos=(gradients%(W*H/2))/(W/2);
   if($signed(dut.gx0)!==reference_gx(gf,gxpos,gypos) ||
      $signed(dut.gy0)!==reference_gy(gf,gxpos,gypos) ||
      $signed(dut.gx1)!==reference_gx(gf,gxpos+1,gypos) ||
      $signed(dut.gy1)!==reference_gy(gf,gxpos+1,gypos))
    $fatal(1,"gradient mismatch frame=%0d x=%0d y=%0d actual=(%0d,%0d) expected=(%0d,%0d)",gf,gxpos,gypos,$signed(dut.gx0),$signed(dut.gy0),reference_gx(gf,gxpos,gypos),reference_gy(gf,gxpos,gypos));
   gradients=gradients+1;
  end
  if(ov && ready) begin
   ff=got/(W*H/2); xx=(got%(W/2))*2; yy=(got%(W*H/2))/(W/2);
   expected={reference(ff,xx,yy),reference(ff,xx+1,yy)};
   if(result!==expected) $fatal(1,"pixel mismatch frame=%0d x=%0d y=%0d got=%h expected=%h",ff,xx,yy,result,expected);
   if(os!==(xx==0 && yy==0) || ol!==(xx==W-2) || oe!==(xx==W-2 && yy==H-1) || ofid!==ff+101 || oepoch!==ff+20)
    $fatal(1,"metadata mismatch pair=%0d",got);
   if(actual!==11'(threshold_for(ff))) $fatal(1,"threshold changed inside frame");
   edge_count=edge_count+(result[63]?1:0)+(result[31]?1:0);
   got=got+1;
  end
 end
 always @(negedge clk) if(rst_n) ready=STALL?($random(seed)&7)!=0:1;
 initial begin
  repeat(4) @(negedge clk); rst_n=1;
  for(f=0;f<8;f=f+1) begin
   for(p=0;p<W*H/2;p=p+1) begin
    @(negedge clk);
    if(STALL && ($random(seed)&7)==0) begin iv=0; repeat(2) @(negedge clk); end
    requested=p==0?threshold_for(f):2040-threshold_for(f);
    iv=1; sof=p==0; eol=p%(W/2)==W/2-1; eof=p==W*H/2-1;
    fid=f+101; epoch=f+20;
    data={word(f,(p%(W/2))*2,p/(W/2)),word(f,(p%(W/2))*2+1,p/(W/2))};
    @(posedge clk); while(!ir) @(posedge clk);
   end
   @(negedge clk); iv=0; sof=0;eol=0;eof=0;
   wait(got==(f+1)*W*H/2);
   if(edge_count>previous_count) $fatal(1,"nonmonotonic edges");
   $display("T=%0d edges=%0d",threshold_for(f),edge_count);
   previous_count=edge_count;edge_count=0;
  end
  repeat(10) @(negedge clk);
  if(got!=8*W*H/2 || gradients!=got) $fatal(1,"wrong total");
  $display("PASS Sobel %0dx%0d T=%0d stall=%0d: 8 frames, signed gradients, replicated boundaries, exact RGB/edges, metadata and backpressure",W,H,T,STALL);
  $finish;
 end
endmodule
