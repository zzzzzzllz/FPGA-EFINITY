`timescale 1ns/1ps
module tb;
    parameter REAL_FRAME=0;
    parameter COLOR_ENABLE=1;
    reg [127:0] memory[0:172799];
    reg [23:0] expected[0:14335];
    reg [31:0] corners[0:7];
    reg [7:0] threshold[0:0];
    reg [31:0] frame_id=36,source_time=1234;
    reg [133:0] expected_identity;
    integer color_seen=0,stall_ticks=0,stall_total=0;
    reg force_stall=0,was_stalled=0;
    reg [38:0] held_color;
    wire color_valid,color_ready,color_last;
    wire [23:0] color_rgb;wire [13:0] color_address;
    assign color_ready=!force_stall && (!REAL_FRAME || stall_ticks>=4);
    reg clk=0;always #5 clk=~clk;
    reg rst=1,cancel_valid=0;reg [1:0] response_error=0;
    reg job_valid=0;wire job_ready,hold_valid,held;wire [5:0] held_slot;
    wire [133:0] identity,hold_identity;
    wire cmd_valid,cmd_ready;wire [10:0] cmd_x;wire [9:0] cmd_y;
    wire [8:0] cmd_width;wire [6:0] cmd_height;
    wire pixel_valid,pixel_ready;wire [23:0] rgb0,rgb1;wire [1:0] keep;
    wire [10:0] pixel_x;wire [9:0] pixel_y;wire line_last,cmd_last;
    wire cmd_done_valid,cmd_done_ready;
    reg finish_valid=0;wire finish_ready,abort_valid;wire [3:0] abort_status;
    wire burst_valid,burst_ready;wire [31:0] burst_addr;wire [7:0] burst_len;
    wire rsp_valid,rsp_ready,rsp_last;wire [127:0] rsp_data;
    wire recover_req;reg recover_ack=0;wire release_valid,job_done_valid;wire [3:0] status;
    frame_reader reader(.clk(clk),.rst(rst),.job_valid(job_valid),.job_ready(job_ready),
        .job_slot(6'd0),.job_frame_id(frame_id),.job_epoch(32'd1),.job_generation(32'd2),.job_source_time_ms(source_time),
        .hold_valid(hold_valid),.hold_ready(1'b1),.hold_granted(1'b1),.hold_identity(hold_identity),
        .held(held),.held_slot(held_slot),.identity(identity),.config_epoch(32'd1),.config_generation(32'd2),
        .cmd_valid(cmd_valid),.cmd_ready(cmd_ready),.full_scan(1'b0),.cmd_x(cmd_x),.cmd_y(cmd_y),.cmd_width(cmd_width),.cmd_height(cmd_height),
        .pixel_valid(pixel_valid),.pixel_ready(pixel_ready),.rgb0(rgb0),.rgb1(rgb1),.keep(keep),.pixel_x(pixel_x),.pixel_y(pixel_y),.line_last(line_last),.cmd_last(cmd_last),
        .cmd_done_valid(cmd_done_valid),.cmd_done_ready(cmd_done_ready),.finish_valid(finish_valid),.finish_ready(finish_ready),.finish_status(4'd0),
        .cancel_valid(cancel_valid),.cancel_status(4'd4),.abort_valid(abort_valid),.abort_status(abort_status),
        .burst_valid(burst_valid),.burst_ready(burst_ready),.burst_addr(burst_addr),.burst_len(burst_len),
        .rsp_valid(rsp_valid),.rsp_ready(rsp_ready),.rsp_data(rsp_data),.rsp_last(rsp_last),.rsp_resp(response_error),
        .recover_req(recover_req),.recover_ack(recover_ack),.release_valid(release_valid),.release_ready(1'b1),
        .job_done_valid(job_done_valid),.job_done_ready(job_done_ready),.status(status));
    reg start_valid=0,corner_valid=0,result_ready=0,job_done_ready=0;
    reg signed [31:0] corner_data=0;
    wire start_ready,corner_ready,result_valid,gray_write;
    wire [13:0] gray_address;wire [7:0] gray_data;
    wire [4:0] result_threshold;wire [3:0] result_status;
    reg inject_bad=0;
    `ifdef LEGACY_RTL
    perspective_quad roi(
`else
    perspective_quad #(.COLOR_OUTPUT(COLOR_ENABLE)) roi(
`endif
        .clk(clk),.rst(rst),.abort(abort_valid),.keep(inject_bad ? 2'b00 : keep),.*);
    integer tick=0,base_word=0,bus_index=0,bus_length=0,quiet=0,holds=0,releases=0,jobs=0,seen=0,k,watch=0;
    reg bus_active=0,bus_pause=0;reg check_gray=0;
    assign burst_ready=!bus_active && !recover_req && tick%5!=0;
    assign rsp_valid=bus_active && !bus_pause && tick%7!=0;
    assign rsp_last=bus_index==bus_length;
    function [7:0] byte_at(input integer a);
      integer pix,x,y;begin pix=a/3;x=pix%1280;y=pix/1280;
      case(a%3) 0:byte_at=x;1:byte_at=y;2:byte_at=x+y;endcase end
    endfunction
    function [127:0] word_at(input integer a);
      integer j;begin if(REAL_FRAME)word_at=memory[a/16];else for(j=0;j<16;j=j+1)word_at[127-j*8-:8]=byte_at(a+j);end
    endfunction
    function [7:0] gray_at(input integer p);
      integer x,y;begin x=p%224;y=p/224;if(REAL_FRAME)gray_at=(77*expected[p][23:16]+150*expected[p][15:8]+29*expected[p][7:0])>>8;else gray_at=(77*x+150*y+29*((x+y)%256))>>8;end
    endfunction
    assign rsp_data=word_at((base_word+bus_index)*16);
    always @(posedge clk)begin
      tick<=tick+1;
      if(rst)begin bus_active<=0;recover_ack<=0;quiet<=0;end else begin
        if(hold_valid && job_ready)holds=holds+1;
        if(release_valid)begin if(bus_active || !held)$fatal(1,"unsafe release");releases=releases+1;end
        if(held && identity!==expected_identity)$fatal(1,"identity mismatch");
        if(burst_valid && burst_ready)begin
          if(!held)$fatal(1,"unheld command");base_word=burst_addr/16;bus_length=burst_len;bus_index<=0;bus_active<=1;
        end
        if(rsp_valid)begin if(!rsp_ready)$fatal(1,"response stalled");if(rsp_last)bus_active<=0;else bus_index<=bus_index+1;end
        // The responder drains the complete outstanding burst before isolation acknowledgement.
        if(recover_req && !bus_active && !rsp_valid)begin quiet<=quiet+1;recover_ack<=quiet>=3;end
        else begin quiet<=0;recover_ack<=0;end
        if(COLOR_ENABLE && gray_write !== (color_valid && color_ready))$fatal(1,"gray/color handshake diverged");
        if(COLOR_ENABLE && was_stalled && !abort_valid && ( !color_valid || {color_last,color_address,color_rgb}!==held_color))$fatal(1,"stalled color changed");
        was_stalled=color_valid && !color_ready && !abort_valid;
        held_color={color_last,color_address,color_rgb};
        if(COLOR_ENABLE && color_valid && !color_ready)begin stall_ticks<=stall_ticks+1;stall_total=stall_total+1;end
        if(COLOR_ENABLE && color_valid && color_ready)begin
          stall_ticks<=0;
          if(color_address!==color_seen || color_last!==(color_seen==14335))$fatal(1,"color framing");
          if(REAL_FRAME && color_rgb!==expected[color_seen])$fatal(1,"frozen RGB mismatch p=%0d got=%h exp=%h",color_seen,color_rgb,expected[color_seen]);
          if(!REAL_FRAME && color_rgb!=={8'(color_seen%224),8'(color_seen/224),8'((color_seen%224+color_seen/224)%256)})$fatal(1,"synthetic RGB mismatch");
          color_seen=color_seen+1;
        end
        if(gray_write)begin
          if(!held || abort_valid || result_valid)$fatal(1,"unsafe gray write");
          if(check_gray && (gray_address!==seen || gray_data!==gray_at(seen)))$fatal(1,"gray p=%0d got=%0d expected=%0d",seen,gray_data,gray_at(seen));
          seen=seen+1;
        end
      end
    end
    task begin_job;begin
      @(negedge clk);while(!job_ready)@(negedge clk);
      frame_id=36+jobs;source_time=1234+jobs;expected_identity={6'd0,frame_id,32'd1,32'd2,source_time};
      job_valid=1;@(negedge clk);job_valid=0;frame_id=32'hdeadbeef;source_time=32'hbadbeef;seen=0;color_seen=0;stall_ticks=0;was_stalled=0;check_gray=1;
      if(!start_ready)$fatal(1,"roi not ready after reader acquired");start_valid=1;
      @(negedge clk);start_valid=0;
    end endtask
    task coefficients(input integer mode);begin
      for(k=0;k<8;k=k+1)begin
        if(!corner_ready)$fatal(1,"corner not ready");corner_valid=1;
        case(k) 0,1,3,6:corner_data=0;2,4:corner_data=223*65536;5,7:corner_data=63*65536;endcase
        if(REAL_FRAME && mode==0)corner_data=corners[k];
        if(mode==1)corner_data=0;
        if(mode==2 && k==0)corner_data=134217729;
        if(mode==3)begin
          case(k) 0,1,3,6:corner_data=0;2,4,7:corner_data=1000*65536;5:corner_data=1;endcase
        end
        @(negedge clk);
      end
      corner_valid=0;
    end endtask
    task collect_job(input integer expected_status);begin
      watch=0;while(!job_done_valid)begin @(negedge clk);watch=watch+1;if(watch>2000)$fatal(1,"reader cleanup timeout state=%0d",reader.state);end
      if(status!==expected_status || held || bus_active || holds!=releases)$fatal(1,"cleanup status=%0d exp=%0d holds=%0d releases=%0d",status,expected_status,holds,releases);
      repeat(3)@(negedge clk);job_done_ready=1;@(negedge clk);job_done_ready=0;cancel_valid=0;response_error=0;inject_bad=0;jobs=jobs+1;
      @(negedge clk);
    end endtask
    task finish_job;begin
      result_ready=1;@(negedge clk);result_ready=0;
      finish_valid=1;while(!finish_ready)@(negedge clk);@(negedge clk);finish_valid=0;collect_job(0);
    end endtask
    task normal;begin
      begin_job();coefficients(0);watch=0;
      while(!result_valid)begin @(negedge clk);watch=watch+1;if(watch>2000000)$fatal(1,"normal timeout");end
      if(result_status!=0 || result_threshold!=(REAL_FRAME ? threshold[0][4:0] : 5'd7) || seen!=14336 || (COLOR_ENABLE && color_seen!=14336))$fatal(1,"bad normal result status=%0d th=%0d seen=%0d",result_status,result_threshold,seen);
      repeat(7)begin @(negedge clk);if(!result_valid || start_ready || gray_write || result_status!=0 || result_threshold!=(REAL_FRAME ? threshold[0][4:0] : 5'd7))$fatal(1,"result not held");end
      finish_job();$display("normal recovered jobs=%0d",jobs);
    end endtask
    task cancel_job;begin
      cancel_valid=1;@(negedge clk);repeat(5)@(negedge clk);bus_pause=0;collect_job(4);
    end endtask
    initial begin
      if(REAL_FRAME)begin
        $readmemh("frame.mem",memory);$readmemh("pixels.mem",expected);$readmemh("corners.mem",corners);$readmemh("threshold.mem",threshold);
      end
      repeat(3)@(negedge clk);rst=0;normal();
      if(REAL_FRAME)begin
        if(COLOR_ENABLE && stall_total<14336*4)$fatal(1,"missing color stalls");
        $display("PASS frozen development RGB/legacy: 14336 pixels, RGB/BGR, gray/Otsu, stalls=%0d, hold=%0d release=%0d",stall_total,holds,releases);$finish;
      end
      begin_job();coefficients(1);while(!result_valid)@(negedge clk);
      if(result_status!=10 || seen!=0)$fatal(1,"degenerate status");repeat(5)@(negedge clk);finish_job();normal();
      begin_job();coefficients(2);while(!result_valid)@(negedge clk);
      if(result_status!=9 || seen!=0)$fatal(1,"bad corner status");finish_job();normal();
      begin_job();coefficients(3);while(!result_valid)@(negedge clk);
      if(result_status!=11 || seen!=0)$fatal(1,"matrix overflow status");finish_job();normal();
      begin_job();corner_valid=1;corner_data=0;@(negedge clk);corner_valid=0;cancel_job();
      begin_job();coefficients(0);while(roi.solver.state!=4)@(negedge clk);cancel_job();
      begin_job();coefficients(0);while(roi.solver.state!=7)@(negedge clk);cancel_job();
      begin_job();coefficients(0);while(roi.solver.state!=9)@(negedge clk);cancel_job();
      begin_job();coefficients(0);while(roi.roi.coords.state!=4)@(negedge clk);cancel_job();
      begin_job();coefficients(0);inject_bad=1;while(!result_valid)@(negedge clk);
      if(result_status!=7 || seen!=0)$fatal(1,"bad stream status");repeat(5)@(negedge clk);cancel_job();
      begin_job();coefficients(0);response_error=2;collect_job(9);
      begin_job();coefficients(0);bus_pause=1;while(!bus_active)@(negedge clk);cancel_job();normal();
      // Cancel while the first and the last RGB sample are held by the consumer.
      begin_job();coefficients(0);force_stall=1;while(!color_valid)@(negedge clk);repeat(9)@(negedge clk);cancel_job();force_stall=0;normal();
      begin_job();coefficients(0);while(color_seen<14335)@(negedge clk);force_stall=1;while(!color_valid)@(negedge clk);repeat(9)@(negedge clk);cancel_job();force_stall=0;normal();
      if(holds!=releases)$fatal(1,"leaked reference");
      $display("PASS COLOR QUAD lifecycle jobs=%0d holds=%0d releases=%0d",jobs,holds,releases);$finish;
    end
    initial begin #2000000000;$fatal(1,"global timeout reader=%0d roi_active=%0d",reader.state,roi.active);end
endmodule
