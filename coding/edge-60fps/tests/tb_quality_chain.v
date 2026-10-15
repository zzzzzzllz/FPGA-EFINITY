`timescale 1ns/1ps
// Feed the real top-level gray/Sobel adapter from the optimized camera RTL.
module tb_quality_chain;
 tb_quality #(.W(1920),.H(1080),.BURST(1),.PHASE(0),
              .FRAME_CYCLES(1666667),.LINE_CYCLES(1449)) source();
 ti60f225_oob_top adapter(.i_mipi_rx_pclk(source.clk));
 initial begin
  force adapter.w_arstn=source.rst_n;
  force adapter.full_vs=source.ovs;
  force adapter.full_valid=source.ov;
  force adapter.full_rgb=source.rgb;
  force adapter.full_frames=source.frames;
 end
 integer count=0,k;
 reg [31:0] previous_frames=0;
 always @(negedge source.clk) if(source.rst_n) begin
  if(adapter.gray_valid && !adapter.sobel_ready)$fatal(1,"Sobel overrun");
  if(adapter.sobel_valid) begin
   if(adapter.sobel_sof!==(count%921600==0) ||
      adapter.sobel_eol!==(count%1280==1278) ||
      adapter.sobel_eof!==(count%921600==921598) ||
      adapter.sobel_frame_id!==count/921600+1)
    $fatal(1,"Sobel metadata mismatch count=%0d",count);
   for(k=0;k<2;k=k+1)
    if(adapter.sobel_rgbe[(1-k)*32+:24]!==source.expected[count+k][23:0])
     $fatal(1,"Sobel RGB mismatch count=%0d",count+k);
   count=count+2;
  end
  if(source.frames!=previous_frames) begin
   if(count!=source.frames*921600 || adapter.processed_frames!=source.frames)
    $fatal(1,"Sobel deadline/count mismatch: pixels=%0d processed=%0d",count,adapter.processed_frames);
   $display("CHAIN PASS: frame=%0d, all RGB pixels and metadata, zero Sobel overrun",source.frames);
   previous_frames=source.frames;
  end
 end
endmodule
