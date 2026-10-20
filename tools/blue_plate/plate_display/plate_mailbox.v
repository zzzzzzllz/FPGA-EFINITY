// Bundled-data two-phase CDC: held data changes only after the prior ack.
// Common asynchronous assertion, separate synchronized reset release required.
module plate_mailbox #(parameter WIDTH=32)(
 input src_clk,src_rst_n,input src_valid,output src_ready,input [WIDTH-1:0] src_data,
 input dst_clk,dst_rst_n,output dst_valid,input dst_ready,output [WIDTH-1:0] dst_data
);
 reg [WIDTH-1:0] held;
 reg request,ack;
 (* async_reg="true" *) reg [1:0] req_sync,ack_sync;
 assign src_ready=request==ack_sync[1];
 assign dst_valid=req_sync[1]!=ack;
 assign dst_data=held;
 always @(posedge src_clk or negedge src_rst_n) begin
  if(!src_rst_n) begin held<=0;request<=0;ack_sync<=0;end
  else begin
   ack_sync<={ack_sync[0],ack};
   if(src_valid && src_ready) begin held<=src_data;request<=!request;end
  end
 end
 always @(posedge dst_clk or negedge dst_rst_n) begin
  if(!dst_rst_n) begin req_sync<=0;ack<=0;end
  else begin
   req_sync<={req_sync[0],request};
   if(dst_valid && dst_ready) ack<=req_sync[1];
  end
 end
endmodule
