`timescale 1ns/1ps
module tb_canny_local;
 parameter W=32,H=24;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0;
 reg [15:0] config_value;
 reg [63:0] pixels;
 reg valid=0,sof=0,eol=0,eof=0,ready=0;
 wire in_ready,out_valid,os,ol,oe;
 wire [63:0] output_pixels;
 wire [31:0] oid,oepoch;
 wire [15:0] oc;
 reg [31:0] source[0:W*H-1],expected[0:W*H-1];
 reg [1023:0] input_file,class_file;
 integer sent=0,received=0,cycles=0;
 reg [31:0] rng=32'h901;
 edge_algorithm_pair #(.W(W),.H(H)) dut(.clk(clk),.rst_n(rst_n),.in_config(config_value),
  .in_pixels(pixels),.in_valid(valid),.in_ready(in_ready),.in_sof(sof),.in_eol(eol),.in_eof(eof),
  .in_id(32'd901),.in_epoch(32'd19),.out_pixels(output_pixels),.out_valid(out_valid),.out_ready(ready),
  .out_sof(os),.out_eol(ol),.out_eof(oe),.out_id(oid),.out_epoch(oepoch),.out_config(oc));
 function [31:0] expected_pixel;
  input integer index;
  reg [31:0] value;
  begin
   value=expected[index];
   if(!config_value[13]) begin
    value[30:24]=7'd5;
    if(index==1) value[30:24]=config_value[6:0];
    if(index==2) value[30:24]={1'b0,config_value[12:11],config_value[10:7]};
   end
   expected_pixel=value;
  end
 endfunction
 initial begin
  if(!$value$plusargs("input=%s",input_file) || !$value$plusargs("expected=%s",class_file) ||
     !$value$plusargs("config=%d",config_value)) $fatal(1,"missing vector arguments");
  $readmemh(input_file,source);$readmemh(class_file,expected);
  repeat(5) @(negedge clk);rst_n=1;
 end
 always @(negedge clk) if(rst_n) begin
  rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};ready=rng[3:0]!=0;
  if(!valid && sent<W*H && rng[7:4]!=0) begin
   valid=1;pixels={source[sent],source[sent+1]};
   sof=sent==0;eol=sent%W==W-2;eof=sent==W*H-2;
  end
 end
 always @(posedge clk) if(rst_n) begin
  cycles=cycles+1;
  if(valid && in_ready) begin sent=sent+2;valid<=0;end
  if(out_valid && ready) begin
   if(output_pixels!=={expected_pixel(received),expected_pixel(received+1)})
    $fatal(1,"pixel %0d got %h expected %h",received,output_pixels,{expected_pixel(received),expected_pixel(received+1)});
   if(os!==(received==0) || ol!==(received%W==W-2) || oe!==(received==W*H-2) || oid!=901 || oepoch!=19 || oc!=config_value)
    $fatal(1,"metadata at %0d",received);
   received=received+2;
   if(received==W*H) begin $display("PASS local %0dx%0d config=%h pixels=%0d cycles=%0d",W,H,config_value,received,cycles);$finish;end
  end
  if(cycles>W*H*10) $fatal(1,"timeout sent=%0d received=%0d",sent,received);
 end
endmodule
