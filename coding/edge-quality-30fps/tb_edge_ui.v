`timescale 1ns/1ps
module tb_edge_ui;
 reg clk=0;always #10 clk=~clk;
 reg rst_n=0,k1=1,k2=1,k3=1,fs=0;
 wire [1:0] presses,keys,ratio;wire [2:0] focus;wire algorithm,recognition;wire [3:0] action,cmd;
 wire [2:0] view,error;wire med,busy,toggle;
 reg ack=0;reg [2:0] mode=0;
 reg [2:0] jview=3;reg jmed=1,apply=0;wire apply_ack;
 reg [3:0] jcmd=0;reg jtoggle=0;wire jack;
 wire [31:0] short_events,long_events,epoch,minus_events,plus_events;
 wire [10:0] pending,active;wire tack;
 reg threshold_toggle=0;reg [10:0] threshold_value=32;
 threshold_control #(.DEBOUNCE(5),.HOLD(50),.REPEAT(10)) thresholds(
  .clk(clk),.rst_n(rst_n),.frame_start(fs),.key_minus_n(k2),.key_plus_n(k3),.canny_enabled(algorithm),.adjust_enable(focus==2),.press_events(presses),
  .jtag_value(threshold_value),.jtag_toggle(threshold_toggle),.jtag_ack(tack),.pending(pending),.active(active),
  .epoch(epoch),.minus_events(minus_events),.plus_events(plus_events),.keys(keys));
 edge_ui #(.DEBOUNCE(5),.LONG(40)) dut(.clk(clk),.rst_n(rst_n),.key_select_n(k1),.presses(presses),.keys(keys),
  .frame_mode(mode),.reference_valid(1'b1),.jtag_view(jview),.jtag_median(jmed),.jtag_algorithm(1'b0),.jtag_ratio(2'd1),.jtag_apply(apply),.jtag_apply_ack(apply_ack),
  .jtag_command(jcmd),.jtag_command_toggle(jtoggle),.jtag_command_ack(jack),.frame_command(cmd),.frame_toggle(toggle),.frame_ack(ack),
  .jtag_recognition(1'b0),.recognition(recognition),
  .focus(focus),.action(action),.view(view),.median(med),.algorithm(algorithm),.ratio(ratio),.short_events(short_events),.long_events(long_events),.error(error),.busy(busy));
 integer backend_delay=0,commands=0;
 always @(posedge clk) begin
  if(toggle!=ack) begin
   backend_delay<=backend_delay+1;
   if(backend_delay==3) begin
    ack<=toggle;backend_delay<=0;commands<=commands+1;
    if(cmd==2) mode<=1;else if(cmd==1) mode<=0;
   end
  end
 end
 task cycles(input integer n);repeat(n) @(negedge clk);endtask
 task select_short;begin
  k1=0;cycles(2);k1=1;cycles(2);k1=0;cycles(12);k1=1;cycles(12);
 end endtask
 task plus;begin k3=0;cycles(12);k3=1;cycles(12);end endtask
 task minus;begin k2=0;cycles(12);k2=1;cycles(12);end endtask
 integer before_events;
 initial begin
  cycles(5);rst_n=1;cycles(5);
  plus;if(view!=4 || pending!=32) $fatal(1,"view plus changed threshold");
  k3=0;cycles(100);k3=1;cycles(12);
  if(view!=5) $fatal(1,"enum auto-repeated");
  select_short;if(focus!=1 || short_events!=1) $fatal(1,"KEY1 short/bounce");
  plus;if(!algorithm) $fatal(1,"algorithm focus");
  minus;if(algorithm) $fatal(1,"algorithm minus");
  select_short;plus;if(pending!=48) $fatal(1,"threshold focus");
  k3=0;cycles(76);k3=1;cycles(12);if(pending<=64) $fatal(1,"threshold hold repeat");
  before_events=short_events;
  k1=0;cycles(100);k1=1;cycles(15);
  if(mode!=1 || long_events!=1 || short_events!=before_events || focus!=2 || commands!=1) $fatal(1,"long press duplicated short");
  k1=0;cycles(55);k1=1;cycles(15);
  if(mode!=0 || commands!=2) $fatal(1,"long resume");
  select_short;minus;if(focus!=4 || med!=0) $fatal(1,"median control");
  select_short;plus;if(focus!=5 || !recognition) $fatal(1,"recognition on");
  minus;if(recognition) $fatal(1,"recognition off");
  select_short;plus;plus;if(action!=2) $fatal(1,"frame menu");
  select_short;cycles(10);if(cmd!=4 || focus!=0 || commands!=3) $fatal(1,"record action");
  jview=3;jmed=1;apply=1;cycles(5);if(view!=3 || !med || !apply_ack) $fatal(1,"JTAG shared apply");
  jcmd=8;jtoggle=1;cycles(15);if(jack!=1 || cmd!=8) $fatal(1,"JTAG command ack");
  select_short;plus;if(!algorithm || focus!=1) $fatal(1,"Canny selection");
  select_short;select_short;if(focus!=3 || ratio!=1) $fatal(1,"Canny ratio focus");
  plus;if(ratio!=2) $fatal(1,"ratio 3/4");plus;if(ratio!=0) $fatal(1,"ratio wrap 1/4");
  minus;if(ratio!=2) $fatal(1,"ratio reverse wrap");
  apply=0;cycles(5);if(algorithm || ratio!=1 || focus!=4) $fatal(1,"JTAG algorithm/ratio and hidden focus");
  $display("PASS: three physical keys, bounce, short/long exclusion, enum/no-repeat, threshold repeat, median, record menu, JTAG override");
  $finish;
 end
endmodule
