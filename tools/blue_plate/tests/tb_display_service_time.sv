`timescale 1ns/1ps
`include "plate_defs.vh"
// Read-only timing probe of the existing confirmation module, with no output
// backpressure. Twenty clocks per modeled millisecond preserve handshake order.
module tb_display_service_time;
 reg clk=0,rst_n=0;always #5 clk=~clk;
 reg [31:0] now_ms=1000;
 reg iv=0;wire ir,ov,confirmed;wire [1:0] count;
 reg [`PD_BITS-1:0] ip=0;wire [`PD_BITS:0] op;
 plate_confirm dut(.clk(clk),.rst_n(rst_n),.now_ms(now_ms),.current_epoch(32'd1),.current_generation(32'd1),
  .in_valid(iv),.in_ready(ir),.in_packet(ip),.out_valid(ov),.out_ready(1'b1),.out_packet(op),.count(count),.confirmed(confirmed));
 function [`PD_BITS-1:0] packet(input integer frame,stamp,latency);
  reg [`PD_BITS-1:0] p;integer k;
  begin
   p=0;p[`PD_VERSION]=1;p[`PD_STATUS]=`PD_OK;p[`PD_FRAME]=frame;p[`PD_TIME]=stamp;
   p[`PD_EPOCH]=1;p[`PD_GENERATION]=1;p[`PD_X]=100;p[`PD_Y]=300;p[`PD_W]=200;p[`PD_H]=60;
   p[`PD_IDS_LSB +:7]=0;p[`PD_IDS_LSB+7 +:7]=31;
   for(k=2;k<7;k=k+1)p[`PD_IDS_LSB+k*7 +:7]=55;
   p[`PD_TASK_MS]=latency;packet=p;
  end
 endfunction
 task run_case(input integer latency,interval,expected_max,expected_confirmed);
  integer ms,j,next_result,handshakes,max_count,ever_confirmed,taken;
  begin
   rst_n=0;iv=0;now_ms=1000;repeat(4)@(negedge clk);rst_n=1;repeat(12)@(negedge clk);
   next_result=0;handshakes=0;max_count=0;ever_confirmed=0;
   for(ms=0;ms<=latency+5*interval+1;ms=ms+1)begin
    now_ms=1000+ms;
    if(next_result<6 && ms==latency+next_result*interval)begin
     if(iv)$fatal(1,"previous packet still pending");
     ip=packet(next_result+1,1000+next_result*interval,latency);iv=1;next_result=next_result+1;
    end
    repeat(20)begin
     @(posedge clk);taken=iv&&ir;if(taken)handshakes=handshakes+1;
     #1;if(count>max_count)max_count=count;if(confirmed)ever_confirmed=1;
     @(negedge clk);if(taken)iv=0;
    end
   end
   if(handshakes!=6 || max_count!=expected_max || ever_confirmed!=expected_confirmed)
    $fatal(1,"latency=%0d interval=%0d handshakes=%0d max=%0d confirmed=%0d",latency,interval,handshakes,max_count,ever_confirmed);
   $display("TIMING latency=%0d interval=%0d accepted_packets=%0d max_count=%0d ever_confirmed=%0d",latency,interval,handshakes,max_count,ever_confirmed);
  end
 endtask
 initial begin
  run_case(100,100,3,1);
  run_case(240,240,3,1);
  run_case(249,249,3,1);
  run_case(250,250,1,0);
  run_case(300,300,1,0);
  run_case(499,499,1,0);
  run_case(500,500,0,0);
  run_case(300,100,3,1);
  run_case(400,100,1,0);
  run_case(400,90,3,1);
  $display("PASS 10 service-time scenarios; TTL=500 unchanged");$finish;
 end
 initial begin #100000000;$fatal(1,"timeout");end
endmodule
