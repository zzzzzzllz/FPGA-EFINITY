`timescale 1ns/1ps
// Exercise the actual top-level adapter without simulating the DDR/CSI IP.
module tb_gray_frame;
 reg clk=0; always #10 clk=~clk;
 reg rst_n=0,vs=0,valid=0;
 reg [63:0] rgb=64'h00ff00000000ff00;
 reg [31:0] frames=0;
 reg enable=1;wire left_edge=enable && edges%640==639 && (edges%460800)/640>0 && (edges%460800)/640<719;
 wire right_edge=enable && edges%640==0 && (edges%460800)/640>0 && (edges%460800)/640<719;
 integer frame,pair,outputs=0,completed=0,edges=0;
 wire [23:0] stored_pairs;
 frame_info_det #(.I_VID_WIDTH(64),.AXI_DDR_WIDTH(128)) frame_check(
  .clk(clk),.rst_n(rst_n),.i_vs(dut.sobel_vs),.i_de(dut.sobel_valid),
  .i_data(dut.sobel_rgbe),.frame_pix_num_o(stored_pairs));
 ti60f225_oob_top dut(.i_mipi_rx_pclk(clk));
 initial begin
  force dut.median_active=enable;force dut.denoise_active=1'b0;force dut.median_epoch=32'd0;
  force dut.threshold_active=11'd32;
  force dut.threshold_epoch=32'd0;
  force dut.w_arstn=rst_n;
  force dut.full_vs=vs;
  force dut.full_valid=valid;
  force dut.full_rgb=rgb;
  force dut.full_frames=frames;
 end
 always @(negedge clk) if(rst_n && dut.gray_valid) begin
  if(dut.gray_rgby!==64'h4dff00009500ff00) $fatal(1,"RGBY mismatch");
  if(dut.gray_pipeline.out_sof !== (outputs%460800==0) ||
     dut.gray_pipeline.out_eol !== (outputs%640==639) ||
     dut.gray_eof !== (outputs%460800==460799))
   $fatal(1,"Frame metadata mismatch at pair %0d",outputs);
  if(dut.gray_frame_id !== outputs/460800+1) $fatal(1,"Frame ID mismatch");
  if(dut.gray_eof) completed=completed+1;
  outputs=outputs+1;
 end
 always @(negedge clk) if(rst_n) begin
  if(dut.gray_valid && !dut.median_ready) $fatal(1,"Sobel input overrun");
  if(dut.sobel_valid) begin
   if(dut.stored_pixels!=={left_edge,(edges%460800==1?(enable?7'd16:7'd0):7'(edges/460800+1)),24'hff0000,
                           right_edge,(edges%460800==0?7'd32:7'(edges/460800+1)),24'h00ff00})
    $fatal(1,"DDR packing pair=%0d value=%h flags=%h",edges,dut.stored_pixels,dut.sobel_flags);
   if(dut.sobel_rgbe!=={{8{left_edge}},24'hff0000,{8{right_edge}},24'h00ff00}) $fatal(1,"Sobel RGB/edge mismatch");
   if(dut.sobel_sof!==(edges%460800==0) || dut.sobel_eol!==(edges%640==639) ||
      dut.sobel_eof!==(edges%460800==460799) || dut.sobel_frame_id!==edges/460800+1)
    $fatal(1,"Sobel metadata mismatch %0d",edges);
   if(dut.sobel_vs) $fatal(1,"Sobel VS overlaps active pixels");
   edges=edges+1;
  end
 end
 initial begin
  repeat(4) @(posedge clk);
  #1; rst_n=1;
  for(frame=0;frame<4;frame=frame+1) begin
   enable=!(frame%2);
   // Alternate between low-active and high-active frame sync.
   @(posedge clk); #1; vs=!(frame%2); valid=0;
   repeat(5) @(posedge clk);
   #1;vs=frame%2;
   repeat(5) @(posedge clk);
   for(pair=0;pair<460800;pair=pair+1) begin
    #1;valid=1;
    @(posedge clk);
    if(pair%640==639) begin
     #1;valid=0;
     repeat(4) @(posedge clk);
    end
   end
   #1;valid=0;
   repeat(1320) @(posedge clk);
   #1;vs=!(frame%2);frames=frames+1;
   repeat(6) @(posedge clk);
   #1;
   if(dut.processed_frames!==frame+1 || dut.last_frame_id!==frame+1)
    $fatal(1,"Completed frame count/ID mismatch: frame %0d count %0d ID %0d",
           frame,dut.processed_frames,dut.last_frame_id);
   if(stored_pairs!==460800) $fatal(1,"DDR frame length mismatch %0d",stored_pairs);
  end
  if(completed!=4 || outputs!=1843200 || edges!=1843200) $fatal(1,"Wrong total");
  $display("PASS: actual gray/Sobel top adapter, 4 full 720p frames, both VS polarities, line gaps, SOF/EOL/EOF, RGB preservation, completed IDs and DDR frame lengths");
  $finish;
 end
endmodule
