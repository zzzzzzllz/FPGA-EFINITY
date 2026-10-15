// Four consecutive pixels per DDR beat; first pair occupies the upper half.
// SOF/EOF travel with the data, so a failed frame cannot become a valid frame
// merely because its byte count happens to match.
module frame_pair_fifo #(parameter DEPTH=1024,RGB_ONLY=0)(
 input rst_n, in_clk,out_clk,
 input valid,sof,eof,input [63:0] pixels,input [31:0] frame_id,
 output ready,output reg [31:0] overflow,
 output [161:0] data,output empty,
 output [$clog2(DEPTH):0] count,input take
);
 reg half,first;
 localparam PAIR_BITS=RGB_ONLY ? 48 : 64;
 reg [PAIR_BITS-1:0] upper;
 wire [PAIR_BITS-1:0] pair_data=RGB_ONLY ? {pixels[55:32],pixels[23:0]} : pixels;
 wire [33+PAIR_BITS*2:0] stored_data;
 reg [31:0] id;
 wire full;
 assign ready=!full;
 generate if(RGB_ONLY) begin
  assign data={stored_data[129:96],8'd0,stored_data[95:72],8'd0,stored_data[71:48],
               8'd0,stored_data[47:24],8'd0,stored_data[23:0]};
 end else begin
  assign data=stored_data;
 end endgenerate
 DC_FIFO #(.FIFO_MODE("ShowAhead"),.DATA_WIDTH(34+PAIR_BITS*2),.FIFO_DEPTH(DEPTH)) fifo(
  .Reset(!rst_n),.WrClk(in_clk),.WrEn(valid && half && !sof && !full),
  .WrData({id,first,eof,upper,pair_data}),.WrFull(full),.WrDNum(),
  .RdClk(out_clk),.RdEn(take),.RdData(stored_data),.RdEmpty(empty),.RdDNum(count),.DataVal());
 always @(posedge in_clk) begin
  if(!rst_n) begin half<=0;first<=0;upper<=0;id<=0;overflow<=0;end
  else if(valid) begin
   if(sof || !half) begin upper<=pair_data;id<=frame_id;first<=sof;half<=1;end
   else begin
    half<=0;
    if(full) overflow<=overflow+1'b1;
   end
  end
 end
endmodule
