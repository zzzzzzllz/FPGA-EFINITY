// Serial owner of an unpublished result slot. Packed state: 10 accepted, 01 weak.
// LIFO work queue keeps newly found weak edges local; mark before enqueue.
// Coordinates are {11'b0,y[9:0],x[10:0]}; each pixel enters at most once.
module canny_hysteresis #(
 parameter W=1280,H=720,SCAN_BURST=128,QUEUE_BASE=32'h0b000000,STATE_BASE=32'h0b400000,VISIT_BASE=32'h0b500000
)(
 input clk,rst_n,start,input [1:0] slot,
 // M10 uses this memory only between complete Canny jobs.
 input ext_valid,ext_write,ext_copy,input [31:0] ext_address,
 input [127:0] ext_data,output reg ext_done,ext_error,output [127:0] ext_result,
 output reg busy,done,ok,
 output reg [31:0] cycles,enqueued,highwater,cache_misses,
 output reg req_valid,req_write,output reg [31:0] req_address,output reg [7:0] req_len,
 input req_ready,output [127:0] write_data,output write_valid,input write_ready,
 input read_valid,input [127:0] read_data,input transfer_done,transfer_error
);
 localparam PIXELS=W*H,WORDS=PIXELS/4;
 localparam STATE_GROUP=SCAN_BURST;
 localparam IDLE=0,SEED_REQ=1,SEED_WAIT=2,SEED_LOAD=3,SEED_CHECK=4,SEED_NEXT=5,
  PUSH=6,QFLUSH_REQ=7,QFLUSH_WAIT=8,POP=9,QREAD_REQ=10,QREAD_WAIT=11,POP_LOAD=12,POP_USE=13,
  NEIGHBOR=14,CACHE_LOOK=15,CACHE_CHECK=16,CACHE_WB_REQ=17,CACHE_WB_WAIT=18,
  CACHE_RD_REQ=19,CACHE_RD_WAIT=20,MARK=21,NEXT_NEIGHBOR=22,
  FLUSH=23,FINISH=28,EXT_LOOK=30,EXT_CHECK=31,EXT_WRITE=32,
  COPY_READ=33,COPY_WAIT=34,COPY_WRITE=35,COPY_DONE=36;
 reg [5:0] state,return_state;
 reg [31:0] state_base;
 reg external_mode,external_write;
 reg [31:0] external_address,copy_offset;
 // The sole external caller holds request data until ext_done.
 assign ext_result=cache_q;
 reg failed;
 reg [19:0] tail,head;
 reg [31:0] push_coordinate,current_coordinate;
 reg [12:0] read_queue_block;
 reg queue_loaded;
 reg [17:0] scan_offset;
 reg [$clog2(STATE_GROUP)-1:0] scan_index;
 reg [10:0] scan_x;
 reg [9:0] scan_y;
 reg [3:0] seed_mask;
 wire [1:0] seed_lane=seed_mask[0] ? 0 : seed_mask[1] ? 1 : seed_mask[2] ? 2 : 3;
 reg [3:0] neighbor;
 reg [10:0] nx;
 reg [9:0] ny;
 reg [19:0] neighbor_pixel;
 wire [13:0] neighbor_word=neighbor_pixel[19:6];
 wire external_request=state==IDLE && ext_valid===1'b1 && !ext_copy;
 wire [31:0] cache_address=external_request ? ext_address : external_mode ? external_address : state_base+{14'd0,neighbor_word,4'd0};
 // Recognition alternates the run queue and three nearby image rows. Associative
 // lookup prevents those unrelated addresses from evicting the same direct slot.
 reg [1:0] external_line,replacement;
 wire [1:0] line_index=external_mode || external_request ? external_line : cache_address[13:12];
 reg [1:0] active_line,flush_line;
 reg [19:0] tags[0:3];
 reg [3:0] valid_lines,dirty_lines;
 // Lower 16 KiB: four 4 KiB image lines. Upper 16 KiB: the recognition
 // queue prefix, written before read by its sole caller. Larger queues keep
 // using DDR, so this does not cap component size or change traversal order.
 reg [127:0] cache[0:2047];
 wire local_queue=external_request && (ext_address>>14)==(QUEUE_BASE>>14);
 reg [31:0] queue0[0:31],queue1[0:31],queue2[0:31],queue3[0:31];
 reg [63:0] seed_fifo[0:STATE_GROUP/16-1];
 reg [127:0] cache_q,queue_q;
  reg [7:0] beat;
 reg transfer_active;
 reg write_source;
 reg [1:0] transfer_line;
 reg [127:0] updated_word;
 wire [19:0] occupancy=tail;
 wire [19:0] top_index=tail-1'b1;
 wire [10:0] cx=current_coordinate[10:0];
 wire [9:0] cy=current_coordinate[20:11];
 // Adjacent pixels already in this RAM word need no additional read cycles
 // when none is weak. Never combine across a row or a 64-pixel word boundary.
 wire skip_pair=cx<W-1 && neighbor_pixel[5:0]<=61 && !cache_q[(neighbor_pixel[5:0]+2)*2];
 wire skip_triple=skip_pair && !cache_q[(neighbor_pixel[5:0]+1)*2] && (neighbor==0 || neighbor==5);
 wire [3:0] following_neighbor=skip_triple ? neighbor+3 : skip_pair && neighbor==3 ? neighbor+2 : neighbor+1'b1;
 wire [3:0] lookup_neighbor=state==CACHE_CHECK ? following_neighbor : neighbor;
 wire neighbor_valid=(lookup_neighbor!=0 && lookup_neighbor!=3 && lookup_neighbor!=5 || cx!=0) &&
                     (lookup_neighbor!=2 && lookup_neighbor!=4 && lookup_neighbor!=7 || cx!=W-1) &&
                     (lookup_neighbor>2 || cy!=0) && (lookup_neighbor<5 || cy!=H-1);
 wire cache_hit=valid_lines[line_index] && tags[line_index]==cache_address[31:12];
 always @* begin
  external_line=replacement;
  for(integer way=3;way>=0;way=way-1) if(!valid_lines[way]) external_line=way;
  for(integer way=3;way>=0;way=way-1)
   if(valid_lines[way] && tags[way]==cache_address[31:12]) external_line=way;
 end
 wire cache_weak=cache_q[neighbor_pixel[5:0]*2];
 wire next_hit_read=state==CACHE_CHECK && cache_hit && !cache_weak && following_neighbor<8 && neighbor_valid;
 always @* begin
  nx=cx;ny=cy;
  case(lookup_neighbor)
   0:begin nx=cx-1'b1;ny=cy-1'b1;end
   1:ny=cy-1'b1;
   2:begin nx=cx+1'b1;ny=cy-1'b1;end
   3:nx=cx-1'b1;
   4:nx=cx+1'b1;
   5:begin nx=cx-1'b1;ny=cy+1'b1;end
   6:ny=cy+1'b1;
   7:begin nx=cx+1'b1;ny=cy+1'b1;end
   default:;
  endcase
  updated_word=cache_q;
  updated_word[neighbor_pixel[5:0]*2 +:2]=2'b10;
 end
 assign write_valid=transfer_active && req_write;
 assign write_data=write_source ? cache_q : queue_q;

 // Each inferred RAM has one explicit read address and registered output.
 wire scan_advance=(state==SEED_CHECK && scan_seeds==0 || state==SEED_NEXT && seed_mask==0);
 wire [3:0] scan_seeds=seed_q[scan_index[3:0]*4 +:4];
 wire queue_read_enable=state==POP_LOAD || state==POP && tail!=0 && queue_loaded && read_queue_block==top_index[19:7] ||
   req_valid && req_ready && req_write && write_source==0 ||
   write_valid && write_ready && write_source==0;
 wire [4:0] queue_read_address=state==POP_LOAD || state==POP ? top_index[6:2] : req_valid ? 5'd0 : beat[4:0]+5'd1;
 wire state_buffer_write=read_valid && state==SEED_WAIT;
 wire state_buffer_read=state==SEED_LOAD || scan_advance && scan_index[3:0]==15;
 reg [63:0] seed_q;
 wire [63:0] seed_input;
 for(genvar si=0;si<64;si=si+1) assign seed_input[si]=read_data[si*2+1];
 wire queue_fill=read_valid && state==QREAD_WAIT;
 wire work_push=state==PUSH || state==SEED_NEXT && seed_mask!=0;
 wire [31:0] work_coordinate=state==SEED_NEXT ? {11'd0,scan_y,(scan_x+{9'd0,seed_lane})} : push_coordinate;
 wire [4:0] queue_write_address=queue_fill ? beat[4:0] : tail[6:2];
 always @(posedge clk) begin
  if(queue_fill || work_push && tail[1:0]==0) queue0[queue_write_address]<=queue_fill ? read_data[31:0] : work_coordinate;
  if(queue_fill || work_push && tail[1:0]==1) queue1[queue_write_address]<=queue_fill ? read_data[63:32] : work_coordinate;
  if(queue_fill || work_push && tail[1:0]==2) queue2[queue_write_address]<=queue_fill ? read_data[95:64] : work_coordinate;
  if(queue_fill || work_push && tail[1:0]==3) queue3[queue_write_address]<=queue_fill ? read_data[127:96] : work_coordinate;
  if(queue_read_enable) queue_q<={queue3[queue_read_address],queue2[queue_read_address],queue1[queue_read_address],queue0[queue_read_address]};
  if(state_buffer_write || state_buffer_read) begin
   for(integer s=0;s<STATE_GROUP/16-1;s=s+1) seed_fifo[s]<=seed_fifo[s+1];
   seed_fifo[STATE_GROUP/16-1]<=state_buffer_write ? seed_input : 64'd0;
  end
  if(state_buffer_read) seed_q<=seed_fifo[0];
 end
 wire [31:0] popped_coordinate=queue_q[top_index[1:0]*32 +:32];
 wire [19:0] next_neighbor_pixel=ny*W+nx;
 wire [31:0] next_cache_address=state_base+{14'd0,next_neighbor_pixel[19:6],4'd0};
 wire external_hit=external_request && (local_queue || cache_hit);
 wire cache_read_enable=external_hit && !ext_write || state==EXT_LOOK || state==CACHE_LOOK || state==NEIGHBOR && neighbor_valid || next_hit_read ||
   req_valid && req_ready && req_write && write_source==1 ||
   write_valid && write_ready && write_source==1;
 wire [10:0] cache_read_address=local_queue ? {1'b1,ext_address[13:4]} :
   external_hit || state==EXT_LOOK ? {1'b0,line_index,cache_address[11:4]} : state==NEIGHBOR || state==CACHE_CHECK ? {1'b0,next_cache_address[13:4]} : state==CACHE_LOOK ? {1'b0,cache_address[13:4]} :
   req_valid ? {1'b0,transfer_line,8'd0} : {1'b0,transfer_line,beat+8'd1};
 wire cache_write_enable=external_hit && ext_write || state==EXT_WRITE || state==MARK || read_valid && (state==CACHE_RD_WAIT || state==COPY_WAIT);
 wire [10:0] cache_write_address=local_queue ? {1'b1,ext_address[13:4]} :
   external_hit || state==EXT_WRITE ? {1'b0,line_index,cache_address[11:4]} : state==MARK ? {1'b0,cache_address[13:4]} : {1'b0,active_line,beat};
 wire [127:0] cache_write_data=external_hit || state==EXT_WRITE ? ext_data : state==MARK ? updated_word : read_data;
 always @(posedge clk) begin
  if(cache_write_enable) cache[cache_write_address]<=cache_write_data;
  if(cache_read_enable) cache_q<=cache[cache_read_address];
 end

 integer k;
 always @(posedge clk) begin
  if(!rst_n) begin
   state<=IDLE;return_state<=IDLE;busy<=0;done<=0;ok<=0;cycles<=0;enqueued<=0;highwater<=0;cache_misses<=0;
   req_valid<=0;req_write<=0;req_address<=0;req_len<=0;transfer_active<=0;beat<=0;write_source<=0;transfer_line<=0;
   state_base<=0;failed<=0;tail<=0;head<=0;push_coordinate<=0;current_coordinate<=0;
   external_mode<=0;external_write<=0;external_address<=0;ext_done<=0;ext_error<=0;copy_offset<=0;replacement<=0;
   read_queue_block<=0;queue_loaded<=0;scan_offset<=0;scan_index<=0;scan_x<=0;scan_y<=0;seed_mask<=0;
   neighbor<=0;neighbor_pixel<=0;active_line<=0;flush_line<=0;valid_lines<=0;dirty_lines<=0;
   for(k=0;k<4;k=k+1) tags[k]<=0;
  end else begin
   done<=0;
   ext_done<=0;
   if(busy) cycles<=cycles+1'b1;
   if(occupancy>highwater) highwater<=occupancy;
   if(req_valid && req_ready) begin req_valid<=0;transfer_active<=1;beat<=0;end
   if(read_valid || write_valid && write_ready) beat<=beat+1'b1;
   if(transfer_done) begin transfer_active<=0;if(transfer_error) failed<=1;end
   case(state)
    IDLE:if(start) begin
     external_mode<=0;
     busy<=1;ok<=0;failed<=0;cycles<=0;enqueued<=0;highwater<=0;cache_misses<=0;
     state_base<=STATE_BASE+{12'd0,slot,18'd0};head<=0;tail<=0;
     queue_loaded<=0;valid_lines<=0;dirty_lines<=0;scan_offset<=0;scan_x<=0;scan_y<=0;state<=SEED_REQ;
    end else if(ext_valid===1'b1) begin
     external_mode<=1;external_write<=ext_write;external_address<=ext_address;ext_error<=0;
     if(ext_copy) begin
      // Copy accepted state to the independent traversal plane in 64-beat bursts.
      state_base<=ext_address;copy_offset<=0;active_line<=0;transfer_line<=0;valid_lines<=0;dirty_lines<=0;state<=COPY_READ;
     end else if(local_queue || cache_hit) begin
      // The registered RAM read and acknowledgement arrive together. Writes
      // replace a complete word, so a hit needs no preceding RAM read.
      if(ext_write && !local_queue) dirty_lines[line_index]<=1;
      ext_done<=1;
     end else state<=EXT_LOOK;
    end
    SEED_REQ:begin
     req_valid<=1;req_write<=0;req_address<=state_base+scan_offset;req_len<=STATE_GROUP/16-1;
     state<=SEED_WAIT;
    end
    SEED_WAIT:if(transfer_done) begin scan_index<=0;state<=SEED_LOAD;end
    SEED_LOAD:state<=SEED_CHECK;
    SEED_CHECK:begin
     if(scan_seeds!=0) begin seed_mask<=scan_seeds;state<=SEED_NEXT;end
     else begin
      if(scan_x==W-4) begin scan_x<=0;scan_y<=scan_y+1'b1;end else scan_x<=scan_x+4;
      if(scan_index==STATE_GROUP-1) begin
       if(scan_offset==WORDS-STATE_GROUP) state<=POP;
       else begin scan_offset<=scan_offset+STATE_GROUP;state<=SEED_REQ;end
      end else scan_index<=scan_index+1'b1;
     end
    end
    SEED_NEXT:begin
     if(seed_mask!=0) begin
      if(enqueued==PIXELS) begin failed<=1;state<=FINISH;end
      else begin
       tail<=tail+1'b1;enqueued<=enqueued+1'b1;queue_loaded<=1;read_queue_block<=tail[19:7];
       seed_mask[seed_lane]<=0;
       if(tail[6:0]==127) begin return_state<=SEED_NEXT;state<=QFLUSH_REQ;end
      end
     end else begin
      if(scan_x==W-4) begin scan_x<=0;scan_y<=scan_y+1'b1;end else scan_x<=scan_x+4;
      if(scan_index==STATE_GROUP-1) begin
       if(scan_offset==WORDS-STATE_GROUP) state<=POP;
       else begin scan_offset<=scan_offset+STATE_GROUP;state<=SEED_REQ;end
      end else begin scan_index<=scan_index+1'b1;state<=SEED_CHECK;end
     end
    end
    PUSH:begin
     if(enqueued==PIXELS) begin failed<=1;state<=FINISH;end
     else begin
      tail<=tail+1'b1;enqueued<=enqueued+1'b1;
      queue_loaded<=1;read_queue_block<=tail[19:7];
      state<=tail[6:0]==127 ? QFLUSH_REQ : return_state;
     end
    end
    QFLUSH_REQ:begin
     req_valid<=1;req_write<=1;req_address<=QUEUE_BASE+((tail-128)<<2);req_len<=31;write_source<=0;
     state<=QFLUSH_WAIT;
    end
    QFLUSH_WAIT:if(transfer_done) state<=return_state;
    POP:begin
     if(tail==0) begin flush_line<=0;state<=FLUSH;end
     else if(queue_loaded && read_queue_block==top_index[19:7]) state<=POP_USE;
     else state<=QREAD_REQ;
    end
    QREAD_REQ:begin
     req_valid<=1;req_write<=0;req_address<=QUEUE_BASE+{10'd0,top_index[19:7],9'd0};req_len<=31;
     state<=QREAD_WAIT;
    end
    QREAD_WAIT:if(transfer_done) begin queue_loaded<=1;read_queue_block<=top_index[19:7];state<=POP_LOAD;end
    POP_LOAD:state<=POP_USE;
    POP_USE:begin current_coordinate<=popped_coordinate;head<=head+1'b1;tail<=tail-1'b1;neighbor<=0;state<=NEIGHBOR;end
    NEIGHBOR:begin
     if(neighbor_valid) begin
      // State pairs use increasing x in increasing bit lanes.
      neighbor_pixel<=next_neighbor_pixel;state<=CACHE_CHECK;
     end else if(neighbor==7) state<=POP;
     else begin neighbor<=neighbor+1'b1;state<=NEIGHBOR;end
    end
    CACHE_LOOK:state<=CACHE_CHECK;
    CACHE_CHECK:begin
     if(cache_hit) begin
      if(cache_weak) state<=MARK;
      else if(following_neighbor>=8) state<=POP;
      else if(neighbor_valid) begin neighbor<=following_neighbor;neighbor_pixel<=next_neighbor_pixel;state<=CACHE_CHECK;end
      else begin neighbor<=following_neighbor;state<=NEIGHBOR;end
     end else begin
      active_line<=line_index;cache_misses<=cache_misses+1'b1;
      state<=valid_lines[line_index] && dirty_lines[line_index] ? CACHE_WB_REQ : CACHE_RD_REQ;
     end
    end
    CACHE_WB_REQ:begin
     req_valid<=1;req_write<=1;req_address<={tags[active_line],12'd0};req_len<=255;
     transfer_line<=active_line;write_source<=1;state<=CACHE_WB_WAIT;
    end
    CACHE_WB_WAIT:if(transfer_done) begin dirty_lines[active_line]<=0;state<=CACHE_RD_REQ;end
    CACHE_RD_REQ:begin
     req_valid<=1;req_write<=0;req_address<={cache_address[31:12],12'd0};req_len<=255;
     state<=CACHE_RD_WAIT;
    end
    CACHE_RD_WAIT:if(transfer_done) begin
     valid_lines[active_line]<=1;dirty_lines[active_line]<=0;tags[active_line]<=cache_address[31:12];state<=external_mode ? EXT_LOOK : CACHE_LOOK;
    end
    MARK:begin
     dirty_lines[line_index]<=1;push_coordinate<={11'd0,ny,nx};return_state<=NEXT_NEIGHBOR;state<=PUSH;
    end
    NEXT_NEIGHBOR:begin
     if(neighbor==7) state<=POP;
     else begin neighbor<=neighbor+1'b1;state<=NEIGHBOR;end
    end
    FLUSH:begin
     if(dirty_lines[flush_line]) begin
      req_valid<=1;req_write<=1;req_address<={tags[flush_line],12'd0};req_len<=255;
      transfer_line<=flush_line;write_source<=1;state<=29;
     end else if(flush_line==3) state<=FINISH;
     else flush_line<=flush_line+1'b1;
    end
    29:if(transfer_done) begin dirty_lines[flush_line]<=0;state<=FLUSH;end
    EXT_LOOK:state<=EXT_CHECK;
    EXT_CHECK:begin
     if(cache_hit) begin
      if(external_write) state<=EXT_WRITE;
      else begin ext_done<=1;state<=IDLE;end
     end else begin
      active_line<=line_index;
      replacement<=line_index+1'b1;
      state<=valid_lines[line_index] && dirty_lines[line_index] ? CACHE_WB_REQ : CACHE_RD_REQ;
     end
    end
    EXT_WRITE:begin dirty_lines[line_index]<=1;ext_done<=1;state<=IDLE;end
    COPY_READ:begin
     req_valid<=1;req_write<=0;req_address<=state_base+copy_offset;
     req_len<=WORDS-copy_offset>=1024 ? 63 : (WORDS-copy_offset)/16-1;state<=COPY_WAIT;
    end
    COPY_WAIT:if(transfer_done) state<=COPY_WRITE;
    COPY_WRITE:begin
     req_valid<=1;req_write<=1;req_address<=VISIT_BASE+copy_offset;write_source<=1;
     state<=COPY_DONE;
    end
    COPY_DONE:if(transfer_done) begin
     if(copy_offset+1024>=WORDS) begin ext_done<=1;state<=IDLE;end
     else begin copy_offset<=copy_offset+1024;state<=COPY_READ;end
    end
    FINISH:begin busy<=0;done<=1;ok<=!failed;state<=IDLE;end
    default:begin failed<=1;state<=FINISH;end
   endcase
   // Abort after the outstanding transaction; corrupt queue data must never become an address.
   if(transfer_done && transfer_error) begin
    if(external_mode) begin ext_error<=1;ext_done<=1;state<=IDLE;valid_lines<=0;dirty_lines<=0;end
    else begin failed<=1;state<=FINISH;end
   end
  end
 end
endmodule
