`timescale 1ns/1ps
module tb_gamma_rom;
 reg clk=0;always #5 clk=~clk;
 reg rst=0,valid=0,hs=0,vs=0;
 reg [7:0] r=0,g=0,b=0;
 wire [7:0] nr,ng,nb,oldr,oldg,oldb;wire nv,nh,ns,ov,oh,os;
 gamma_correction #(.DATA_WIDTH(8),.GAMMA_CURVE("rtl/gamma_conrrection/2P2.mem")) current_gamma(
 clk,rst,valid,hs,vs,r,g,b,nr,ng,nb,nv,nh,ns);
 gamma_correction_before #(.DATA_WIDTH(8),.GAMMA_CURVE("rtl/gamma_conrrection/2P2.mem")) baseline(
 clk,rst,valid,hs,vs,r,g,b,oldr,oldg,oldb,ov,oh,os);
 integer i;
 initial begin
  repeat(4) @(negedge clk);rst=1;
  repeat(1100) @(negedge clk);
  for(i=0;i<1024;i=i+1) begin
   r=i;g=i*37;b=255-i;valid=i<768;hs=i%3==0;vs=i%7==0;
   @(negedge clk);
   if({nr,ng,nb,nv,nh,ns}!=={oldr,oldg,oldb,ov,oh,os})
    $fatal(1,"gamma mismatch input %d: %h/%h",i,{nr,ng,nb},{oldr,oldg,oldb});
  end
  $display("PASS: Gamma ROM matches the accepted curve for every 8-bit channel input, outputs and one-cycle sync/blanking");
  $finish;
 end
endmodule
