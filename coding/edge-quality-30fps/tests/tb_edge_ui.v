`timescale 1ns/1ps
module tb_edge_ui;
 reg clk=0;always #10 clk=~clk;
 reg rst_n=0,k1=1,k2=1,k3=1,fs=0,visible=1;
 wire [1:0] presses,keys,ratio;wire algorithm,recognition;wire [3:0] step,cmd;
 wire [2:0] view,error;wire med,busy,toggle,preset;
 reg ack=0;reg [2:0] mode=0;reg ref_valid=0;reg [5:0] recorded=0;reg [3:0] backend_error=0;
 reg [2:0] jview=3;reg jmed=1,apply=0;wire apply_ack;
 reg [3:0] jcmd=0;reg jtoggle=0;wire jack;
 wire [31:0] short_events,long_events,epoch,minus_events,plus_events;
 wire [10:0] pending,active,preset_value;wire tack;
 reg threshold_toggle=0;reg [10:0] threshold_value=56;
 threshold_control #(.DEBOUNCE(5),.HOLD(50),.REPEAT(10),.RESET_VALUE(56)) thresholds(
  .clk(clk),.rst_n(rst_n),.frame_start(fs),.preset(preset),.preset_value(preset_value),.key_minus_n(k2),.key_plus_n(k3),.canny_enabled(algorithm),.adjust_enable((step==5 || step==8) && !busy),.fine_adjust(step==8),.press_events(presses),
  .jtag_value(threshold_value),.jtag_toggle(threshold_toggle),.jtag_ack(tack),.pending(pending),.active(active),
  .epoch(epoch),.minus_events(minus_events),.plus_events(plus_events),.keys(keys));
 edge_ui #(.DEBOUNCE(5),.LONG(40),.TIMEOUT(500)) dut(.clk(clk),.rst_n(rst_n),.key_select_n(k1),.frame_start(fs),.settings_visible(visible),.presses(presses),.keys(keys),
  .frame_mode(mode),.reference_valid(ref_valid),.recorded(recorded),.backend_error(backend_error),.jtag_view(jview),.jtag_median(jmed),.jtag_algorithm(1'b0),.jtag_ratio(2'd1),.jtag_apply(apply),.jtag_apply_ack(apply_ack),
  .jtag_command(jcmd),.jtag_command_toggle(jtoggle),.jtag_command_ack(jack),.frame_command(cmd),.frame_toggle(toggle),.frame_ack(ack),
  .jtag_recognition(1'b0),.recognition(recognition),
  .threshold_pending(pending),.threshold_preset_value(preset_value),
  .demo_step(step),.threshold_preset(preset),.view(view),.median(med),.algorithm(algorithm),.ratio(ratio),.short_events(short_events),.long_events(long_events),.error(error),.busy(busy));
 integer backend_delay=0,commands=0,records=0,ref_saves=0,ticks=0;
 reg stall_ack=0;
 always @(negedge clk) begin ticks=ticks+1;fs=ticks%12==0;end
 always @(posedge clk) begin
  if(toggle!=ack && !stall_ack) begin
   backend_delay<=backend_delay+1;
   if(backend_delay==3) begin
    ack<=toggle;backend_delay<=0;commands<=commands+1;backend_error<=0;
    case(cmd)
     1:mode<=0;
     2:mode<=1;
     3:mode<=5;
     4:begin mode<=2;recorded<=0;records<=records+1;end
     5,11:if(recorded!=0) mode<=3;else backend_error<=2;
     6,7,10:if(recorded!=0) mode<=4;else backend_error<=2;
     8:begin ref_valid<=1;ref_saves<=ref_saves+1;end
     9:ref_valid<=0;
     default:$fatal(1,"unknown backend command %d",cmd);
    endcase
   end
  end
  if(mode==5 && fs) mode<=1;
 end
 task cycles(input integer n);repeat(n) @(negedge clk);endtask
 task ready;begin cycles(2);wait(!busy);cycles(2);end endtask
 task next_step;begin
  ready;k1=0;cycles(2);k1=1;cycles(2);k1=0;cycles(12);k1=1;cycles(12);ready;
 end endtask
 task prev_step;begin ready;k1=0;cycles(65);k1=1;cycles(12);ready;end endtask
 task plus;begin ready;k3=0;cycles(12);k3=1;cycles(12);ready;end endtask
 task minus;begin ready;k2=0;cycles(12);k2=1;cycles(12);ready;end endtask
 task host(input [3:0] c);begin ready;jcmd=c;jtoggle=!jtoggle;wait(jack==jtoggle);ready;end endtask
 integer before_events,old_commands,n,sobel_saved;
 initial begin
  cycles(5);rst_n=1;cycles(5);
  if(step!=1 || view!=0 || med || algorithm || pending!=56) $fatal(1,"startup preset");
  prev_step;if(step!=13 || short_events!=0) $fatal(1,"previous wraps/long release");
  next_step;if(step!=1 || view!=0) $fatal(1,"last wraps to color");
  plus;minus;if(view!=0 || pending!=56) $fatal(1,"inactive keys");
  next_step;if(step!=2 || view!=1 || mode!=0) $fatal(1,"gray preset");
  next_step;if(step!=3 || view!=4 || !med || algorithm) $fatal(1,"denoise preset");
  minus;if(med || view!=4) $fatal(1,"median off");
  plus;if(view!=7 || med) $fatal(1,"edge comparison keeps median off");
  minus;if(!med || view!=7) $fatal(1,"median on in edge comparison");
  plus;if(view!=4 || !med) $fatal(1,"gray comparison keeps median on");
  minus;next_step;if(step!=4 || view!=3 || !med || algorithm) $fatal(1,"Sobel always uses median even after comparison off");
  minus;if(view!=2) $fatal(1,"full edge");plus;if(view!=3) $fatal(1,"compare");
  next_step;plus;if(step!=5 || !med || pending!=72) $fatal(1,"threshold plus");
  k3=0;cycles(76);k3=1;cycles(12);if(pending<=88) $fatal(1,"threshold repeat");sobel_saved=pending;
  next_step;if(step!=6 || !algorithm || ratio!=1 || !med || pending!=56) $fatal(1,"Canny preset");
  minus;minus;if(ratio!=0) $fatal(1,"low ratio clamp");plus;plus;plus;if(ratio!=2) $fatal(1,"high ratio clamp");
  // Use a different Canny threshold to catch accidental reuse of the Sobel value.
  threshold_value=80;threshold_toggle=!threshold_toggle;cycles(24);
  next_step;if(step!=7 || view!=5 || !med || !algorithm || ratio!=2 || pending!=80 || active!=80) $fatal(1,"overlay inherits Canny settings");
  plus;if(view!=5 || algorithm || !med || pending!=sobel_saved || active!=sobel_saved) $fatal(1,"Sobel overlay inherits tuned threshold");
  minus;if(view!=5 || !algorithm || !med || ratio!=2 || pending!=80 || active!=80) $fatal(1,"Canny overlay restores its own settings");
  plus;minus;if(!algorithm || ratio!=2 || pending!=80) $fatal(1,"repeated switching preserves settings");
  next_step;prev_step;if(step!=7 || !algorithm || ratio!=2 || pending!=80) $fatal(1,"return to overlay restores Canny");
  plus;if(algorithm || pending!=sobel_saved) $fatal(1,"return to overlay preserves Sobel");
  next_step;if(step!=8 || !med || !recognition || pending!=56) $fatal(1,"shape preset");
  plus;if(!recognition || pending!=60 || active!=60) $fatal(1,"shape threshold +4");
  minus;if(!recognition || pending!=56 || active!=56) $fatal(1,"shape threshold -4");
  k3=0;cycles(76);k3=1;cycles(12);if(pending<=60 || !recognition) $fatal(1,"shape threshold repeat");
  threshold_value=2039;threshold_toggle=!threshold_toggle;cycles(24);plus;plus;
  if(pending!=2040) $fatal(1,"shape upper saturation");
  threshold_value=3;threshold_toggle=!threshold_toggle;cycles(24);minus;minus;
  if(pending!=1) $fatal(1,"shape lower saturation");
  threshold_value=68;threshold_toggle=!threshold_toggle;cycles(24);
  k2=0;k3=0;cycles(76);k2=1;k3=1;cycles(12);
  if(pending!=68) $fatal(1,"shape simultaneous keys");
  next_step;prev_step;if(step!=8 || pending!=68 || !recognition) $fatal(1,"shape threshold retained / skip deleted page backward");
  next_step;minus;if(step!=10 || mode!=1 || cmd!=3) $fatal(1,"new live frame");plus;if(mode!=0) $fatal(1,"step live resume");
  next_step;if(step!=11 || records!=0) $fatal(1,"navigation must not erase clip");
  next_step;if(step!=12 || error!=2 || mode!=0) $fatal(1,"empty clip");old_commands=commands;plus;minus;if(commands!=old_commands) $fatal(1,"empty clip command sent");
  before_events=short_events;prev_step;if(step!=11 || short_events!=before_events) $fatal(1,"previous duplicates next");
  plus;if(records!=1 || mode!=2) $fatal(1,"explicit record");recorded=32;mode=4;
  next_step;if(step!=12 || mode!=4 || cmd!=10 || recorded!=32) $fatal(1,"first paused frame");
  minus;if(mode!=3 || cmd!=11) $fatal(1,"resume playback");minus;if(mode!=4 || cmd!=6) $fatal(1,"pause playback");plus;if(cmd!=7) $fatal(1,"next clip frame");
  next_step;if(step!=13 || view!=6 || mode!=0) $fatal(1,"reference initial");minus;if(!ref_valid || view!=6) $fatal(1,"save reference and display");
  next_step;if(step!=1 || view!=0 || algorithm || mode!=0 || !ref_valid || recorded!=32) $fatal(1,"loop/preservation");
  prev_step;if(view!=6 || ref_saves!=1) $fatal(1,"reference retained on reentry");plus;if(view!=6 || ref_valid) $fatal(1,"clear reference");
  host(14);if(step!=1 || records!=1 || recorded!=32) $fatal(1,"home preserves clip");
  host(13);if(step!=13) $fatal(1,"host previous wrap");host(12);if(step!=1) $fatal(1,"host next wrap");
  host(12);if(step!=2) $fatal(1,"host next");host(13);if(step!=1) $fatal(1,"host previous");
  // Busy navigation is ignored, not queued behind a different demonstration step.
  visible=0;k1=0;cycles(12);k1=1;cycles(12);cycles(25);
  if(!busy || step!=2) $fatal(1,"busy not held for displayed settings");
  k1=0;cycles(12);k1=1;cycles(12);visible=1;ready;
  if(step!=2) $fatal(1,"busy key unexpectedly queued");
  visible=0;k1=0;cycles(12);k1=1;cycles(12);cycles(510);
  if(error!=4 || busy) $fatal(1,"missing visible-settings timeout");visible=1;
  next_step;if(error || step!=4) $fatal(1,"timeout recovery");
  // Separate configuration and frame command toggles are both serviced.
  jview=3;jmed=1;apply=1;jcmd=2;jtoggle=!jtoggle;wait(jack==jtoggle);ready;
  if(view!=3 || !med || mode!=1 || apply_ack!=apply) $fatal(1,"JTAG simultaneous config/command");
  if(records!=1 || ref_saves!=1) $fatal(1,"destructive command repeated");
  $display("PASS: 12-page loop skipping 09, all actions, presets, clip/reference retention, empty clip, wraps, debounce, long-release exclusion, busy/timeout recovery, JTAG");
  $finish;
 end
 initial begin #1000000;$fatal(1,"timeout step %d state %d",step,dut.state);end
endmodule
