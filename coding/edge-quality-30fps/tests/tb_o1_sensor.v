`timescale 1ns/1ps
module tb_o1_sensor;
 reg clk=0;always #100 clk=~clk;
 reg rst_n=0,frame=0;
 reg [25:0] command=0;
 wire [10:0] response;
 wire scl,sda,scl_oe,sda_oe;
 integer initial_writes=0,runtime_writes=0,runtime_reads=0,cycles;
 reg req=0;
 i2c_master_ctrl_top dut(.clk(clk),.rst_n(rst_n),.sensor_command(command),
  .frame_toggle(frame),.sensor_response(response),.scl_pad_i(1'b1),.scl_pad_o(scl),
  .scl_padoen_o(scl_oe),.sda_pad_i(1'b1),.sda_pad_o(sda),.sda_padoen_o(sda_oe));
 always @(posedge clk) begin
  if(rst_n && dut.wr_en) begin
   if(!dut.configured) initial_writes=initial_writes+1;
   else runtime_writes=runtime_writes+1;
  end
  if(rst_n && dut.configured && dut.rd_en) runtime_reads=runtime_reads+1;
 end
 task transact;
  input write_mode;input [15:0] address;input [7:0] value;
  integer writes_before;
  begin
   @(negedge clk);req=!req;command={req,write_mode,address,value};writes_before=runtime_writes;
   if(write_mode) begin
    repeat(20) @(negedge clk);
    if(response[0]===req || runtime_writes!=writes_before) $fatal(1,"Write escaped frame boundary");
    frame=!frame;
   end
   cycles=0;
   while(response[0]!==req && cycles<100) begin @(negedge clk);cycles=cycles+1;end
   if(cycles==100) $fatal(1,"Runtime command not acknowledged");
   if(response[1]!==dut.u_i2c_ctrl.inject_nack) $fatal(1,"NACK not carried to JTAG response");
   if(!write_mode && response[10:3]!==8'hcd) $fatal(1,"Read byte not captured at done");
   repeat(15) @(negedge clk);
   if(write_mode && runtime_writes!=writes_before+1) $fatal(1,"Request duplicated");
  end
 endtask
 initial begin
  repeat(4) @(negedge clk);rst_n=1;
  cycles=0;while(!response[2] && cycles<5000) begin @(negedge clk);cycles=cycles+1;end
  if(!response[2] || initial_writes!=164) $fatal(1,"ROM initialization changed: %0d",initial_writes);
  repeat(25) @(negedge clk);
  if(runtime_writes || runtime_reads) $fatal(1,"Unexpected runtime I2C without request");
  transact(0,16'h3107,0);
  transact(1,16'h3812,0);transact(1,16'h3e00,0);transact(1,16'h3e01,8'h38);
  transact(1,16'h3e02,8'h40);transact(1,16'h3812,8'h30);
  dut.u_i2c_ctrl.inject_nack=1;transact(1,16'h3e01,0);
  dut.u_i2c_ctrl.inject_nack=0;transact(0,16'h3107,0);
  if(initial_writes!=164 || runtime_writes!=6 || runtime_reads!=2) $fatal(1,"Transaction counts differ");
  $display("PASS O1 arbitration: ROM unchanged, idle untouched, reads, frame-boundary writes, NACK, no duplicates");$finish;
 end
endmodule

// Transaction-level bus stub; tb_o1_i2c checks the actual byte-controller FSM.
module i2c_16addr_8data #(parameter CLK_DIV=0,IRQ_EN=0,I2C_EN=1)(
 input clk,rst_n,wr_en,rd_en,input [15:0] addr,input [7:0] dev_addr,din,
 output [7:0] dout,output reg init_done,rd_done,wr_done,
 output dout_valid,nack_error,output [2:0] i2c_address,
 output i2c_write,output [7:0] i2c_writedata,output i2c_chipselect,
 input i2c_waitrequest,input [7:0] i2c_readdata);
 reg [3:0] delay;reg write_mode,inject_nack=0;
 assign dout=8'hcd;assign dout_valid=rd_done;assign nack_error=inject_nack;
 assign i2c_address=0;assign i2c_write=0;assign i2c_writedata=0;assign i2c_chipselect=0;
 always @(posedge clk) begin
  if(!rst_n) begin init_done<=0;delay<=0;rd_done<=0;wr_done<=0;write_mode<=0;end
  else begin
   init_done<=1;rd_done<=0;wr_done<=0;
   if(wr_en||rd_en) begin
    if(delay) $fatal(1,"I2C overlapped transactions");
    delay<=8;write_mode<=wr_en;
   end else if(delay) begin
    delay<=delay-1;
    if(delay==1) begin wr_done<=write_mode;rd_done<=!write_mode;end
   end
  end
 end
endmodule
module i2c_master_top(input arst_i,scl_pad_i,sda_pad_i,wb_clk_i,wb_rst_i,wb_stb_i,wb_we_i,
 input [2:0] wb_adr_i,input [7:0] wb_dat_i,
 output scl_pad_o,scl_padoen_o,sda_pad_o,sda_padoen_o,wb_ack_o,wb_inta_o,output [7:0] wb_dat_o);
 assign {scl_pad_o,scl_padoen_o,sda_pad_o,sda_padoen_o,wb_ack_o,wb_inta_o,wb_dat_o}=0;
endmodule
