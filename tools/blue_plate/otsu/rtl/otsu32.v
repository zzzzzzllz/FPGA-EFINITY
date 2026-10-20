`timescale 1ns/1ps
// Exact 32-bin Otsu comparison for at most 320*96 pixels.
// Histogram bins arrive in order. All products share one shift/add datapath.
module otsu32 (
    input wire clk,
    input wire rst,
    input wire start_valid,
    output wire start_ready,
    input wire hist_valid,
    output wire hist_ready,
    input wire [14:0] hist_count,
    output wire result_valid,
    input wire result_ready,
    output reg [4:0] result_threshold,
    output reg [1:0] result_status
);
    // status: 0 usable, 1 empty, 2 exceeds 30720 pixels, 3 single occupied bin.
    localparam IDLE=0, LOAD=1, CHECK=2, ACCUMULATE=3,
               MULTIPLY=4, PRODUCT=5, ADVANCE=6, HOLD=7;
    reg [2:0] state;
    reg [4:0] index;
    reg [14:0] histogram [0:31];
    reg [19:0] pixel_count;
    reg [23:0] total_moment;
    reg [14:0] left_count;
    reg [19:0] left_moment;
    reg found;
    reg [4:0] best_threshold;
    reg [69:0] numerator, best_numerator;
    reg [29:0] denominator, best_denominator;
    reg [34:0] first_product;
    reg [99:0] first_cross;
    reg [99:0] mul_a, mul_b, mul_acc, mul_result;
    reg [2:0] phase;

    function [23:0] weighted_bin;
        input [14:0] count;
        input [4:0] bin;
        reg [23:0] value;
        begin
            value={9'd0,count};
            weighted_bin=(bin[0] ? value : 24'd0)
                       + (bin[1] ? value<<1 : 24'd0)
                       + (bin[2] ? value<<2 : 24'd0)
                       + (bin[3] ? value<<3 : 24'd0)
                       + (bin[4] ? value<<4 : 24'd0);
        end
    endfunction

    wire [15:0] next_left_count={1'b0,left_count}+{1'b0,histogram[index]};
    wire [23:0] next_left_moment={4'd0,left_moment}+weighted_bin(histogram[index],index);
    wire [34:0] absolute_difference=(first_product>=mul_result[34:0]) ?
                                    first_product-mul_result[34:0] : mul_result[34:0]-first_product;
    wire [99:0] mul_next=mul_acc+(mul_b[0] ? mul_a : 100'd0);

    assign start_ready=state==IDLE && !rst;
    assign hist_ready=state==LOAD && !rst;
    assign result_valid=state==HOLD && !rst;

    task launch_multiply;
        input [99:0] a;
        input [99:0] b;
        input [2:0] next_phase;
        begin
            mul_a<=a;mul_b<=b;mul_acc<=0;
            phase<=next_phase;state<=MULTIPLY;
        end
    endtask

    always @(posedge clk) begin
        if (rst) begin
            state<=IDLE;
            result_threshold<=0;result_status<=0;
        end else begin
            case (state)
                IDLE: if (start_valid) begin
                    index<=0;pixel_count<=0;total_moment<=0;
                    result_threshold<=0;result_status<=0;
                    state<=LOAD;
                end
                LOAD: if (hist_valid) begin
                    histogram[index]<=hist_count;
                    pixel_count<=pixel_count+{5'd0,hist_count};
                    total_moment<=total_moment+weighted_bin(hist_count,index);
                    if (index==31) state<=CHECK;
                    else index<=index+1'b1;
                end
                CHECK: begin
                    if (pixel_count==0) begin result_status<=1;state<=HOLD;end
                    else if (pixel_count>30720) begin result_status<=2;state<=HOLD;end
                    else begin
                        index<=0;left_count<=0;left_moment<=0;
                        found<=0;best_threshold<=0;
                        best_numerator<=0;best_denominator<=1;
                        state<=ACCUMULATE;
                    end
                end
                ACCUMULATE: begin
                    left_count<=next_left_count[14:0];
                    left_moment<=next_left_moment[19:0];
                    if (next_left_count==0 || next_left_count==pixel_count) state<=ADVANCE;
                    else launch_multiply({80'd0,next_left_moment[19:0]},
                                         {85'd0,pixel_count[14:0]},0);
                end
                MULTIPLY: begin
                    mul_acc<=mul_next;
                    if (mul_b<=1) begin mul_result<=mul_next;state<=PRODUCT;end
                    else begin mul_a<=mul_a<<1;mul_b<=mul_b>>1;end
                end
                PRODUCT: begin
                    case (phase)
                        0: begin
                            first_product<=mul_result[34:0];
                            launch_multiply({80'd0,total_moment[19:0]},
                                            {85'd0,left_count},1);
                        end
                        1: launch_multiply({65'd0,absolute_difference},
                                           {65'd0,absolute_difference},2);
                        2: begin
                            numerator<=mul_result[69:0];
                            launch_multiply({85'd0,left_count},
                                            {85'd0,(pixel_count[14:0]-left_count)},3);
                        end
                        3: begin
                            denominator<=mul_result[29:0];
                            if (!found) begin
                                found<=1;best_threshold<=index;
                                best_numerator<=numerator;best_denominator<=mul_result[29:0];
                                state<=ADVANCE;
                            end else launch_multiply({30'd0,numerator},
                                                     {70'd0,best_denominator},4);
                        end
                        4: begin
                            first_cross<=mul_result;
                            launch_multiply({30'd0,best_numerator},
                                            {70'd0,denominator},5);
                        end
                        5: begin
                            // Strict comparison retains the earliest threshold on a tie.
                            if (first_cross>mul_result) begin
                                best_numerator<=numerator;best_denominator<=denominator;
                                best_threshold<=index;
                            end
                            state<=ADVANCE;
                        end
                    endcase
                end
                ADVANCE: begin
                    if (index==30) begin
                        result_threshold<=best_threshold;
                        result_status<=found ? 2'd0 : 2'd3;
                        state<=HOLD;
                    end else begin index<=index+1'b1;state<=ACCUMULATE;end
                end
                HOLD: if (result_ready) state<=IDLE;
            endcase
        end
    end
endmodule
