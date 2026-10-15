// VIEW, ALGORITHM, THRESHOLD, LOW RATIO (Canny), MEDIAN, FRAME.
module edge_ui #(parameter DEBOUNCE=1000000,LONG=40000000)(
 input clk,rst_n,key_select_n,
 input [1:0] presses,keys,
 input [2:0] frame_mode,input reference_valid,
 input [2:0] jtag_view,input jtag_median,jtag_algorithm,jtag_recognition,input [1:0] jtag_ratio,input jtag_apply,output reg jtag_apply_ack,
 input [3:0] jtag_command,input jtag_command_toggle,output reg jtag_command_ack,
 output reg [3:0] frame_command,output reg frame_toggle,input frame_ack,
 output reg [2:0] focus,output reg [3:0] action,
 output reg [2:0] view,output reg median,algorithm,recognition,output reg [1:0] ratio,
 output reg [31:0] short_events,long_events,
 output reg [2:0] error,output busy
);
 reg [1:0] select_sync;
 reg select_stable,long_fired,short_press,long_press;
 reg [25:0] debounce_count,hold_count;
 reg pending_jtag;
 assign busy=frame_toggle!=frame_ack;
 always @(posedge clk) begin
  if(!rst_n) begin
   select_sync<=3;select_stable<=1;long_fired<=0;short_press<=0;long_press<=0;
   debounce_count<=0;hold_count<=0;
  end else begin
   select_sync<={select_sync[0],key_select_n};short_press<=0;long_press<=0;
   if(select_sync[1]==select_stable) debounce_count<=0;
   else if(debounce_count==DEBOUNCE-1) begin
    select_stable<=select_sync[1];debounce_count<=0;
    if(select_sync[1] && !long_fired) short_press<=1;
    if(!select_sync[1]) begin long_fired<=0;hold_count<=0;end
   end else debounce_count<=debounce_count+1'b1;
   if(!select_stable && !select_sync[1] && !long_fired) begin
    if(hold_count==LONG-DEBOUNCE-1) begin long_press<=1;long_fired<=1;end
    else hold_count<=hold_count+1'b1;
   end
  end
 end
 function [3:0] action_command;
  input [3:0] selected;
  begin case(selected)
   1:action_command=3; // acquire a new live frame
   2:action_command=4; // explicit overwrite and record
   3:action_command=5; // loop playback
   4:action_command=6; // pause at the shown frame
   5:action_command=7; // next recorded frame
   6:action_command=8; // independent reference
   7:action_command=1; // live
   8:action_command=9; // clear reference
   default:action_command=0;
  endcase end
 endfunction
 always @(posedge clk) begin
  if(!rst_n) begin
   focus<=0;action<=0;view<=3;median<=1;algorithm<=0;ratio<=1;recognition<=0;
   frame_command<=0;frame_toggle<=0;pending_jtag<=0;jtag_command_ack<=0;jtag_apply_ack<=0;
   short_events<=0;long_events<=0;error<=0;
  end else begin
   if(pending_jtag && !busy) begin jtag_command_ack<=jtag_command_toggle;pending_jtag<=0;end
   // Explicit apply toggle means an identical JTAG setting can override keys.
   if(jtag_apply!=jtag_apply_ack) begin
    view<=jtag_view;median<=jtag_median;algorithm<=jtag_algorithm;ratio<=jtag_ratio;recognition<=jtag_recognition;
    if(!jtag_algorithm && focus==3) focus<=4;jtag_apply_ack<=jtag_apply;error<=0;
   end else begin
    if(presses==1 && keys==2) begin
     if(focus==0) view<=view==0 ? (reference_valid?6:5) : view-1'b1;
     if(focus==1) algorithm<=0;
     if(focus==3) ratio<=ratio==0 ? 2 : ratio-1'b1;
     if(focus==4) median<=0;
     if(focus==5) recognition<=0;
     if(focus==6) action<=action==0 ? 8 : action-1'b1;
    end
    if(presses==2 && keys==1) begin
     if(focus==0) view<=view==(reference_valid?6:5) ? 0 : view+1'b1;
     if(focus==1) algorithm<=1;
     if(focus==3) ratio<=ratio==2 ? 0 : ratio+1'b1;
     if(focus==4) median<=1;
     if(focus==5) recognition<=1;
     if(focus==6) action<=action==8 ? 0 : action+1'b1;
    end
   end
   if(jtag_command_toggle!=jtag_command_ack && !pending_jtag && !busy) begin
    frame_command<=jtag_command;frame_toggle<=!frame_toggle;pending_jtag<=1;error<=0;
   end else if(!busy && !pending_jtag) begin
    if(long_press) begin
     frame_command<=frame_mode==0 || frame_mode==2 ? 2 : 1;frame_toggle<=!frame_toggle;
     long_events<=long_events+1'b1;error<=0;
    end else if(short_press) begin
     short_events<=short_events+1'b1;error<=0;
     if(focus==6) begin
      focus<=0;
      if(action!=0) begin frame_command<=action_command(action);frame_toggle<=!frame_toggle;end
     end else focus<=focus==2 && !algorithm ? 4 : focus+1'b1;
    end
   end else if(short_press || long_press) error<=1;
   if(view==6 && !reference_valid) view<=3;
  end
 end
endmodule
