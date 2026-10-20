`timescale 1ns/1ps
`include "plate_defs.vh"
`include "test_ids.vh"
module tb_plate_state #(parameter SRC_HALF=5,DST_HALF=7);
 reg sc=0,dc=0,run_src=1,run_dst=1,rst=0;
 always #(SRC_HALF) if(run_src) sc=~sc;else sc=0;
 always #(DST_HALF) if(run_dst) dc=~dc;else dc=0;
 reg [31:0] now_ms=1000,epoch=1,generation=1;
 reg iv=0,fs=0,accept=1;reg [`PD_BITS-1:0] ip=0;
 wire ir;wire [`PD_BITS:0] active;wire [1:0] count;wire [31:0] dnow;
 wire display_rst;
 plate_display_state dut(rst,sc,dc,now_ms,epoch,generation,iv,ir,ip,fs,accept,active,count,dnow,display_rst);
 integer checks=0;
 reg [`PD_BITS:0] previous,held_output,held_cdc;
 reg stalled_output=0,stalled_cdc=0;
 always @(posedge dc) begin
  #1;
  if(dut.drst && !fs && active!==previous) $fatal(1,"active changed in middle of display frame");
  previous=active;
 end
 always @(posedge sc) begin
  if(dut.srst) begin
   if(stalled_output && dut.packet!==held_output) $fatal(1,"confirmation output changed under backpressure");
   if(stalled_cdc && dut.results.held!==held_cdc) $fatal(1,"CDC held bus changed before ack");
   held_output=dut.packet;stalled_output=dut.valid&&!dut.ready;
   held_cdc=dut.results.held;stalled_cdc=!dut.ready;
  end else begin stalled_output=0;stalled_cdc=0;end
 end
 task settle;begin repeat(40) @(negedge dc);end endtask
 task boundary;begin @(negedge dc);fs=1;@(negedge dc);fs=0;checks=checks+1;end endtask
 task expect_count(input integer n);begin if(count!==n) $fatal(1,"count=%d expected=%d",count,n);checks=checks+1;end endtask
 task shown(input bit valid,input [48:0] ids);begin
  boundary();if(active[`PD_BITS]!==valid) $fatal(1,"display valid=%d expected=%d frame=%d count=%d",active[`PD_BITS],valid,active[`PD_FRAME],count);
  if(valid && active[`PD_IDS]!==ids) $fatal(1,"torn/wrong seven IDs");
  if(!valid && active[`PD_IDS]!=={7{7'h7f}}) $fatal(1,"invalid IDs not cleared");
 end endtask
 task tick(input integer n);integer j;begin for(j=0;j<n;j=j+1) begin @(negedge sc);now_ms=now_ms+1;end settle();end endtask
 function [`PD_BITS-1:0] pack(input [31:0] frame,stamp,input [48:0] ids,input [7:0] status,input integer x,y,w,h,input [31:0] ep,gen);
  reg [`PD_BITS-1:0] p;integer k;
  begin p=0;p[`PD_VERSION]=1;p[`PD_STATUS]=status;p[`PD_FRAME]=frame;p[`PD_TIME]=stamp;
   p[`PD_EPOCH]=ep;p[`PD_GENERATION]=gen;p[`PD_IDS]=ids;p[`PD_X]=x;p[`PD_Y]=y;p[`PD_W]=w;p[`PD_H]=h;
   p[`PD_TASK_MS]=37;
   for(k=0;k<7;k=k+1) begin p[`PD_SCORES_LSB+k*32 +:32]=-1000-frame-k;p[`PD_MARGINS_LSB+k*32 +:32]=4000+frame+k;end
   pack=p;
  end
 endfunction
 task send_packet(input [`PD_BITS-1:0] p);integer timeout;begin
  @(negedge sc);ip=p;iv=1;timeout=0;
  @(posedge sc);while(!ir) begin @(posedge sc);timeout=timeout+1;if(timeout>10000)$fatal(1,"input deadlock");end
  @(negedge sc);iv=0;
 end endtask
 task send(input [31:0] f,t,input [48:0] ids,input [7:0] status,input integer x);begin
  send_packet(pack(f,t,ids,status,x,300,200,60,epoch,generation));settle();
 end endtask
 task reset_all(input [31:0] time_value);begin
  rst=0;iv=0;fs=0;accept=1;now_ms=time_value;
  #31;rst=1;settle();
 end endtask
 reg [`PD_BITS:0] expected;reg [48:0] invalid_ids;integer burst;time config_changed;
 initial begin
  #3000000;$fatal(1,"test timeout");
 end
 initial begin
  reset_all(1000);
  send(10,1000,`TEST_A,`PD_OK,100);expect_count(1);shown(0,0);
  send(10,1000,`TEST_B,`PD_OK,600);expect_count(1);
  send(11,1000,`TEST_A,`PD_OK,110);expect_count(2);
  send(9,1000,`TEST_B,`PD_REJECT,100);expect_count(2);
  send(12,1000,`TEST_A,`PD_OK,120);expect_count(3);
  if(active[`PD_BITS])$fatal(1,"published before frame boundary");
  shown(1,`TEST_A);
  expected={1'b1,pack(12,1000,`TEST_A,`PD_OK,120,300,200,60,epoch,generation)};
  if(active!==expected)$fatal(1,"full metadata/score packet mismatch");
  send(13,1000,`TEST_B,`PD_OK,120);expect_count(1);
  if(!active[`PD_BITS])$fatal(1,"cleared midframe");shown(0,0);
  send(14,1000,`TEST_B,`PD_OK,130);send(15,1000,`TEST_B,`PD_OK,140);shown(1,`TEST_B);
  send(16,1000,`TEST_B,`PD_OK,150);expect_count(3);
  send(17,1000,`TEST_B,`PD_OK,190);expect_count(3); // continuous moving target
  send(18,1000,`TEST_B,`PD_OK,500);expect_count(1);shown(0,0);
  send(19,1000,`TEST_B,`PD_OK,500);send(20,1000,`TEST_B,`PD_OK,500);shown(1,`TEST_B);
  send(21,1000,`TEST_B,`PD_REJECT,500);expect_count(0);shown(0,0);
  send(22,1000,`TEST_A,`PD_OK,100);send(23,1000,`TEST_A,`PD_OK,100);send(24,1000,`TEST_A,`PD_OK,100);shown(1,`TEST_A);
  tick(499);if(dnow!=1499)$fatal(1,"Gray time mismatch");shown(1,`TEST_A);
  send(24,1499,`TEST_A,`PD_OK,100); // forged fresher timestamp, same source frame
  if(dut.confirm.support_time!=1000)$fatal(1,"duplicate extended lifetime");
  tick(1);expect_count(0);shown(0,0);
  send(24,1500,`TEST_A,`PD_OK,100);expect_count(0);shown(0,0);
  send(25,1000,`TEST_A,`PD_OK,100);send(26,1000,`TEST_A,`PD_OK,100);send(27,1000,`TEST_A,`PD_OK,100);expect_count(0);
  send(28,1501,`TEST_A,`PD_OK,100);expect_count(0); // future time
  tick(10);send(29,1510,`TEST_A,`PD_OK,100);expect_count(1);
  send(30,1509,`TEST_A,`PD_OK,100);expect_count(0); // increasing frame, decreasing time
  send(31,1510,`TEST_A,`PD_OK,100);send(32,1510,`TEST_A,`PD_OK,100);send(33,1510,`TEST_A,`PD_OK,100);shown(1,`TEST_A);
  // An old confirmed packet in flight cannot block independent configuration invalidation.
  accept=0;send_packet(pack(34,1510,`TEST_A,`PD_OK,100,300,200,60,epoch,generation));settle();
  @(negedge sc);generation=2;settle();expect_count(0);shown(0,0);
  if(dut.display_config!={epoch,generation})$fatal(1,"configuration blocked by result backpressure");
  accept=1;settle();shown(0,0); // old held packet and then clear message
  send_packet(pack(35,1510,`TEST_A,`PD_OK,100,300,200,60,epoch,1));settle();expect_count(0);shown(0,0);
  send(1,1510,`TEST_B,`PD_OK,100);send(2,1510,`TEST_B,`PD_OK,100);send(3,1510,`TEST_B,`PD_OK,100);shown(1,`TEST_B);
  // A clear event cannot be overwritten by three later successes before the next display frame.
  send(4,1510,`TEST_B,`PD_NO_TARGET,100);
  send(5,1510,`TEST_B,`PD_OK,100);send(6,1510,`TEST_B,`PD_OK,100);send(7,1510,`TEST_B,`PD_OK,100);
  shown(0,0);shown(1,`TEST_B);
  @(negedge sc);epoch=2;settle();shown(0,0);expect_count(0);
  invalid_ids=`TEST_A;invalid_ids[7 +:7]=65;
  send(1,1510,invalid_ids,`PD_OK,100);expect_count(0);
  send_packet(pack(2,1510,`TEST_A,`PD_OK,1200,300,200,60,epoch,generation));settle();expect_count(0);
  send(3,1510,`TEST_A,`PD_ERROR,100);expect_count(0);
  ip=pack(4,1510,`TEST_A,`PD_OK,100,300,200,60,epoch,generation);ip[`PD_VERSION]=2;send_packet(ip);settle();expect_count(0);
  // Time and frame number wrap are legitimate, using half-range ordering.
  epoch=3;generation=1;reset_all(32'hfffffff0);
  send(32'hfffffffe,now_ms,`TEST_A,`PD_OK,100);tick(5);
  send(32'hffffffff,now_ms,`TEST_A,`PD_OK,105);tick(32);
  send(0,now_ms,`TEST_A,`PD_OK,110);expect_count(3);shown(1,`TEST_A);
  if(dnow!=21)$fatal(1,"time wrap decode: %d",dnow);
  send(32'hffffffff,now_ms,`TEST_B,`PD_REJECT,100);expect_count(3);
  // Stop destination, reset both asynchronously, release at different local clock edges.
  @(negedge dc);run_dst=0;#20;rst=0;#31;now_ms=0;rst=1;
  repeat(50) @(negedge sc);
  if(dut.drst!==0 || active!==0)$fatal(1,"stopped destination reset failed");
  run_dst=1;settle();expect_count(0);shown(0,0);
  // New CDC packet and frame boundary on exactly the same destination edge.
  send(1,0,`TEST_A,`PD_OK,100);send(2,0,`TEST_A,`PD_OK,100);
  send_packet(pack(3,0,`TEST_A,`PD_OK,100,300,200,60,epoch,generation));
  @(negedge dc);while(!dut.received) @(negedge dc);
  expected=dut.received_packet;fs=1;@(negedge dc);fs=0;
  if(active!==expected || !active[`PD_BITS])$fatal(1,"same-cycle boundary dropped new packet");checks=checks+1;
  // Destination halted while a transfer is in flight, then resumed without reset.
  @(negedge dc);run_dst=0;
  send_packet(pack(4,0,`TEST_A,`PD_OK,100,300,200,60,epoch,generation));
  repeat(50) @(negedge sc);if(ir)$fatal(1,"halted destination did not backpressure");
  run_dst=1;settle();shown(1,`TEST_A);
  // Rapid monotonic configuration changes can coalesce; final state is bounded independently of stalled results.
  accept=0;send_packet(pack(5,0,`TEST_A,`PD_OK,100,300,200,60,epoch,generation));settle();
  for(burst=2;burst<=40;burst=burst+1)begin @(negedge sc);generation=burst;if(burst==20)epoch=4;end
  config_changed=$time;
  @(negedge dc);while(dut.display_config!={epoch,generation})begin
   if($time-config_changed>32*(SRC_HALF+DST_HALF))$fatal(1,"config exceeded 16 source + 16 destination cycle bound");
   @(negedge dc);
  end
  $display("Configuration final value observed after %0t; bound %0d ns; clocks %0d/%0d ns",$time-config_changed,32*(SRC_HALF+DST_HALF),2*SRC_HALF,2*DST_HALF);
  shown(0,0);accept=1;
  repeat(10)begin settle();shown(0,0);end
  send(1,0,`TEST_A,`PD_OK,100);send(2,0,`TEST_A,`PD_OK,100);send(3,0,`TEST_A,`PD_OK,100);shown(1,`TEST_A);
  send_packet(pack(4,0,`TEST_A,`PD_REJECT,100,300,200,60,epoch,generation));
  @(negedge dc);while(!dut.received)@(negedge dc);
  fs=1;@(negedge dc);fs=0;if(active[`PD_BITS])$fatal(1,"same-cycle clear lost");checks=checks+1;
  // Symmetric reset with the source clock stopped; no support for independent domain resets is claimed.
  @(negedge sc);run_src=0;#20;rst=0;#31;rst=1;
  repeat(50)@(negedge dc);
  if(dut.srst!==0 || active!==0)$fatal(1,"stopped source reset failed");
  run_src=1;settle();expect_count(0);shown(0,0);
  $display("PASS plate state: %0d checks; order, repeats, 499/500ms, future/wrap, config in flight, sticky clear, async clocks, backpressure, stop/reset and frame atomicity",checks);
  $finish;
 end
endmodule
