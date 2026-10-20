`timescale 1ns/1ps
module tb_char_preprocess;
 reg clk=0,rst=1;
 always #5 clk=~clk;
 reg start_valid=0,pixel_valid=0,pixel_data=0,pixel_last=0,done_ready=0;
 wire start_ready,pixel_ready,norm_valid,norm_data,feature_valid,done_valid;
 reg [8:0] width=0;reg [6:0] height=0;
 wire [9:0] norm_index;wire [8:0] feature_index;wire [5:0] feature_data;wire [2:0] error;
 integer cycle=0,started=0,done_cycles=0,norm_count=0,feature_count=0,score_count=0;
 integer stalls=0,case_id,w,h,n,expected_error,last_flag,position,id,score,margin,accepted;
 integer fd,fields,j,completed=0,phase;
 reg done_seen=0;
 reg raw[0:30719],expected_norm[0:1023];reg [5:0] expected_features[0:319];
 reg signed [31:0] expected_scores[0:64];
 string filename;
 wire norm_ready=!stalls || cycle%7!=0;
 wire feature_gate=!stalls || cycle%5!=0;
 wire feature_ready;
 char_preprocess dut(.*);
`ifdef END_TO_END
 wire char_start_ready,char_feature_ready,char_result_valid,char_accept,char_error,char_score_valid;
 wire [6:0] char_id,char_score_id;wire signed [31:0] char_score,char_margin,char_score_value;
 reg char_result_ready=0;
 char_linear classifier(.clk(clk),.rst(rst),
  .start_valid(feature_valid && feature_index==0 && char_start_ready),.start_ready(char_start_ready),.position(3'(position)),
  .feature_valid(feature_valid && feature_gate),.feature_ready(char_feature_ready),.feature_data(feature_data),
  .result_valid(char_result_valid),.result_ready(char_result_ready),.result_id(char_id),.result_score(char_score),
  .result_margin(char_margin),.result_accept(char_accept),.result_error(char_error),
  .score_valid(char_score_valid),.score_id(char_score_id),.score_value(char_score_value));
 assign feature_ready=char_feature_ready && feature_gate;
 always @(posedge clk) if(!rst && char_score_valid) begin
  if(char_score_id!==7'(score_count) || char_score_value!==expected_scores[score_count])
   $fatal(1,"class score case=%0d class=%0d got=%0d expected=%0d",case_id,char_score_id,char_score_value,expected_scores[score_count]);
  score_count=score_count+1;
 end
`else
 assign feature_ready=feature_gate;
`endif
 reg [10:0] stalled_norm;reg [14:0] stalled_feature;reg had_norm_stall=0,had_feature_stall=0;
 always @(posedge clk) begin
  cycle<=cycle+1;
  if(rst) begin had_norm_stall<=0;had_feature_stall<=0;end
  else begin
   if(start_valid && start_ready) started=cycle;
   if(had_norm_stall && (!norm_valid || {norm_index,norm_data}!==stalled_norm)) $fatal(1,"normalization changed while stalled");
   if(had_feature_stall && (!feature_valid || {feature_index,feature_data}!==stalled_feature)) $fatal(1,"feature changed while stalled");
   had_norm_stall<=norm_valid && !norm_ready;stalled_norm<={norm_index,norm_data};
   had_feature_stall<=feature_valid && !feature_ready;stalled_feature<={feature_index,feature_data};
   if(norm_valid && norm_ready) begin
    if(expected_error!=0 || norm_index!==10'(norm_count) || norm_data!==expected_norm[norm_count])
     $fatal(1,"normalized pixel case=%0d index=%0d got=%b expected=%b",case_id,norm_index,norm_data,expected_norm[norm_count]);
    norm_count=norm_count+1;
   end
   if(feature_valid && feature_ready) begin
    if(expected_error!=0 || feature_index!==9'(feature_count) || feature_data!==expected_features[feature_count])
     $fatal(1,"feature case=%0d index=%0d got=%0d expected=%0d",case_id,feature_index,feature_data,expected_features[feature_count]);
    feature_count=feature_count+1;
   end
   if(done_valid && !done_seen) begin done_cycles=cycle-started;done_seen=1;end
  end
 end
 task load_case;
  begin
   norm_count=0;feature_count=0;score_count=0;done_seen=0;
   if(n>0) begin filename=$sformatf("vectors/raw-%0d.mem",case_id);$readmemb(filename,raw,0,n-1);end
   if(expected_error==0) begin
    filename=$sformatf("vectors/norm-%0d.mem",case_id);$readmemb(filename,expected_norm);
    filename=$sformatf("vectors/features-%0d.mem",case_id);$readmemh(filename,expected_features);
    filename=$sformatf("vectors/scores-%0d.mem",case_id);$readmemh(filename,expected_scores);
   end
  end
 endtask
 task launch;
  begin
   @(negedge clk);width=w;height=h;start_valid=1;
   @(posedge clk);while(!start_ready) @(posedge clk);
   @(negedge clk);start_valid=0;
  end
 endtask
 task feed(input integer count);
  begin
   for(j=0;j<count;j=j+1) begin
    @(negedge clk);pixel_valid=0;
    if(stalls && j%13==0) repeat(2) @(negedge clk);
    pixel_data=raw[j];pixel_last=last_flag && j==n-1;pixel_valid=1;
    @(posedge clk);while(!pixel_ready) @(posedge clk);
   end
   @(negedge clk);pixel_valid=0;pixel_last=0;
  end
 endtask
 task finish_case;
  integer total_cycles;
  begin
   wait(done_valid);@(negedge clk);
   if(error!==3'(expected_error)) $fatal(1,"status case=%0d got=%0d expected=%0d",case_id,error,expected_error);
   if(expected_error==0 && (norm_count!=1024 || feature_count!=320)) $fatal(1,"output counts");
   if(expected_error!=0 && (norm_count!=0 || feature_count!=0)) $fatal(1,"error emitted payload");
   repeat(3) @(negedge clk);
   if(!done_valid || error!==3'(expected_error)) $fatal(1,"done hold");
   total_cycles=done_cycles;
`ifdef END_TO_END
   if(expected_error==0) begin
    wait(char_result_valid);@(negedge clk);total_cycles=cycle-started;
    if(char_error || char_id!==7'(id) || char_score!==score || char_margin!==margin || char_accept!==1'(accepted) || score_count!=65)
     $fatal(1,"classifier result case=%0d id=%0d score=%0d margin=%0d accepted=%b",case_id,char_id,char_score,char_margin,char_accept);
    repeat(2) @(negedge clk);char_result_ready=1;
    @(negedge clk);char_result_ready=0;
   end
`endif
   $display("CASE %0d error=%0d preprocess_cycles=%0d total_cycles=%0d",case_id,error,done_cycles,total_cycles);
   done_ready=1;@(negedge clk);done_ready=0;
   completed=completed+1;
  end
 endtask
 task reset_now;
  begin
   @(negedge clk);rst=1;pixel_valid=0;start_valid=0;
   #1;if(norm_valid || feature_valid || done_valid || pixel_ready || start_ready) $fatal(1,"reset gates");
   repeat(2) @(negedge clk);rst=0;
   @(negedge clk);if(!start_ready || done_valid) $fatal(1,"reset recovery");
  end
 endtask
 initial begin
  stalls=$test$plusargs("STALLS");
  repeat(3) @(negedge clk);rst=0;
  fd=$fopen("cases.txt","r");if(fd==0)$fatal(1,"cases missing");
  fields=$fscanf(fd,"%d %d %d %d %d %d %d %d %d %d %d\n",case_id,w,h,n,expected_error,last_flag,position,id,score,margin,accepted);
  while(fields==11) begin
   load_case();launch();feed(n);finish_case();
   fields=$fscanf(fd,"%d %d %d %d %d %d %d %d %d %d %d\n",case_id,w,h,n,expected_error,last_flag,position,id,score,margin,accepted);
  end
  $fclose(fd);
  // Reset during raw load, normalization and feature output, then recover on case 0.
  for(phase=0;phase<3;phase=phase+1) begin
   fd=$fopen("cases.txt","r");
   fields=$fscanf(fd,"%d %d %d %d %d %d %d %d %d %d %d\n",case_id,w,h,n,expected_error,last_flag,position,id,score,margin,accepted);
   $fclose(fd);load_case();launch();
   if(phase==0) feed(5);
   else begin feed(n);if(phase==1) wait(norm_valid);else wait(feature_valid);end
   reset_now();load_case();launch();feed(n);finish_case();
  end
  $display("PASS %0d completed cases; pixels/features/scores exact; reset in 3 phases; stalls=%0d",completed,stalls);
  $finish;
 end
 initial begin #1000000000;$fatal(1,"timeout case=%0d state=%0d",case_id,dut.state);end
endmodule
