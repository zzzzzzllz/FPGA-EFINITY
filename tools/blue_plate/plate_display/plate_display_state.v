`include "plate_defs.vh"
module plate_display_state #(parameter TTL_MS=500)(
 input rst_n,src_clk,dst_clk,input [31:0] now_ms,current_epoch,current_generation,
 input result_valid,output result_ready,input [`PD_BITS-1:0] result_packet,
 input frame_start,input display_accept,
 output reg [`PD_BITS:0] active_packet,output [1:0] confirmation_count,
 output [31:0] display_now_ms,output display_rst_n
);
 (* async_reg="true" *) reg [1:0] src_reset,dst_reset;
 always @(posedge src_clk or negedge rst_n) if(!rst_n) src_reset<=0;else src_reset<={src_reset[0],1'b1};
 always @(posedge dst_clk or negedge rst_n) if(!rst_n) dst_reset<=0;else dst_reset<={dst_reset[0],1'b1};
 wire srst=src_reset[1],drst=dst_reset[1];
 assign display_rst_n=drst;
 wire valid,ready;wire [`PD_BITS:0] packet;
 plate_confirm #(.TTL_MS(TTL_MS)) confirm(.clk(src_clk),.rst_n(srst),.now_ms(now_ms),.current_epoch(current_epoch),
  .current_generation(current_generation),.in_valid(result_valid),.in_ready(result_ready),.in_packet(result_packet),
  .out_valid(valid),.out_ready(ready),.out_packet(packet),.count(confirmation_count),.confirmed());
 wire received;wire [`PD_BITS:0] received_packet;
 plate_mailbox #(.WIDTH(`PD_BITS+1)) results(.src_clk(src_clk),.src_rst_n(srst),.src_valid(valid),.src_ready(ready),.src_data(packet),
  .dst_clk(dst_clk),.dst_rst_n(drst),.dst_valid(received),.dst_ready(display_accept),.dst_data(received_packet));
 // Configuration has an independent channel, so stalled results cannot block invalidation.
 reg cfg_valid;reg [63:0] cfg_buffer;
 wire cfg_ready,cfg_received;wire [63:0] cfg_packet;
 always @(posedge src_clk or negedge srst) begin
  if(!srst) begin cfg_valid<=0;cfg_buffer<=0;end
  else if(!cfg_valid || cfg_ready) begin cfg_buffer<={current_epoch,current_generation};cfg_valid<=1;end
 end
 plate_mailbox #(.WIDTH(64)) config_link(.src_clk(src_clk),.src_rst_n(srst),.src_valid(cfg_valid),.src_ready(cfg_ready),.src_data(cfg_buffer),
  .dst_clk(dst_clk),.dst_rst_n(drst),.dst_valid(cfg_received),.dst_ready(1'b1),.dst_data(cfg_packet));
 reg [63:0] display_config;
 wire [63:0] config_at_boundary=cfg_received ? cfg_packet : display_config;
 reg [31:0] time_gray;
 (* async_reg="true" *) reg [31:0] time_sync0,time_sync1;
 always @(posedge src_clk or negedge srst) if(!srst) time_gray<=0;else time_gray<=now_ms^(now_ms>>1);
 always @(posedge dst_clk or negedge drst) begin
  if(!drst) begin time_sync0<=0;time_sync1<=0;end
  else begin time_sync0<=time_gray;time_sync1<=time_sync0;end
 end
 genvar bit_number;
 generate for(bit_number=0;bit_number<32;bit_number=bit_number+1) begin:decode_time
  assign display_now_ms[bit_number]=^(time_sync1>>bit_number);
 end endgenerate
 reg [`PD_BITS:0] pending;reg clear_pending;
 wire [`PD_BITS:0] next_packet=received && display_accept ? received_packet : pending;
 wire [31:0] age=display_now_ms-next_packet[`PD_TIME];
 wire next_fresh=!age[31] && age<TTL_MS;
 wire config_ok={next_packet[`PD_EPOCH],next_packet[`PD_GENERATION]}==config_at_boundary;
 wire invalidate_event=((cfg_received && cfg_packet!=display_config) ||
       (received && display_accept && !received_packet[`PD_BITS])) && (active_packet[`PD_BITS] || pending[`PD_BITS]);
 always @(posedge dst_clk or negedge drst) begin
  if(!drst) begin pending<=0;active_packet<=0;display_config<=0;clear_pending<=0;end
  else begin
   if(cfg_received) display_config<=cfg_packet;
   if(received && display_accept) pending<=received_packet;
   if(invalidate_event) clear_pending<=1;
   if(frame_start) begin
    active_packet<=next_packet;
    active_packet[`PD_BITS]<=next_packet[`PD_BITS] && next_fresh && config_ok && !clear_pending && !invalidate_event;
    if(!next_packet[`PD_BITS] || !next_fresh || !config_ok || clear_pending || invalidate_event) active_packet[`PD_IDS]<={7{7'h7f}};
    if(!next_fresh || !config_ok) pending[`PD_BITS]<=0;
    clear_pending<=0;
   end
  end
 end
endmodule
