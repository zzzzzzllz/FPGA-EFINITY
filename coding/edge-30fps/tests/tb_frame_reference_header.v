`timescale 1ns/1ps
// Toggle the requested view exactly between the DMA snapshot and header latch.
module tb_frame_reference_header;
 reg core=0,pixel=0,video=0,rst=0,period=0;
 always #5 core=~core;always #10 pixel=~pixel;always #7 video=~video;
 frame_store #(.W(32),.H(16),.BURST(16)) dut(
 .rst_n(rst),.core_clk(core),.pixel_clk(pixel),.display_clk(video),.enabled(1'b0),
 .capture_pixels(64'd0),.capture_valid(1'b0),.capture_sof(1'b0),.capture_eof(1'b0),.capture_frame_id(32'd0),
 .config_value(13'd32),.config_epoch(32'd0),.algorithm_ready(1'b0),
 .result_pixels(64'd0),.result_valid(1'b0),.result_sof(1'b0),.result_eof(1'b0),
 .command(4'd0),.command_toggle(1'b0),.reference_mode(1'b0),.display_period(period),
 .display_ready(1'b0),.shown_toggle(1'b0),.shown_slot(2'd0),
 .awready(1'b0),.wready(1'b0),.bvalid(1'b0),.arready(1'b0),.rvalid(1'b0),.rlast(1'b0),
 .bresp(2'd0),.rresp(2'd0),.rdata(128'd0));
 task boundary(input bit selected);
 begin
  @(negedge core);period=1;
  wait(dut.dma.restart_count==16);
  @(negedge core);
  if(selected) force dut.reference_sync=2'b11;else force dut.reference_sync=2'b00;
  @(posedge core);@(negedge core);
  if(selected) force dut.reference_sync=2'b00;else force dut.reference_sync=2'b11;
  @(posedge core);#1;
  if(dut.descriptor[101]!==selected || dut.descriptor[101]!==dut.dma.reference_needed)
   $fatal(1,"REF header differs from latched pixel source");
  release dut.reference_sync;
  @(negedge core);period=0;#300;
 end endtask
 initial begin
  #100;rst=1;
  force dut.read_valid=1;force dut.read_slot=0;
  force dut.display_reference_valid=1;force dut.display_reference_id=42;
  force dut.display_epoch=3;force dut.display_id=77;
  boundary(1);boundary(0);
  $display("PASS: REF metadata matches the DMA frame snapshot at both view-switch boundaries");$finish;
 end
 initial begin #10000;$fatal(1,"timeout");end
endmodule
