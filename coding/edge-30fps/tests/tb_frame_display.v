`timescale 1ns/1ps
// Real DDR reader, async FIFO, stream queue, compositor and HDMI timing.
module tb_frame_display;
`ifdef SHORT_DISPLAY
 localparam W=1280,H=128;
`else
 localparam W=1280,H=720;
`endif
`ifdef REFERENCE_DISPLAY
 localparam REFERENCE=1;
`else
 localparam REFERENCE=0;
`endif
`ifdef CANNY_DISPLAY
 localparam CANNY=1;
`else
 localparam CANNY=0;
`endif
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
 threshold_osd osd(clk,rst,vs,de,video[30:24],video[23:0],osd_rgb,shown_threshold,shown_flags,shown_descriptor,shown_toggle,64'd0);
 wire [300:0] shown_descriptor;wire shown_toggle;
 always @(posedge clk) if(rst && de && osd.y>0) begin
  if(shown_flags!=={1'b0,1'(REFERENCE || tag==1),1'b1}) $fatal(1,"OSD flags differ from actual frame");
  if(shown_threshold!==11'((tag*317)%2041)) $fatal(1,"OSD threshold does not match DDR frame");
  if(osd.bcd!=={4'(((tag*317)%2041)/1000),4'((((tag*317)%2041)/100)%10),4'((((tag*317)%2041)/10)%10),4'(((tag*317)%2041)%10)})
   $fatal(1,"OSD decimal conversion");
 end
 wire reset_fifo,write_fifo,empty_fifo;wire [127:0] fifo_data;wire [10:0] used;
 reg job_start=0;
`ifdef CACHE_CONTENTION
 localparam CACHE_LOAD=1;
`else
 localparam CACHE_LOAD=0;
`endif
 reg cache_pending=0;
 wire cache_ready,cache_done;
 integer cache_bursts=0;
 always @(posedge axi) if(rst && CACHE_LOAD) begin
  if(!cache_pending && cache_ready) begin cache_pending<=1;cache_bursts<=cache_bursts+1;end
  if(cache_done) cache_pending<=0;
 end
 wire [15:0] display_config={2'd1,1'(CANNY),1'(tag==1),1'b1,11'((tag*317)%2041)};
 reg state_read=0,raw_response=0;reg [31:0] raw_pixel;integer byte_index,raw_position;
 frame_store_dma #(.WORDS(W*H/4),.ENABLE_CANNY(CANNY)) dma(.clk(axi),.rst_n(rst),.enabled(1'b1),
 .job_canny(1'b0),.job_recognize(1'b0),.canny_req_valid(1'(CACHE_LOAD) && !cache_pending),.canny_req_write(1'b0),
 .canny_address(32'h08c00000),.canny_len(8'd255),.canny_req_ready(cache_ready),.canny_done(cache_done),
 .display_config(display_config),.display_frame_id(32'(tag)),
 .capture_data(162'd0),.capture_count(11'd0),.capture_empty(1'b1),.capture_accept(1'b0),.capture_slot(6'd0),
 .result_data(162'd0),.result_count(11'd0),.result_empty(1'b1),
 .job_start(job_start),.job_source(6'd0),.job_result(2'd0),.job_reader_ready(!1'(CACHE_LOAD)),.algorithm_used(11'd0),
 .display_period(period),.reference_mode(1'(REFERENCE)),.display_reset(reset_fifo),.display_valid(1'b1),.display_slot(2'd0),
 .reference_valid(1'(REFERENCE)),.reference_slot(6'd0),.display_data(fifo_data),.display_write(write_fifo),.display_used(used),
 .araddr(araddr),.arlen(arlen),.arvalid(arvalid),.rready(rready),
 .awready(1'b0),.wready(1'b0),.bvalid(1'b0),.bresp(2'd0),
 .arready(arready),.rvalid(rvalid),.rlast(rlast),.rresp(2'd0),.rdata(rdata));
 DC_FIFO #(.FIFO_MODE("ShowAhead"),.DATA_WIDTH(128),.FIFO_DEPTH(512)) fifo(
 .Reset(!rst || reset_fifo),.WrClk(axi),.WrEn(write_fifo),.WrData(fifo_data),.WrDNum(used),
 .RdClk(clk),.RdEn(dv && dr),.RdData(words),.RdEmpty(empty_fifo));
 assign dv=!empty_fifo && !period;
 // Keep processing reads queued throughout HDMI scanout.
 always @(negedge axi) job_start=rst && (!dma.job_active || dma.algorithm_offset==W*H/4);
 compare_display #(.W(W),.H(H)) comp(clk,rst,period,1'b1,1'b0,1'b0,(tag!=3),294'd0,words,dv,dr,pixels,pv,pr,sof,eol,mixed,completed,source_signature);
 cvo_axi #(.SYMBOL_WIDTH(8),.SYMBOL_NUM(4),.PIXEL_NUM(1),.FIFO_DEPTH(1024),
  .FIFO_ALMOST_FULL(1000),.MAX_H_VALID(W),.MAX_V_VALID(H)) cvo(
  .o_clk(clk),.rst_n(rst),.s_axi_clk(clk),.fifo_rd_period(period),.fifo_rd_underflow(underflow),
  .s_axis_tdata(pixels),.s_axis_tvalid(pv),.s_axis_tready(pr),.s_axis_tuser(sof),.s_axis_tlast(eol),
  .H_FRONT_PORCH(13'd110),.H_SYNC(13'd40),.H_VALID(13'd1280),.H_BACK_PORCH(13'd220),
  .V_FRONT_PORCH(13'd5),.V_SYNC(13'd5),.V_VALID(13'(H)),.V_BACK_PORCH(13'd20),
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
  if(CACHE_LOAD && tick%250000==0) $display("display progress cycles=%0d frames=%0d pixels=%0d cache_bursts=%0d",tick,frames,seen,cache_bursts);
  arready=rst && left==0 && tick%7!=0;
  rvalid=rst && left!=0 && tick%5!=0;
  rlast=left==1;
  if(rvalid) begin
  // Contending cache reads only exercise arbitration; their payload is unused.
  // Keep the full pixel oracle for every read that feeds the HDMI pipeline.
  if(dma.reader==3) rdata=0;
  else if(REFERENCE && raw_response) begin
   rdata=0;
   if(dma.reader==2) for(byte_index=0;byte_index<16;byte_index=byte_index+1) begin
    raw_position=(addr+byte_index)/3;
    if(byte_index==0 || (addr+byte_index)%3==0)
     raw_pixel=pixel(tag+10,raw_position%W,raw_position/W);
    rdata[127-byte_index*8 -:8]=raw_pixel[23-((addr+byte_index)%3)*8 -:8];
   end
  end else begin
  for(k=0;k<4;k=k+1) rdata[127-32*k -:32]=pixel(tag,(addr/4+k)%W,(addr/4+k)/W);
  if(CANNY) begin
   if(state_read) begin
    for(k=0;k<64;k=k+1)
     rdata[k*2 +:2]={1'((((addr*4+k)%W+3*((addr*4+k)/W)+tag)%11)==0),1'b0};
   end else for(k=0;k<4;k=k+1) rdata[127-32*k -:8]=8'h55;
  end
  end
  end
 end
 always @(posedge axi) begin
  if(arvalid && arready && ({1'b0,araddr[11:0]}+({5'd0,arlen}+1)*16)>4096) $fatal(1,"AXI read crosses 4 KiB");
  if(arvalid && arready) begin
   state_read=araddr>=32'h08b00000;
   raw_response=araddr<32'h07b00000;
   addr=state_read ? araddr-32'h08b00000 : araddr>=32'h07b00000 ? araddr-32'h07b00000 : araddr;
   left=arlen+1;
  end
  else if(rvalid && rready) begin left=left-1;addr=addr+16; end
 end
 always @(negedge clk) if(rst) begin
  if(underflow && frames!=0) $fatal(1,"HDMI underflow after warmup");
  if(de) begin
   x=seen%W;y=seen/W;
   if(y<H/4 || y>=3*H/4) expected=0;
   else begin
    sx=(x%(W/2))*2;sy=(y-H/4)*2;sum=0;ev=0;medsum=0;
    for(integer z=0;z<4;z=z+1) begin
     p=pixel(tag,sx+z%2,sy+z/2);sum=sum+(tag==1?p[23:16]:luma(p));medsum=medsum+p[15:8];ev=ev|p[31];
    end
    sum=x<W/2 ? (sum+2)/4 : (tag==1?(medsum+2)/4:(ev?255:0));
    if(REFERENCE) begin
     sum=0;
     for(integer z=0;z<4;z=z+1) begin
      p=pixel(x<W/2 ? tag+10 : tag,sx+z%2,sy+z/2);
      sum=sum+(x>=W/2 && tag==1 ? p[23:16] : luma(p));
     end
     sum=(sum+2)/4;
    end
    expected={8'd0,{3{8'(sum)}}};
   end
   expected[30:24]=y==0 && x==0 ? 7'(((tag)*317)%2041) : (y==0 && x==1 ? {1'b0,1'(REFERENCE || tag==1),1'b1,4'((((tag)*317)%2041)>>7)} : 7'd0);
   if(y==0 && x==44) expected[30:24]={1'b0,1'(tag!=3),2'b00,1'b1,1'(REFERENCE || tag==1),1'b0};
     if(video!==expected) $fatal(1,"pipeline tag=%0d xy=%0d,%0d got=%h expected=%h",tag,x,y,video,expected);
   seen=seen+1;
   if(seen==W*H) begin
    seen=0;frames=frames+1;
    if(frames==3) begin
     if(mixed!=0) $fatal(1,"mixed frame tags %0d",mixed);
     if(CACHE_LOAD && cache_bursts<100) $fatal(1,"cache contention coverage: %0d bursts",cache_bursts);
     if(CACHE_LOAD) $display("PASS cache contention: %0d full 4 KiB reads",cache_bursts);
     $display("PASS display Canny=%0d reference=%0d: 3 full %0dx%0d split frames, saturated algorithm read contention, AXI bubbles, all HDMI pixels and deadlines",CANNY,REFERENCE,W,H);
     $finish;
    end
   end
  end
 end
 initial begin
  repeat(10) @(negedge clk);rst=1;
  #100000000;$fatal(1,"pipeline timeout frames=%0d seen=%0d",frames,seen);
 end
endmodule
