// KEY1 walks a fixed demonstration route; KEY2/KEY3 act on the current step.
module edge_ui #(parameter DEBOUNCE=1000000,LONG=40000000,TIMEOUT=100000000)(
 input clk,rst_n,key_select_n,frame_start,settings_visible,
 input [1:0] presses,keys,
 input [2:0] frame_mode,input reference_valid,input [5:0] recorded,input [3:0] backend_error,
 input [2:0] jtag_view,input jtag_median,jtag_algorithm,jtag_recognition,input [1:0] jtag_ratio,input jtag_apply,output reg jtag_apply_ack,
 input [3:0] jtag_command,input jtag_command_toggle,output reg jtag_command_ack,
 output reg [3:0] frame_command,output reg frame_toggle,input frame_ack,
 input [10:0] threshold_pending,
 output reg [3:0] demo_step,output reg threshold_preset,output reg [10:0] threshold_preset_value,
 output reg [2:0] view,output reg median,algorithm,recognition,output reg [1:0] ratio,
 output reg [31:0] short_events,long_events,
 output reg [2:0] error,output busy
);
 reg [1:0] select_sync;
 reg select_stable,long_fired,short_press,long_press;
 reg [25:0] debounce_count,hold_count;
 reg pending_jtag;
 reg [10:0] sobel_threshold_saved,canny_threshold_saved,shape_threshold_saved;
 reg [1:0] canny_ratio_saved;
 localparam IDLE=0,COMMIT=1,SEND=2,ACK=3,SETTLE=4;
 reg [2:0] state;
 reg [3:0] queued_command;
 reg [1:0] settled_frames;
 reg [26:0] wait_count;
 assign busy=state!=IDLE || frame_toggle!=frame_ack;
 // Presets change presentation only. Clips and reference slots survive navigation.
 task enter_step(input [3:0] step_number);
 begin
  if(step_number==9) step_number=demo_step==8 ? 10 : 8;
  // Keep each algorithm's settings when leaving its demonstration page.
  if(demo_step==4 || demo_step==5) sobel_threshold_saved<=threshold_pending;
  if(demo_step==6) begin canny_threshold_saved<=threshold_pending;canny_ratio_saved<=ratio;end
  if(demo_step==8) shape_threshold_saved<=threshold_pending;
  demo_step<=step_number;median<=step_number>=3 && step_number<=8;recognition<=step_number==8;ratio<=1;threshold_preset<=1;
  threshold_preset_value<=56;
  if(step_number==8) threshold_preset_value<=shape_threshold_saved;
  if(step_number==7) begin
   threshold_preset_value<=demo_step==6 ? threshold_pending : canny_threshold_saved;
   ratio<=demo_step==6 ? ratio : canny_ratio_saved;
  end
  algorithm<=step_number==6 || step_number==7 || step_number==8;
  case(step_number)
   2:view<=1;
   4,5,6:view<=3;
   3:view<=4;
   7,8:view<=5;
   13:view<=6;
   default:view<=0;
  endcase
  queued_command<=step_number==12 && recorded!=0 ? 10 : 1;
  error<=step_number==12 && recorded==0 ? 2 : 0;
  state<=COMMIT;wait_count<=0;
 end endtask
 task send_command(input [3:0] command_number);
 begin queued_command<=command_number;state<=SEND;wait_count<=0;error<=0;end
 endtask
 task changed_setting;
 begin state<=COMMIT;queued_command<=0;wait_count<=0;error<=0;end
 endtask
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
 always @(posedge clk) begin
  if(!rst_n) begin
   sobel_threshold_saved<=56;canny_threshold_saved<=56;shape_threshold_saved<=56;canny_ratio_saved<=1;threshold_preset_value<=56;
   demo_step<=1;threshold_preset<=0;view<=0;median<=0;algorithm<=0;ratio<=1;recognition<=0;
   frame_command<=0;frame_toggle<=0;pending_jtag<=0;jtag_command_ack<=0;jtag_apply_ack<=0;
   short_events<=0;long_events<=0;error<=0;state<=IDLE;queued_command<=0;settled_frames<=0;wait_count<=0;
  end else begin
   threshold_preset<=0;
   if(state!=IDLE) begin
    wait_count<=wait_count+1'b1;
    if(wait_count==TIMEOUT-1) begin error<=4;state<=IDLE;end
    else case(state)
     COMMIT: if(frame_start && !threshold_preset) begin
      if(queued_command!=0) state<=SEND;
      else begin state<=SETTLE;settled_frames<=0;end
     end
     SEND: if(frame_toggle==frame_ack) begin
      frame_command<=queued_command;frame_toggle<=!frame_toggle;state<=ACK;
     end
     ACK: if(frame_toggle==frame_ack) begin state<=SETTLE;settled_frames<=0;end
     SETTLE: if(frame_start) begin
      // Allow the command-status mailbox and frame-committed settings to arrive.
      if(settled_frames!=2) settled_frames<=settled_frames+1'b1;
      else if(queued_command!=0 && backend_error!=0) begin error<=3;state<=IDLE;end
      else if(queued_command==8 && reference_valid && view!=6) begin view<=6;settled_frames<=0;end
      else if(settings_visible && frame_mode!=5) state<=IDLE;
     end
     default: state<=IDLE;
    endcase
   end else if(frame_toggle==frame_ack) begin
    if(pending_jtag) begin jtag_command_ack<=jtag_command_toggle;pending_jtag<=0;end
    else if(jtag_apply!=jtag_apply_ack) begin
     view<=jtag_view;median<=jtag_median;algorithm<=jtag_algorithm;ratio<=jtag_ratio;recognition<=jtag_recognition;
     jtag_apply_ack<=jtag_apply;changed_setting;
    end else if(jtag_command_toggle!=jtag_command_ack) begin
     pending_jtag<=1;
     case(jtag_command)
      12:enter_step(demo_step==13 ? 4'd1 : demo_step+1'b1);
      13:enter_step(demo_step==1 ? 4'd13 : demo_step-1'b1);
      14:enter_step(1);
      default:send_command(jtag_command);
     endcase
    end else if(long_press) begin
     long_events<=long_events+1'b1;
     enter_step(demo_step==1 ? 4'd13 : demo_step-1'b1);
    end else if(short_press) begin
     short_events<=short_events+1'b1;
     enter_step(demo_step==13 ? 4'd1 : demo_step+1'b1);
    end else if((presses==1 && keys==2) || (presses==2 && keys==1)) begin
     case(demo_step)
      3:begin
       if(presses==1) median<=!median;
       else view<=view==4?7:4;
       changed_setting;
      end
      4:begin view<=presses==1?2:3;changed_setting;end
      6:begin
       if(presses==1 && ratio!=0) ratio<=ratio-1'b1;
       if(presses==2 && ratio!=2) ratio<=ratio+1'b1;
       changed_setting;
      end
      7:begin
       view<=5;median<=1;algorithm<=presses==1;
       threshold_preset<=1;
       threshold_preset_value<=presses==1 ? canny_threshold_saved : sobel_threshold_saved;
       ratio<=presses==1 ? canny_ratio_saved : 2'd1;
       changed_setting;
      end
      // Task 8 threshold keys are handled by threshold_control, including repeat.
      10:send_command(presses==1?3:1);
      11:send_command(presses==1?1:4);
      12:if(recorded==0) error<=2;
         else send_command(presses==2?7:frame_mode==3?6:11);
      13:begin
       send_command(presses==1?8:9);
       view<=6;
      end
      default:;
     endcase
    end
   end
  end
 end
endmodule
