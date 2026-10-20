`timescale 1ns/1ps
module tb_startup;
reg CLK_5M=0,w_arstn=0;
always #100 CLK_5M=~CLK_5M;
wire scl_oe,sda_oe,scl_o,sda_o;
wire scl=scl_oe?1'b1:scl_o;
wire sda=sda_oe?1'b1:sda_o;
wire [10:0] response;
real release_ns;
integer starts=0;
reg [12:0] i2c_rst_cnt = '0;

always @( posedge CLK_5M or negedge w_arstn )
begin
    if( !w_arstn )
       i2c_rst_cnt <= 'd0;
    else 
       i2c_rst_cnt <= i2c_rst_cnt[12] ? i2c_rst_cnt : i2c_rst_cnt + 1'b1;
end
wire i2c_rst_n = i2c_rst_cnt[12];


i2c_master_ctrl_top dut(.clk(CLK_5M),.rst_n(i2c_rst_n),.sensor_command(26'b0),.frame_toggle(1'b0),.sensor_response(response),.scl_pad_i(scl),.scl_pad_o(scl_o),.scl_padoen_o(scl_oe),.sda_pad_i(sda),.sda_pad_o(sda_o),.sda_padoen_o(sda_oe));
initial begin repeat(5) @(negedge CLK_5M);w_arstn=1;release_ns=$realtime;end
always @(negedge sda) if(scl===1'b1 && i2c_rst_n) begin
 starts=starts+1;
 if(starts==1) $display("MEASURE first_start_after_w_arstn_us=%0.3f",($realtime-release_ns)/1000.0);
end
always @(posedge response[2]) begin
 $display("MEASURE no_sensor_ack configured=%b runtime_error=%b starts=%0d time_us=%0.3f",response[2],response[1],starts,($realtime-release_ns)/1000.0);
 if(starts!=164 || response[1]!==0) $fatal(1,"unexpected audit observation");
 $display("PASS observed all-NACK init still declares configured");$finish;
end
initial begin #300000000;$fatal(1,"audit timeout");end
endmodule
