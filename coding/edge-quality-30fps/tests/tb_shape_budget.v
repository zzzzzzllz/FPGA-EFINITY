`timescale 1ns/1ps
module tb_shape_budget;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,start=0,mem_done=0;
 wire busy,done,ok,overflow,mem_valid;
 wire [2:0] count;wire [175:0] boxes;wire [7:0] kinds;wire [31:0] cycles;
 reg pending=0;integer delay_left=0,response_delay=40;
 shape_recognizer #(.W(64),.H(1),.MAX_CYCLES(20)) dut(
  .clk(clk),.rst_n(rst_n),.start(start),.slot(2'd0),.busy(busy),.done(done),.ok(ok),
  .count(count),.boxes(boxes),.kinds(kinds),.overflow(overflow),.cycles(cycles),
  .mem_valid(mem_valid),.mem_done(mem_done),.mem_error(1'b0),.mem_result(128'd0));
 always @(posedge clk) begin
  mem_done<=0;
  if(mem_valid) begin
   if(pending) $fatal(1,"overlapping memory requests");
   pending<=1;delay_left<=response_delay;
  end else if(pending) begin
   if(delay_left==0) begin mem_done<=1;pending<=0;end
   else delay_left<=delay_left-1;
  end
  if(done && pending) $fatal(1,"published before memory request drained");
 end
 task launch;begin @(negedge clk);start=1;@(negedge clk);start=0;end endtask
 initial begin
  repeat(4) @(negedge clk);rst_n=1;
  launch;wait(done);#1;
  if(!ok || !overflow || count!=0 || boxes!=0 || kinds!=0 || cycles<40 || cycles>50)
   $fatal(1,"budget did not drain and publish empty overflow result");
  repeat(3) @(negedge clk);response_delay=1;
  launch;wait(done);#1;
  if(!ok || overflow || count!=0 || cycles>=20) $fatal(1,"next frame did not recover");
  $display("PASS shape budget: outstanding request drained, explicit empty overflow, next frame recovers");
  $finish;
 end
 initial begin #10000;$fatal(1,"timeout");end
endmodule
