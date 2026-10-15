`timescale 1ns/1ps
module tb_o1_response_cdc;
 reg pixel_clk=0;always #7 pixel_clk=~pixel_clk;
 reg reset_n=0;reg [10:0] response=0;
 ti60f225_oob_top dut(.i_mipi_rx_pclk(pixel_clk));
 initial begin
  force dut.w_arstn=reset_n;
  force dut.sensor_response=response;
  repeat(5) @(negedge pixel_clk);reset_n=1;
  #3;response={8'h00,1'b1,1'b0,1'b0};
  repeat(5) @(negedge pixel_clk);
  if(dut.sensor_response_cdc!==11'h004) $fatal(1,"Configured status did not cross");
  #3;response={8'hcd,1'b1,1'b0,1'b1};
  repeat(6) begin
   @(negedge pixel_clk);
   if(dut.sensor_response_cdc[0] && dut.sensor_response_cdc!={8'hcd,1'b1,1'b0,1'b1})
    $fatal(1,"Acknowledged response contains stale data");
  end
  if(dut.sensor_response_cdc!==response) $fatal(1,"First response lost");
  #5;response={8'h6b,1'b1,1'b1,1'b0};
  repeat(6) begin
   @(negedge pixel_clk);
   if(!dut.sensor_response_cdc[0] && dut.sensor_response_cdc!={8'h6b,1'b1,1'b1,1'b0})
    $fatal(1,"Error/data were not bundled with acknowledgement");
  end
  if(dut.sensor_response_cdc!==response) $fatal(1,"Second response lost");
  $display("PASS O1 top-level response CDC: readiness, both toggle directions, data and NACK coherent");$finish;
 end
endmodule
