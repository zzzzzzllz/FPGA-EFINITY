`timescale 1ns/1ps
module tb_gray;
 parameter PAIRS=8388608;
 reg clk=0; always #5 clk=~clk;
 reg rst_n=0,in_valid=0,out_ready=0;
 wire in_ready,out_valid,sof,eol,eof;
 reg [63:0] rgb=0;
 wire [63:0] rgby;
 reg isof=0,ieol=0,ieof=0;
 reg [31:0] fid=0,epoch=0;
 wire [31:0] ofid,oepoch;
 integer sent=0,received=0,cycles=0;
 reg [31:0] random_state=32'h13579bdf;
 reg stalled=0,accepted=0;
 reg [130:0] held;
 wire [130:0] token={rgby,sof,eol,eof,ofid,oepoch};
 rgb_to_gray dut(clk,rst_n,in_valid,in_ready,rgb,isof,ieol,ieof,fid,epoch,
                 out_valid,out_ready,rgby,sof,eol,eof,ofid,oepoch);
 function [31:0] reference;
  input integer color;
  integer y;
  begin
   y=(77*((color>>16)&255)+150*((color>>8)&255)+29*(color&255)+128)/256;
   reference={y[7:0],color[23:0]};
  end
 endfunction
 always @(posedge clk) if(rst_n) begin
  if(stalled && (!out_valid || token!==held)) $fatal(1,"Output changed while stalled");
  stalled=out_valid && !out_ready; held=token;
  if(out_valid && out_ready) begin
   if(rgby!=={reference(received*2),reference(received*2+1)})
    $fatal(1,"Luma/RGB/order mismatch pair=%0d got=%h",received,rgby);
   if(sof!==(received%460800==0) || eol!==(received%640==639) ||
      eof!==(received%460800==460799) || ofid!==received/460800+1 ||
      oepoch!==received/460800/3)
    $fatal(1,"Frame/line/epoch mismatch pair=%0d",received);
   received=received+1;
  end
  accepted=in_valid && in_ready;
  if(accepted) sent=sent+1;
  cycles=cycles+1;
  if(cycles>PAIRS*4+100) $fatal(1,"Stream did not drain");
 end
 always @(negedge clk) if(rst_n) begin
  random_state={random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]};
  out_ready=random_state[1] || random_state[3];
  if(!in_valid || accepted) begin
   in_valid=sent<PAIRS && (random_state[0] || random_state[5]);
   rgb={8'hff,24'(sent*2),8'h5a,24'(sent*2+1)};
   isof=sent%460800==0; ieol=sent%640==639; ieof=sent%460800==460799;
   fid=sent/460800+1; epoch=sent/460800/3;
  end
 end
 initial begin
  repeat(3) @(negedge clk);
  rst_n=1;
  wait(received==PAIRS);
  @(negedge clk); rst_n=0;
  repeat(2) @(negedge clk);
  if(out_valid!==0) $fatal(1,"Reset did not clear valid");
  $display("PASS: %0d RGB pixels, exact rounded Y, RGB preserved, stalls/gaps, SOF/EOL/EOF, frame IDs/epochs, reset",PAIRS*2);
  $finish;
 end
endmodule
