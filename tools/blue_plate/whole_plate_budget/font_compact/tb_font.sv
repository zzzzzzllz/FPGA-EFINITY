`timescale 1ns/1ps
`include "plate_defs.vh"
module tb_font;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=1;reg [10:0] x=0,y=0;reg de=0,hs=0,vs=0;reg [23:0] rgb=0;
 reg [`PD_BITS:0] active_packet=0;
 wire [23:0] ref_rgb,dut_rgb;wire ref_de,ref_hs,ref_vs,dut_de,dut_hs,dut_vs;
 plate_osd #(.FONT_FILE("plate_font.mem")) reference(.clk(clk),.rst_n(rst_n),.x(x),.y(y),.de(de),.hs(hs),.vs(vs),.rgb(rgb),.active_packet(active_packet),.out_rgb(ref_rgb),.out_de(ref_de),.out_hs(ref_hs),.out_vs(ref_vs));
 plate_osd_compact candidate(.clk(clk),.rst_n(rst_n),.x(x),.y(y),.de(de),.hs(hs),.vs(vs),.rgb(rgb),.active_packet(active_packet),.out_rgb(dut_rgb),.out_de(dut_de),.out_hs(dut_hs),.out_vs(dut_vs));
 reg [31:0] font[0:4095];initial $readmemh("plate_font.mem",font);
 integer cycles=0,reset_checks=0,id,slot,yy,xx,j,n;
 reg [31:0] random_state=32'h83a51c27;
 task step;
  integer tx,ty,g,s;reg [23:0] expected;reg [26:0] control;
  begin
   expected=rgb;
   if(de && x>=16 && x<272 && y>=656 && y<704) begin
    expected=24'h123b78;tx=x-32;ty=y-664;
    if(tx>=0 && tx<224 && ty>=0 && ty<32) begin
     s=tx/32;g=68;
     if(active_packet[`PD_BITS]) g=(active_packet >> (`PD_IDS_LSB+7*s)) & 127;
     else if(s>=2 && s<=4) g=65+s-2;
     if(g>68) g=68;
     if(font[g*32+ty][31-(tx%32)]) expected=24'hffffff;
    end
   end
   control={expected,de,hs,vs};
   @(posedge clk);#1;
   if({ref_rgb,ref_de,ref_hs,ref_vs} !== control || {dut_rgb,dut_de,dut_hs,dut_vs} !== control)
    $fatal(1,"Mismatch cycle=%0d x=%0d y=%0d ref=%h dut=%h expected=%h",cycles,x,y,{ref_rgb,ref_de,ref_hs,ref_vs},{dut_rgb,dut_de,dut_hs,dut_vs},control);
   cycles=cycles+1;
   @(negedge clk);
  end
 endtask
 task reset_between_edges;
  begin
   #2;rst_n=0;#1;
   if({ref_rgb,ref_de,ref_hs,ref_vs} !== 27'd0 || {dut_rgb,dut_de,dut_hs,dut_vs} !== 27'd0) $fatal(1,"Async reset mismatch");
   reset_checks=reset_checks+1;
   @(posedge clk);#1;
   if({ref_rgb,ref_de,ref_hs,ref_vs} !== 27'd0 || {dut_rgb,dut_de,dut_hs,dut_vs} !== 27'd0) $fatal(1,"Held reset mismatch");
   reset_checks=reset_checks+1;
   #1;rst_n=1;@(negedge clk);
  end
 endtask
 task randomize_input;
  begin
   random_state={random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]};
   x=random_state[10:0];y=random_state[21:11];de=random_state[22];hs=random_state[23];vs=random_state[24];rgb=random_state[23:0];
   active_packet[`PD_BITS]=random_state[25];
   for(j=0;j<7;j=j+1) active_packet[`PD_IDS_LSB+7*j +:7]=(random_state >> (j*3)) & 127;
  end
 endtask
 initial begin
  @(negedge clk);reset_between_edges();
  // All input IDs in every slot; other slots carry distinct IDs.
  active_packet[`PD_BITS]=1;de=1;
  for(id=0;id<128;id=id+1) begin
   for(slot=0;slot<7;slot=slot+1) begin
    for(j=0;j<7;j=j+1) active_packet[`PD_IDS_LSB+7*j +:7]=(id+j*19)&127;
    active_packet[`PD_IDS_LSB+7*slot +:7]=id;
    for(yy=0;yy<32;yy=yy+1) for(xx=0;xx<32;xx=xx+1) begin
     x=32+32*slot+xx;y=664+yy;rgb=(id<<16)|(yy<<8)|xx;hs=xx[0];vs=yy[0];step();
    end
   end
   if(id%16==0) reset_between_edges();
  end
  // Invalid packet ignores IDs and renders the three original status glyphs.
  active_packet={`PD_BITS+1{1'b1}};active_packet[`PD_BITS]=0;
  for(yy=0;yy<32;yy=yy+1) for(xx=0;xx<224;xx=xx+1) begin x=32+xx;y=664+yy;step();end
  // Every pixel of the panel plus its exterior border, with DE toggled.
  for(yy=654;yy<=705;yy=yy+1) for(xx=14;xx<=273;xx=xx+1) begin
   x=xx;y=yy;de=0;step();de=1;step();
  end
  // Deterministic jumps across the full 11-bit coordinate domain, changing packets each cycle.
  for(n=0;n<20000;n=n+1) begin randomize_input();step();if(n%1000==0) reset_between_edges();end
  // Jumps targeted at the seven text slots exercise changing bank/blank selection each clock.
  for(n=0;n<10000;n=n+1) begin
   randomize_input();x=32+(random_state%224);y=664+random_state[4:0];de=n[0];step();
  end
  $display("PASS cycles=%0d reset_checks=%0d all_ids=128 slots=7 glyph_pixels=917504 status_pixels=7168 border_checks=27040 random_jumps=30000",cycles,reset_checks);
  $finish;
 end
endmodule
