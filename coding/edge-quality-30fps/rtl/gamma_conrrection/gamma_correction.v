// Three synchronous lookups use two existing dual-port ROMs.
// Original curve, address expansion, rounding and one-cycle latency.
module gamma_correction #(parameter DATA_WIDTH=10,GAMMA_CURVE="2P2.mem")(
 input i_pclk,i_rstn,i_valid,i_hs,i_vs,
 input [DATA_WIDTH-1:0] i_red,i_green,i_blue,
 output [DATA_WIDTH-1:0] o_red,o_green,o_blue,
 output reg o_valid,o_hs,o_vs
);
 wire [9:0] ra,ga,ba,rv,gv,bv;
 generate if(DATA_WIDTH==10) begin
  assign ra=i_red;assign ga=i_green;assign ba=i_blue;
 end else begin
  assign ra={i_red,i_red[7:6]};assign ga={i_green,i_green[7:6]};assign ba={i_blue,i_blue[7:6]};
 end endgenerate
 true_dual_port_ram #(.DATA_WIDTH(10),.ADDR_WIDTH(10),.RAM_INIT_FILE(GAMMA_CURVE)) rg_rom(
  .we1(1'b0),.we2(1'b0),.clka(i_pclk),.clkb(i_pclk),.din1(10'd0),.din2(10'd0),
  .addr1(ra),.addr2(ga),.dout1(rv),.dout2(gv));
 true_dual_port_ram #(.DATA_WIDTH(10),.ADDR_WIDTH(10),.RAM_INIT_FILE(GAMMA_CURVE)) b_rom(
  .we1(1'b0),.we2(1'b0),.clka(i_pclk),.clkb(1'b0),.din1(10'd0),.din2(10'd0),
  .addr1(ba),.addr2(10'd0),.dout1(bv),.dout2());
 assign o_red=o_valid ? (DATA_WIDTH==10 ? rv : rv[9:2]) : 0;
 assign o_green=o_valid ? (DATA_WIDTH==10 ? gv : gv[9:2]) : 0;
 assign o_blue=o_valid ? (DATA_WIDTH==10 ? bv : bv[9:2]) : 0;
 always @(posedge i_pclk) begin
  if(!i_rstn) begin o_valid<=0;o_hs<=0;o_vs<=0;end
  else begin o_valid<=i_valid;o_hs<=i_hs;o_vs<=i_vs;end
 end
endmodule
