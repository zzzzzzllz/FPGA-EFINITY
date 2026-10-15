`timescale 1ns/1ps
module tb_o1_i2c;
 reg clk=0; always #100 clk=~clk;
 reg rst_n=0,rd_en=0,wr_en=0,nack=0;
 reg [7:0] mock_byte=8'hcd,bus_read;
 wire init_done,rd_done,wr_done,valid,error,bus_wr,bus_cs;
 wire [2:0] bus_addr;
 wire [7:0] data,bus_data;
 integer cycles;
 always @(posedge clk) bus_read<=bus_addr==3 ? mock_byte : {nack,7'h20};
 i2c_16addr_8data dut(.clk(clk),.rst_n(rst_n),.din(8'h90),.addr(16'h3e01),
  .dout(data),.dev_addr(8'h60),.init_done(init_done),.wr_en(wr_en),.rd_en(rd_en),
  .wr_done(wr_done),.rd_done(rd_done),.dout_valid(valid),.nack_error(error),
  .i2c_address(bus_addr),.i2c_write(bus_wr),.i2c_writedata(bus_data),
  .i2c_chipselect(bus_cs),.i2c_waitrequest(1'b0),.i2c_readdata(bus_read));
 task transaction;
  input write_mode,fail;input [7:0] expected;
  begin
   @(negedge clk);nack=fail;mock_byte=expected;wr_en=write_mode;rd_en=!write_mode;
   @(negedge clk);wr_en=0;rd_en=0;cycles=0;
   while(!(wr_done||rd_done)&&cycles<500) begin @(negedge clk);cycles=cycles+1;end
   if(cycles==500) $fatal(1,"I2C transaction timeout");
   if(error!==fail) $fatal(1,"NACK was lost or not cleared");
   if(!write_mode && (!valid || data!==expected)) $fatal(1,"RX alignment error: %h",data);
   repeat(8) @(negedge clk);
  end
 endtask
 initial begin
  repeat(3) @(negedge clk);rst_n=1;repeat(10) @(negedge clk);
  if(!init_done) $fatal(1,"I2C initialization failed");
  transaction(0,0,8'hcd);transaction(0,0,8'h6b);
  transaction(1,1,0);transaction(1,0,0);transaction(0,1,8'h90);transaction(0,0,8'h90);
  $display("PASS O1 I2C: registered RX data, read/write NACK, error clears on next request");$finish;
 end
endmodule
