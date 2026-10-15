`timescale 1ns/1ps
module tb_canny_rules;
 gaussian_pair gaussian();sobel_pair gradient();canny_nms_pair nms();
 integer i,r,d,low;
 reg [15:0] cfg;
 reg [12:0] center;
 reg [10:0] before_value,after_value;
 reg [1:0] got;
 initial begin
  for(i=0;i<256;i=i+1)
   if(gaussian.gaussian(i,i,i,i,i,i,i,i,i)!=i) $fatal(1,"Gaussian DC %0d",i);
  if(gaussian.gaussian(0,0,0,0,1,0,0,0,0)!=0 || gaussian.gaussian(0,0,0,0,2,0,0,0,0)!=1)
   $fatal(1,"Gaussian half-up rounding");
  if(gradient.direction(256,106)!=0 || gradient.direction(256,107)!=2 ||
     gradient.direction(106,256)!=1 || gradient.direction(107,256)!=2 ||
     gradient.direction(-256,107)!=3 || gradient.direction(256,-107)!=3 ||
     gradient.direction(-256,-107)!=2 || gradient.direction(0,0)!=0)
   $fatal(1,"integer direction boundaries/signs");
  for(i=1;i<=2040;i=i+1) for(r=0;r<3;r=r+1) begin
   cfg=(r<<14)|8192|i;low=i*(r+1)/4;
   if(nms.classify(0,0,0,0,0,0,0,0,0,0,cfg)!=0) $fatal(1,"zero gradient");
   if(nms.classify(0,0,0,0,i,0,0,0,0,0,cfg)!=1) $fatal(1,"G==Th must be weak");
   if(nms.classify(0,0,0,0,i+1,0,0,0,0,0,cfg)!=2) $fatal(1,"G>Th strong");
   if(nms.classify(0,0,0,0,low,0,0,0,0,0,cfg)!=0) $fatal(1,"G==Tl must be discarded");
   if(low+1<=i && nms.classify(0,0,0,0,low+1,0,0,0,0,0,cfg)!=1) $fatal(1,"weak lower boundary");
  end
  cfg=16'h6020;
  for(d=0;d<4;d=d+1) begin
   center=(d<<11)|64;
   // A one-sided plateau keeps its start; equal neighbours on both sides suppress it.
   got=nms.classify(d==2?64:0,d==1?64:0,d==3?64:0,d==0?64:0,center,0,0,0,0,0,cfg);
   if(got!=0) $fatal(1,"strict before comparison direction %0d",d);
   got=nms.classify(0,0,0,0,center,d==0?64:0,d==3?64:0,d==1?64:0,d==2?64:0,0,cfg);
   if(got!=2) $fatal(1,"inclusive after comparison direction %0d",d);
   if(nms.classify(0,0,0,0,center,0,0,0,0,1,cfg)!=0) $fatal(1,"outer border");
  end
  $display("PASS Canny rules: all 6120 threshold/ratio combinations, Gaussian rounding, signed direction ties, four NMS plateaus, border");$finish;
 end
endmodule
