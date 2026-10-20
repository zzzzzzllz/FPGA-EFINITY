`timescale 1ns/1ps
`ifndef CHAR_DUT
`define CHAR_DUT char_linear
`endif
module tb_char_linear #(
    parameter WEIGHT_BITS=10,WEIGHT_FILE="w1-s10.bin",BIAS_FILE="b1.mem",
    parameter signed [31:0] PROVINCE_SCORE=-1351,PROVINCE_MARGIN=4245,
    parameter signed [31:0] ALNUM_SCORE=-20593,ALNUM_MARGIN=3556
);
    reg clk=0; always #5 clk=~clk;
    reg rst=1, start_valid=0, feature_valid=0, result_ready=0;
    reg [2:0] position=0;
    reg [5:0] feature_data=0;
    wire start_ready, feature_ready, result_valid, result_accept, result_error;
    wire [6:0] result_id,score_id;
    wire signed [31:0] result_score,result_margin,score_value;
    wire score_valid;
`ifdef MAPPED_NETLIST
    `CHAR_DUT dut(.*);
`else
    char_linear #(.WEIGHT_BITS(WEIGHT_BITS),.WEIGHT_FILE(WEIGHT_FILE),.BIAS_FILE(BIAS_FILE),
      .PROVINCE_SCORE(PROVINCE_SCORE),.PROVINCE_MARGIN(PROVINCE_MARGIN),
      .ALNUM_SCORE(ALNUM_SCORE),.ALNUM_MARGIN(ALNUM_MARGIN)) dut(.*);
`endif
    reg [5:0] inputs [0:131071];
    reg [31:0] scores [0:32767];
    reg [31:0] metadata [0:2047];
    integer count,vector_index=-1,score_count=0,cycle_count=0,i,j,seed=701;
    integer total_scores=0;
    reg [73:0] held_packet;
    reg tracing=0;
    integer last_latency=0;
`ifdef DEBUG_MAPPED
    always @(negedge clk) begin #0.1; $display("debug rst=%b start=%b pos=%b state=%b next=%b ce=%b n846=%b n1063=%b lut1923=%h in=%b",rst,start_valid,position,dut.state,dut.n1095,dut.ceg_net110,dut.n846,dut.n1063,dut.LUT__1923.LUTMASK,{dut.LUT__1923.I3_net,dut.LUT__1923.I2_net,dut.LUT__1923.I1_net,dut.LUT__1923.I0_net});end
`endif

    always @(posedge clk) if (score_valid && tracing) begin
        if (score_id !== score_count || score_value !== scores[vector_index*65+score_count])
            $fatal(1,"score mismatch vector=%0d class=%0d got=%0d expected=%0d",vector_index,score_id,score_value,$signed(scores[vector_index*65+score_count]));
        score_count=score_count+1;
        total_scores=total_scores+1;
    end

    task reset_core;
        begin
            @(negedge clk); rst=1; start_valid=0; feature_valid=0; result_ready=0; tracing=0;
            repeat(2) @(posedge clk);
            #1;if(result_valid || score_valid) $fatal(1,"reset left valid output");
            @(negedge clk);rst=0;
            #1;if(!start_ready) $fatal(1,"reset did not restore idle");
        end
    endtask

    task begin_request(input integer pos);
        begin
            @(negedge clk);
            if(!start_ready) $fatal(1,"not ready for start");
            position=pos;start_valid=1;
            @(posedge clk);#1;
            @(negedge clk);start_valid=0;
        end
    endtask

    task load_features(input integer idx,input integer length);
        integer n,random_value;
        begin
            n=0;
            while(n<length) begin
                @(negedge clk);
                random_value=$urandom(seed);
                feature_valid=(random_value & 3)!=0;
                feature_data=inputs[idx*320+n];
                if(!feature_ready) $fatal(1,"feature_ready dropped during loading");
                @(posedge clk);
                if(feature_valid && feature_ready) n=n+1;
                #1;
            end
            @(negedge clk);feature_valid=0;
        end
    endtask

    task run_vector(input integer idx);
        integer latency,hold_cycles;
        begin
            vector_index=idx; score_count=0; tracing=1;
            begin_request(metadata[idx*6]);
`ifndef MAPPED_NETLIST
            if(metadata[idx*6+5]) force dut.accumulator=32'sd0;
`endif
            load_features(idx,320);
            // The last input was accepted at the preceding rising edge.
            latency=0;
            start_valid=1;position=7;feature_valid=1;feature_data=63;
            while(!result_valid) begin
                @(posedge clk);#1;latency=latency+1;
                if(start_ready || feature_ready) $fatal(1,"busy accepted input");
                if(latency>42000) $fatal(1,"timeout");
            end
            if(latency!=41796 || score_count!=65) $fatal(1,"latency/score count %0d/%0d",latency,score_count);
            last_latency=latency;
            if(result_error || result_id!==metadata[idx*6+1][6:0] ||
               result_score!==metadata[idx*6+2] || result_margin!==metadata[idx*6+3] ||
               result_accept!==metadata[idx*6+4][0])
                $fatal(1,"result mismatch vector=%0d id=%0d score=%0d margin=%0d accept=%0d",idx,result_id,result_score,result_margin,result_accept);
            held_packet={result_error,result_accept,result_id,result_score,result_margin};
            hold_cycles=3+(idx%5);
            repeat(hold_cycles) begin
                @(posedge clk);#1;
                if(!result_valid || {result_error,result_accept,result_id,result_score,result_margin}!==held_packet)
                    $fatal(1,"result changed under backpressure");
            end
`ifndef MAPPED_NETLIST
            if(metadata[idx*6+5]) release dut.accumulator;
`endif
            @(negedge clk);start_valid=0;feature_valid=0;result_ready=1;
            @(posedge clk);#1;
            if(result_valid || !start_ready) $fatal(1,"result handshake did not finish");
            @(negedge clk);result_ready=0;tracing=0;
        end
    endtask

    initial begin
        if(!$value$plusargs("count=%d",count)) $fatal(1,"missing vector count");
        $readmemh("features.mem",inputs,0,count*320-1);
        $readmemh("scores.mem",scores,0,count*65-1);
        $readmemh("metadata.mem",metadata,0,count*6-1);
        reset_core();
        // Invalid position and out-of-range feature must fail explicitly.
        begin_request(7);#1;
        if(!result_valid || !result_error || result_accept) $fatal(1,"invalid position accepted valid=%b error=%b accept=%b",result_valid,result_error,result_accept);
        reset_core();begin_request(0);
        feature_valid=1;feature_data=33;@(posedge clk);#1;
        if(!result_valid || !result_error || result_accept) $fatal(1,"invalid feature accepted");
        reset_core();
        // Reset at a partial load and while a MAC is active; no stale RAM reuse.
        begin_request(0);load_features(0,17);reset_core();
        begin_request(0);load_features(0,320);repeat(55) @(posedge clk);reset_core();
        for(i=0;i<count;i=i+1) run_vector(i);
        // Reset while a result is held, then accept and execute a fresh request.
        vector_index=0;score_count=0;tracing=1;
        begin_request(metadata[0]);load_features(0,320);
        wait(result_valid);reset_core();run_vector(0);
        $display("PASS vectors=%0d compared_scores=%0d latency_cycles=%0d input_stalls=seed701 output_backpressure=yes reset_load_mac_hold=yes invalid_input=yes",count,total_scores,last_latency);
        $finish;
    end
    initial begin #1000000000; $fatal(1,"global timeout");end
endmodule
