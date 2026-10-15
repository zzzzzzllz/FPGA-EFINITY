`timescale 1ns/1ps
module tb_canny_store;
 reg recognition_enable=0;
`ifdef FULL_SMOKE
 localparam W=1280,H=720,WORDS=W*H/4;
`elsif MEDIUM_SMOKE
 localparam W=128,H=256,WORDS=W*H/4;
`else
 localparam W=32,H=24,WORDS=W*H/4;
`endif
 reg core_clk=0,pixel_clk=0,display_clk=0;
 always #5 core_clk=~core_clk;always #10 pixel_clk=~pixel_clk;always #7 display_clk=~display_clk;
 reg rst_n=0,enabled=1;
 reg [63:0] capture_pixels;reg capture_valid=0,capture_sof=0,capture_eof=0;
 reg [31:0] capture_frame_id=901,config_epoch=19;reg [15:0] config_value;
 wire [63:0] algorithm_pixels;wire algorithm_valid;wire algorithm_ready;
 wire algorithm_sof,algorithm_eol,algorithm_eof;
 wire [31:0] algorithm_frame_id,algorithm_epoch;wire [15:0] algorithm_config;
 wire [63:0] result_pixels;wire result_valid,result_sof,result_eof,result_ready;
 reg [3:0] command=0;reg command_toggle=0;wire command_ack;
 reg reference_mode=0,display_period=0;
 wire [127:0] display_pixels;wire display_valid;reg display_ready=1;
 wire [293:0] display_descriptor;
 reg shown_toggle=0;reg [1:0] shown_slot=0;
 wire [319:0] status;wire [31:0] capture_overflow,result_overflow;
 wire [159:0] traffic;wire [223:0] algorithm_status;
 wire [31:0] awaddr,araddr;wire [7:0] awlen,arlen;
 wire awvalid,wvalid,wlast,bready,arvalid,rready;wire [127:0] wdata;wire [15:0] wstrb;integer byte_lane;
 reg awready=0,wready=0,bvalid=0,arready=0,rvalid=0,rlast=0;
 reg [1:0] bresp=0,rresp=0;reg [127:0] rdata=0;
 integer state_error=0,reuse_slots=0,reference_test=0;reg state_error_sent=0;
 reg [15:0] initial_config,shown_config;
 reg [31:0] verified_epoch=0;
 frame_store #(.W(W),.H(H),.BURST(W>=128 ? 128 : 16),.PLAY_PERIOD(4200),.ENABLE_CANNY(1),.ENABLE_SHAPE(1)) dut(.*);

 reg [31:0] source[0:W*H-1],expected[0:W*H-1];
 reg [1023:0] input_file,final_file;
 reg [1023:0] shapes_file;reg [188:0] expected_shapes[0:0];
 wire result_eol;wire [31:0] result_id,result_epoch;wire [15:0] result_config;
 edge_algorithm_pair #(.W(W),.H(H)) algorithm(.clk(pixel_clk),.rst_n(rst_n),.in_config(algorithm_config),
  .in_pixels(algorithm_pixels),.in_valid(algorithm_valid),.in_ready(algorithm_ready),
  .in_sof(algorithm_sof),.in_eol(algorithm_eol),.in_eof(algorithm_eof),.in_id(algorithm_frame_id),.in_epoch(algorithm_epoch),
  .out_pixels(result_pixels),.out_valid(result_valid),.out_ready(result_ready),.out_sof(result_sof),.out_eol(result_eol),.out_eof(result_eof),
  .out_id(result_id),.out_epoch(result_epoch),.out_config(result_config));
 localparam STATE_WORDS=(W*H+16383)/16384*256;
 localparam RAW_WORDS=WORDS*3/4,RESULT_INDEX=41*RAW_WORDS,QUEUE_INDEX=RESULT_INDEX+3*WORDS,STATE_INDEX=QUEUE_INDEX+WORDS;
 reg [127:0] memory[0:STATE_INDEX+5*STATE_WORDS-1];
 integer cycles=0,write_index,read_index,read_remaining=0;
 function integer address_index(input [31:0] address);
  begin
   if(address>=32'h08b00000) begin
    if((address-32'h08b00000)/262144>4 || address[17:4]>=STATE_WORDS) $fatal(1,"state plane address range %h",address);
    address_index=STATE_INDEX+((address-32'h08b00000)/262144)*STATE_WORDS+address[17:4];
   end else if(address>=32'h08700000) begin
    if((address-32'h08700000)/16>=WORDS) $fatal(1,"queue address range %h",address);
    address_index=QUEUE_INDEX+(address-32'h08700000)/16;
   end else if(address>=32'h07b00000) begin
    if(((address-32'h07b00000)%4194304)/16>=WORDS) $fatal(1,"result address range %h",address);
    address_index=RESULT_INDEX+((address-32'h07b00000)/4194304)*WORDS+((address-32'h07b00000)%4194304)/16;
   end else begin
    if((address%3145728)/16>=RAW_WORDS) $fatal(1,"raw RGB24 address range %h",address);
    address_index=(address/3145728)*RAW_WORDS+(address%3145728)/16;
   end
  end
 endfunction
 always @(posedge core_clk) begin
  if(awvalid && awready && ({1'b0,awaddr[11:0]}+({5'd0,awlen}+1)*16)>4096) $fatal(1,"AXI write crosses 4 KiB");
  if(arvalid && arready && ({1'b0,araddr[11:0]}+({5'd0,arlen}+1)*16)>4096) $fatal(1,"AXI read crosses 4 KiB");
  cycles<=cycles+1;awready<=cycles%3!=0;wready<=cycles%7!=0;arready<=read_remaining==0 && !rvalid && cycles%5!=0;
`ifdef FULL_SMOKE
  if(cycles%250000==0) $display("store progress cycles=%0d sent=%0d local=%b canny=%0d shape=%0d",cycles,sent,dut.local_done,dut.canny.engine.state,dut.shapes.engine.state);
`endif
  if(awvalid && awready) write_index=address_index(awaddr);
  if(wvalid && wready) begin
   for(byte_lane=0;byte_lane<16;byte_lane=byte_lane+1) if(wstrb[byte_lane]) memory[write_index][byte_lane*8 +:8]=wdata[byte_lane*8 +:8];
   write_index=write_index+1;
   if(wlast) begin
    bvalid<=1;bresp<=0;
    if(state_error!=0 && dut.dma.writer==3 && !state_error_sent) begin bresp<=2;state_error_sent<=1;end
   end
  end
  if(bvalid && bready) bvalid<=0;
  if(arvalid && arready) begin read_index=address_index(araddr);read_remaining=arlen+1;end
  if(rvalid && rready) begin rvalid<=0;read_remaining=read_remaining-1;read_index=read_index+1;end
  if(!rvalid && read_remaining!=0 && cycles%4!=0) begin
   rvalid<=1;rdata<=memory[read_index];rlast<=read_remaining==1;
  end
  if(state_error!=0 && dut.failed_frames!=0) begin
   if(!state_error_sent || dut.completed!=0 || dut.h_busy || dut.read_valid) $fatal(1,"state DDR failure published a result");
   $display("PASS compact-state DDR write failure aborts before hysteresis/publication");$finish;
  end
  if(cycles>W*H*500) $fatal(1,"timeout localdone=%b hstate=%d head=%d tail=%d",dut.local_done,dut.canny.engine.state,dut.canny.engine.head,dut.canny.engine.tail);
 end
 integer sent,received=0,lane;
 reg [31:0] wanted;
 integer gray_sum;
 always @(posedge display_clk) begin
  if(display_period) received=0;
  else if(rst_n && display_valid && display_ready) begin
   if(received==0) begin shown_slot<=display_descriptor[97:96];shown_toggle<=!shown_toggle;end
   if(dut.h_busy && display_descriptor[97:96]==dut.job_result) $fatal(1,"published unfinished hysteresis");
   if(dut.s_busy && display_descriptor[97:96]==dut.job_result) $fatal(1,"published unfinished recognition");
   if(display_descriptor[293]!==recognition_enable) $fatal(1,"recognition descriptor mismatch");
   if(recognition_enable && display_descriptor[293:105]!==expected_shapes[0])
    $fatal(1,"recognition boxes/classes mismatch got=%h expected=%h",display_descriptor[293:105],expected_shapes[0]);
   shown_config=reuse_slots!=0 && display_descriptor[63:32]==20 ? (initial_config&16'hf800)|16'd2040 : initial_config;
   if(display_descriptor[31:0]!=901 || display_descriptor[63:32]<19 ||
      display_descriptor[63:32]>(reuse_slots!=0 ? 21 : 19) || display_descriptor[104:102]!=shown_config[15:13])
    $fatal(1,"display descriptor mismatch %h",display_descriptor);
   for(lane=0;lane<4;lane=lane+1) begin
    wanted=expected[received+lane];wanted[30:24]=7'd5;
    if(reuse_slots!=0 && display_descriptor[63:32]==20) wanted[31]=0;
    if(received+lane==1) wanted[30:24]=shown_config[6:0];
    if(received+lane==2) wanted[30:24]={1'b0,shown_config[12:11],shown_config[10:7]};
    if(display_descriptor[101]) begin
     gray_sum=(77*wanted[23:16]+150*wanted[15:8]+29*wanted[7:0]+128)>>8;
     wanted[31]=0;wanted[23:0]={source[received+lane][31:24],8'(gray_sum),8'd0};
     if(received+lane==2) wanted[29]=1;
    end
    if(display_pixels[(3-lane)*32 +:32]!==wanted)
     $fatal(1,"store pixel %0d got=%h expected=%h",received+lane,display_pixels[(3-lane)*32 +:32],wanted);
   end
   received=received+4;
   if(received==W*H) begin
    verified_epoch<=display_descriptor[63:32];
    if(status[319:256]!=0 || capture_overflow!=0 || result_overflow!=0 || (reuse_slots==0 && algorithm_status[31:0]!=1))
     $fatal(1,"health status=%h algorithm_status=%h",status,algorithm_status);
    if(reuse_slots!=0 && display_descriptor[63:32]==21) begin
     if(algorithm_status[31:0]!=3) $fatal(1,"reprocess completion count");
     $display("PASS frozen slot reuse: old RGB/edges stay coherent while new epochs 20/21 are processed");$finish;
    end
    if(reference_test!=0 && display_descriptor[101]) begin
     if(display_descriptor[95:64]!=901) $fatal(1,"reference frame ID mismatch");
     $display("PASS Canny reference: coherent grayscale and metadata without edge-state reads");$finish;
    end
    if(reuse_slots==0 && reference_test==0) begin
     $display("PASS Canny store %0dx%0d config=%h complete_job_cycles=%0d queue=%0d",W,H,config_value,algorithm_status[127:96],algorithm_status[159:128]);$finish;
    end
   end
  end
 end
 initial begin
  wait(rst_n);
  forever begin
   @(negedge display_clk);display_period=1;
   repeat(100) @(negedge display_clk);display_period=0;
   repeat(W*H*2) @(negedge display_clk);
  end
 end
 initial begin
  if(!$value$plusargs("input=%s",input_file) || !$value$plusargs("expected=%s",final_file) ||
     !$value$plusargs("config=%d",config_value)) $fatal(1,"missing vectors");
  if($value$plusargs("state_error=%d",state_error)) begin end
  if($value$plusargs("reuse_slots=%d",reuse_slots)) begin end
  if($value$plusargs("reference_test=%d",reference_test)) begin end
  if($value$plusargs("recognition=%d",recognition_enable)) begin end
  if(recognition_enable) begin
   if(!$value$plusargs("shapes=%s",shapes_file)) $fatal(1,"missing expected recognition metadata");
   $readmemh(shapes_file,expected_shapes);
  end
  initial_config=config_value;
  $readmemh(input_file,source);$readmemh(final_file,expected);
  repeat(8) @(negedge pixel_clk);rst_n=1;
  repeat(100) @(negedge pixel_clk);
  for(sent=0;sent<W*H;sent=sent+2) begin
   capture_pixels={source[sent],source[sent+1]};capture_valid=1;capture_sof=sent==0;capture_eof=sent==W*H-2;
   @(negedge pixel_clk);capture_valid=0;
   if(sent%32==30) repeat(5) @(negedge pixel_clk);
  end
  if(reuse_slots!=0) begin
   wait(verified_epoch==19);
   @(negedge pixel_clk);command=2;command_toggle=1;
   wait(command_ack==1);
   @(negedge pixel_clk);config_value=(initial_config&16'hf800)|16'd2040;config_epoch=20;
   wait(verified_epoch==20);
   @(negedge pixel_clk);config_value=initial_config;config_epoch=21;
  end
  if(reference_test!=0) begin
   wait(verified_epoch==19);
   @(negedge pixel_clk);command=8;command_toggle=1;
   wait(command_ack==1);
   @(negedge pixel_clk);reference_mode=1;
  end
 end
endmodule
