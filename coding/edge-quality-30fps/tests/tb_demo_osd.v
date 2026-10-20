`timescale 1ns/1ps
module tb_demo_osd;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,de=0;reg [63:0] ui=0;
 wire [23:0] out_rgb;
 integer x,y,s,fd;
 threshold_osd dut(.clk(clk),.rst_n(rst_n),.vs(1'b0),.de(de),.metadata(7'd0),.rgb(24'h182434),.out_rgb(out_rgb),.ui_status(ui));
 initial begin
  repeat(3) @(negedge clk);rst_n=1;de=1;
  force dut.x=x;force dut.y=y;
  fd=$fopen("../../tmp/tests/edge-quality-30fps/regression/serial-demo-osd.ppm","wb");if(!fd) $fatal(1,"cannot create OSD raster");$fwrite(fd,"P6\n1280 960\n255\n");
  for(s=1;s<=13;s=s+1) if(s!=9) begin
   ui=0;ui[27:24]=s;ui[63:56]=30;ui[55:48]=30;
   if(s==3) ui[10]=1;
   if(s==11) ui[47:42]=32;
   if(s==12) ui[14:12]=2;
   if(s==13) ui[11]=1;
   for(y=640;y<720;y=y+1) for(x=0;x<1280;x=x+1) begin
    @(posedge clk);#1;
    if(y==640 && x==16 && dut.menu_character!=(s<10?"0":"1")) $fatal(1,"step tens");
    if(y==640 && x==32 && dut.menu_character!=8'd48+s%10) $fatal(1,"step units");
    if(y==640 && x==17*16 && dut.menu_character!="K") $fatal(1,"KEY2 action missing");
    if(y==640 && x==35*16 && dut.menu_character!="K") $fatal(1,"KEY3 action missing");
    if(s==8 && y==640 && x==22*16 && dut.menu_character!="-") $fatal(1,"shape threshold minus hint");
    if(s==8 && y==640 && x==40*16 && dut.menu_character!="+") $fatal(1,"shape threshold plus hint");
    if(y==672 && x==8*32 && dut.character!="K") $fatal(1,"navigation hint missing");
    $fwrite(fd,"%c%c%c",out_rgb[23:16],out_rgb[15:8],out_rgb[7:0]);
   end
  end
  $fclose(fd);release dut.x;release dut.y;
  $display("PASS: rendered 12 pages, task 8 threshold hints, navigation, NO CLIP and WAIT");$finish;
 end
endmodule
