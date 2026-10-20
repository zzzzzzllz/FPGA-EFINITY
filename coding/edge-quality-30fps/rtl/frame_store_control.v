// Frame references live in one clock domain. A transaction releases its slot
// only at capture_done / job_done / display_end, never when a command arrives.
module frame_store_control #(
 parameter RAW_SLOTS=41, RESULT_SLOTS=3, PLAY_PERIOD=3333333
)(
 input clk,rst_n,enabled,
 input command_valid,input [3:0] command,output reg command_ack,
 input [31:0] config_epoch,
 input capture_start,input [31:0] capture_id,
 output reg capture_accept,output reg [5:0] capture_slot,
 input capture_done,capture_ok,
 output reg job_start,output reg [5:0] job_source,
 output reg [1:0] job_result,output reg [31:0] job_id,job_epoch,
 input job_done,job_ok,
 input display_start,display_end,
 output reg display_valid,output reg [1:0] display_slot,
 output reg display_reference_valid,output reg [5:0] display_reference_slot,
 output reg [17:0] display_saved_slots,output reg [2:0] display_saved_valid,
 output [5:0] display_source,
 output [31:0] display_id,display_epoch,output reg [31:0] display_reference_id,
 // The HDMI consumer acknowledges the result it actually starts displaying.
 input shown_valid,input [1:0] shown_slot,
 output reg [2:0] mode,output reg [5:0] recorded,
 output reg [4:0] playback_index,
 output reg reference_valid,output reg [5:0] reference_slot,
 output reg [31:0] reference_id,
 output reg [31:0] shown_id,shown_epoch,
 output reg [31:0] ignored_frames,skipped_frames,failed_frames,
 output reg [31:0] generation,
 output reg [3:0] command_error
);
 localparam LIVE=0,FROZEN=1,RECORD=2,PLAY=3,PAUSE=4,STEP=5;
 localparam LIVE_CMD=1,FREEZE_CMD=2,STEP_CMD=3,RECORD_CMD=4,
            PLAY_CMD=5,PAUSE_CMD=6,NEXT_CMD=7,REFERENCE_CMD=8,CLEAR_REF_CMD=9,FIRST_PAUSE_CMD=10,RESUME_CMD=11;
 reg [17:0] saved_slots;reg [2:0] saved_valid;reg [1:0] save_next;
 reg [5:0] clip[0:31];
 reg [31:0] clip_id[0:31];
 reg [5:0] result_source[0:RESULT_SLOTS-1];
 reg [31:0] result_id[0:RESULT_SLOTS-1];
 reg [31:0] result_epoch[0:RESULT_SLOTS-1];
 reg [RESULT_SLOTS-1:0] result_valid;
 reg capture_busy,capture_record,job_busy,display_busy;
 reg [31:0] incoming_id,job_generation,capture_generation;
 reg pending_valid;reg [5:0] pending_source;
 reg [31:0] pending_id;
 reg freeze_valid;reg [5:0] freeze_source;
 reg [31:0] freeze_id;
 reg ready_valid;reg [1:0] ready_slot;
 reg actual_valid;reg [1:0] actual_slot;
 reg [31:0] last_epoch;
 reg reprocess;
 reg [21:0] play_ticks;
 reg [RAW_SLOTS-1:0] held;
 reg [RAW_SLOTS-1:0] recorded_slots;
 integer i,raw_free,result_free;
 reg [4:0] actual_clip_index,actual_clip_reverse;
 reg actual_clip_found;
 integer c;
 always @* begin
  actual_clip_reverse=0;actual_clip_found=0;
  for(c=0;c<32;c=c+1)
   if(actual_valid && c<recorded && clip[c]==result_source[actual_slot]) begin
    actual_clip_reverse=c;actual_clip_found=1;
   end
  // Resolve the slot first, then reverse chronological order with one subtractor.
  actual_clip_index=actual_clip_found ? recorded-1'b1-actual_clip_reverse : playback_index;
 end
 wire [4:0] next_index=actual_clip_index==recorded-1 ? 0 : actual_clip_index+1'b1;
 wire [4:0] clip_read_index=command_valid && (command==NEXT_CMD || command==RESUME_CMD) ? next_index :
                            command_valid && command==FIRST_PAUSE_CMD ? 5'd0 : playback_index;
 wire [4:0] clip_id_index=recorded-1'b1-clip_read_index;
 wire [31:0] clip_read_id=clip_id[clip_id_index];
 wire [5:0] clip_read_slot=clip[clip_id_index];
 assign display_source=result_source[display_slot];
 assign display_id=display_valid ? result_id[display_slot] : 0;
 assign display_epoch=display_valid ? result_epoch[display_slot] : 0;
 always @* begin
  held=recorded_slots;
  for(i=0;i<RESULT_SLOTS;i=i+1)
   if(result_valid[i]) held[result_source[i]]=1;
  for(i=0;i<3;i=i+1) begin
   if(saved_valid[i]) held[saved_slots[i*6 +:6]]=1;
   if(display_saved_valid[i]) held[display_saved_slots[i*6 +:6]]=1;
  end
  if(freeze_valid) held[freeze_source]=1;
  if(capture_busy) held[capture_slot]=1;
  if(job_busy) held[job_source]=1;
  if(pending_valid) held[pending_source]=1;
  raw_free=-1;
  for(i=RAW_SLOTS-1;i>=0;i=i-1) if(!held[i]) raw_free=i;
  result_free=-1;
  for(i=RESULT_SLOTS-1;i>=0;i=i-1)
   if(!(actual_valid && actual_slot==i) && !(display_valid && display_slot==i) &&
      !(ready_valid && ready_slot==i) && !(job_busy && job_result==i)) result_free=i;
 end
 always @(posedge clk) begin
  if(!rst_n) begin
   mode<=LIVE;recorded<=0;recorded_slots<=0;playback_index<=0;generation<=0;
   capture_busy<=0;capture_accept<=0;capture_slot<=0;capture_record<=0;incoming_id<=0;capture_generation<=0;
   job_busy<=0;job_start<=0;job_source<=0;job_result<=0;job_id<=0;job_epoch<=0;job_generation<=0;
   display_busy<=0;display_valid<=0;display_slot<=0;actual_valid<=0;actual_slot<=0;
   saved_slots<=0;saved_valid<=0;save_next<=0;display_saved_slots<=0;display_saved_valid<=0;
   reference_valid<=0;reference_slot<=0;freeze_valid<=0;freeze_source<=0;
   display_reference_valid<=0;display_reference_slot<=0;
   display_reference_id<=0;reference_id<=0;pending_id<=0;freeze_id<=0;
   ready_valid<=0;ready_slot<=0;pending_valid<=0;pending_source<=0;
   result_valid<=0;reprocess<=0;last_epoch<=0;shown_id<=0;shown_epoch<=0;
   ignored_frames<=0;skipped_frames<=0;failed_frames<=0;command_ack<=0;command_error<=0;
   play_ticks<=PLAY_PERIOD;
  end else begin
   capture_accept<=0;job_start<=0;command_ack<=0;
   if(play_ticks<PLAY_PERIOD) play_ticks<=play_ticks+1'b1;
   if(shown_valid && result_valid[shown_slot]) begin
    actual_valid<=1;actual_slot<=shown_slot;
    shown_id<=result_id[shown_slot];shown_epoch<=result_epoch[shown_slot];
   end
   if(display_end) display_busy<=0;
   if(display_start && !display_busy) begin
    display_saved_slots<=saved_slots;display_saved_valid<=saved_valid;
    display_reference_valid<=reference_valid;display_reference_slot<=reference_slot;
    display_reference_id<=reference_id;
    if(command_valid && (command==FREEZE_CMD || command==PAUSE_CMD) && actual_valid) begin
     display_slot<=actual_slot;display_valid<=1;display_busy<=1;
    end else if(ready_valid) begin
     display_slot<=ready_slot;display_valid<=1;display_busy<=1;ready_valid<=0;
    end else if(actual_valid) begin
     display_slot<=actual_slot;display_valid<=1;display_busy<=1;
    end else display_valid<=0;
   end
   // Retain only frames that are published, being read, or actually visible.
   for(i=0;i<RESULT_SLOTS;i=i+1)
    if(result_valid[i] && !(actual_valid && actual_slot==i) &&
       !(display_valid && display_slot==i) && !(ready_valid && ready_slot==i)) result_valid[i]<=0;
   if(config_epoch!=last_epoch) begin
    last_epoch<=config_epoch;reprocess<=1;
   end
   if(capture_start && enabled && !capture_busy) begin
    if(mode==LIVE || mode==RECORD || mode==STEP) begin
     if(raw_free>=0) begin
      capture_busy<=1;capture_accept<=1;capture_slot<=raw_free;
      incoming_id<=capture_id;capture_record<=mode==RECORD;capture_generation<=generation;
     end else skipped_frames<=skipped_frames+1'b1;
    end else ignored_frames<=ignored_frames+1'b1;
   end
   if(capture_done && capture_busy) begin
    capture_busy<=0;
    if(capture_ok) begin
     if(capture_record && mode==RECORD && recorded<32 && capture_generation==generation) begin
      clip[0]<=capture_slot;recorded<=recorded+1'b1;
      // Recorded IDs arrive in order; a shift register avoids a 32-way write mux.
      clip_id[0]<=incoming_id;
      for(integer c=1;c<32;c=c+1) begin clip_id[c]<=clip_id[c-1];clip[c]<=clip[c-1];end
      recorded_slots[capture_slot]<=1;
      if(recorded==31) begin
       mode<=PAUSE;playback_index<=0;pending_valid<=0;reprocess<=1;
       freeze_source<=clip[30];freeze_id<=clip_id[30];freeze_valid<=1;generation<=generation+1'b1;
      end
     end
     if(capture_generation==generation && (mode==LIVE || (mode==RECORD && recorded!=31))) begin
      if(pending_valid) skipped_frames<=skipped_frames+1'b1;
      pending_source<=capture_slot;pending_id<=incoming_id;pending_valid<=1;
     end
     if(mode==STEP && capture_generation==generation) begin
      freeze_source<=capture_slot;freeze_id<=incoming_id;freeze_valid<=1;mode<=FROZEN;reprocess<=1;
     end
    end else failed_frames<=failed_frames+1'b1;
   end
   if(job_done && job_busy) begin
    job_busy<=0;
    if(job_ok && job_generation==generation && job_epoch==config_epoch) begin
     result_source[job_result]<=job_source;result_epoch[job_result]<=job_epoch;
     result_id[job_result]<=job_id;
     result_valid[job_result]<=1;ready_slot<=job_result;ready_valid<=1;
     if(mode==PLAY) begin
      playback_index<=playback_index==recorded-1 ? 0 : playback_index+1'b1;
      reprocess<=1;
     end
    end else if(!job_ok) failed_frames<=failed_frames+1'b1;
   end
   // One shared algorithm job at a time. Commands supersede publication,
   // while the outstanding read and write still drain normally.
   if(enabled && !job_busy && (!ready_valid || mode==LIVE || mode==RECORD) && result_free>=0 && !command_valid && !capture_done) begin
    if(((mode==LIVE || mode==RECORD) && pending_valid) ||
       ((mode==FROZEN || mode==PAUSE || (mode==PLAY && play_ticks==PLAY_PERIOD)) && reprocess &&
        (mode==PLAY ? recorded!=0 : freeze_valid))) begin
     job_source<=mode==LIVE || mode==RECORD ? pending_source :
                  mode==PLAY ? clip_read_slot : freeze_source;
     job_id<=mode==LIVE || mode==RECORD ? pending_id : mode==PLAY ? clip_read_id : freeze_id;
     job_epoch<=config_epoch;job_result<=result_free;result_valid[result_free]<=0;
     job_generation<=generation;job_start<=1;job_busy<=1;reprocess<=0;
     if(mode==PLAY) play_ticks<=0;
     if(mode==LIVE || mode==RECORD) pending_valid<=0;
    end
   end
   if(command_valid) begin
    command_ack<=1;command_error<=0;
    case(command)
     LIVE_CMD: begin mode<=LIVE;freeze_valid<=0;pending_valid<=0;ready_valid<=0;generation<=generation+1'b1;end
     FREEZE_CMD: if(actual_valid) begin
      mode<=FROZEN;freeze_valid<=1;freeze_source<=result_source[actual_slot];
      freeze_id<=result_id[actual_slot];
      pending_valid<=0;ready_valid<=0;generation<=generation+1'b1;reprocess<=0;
     end else command_error<=1;
     STEP_CMD: begin mode<=STEP;pending_valid<=0;ready_valid<=0;generation<=generation+1'b1;end
     RECORD_CMD: begin
      mode<=RECORD;recorded<=0;recorded_slots<=0;freeze_valid<=0;pending_valid<=0;ready_valid<=0;
      generation<=generation+1'b1;
     end
     PLAY_CMD: if(recorded!=0) begin
      mode<=PLAY;playback_index<=0;pending_valid<=0;ready_valid<=0;generation<=generation+1'b1;reprocess<=1;
     end else command_error<=2;
     RESUME_CMD: if(recorded!=0) begin
      mode<=PLAY;playback_index<=next_index;pending_valid<=0;ready_valid<=0;
      generation<=generation+1'b1;reprocess<=1;play_ticks<=PLAY_PERIOD;
     end else command_error<=2;
     FIRST_PAUSE_CMD: if(recorded!=0) begin
      mode<=PAUSE;playback_index<=0;freeze_source<=clip_read_slot;freeze_id<=clip_read_id;freeze_valid<=1;
      pending_valid<=0;ready_valid<=0;generation<=generation+1'b1;reprocess<=1;
     end else command_error<=2;
     PAUSE_CMD: if(actual_valid) begin
      mode<=PAUSE;freeze_valid<=1;freeze_source<=result_source[actual_slot];
      freeze_id<=result_id[actual_slot];
      ready_valid<=0;generation<=generation+1'b1;reprocess<=0;
      playback_index<=actual_clip_index;
     end else command_error<=1;
     NEXT_CMD: if(recorded!=0) begin
      mode<=PAUSE;playback_index<=next_index;
      freeze_source<=clip_read_slot;freeze_id<=clip_read_id;freeze_valid<=1;
      ready_valid<=0;generation<=generation+1'b1;reprocess<=1;
     end else command_error<=2;
     REFERENCE_CMD: if(actual_valid) begin
      saved_slots[save_next*6 +:6]<=result_source[actual_slot];saved_valid[save_next]<=1;save_next<=save_next==2 ? 0 : save_next+1'b1;
      reference_slot<=result_source[actual_slot];reference_id<=result_id[actual_slot];reference_valid<=1;
     end else command_error<=1;
     CLEAR_REF_CMD: begin reference_valid<=0;saved_valid<=0;save_next<=0;end
     default: command_error<=3;
    endcase
   end
  end
 end
endmodule
