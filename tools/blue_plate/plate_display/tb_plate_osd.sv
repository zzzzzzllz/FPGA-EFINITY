`timescale 1ns/1ps
`include "plate_defs.vh"
`include "test_ids.vh"
module tb_plate_osd;
 reg clk=0,rst=0;always #5 clk=~clk;
 reg [10:0] x=0,y=0;reg de=0,hs=0,vs=0;reg [23:0] rgb=24'h263849;
 reg [`PD_BITS:0] active=0;
 wire [23:0] pixel;wire od,oh,ov;
 plate_osd #(.X(16),.Y(16)) dut(clk,rst,x,y,de,hs,vs,rgb,active,pixel,od,oh,ov);
 integer fd,f,xx,yy;
 reg [48:0] sample_ids[0:31];
 initial begin
  $readmemh("tmp/blue-plate-plate-display/plate_ids.mem",sample_ids);
  fd=$fopen("tmp/blue-plate-plate-display/osd.ppm","wb");if(!fd)$fatal(1,"output file");
  $fwrite(fd,"P6\n320 2560\n255\n");
  repeat(4)@(negedge clk);rst=1;
  for(f=0;f<32;f=f+1) begin
   active=0;active[`PD_BITS]=f<31;active[`PD_IDS]=sample_ids[f];
   for(yy=0;yy<80;yy=yy+1)for(xx=0;xx<320;xx=xx+1)begin
    @(negedge clk);x=xx;y=yy;de=1;hs=(xx<3);vs=(yy<2);
    @(posedge clk);#1;
    if(od!==de || oh!==hs || ov!==vs)$fatal(1,"video pipeline misaligned");
    if((xx<16 || xx>=272 || yy<16 || yy>=64) && pixel!==rgb)$fatal(1,"outside panel changed");
    $fwrite(fd,"%c%c%c",pixel[23:16],pixel[15:8],pixel[7:0]);
   end
  end
  @(negedge clk);de=0;@(posedge clk);#1;if(od!==0 || pixel!==rgb)$fatal(1,"blanking changed");
  $fclose(fd);$display("PASS OSD: 31 province renderings + unrecognized, 819200 pixels, RGB/control latency and bounds");$finish;
 end
endmodule
