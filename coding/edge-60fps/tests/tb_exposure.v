`timescale 1ns/1ps
module tb_exposure;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0;
 reg [7:0] index=0;
 wire [24:0] word;
 i2c_master_reg_rom rom(clk,index,word);
 i2c_master_ctrl_top sensor(.clk(clk),.rst_n(rst_n),.scl_pad_i(1'b1),.sda_pad_i(1'b1));
 reg [15:0] injected_address;
 reg [7:0] injected_data;
 reg injected_valid=0;
 integer i,writes=0,reads=0;
 reg [15:0] exposure;
 reg [15:0] gain;
 task readback;
  input [15:0] address;
  input [7:0] data;
  begin
   @(negedge clk);injected_address=address;injected_data=data;injected_valid=1;
   @(negedge clk);injected_valid=0;
  end
 endtask
 initial begin
  force sensor.addr=injected_address;
  force sensor.get_data=injected_data;
  force sensor.get_valid=injected_valid;
  repeat(2)@(negedge clk);rst_n=1;
  for(i=0;i<190;i=i+1) begin
   @(negedge clk);index=i;
   @(posedge clk);#1;
   if(word[0])reads=reads+1;
   else begin
    writes=writes+1;
    case(word[24:9])
     16'h3e00:exposure[15:12]=word[4:1];
     16'h3e01:exposure[11:4]=word[8:1];
     16'h3e02:exposure[3:0]=word[8:5];
     16'h3e08:gain[15:8]=word[8:1];
     16'h3e09:gain[7:0]=word[8:1];
    endcase
   end
  end
  if(exposure!==16'd1381 || gain!==16'h803d || writes!=173 || reads!=17 ||
     word!=={16'h0100,8'h00,1'b1}) $fatal(1,"exposure ROM mismatch");
  readback(16'h3e00,0);readback(16'h3e01,8'h56);readback(16'h3e02,8'h50);
  readback(16'h3e08,8'h80);readback(16'h3e09,8'h3d);
  if(sensor.sensor_exposure_gain!==32'h0565803d || sensor.sensor_diag[7:0]!==0)
   $fatal(1,"exposure readback packing or premature ready");
  readback(16'h0100,1);
  if(sensor.sensor_diag[7:0]!==1)$fatal(1,"stream ready mismatch");
  $display("PASS: exposure=1381 half-lines gain=803d, ROM writes/reads and startup readback");
  $finish;
 end
endmodule
