`timescale 1ns/1ps
module tb_frame_reader;
 reg clk=0;always #5 clk=~clk;
 reg rst=1,job_valid=0,hold_ready=1,hold_granted=1;
 wire job_ready,hold_valid,held;reg [5:0] job_slot=0;
 reg [31:0] job_frame_id=10,job_epoch=1,job_generation=2,job_source_time_ms=1234;
 wire [133:0] identity,hold_identity;wire [5:0] held_slot;
 reg [31:0] config_epoch=1,config_generation=2;
 reg cmd_valid=0,full_scan=0;wire cmd_ready;
 reg [10:0] cmd_x=0;reg [9:0] cmd_y=0;reg [8:0] cmd_width=1;reg [6:0] cmd_height=1;
 wire pixel_valid,pixel_ready;wire [23:0] rgb0,rgb1;wire [1:0] keep;
 wire [10:0] pixel_x;wire [9:0] pixel_y;wire line_last,cmd_last;
 wire cmd_done_valid;reg cmd_done_ready=1;
 reg finish_valid=0;wire finish_ready;reg [3:0] finish_status=0;
 reg cancel_valid=0;reg [3:0] cancel_status=4;
 wire abort_valid;wire [3:0] abort_status;
 wire burst_valid,burst_ready;wire [31:0] burst_addr;wire [7:0] burst_len;
 wire rsp_valid,rsp_ready,rsp_last;wire [127:0] rsp_data;wire [1:0] rsp_resp;
 wire recover_req;reg recover_ack=1;
 wire release_valid;reg release_ready=1;
 wire job_done_valid;reg job_done_ready=0;wire [3:0] status;
 frame_reader dut(.*);
 reg [127:0] mem10[0:172799],mem11[0:172799];
 string work;
 integer tick=0,bursts=0,pixels=0,commands=0,jobs=0,holds=0,releases=0,reset_clears=0,refs=0;
 integer memory_seed=10,mode=0,index=0,blen=0,base_word=0;
 reg bus_active=0,bus_enable=1,bus_pause=0,bus_abort=0,allow_pixel=1,unsafe_ready=0;
 reg manual_valid=0,manual_last=0;reg [127:0] manual_data=0;
 assign burst_ready=bus_enable && !bus_active && (unsafe_ready || !recover_ack && tick%5!=0);
 assign rsp_valid=manual_valid || (bus_active && !bus_pause && tick%7!=0);
 assign rsp_data=manual_valid ? manual_data : memory_seed==10 ? mem10[base_word+index] : mem11[base_word+index];
 assign rsp_last=manual_valid ? manual_last : mode==2 ? index==0 : mode==3 ? 1'b0 : index==blen;
 assign rsp_resp=mode==1 && index==1 ? 2'b10 : 2'b00;
 assign pixel_ready=allow_pixel && tick%11!=0 && tick%17!=0;
 integer ex=0,ey=0,x0=0,y0=0,ew=0,eh=0,expected_pixels=0,seen_pixels=0;
 integer command_start=0;
 reg checking=0;reg [133:0] expected_identity;
 reg prev_pixel_stall=0,prev_burst_stall=0;reg [72:0] prev_pixel;reg [39:0] prev_burst;
 reg prev_release_stall=0;reg [133:0] prev_release_identity;
 reg [15:0] phase_seen=0;reg boundary_seen=0,abort_seen=0;
 function [23:0] pixel;
  input integer x,y,seed;reg [7:0] r,g,b;
  begin r=x*7+y*13+seed;g=x*11+y*3+seed*3;b=x^(y*17)^(seed*13);pixel={r,g,b};end
 endfunction
 always @(posedge clk) begin
  tick<=tick+1;
  if(rst) begin bus_active<=0;reset_clears=reset_clears+refs;refs=0;prev_pixel_stall=0;prev_burst_stall=0;prev_release_stall=0;checking=0;end
  else begin
   if(hold_valid && hold_ready && hold_granted) begin
    if(refs!=0) $fatal(1,"duplicate hold");refs=refs+1;holds=holds+1;
   end
   if(release_valid && release_ready) begin
    if(refs!=1 || !held || dut.outstanding || dut.offer) $fatal(1,"unsafe release");
    refs=refs-1;releases=releases+1;
   end
   if(job_valid && job_ready) expected_identity={job_slot,job_frame_id,job_epoch,job_generation,job_source_time_ms};
   if(held && identity!==expected_identity) $fatal(1,"identity changed");
   if(cmd_valid && cmd_ready && finish_valid && finish_ready) $fatal(1,"two commands accepted");
   if(cmd_valid && cmd_ready) command_start=tick;
   if(abort_valid) begin checking=0;abort_seen=1;end
   if(prev_pixel_stall && !abort_valid && (!pixel_valid || prev_pixel!=={rgb0,rgb1,keep,pixel_x,pixel_y,line_last,cmd_last}))
    $fatal(1,"pixel changed under backpressure");
   if(prev_burst_stall && !dut.ack_ok && (!burst_valid || prev_burst!=={burst_addr,burst_len}))
    $fatal(1,"request changed before accepted/recovered");
   prev_pixel_stall=pixel_valid && !pixel_ready;
   prev_pixel={rgb0,rgb1,keep,pixel_x,pixel_y,line_last,cmd_last};
   prev_burst_stall=burst_valid && !burst_ready && !dut.ack_ok;
   prev_burst={burst_addr,burst_len};
   if(prev_release_stall && !dut.fault_now && !recover_req &&
      (!release_valid || identity!==prev_release_identity)) $fatal(1,"release changed under backpressure");
   prev_release_stall=release_valid && !release_ready;
   prev_release_identity=identity;
   if(rsp_valid && !rsp_ready) $fatal(1,"response blocked by consumer");
   if(dut.ack_ok && (rsp_valid || burst_valid && burst_ready)) $fatal(1,"unsafe recovery confirmation");
   if(burst_valid && burst_ready) begin
    if(bus_active || !held || burst_len>31 || burst_addr[3:0]!=0 ||
       {1'b0,burst_addr[11:0]}+({5'b0,burst_len}+13'd1)*16>4096)
     $fatal(1,"invalid/reservation/overlapping burst");
    if(burst_addr<held_slot*32'h300000 || burst_addr+(burst_len+1)*16>held_slot*32'h300000+2764800)
     $fatal(1,"read outside completed frame");
    base_word=(burst_addr-held_slot*32'h300000)/16;index<=0;blen=burst_len;bus_active<=1;bursts=bursts+1;
    if(burst_addr[11:0]+(burst_len+1)*16==4096) boundary_seen=1;
   end
   if(rsp_valid && rsp_ready && !manual_valid && bus_active) begin
    if(index==blen || mode==2 && index==0 || mode==4 && index==1) bus_active<=0;
    else index<=index+1;
   end
   if(bus_abort) bus_active<=0;
   if(pixel_valid && pixel_ready) begin
    if(!checking) $fatal(1,"unexpected pixel after abort/without command");
    if(pixel_x!==ex || pixel_y!==ey || rgb0!==pixel(ex,ey,memory_seed))
     $fatal(1,"pixel0 x%0d y%0d got%h expected%h xy%0d,%0d",ex,ey,rgb0,pixel(ex,ey,memory_seed),pixel_x,pixel_y);
    if(keep!==(ex+1<x0+ew ? 2'b11 : 2'b01)) $fatal(1,"keep");
    if(rgb1!==(keep==3 ? pixel(ex+1,ey,memory_seed) : 24'd0)) $fatal(1,"pixel1");
    if(line_last!==(ex+(keep==3 ? 2 : 1)==x0+ew) || cmd_last!==(line_last && ey==y0+eh-1))
     $fatal(1,"last markers");
    seen_pixels=seen_pixels+(keep==3 ? 2 : 1);pixels=pixels+(keep==3 ? 2 : 1);
    if(line_last) begin ex=x0;ey=ey+1;end else ex=ex+2;
   end
   if(cmd_done_valid && cmd_done_ready) begin
    if(!checking || seen_pixels!=expected_pixels || dut.outstanding || dut.offer)
     $fatal(1,"incomplete command got%0d expected%0d",seen_pixels,expected_pixels);
    if(ew==1280) $display("METRIC full scan pixels=%0d cycles=%0d",seen_pixels,tick-command_start);
    checking=0;commands=commands+1;
   end
  end
 end
 task new_job(input integer slot,seed);
  begin
   memory_seed=seed;abort_seen=0;
   @(negedge clk);job_slot=slot;job_frame_id=seed;job_epoch=config_epoch;job_generation=config_generation;
   job_source_time_ms=1234+seed;job_valid=1;
   do @(posedge clk);while(!job_ready);
   @(negedge clk);job_valid=0;
  end
 endtask
 task command(input integer x,y,w,h);
  begin
   @(negedge clk);cmd_x=x;cmd_y=y;cmd_width=w;cmd_height=h;full_scan=w==1280;cmd_valid=1;
   x0=x;y0=y;ew=w;eh=h;ex=x;ey=y;expected_pixels=w*h;seen_pixels=0;checking=1;
   phase_seen[(3*x)%16]=1;
   do @(posedge clk);while(!cmd_ready);
   @(negedge clk);cmd_valid=0;
  end
 endtask
 task complete_command;
  begin
   wait(cmd_done_valid);@(posedge clk);@(negedge clk);
  end
 endtask
 task complete_job(input integer expected_status);
  begin
   wait(job_done_valid);@(negedge clk);
   if(status!==expected_status || held || refs!=0) $fatal(1,"job result %0d expected%0d refs%0d",status,expected_status,refs);
   job_done_ready=1;@(posedge clk);@(negedge clk);job_done_ready=0;jobs=jobs+1;
  end
 endtask
 task finish_job;
  begin
   @(negedge clk);finish_valid=1;
   do @(posedge clk);while(!finish_ready);
   @(negedge clk);finish_valid=0;complete_job(finish_status);
  end
 endtask
 task recovery;
  begin
   wait(recover_req);
   @(negedge clk);bus_abort=1;recover_ack=0;
   repeat(3) @(negedge clk);
   bus_abort=0;recover_ack=1;
   wait(!recover_req);@(negedge clk);recover_ack=0;
  end
 endtask
 task cancel_job(input integer code);
  begin @(negedge clk);cancel_status=code;cancel_valid=1;@(negedge clk);cancel_valid=0;end
 endtask
 integer f,rc,x,y,w,h,k,prior;
 initial begin
  if(!$value$plusargs("WORK=%s",work)) $fatal(1,"WORK missing");
  $readmemh({work,"/rgb-10.mem"},mem10);$readmemh({work,"/rgb-11.mem"},mem11);
  repeat(4) @(negedge clk);rst=0;
  repeat(6) @(negedge clk);
  if(job_ready || !recover_req) $fatal(1,"stale reset ack accepted");
  recovery();
  new_job(40,10);
  if(!$test$plusargs("QUICK")) begin
  f=$fopen({work,"/cases.txt"},"r");
  while(!$feof(f)) begin
   rc=$fscanf(f,"%d %d %d %d\n",x,y,w,h);
   if(rc==4) begin command(x,y,w,h);complete_command();end
  end
  $fclose(f);
  if(phase_seen!==16'hffff || !boundary_seen) $fatal(1,"coverage phases/boundary");
  end else begin command(85,1,320,2);complete_command();end
  finish_job();
  $display("PASS normal commands=%0d, %0d exact pixels, %0d bursts",commands,pixels,bursts);
  new_job(3,11);command(83,1,319,3);complete_command();command(1279,719,1,1);complete_command();finish_job();
  // Invalid slot must never reach the reference allocator.
  prior=holds;new_job(63,10);complete_job(8);if(holds!=prior) $fatal(1,"held illegal slot");
  hold_granted=0;new_job(1,10);complete_job(7);hold_granted=1;
  // A grant concurrent with cancellation still has exactly one release.
  cancel_valid=1;cancel_status=4;new_job(1,10);cancel_valid=0;complete_job(4);
  // Maximum input fields exercise explicitly widened bounds arithmetic.
  for(k=0;k<6;k=k+1) begin
   new_job(1,10);
   case(k)
    0: command(2047,0,320,1);
    1: command(0,1023,1,96);
    2: command(1279,719,2,1);
    3: command(0,0,0,1);
    4: command(0,0,511,1);
    5: command(0,0,1,127);
   endcase
   complete_job(8);
  end
  // finish outranks a simultaneous command.
  new_job(1,10);@(negedge clk);finish_valid=1;cmd_valid=1;
  @(posedge clk);if(!finish_ready || cmd_ready) $fatal(1,"finish priority");
  @(negedge clk);finish_valid=0;cmd_valid=0;complete_job(0);
  // Consumer can stop for thousands of clocks without blocking the read response.
  new_job(1,10);allow_pixel=0;command(85,1,320,4);wait(pixel_valid);
  prior=bursts;repeat(2000) @(negedge clk);
  if(bus_active || dut.outstanding || bursts!=prior) $fatal(1,"backpressure occupied bus");
  cancel_job(4);complete_job(4);allow_pixel=1;
  // Mid-burst RRESP error can naturally drain if its length and last are correct.
  mode=1;new_job(1,10);command(0,0,320,1);complete_job(9);mode=0;
  // Early/missing last cannot authorize release, even after a stale high ack.
  for(k=2;k<=4;k=k+1) begin
   mode=k;recover_ack=1;new_job(1,10);recover_ack=0;
   command(0,0,320,1);wait(!bus_active && dut.outstanding);
   if(k==4) cancel_job(5);
   wait(recover_req);recover_ack=1;
   // Force a response coincident with ack; the ack must be rearmed afterwards.
   @(negedge clk);manual_valid=1;manual_last=0;
   @(negedge clk);manual_valid=0;
   repeat(20) @(negedge clk);
   if(refs!=1 || release_valid || job_ready || !recover_req) $fatal(1,"unsafe fault release");
   recovery();complete_job(k==4 ? 5 : 10);mode=0;
  end
  // Cancel an offered request, then collide request acceptance with recovery ack.
  new_job(1,10);bus_enable=0;command(0,0,320,1);wait(burst_valid);
  cancel_job(5);repeat(4) @(negedge clk);
  bus_pause=1;unsafe_ready=1;bus_enable=1;recover_ack=1;
  @(negedge clk);unsafe_ready=0;
  repeat(4) @(negedge clk);
  if(!held || !recover_req || release_valid) $fatal(1,"ack/request race");
  recovery();bus_pause=0;complete_job(5);
  // Late extra response during pixel unpack must invalidate the current job.
  new_job(1,10);allow_pixel=0;command(0,0,32,1);wait(pixel_valid);
  @(negedge clk);manual_valid=1;manual_last=1;
  @(negedge clk);manual_valid=0;
  if(!abort_valid || !recover_req) $fatal(1,"late response missed");
  recovery();complete_job(10);allow_pixel=1;
  // Epoch changes are visible to the consumer in the same cycle they cancel.
  new_job(1,10);command(0,0,32,1);wait(pixel_valid);
  @(negedge clk);config_epoch=config_epoch+1;
  #1;if(!abort_valid || abort_status!=6 || pixel_valid) $fatal(1,"configuration cancel notification");
  complete_job(6);
  // A valid frame after every fault must not receive an old pixel.
  new_job(0,11);command(85,1,31,2);complete_command();finish_job();
  // Cancellation/configuration change preserves an offered release and its handshake.
  for(k=0;k<4;k=k+1) begin
   new_job(1,10);prior=releases;
   release_ready=0;
   @(negedge clk);finish_valid=1;
   @(negedge clk);finish_valid=0;
   if(!release_valid) $fatal(1,"missing release offer for race");
   repeat(3) @(negedge clk);
   if(k%2==0) begin cancel_valid=1;cancel_status=4;end else config_epoch=config_epoch+1;
   release_ready=k<2;
   #1;if(!release_valid || !abort_valid) $fatal(1,"release withdrawn on cancel");
   @(negedge clk);cancel_valid=0;
   if(k>=2) begin
    repeat(3) @(negedge clk);
    if(!release_valid || !held) $fatal(1,"release lost during cancel backpressure");
    release_ready=1;
   end
   complete_job(k%2==0 ? 4 : 6);
   if(releases!=prior+1) $fatal(1,"release race count");
  end
  // Mismatched configuration at grant still owns and releases the granted reference.
  @(negedge clk);job_valid=1;job_slot=1;job_epoch=config_epoch-1;
  do @(posedge clk);while(!job_ready);
  @(negedge clk);job_valid=0;complete_job(6);
  // Cancel wins over both finish and command without either handshake.
  new_job(1,10);@(negedge clk);cancel_valid=1;finish_valid=1;cmd_valid=1;
  #1;if(finish_ready || cmd_ready || !abort_valid) $fatal(1,"cancel priority");
  @(negedge clk);cancel_valid=0;finish_valid=0;cmd_valid=0;complete_job(4);
  // Hold release under allocator backpressure; a persistent cancel must not deadlock it.
  new_job(1,10);release_ready=0;cancel_job(4);wait(release_valid);
  repeat(40) @(negedge clk);
  if(!held || refs!=1 || job_done_valid) $fatal(1,"release backpressure");
  release_ready=1;complete_job(4);
  // A cancelled, already accepted burst may naturally finish without reset acknowledgement.
  new_job(1,10);bus_pause=1;command(0,0,320,1);wait(dut.outstanding);
  cancel_job(4);bus_pause=0;complete_job(4);
  // Unexpected responses in WAIT_CMD, RELEASE, DONE and IDLE are all quarantined.
  for(k=0;k<4;k=k+1) begin
   if(k!=3) new_job(1,10);
   if(k==1 || k==2) begin
    release_ready=k==2;@(negedge clk);finish_valid=1;
    @(negedge clk);finish_valid=0;
    if(k==1) wait(release_valid);else wait(job_done_valid);
   end
   @(negedge clk);manual_valid=1;manual_last=1;
   #1;if(release_valid || job_done_valid || job_ready) $fatal(1,"late response accepted terminal handshake");
   @(negedge clk);manual_valid=0;
   repeat(10) @(negedge clk);
   if(!recover_req) $fatal(1,"late response not recovered state%0d",k);
   recovery();release_ready=1;
   if(k!=3) complete_job(10);
  end
  // Coordinated reset clears the external reference table; stale acknowledgement stays blocked.
  new_job(1,10);bus_pause=1;command(0,0,320,1);wait(dut.outstanding);
  @(negedge clk);rst=1;recover_ack=1;
  repeat(3) @(negedge clk);rst=0;bus_pause=0;
  repeat(10) @(negedge clk);
  if(job_ready || !recover_req) $fatal(1,"reset stale ack");
  recovery();
  new_job(0,11);command(85,1,31,2);complete_command();finish_job();
  if(refs!=0 || holds!=releases+reset_clears) $fatal(1,"reference leak %0d/%0d reset%0d",holds,releases,reset_clears);
  $display("PASS jobs=%0d holds=%0d releases=%0d reset_clears=%0d commands=%0d pixels=%0d bursts=%0d",jobs,holds,releases,reset_clears,commands,pixels,bursts);
  $finish;
 end
 initial begin #300000000;$fatal(1,"timeout state=%0d job=%0d mode=%0d refs=%0d",dut.state,jobs,mode,refs);end
endmodule
