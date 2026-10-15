`timescale 1ns/1ps
module tb_frame_store_control;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,enabled=1,command_valid=0;
 reg [3:0] command=0;wire command_ack;
 reg [31:0] config_epoch=0,capture_id=0;
 reg capture_start=0,capture_done=0,capture_ok=1,job_done=0,job_ok=1;
 reg display_start=0,display_end=0,shown_valid=0;
 reg [1:0] shown_slot=0;
 wire capture_accept,job_start,display_valid,reference_valid;
 wire [5:0] capture_slot,job_source,recorded,reference_slot;
 wire [1:0] job_result,display_slot;
 wire display_reference_valid;wire [5:0] display_reference_slot;
 wire [31:0] display_id,display_epoch,display_reference_id;
 wire [31:0] job_id,job_epoch,reference_id,shown_id,shown_epoch,ignored_frames,skipped_frames,failed_frames,generation;
 wire [2:0] mode;wire [4:0] playback_index;wire [3:0] command_error;
 frame_store_control #(.PLAY_PERIOD(20)) dut(.*);
 reg [40:0] recorded_reference;
 always @(negedge clk) if(rst_n) begin
  recorded_reference=0;
  for(integer c=0;c<32;c=c+1) if(c<recorded) recorded_reference[dut.clip[c]]=1;
  if(dut.recorded_slots!==recorded_reference) $fatal(1,"recorded slot bitmap diverged from clip references");
 end
 integer n;reg [31:0] frozen_id;reg [5:0] pinned;
 task tick;begin @(negedge clk);end endtask
 task cmd(input [3:0] value);begin
  tick;command=value;command_valid=1;tick;command_valid=0;tick;
  if(!command_ack && command_error) $fatal(1,"command error");
 end endtask
 task capture(input [31:0] id_value);begin
  tick;capture_id=id_value;capture_start=1;tick;capture_start=0;
  if(!capture_accept) $fatal(1,"capture refused %d mode%d",id_value,mode);
  if(reference_valid && capture_slot==reference_slot) $fatal(1,"reference overwritten");
  repeat(3) tick;capture_done=1;tick;capture_done=0;
 end endtask
 task finish_job;begin
  wait(dut.job_busy);repeat(3) tick;job_done=1;tick;job_done=0;tick;
 end endtask
 task show;begin
  tick;display_start=1;tick;display_start=0;tick;
  if(!display_valid) $fatal(1,"no display frame");
  // Read completes before HDMI starts: slot must remain referenced.
  display_end=1;tick;display_end=0;repeat(5) tick;
  if(!dut.result_valid[display_slot]) $fatal(1,"prefetched result released before HDMI");
  shown_slot=display_slot;shown_valid=1;tick;shown_valid=0;tick;
 end endtask
 initial begin
  repeat(4) tick;rst_n=1;
  capture(100);finish_job;show;
  if(shown_id!=100) $fatal(1,"wrong live source");
  cmd(2);frozen_id=shown_id;
  repeat(10) begin tick;capture_start=1;tick;capture_start=0;end
  if(shown_id!=frozen_id || dut.job_busy || ignored_frames!=10) $fatal(1,"freeze changed");
  config_epoch=1;finish_job;show;
  if(shown_id!=100 || shown_epoch!=1) $fatal(1,"reprocess changed source/version");
  cmd(8);pinned=reference_slot;
  cmd(3);capture(123);finish_job;show;
  if(mode!=1 || shown_id!=123 || reference_id!=100) $fatal(1,"step/reference wrong");
  cmd(4);
  for(n=0;n<32;n=n+1) begin
   capture(200+n);
   if(n!=31) begin finish_job;show;end
  end
  finish_job;show;
  if(recorded!=32 || mode!=4 || shown_id!=200) $fatal(1,"record stop/start wrong");
  for(n=1;n<32;n=n+1) begin
   cmd(7);finish_job;show;
   if(shown_id!=200+n) $fatal(1,"clip order %d %d",n,shown_id);
  end
  cmd(7);finish_job;show;
  if(shown_id!=200) $fatal(1,"loop failed");
  cmd(5);
  for(n=0;n<64;n=n+1) begin
   finish_job;show;
   if(shown_id!=200+n%32) $fatal(1,"continuous replay order");
  end
  cmd(6);frozen_id=shown_id;
  repeat(100) tick;
  if(shown_id!=frozen_id) $fatal(1,"pause moved");
  // Explicit recording frees the old clip but preserves the independent ref.
  cmd(4);capture(400);finish_job;show;
  if(reference_id!=100 || reference_slot!=pinned || recorded!=1) $fatal(1,"reference lost");
  cmd(1);capture(500);wait(dut.job_busy);cmd(2);finish_job;
  if(dut.ready_valid) $fatal(1,"late job published after source change");
  // A pending display result must not stall the next live job in a free slot.
  cmd(1);capture(600);finish_job;
  capture(601);repeat(4) tick;
  if(!dut.job_busy || dut.job_id!=601 || dut.job_result==dut.ready_slot || dut.job_result==dut.actual_slot)
   $fatal(1,"live job stalled behind display or reused a held slot");
  show;
  if(shown_id!=600) $fatal(1,"pending display frame replaced by unfinished job");
  finish_job;show;
  if(shown_id!=601) $fatal(1,"overlapped live job missing");
  if(failed_frames || skipped_frames) $fatal(1,"unexpected failures/skips");
  $display("PASS: frame references, freeze/reprocess, step, 32 frames, wrap, independent reference, late result isolation");
  $finish;
 end
 initial begin #1000000;$fatal(1,"timeout mode%d job%b ready%b",mode,dut.job_busy,dut.ready_valid);end
endmodule
