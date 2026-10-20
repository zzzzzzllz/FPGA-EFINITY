// One held raw frame; each burst is fully buffered before pixel consumption.
module frame_reader(
 input clk, rst,
 input job_valid, output job_ready,
 input [5:0] job_slot,
 input [31:0] job_frame_id, job_epoch, job_generation, job_source_time_ms,
 output hold_valid, input hold_ready, hold_granted,
 output [133:0] hold_identity,
 output reg held, output [5:0] held_slot, output reg [133:0] identity,
 input [31:0] config_epoch, config_generation,
 input cmd_valid, output cmd_ready, input full_scan,
 input [10:0] cmd_x, input [9:0] cmd_y,
 input [8:0] cmd_width, input [6:0] cmd_height,
 output pixel_valid, input pixel_ready,
 output reg [23:0] rgb0, rgb1, output reg [1:0] keep,
 output reg [10:0] pixel_x, output reg [9:0] pixel_y,
 output reg line_last, cmd_last,
 output cmd_done_valid, input cmd_done_ready,
 input finish_valid, output finish_ready, input [3:0] finish_status,
 input cancel_valid, input [3:0] cancel_status,
 output abort_valid, output [3:0] abort_status,
 output burst_valid, input burst_ready,
 output reg [31:0] burst_addr, output reg [7:0] burst_len,
 input rsp_valid, output rsp_ready, input [127:0] rsp_data,
 input rsp_last, input [1:0] rsp_resp,
 output recover_req, input recover_ack,
 output release_valid, input release_ready,
 output job_done_valid, input job_done_ready, output reg [3:0] status
);
 localparam BOOT=0, IDLE=1, WAIT_CMD=2, ROW=3, PLAN=4, OFFER=5,
  RECEIVE=6, FETCH=7, LOAD=8, BYTES=9, PIXEL=10, CMD_DONE=11,
  DRAIN=12, RECOVER=13, RELEASE=14, DONE=15;
 reg [3:0] state;
 reg have_job, aborted, protocol_fault, offer, outstanding, ack_armed;
 reg [5:0] received;
 reg [10:0] x_start, width, cursor_x;
 reg [9:0] cursor_y, rows_left;
 reg [31:0] row_addr, next_addr;
 reg [11:0] bytes_left;
 reg [3:0] skip, lane;
 reg [4:0] read_index;
 reg [127:0] word_q, shift_word;
 reg [47:0] pair_bytes;
 reg [2:0] pair_count;
 reg [1:0] after_pixel;
 // ponytail: one 32-beat buffer; overlap fetch/consume only if measured throughput needs it.
 (* ram_style="block" *) reg [127:0] buffer[0:31];
 wire config_changed = identity[95:64]!=config_epoch || identity[63:32]!=config_generation;
 wire cancel_now = have_job && state!=DONE && !aborted && (config_changed || cancel_valid);
 wire [3:0] cancel_code = config_changed ? 4'd6 : cancel_status;
 wire unexpected = rsp_valid && !outstanding && state!=BOOT && state!=RECOVER;
 wire bad_last = rsp_valid && outstanding && (rsp_last != (received=={1'b0,burst_len}));
 wire bad_resp = rsp_valid && outstanding && rsp_resp!=0;
 wire fault_now = unexpected || bad_last;
 assign abort_valid = !rst && have_job && (aborted || cancel_now || fault_now || bad_resp);
 assign abort_status = aborted ? status : cancel_now ? cancel_code : fault_now ? 4'd10 : bad_resp ? 4'd9 : cancel_code;
 assign hold_identity = {job_slot,job_frame_id,job_epoch,job_generation,job_source_time_ms};
 assign held_slot = identity[133:128];
 assign hold_valid = !rst && state==IDLE && job_valid && job_slot<=40 && !rsp_valid;
 assign job_ready = !rst && state==IDLE && !rsp_valid && (job_slot>40 || hold_ready);
 assign finish_ready = !rst && state==WAIT_CMD && !abort_valid && !rsp_valid;
 assign cmd_ready = finish_ready && !finish_valid;
 assign pixel_valid = !rst && state==PIXEL && !abort_valid && !rsp_valid;
 assign cmd_done_valid = !rst && state==CMD_DONE && !abort_valid && !rsp_valid;
 assign burst_valid = !rst && offer;
 assign rsp_ready = !rst;
 assign recover_req = !rst && (state==BOOT || state==RECOVER ||
                              ((aborted || cancel_now) && (offer || outstanding)));
 wire burst_fire = burst_valid && burst_ready;
 wire ack_ok = recover_req && ack_armed && recover_ack && !rsp_valid && !burst_fire;
 assign release_valid = !rst && state==RELEASE && held && !rsp_valid &&
                        !offer && !outstanding && !protocol_fault;
 assign job_done_valid = !rst && state==DONE && !rsp_valid;
 wire [11:0] roi_right = {1'b0,cmd_x}+{3'b0,cmd_width};
 wire [10:0] roi_bottom = {1'b0,cmd_y}+{4'b0,cmd_height};
 wire bad_roi = !full_scan && (cmd_width==0 || cmd_width>320 || cmd_height==0 ||
                  cmd_height>96 || roi_right>1280 || roi_bottom>720);
 wire [31:0] base_addr = ({26'b0,held_slot}<<21)+({26'b0,held_slot}<<20);
 wire [31:0] roi_addr = base_addr+({22'b0,cmd_y}<<12)-({22'b0,cmd_y}<<8)+
                                     ({21'b0,cmd_x}<<1)+{21'b0,cmd_x};
 wire [12:0] covered_bytes = {1'b0,bytes_left}+{9'b0,skip}+13'd15;
 wire [8:0] needed_beats = covered_bytes[12:4];
 wire [8:0] page_beats = 9'd256-{1'b0,next_addr[11:4]};
 wire [8:0] capped_beats = needed_beats>32 ? 9'd32 : needed_beats;
 wire [8:0] planned_beats = capped_beats>page_beats ? page_beats : capped_beats;
 wire [1:0] byte_action = bytes_left==1 ? 2'd3 : lane!=15 ? 2'd0 :
                         read_index==burst_len[4:0] ? 2'd2 : 2'd1;
 always @(posedge clk) begin
  if(!rst && state==RECEIVE && outstanding && rsp_valid && !aborted && !cancel_now && received<32)
   buffer[received[4:0]]<=rsp_data;
  if(state==FETCH) word_q<=buffer[read_index];
 end
 always @(posedge clk) begin
  if(rst) begin
   state<=BOOT;have_job<=0;held<=0;identity<=0;status<=0;aborted<=0;protocol_fault<=0;
   offer<=0;outstanding<=0;ack_armed<=0;received<=0;burst_addr<=0;burst_len<=0;
   x_start<=0;width<=0;cursor_x<=0;cursor_y<=0;rows_left<=0;row_addr<=0;next_addr<=0;
   bytes_left<=0;skip<=0;lane<=0;read_index<=0;shift_word<=0;pair_bytes<=0;pair_count<=0;
   after_pixel<=0;rgb0<=0;rgb1<=0;keep<=0;pixel_x<=0;pixel_y<=0;line_last<=0;cmd_last<=0;
  end else begin
   if(!recover_req) ack_armed<=0;
   else if(!recover_ack) ack_armed<=1;
   else if(rsp_valid || burst_fire) ack_armed<=0;
   case(state)
    IDLE: if(job_valid && job_ready) begin
     identity<=hold_identity;have_job<=1;aborted<=0;protocol_fault<=0;status<=0;
     if(job_slot>40) begin status<=8;aborted<=1;state<=DONE;end
     else if(!hold_granted) begin status<=7;aborted<=1;state<=DONE;end
     else begin
      held<=1;
      if(job_epoch!=config_epoch || job_generation!=config_generation || cancel_valid) begin
       status<=job_epoch!=config_epoch || job_generation!=config_generation ? 4'd6 : cancel_status;
       aborted<=1;state<=RELEASE;
      end else state<=WAIT_CMD;
     end
    end
    WAIT_CMD: begin
     if(finish_valid && finish_ready) begin status<=finish_status;state<=RELEASE;end
     else if(cmd_valid && cmd_ready) begin
      if(bad_roi) begin status<=8;aborted<=1;state<=RELEASE;end
      else begin
       x_start<=full_scan ? 0 : cmd_x;cursor_x<=full_scan ? 0 : cmd_x;
       cursor_y<=full_scan ? 0 : cmd_y;width<=full_scan ? 1280 : {2'b0,cmd_width};
       rows_left<=full_scan ? 720 : {3'b0,cmd_height};
       row_addr<=full_scan ? base_addr : roi_addr;state<=ROW;
      end
     end
    end
    ROW: begin
     next_addr<={row_addr[31:4],4'b0};skip<=row_addr[3:0];
     bytes_left<=({1'b0,width}<<1)+{1'b0,width};pair_count<=0;pair_bytes<=0;state<=PLAN;
    end
    PLAN: if(!abort_valid && !rsp_valid) begin
     burst_addr<=next_addr;burst_len<=planned_beats-1'b1;offer<=1;state<=OFFER;
    end
    FETCH: state<=LOAD;
    LOAD: begin shift_word<=word_q<<{skip,3'b0};lane<=skip;skip<=0;state<=BYTES;end
    BYTES: begin
     pair_bytes<={pair_bytes[39:0],shift_word[127:120]};shift_word<=shift_word<<8;
     bytes_left<=bytes_left-1'b1;lane<=lane+1'b1;
     if(lane==15) begin
      if(read_index==burst_len[4:0]) next_addr<=next_addr+(({24'b0,burst_len}+32'd1)<<4);
      else read_index<=read_index+1'b1;
     end
     if(pair_count==5 || bytes_left==1) begin
      rgb0<=pair_count==5 ? pair_bytes[39:16] : {pair_bytes[15:0],shift_word[127:120]};
      rgb1<=pair_count==5 ? {pair_bytes[15:0],shift_word[127:120]} : 24'd0;
      keep<=pair_count==5 ? 2'b11 : 2'b01;pixel_x<=cursor_x;pixel_y<=cursor_y;
      line_last<=bytes_left==1;cmd_last<=bytes_left==1 && rows_left==1;
      pair_count<=0;after_pixel<=byte_action;state<=PIXEL;
     end else begin
      pair_count<=pair_count+1'b1;
      case(byte_action)
       0: state<=BYTES;
       1: state<=FETCH;
       2: state<=PLAN;
       default: state<=RECOVER;
      endcase
     end
    end
    PIXEL: if(pixel_valid && pixel_ready) begin
     cursor_x<=cursor_x+(keep==3 ? 11'd2 : 11'd1);
     case(after_pixel)
      0: state<=BYTES;
      1: state<=FETCH;
      2: state<=PLAN;
      3: if(rows_left==1) state<=CMD_DONE;
         else begin
          rows_left<=rows_left-1'b1;cursor_y<=cursor_y+1'b1;cursor_x<=x_start;
          row_addr<=row_addr+32'd3840;state<=ROW;
         end
     endcase
    end
    CMD_DONE: if(cmd_done_valid && cmd_done_ready) state<=WAIT_CMD;
    DRAIN: if(!offer && !outstanding) state<=held ? RELEASE : DONE;
    RELEASE: if(release_valid && release_ready) begin held<=0;state<=DONE;end
    DONE: if(job_done_valid && job_done_ready) begin have_job<=0;aborted<=0;state<=IDLE;end
    default: ;
   endcase
   if(burst_fire) begin
    offer<=0;outstanding<=1;received<=0;
    state<=protocol_fault ? RECOVER : (aborted || cancel_now) ? DRAIN : RECEIVE;
   end
   if(rsp_valid && outstanding) begin
    if(received<32) received<=received+1'b1;
    if(!bad_last && received=={1'b0,burst_len}) begin
     outstanding<=0;
     if(!protocol_fault) begin
      if(aborted || cancel_now || bad_resp) state<=held ? RELEASE : DONE;
      else begin read_index<=0;state<=FETCH;end
     end
    end
    if(bad_resp && !aborted) begin
     status<=9;aborted<=1;
     if(received!={1'b0,burst_len} && !protocol_fault) state<=DRAIN;
    end
   end
   if(cancel_now) begin
    status<=cancel_code;aborted<=1;
    if(!protocol_fault) state<=release_valid && release_ready ? DONE :
                               (offer || outstanding) ? DRAIN : held ? RELEASE : DONE;
   end
   if(fault_now) begin
    protocol_fault<=1;aborted<=1;state<=RECOVER;
    if(!aborted && !cancel_now) status<=10;
   end
   if(ack_ok) begin
    offer<=0;outstanding<=0;protocol_fault<=0;ack_armed<=0;
    if(held) state<=RELEASE;
    else if(have_job) state<=DONE;
    else begin state<=IDLE;aborted<=0;end
   end
  end
 end
endmodule
