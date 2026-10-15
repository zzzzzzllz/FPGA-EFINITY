// Destructive boot check. Own the AXI port until both pattern passes finish.
// All locations are written before any are read, so aliased addresses fail.
module frame_memory_probe (
 input clk, rst_n, start,
 output reg done, failed,
 output reg [31:0] fail_address, checks,
 output [31:0] awaddr, araddr,
 output awvalid, wvalid, wlast, bready, arvalid, rready,
 output [127:0] wdata,
 input awready, wready, bvalid, arready, rvalid, rlast,
 input [1:0] bresp, rresp,
 input [127:0] rdata
);
 localparam IDLE=0, WA=1, WD=2, WB=3, RA=4, RD=5, STOP=6;
 // 0..23: byte address bits 4..27; 24..151: first/last word of
 // each 4 MiB block; 152: zero. This covers the complete 256 MiB range.
 localparam LAST=152;
 reg [2:0] state;
 reg [7:0] index;
 reg complement;
 reg [25:0] watchdog;
 wire [31:0] address = index<24 ? (32'd16<<index) :
                             index==LAST ? 32'd0 :
                             (((index-24)>>1)<<22) | (index[0]?32'h003ffff0:32'd0);
 // Derive the pattern from the address, since the bit test and block test
 // intentionally visit some locations twice.
 wire [31:0] pattern=address ^ (complement?32'h5aa59669:32'ha55a6996);
 assign wdata={pattern,~pattern,pattern^32'h13579bdf,pattern^32'h2468ace0};
 assign awaddr=address;
 assign araddr=address;
 assign awvalid=state==WA;
 assign wvalid=state==WD;
 assign wlast=1'b1;
 assign bready=state==WB;
 assign arvalid=state==RA;
 assign rready=state==RD;
 always @(posedge clk) begin
  if(!rst_n) begin
   state<=IDLE;index<=0;complement<=0;done<=0;failed<=0;
   fail_address<=0;checks<=0;watchdog<=0;
  end else begin
   if(state!=IDLE && state!=STOP) watchdog<=watchdog+1'b1;
   if(&watchdog && state!=STOP) begin
    failed<=1;fail_address<=address;state<=STOP;
   end else case(state)
    IDLE: if(start) begin state<=WA;watchdog<=0;end
    WA: if(awready) state<=WD;
    WD: if(wready) state<=WB;
    WB: if(bvalid) begin
     if(bresp!=0) begin failed<=1;fail_address<=address;state<=STOP;end
     else if(index==LAST) begin index<=0;state<=RA;end
     else begin index<=index+1'b1;state<=WA;end
    end
    RA: if(arready) state<=RD;
    RD: if(rvalid) begin
     if(rresp!=0 || !rlast || rdata!=wdata) begin
      failed<=1;fail_address<=address;state<=STOP;
     end else begin
      checks<=checks+1'b1;
      if(index==LAST) begin
       if(complement) begin done<=1;state<=STOP;end
       else begin complement<=1;index<=0;state<=WA;end
      end else begin index<=index+1'b1;state<=RA;end
     end
    end
    default: ;
   endcase
  end
 end
endmodule
