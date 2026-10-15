// Four DDR pixels per word; two complete views share the same reduced row.
module compare_display #(
 parameter W=1280, H=720
)(
 input clk, rst_n, frame_period, compare_mode,
 input gray_mode,edge_mode,overlay_mode,
 input [293:0] frame_descriptor,
 input [127:0] in_data, input in_valid, output in_ready,
 output [31:0] out_data, output reg out_valid,
 input out_ready, output reg out_sof, out_eol,
 output reg [31:0] mixed_words, completed_frames,
 output reg [31:0] source_signature
);
 localparam HW=W/2, TOP=H/4;
 reg [127:0] word_data;
 reg [2:0] remaining;
 reg [10:0] ix, ox;
 reg [9:0] iy, oy;
 reg [1:0] rows_ready;
 reg [18:0] upper_row [0:HW-1];
 reg [16:0] reduced [0:2*HW-1];
 reg [18:0] upper_q;
 reg [16:0] reduced_q;
 reg [8:0] pair_filtered;
 reg [1:0] frame_flags;
 reg [3:0] frame_view;
 wire split_mode=frame_view[0] || frame_flags[1];
 wire overlay_active=frame_view[3] && !split_mode;
 reg pair_valid, pair_bank, pair_odd;
 reg [10:0] pair_x;
 reg [8:0] pair_sum;
 reg pair_edge;
 reg black_q, right_q;
 reg [31:0] full_q;
 reg [6:0] frame_tag;
 reg seen_word;
 reg [10:0] frame_threshold;
 reg [6:0] meta_q;
 reg [300:0] descriptor;
 wire window_row=oy>=TOP && oy<TOP+H/2;
 wire read_bank=(oy-TOP)&1;
 wire slot_ready=!out_valid || out_ready;
 wire pair_take=split_mode && remaining!=0 && iy<H && !rows_ready[iy[1]];
 wire emit=slot_ready && seen_word && oy<H && (split_mode ? (!window_row || rows_ready[read_bank]) : remaining!=0);
 wire [7:0] value=black_q ? 8'd0 : (right_q ? (frame_flags[1]?reduced_q[16:9]:{8{reduced_q[8]}}) : reduced_q[7:0]);
 assign out_data=split_mode ? {1'b0,meta_q,value,value,value} : {full_q[31],meta_q,full_q[23:0]};
 assign in_ready=!frame_period && iy<H && (remaining==0 ||
                 (split_mode ? (pair_take && remaining==2 && !(ix==HW-1 && iy==H-1)) :
                                  (emit && remaining==1 && !(ox==W-1 && oy==H-1))));
 function [7:0] luma;
  input [23:0] rgb;
  reg [15:0] sum;
  begin
   sum=16'd77*rgb[23:16]+16'd150*rgb[15:8]+16'd29*rgb[7:0]+16'd128;
   luma=sum[15:8];
  end
 endfunction
 wire [8:0] horizontal_sum={1'b0,(frame_flags[1]?word_data[119:112]:luma(word_data[119:96]))}+{1'b0,(frame_flags[1]?word_data[87:80]:luma(word_data[87:64]))};
 wire [10:0] block_sum={2'b0,pair_sum}+{2'b0,upper_q[8:0]}+11'd2;
 wire [9:0] filtered_sum={1'b0,pair_filtered}+{1'b0,upper_q[18:10]}+10'd2;
 wire [7:0] full_y=luma(word_data[119:96]);
 wire [23:0] full_rgb=overlay_active ? (word_data[127]?24'hff0000:word_data[119:96]) : frame_view[2]?{24{word_data[127]}}:(frame_view[1]?{full_y,full_y,full_y}:word_data[119:96]);
 always @(posedge clk) begin
  if(!rst_n) begin mixed_words<=0; completed_frames<=0; source_signature<=0; end
  else begin
   if(in_valid && in_ready) begin
    if(!seen_word) source_signature<=in_data[127:96];
    if((seen_word && in_data[126:120]!=frame_tag) ||
       (seen_word && (in_data[94:88]!=in_data[126:120] || in_data[62:56]!=in_data[126:120])) ||
       in_data[30:24]!=in_data[126:120]) mixed_words<=mixed_words+1'b1;
   end
   if(out_valid && out_ready && out_eol && oy==H) completed_frames<=completed_frames+1'b1;
  end
 end
 always @(posedge clk) begin
  if(!rst_n || frame_period) begin
   remaining<=0; ix<=0; iy<=0; ox<=0; oy<=0; rows_ready<=0;
   out_valid<=0; out_sof<=0; out_eol<=0;
   pair_valid<=0; seen_word<=0; frame_tag<=0;
   frame_view<=0;frame_flags<=0;frame_threshold<=32;meta_q<=0;descriptor<=0;
   black_q<=1; right_q<=0; full_q<=0;
  end else begin
   pair_valid<=pair_take;
   if(pair_take) begin
    upper_q<=upper_row[ix];
    pair_filtered<={1'b0,word_data[111:104]}+{1'b0,word_data[79:72]};pair_sum<=horizontal_sum; pair_edge<=word_data[127] | word_data[95];
    pair_x<=ix; pair_odd<=iy[0]; pair_bank<=iy[1];
    word_data<=word_data<<64; remaining<=remaining-2;
    if(ix==HW-1) begin ix<=0; iy<=iy+1'b1; end
    else ix<=ix+1'b1;
   end
   if(pair_valid) begin
    if(!pair_odd) upper_row[pair_x]<={pair_filtered,pair_edge,pair_sum};
    else begin
     reduced[pair_bank*HW+pair_x]<={filtered_sum[9:2],pair_edge|upper_q[9],block_sum[9:2]};
     if(pair_x==HW-1) rows_ready[pair_bank]<=1;
    end
   end
   if(slot_ready) begin
    out_valid<=emit;
    if(emit) begin
     if(oy==0 && ox>=2 && ox<=44) descriptor<=descriptor>>7;
     meta_q<=oy==0 && ox==0 ? frame_threshold[6:0] :
             (oy==0 && ox==1 ? {overlay_active,frame_flags,frame_threshold[10:7]} :
              (oy==0 && ox>=2 && ox<=44 ? descriptor[6:0] : 7'd0));
     out_sof<=ox==0 && oy==0; out_eol<=ox==W-1;
     if(split_mode) begin
      black_q<=!window_row; right_q<=ox>=HW;
      reduced_q<=reduced[read_bank*HW+(ox>=HW ? ox-HW : ox)];
      if(window_row && ox==W-1) rows_ready[read_bank]<=0;
     end else begin
      full_q<={word_data[127:120],full_rgb};
      word_data<=word_data<<32; remaining<=remaining-1'b1;
      if(ox==W-1) iy<=iy+1'b1;
     end
     if(ox==W-1) begin ox<=0; oy<=oy+1'b1; end
     else ox<=ox+1'b1;
    end
   end
   if(in_valid && in_ready) begin
    word_data<=in_data; remaining<=4;
    if(!seen_word) begin
     // Latch requests with the first DDR word; they cannot change a frame in flight.
     frame_view<={overlay_mode,edge_mode,gray_mode,compare_mode};
     descriptor<={1'b0,overlay_mode,edge_mode,gray_mode,compare_mode,in_data[61],frame_descriptor[101],frame_descriptor};
     frame_flags<=in_data[61:60];frame_tag<=in_data[126:120];frame_threshold<={in_data[59:56],in_data[94:88]};
    end
    seen_word<=1;
   end
  end
 end
endmodule
