// Burst transport for the M08 frame store. The existing DDR controller/PHY
// remains unchanged. Each channel has at most one outstanding transaction.
module frame_store_dma #(
 parameter WORDS=230400, W=1280, H=720, BURST=128, FIFO_DEPTH=512, RAW_SLOTS=41, ENABLE_CANNY=0,
 RESULT_BASE=32'h07b00000, STATE_BASE=32'h08b00000
)(
 input clk,rst_n,enabled,
 input canny_req_valid,canny_req_write,input [31:0] canny_address,input [7:0] canny_len,
 output canny_req_ready,input [127:0] canny_write_data,input canny_write_valid,
 output canny_write_ready,canny_read_valid,canny_done,canny_error,
 input [161:0] capture_data,input [10:0] capture_count,input capture_empty,
 output capture_take,
 input [161:0] result_data,input [10:0] result_count,input result_empty,
 output result_take,
 output reg capture_start,output [31:0] capture_id,
 input capture_accept,input [5:0] capture_slot,
 output reg capture_done,capture_ok,
 input job_start,input job_canny,job_recognize,input [5:0] job_source,input [1:0] job_result,
 input job_reader_ready,
 output reg job_done,job_ok,
 output [127:0] algorithm_data,output algorithm_write,input [10:0] algorithm_used,
 input display_period,input reference_mode,
 output reg display_start,display_end,display_reset,
 output display_reference_active,
 input display_valid,input [1:0] display_slot,
 input [15:0] display_config,input [31:0] display_frame_id,
 input [2:0] saved_valid,input [17:0] saved_slots,input [5:0] display_source,
 output reg [127:0] display_data,output reg display_write,input [10:0] display_used,
 output reg [31:0] bus_errors,
 output reg [159:0] traffic,
 output [31:0] awaddr,araddr,output [7:0] awlen,arlen,
 output awvalid,wvalid,wlast,bready,arvalid,rready,
 output [127:0] wdata,output [15:0] wstrb,
 input awready,wready,bvalid,arready,rvalid,rlast,
 input [1:0] bresp,rresp,input [127:0] rdata
);
 localparam C_SEEK=0,C_WAIT=1,C_DROP=2,C_ACTIVE=3,C_REJECT=4;
 reg [2:0] capture_state;
 reg [2:0] allocation_wait;
 reg [$clog2(WORDS+1)-1:0] capture_offset,result_offset,algorithm_offset,display_offset;
 reg capture_bad,result_bad,job_active,job_canny_active,job_is_canny;
 reg [5:0] raw_slot,source_slot;
 reg [1:0] output_slot;
 reg [2:0] ws;
 reg [1:0] writer;
 reg result_turn;
 reg [7:0] write_length,read_length;
 reg canny_read_bad;
 reg [7:0] wb;
 reg [31:0] write_address;
 reg [1:0] raw_write_phase,raw_read_phase;
 reg [95:0] raw_write_carry,raw_read_carry;
 reg [7:0] raw_write_index,raw_read_index;
 // Three power-of-two sub-bursts preserve AXI 4 KiB alignment. For BURST=128,
 // each is 512 bytes and every packed block begins on a 512-byte boundary.
 localparam RAW_BEATS=BURST/4;
 reg [1:0] raw_write_burst,raw_read_burst;
 reg raw_read_last;
 wire [95:0] compact_capture={capture_data[119:96],capture_data[87:64],capture_data[55:32],capture_data[23:0]};
 wire [127:0] compact_write=raw_write_phase==1 ? {raw_write_carry,compact_capture[95:64]} :
                           raw_write_phase==2 ? {raw_write_carry[63:0],compact_capture[95:32]} :
                                                {raw_write_carry[31:0],compact_capture};
 function [31:0] raw_address;
  input [5:0] slot;input [31:0] word_offset;
  begin raw_address=({26'd0,slot}<<21)+({26'd0,slot}<<20)+(word_offset<<3)+(word_offset<<2);end
 endfunction
 wire capture_burst=capture_state==C_ACTIVE && capture_count>=BURST;
 wire result_burst=job_active && result_count>=BURST;
 assign capture_id=capture_data[161:130];
 assign capture_take=(capture_state==C_REJECT && !capture_empty) ||
                      (capture_state==C_DROP && !capture_empty && !capture_data[129]) ||
                      (ws==2 && writer==0 && !capture_empty && (raw_write_phase==0 || wready && wvalid));
 assign result_take=ws==2 && writer==1 && wready && wvalid;
 assign awaddr=write_address;
 assign awlen=write_length;
 assign awvalid=ws==1;
 assign wvalid=ws==2 && (writer==3 ? 1'b1 : writer==2 ? canny_write_valid : writer==1 ? !result_empty : !capture_empty && raw_write_phase!=0);
 assign wdata=writer==3 ? state_q : writer==2 ? canny_write_data : writer==1 ? result_data[127:0] : compact_write;
 assign wstrb=16'hffff;
 assign wlast=wb==write_length;
 assign bready=ws==3;

 // Preserve compact classification while its RGB result burst is written.
 reg [119:0] state_pack;
 reg [127:0] state_buffer[0:BURST/16-1];
 wire [127:0] state_q=state_buffer[0];
 wire [7:0] class_four=job_is_canny ? {result_data[31:30],result_data[63:62],result_data[95:94],result_data[127:126]} : {result_data[31],1'b0,result_data[63],1'b0,result_data[95],1'b0,result_data[127],1'b0};
 wire state_next=ws==2 && writer==3 && wvalid && wready;
 wire state_append=result_take && job_canny_active && wb[3:0]==15;
 always @(posedge clk) begin
  if(result_take && job_canny_active) begin
   state_pack<={class_four,state_pack[119:8]};
  end
  // Sequential write/read order allows SRL storage instead of six shallow RAMs.
  if(state_append || state_next) begin
   for(integer s=0;s<BURST/16-1;s=s+1) state_buffer[s]<=state_buffer[s+1];
   state_buffer[BURST/16-1]<=state_append ? {class_four,state_pack} : 128'd0;
  end
 end

 reg [2:0] rs;
 reg [2:0] reader;
 reg [7:0] rb;
 reg [31:0] read_address;
 reg read_turn,display_active,reference_needed,state_loaded,read_display_canny;
 reg [15:0] read_config;
 reg [31:0] read_frame_id;
 assign display_reference_active=reference_needed;
 // Read every second source row and keep every second pixel for each tile.
 localparam ROW_WORDS=W/4, ROW_FACTOR=ROW_WORDS & -ROW_WORDS;
 localparam QUAD_WORDS=ROW_FACTOR<BURST ? ROW_FACTOR : BURST, QUAD_BEATS=QUAD_WORDS/4;
 reg [23:0] quad_slots;reg [3:0] quad_valid;
 reg quad_right,quad_bottom;
 reg [$clog2(ROW_WORDS+1)-1:0] quad_x;
 reg [$clog2(H/2+1)-1:0] quad_y;
 reg [$clog2(WORDS+1)-1:0] quad_row;
 reg [63:0] quad_pair;
 wire [1:0] quad_index={quad_bottom,quad_right};
 wire [23:0] quad_rgb0=quad_valid[quad_index] ? raw_rgb[95:72] : 24'd0;
 wire [23:0] quad_rgb2=quad_valid[quad_index] ? raw_rgb[47:24] : 24'd0;
 wire [63:0] quad_samples={1'b0,read_frame_id[6:0],quad_rgb0,1'b0,read_frame_id[6:0],quad_rgb2};
 reg [1:0] read_display_slot;
 reg [127:0] response_q;
 reg response_pending;
 reg [1:0] period_sync;
 reg period_last,restart_pending;
 reg [5:0] restart_count;
 wire period_rise=period_sync[1] && !period_last;
 wire algorithm_burst=job_active && job_reader_ready && algorithm_offset<WORDS && algorithm_used<=FIFO_DEPTH-BURST-4;
 wire display_burst=display_active && display_offset<WORDS && display_used<=FIFO_DEPTH-BURST-4;
 wire canny_write_request=ENABLE_CANNY && canny_req_valid && canny_req_write;
 wire canny_read_request=ENABLE_CANNY && canny_req_valid && !canny_req_write;
 wire choose_canny_write=canny_write_request && !result_burst && (!capture_burst || result_turn);
 wire choose_display=display_burst && (!(algorithm_burst || canny_read_request) || display_used<FIFO_DEPTH/2 || read_turn || state_loaded);
 assign canny_req_ready=enabled && ((ws==0 && choose_canny_write) ||
   (rs==0 && !restart_pending && restart_count==0 && !choose_display && !algorithm_burst && canny_read_request));
 assign canny_write_ready=ws==2 && writer==2 && wready;
 assign canny_read_valid=rs==2 && reader==3 && rvalid;
 assign canny_done=(ws==3 && writer==2 && bvalid) || (canny_read_valid && rb==read_length);
 assign canny_error=ws==3 && writer==2 ? bresp!=0 : canny_read_bad || rresp!=0 || rlast!=(rb==read_length);

 assign araddr=read_address;
 assign arlen=read_length;
 assign arvalid=rs==1;
 wire raw_read=reader==0 || reader==2;
 assign rready=rs==2 && (!raw_read || raw_read_phase!=3);
 wire raw_output_valid=rs==2 && raw_read && (raw_read_phase==3 || rvalid && rready);
 wire [95:0] raw_rgb=raw_read_phase==0 ? rdata[127:32] :
                     raw_read_phase==1 ? {raw_read_carry[31:0],rdata[127:64]} :
                     raw_read_phase==2 ? {raw_read_carry[63:0],rdata[127:96]} : raw_read_carry;
 wire [127:0] raw_rgby;
 for(genvar c=0;c<4;c=c+1) assign raw_rgby[c*32 +:32]={luma(raw_rgb[c*24 +:24]),raw_rgb[c*24 +:24]};
 assign algorithm_data=raw_rgby;
 assign algorithm_write=raw_output_valid && reader==0;
 // One accepted bit per pixel; registers avoid adding another wide block RAM.
 wire [BURST*4-1:0] display_accepted;
 genvar state_word;
 generate for(state_word=0;state_word<BURST/16;state_word=state_word+1) begin: display_state
  reg [63:0] accepted;
  integer bit_index;
  always @(posedge clk) if(rs==2 && reader==4 && rvalid && rb==state_word)
   for(bit_index=0;bit_index<64;bit_index=bit_index+1) accepted[bit_index]<=rdata[bit_index*2+1];
  assign display_accepted[state_word*64 +:64]=accepted;
 end endgenerate
 function [7:0] luma;
  input [23:0] rgb;reg [15:0] sum;
  begin sum=77*rgb[23:16]+150*rgb[15:8]+29*rgb[7:0]+128;luma=sum[15:8];end
 endfunction
 integer p;
 reg [127:0] display_word;
 always @* begin
  display_word=rdata;
  if(read_display_canny) for(p=0;p<4;p=p+1) begin
   display_word[p*32+31]=!reference_needed && display_accepted[rb*4+3-p];
   display_word[p*32+24 +:7]=read_frame_id[6:0];
   if(display_offset==0 && rb==0 && p==2) display_word[p*32+24 +:7]=read_config[6:0];
   if(display_offset==0 && rb==0 && p==1) display_word[p*32+24 +:7]={1'b0,read_config[12:11],read_config[10:7]};
  end
 end
 reg [23:0] capture_watchdog;
 always @(posedge clk) begin
  if(!rst_n) begin
   capture_state<=C_SEEK;allocation_wait<=0;capture_start<=0;capture_done<=0;capture_ok<=0;
   capture_offset<=0;result_offset<=0;algorithm_offset<=0;display_offset<=0;
   capture_bad<=0;result_bad<=0;job_active<=0;job_canny_active<=0;job_is_canny<=0;raw_slot<=0;source_slot<=0;output_slot<=0;
   raw_write_phase<=0;raw_read_phase<=0;raw_write_carry<=0;raw_read_carry<=0;raw_write_index<=0;raw_read_index<=0;raw_read_last<=0;
   raw_write_burst<=0;raw_read_burst<=0;
   write_length<=BURST-1;read_length<=BURST-1;canny_read_bad<=0;ws<=0;writer<=0;result_turn<=0;wb<=0;write_address<=0;
   job_done<=0;job_ok<=0;bus_errors<=0;capture_watchdog<=0;
   traffic<=0;
   rs<=0;reader<=0;rb<=0;read_address<=0;read_turn<=0;
   display_active<=0;reference_needed<=0;state_loaded<=0;read_display_canny<=0;read_config<=0;read_frame_id<=0;quad_slots<=0;quad_valid<=0;quad_right<=0;quad_bottom<=0;quad_x<=0;quad_y<=0;quad_row<=0;quad_pair<=0;read_display_slot<=0;
   response_pending<=0;response_q<=0;display_write<=0;display_data<=0;
   period_sync<=0;period_last<=0;restart_pending<=0;restart_count<=0;
   display_start<=0;display_end<=0;display_reset<=1;
  end else begin
   capture_start<=0;capture_done<=0;job_done<=0;display_start<=0;display_end<=0;
   if(wvalid && wready) begin
    if(writer==1) traffic[63:32]<=traffic[63:32]+1'b1;
    else if(writer==0) traffic[31:0]<=traffic[31:0]+1'b1;
   end
   if(rvalid && rready) begin
    case(reader)
     0:traffic[95:64]<=traffic[95:64]+1'b1;
     1:traffic[127:96]<=traffic[127:96]+1'b1;
     2:traffic[159:128]<=traffic[159:128]+1'b1;
     default:;
    endcase
   end
   period_sync<={period_sync[0],display_period};period_last<=period_sync[1];
   if(period_rise) restart_pending<=1;
   if(capture_state==C_ACTIVE) capture_watchdog<=capture_watchdog+1'b1;
   else capture_watchdog<=0;
   case(capture_state)
    C_SEEK: if(enabled && !capture_empty) begin
     if(capture_data[129]) begin capture_start<=1;allocation_wait<=0;capture_state<=C_WAIT;end
     else capture_state<=C_DROP;
    end
    C_WAIT: begin
     allocation_wait<=allocation_wait+1'b1;
     if(capture_accept) begin
      raw_slot<=capture_slot;capture_offset<=0;capture_bad<=0;capture_state<=C_ACTIVE;
     end else if(allocation_wait==5) capture_state<=C_REJECT;
    end
    C_REJECT: if(!capture_empty) capture_state<=C_DROP;
    C_DROP: if(!capture_empty && capture_data[129]) capture_state<=C_SEEK;
    default: ;
   endcase
   if(job_start) begin
    job_active<=1;job_canny_active<=ENABLE_CANNY && (job_canny || job_recognize===1'b1);job_is_canny<=job_canny;source_slot<=job_source;output_slot<=job_result;
    result_offset<=0;algorithm_offset<=0;result_bad<=0;
   end
   if(capture_take && ws==2 && writer==0) begin
    raw_write_carry<=compact_capture;raw_write_phase<=raw_write_phase+1'b1;raw_write_index<=raw_write_index+1'b1;
    if(capture_data[129]!=(capture_offset==0 && raw_write_index==0) ||
       capture_data[128]!=(capture_offset+raw_write_index==WORDS-1)) capture_bad<=1;
   end
   case(ws)
    0: if(enabled && (capture_burst || result_burst || canny_write_request)) begin
     writer<=choose_canny_write ? 2 : result_burst && (!capture_burst || result_turn) ? 1 : 0;
     write_length<=choose_canny_write ? canny_len : result_burst && (!capture_burst || result_turn) ? BURST-1 : RAW_BEATS-1;
     write_address<=choose_canny_write ? canny_address : result_burst && (!capture_burst || result_turn) ?
        RESULT_BASE+({30'd0,output_slot}<<22)+(result_offset<<4) : raw_address(raw_slot,capture_offset);
     raw_write_phase<=0;raw_write_index<=0;raw_write_burst<=0;
     result_turn<=!result_turn;wb<=0;ws<=1;
    end
    1: if(awready) ws<=2;
    2: if(wvalid && wready) begin
     if(writer==1) begin
      if(result_data[129]!=(result_offset==0 && wb==0) ||
         result_data[128]!=(result_offset+wb==WORDS-1)) result_bad<=1;
     end
     if(wlast) ws<=3;else wb<=wb+1'b1;
    end
    3: if(bvalid) begin
     ws<=0;
     if(bresp!=0) bus_errors<=bus_errors+1'b1;
     if(writer==1) begin
      if(bresp!=0) result_bad<=1;
      if(job_canny_active) begin
       writer<=3;write_length<=BURST/16-1;write_address<=STATE_BASE+({30'd0,output_slot}<<18)+result_offset;wb<=0;ws<=1;
      end else if(result_offset==WORDS-BURST) begin
       job_done<=1;job_ok<=!result_bad && bresp==0;job_active<=0;
      end else result_offset<=result_offset+BURST;
     end else if(writer==3) begin
      if(bresp!=0) result_bad<=1;
      if(result_offset==WORDS-BURST) begin
       job_done<=1;job_ok<=!result_bad && bresp==0;job_active<=0;
      end else result_offset<=result_offset+BURST;
     end else if(writer==0) begin
      if(bresp!=0) capture_bad<=1;
      if(raw_write_burst!=2) begin
       raw_write_burst<=raw_write_burst+1'b1;write_address<=write_address+RAW_BEATS*16;wb<=0;ws<=1;
      end else if(capture_offset==WORDS-BURST) begin
       capture_done<=1;capture_ok<=!capture_bad && bresp==0;capture_state<=C_SEEK;
      end else capture_offset<=capture_offset+BURST;
     end
    end
    default: ws<=0;
   endcase
   if(&capture_watchdog && ws==0) begin
    capture_done<=1;capture_ok<=0;capture_state<=C_DROP;
   end
   // Finish the outstanding read before resetting its FIFO or changing refs.
   if(restart_pending && rs==0 && restart_count==0 && !response_pending) begin
    restart_pending<=0;restart_count<=1;display_active<=0;display_reset<=1;display_end<=1;
   end else if(restart_count!=0) begin
    restart_count<=restart_count+1'b1;
    if(restart_count==3) display_start<=1;
    if(restart_count==16) begin
     display_reset<=0;display_offset<=0;state_loaded<=0;
     read_display_slot<=display_slot;quad_slots<={display_source,saved_slots};quad_valid<={1'b1,saved_valid};
     quad_right<=0;quad_bottom<=0;quad_x<=0;quad_y<=0;quad_row<=0;
     read_display_canny<=ENABLE_CANNY && display_config[13];read_config<=display_config;read_frame_id<=display_frame_id;
     reference_needed<=reference_mode;
     display_active<=display_valid;restart_count<=0;
    end
   end
   display_write<=response_pending && !display_reset;
   display_data<=response_q;
   response_pending<=0;
   if(raw_output_valid) begin
    raw_read_index<=raw_read_index+1'b1;
    if(reader==2) begin
     if(!raw_read_index[0]) quad_pair<=quad_samples;
     else begin
      response_q<={quad_pair,quad_samples};response_pending<=1;
      if(display_offset==0 && raw_read_index==1) begin
       response_q[94:88]<=read_config[6:0];
       response_q[62:56]<={3'b000,read_config[10:7]};
      end
     end
    end
    if(raw_read_phase==3) begin
     raw_read_phase<=0;
     if(raw_read_last) begin
      rs<=0;
      if(reader==0) begin algorithm_offset<=algorithm_offset+BURST;read_turn<=1;end
      else begin
       display_offset<=display_offset+QUAD_WORDS/2;read_turn<=0;
       if(quad_x==ROW_WORDS-QUAD_WORDS) begin
        quad_x<=0;quad_right<=!quad_right;
        if(quad_right) begin
         if(quad_y==H/2-1) begin quad_y<=0;quad_row<=0;quad_bottom<=1;end
         else begin quad_y<=quad_y+1'b1;quad_row<=quad_row+W/2;end
        end
       end else quad_x<=quad_x+QUAD_WORDS;
       if(display_offset==WORDS-QUAD_WORDS/2) begin display_active<=0;display_end<=1;end
      end
     end
    end else begin raw_read_carry<=rdata[95:0];raw_read_phase<=raw_read_phase+1'b1;end
   end
   case(rs)
    0: if(enabled && !restart_pending && restart_count==0 &&
          (algorithm_burst || display_burst || canny_read_request)) begin
     rb<=0;rs<=1;read_length<=BURST-1;canny_read_bad<=0;raw_read_phase<=0;raw_read_index<=0;raw_read_last<=0;raw_read_burst<=0;
     // Split views consume two source rows per output row. Refill their
     // deadline-driven FIFO before spending spare bandwidth on processing.
     if(choose_display) begin
      if(reference_needed) begin
       reader<=2;read_address<=raw_address(quad_slots[quad_index*6 +:6],quad_row+quad_x);read_length<=QUAD_BEATS-1;
      end else if(read_display_canny && !state_loaded) begin
       reader<=4;read_address<=STATE_BASE+({30'd0,read_display_slot}<<18)+display_offset;read_length<=BURST/16-1;
      end else begin
       reader<=1;read_address<=RESULT_BASE+({30'd0,read_display_slot}<<22)+(display_offset<<4);
      end
     end else if(algorithm_burst) begin reader<=0;read_address<=raw_address(source_slot,algorithm_offset);read_length<=RAW_BEATS-1;end
     else begin reader<=3;read_address<=canny_address;read_length<=canny_len;end
    end
    1: if(arready) rs<=2;
    2: if(rvalid && rready) begin
     if(rresp!=0 || rlast!=(rb==read_length)) begin
      bus_errors<=bus_errors+1'b1;
      if(reader==0) result_bad<=1;
      if(reader==3) canny_read_bad<=1;
     end
     if(reader==1) begin
      response_q<=display_word;response_pending<=1;
     end
     if(rb==read_length) begin
      if(raw_read) begin
       if(raw_read_burst==2) raw_read_last<=1;
       else begin raw_read_burst<=raw_read_burst+1'b1;read_address<=read_address+(reader==2 ? QUAD_BEATS*16 : RAW_BEATS*16);rb<=0;rs<=1;end
      end else rs<=0;
      case(reader)
       0: ;
       1: begin
        display_offset<=display_offset+BURST;state_loaded<=0;read_turn<=0;
        if(display_offset==WORDS-BURST) begin display_active<=0;display_end<=1;end
       end
       2: ;
       3: read_turn<=1;
       4: state_loaded<=1;
       default: ;
      endcase
     end else rb<=rb+1'b1;
    end
    default: rs<=0;
   endcase
  end
 end
endmodule
