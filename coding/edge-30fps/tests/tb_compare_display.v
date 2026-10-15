`timescale 1ns/1ps
module tb_compare_display;
 parameter W=32,H=16;
 reg clk=0; always #5 clk=~clk;
 reg rst_n=0,period=1,mode=1,valid=0,ready=0;
 reg [127:0] data;
 wire in_ready,out_valid,sof,eol;
 wire [31:0] out_data,mixed,completed,source_signature;
 integer f,src,dst,x,y,k,sx,sy,sum,ev,cycles;
 reg [31:0] expected,p;
 reg gm=0,em=0,om=0;integer medsum;
 reg [31:0] seed=32'h31415926;
 reg [104:0] descriptor;reg [104:0] expected_descriptor;
 compare_display #(.W(W),.H(H)) dut(clk,rst_n,period,mode,gm,em,om,descriptor,data,valid,in_ready,
  out_data,out_valid,ready,sof,eol,mixed,completed,source_signature);
 function [31:0] pixel;
  input integer n,xx,yy;
  begin pixel={1'(((xx+3*yy+n)%11)==0),7'(n),8'(xx*37+yy*13+n*17),8'(xx*11+yy*53+n*29),8'(xx*7+yy*3+n*61)};
   if(yy==0 && xx==1) pixel[30:24]=7'((n*317)%2041);
   if(yy==0 && xx==2) pixel[30:24]={1'b0,1'(n==2 || n==6 || n==8 || n==11),1'(n%2),4'(((n*317)%2041)>>7)};
  end
 endfunction
 function integer luma;
  input [31:0] p;
  begin luma=(77*p[23:16]+150*p[15:8]+29*p[7:0]+128)>>8; end
 endfunction
 initial begin
  repeat(4) @(negedge clk); rst_n=1;
  for(f=0;f<12;f=f+1) begin
   descriptor={9'(f*17),32'(f+100),32'(f+10),32'(f+1)};expected_descriptor=descriptor;
   period=1;mode=f==0;gm=f==3;em=f==4;om=f>=6 && f!=8;valid=0;ready=0;src=0;dst=0;cycles=0;
   repeat(8) @(negedge clk);period=0;
   while(dst<W*H) begin
    seed=seed*1664525+1013904223;
    if(!valid && src<W*H && seed[3:0]!=0) begin
     for(k=0;k<4;k=k+1) data[127-32*k -:32]=pixel(f+1,(src+k)%W,(src+k)/W);
     valid=1;
    end
    ready=seed[6:4]!=0;
    @(posedge clk);
    if(out_valid && ready) begin
     x=dst%W;y=dst/W;
     if(f!=0 && f!=1 && f!=5 && f!=7 && f!=10) begin
      expected=pixel(f+1,x,y);
      if(f>=6 && f!=8) begin if(expected[31]) expected[23:0]=24'hff0000;end
      else if(f==4) expected[23:0]={24{expected[31]}};
      else if(f==3) expected[23:0]={3{8'(luma(expected))}};
     end
     else if(y<H/4 || y>=3*H/4) expected=0;
     else begin
      sx=(x%(W/2))*2;sy=(y-H/4)*2;sum=0;ev=0;medsum=0;
      for(k=0;k<4;k=k+1) begin
       p=pixel(f+1,sx+k%2,sy+k/2);sum=sum+((f==1 || f==5 || f==7 || f==10)?p[23:16]:luma(p));medsum=medsum+p[15:8];ev=ev|p[31];
      end
      sum=x<W/2 ? (sum+2)/4 : ((f==1 || f==5 || f==7 || f==10)?(medsum+2)/4:(ev?255:0));
      expected={8'd0,{3{8'(sum)}}};
     end
     expected[30:24]=y==0 && x==0 ? 7'(((f+1)*317)%2041) : (y==0 && x==1 ? {1'(f>=6 && f!=7 && f!=8 && f!=10),1'(f==1 || f==5 || f==7 || f==10),1'((f+1)%2),4'((((f+1)*317)%2041)>>7)} : 7'd0);
     if(y==0 && x>=2 && x<=16) expected[30:24]=expected_descriptor[(x-2)*7 +:7];
     // This check observes a stable offered pixel; record only at its handshake.
     if(out_data!==expected || sof!==(dst==0) || eol!==(x==W-1))
      $fatal(1,"compare f=%0d xy=%0d,%0d got=%h expected=%h",f,x,y,out_data,expected);
    end
    if(out_valid && ready) dst=dst+1;
    if(valid && in_ready) begin src=src+4; #1;valid=0; end
    @(negedge clk);
    cycles=cycles+1;
    // Change every request after frame start: the offered frame must stay intact.
    if(dst>W*H/2) begin mode=~mode;gm=~gm;em=~em;om=~om;descriptor=~descriptor;end
    if(cycles>W*H*10) $fatal(1,"timeout src=%0d dst=%0d",src,dst);
   end
   if(source_signature!==pixel(f+1,0,0)) $fatal(1,"source frame signature mismatch");
   if(src!=W*H || mixed!=0) $fatal(1,"source count or frame tags");
   valid=0;ready=0;
  end
  if(completed!=12) $fatal(1,"completed frame count %0d",completed);
  period=1; repeat(4) @(negedge clk); period=0;mode=0;
  data={pixel(5,0,0),pixel(5,1,0),pixel(6,3,0),pixel(6,3,0)};valid=1;
  @(posedge clk); #1;
  if(mixed!=1) $fatal(1,"mixed-tag injection was not detected");
  $display("PASS compare: %0dx%0d, 12 frames, all six views and in-frame request changes, mapping, rounded mean, OR, full color, gaps/stalls and mixed-tag detection",W,H);
  $finish;
 end
endmodule
