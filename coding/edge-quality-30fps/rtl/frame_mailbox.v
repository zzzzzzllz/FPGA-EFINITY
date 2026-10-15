// Bundled-data CDC: hold the complete payload until the destination acks it.
module frame_mailbox #(parameter WIDTH=32,ALWAYS_SEND=0)(
 input rst_n,src_clk,dst_clk,input [WIDTH-1:0] src_data,
 output delivered,output reg [WIDTH-1:0] dst_data
);
 reg [WIDTH-1:0] held;
 reg request,ack;
 (* async_reg="true" *) reg [1:0] request_sync,ack_sync;
 assign delivered=request==ack_sync[1] && held==src_data;
 always @(posedge src_clk) begin
  if(!rst_n) begin held<=0;request<=0;ack_sync<=0;end
  else begin
   ack_sync<={ack_sync[0],ack};
   if(request==ack_sync[1] && (ALWAYS_SEND || held!=src_data)) begin held<=src_data;request<=!request;end
  end
 end
 always @(posedge dst_clk) begin
  if(!rst_n) begin request_sync<=0;ack<=0;dst_data<=0;end
  else begin
   request_sync<={request_sync[0],request};
   if(request_sync[1]!=ack) begin dst_data<=held;ack<=request_sync[1];end
  end
 end
endmodule
