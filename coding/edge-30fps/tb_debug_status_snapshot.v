`timescale 1ns/1ps
module tb_debug_status_snapshot;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,capture=0;reg [5:0] page=0;
 reg [1904:0] live=0,expected;
 wire capture_ack;wire [5:0] page_ack;wire [63:0] data;
 debug_status_snapshot #(.WIDTH(1905)) dut(.*);
 task tick;@(negedge clk);endtask
 initial begin
  tick;rst_n=1;
  for(integer transaction=0;transaction<4;transaction=transaction+1) begin
   for(integer bitno=0;bitno<1905;bitno=bitno+1) live[bitno]=$random;
   expected=live;capture=~capture;repeat(3) tick;
   if(capture_ack!==capture) $fatal(1,"capture ack");
   // Live fields may change between every page; the returned snapshot must not.
   for(integer p=0;p<30;p=p+1) begin
    live=~live;page=(p*17)%30;repeat(32) tick;
    if(page_ack!==page || data!==64'(expected>>(64*page))) $fatal(1,"snapshot/page mismatch %d",page);
   end
   page=63;repeat(3) tick;if(data!==0) $fatal(1,"out-of-range page");
  end
  $display("PASS snapshot capture, immutable pages, recapture, padding and invalid page");$finish;
 end
endmodule
