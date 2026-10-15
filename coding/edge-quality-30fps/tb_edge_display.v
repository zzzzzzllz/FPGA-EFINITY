`timescale 1ns/1ps
module tb_edge_display;
 reg clk=0; always #7 clk=~clk;
 reg rst_n=0,vs=0,hs=0,de=0,gray=0,edge_mode=1,overlay=0;
 reg [31:0] pixel=0;
 integer mode,i,sum,frame,pair,s0,s1;
 reg [1:0] flags=0;reg [63:0] source=0;reg [15:0] filtered=0;
 reg sv=0,ss=0;reg [63:0] stored_expected;reg [23:0] rgb0,rgb1;
 reg [23:0] expected;
 ti60f225_oob_top dut(.i_mipi_rx_pclk(clk));
 initial begin
  force dut.hdmi_tx_slow_clk=clk;
  force dut.vid_rst_n=rst_n;
  force dut.w_arstn=rst_n;
  force dut.display_rgb=pixel;
  force dut.ch0_vs=vs; force dut.ch0_hs=hs; force dut.ch0_de=de;
  force dut.overlay_sel=overlay;force dut.gray_sel=gray; force dut.edge_sel=edge_mode; force dut.gamma_sel=1'b0;
  repeat(4) @(negedge clk); rst_n=1;
  force dut.sobel_flags=flags;force dut.sobel_frame_id=32'd57;
  force dut.sobel_frame_threshold=11'd1345;force dut.sobel_rgbe=source;
  force dut.sobel_luma=filtered;force dut.sobel_valid=sv;force dut.sobel_sof=ss;
  for(frame=0;frame<4;frame=frame+1) begin
   flags=frame;
   for(pair=0;pair<8;pair=pair+1) begin
    @(negedge clk);sv=1;ss=pair==0;
    source={8'(pair%2?255:0),24'(pair*123456+frame*917),8'(pair%2?0:255),24'(pair*765432+frame*391)};
    filtered={8'(pair*17+frame*23),8'(pair*37+frame*19)};
    s0=(77*source[55:48]+150*source[47:40]+29*source[39:32]+128)>>8;
    s1=(77*source[23:16]+150*source[15:8]+29*source[7:0]+128)>>8;
    rgb0=flags[1]?{8'(s0),filtered[15:8],8'd0}:source[55:32];
    rgb1=flags[1]?{8'(s1),filtered[7:0],8'd0}:source[23:0];
    stored_expected={source[63],(pair==1?{1'b0,flags,4'd10}:7'd57),rgb0,
                     source[31],(pair==0?7'd65:7'd57),rgb1};
    #1;if(dut.stored_pixels!==stored_expected) $fatal(1,"M06 DDR payload/metadata packing");
   end
   @(negedge clk);sv=0;ss=0;repeat(3) @(negedge clk);
  end
  $display("PASS storage: all filter/view flags, exact original luma, median payload and frame header packing");
  for(mode=0;mode<4;mode=mode+1) begin
   @(negedge clk); overlay=mode==3;gray=mode==1;edge_mode=mode==2;vs=0;
   repeat(5) @(negedge clk);
   vs=1; repeat(3) @(negedge clk); vs=0;
   if(dut.display_overlay!==(mode==3) || dut.display_edge!==(mode==2) || dut.display_gray!==(mode==1)) $fatal(1,"view commit mismatch");
   for(i=0;i<4096;i=i+1) begin
    @(negedge clk);
    pixel={i[0]?8'hff:8'h00,8'(i*71),8'(i*137),8'(i*53)};
    hs=i%13==0;de=i%7!=0;
    sum=(77*pixel[23:16]+150*pixel[15:8]+29*pixel[7:0]+128)>>8;
    expected=pixel[23:0];
    @(posedge clk); #1;
    if({dut.hdmi_tx_rdata,dut.hdmi_tx_gdata,dut.hdmi_tx_bdata}!==expected ||
       dut.hdmi_tx_de!==de || dut.hdmi_tx_hs!==hs || dut.hdmi_tx_vs!==vs)
     $fatal(1,"display alignment mismatch mode=%0d pixel=%0d",mode,i);
   end
  end
  $display("PASS display: 16384 pixels, composed RGB preserved in every view and aligned HDMI timing");
  $finish;
 end
endmodule
