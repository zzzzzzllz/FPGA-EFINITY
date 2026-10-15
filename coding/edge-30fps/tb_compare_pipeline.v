`timescale 1ns/1ps
// Real DDR reader, async FIFO, stream queue, compositor and HDMI timing.
module tb_compare_pipeline;
 localparam W=1280,H=720;
 reg axi=0,clk=0,rst=0;
 always #5 axi=~axi;
 always #6.734 clk=~clk;
 wire period,underflow,dv,dr,pv,pr,sof,eol,hs,vs,de;
 wire [127:0] words;
 wire [31:0] pixels,video,mixed,completed,source_signature;
 wire [31:0] araddr;
 wire [7:0] arlen;
 wire arvalid,rready;
 reg arready=0,rvalid=0,rlast=0;
 reg [127:0] rdata=0;
 integer left=0,addr=0,tick=0,tag=0,k,seen=0,frames=0,x,y,sx,sy,sum,ev;
 reg [31:0] expected,p;
 wire [10:0] shown_threshold;wire [2:0] shown_flags;integer medsum;
 wire [23:0] osd_rgb;
 threshold_osd osd(clk,rst,vs,de,video[30:24],video[23:0],osd_rgb,shown_threshold,shown_flags,shown_descriptor,shown_toggle,32'd0);
 wire [103:0] shown_descriptor;wire shown_toggle;
 always @(posedge clk) if(rst && de && osd.y>0) begin
  if(shown_flags!=={1'(tag==0 || tag==2 || tag==4),1'(tag==1),1'b1}) $fatal(1,"OSD flags differ from actual frame");
  if(shown_threshold!==11'((tag*317)%2041)) $fatal(1,"OSD threshold does not match DDR frame");
  if(osd.bcd!=={4'(((tag*317)%2041)/1000),4'((((tag*317)%2041)/100)%10),4'((((tag*317)%2041)/10)%10),4'(((tag*317)%2041)%10)})
   $fatal(1,"OSD decimal conversion");
 end
 frame_buffer #(.I_VID_WIDTH(64),.O_VID_WIDTH(128),.AXI_DATA_WIDTH(128),
  .AXI_ADDR_WIDTH(32),.START_ADDR(0),.O_FRAME_WIDTH(320),.O_FRAME_HEIGHT(H),.BURST_LEN(127)) fb(
  .axi_clk(axi),.rst_n(rst),.i_clk(axi),.i_vs(1'b0),.i_de(1'b0),.vin(64'd0),
  .o_clk(clk),.fifo_rd_period(period),.m_axis_tdata(words),.m_axis_tvalid(dv),.m_axis_tready(dr),
  .araddr(araddr),.arlen(arlen),.arvalid(arvalid),.arready(arready),
  .rid(6'd0),.rdata(rdata),.rvalid(rvalid),.rlast(rlast),.rready(rready),.rresp(2'd0),
  .awready(1'b0),.wready(1'b0),.bid(6'd0),.bvalid(1'b0));
 compare_display comp(clk,rst,period,1'b0,1'b0,1'b0,(tag!=3),104'd0,words,dv,dr,pixels,pv,pr,sof,eol,mixed,completed,source_signature);
 cvo_axi #(.SYMBOL_WIDTH(8),.SYMBOL_NUM(4),.PIXEL_NUM(1),.FIFO_DEPTH(1024),
  .FIFO_ALMOST_FULL(1000),.MAX_H_VALID(W),.MAX_V_VALID(H)) cvo(
  .o_clk(clk),.rst_n(rst),.s_axi_clk(clk),.fifo_rd_period(period),.fifo_rd_underflow(underflow),
  .s_axis_tdata(pixels),.s_axis_tvalid(pv),.s_axis_tready(pr),.s_axis_tuser(sof),.s_axis_tlast(eol),
  .H_FRONT_PORCH(13'd110),.H_SYNC(13'd40),.H_VALID(13'd1280),.H_BACK_PORCH(13'd220),
  .V_FRONT_PORCH(13'd5),.V_SYNC(13'd5),.V_VALID(13'd720),.V_BACK_PORCH(13'd20),
  .vout(video),.o_hs(hs),.o_vs(vs),.o_de(de));
 function [31:0] pixel;
  input integer n,xx,yy;
  begin pixel={1'(((xx+3*yy+n)%11)==0),7'(n),8'(xx*37+yy*13+n*17),8'(xx*11+yy*53+n*29),8'(xx*7+yy*3+n*61)};
   if(yy==0 && xx==1) pixel[30:24]=7'((n*317)%2041);
   if(yy==0 && xx==2) pixel[30:24]={1'b0,1'(n==1),1'b1,4'(((n*317)%2041)>>7)};
  end
 endfunction
 function integer luma;
  input [31:0] p;
  begin luma=(77*p[23:16]+150*p[15:8]+29*p[7:0]+128)>>8; end
 endfunction
 always @(posedge period) if(rst) begin tag=tag+1;seen=0; $display("PERIOD tag=%0d time=%0t",tag,$time); end
 always @(posedge underflow) if(rst) $display("UNDERFLOW time=%0t seen=%0d comp xy=%0d,%0d inxy=%0d,%0d",$time,seen,comp.ox,comp.oy,comp.ix,comp.iy);
 // Burst responder has a deterministic 20% bubble rate and delayed starts.
 always @(negedge axi) begin
  tick=tick+1;
  arready=rst && left==0 && tick%7!=0;
  rvalid=rst && left!=0 && tick%5!=0;
  rlast=left==1;
  for(k=0;k<4;k=k+1) rdata[127-32*k -:32]=pixel(tag,(addr/4+k)%W,(addr/4+k)/W);
 end
 always @(posedge axi) begin
  if(arvalid && arready) begin addr=araddr;left=arlen+1; end
  else if(rvalid && rready) begin left=left-1;addr=addr+16; end
 end
 always @(negedge clk) if(rst) begin
  if(underflow && frames!=0) $fatal(1,"HDMI underflow after warmup");
  if(de) begin
   x=seen%W;y=seen/W;
   if(tag!=1) begin
    expected=pixel(tag,x,y);
    if(tag!=3 && expected[31]) expected[23:0]=24'hff0000;
   end
   else if(y<H/4 || y>=3*H/4) expected=0;
   else begin
    sx=(x%(W/2))*2;sy=(y-H/4)*2;sum=0;ev=0;medsum=0;
    for(integer z=0;z<4;z=z+1) begin
     p=pixel(tag,sx+z%2,sy+z/2);sum=sum+(tag==1?p[23:16]:luma(p));medsum=medsum+p[15:8];ev=ev|p[31];
    end
    sum=x<W/2 ? (sum+2)/4 : (tag==1?(medsum+2)/4:(ev?255:0));
    expected={8'd0,{3{8'(sum)}}};
   end
   expected[30:24]=y==0 && x==0 ? 7'(((tag)*317)%2041) : (y==0 && x==1 ? {1'(tag==0 || tag==2 || tag==4),1'(tag==1),1'b1,4'((((tag)*317)%2041)>>7)} : 7'd0);
     if(video!==expected) $fatal(1,"pipeline tag=%0d xy=%0d,%0d got=%h expected=%h",tag,x,y,video,expected);
   seen=seen+1;
   if(seen==W*H) begin
    seen=0;frames=frames+1;
    if(frames==5) begin
     if(mixed!=0) $fatal(1,"mixed frame tags %0d",mixed);
     $display("PASS pipeline: 5 full 720p frames, overlay/denoise/overlay/color/overlay, DDR bursts/bubbles, CDC FIFO, all output pixels and HDMI deadlines");
     $finish;
    end
   end
  end
 end
 initial begin
  force fb.ddr_frame_len=230400;
  force fb.u_ddr_buffer.rd_start_addr=0;
  repeat(10) @(negedge clk);rst=1;
  #100000000;$fatal(1,"pipeline timeout frames=%0d seen=%0d",frames,seen);
 end
endmodule
