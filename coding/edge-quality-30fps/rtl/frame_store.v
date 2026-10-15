module frame_store #(parameter W=1280,H=720,BURST=128,FIFO_DEPTH=512,PLAY_PERIOD=3333333,ENABLE_CANNY=0,ENABLE_SHAPE=0)(
 input rst_n,core_clk,pixel_clk,display_clk,enabled,
 input [63:0] capture_pixels,input capture_valid,capture_sof,capture_eof,
 input [31:0] capture_frame_id,
 input recognition_enable,input [15:0] config_value,input [31:0] config_epoch,
 output [63:0] algorithm_pixels,output algorithm_valid,input algorithm_ready,
 output algorithm_sof,algorithm_eol,algorithm_eof,
 output [31:0] algorithm_frame_id,algorithm_epoch,output [15:0] algorithm_config,
 input [63:0] result_pixels,input result_valid,result_sof,result_eof,
 output result_ready,
 input [3:0] command,input command_toggle,output command_ack,
 input reference_mode,input display_period,
 output [127:0] display_pixels,output display_valid,input display_ready,
 // Passed through the HDMI FIFO as frame metadata, then acknowledged at SOF.
 output reg [293:0] display_descriptor,
 input shown_toggle,input [1:0] shown_slot,
 output [319:0] status,
 output [159:0] traffic,
 output [223:0] algorithm_status,
 output [31:0] capture_overflow,result_overflow,
 output [31:0] awaddr,araddr,output [7:0] awlen,arlen,
 output awvalid,wvalid,wlast,bready,arvalid,rready,
 output [127:0] wdata,output [15:0] wstrb,
 input awready,wready,bvalid,arready,rvalid,rlast,
 input [1:0] bresp,rresp,input [127:0] rdata
);
 localparam WORDS=W*H/4;
 wire [161:0] capture_data,result_data;
 wire [10:0] capture_count,result_count;
 wire capture_empty,result_empty,capture_take,result_take;
 frame_pair_fifo #(.DEPTH(FIFO_DEPTH),.RGB_ONLY(1)) capture_fifo(.rst_n(rst_n),.in_clk(pixel_clk),.out_clk(core_clk),
  .valid(capture_valid),.sof(capture_sof),.eof(capture_eof),.pixels(capture_pixels),.frame_id(capture_frame_id),
  .ready(),.overflow(capture_overflow),.data(capture_data),.empty(capture_empty),.count(capture_count),.take(capture_take));
 frame_pair_fifo #(.DEPTH(FIFO_DEPTH)) result_fifo(.rst_n(rst_n),.in_clk(pixel_clk),.out_clk(core_clk),
  .valid(result_valid && result_ready),.sof(result_sof),.eof(result_eof),.pixels(result_pixels),.frame_id(32'd0),
  .ready(result_ready),.overflow(result_overflow),.data(result_data),.empty(result_empty),.count(result_count),.take(result_take));
 wire [48:0] core_config;
 frame_mailbox #(.WIDTH(49)) config_cdc(.rst_n(rst_n),.src_clk(pixel_clk),.dst_clk(core_clk),
  .src_data({recognition_enable,config_epoch,config_value}),.delivered(),.dst_data(core_config));
 wire capture_start,capture_accept,capture_done,capture_ok;
 wire [31:0] incoming_id;
 wire [5:0] capture_slot,job_source;
 wire [1:0] job_result;
 wire job_start,job_done,job_ok;
 wire [31:0] job_id,job_epoch;
 wire local_done,local_ok,h_done,h_ok,h_busy;
 wire [31:0] h_cycles,h_enqueued,h_highwater,h_misses;
 wire h_req,h_write,h_ready,h_wvalid,h_wready,h_rvalid,h_transfer_done,h_error;
 wire [31:0] h_address;wire [7:0] h_len;wire [127:0] h_wdata;
 reg held_recognition;
 wire edge_done,edge_ok,s_done,s_ok,s_busy,s_overflow;
 wire [2:0] s_count;wire [175:0] s_boxes;wire [7:0] s_kinds;
 wire s_req,s_write,s_copy,s_response,s_error;wire [31:0] s_address;wire [127:0] s_data,s_result;
 reg [188:0] result_shape[0:2];
 reg [15:0] held_config;
 reg [15:0] result_config[0:2];
 reg [31:0] completed,last_completed_id,last_completed_epoch,job_cycles,last_job_cycles;
 reg [31:0] last_enqueued,last_highwater,last_misses;
 always @(posedge core_clk) begin
  if(!rst_n) begin
   last_enqueued<=0;last_highwater<=0;last_misses<=0;held_config<=0;completed<=0;last_completed_id<=0;last_completed_epoch<=0;job_cycles<=0;last_job_cycles<=0;
   held_recognition<=0;result_shape[0]<=0;result_shape[1]<=0;result_shape[2]<=0;
   result_config[0]<=0;result_config[1]<=0;result_config[2]<=0;
  end else begin
   if(job_start) begin held_config<=core_config[15:0];held_recognition<=ENABLE_SHAPE && core_config[48];job_cycles<=0;end
   else job_cycles<=job_cycles+1'b1;
   if(job_done && job_ok) begin
    completed<=completed+1'b1;last_completed_id<=job_id;last_completed_epoch<=job_epoch;last_job_cycles<=job_cycles;
    last_enqueued<=held_config[13]?h_enqueued:0;last_highwater<=held_config[13]?h_highwater:0;last_misses<=held_config[13]?h_misses:0;
    result_config[job_result]<=held_config;
    result_shape[job_result]<=held_recognition ? {1'b1,s_overflow,s_count,s_kinds,s_boxes} : 189'd0;
   end
  end
 end
 assign edge_done=local_done && (!ENABLE_CANNY || !held_config[13] || !local_ok) || h_done;
 assign edge_ok=h_done ? h_ok : local_ok;
 assign job_done=(edge_done && (!held_recognition || !edge_ok)) || s_done;
 assign job_ok=s_done ? s_ok : edge_ok;
 generate if(ENABLE_SHAPE) begin: shapes
  shape_recognizer #(.W(W),.H(H),.QUEUE_BASE(32'h08700000),.STATE_BASE(32'h08b00000),.VISIT_BASE(32'h08c00000)) engine(.clk(core_clk),.rst_n(rst_n),.start(edge_done && edge_ok && held_recognition),.slot(job_result),
   .busy(s_busy),.done(s_done),.ok(s_ok),.count(s_count),.overflow(s_overflow),.boxes(s_boxes),.kinds(s_kinds),.candidates(),.cycles(),
   .mem_valid(s_req),.mem_write(s_write),.mem_copy(s_copy),.mem_address(s_address),.mem_data(s_data),
   .mem_done(s_response),.mem_error(s_error),.mem_result(s_result));
 end else begin
  assign s_req=0;assign s_write=0;assign s_copy=0;assign s_address=0;assign s_data=0;
  assign s_done=0;assign s_ok=0;assign s_busy=0;assign s_count=0;assign s_overflow=0;assign s_boxes=0;assign s_kinds=0;
 end endgenerate
 generate if(ENABLE_CANNY) begin: canny
  canny_hysteresis #(.W(W),.H(H),.SCAN_BURST(BURST),.QUEUE_BASE(32'h08700000),.STATE_BASE(32'h08b00000),.VISIT_BASE(32'h08c00000)) engine(
   .clk(core_clk),.rst_n(rst_n),.start(local_done && local_ok && held_config[13]),
   .slot(job_result),
   .ext_valid(s_req),.ext_write(s_write),.ext_copy(s_copy),.ext_address(s_address),.ext_data(s_data),
   .ext_done(s_response),.ext_error(s_error),.ext_result(s_result),
   .busy(h_busy),.done(h_done),.ok(h_ok),.cycles(h_cycles),.enqueued(h_enqueued),.highwater(h_highwater),.cache_misses(h_misses),
   .req_valid(h_req),.req_write(h_write),.req_address(h_address),.req_len(h_len),.req_ready(h_ready),
   .write_data(h_wdata),.write_valid(h_wvalid),.write_ready(h_wready),
   .read_valid(h_rvalid),.read_data(rdata),.transfer_done(h_transfer_done),.transfer_error(h_error));
 end else begin
  assign h_busy=0;assign h_done=0;assign h_ok=0;assign h_cycles=0;assign h_enqueued=0;assign h_highwater=0;assign h_misses=0;
  assign h_req=0;assign h_write=0;assign h_address=0;assign h_len=0;assign h_wdata=0;assign h_wvalid=0;
 end endgenerate
 wire [223:0] core_algorithm_status={last_misses,last_highwater,last_enqueued,last_job_cycles,last_completed_epoch,last_completed_id,completed};
 frame_mailbox #(.WIDTH(224),.ALWAYS_SEND(1)) algorithm_status_cdc(.rst_n(rst_n),.src_clk(core_clk),.dst_clk(pixel_clk),
  .src_data(core_algorithm_status),.delivered(),.dst_data(algorithm_status));

 wire read_start,read_end,read_valid,display_reset;
 wire [1:0] read_slot;
 wire display_reference_valid;
 wire [5:0] display_reference_slot;
 wire [31:0] display_id,display_epoch,display_reference_id;
 wire [2:0] mode;wire [5:0] recorded;wire [4:0] playback_index;
 wire reference_valid;wire [5:0] reference_slot;
 wire [31:0] reference_id,shown_id,shown_epoch,ignored_frames,skipped_frames,failed_frames,generation,bus_errors;
 wire [159:0] core_traffic;
 wire [3:0] command_error;
 reg command_ack_core;
 (* async_reg="true" *) reg [1:0] command_sync,shown_sync;
 reg shown_ack;
 wire command_valid=command_sync[1]!=command_ack_core && read_start;
 wire shown_valid=shown_sync[1]!=shown_ack;
 always @(posedge core_clk) begin
  if(!rst_n) begin command_sync<=0;command_ack_core<=0;shown_sync<=0;shown_ack<=0;end
  else begin
   command_sync<={command_sync[0],command_toggle};shown_sync<={shown_sync[0],shown_toggle};
   if(command_valid) command_ack_core<=command_sync[1];
   if(shown_valid) shown_ack<=shown_sync[1];
  end
 end
 // The sender keeps each command and shown slot stable across its toggle.
 reg [1:0] ack_sync;
 always @(posedge pixel_clk) if(!rst_n) ack_sync<=0;else ack_sync<={ack_sync[0],command_ack_core};
 assign command_ack=ack_sync[1];
 frame_store_control #(.PLAY_PERIOD(PLAY_PERIOD)) control(.clk(core_clk),.rst_n(rst_n),.enabled(enabled),
  .command_valid(command_valid),.command(command),.command_ack(),.config_epoch(core_config[47:16]),
  .capture_start(capture_start),.capture_id(incoming_id),.capture_accept(capture_accept),.capture_slot(capture_slot),
  .capture_done(capture_done),.capture_ok(capture_ok),.job_start(job_start),.job_source(job_source),
  .job_result(job_result),.job_id(job_id),.job_epoch(job_epoch),.job_done(job_done),.job_ok(job_ok),
  .display_start(read_start),.display_end(read_end),.display_valid(read_valid),.display_slot(read_slot),
  .display_reference_valid(display_reference_valid),.display_reference_slot(display_reference_slot),
  .display_id(display_id),.display_epoch(display_epoch),.display_reference_id(display_reference_id),
  .shown_valid(shown_valid),.shown_slot(shown_slot),.mode(mode),.recorded(recorded),.playback_index(playback_index),
  .reference_valid(reference_valid),.reference_slot(reference_slot),.reference_id(reference_id),
  .shown_id(shown_id),.shown_epoch(shown_epoch),.ignored_frames(ignored_frames),.skipped_frames(skipped_frames),
  .failed_frames(failed_frames),.generation(generation),.command_error(command_error));
 reg job_toggle;
 reg [80:0] job_message;
 wire [80:0] pixel_job;
 wire job_delivered;
 always @(posedge core_clk) begin
  if(!rst_n) begin job_toggle<=0;job_message<=0;end
  else if(job_start) begin
   job_toggle<=!job_toggle;job_message<={!job_toggle,job_id,job_epoch,core_config[15:0]};
  end
 end
 frame_mailbox #(.WIDTH(81)) job_cdc(.rst_n(rst_n),.src_clk(core_clk),.dst_clk(pixel_clk),
  .src_data(job_message),.delivered(job_delivered),.dst_data(pixel_job));
 assign algorithm_frame_id=pixel_job[79:48];
 assign algorithm_epoch=pixel_job[47:16];
 assign algorithm_config=pixel_job[15:0];
 wire [127:0] algorithm_word,algorithm_write_data;
 wire algorithm_empty,algorithm_write,algorithm_take;
 wire [10:0] algorithm_used;
 reg algorithm_half;
 reg [19:0] algorithm_pair;
 reg [10:0] algorithm_x;
 assign algorithm_valid=!algorithm_empty;
 assign algorithm_pixels=algorithm_half ? algorithm_word[63:0] : algorithm_word[127:64];
 assign algorithm_take=algorithm_valid && algorithm_ready && algorithm_half;
 assign algorithm_sof=algorithm_pair==0;
 assign algorithm_eof=algorithm_pair==W*H/2-1;
 assign algorithm_eol=algorithm_x==W/2-1;
 always @(posedge pixel_clk) begin
  if(!rst_n) begin algorithm_half<=0;algorithm_pair<=0;algorithm_x<=0;end
  else if(algorithm_valid && algorithm_ready) begin
   algorithm_half<=!algorithm_half;
   algorithm_pair<=algorithm_eof ? 0 : algorithm_pair+1'b1;
   algorithm_x<=algorithm_eol ? 0 : algorithm_x+1'b1;
  end
 end
 DC_FIFO #(.FIFO_MODE("ShowAhead"),.DATA_WIDTH(128),.FIFO_DEPTH(FIFO_DEPTH)) algorithm_fifo(
  .Reset(!rst_n),.WrClk(core_clk),.WrEn(algorithm_write),.WrData(algorithm_write_data),
  .WrFull(),.WrDNum(algorithm_used),.RdClk(pixel_clk),.RdEn(algorithm_take),
  .RdData(algorithm_word),.RdEmpty(algorithm_empty),.RdDNum(),.DataVal());
 wire [127:0] display_write_data;
 wire display_write,display_empty;
 wire display_reference_active;
 wire [10:0] display_used;
 assign display_valid=!display_empty && !display_period;
 DC_FIFO #(.FIFO_MODE("ShowAhead"),.DATA_WIDTH(128),.FIFO_DEPTH(FIFO_DEPTH)) display_fifo(
  .Reset(!rst_n || display_reset),.WrClk(core_clk),.WrEn(display_write),.WrData(display_write_data),
  .WrFull(),.WrDNum(display_used),.RdClk(display_clk),.RdEn(display_valid && display_ready),
  .RdData(display_pixels),.RdEmpty(display_empty),.RdDNum(),.DataVal());
 reg [293:0] descriptor;
 reg descriptor_toggle;
 (* async_reg="true" *) reg [1:0] descriptor_sync;
 reg descriptor_ack;
 reg reset_last;
 reg [1:0] reference_sync;
 always @(posedge core_clk) begin
  if(!rst_n) begin descriptor<=0;descriptor_toggle<=0;reset_last<=1;reference_sync<=0;end
  else begin
   reset_last<=display_reset;reference_sync<={reference_sync[0],reference_mode};
   if(reset_last && !display_reset) begin
    descriptor_toggle<=!descriptor_toggle;
    descriptor<={result_shape[read_slot],result_config[read_slot][15:13],display_reference_active,mode,read_slot,
                 display_reference_id,display_epoch,display_id};
   end
  end
 end
 // Descriptor is held for an entire HDMI frame; synchronize its update toggle.
 always @(posedge display_clk) begin
  if(!rst_n) begin descriptor_sync<=0;descriptor_ack<=0;display_descriptor<=0;end
  else begin
   descriptor_sync<={descriptor_sync[0],descriptor_toggle};
   if(descriptor_sync[1]!=descriptor_ack) begin display_descriptor<=descriptor;descriptor_ack<=descriptor_sync[1];end
  end
 end
 frame_store_dma #(.WORDS(WORDS),.BURST(BURST),.FIFO_DEPTH(FIFO_DEPTH),.ENABLE_CANNY(ENABLE_CANNY)) dma(
  .clk(core_clk),.rst_n(rst_n),.enabled(enabled),
  .canny_req_valid(h_req),.canny_req_write(h_write),.canny_address(h_address),.canny_len(h_len),.canny_req_ready(h_ready),
  .canny_write_data(h_wdata),.canny_write_valid(h_wvalid),.canny_write_ready(h_wready),.canny_read_valid(h_rvalid),
  .canny_done(h_transfer_done),.canny_error(h_error),
  .capture_data(capture_data),.capture_count(capture_count),.capture_empty(capture_empty),.capture_take(capture_take),
  .result_data(result_data),.result_count(result_count),.result_empty(result_empty),.result_take(result_take),
  .capture_start(capture_start),.capture_id(incoming_id),.capture_accept(capture_accept),.capture_slot(capture_slot),
  .capture_done(capture_done),.capture_ok(capture_ok),.job_start(job_start),.job_canny(core_config[13]),.job_recognize(ENABLE_SHAPE && core_config[48]),.job_source(job_source),.job_result(job_result),
  .job_reader_ready(job_delivered),.job_done(local_done),.job_ok(local_ok),
  .algorithm_data(algorithm_write_data),.algorithm_write(algorithm_write),.algorithm_used(algorithm_used),
  .display_period(display_period),.reference_mode(reference_sync[1]),.display_start(read_start),.display_end(read_end),
  .display_reference_active(display_reference_active),
  .display_reset(display_reset),.display_valid(read_valid),.display_slot(read_slot),
  .display_config(result_config[read_slot]),.display_frame_id(display_id),
  .reference_valid(display_reference_valid),.reference_slot(display_reference_slot),
  .display_data(display_write_data),.display_write(display_write),.display_used(display_used),.bus_errors(bus_errors),.traffic(core_traffic),
  .awaddr(awaddr),.araddr(araddr),.awlen(awlen),.arlen(arlen),.awvalid(awvalid),.wvalid(wvalid),.wlast(wlast),
  .bready(bready),.arvalid(arvalid),.rready(rready),.wdata(wdata),.wstrb(wstrb),.awready(awready),.wready(wready),.bvalid(bvalid),
  .arready(arready),.rvalid(rvalid),.rlast(rlast),.bresp(bresp),.rresp(rresp),.rdata(rdata));
 wire [319:0] core_status={bus_errors,failed_frames,skipped_frames,ignored_frames,generation,
                         reference_id,shown_epoch,shown_id,32'd0,
                         13'd0,command_error,reference_valid,playback_index,recorded,mode};
 frame_mailbox #(.WIDTH(320),.ALWAYS_SEND(1)) status_cdc(.rst_n(rst_n),.src_clk(core_clk),.dst_clk(pixel_clk),
  .src_data(core_status),.delivered(),.dst_data(status));
 frame_mailbox #(.WIDTH(160),.ALWAYS_SEND(1)) traffic_cdc(.rst_n(rst_n),.src_clk(core_clk),.dst_clk(pixel_clk),
  .src_data(core_traffic),.delivered(),.dst_data(traffic));
endmodule
