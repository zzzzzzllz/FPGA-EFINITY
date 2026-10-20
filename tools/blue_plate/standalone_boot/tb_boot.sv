`timescale 1ns/1ps
module tb_boot;
 reg CLK_5M=0,w_arstn=0;
 always #100 CLK_5M=~CLK_5M;
 `include "delay.vh"
 reg [25:0] command=0;
 reg frame=0;
 wire [10:0] response;
 wire success,error,scl_o,sda_o,scl_oe,sda_oe;
 reg slave_low=0;
 wire scl=scl_oe ? 1'b1 : scl_o;
 wire sda=(sda_oe ? 1'b1 : sda_o) & !slave_low;
 `ifdef FAST
 localparam DIV=2;
 `else
 localparam DIV=32;
 `endif
 i2c_master_ctrl_top #(.CLK_DIV(DIV)) dut(
  .clk(CLK_5M),.rst_n(i2c_rst_n),.sensor_command(command),.frame_toggle(frame),
  .sensor_response(response),.init_success(success),.init_error(error),
  .scl_pad_i(scl),.scl_pad_o(scl_o),.scl_padoen_o(scl_oe),
  .sda_pad_i(sda),.sda_pad_o(sda_o),.sda_padoen_o(sda_oe));
 reg [23:0] expected[0:165];
 reg [7:0] bytes[0:3],shift;
 integer bits=0,byte_no=0,transactions=0,starts=0,nacks=0,mode=0,case_mode;
 reg bus_active=0,boot_phase=1;
 real release_time;
 function inject;
  input integer tx,by;
  begin
   inject=(mode==5) || (tx==17 && mode>=1 && mode<=4 && by==mode-1) ||
          (mode==6 && tx==165 && by==3);
  end
 endfunction
 // Model only the sensor's open-drain ACK pin; observe the actual transmitted bytes.
 always @(negedge sda) if(scl && i2c_rst_n) begin
  if(bus_active) $fatal(1,"unexpected repeated START");
  bus_active=1;bits=0;byte_no=0;shift=0;starts=starts+1;
  if(starts==1) begin
   $display("CHECK mode=%0d DIV=%0d first_START_us=%0.3f",mode,DIV,($realtime-release_time)/1000.0);
   if($realtime-release_time<4000000) $fatal(1,"START before 4 ms");
  end
 end
 always @(negedge scl) begin
  if(bus_active && bits==8) slave_low=!inject(transactions,byte_no);
  else slave_low=0;
 end
 always @(posedge scl) if(bus_active) begin
  if(bits<8) begin
   shift={shift[6:0],sda};bits=bits+1;
   if(bits==8) begin
    if(byte_no>3) $fatal(1,"too many bytes");
    bytes[byte_no]=shift;
   end
  end else begin
   if(sda!==inject(transactions,byte_no)) $fatal(1,"ACK model mismatch");
   if(sda) nacks=nacks+1;
   bits=0;byte_no=byte_no+1;
  end
 end
 always @(posedge sda) if(scl && bus_active && i2c_rst_n) begin
  bus_active=0;
  if(byte_no!=4) $fatal(1,"transaction bytes=%0d",byte_no);
  if(bytes[0]!==8'h60) $fatal(1,"wrong sensor address %h",bytes[0]);
  if(transactions<166) begin
   if({bytes[1],bytes[2],bytes[3]}!==expected[transactions])
    $fatal(1,"ROM transaction %0d actual=%h expected=%h",transactions,{bytes[1],bytes[2],bytes[3]},expected[transactions]);
   if({bytes[1],bytes[2],bytes[3]}==24'h010001 && transactions!=165)
    $fatal(1,"early stream-on");
  end else if({bytes[1],bytes[2]}!==16'h3e01 || bytes[3]!==8'h70+transactions-166)
   $fatal(1,"runtime write mismatch");
  transactions=transactions+1;
 end
 always @(posedge success) if(i2c_rst_n && boot_phase && mode!=0)
  $fatal(1,"failed initialization produced a success pulse");
 always @(posedge CLK_5M) if(i2c_rst_n && boot_phase && mode!=0 && success)
  $fatal(1,"failed initialization reported success");
 task reset_boot;
  input integer next_mode;
  begin
   @(negedge CLK_5M);w_arstn=0;command=0;frame=0;slave_low=0;bus_active=0;
   repeat(8) @(negedge CLK_5M);
   if(success!==0 || error!==0 || response[2]!==0) $fatal(1,"reset did not clear init state");
   bits=0;byte_no=0;transactions=0;starts=0;nacks=0;mode=next_mode;boot_phase=1;
   w_arstn=1;release_time=$realtime;
  end
 endtask
 task finish_init;
  input expected_error;
  begin
   wait(response[2]);repeat(3) @(negedge CLK_5M);
   if(transactions!=166 || starts!=166) $fatal(1,"table incomplete: %0d/%0d",transactions,starts);
   if(error!==expected_error || success!==!expected_error || response[1]!==0)
    $fatal(1,"init status wrong success=%b error=%b runtime=%b",success,error,response[1]);
   if((nacks!=0)!==expected_error) $fatal(1,"fault was not injected");
   repeat(100) @(negedge CLK_5M);
   if(starts!=166) $fatal(1,"unexpected automatic retry");
   $display("CHECK table=166 final_stream_on=165 NACKs=%0d success=%b error=%b configured=%b",nacks,success,error,response[2]);
   boot_phase=0;
  end
 endtask
 task runtime_write;
  input integer index;
  input fail,boot_error;
  reg request;
  integer before_count;
  begin
   mode=fail?5:0;before_count=starts;
   @(negedge CLK_5M);request=!command[25];command={request,1'b1,16'h3e01,8'h70+index[7:0]};
   repeat(20) @(negedge CLK_5M);
   if(starts!=before_count || response[0]===request) $fatal(1,"write escaped frame boundary");
   frame=!frame;wait(response[0]===request);repeat(4) @(negedge CLK_5M);
   if(response[1]!==fail || starts!=before_count+1 || error!==boot_error || success!==!boot_error)
    $fatal(1,"runtime command changed init result or lost error");
  end
 endtask
 initial begin
  $readmemh("expected.hex",expected);
  if(!$value$plusargs("MODE=%d",case_mode)) case_mode=0;
  reset_boot(case_mode);finish_init(case_mode!=0);
  runtime_write(0,0,case_mode!=0);runtime_write(1,1,case_mode!=0);runtime_write(2,0,case_mode!=0);
  if(case_mode==5) begin
   reset_boot(0);finish_init(0);
   runtime_write(0,0,0);runtime_write(1,1,0);runtime_write(2,0,0);
   $display("CHECK reset recovery restored successful initialization");
  end
  $display("PASS boot mode=%0d DIV=%0d: wire bytes, init state, runtime isolation, no retry",case_mode,DIV);
  $finish;
 end
 initial begin #600000000;$fatal(1,"boot timeout");end
endmodule
