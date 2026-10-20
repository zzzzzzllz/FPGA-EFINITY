`timescale 1ns/1ps
module tb_frame_store;
 wire recognition_enable=0;
`ifdef FULL_SMOKE
 localparam W=1280,H=720,WORDS=W*H/4;
`else
 localparam W=32,H=16,WORDS=W*H/4;
`endif
 reg core_clk=0,pixel_clk=0,display_clk=0;
 always #5 core_clk=~core_clk;always #10 pixel_clk=~pixel_clk;always #7 display_clk=~display_clk;
 reg rst_n=0,enabled=1;
 reg [63:0] capture_pixels;reg capture_valid=0,capture_sof=0,capture_eof=0;
 reg [31:0] capture_frame_id=0,config_epoch=0;reg [15:0] config_value=13'd2080;
 wire [63:0] algorithm_pixels;wire algorithm_valid;wire algorithm_ready;
 wire algorithm_sof,algorithm_eol,algorithm_eof;
 wire [31:0] algorithm_frame_id,algorithm_epoch;wire [15:0] algorithm_config;wire algorithm_recognition;wire [14:0] recognition_live;
 wire [63:0] result_pixels;wire result_valid,result_sof,result_eof,result_ready;
 reg [3:0] command=0;reg command_toggle=0;wire command_ack;
 reg reference_mode=0,display_period=0;
 wire [127:0] display_pixels;wire display_valid;reg display_ready=1;
 wire [293:0] display_descriptor;
 reg shown_toggle=0;reg [1:0] shown_slot=0;
 wire [319:0] status;wire [31:0] capture_overflow,result_overflow;
 wire [159:0] traffic;wire [223:0] algorithm_status;
 wire [31:0] awaddr,araddr;wire [7:0] awlen,arlen;
 wire awvalid,wvalid,wlast,bready,arvalid,rready;wire [127:0] wdata;wire [15:0] wstrb;integer byte_lane;
 reg awready=0,wready=0,bvalid=0,arready=0,rvalid=0,rlast=0;
 reg [1:0] bresp=0,rresp=0;reg [127:0] rdata=0;
 frame_store #(.W(W),.H(H),.BURST(16),.PLAY_PERIOD(4200)) dut(.*);
 function [31:0] pixel(input integer frame,input integer index);
  reg [7:0] r,g,b;reg [15:0] y;
  begin
`ifdef FULL_SMOKE
   r=frame%100+20+(index%W>=W/2?64:0);g=r;b=r;
`else
   r=frame+index*7;g=frame*3+index*11;b=frame*13+index*5;
`endif
   y=77*r+150*g+29*b+128;pixel={y[15:8],r,g,b};end
 endfunction
 // A simple stateless processing stand-in isolates the memory/CDC contract.
 // Median/Sobel correctness remains covered by their independent pixel tests.
 reg [19:0] pair_index=0;
 wire [31:0] input0=pixel(algorithm_frame_id,pair_index*2);
 wire [31:0] input1=pixel(algorithm_frame_id,pair_index*2+1);
 wire edge0=algorithm_pixels[63:56]>algorithm_config[10:0];
 wire edge1=algorithm_pixels[31:24]>algorithm_config[10:0];
`ifdef REAL_ALGORITHM
 wire [63:0] med_pixels,sob_pixels;wire med_valid,med_ready,med_sof,med_eol,med_eof,sob_eol;
 wire [31:0] med_id,med_epoch,sob_id,sob_epoch;
 wire [12:0] med_config;wire [1:0] sob_flags;wire [15:0] sob_luma;wire [10:0] sob_threshold;
 reg result_second=0;
 median_pair #(.WIDTH(W),.HEIGHT(H)) med(.clk(pixel_clk),.rst_n(rst_n),.in_valid(algorithm_valid),.in_ready(algorithm_ready),
  .in_config(algorithm_config),.out_config(med_config),.in_rgby(algorithm_pixels),.in_sof(algorithm_sof),.in_eol(algorithm_eol),.in_eof(algorithm_eof),
  .in_frame_id(algorithm_frame_id),.in_epoch(algorithm_epoch),.out_valid(med_valid),.out_ready(med_ready),.out_rgby(med_pixels),
  .out_sof(med_sof),.out_eol(med_eol),.out_eof(med_eof),.out_frame_id(med_id),.out_epoch(med_epoch));
 sobel_pair #(.WIDTH(W),.HEIGHT(H)) sob(.clk(pixel_clk),.rst_n(rst_n),.in_valid(med_valid),.in_ready(med_ready),
  .threshold(med_config[10:0]),.in_flags(med_config[12:11]),.out_flags(sob_flags),.out_luma(sob_luma),.out_threshold(sob_threshold),
  .in_rgby(med_pixels),.in_sof(med_sof),.in_eol(med_eol),.in_eof(med_eof),.in_frame_id(med_id),.in_epoch(med_epoch),
  .out_valid(result_valid),.out_ready(result_ready),.out_rgbe(sob_pixels),.out_sof(result_sof),.out_eol(sob_eol),.out_eof(result_eof),.out_frame_id(sob_id),.out_epoch(sob_epoch));
 always @(posedge pixel_clk) if(!rst_n) result_second<=0;else if(result_valid && result_ready) result_second<=result_sof;
 assign result_pixels={sob_pixels[63],(result_second?{1'b0,sob_flags,sob_threshold[10:7]}:sob_id[6:0]),sob_pixels[55:32],
                       sob_pixels[31],(result_sof?sob_threshold[6:0]:sob_id[6:0]),sob_pixels[23:0]};
`else
 assign result_pixels={edge0,(pair_index==1 ? {1'b0,algorithm_config[12:11],algorithm_config[10:7]} : algorithm_frame_id[6:0]),algorithm_pixels[55:32],
                       edge1,(pair_index==0 ? algorithm_config[6:0] : algorithm_frame_id[6:0]),algorithm_pixels[23:0]};
 assign result_valid=algorithm_valid && algorithm_ready;
 assign result_sof=algorithm_sof;assign result_eof=algorithm_eof;
 assign algorithm_ready=result_ready;
`endif
 function integer gray(input integer frame,input integer x,input integer y);
  reg [31:0] v;integer cx,cy;
  begin cx=x<0?0:x>=W?W-1:x;cy=y<0?0:y>=H?H-1:y;v=pixel(frame,cy*W+cx);gray=v[31:24];end
 endfunction
 function integer filtered(input integer frame,input integer x,input integer y,input integer median_enabled);
  integer a[0:8];integer i,j,t,cx,cy;
  begin
   cx=x<0?0:x>=W?W-1:x;cy=y<0?0:y>=H?H-1:y;
   for(i=0;i<9;i=i+1) a[i]=gray(frame,cx+i%3-1,cy+i/3-1);
   for(i=1;i<9;i=i+1) for(j=i;j>0;j=j-1) if(a[j]<a[j-1]) begin t=a[j];a[j]=a[j-1];a[j-1]=t;end
   filtered=median_enabled?a[4]:gray(frame,cx,cy);
  end
 endfunction
 function expected_edge(input integer frame,input integer index,input integer threshold,input integer med);
  integer x,y,gx,gy,k;
  begin
   x=index%W;y=index/W;gx=0;gy=0;
   for(k=-1;k<=1;k=k+1) begin
    gx=gx+(k==0?2:1)*(filtered(frame,x+1,y+k,med)-filtered(frame,x-1,y+k,med));
    gy=gy+(k==0?2:1)*(filtered(frame,x+k,y+1,med)-filtered(frame,x+k,y-1,med));
   end
   expected_edge=x!=0 && y!=0 && x!=W-1 && y!=H-1 && (gx<0?-gx:gx)+(gy<0?-gy:gy)>threshold;
  end
 endfunction
 always @(posedge pixel_clk) if(rst_n && algorithm_valid && algorithm_ready) begin
  if(algorithm_pixels!=={input0,input1}) $fatal(1,"source pixels changed id=%d pair=%d got=%h expected=%h",algorithm_frame_id,pair_index,algorithm_pixels,{input0,input1});
  if(algorithm_sof!=(pair_index==0) || algorithm_eof!=(pair_index==W*H/2-1) || algorithm_eol!=(pair_index%(W/2)==W/2-1)) $fatal(1,"source coordinates");
  pair_index<=algorithm_eof ? 0 : pair_index+1;
 end
 localparam RAW_WORDS=WORDS*3/4,RESULT_INDEX=41*RAW_WORDS;
 reg [127:0] memory[0:RESULT_INDEX+3*WORDS-1];
 integer cycles=0,write_index,read_index,read_remaining=0;
 function integer address_index(input [31:0] address);
  integer slot,offset;
  begin
   if(address<32'h07b00000) begin
    slot=address/32'h00300000;offset=(address%32'h00300000)/16;
    if(slot>=41 || offset>=RAW_WORDS) $fatal(1,"Raw DDR address range %h",address);
    address_index=slot*RAW_WORDS+offset;
   end else begin
    slot=(address-32'h07b00000)/32'h00400000;offset=((address-32'h07b00000)%32'h00400000)/16;
    if(slot>=3 || offset>=WORDS) $fatal(1,"Result DDR address range %h",address);
    address_index=RESULT_INDEX+slot*WORDS+offset;
   end
  end
 endfunction
 always @(posedge core_clk) begin
  if(awvalid && awready && ({1'b0,awaddr[11:0]}+({5'd0,awlen}+1)*16)>4096) $fatal(1,"AXI write crosses 4 KiB");
  if(arvalid && arready && ({1'b0,araddr[11:0]}+({5'd0,arlen}+1)*16)>4096) $fatal(1,"AXI read crosses 4 KiB");
  cycles<=cycles+1;awready<=cycles%3!=0;wready<=cycles%7!=0;arready<=read_remaining==0 && !rvalid && cycles%5!=0;
  if(awvalid && awready) write_index=address_index(awaddr);
  if(wvalid && wready) begin
   for(byte_lane=0;byte_lane<16;byte_lane=byte_lane+1) if(wstrb[byte_lane]) memory[write_index][byte_lane*8 +:8]=wdata[byte_lane*8 +:8];
   write_index=write_index+1;if(wlast) bvalid<=1;end
  if(bvalid && bready) bvalid<=0;
  if(arvalid && arready) begin read_index=address_index(araddr);read_remaining=arlen+1;end
  if(rvalid && rready) begin rvalid<=0;read_remaining=read_remaining-1;read_index=read_index+1;end
  if(!rvalid && read_remaining!=0 && cycles%4!=0) begin
   rvalid<=1;rdata<=memory[read_index];rlast<=read_remaining==1;
  end
 end
 integer shown_words=0,shown_frames=0,p,idx;
 reg [104:0] desc;reg [31:0] expected,refpixel,actual_pixel;
 reg [31:0] last_shown_id=0,last_shown_epoch=0;
 reg [10:0] displayed_threshold;
 reg displayed_median,edge_expected;
 always @(posedge display_clk) begin
  if(display_period) shown_words=0;
  else if(rst_n && display_valid && display_ready) begin
   if(shown_words==0) begin
    desc=display_descriptor;shown_slot=desc[97:96];shown_toggle=~shown_toggle;
    last_shown_id=desc[31:0];last_shown_epoch=desc[63:32];
    displayed_threshold={display_pixels[59:56],display_pixels[94:88]};
    displayed_median=display_pixels[60];
   end
   for(p=0;p<4;p=p+1) begin
    idx=shown_words*4+p;expected=pixel(desc[31:0],idx);
    actual_pixel=display_pixels[127-p*32 -:32];
`ifdef REAL_ALGORITHM
`ifdef FULL_SMOKE
    edge_expected=idx/W!=0 && idx/W!=H-1 && (idx%W==W/2-1 || idx%W==W/2) && displayed_threshold<256;
`else
    edge_expected=expected_edge(desc[31:0],idx,displayed_threshold,displayed_median);
`endif
`else
    edge_expected=expected[31:24]>displayed_threshold;
`endif
    if(desc[101]) begin
     refpixel=pixel(idx/W<H/2 ? desc[95:64] : desc[31:0],((idx/W)%(H/2)*2)*W+(idx%W)%(W/2)*2);
     if((idx/W<H/2 && idx%W>=W/2) || (idx/W>=H/2 && idx%W<W/2)) refpixel=0;
     if(actual_pixel[23:0]!==refpixel[23:0]) $fatal(1,"four-tile pixels id%d at%d got%h expected%h",desc[31:0],idx,actual_pixel,refpixel);
    end else if(actual_pixel[23:0]!==expected[23:0] || actual_pixel[31]!=edge_expected)
      $fatal(1,"display pixels id%d at%d got%h expected%h",desc[31:0],idx,actual_pixel,expected);
   end
   shown_words=shown_words+1;
   if(shown_words==WORDS) shown_frames=shown_frames+1;
   if(shown_words>WORDS) $fatal(1,"extra display pixels");
  end
 end
 initial begin
  wait(rst_n);
  forever begin
   @(negedge display_clk);display_period=1;
   repeat(100) @(negedge display_clk);display_period=0;
   repeat(W==1280 ? 1189900 : 1400) @(negedge display_clk);
  end
 end
 task capture(input integer id);
  integer j;
  begin
   for(j=0;j<W*H/2;j=j+1) begin
    @(negedge pixel_clk);capture_valid=1;capture_sof=j==0;capture_eof=j==W*H/2-1;
    capture_frame_id=id;capture_pixels={pixel(id,j*2),pixel(id,j*2+1)};
   end
   @(negedge pixel_clk);capture_valid=0;capture_sof=0;capture_eof=0;
  end
 endtask
 task cmd(input [3:0] value);begin
  @(negedge pixel_clk);command=value;command_toggle=~command_toggle;
  wait(command_ack==command_toggle);repeat(20) @(negedge pixel_clk);
 end endtask
 task await_frame(input integer id,input integer epoch);
  begin wait(last_shown_id==id && last_shown_epoch==epoch);#10000;end
 endtask
 integer n,prior;
 initial begin
  repeat(20) @(negedge pixel_clk);rst_n=1;#1000;
  capture(10);await_frame(10,0);$display("CHECK: initial frame id10 at %0t",$time);cmd(2);
  capture(11);#60000;if(last_shown_id!=10) $fatal(1,"freeze moved");
  @(negedge pixel_clk);config_value=13'd512;config_epoch=1;
  await_frame(10,1);$display("CHECK: same raw frame id10 epoch1 at %0t",$time);cmd(8);reference_mode=1;
  cmd(3);capture(20);await_frame(20,1);$display("CHECK: live step id20 at %0t",$time);
`ifndef FULL_SMOKE
  cmd(4);
  for(n=0;n<32;n=n+1) begin capture(100+n);#60000;end
  await_frame(100,1);
  if(status[8:3]!=32 || status[159:128]!=10) $fatal(1,"record/reference status %h",status);
  for(n=1;n<32;n=n+1) begin cmd(7);await_frame(100+n,1);end
  cmd(7);await_frame(100,1);
  cmd(5);
  for(n=0;n<64;n=n+1) await_frame(100+n%32,1);
  cmd(6);prior=last_shown_id;#60000;
  if(last_shown_id!=prior) $fatal(1,"pause moved");
`endif
  cmd(1);capture(300);await_frame(300,1);
  if(capture_overflow || result_overflow || status[319:256]!=0) $fatal(1,"FIFO/bus/frame error %h",status);
`ifdef FULL_SMOKE
  $display("PASS full 720p: raw RGBY preservation, real median/Sobel, freeze/reprocess, live step and reference comparison; %d complete display frames",shown_frames);
`else
  $display("PASS: actual CDC FIFOs + AXI stalls, raw pixel preservation, freeze/reprocess, step, 32-frame record/replay, reference comparison; %d display frames",shown_frames);
`endif
  $finish;
 end
 initial begin #(W==1280 ? 1000000000 : 20000000);$fatal(1,"timeout shown%d epoch%d mode%d cstate%d ws%d rs%d job%b ready%b counts%d/%d",last_shown_id,last_shown_epoch,dut.mode,dut.dma.capture_state,dut.dma.ws,dut.dma.rs,dut.control.job_busy,dut.control.ready_valid,dut.capture_count,dut.result_count);end
endmodule
