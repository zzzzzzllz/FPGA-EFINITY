`timescale 1ns/1ps
// Read-only probes of original RTL. No new synthesizable tap or localization logic.
module tb_gradients;
 parameter W=16,H=12,JOBS=1,STALL=1;
 localparam N=W*H, TOTAL=N*JOBS;
 reg clk=0; always #10 clk=~clk;
 reg rst_n=0,iv=0,ready=0;
 reg [63:0] pixels;
 reg sof=0,eol=0,eof=0;
 wire ir,ov,os,ol,oe;
 wire [63:0] op;
 wire [31:0] oid,oepoch;
 wire [15:0] oc;
 reg [31:0] source[0:TOTAL-1],med_expected[0:TOTAL-1],gauss_expected[0:TOTAL-1],sobel_expected[0:TOTAL-1];
 reg [63:0] a_expected[0:TOTAL/2-1],b_expected[0:TOTAL/2-1];
 reg [25:0] gradient_expected[0:TOTAL/2-1];
 reg [1:0] raw_edge_expected[0:TOTAL/2-1];
 reg [16:0] settings[0:JOBS-1];
 integer job=0,sent=0,ac=0,bc=0,mc=0,gc=0,sc=0,ocount=0,cycles=0;
 integer afile,bfile,afileout,bfileout,astalls=0,bstalls=0,mstalls=0,gstalls=0,ostalls=0;
 integer first_a=-1,first_b=-1,last_a=-1,last_b=-1,eol_stalls=0,eof_stalls=0;
 integer timeout_cycles;
 reg [31:0] rng=32'h921234;
 reg [1023:0] directory,path;
 wire [15:0] input_config=sent%N==0 ? settings[job][15:0] : ~settings[job][15:0];
 wire input_recognition=sent%N==0 ? settings[job][16] : !settings[job][16];
 // Exercise the actual DDR-read grayscale function; the DMA stays in reset.
 // This is not an AXI/frame-manager integration test.
 frame_store_dma dma_gray_reference(.clk(clk),.rst_n(1'b0),.enabled(1'b0),.rdata(128'd0));
 edge_algorithm_pair #(.W(W),.H(H)) dut(
  .clk(clk),.rst_n(rst_n),.in_config(input_config),.in_recognition(input_recognition),
  .in_pixels(pixels),.in_valid(iv),.in_ready(ir),.in_sof(sof),.in_eol(eol),.in_eof(eof),
  .in_id(sent%N==0 ? 32'd700+job : 32'hdeadbeef),.in_epoch(sent%N==0 ? 32'd1700+job : 32'hbadbeef),
  .out_pixels(op),.out_valid(ov),.out_ready(ready),.out_sof(os),.out_eol(ol),.out_eof(oe),
  .out_id(oid),.out_epoch(oepoch),.out_config(oc));

 function [15:0] sext(input signed [10:0] v); sext=v; endfunction
 wire [63:0] a_now={sext(dut.gradient_stage.gx0),sext(dut.gradient_stage.gy0),sext(dut.gradient_stage.gx1),sext(dut.gradient_stage.gy1)};
 wire [63:0] b_now={sext(dut.median.raw_gx0),sext(dut.median.raw_gy0),sext(dut.median.raw_gx1),sext(dut.median.raw_gy1)};
 wire [255:0] a_bundle={a_now,dut.gradient_stage.s_valid,dut.gradient_stage.s_rgb,dut.gradient_stage.s_id,dut.gradient_stage.s_epoch,
  dut.gradient_stage.s_sof,dut.gradient_stage.s_eol,dut.gradient_stage.s_eof,dut.gradient_stage.s_threshold,dut.gradient_stage.s_flags};
 wire [255:0] b_bundle={b_now,dut.median.valid_pipe[0],dut.median.rgb_pipe[0],dut.median.id_pipe[0],dut.median.epoch_pipe[0],dut.median.marks[0],dut.median.config_pipe[0]};
 wire [255:0] m_bundle={dut.med,dut.original_luma,dut.raw_edge,dut.mv,dut.ms,dut.ml,dut.me,dut.mi,dut.mp,dut.mc};
 wire [255:0] g_bundle={dut.gauss,dut.gv,dut.gs,dut.gl,dut.ge,dut.gi,dut.gp,dut.gc};
 wire [255:0] s_bundle={dut.sobel,dut.gradient,dut.sv,dut.ss,dut.sl,dut.se,dut.si,dut.sp,dut.gradient_stage.out_luma,dut.gradient_stage.out_threshold,dut.gradient_stage.out_flags};
 wire [255:0] o_bundle={op,ov,os,ol,oe,oid,oepoch,oc};
 reg [255:0] ah,bh,mh,gh,sh,oh;
 reg as_hold=0,bs_hold=0,ms_hold=0,gs_hold=0,ss_hold=0,os_hold=0;

 task check_meta(input integer count,input [2:0] marks,input [31:0] id,epoch);
  integer local_pixel,frame;
  begin
   local_pixel=count%N;frame=count/N;
   if(marks!=={(local_pixel==0),(local_pixel%W==W-2),(local_pixel==N-2)} || id!=700+frame || epoch!=1700+frame)
    $fatal(1,"metadata count=%0d marks=%b id=%0d epoch=%0d",count,marks,id,epoch);
  end
 endtask

 initial begin
  if(!$value$plusargs("directory=%s",directory)) $fatal(1,"missing directory");
  path={directory,"/input.mem"};$readmemh(path,source);
  path={directory,"/median.mem"};$readmemh(path,med_expected);
  path={directory,"/gauss.mem"};$readmemh(path,gauss_expected);
  path={directory,"/sobel.mem"};$readmemh(path,sobel_expected);
  path={directory,"/a.mem"};$readmemh(path,a_expected);
  path={directory,"/b.mem"};$readmemh(path,b_expected);
  path={directory,"/gradient.mem"};$readmemh(path,gradient_expected);
  path={directory,"/raw-edge.mem"};$readmemh(path,raw_edge_expected);
  path={directory,"/settings.mem"};$readmemh(path,settings);
  path={directory,"/observed-a.mem"};afileout=$fopen(path,"w");
  path={directory,"/observed-b.mem"};bfileout=$fopen(path,"w");
  if(!afileout || !bfileout) $fatal(1,"cannot open observations");
  timeout_cycles=TOTAL*30+10000;
  repeat(5) @(negedge clk);rst_n=1;
 end

 always @(negedge clk) if(rst_n) begin
  rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
  ready=!STALL || ((cycles%113)>=37 && rng[3:0]>=5);
  if(!iv && sent<(job+1)*N && (!STALL || rng[7:4]!=0)) begin
   if(dma_gray_reference.luma(source[sent][23:0])!==source[sent][31:24] ||
      dma_gray_reference.luma(source[sent+1][23:0])!==source[sent+1][31:24]) $fatal(1,"DDR gray mismatch %0d",sent);
   pixels={dma_gray_reference.luma(source[sent][23:0]),source[sent][23:0],
           dma_gray_reference.luma(source[sent+1][23:0]),source[sent+1][23:0]};
   iv=1;sof=sent%N==0;eol=sent%W==W-2;eof=sent%N==N-2;
  end
 end

 always @(posedge clk) if(rst_n) begin
  cycles=cycles+1;
  if(as_hold && a_bundle!==ah) $fatal(1,"A probe changed while stopped");
  if(bs_hold && b_bundle!==bh) $fatal(1,"B probe changed while stopped");
  if(ms_hold && m_bundle!==mh) $fatal(1,"median changed while stalled");
  if(gs_hold && g_bundle!==gh) $fatal(1,"gaussian changed while stalled");
  if(ss_hold && s_bundle!==sh) $fatal(1,"Sobel output changed while stalled");
  if(os_hold && o_bundle!==oh) $fatal(1,"final output changed while stalled");
  as_hold=dut.gradient_stage.s_valid && !dut.gradient_stage.advance;ah=a_bundle;
  bs_hold=dut.median.valid_pipe[0] && !dut.median.advance;bh=b_bundle;
  ms_hold=dut.mv && !dut.mr;mh=m_bundle;
  gs_hold=dut.gv && !dut.gr;gh=g_bundle;
  ss_hold=dut.sv && !dut.sr;sh=s_bundle;
  os_hold=ov && !ready;oh=o_bundle;
  if(as_hold) astalls=astalls+1;
  if(bs_hold) bstalls=bstalls+1;
  if(ms_hold) mstalls=mstalls+1;
  if(gs_hold) gstalls=gstalls+1;
  if(os_hold) ostalls=ostalls+1;
  if(ss_hold && dut.sl) eol_stalls=eol_stalls+1;
  if(ss_hold && dut.se) eof_stalls=eof_stalls+1;

  if(dut.median.valid_pipe[0] && dut.median.advance) begin
   if(b_now!==b_expected[bc/2]) $fatal(1,"B gradient pixel=%0d got=%h expected=%h",bc,b_now,b_expected[bc/2]);
   check_meta(bc,dut.median.marks[0],dut.median.id_pipe[0],dut.median.epoch_pipe[0]);
   if(dut.median.config_pipe[0]!=={(settings[bc/N][16] && settings[bc/N][13]),settings[bc/N][15:0]}) $fatal(1,"B config");
   $fdisplay(bfileout,"%016h",b_now);if(first_b<0) first_b=cycles;last_b=cycles;bc=bc+2;
  end
  if(dut.mv && dut.mr) begin
   if(dut.med!=={med_expected[mc],med_expected[mc+1]} ||
      dut.original_luma!=={source[mc][31:24],source[mc+1][31:24]} || dut.raw_edge!==raw_edge_expected[mc/2]) $fatal(1,"median/raw edge %0d",mc);
   check_meta(mc,{dut.ms,dut.ml,dut.me},dut.mi,dut.mp);mc=mc+2;
  end
  if(dut.gv && dut.gr) begin
   if(dut.gauss!=={gauss_expected[gc],gauss_expected[gc+1]}) $fatal(1,"gauss pixel=%0d got=%h expected=%h",gc,dut.gauss,{gauss_expected[gc],gauss_expected[gc+1]});
   check_meta(gc,{dut.gs,dut.gl,dut.ge},dut.gi,dut.gp);gc=gc+2;
  end
  if(dut.gradient_stage.s_valid && dut.gradient_stage.advance) begin
   if(a_now!==a_expected[ac/2]) $fatal(1,"A gradient pixel=%0d got=%h expected=%h",ac,a_now,a_expected[ac/2]);
   check_meta(ac,{dut.gradient_stage.s_sof,dut.gradient_stage.s_eol,dut.gradient_stage.s_eof},dut.gradient_stage.s_id,dut.gradient_stage.s_epoch);
   if(dut.gradient_stage.s_flags!==settings[ac/N][12:11] || dut.gradient_stage.s_threshold!==settings[ac/N][10:0]) $fatal(1,"A flags/T");
   $fdisplay(afileout,"%016h",a_now);if(first_a<0) first_a=cycles;last_a=cycles;ac=ac+2;
  end
  if(dut.sv && dut.sr) begin
   if(dut.sobel!=={sobel_expected[sc],sobel_expected[sc+1]} || dut.gradient!==gradient_expected[sc/2] ||
      dut.gradient_stage.out_luma!=={gauss_expected[sc][31:24],gauss_expected[sc+1][31:24]}) $fatal(1,"Sobel output %0d",sc);
   if(dut.gradient_stage.out_flags!==settings[sc/N][12:11] || dut.gradient_stage.out_threshold!==settings[sc/N][10:0]) $fatal(1,"Sobel flags/T");
   check_meta(sc,{dut.ss,dut.sl,dut.se},dut.si,dut.sp);sc=sc+2;
  end
  // Update source after inspecting all old-state handshake signals.
  if(iv && ir) begin sent=sent+2;iv<=0;end
  if(ov && ready) begin
   check_meta(ocount,{os,ol,oe},oid,oepoch);
   if(oc!==settings[ocount/N][15:0]) $fatal(1,"final config");
   ocount=ocount+2;
   if(ocount%N==0) begin
    if(ac!=ocount || bc!=ocount || mc!=ocount || gc!=ocount || sc!=ocount || sent!=ocount) $fatal(1,"count mismatch");
    if(job==JOBS-1) begin
     $fclose(afileout);$fclose(bfileout);
     $display("PASS W=%0d H=%0d jobs=%0d pixels=%0d cycles=%0d A_stalls=%0d B_stalls=%0d M_stalls=%0d G_stalls=%0d O_stalls=%0d eol_stalls=%0d eof_stalls=%0d firstA=%0d firstB=%0d lastA=%0d lastB=%0d",W,H,JOBS,ocount,cycles,astalls,bstalls,mstalls,gstalls,ostalls,eol_stalls,eof_stalls,first_a,first_b,last_a,last_b);
     $finish;
    end else job=job+1;
   end
  end
  if(cycles>timeout_cycles) $fatal(1,"timeout");
 end
endmodule
