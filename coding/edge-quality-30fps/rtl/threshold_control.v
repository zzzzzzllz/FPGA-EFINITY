// KEY2/KEY3 are active low. One event after 20 ms; repeat after 500 ms.
module threshold_control #(
 parameter DEBOUNCE=1000000, HOLD=25000000, REPEAT=5000000, RESET_VALUE=32
)(
 input clk,rst_n,frame_start,preset,input [10:0] preset_value,
 input key_minus_n,key_plus_n,
 input canny_enabled,input adjust_enable,input fine_adjust,output reg [1:0] press_events,
 input [10:0] jtag_value,input jtag_toggle,
 output reg jtag_ack,
 output reg [10:0] pending,active,
 output reg [31:0] epoch,minus_events,plus_events,
 output [1:0] keys
);
 reg [1:0] sync1,sync2,stable;
 reg [25:0] debounce_count[0:1],hold_count[0:1];
 reg [1:0] repeated,event_pulse;
 assign keys=stable;
 integer k;
 always @(posedge clk) begin
  if(!rst_n) begin
   sync1<=3;sync2<=3;stable<=3;event_pulse<=0;press_events<=0;repeated<=0;
   for(k=0;k<2;k=k+1) begin debounce_count[k]<=0;hold_count[k]<=0;end
  end else begin
   sync1<={key_plus_n,key_minus_n};sync2<=sync1;event_pulse<=0;press_events<=0;
   for(k=0;k<2;k=k+1) begin
    if(sync2[k]==stable[k]) debounce_count[k]<=0;
    else if(debounce_count[k]==DEBOUNCE-1) begin
     stable[k]<=sync2[k];debounce_count[k]<=0;
     if(!sync2[k]) begin event_pulse[k]<=1;press_events[k]<=1;end
    end else debounce_count[k]<=debounce_count[k]+1'b1;
    if(stable[k] || sync2[k]) begin hold_count[k]<=0;repeated[k]<=0;end
    else if(hold_count[k]==(repeated[k]?REPEAT-1:HOLD-DEBOUNCE-1)) begin
     hold_count[k]<=0;repeated[k]<=1;event_pulse[k]<=1;
    end else hold_count[k]<=hold_count[k]+1'b1;
   end
  end
 end
 reg [10:0] next_value;
 wire [10:0] adjust_step=fine_adjust ? 11'd4 : 11'd16;
 always @* begin
  next_value=pending;
  if(preset) next_value=preset_value;
  else if(jtag_toggle!=jtag_ack) next_value=jtag_value>2040?11'd2040:jtag_value;
  else if(adjust_enable && event_pulse==1 && stable==2) next_value=pending<adjust_step?11'd0:pending-adjust_step;
  else if(adjust_enable && event_pulse==2 && stable==1) next_value=pending>11'd2040-adjust_step?11'd2040:pending+adjust_step;
  if(canny_enabled && next_value==0) next_value=1;
 end
 always @(posedge clk) begin
  if(!rst_n) begin
   pending<=RESET_VALUE;active<=RESET_VALUE;jtag_ack<=0;epoch<=0;minus_events<=0;plus_events<=0;
  end else begin
   pending<=next_value;if(!preset) jtag_ack<=jtag_toggle;
   if(jtag_toggle==jtag_ack && adjust_enable) begin
    if(event_pulse==1 && stable==2) minus_events<=minus_events+1'b1;
    if(event_pulse==2 && stable==1) plus_events<=plus_events+1'b1;
   end
   if(frame_start) begin
    active<=next_value;
    if(active!=next_value) epoch<=epoch+1'b1;
   end
  end
 end
endmodule
