`timescale 1ns/1ps
module tb_threshold_control;
 reg clk=0;always #10 clk=~clk;
 reg rst=0,fs=0,minus=1,plus=1,toggle=0;
 reg [10:0] value=32;
 wire [1:0] press_events;wire ack;wire [10:0] pending,active;wire [31:0] epoch,mc,pc;wire [1:0] keys;
 threshold_control #(.DEBOUNCE(5),.HOLD(50),.REPEAT(10)) dut(
  clk,rst,fs,minus,plus,1'b0,1'b1,press_events,value,toggle,ack,pending,active,epoch,mc,pc,keys);
 task cycles(input integer n);repeat(n) @(negedge clk);endtask
 task commit;begin fs=1;cycles(1);fs=0;end endtask
 task set_value(input integer v);begin value=v;toggle=!toggle;cycles(2);end endtask
 task press(input integer increase);
  begin
   if(increase) plus=0;else minus=0;cycles(2);
   minus=1;plus=1;cycles(2);
   if(increase) plus=0;else minus=0;cycles(15);
   minus=1;plus=1;cycles(2);
   if(increase) plus=0;else minus=0;cycles(2);
   minus=1;plus=1;cycles(12);
  end
 endtask
 integer i;
 initial begin
  cycles(4);rst=1;cycles(4);
  for(i=1;i<=10;i=i+1) begin
   press(1);if(pending!=32+i*16 || pc!=i || active!=32) $fatal(1,"plus bounce/commit");
  end
  commit();if(active!=192 || epoch!=1) $fatal(1,"frame commit");
  for(i=1;i<=10;i=i+1) begin
   press(0);if(pending!=192-i*16 || mc!=i || active!=192) $fatal(1,"minus bounce/commit");
  end
  commit();if(active!=32) $fatal(1,"minus commit");
  set_value(2035);press(1);press(1);if(pending!=2040) $fatal(1,"upper wrap");
  set_value(7);press(0);press(0);if(pending!=0) $fatal(1,"lower wrap");
  set_value(2047);if(pending!=2040) $fatal(1,"JTAG clamp");
  set_value(32);plus=0;cycles(43);if(pending!=48) $fatal(1,"early repeat");
  cycles(14);if(pending!=64) $fatal(1,"hold repeat");
  cycles(10);if(pending!=80) $fatal(1,"repeat interval");
  plus=1;cycles(12);set_value(32);if(pending!=32) $fatal(1,"same-value JTAG after keys");
  minus=0;plus=0;cycles(20);if(pending!=32) $fatal(1,"opposite keys conflict");
  set_value(128);commit();if(active!=128) $fatal(1,"JTAG priority");
  $display("PASS control: +/-10, contact bounce, frame commit, saturation, JTAG override, hold/repeat, opposite keys");
  $finish;
 end
endmodule
