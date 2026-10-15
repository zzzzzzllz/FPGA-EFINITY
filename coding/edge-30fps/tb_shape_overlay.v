`timescale 1ns/1ps
module tb_shape_overlay;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,vs=0,de=0;reg [6:0] metadata=0;
 wire [23:0] rgb;wire [300:0] shown;wire toggle;
 reg [300:0] packet;
 integer mode,x,y,checks=0;
 reg border;integer x0,x1,y0,y1;
 threshold_osd dut(.clk(clk),.rst_n(rst_n),.vs(vs),.de(de),.metadata(metadata),.rgb(24'h123456),.out_rgb(rgb),
  .shown_descriptor(shown),.shown_toggle(toggle),.ui_status(64'd0));
 initial begin
  repeat(5) @(negedge clk);rst_n=1;
  for(mode=0;mode<4;mode=mode+1) begin
   packet=0;packet[31:0]=101+mode;packet[63:32]=20+mode;
   packet[105 +:44]={11'd500,11'd400,11'd100,11'd100};
   packet[281 +:2]=1;packet[291:289]=1;packet[293]=mode!=3;
   packet[296]=mode==1 || mode==2;packet[294]=mode==2;
   vs=1;repeat(2) @(negedge clk);vs=0;
   for(y=0;y<720;y=y+1) for(x=0;x<1280;x=x+1) begin
    de=1;metadata=x>=2 && x<=44 && y==0 ? packet[(x-2)*7 +:7] : 0;
    #1;
    if(y==1 && x==0 && shown!==packet) $fatal(1,"descriptor frame/epoch/boxes mismatch mode=%0d",mode);
    if(y>=30 && y<620) begin
     x0=100;x1=400;y0=100;y1=500;
     if(mode==1 || mode==2) begin x0=50+(x>=640?640:0);x1=200+(x>=640?640:0);y0=230;y1=430;end
     border=mode!=3 && (mode!=2 || x>=640) && x>=x0 && x<=x1 && y>=y0 && y<=y1 && (x<x0+2 || x+2>x1 || y<y0+2 || y+2>y1);
     if(border && rgb!==24'h00ff66) $fatal(1,"missing same-frame box mode=%0d xy=%0d,%0d",mode,x,y);
     if((mode==3 || mode==2 && x<640) && rgb!==24'h123456) $fatal(1,"stale box or reference overlay mode=%0d xy=%0d,%0d",mode,x,y);
     checks=checks+1;
    end
    @(negedge clk);
   end
   de=0;repeat(2) @(negedge clk);
  end
  $display("PASS shape HDMI descriptor, same-frame boxes, split/reference mapping, off clears boxes: %0d pixels",checks);$finish;
 end
endmodule
