// Preserve RGB and the existing result-frame metadata under arbitrary FIFO stalls.
module video_rgb_passthrough(
 input clk,rst_n,input [15:0] in_config,input in_recognition,
 input [63:0] in_pixels,input in_valid,output in_ready,
 input in_sof,in_eol,in_eof,input [31:0] in_id,in_epoch,
 output [63:0] out_pixels,output out_valid,input out_ready,
 output out_sof,out_eol,out_eof,output [31:0] out_id,out_epoch,
 output [15:0] out_config
);
 reg second;
 always @(posedge clk) begin
  if(!rst_n) second<=0;
  else if(in_valid && in_ready) second<=in_sof;
 end
 assign in_ready=out_ready;
 assign out_valid=in_valid;
 assign out_sof=in_sof;assign out_eol=in_eol;assign out_eof=in_eof;
 assign out_id=in_id;assign out_epoch=in_epoch;assign out_config=0;
 // Two-pixel order is unchanged. Threshold/flags are zero in the first two pairs.
 assign out_pixels={1'b0,(second ? 7'd0 : in_id[6:0]),in_pixels[55:32],
                    1'b0,(in_sof ? 7'd0 : in_id[6:0]),in_pixels[23:0]};
endmodule
