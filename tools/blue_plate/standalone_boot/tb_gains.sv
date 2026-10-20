`timescale 1ns/1ps
module tb_gains;
 reg i_mipi_rx_pclk=0,w_arstn=0,w_mipi_rx_vs=0;
 always #10 i_mipi_rx_pclk=~i_mipi_rx_pclk;
 wire [15:0] r_gain,g_gain,b_gain;
 wire [1:0] bayer_phase;
 wire gamma_sel;
 wire median_set=0,denoise_set=0,ui_algorithm=0,ui_recognition=0;
 wire [1:0] ui_ratio=1;
 reg median_active=0,denoise_active=0,algorithm_active=0,recognition_active=0;
 reg [1:0] ratio_active=1;
 reg [31:0] median_epoch=0;
 `include "gain_initial.vh"
 `include "gain_active.vh"
 debug_edb_top vio(
  .bscan_CAPTURE(1'b0),.bscan_DRCK(1'b0),.bscan_RESET(1'b0),.bscan_RUNTEST(1'b0),
  .bscan_SEL(1'b0),.bscan_SHIFT(1'b0),.bscan_TCK(i_mipi_rx_pclk),.bscan_TDI(1'b0),
  .bscan_TMS(1'b0),.bscan_UPDATE(1'b0),.status_clk(i_mipi_rx_pclk),.status_build_id(32'b0),
  .status_r_gain(r_gain),.status_g_gain(g_gain),.status_b_gain(b_gain),
  .status_phase(bayer_phase),.status_gamma_sel(gamma_sel),
  .snapshot_clk(i_mipi_rx_pclk),.snapshot_data(64'b0),.snapshot_page_ack(6'b0),
  .snapshot_capture_ack(1'b0),.snapshot_sensor_response(11'b0));
 task check;
  begin
   if({r_gain,g_gain,b_gain}!=={16'd389,16'd256,16'd427} ||
      {active_r,active_g,active_b}!=={16'd389,16'd256,16'd427} ||
      active_phase!==0 || bayer_phase!==0 || gamma_sel!==0 || config_epoch!==0)
    $fatal(1,"gain/phase/gamma changed after frame/reset");
  end
 endtask
 integer i;
 initial begin
  #1;check();repeat(5) @(negedge i_mipi_rx_pclk);w_arstn=1;
  for(i=0;i<12;i=i+1) begin
   repeat(5) @(negedge i_mipi_rx_pclk);w_mipi_rx_vs=1;
   repeat(3) @(negedge i_mipi_rx_pclk);check();w_mipi_rx_vs=0;
   if(i==5) begin w_arstn=0;repeat(4) @(negedge i_mipi_rx_pclk);check();w_arstn=1;end
  end
  $display("PASS gains: actual VIO RTL + extracted active block, initial/reset and 12 frames = 389/256/427");
  $finish;
 end
 initial begin #100000;$fatal(1,"gain timeout");end
endmodule
