`timescale 1ns/1ps
module tb_frame_publish;
 reg clk=0;always #5 clk=~clk;
 reg rst=0,start=0,fifo_reset=1,write_en=0,bvalid=0;
 wire awvalid,wvalid,wlast,done;
 wire [7:0] awlen;
 integer sent=0,responses=0;
 ddr_wr_buffer1 #(.AXI_DATA_WIDTH(128),.AXI_ADDR_WIDTH(32),.BURST_LEN(127)) dut(
  .axi_clk(clk),.rst_n(rst),.start(start),.start_addr(32'd0),.total_burst_len(25'd256),
  .wr_fifo_rst_p(fifo_reset),.wr_fifo_wrclk(clk),.wr_fifo_wren(write_en),.wr_fifo_wrdata(128'd0),
  .awvalid(awvalid),.awlen(awlen),.awready(1'b1),.wvalid(wvalid),.wlast(wlast),.wready(1'b1),
  .bvalid(bvalid),.bid(6'd0),.bank_sw(done),.bank_sw_ack(1'b0));
 always @(posedge clk) if(rst) begin
  if(wvalid && wlast) sent=sent+1;
  if(done && responses!=2) $fatal(1,"frame published before final response");
 end
 initial begin
  repeat(10) @(negedge clk);rst=1;fifo_reset=0;
  repeat(20) @(negedge clk);start=1;
  repeat(20) @(negedge clk);start=0;write_en=1;
  repeat(256) @(negedge clk);write_en=0;
  wait(sent==2);
  repeat(20) @(negedge clk);
  if(done) $fatal(1,"published without B responses");
  bvalid=1;responses=1;@(negedge clk);bvalid=0;
  repeat(20) @(negedge clk);
  if(done) $fatal(1,"published after first B response");
  bvalid=1;responses=2;@(negedge clk);bvalid=0;
  repeat(3) @(negedge clk);
  if(!done) $fatal(1,"final B response did not publish frame");
  $display("PASS frame publication waits for both delayed B responses");$finish;
 end
 initial begin #100000;$fatal(1,"timeout sent=%0d state=%0d burstnum=%0d len=%0d fifo=%0d awvalid=%b wvalid=%b",sent,dut.state,dut.burst_num,awlen,dut.wr_fifo_rdusedw,awvalid,wvalid); end
endmodule
