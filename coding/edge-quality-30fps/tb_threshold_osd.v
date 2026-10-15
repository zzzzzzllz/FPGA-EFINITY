`timescale 1ns/1ps
module tb_threshold_osd;
 reg clk=0;always #5 clk=~clk;
 reg rst=0,vs=0,de=0;reg [6:0] meta=0;
 reg [23:0] rgb=24'h123456;wire [23:0] out_rgb;wire [10:0] shown;
 threshold_osd #(.H(80)) dut(clk,rst,vs,de,meta,rgb,out_rgb,shown,shown_flags,shown_descriptor,shown_toggle,64'd0);
 wire [300:0] shown_descriptor;wire shown_toggle;
 wire [2:0] shown_flags;
 integer f,x,y,t,fd;reg [15:0] decimal_value;
 reg [300:0] descriptor;wire [300:0] descriptor_bits=descriptor;
 initial begin
  fd=$fopen("tmp/m05-osd.ppm","w");$fwrite(fd,"P3\n1280 80\n255\n");
  repeat(4) @(negedge clk);rst=1;
  for(f=0;f<8;f=f+1) begin
   case(f%4) 0:t=0;1:t=32;2:t=192;3:t=2040;endcase
   decimal_value={4'(t/1000),4'((t/100)%10),4'((t/10)%10),4'(t%10)};
   descriptor={3'(f),1'(f%2),3'(f%5),2'(f%3),32'(f+100),32'(f+10),32'(f+1)};
   vs=1;de=0;repeat(3) @(negedge clk);vs=0;
   for(y=0;y<80;y=y+1) begin
    for(x=0;x<1280;x=x+1) begin
     de=1;meta=y==0 && x==0 ? 7'(t) : (y==0 && x==1 ? {3'(f),4'(t>>7)} :
                     (y==0 && x>=2 && x<=44 ? descriptor_bits[(x-2)*7 +:7] : 7'd127));
     #1;
     if(y>0 && (shown_flags!==3'(f) || shown!==t || dut.bcd!==decimal_value)) $fatal(1,"OSD value mismatch");
     if(y>0 && (shown_descriptor!==descriptor || shown_toggle!==1'(!(f%2)))) $fatal(1,"OSD frame descriptor mismatch");
     if(((y<32 || y>=64 || x<16 || x>=1264) && !(y>=8 && y<24 && x>=16 && x<1280) && !(y<16 && x>=16 && x<1232)) && out_rgb!==rgb) $fatal(1,"OSD changed image outside strip");
     if(x==32 && y==32 && out_rgb!==24'h66ffff) $fatal(1,"T glyph top stroke missing");
     if(x==32 && y==36 && out_rgb!==24'h202020) $fatal(1,"T glyph blank/background wrong");
     if(f==3) $fwrite(fd,"%0d %0d %0d\n",out_rgb[23:16],out_rgb[15:8],out_rgb[7:0]);
     @(negedge clk);
    end
    de=0;repeat(4) @(negedge clk);
   end
  end
  $fclose(fd);
  $display("PASS OSD: T=0/32/192/2040, decimal digits, same-frame FIFO metadata, glyph strokes and image preservation");
  $finish;
 end
endmodule
