`include "plate_defs.vh"
module plate_display #(parameter FONT_FILE="tools/blue_plate/plate_display/plate_font.mem",TTL_MS=500,X=16,Y=656)(
 input rst_n,src_clk,pixel_clk,input [31:0] now_ms,current_epoch,current_generation,
 input result_valid,output result_ready,input [`PD_BITS-1:0] result_packet,
 input frame_start,display_accept,input [10:0] x,y,input de,hs,vs,input [23:0] rgb,
 output [23:0] out_rgb,output out_de,out_hs,out_vs,
 output [`PD_BITS:0] active_packet,output [1:0] confirmation_count
);
 wire display_reset_n;
 plate_display_state #(.TTL_MS(TTL_MS)) state(.rst_n(rst_n),.src_clk(src_clk),.dst_clk(pixel_clk),.now_ms(now_ms),
  .current_epoch(current_epoch),.current_generation(current_generation),.result_valid(result_valid),.result_ready(result_ready),
  .result_packet(result_packet),.frame_start(frame_start),.display_accept(display_accept),.active_packet(active_packet),
  .confirmation_count(confirmation_count),.display_now_ms(),.display_rst_n(display_reset_n));
 plate_osd #(.FONT_FILE(FONT_FILE),.X(X),.Y(Y)) osd(.clk(pixel_clk),.rst_n(display_reset_n),.x(x),.y(y),.de(de),.hs(hs),.vs(vs),
  .rgb(rgb),.active_packet(active_packet),.out_rgb(out_rgb),.out_de(out_de),.out_hs(out_hs),.out_vs(out_vs));
endmodule
