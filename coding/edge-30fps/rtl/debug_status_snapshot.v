// VIO already synchronizes its outputs to clk. Snapshot and page acknowledgements
// let the host wait for stable data without resetting or rewriting camera controls.
module debug_status_snapshot #(parameter WIDTH=1536)(
 input clk,rst_n,input [WIDTH-1:0] live,
 input capture,input [5:0] page,
 output reg capture_ack,output reg [5:0] page_ack,output reg [63:0] data
);
 localparam PAD_WIDTH=((WIDTH+63)/64)*64;
 localparam PAGES=PAD_WIDTH/64;
 reg [PAD_WIDTH-1:0] held;
 reg [5:0] position;
 reg captured;
 wire [PAD_WIDTH-1:0] rotated;
 generate if(PAGES>1) assign rotated={held[63:0],held[PAD_WIDTH-1:64]};
 else assign rotated=held;endgenerate
 always @(posedge clk) begin
  if(!rst_n) begin held<=0;position<=0;captured<=0;capture_ack<=0;page_ack<=63;data<=0;end
  else begin
   capture_ack<=captured;
   if(capture!=captured) begin
    held<={{(PAD_WIDTH-WIDTH){1'b0}},live};position<=0;captured<=capture;page_ack<=63;data<=0;
   end else if(page>=PAGES) begin page_ack<=page;data<=0;end
   else if(position!=page) begin
    // A fixed 64-bit rotation replaces the parallel page multiplexer. Arbitrary
    // page requests take at most PAGES clocks; the host already waits for ack.
    held<=rotated;position<=position==PAGES-1 ? 0 : position+1'b1;page_ack<=63;
   end else begin page_ack<=page;data<=held[63:0];end
  end
 end
endmodule
