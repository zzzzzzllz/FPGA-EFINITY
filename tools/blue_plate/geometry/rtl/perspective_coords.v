`timescale 1ns/1ps
// 224x64 destination scan -> signed source coordinates in units of 1/32 pixel.
// Nine row-major inverse homography coefficients are signed Q32 in 48 bits.
module perspective_coords (
    input wire clk,rst,abort,
    input wire start_valid,
    output wire start_ready,
    input wire coeff_valid,
    output wire coeff_ready,
    input wire signed [47:0] coeff_data,
    output wire sample_valid,
    input wire sample_ready,
    output reg signed [31:0] source_x32,source_y32,
    output reg [7:0] dest_x,
    output reg [5:0] dest_y,
    output wire sample_last,
    output wire done_valid,
    input wire done_ready,
    output reg [1:0] done_status
);
    // Status 1: nonpositive denominator; 2: source coordinate overflow.
    localparam IDLE=0,LOAD=1,INIT=2,PREPARE=3,DIVIDE=4,
               ROUND=5,Y_START=6,OFFER=7,DONE=8;
    reg [3:0] state,index;
    reg signed [47:0] matrix [0:8];
    reg signed [63:0] row_x,row_y,row_d,numer_x,numer_y,denominator;
    reg [63:0] dividend,divisor,quotient;
    reg [64:0] remainder;
    reg [5:0] bit_index;
    reg negative,y_phase;
    wire reset_local=rst || abort;
    wire [64:0] shifted_remainder={remainder[63:0],dividend[63]};
    wire subtract=shifted_remainder>={1'b0,divisor};
    wire [64:0] final_remainder=subtract ? shifted_remainder-{1'b0,divisor} : shifted_remainder;
    wire [63:0] final_quotient={quotient[62:0],subtract};
    wire [65:0] twice_remainder={remainder,1'b0};
    wire round_up=(twice_remainder>{2'b0,divisor}) ||
                  ((twice_remainder=={2'b0,divisor}) && quotient[0]);
    wire [64:0] rounded={1'b0,quotient}+round_up;
    assign start_ready=state==IDLE && !reset_local;
    assign coeff_ready=state==LOAD && !reset_local;
    assign sample_valid=state==OFFER && !reset_local;
    assign sample_last=dest_x==223 && dest_y==63;
    assign done_valid=state==DONE && !reset_local;

    function signed [63:0] extend;
        input signed [47:0] value;
        begin extend={{16{value[47]}},value};end
    endfunction
    task begin_division;
        input signed [63:0] value;
        reg [63:0] magnitude;
        begin
            magnitude=value<0 ? -value : value;
            // Only 32 quotient bits are emitted. Seed the remainder with the
            // upper half; this skips 32 guaranteed leading zero quotient bits.
            if ({32'd0,magnitude[63:32]}>=$unsigned(denominator)) begin
                done_status<=2;state<=DONE;
            end else begin
                dividend<=magnitude<<32;
                negative<=value<0;divisor<=denominator;
                quotient<=0;remainder<={33'd0,magnitude[63:32]};bit_index<=31;state<=DIVIDE;
            end
        end
    endtask

    always @(posedge clk) begin
        if (reset_local) begin
            state<=IDLE;done_status<=0;source_x32<=0;source_y32<=0;dest_x<=0;dest_y<=0;
        end else case(state)
            IDLE: if (start_valid) begin index<=0;done_status<=0;state<=LOAD;end
            LOAD: if (coeff_valid) begin
                matrix[index]<=coeff_data;
                if (index==8) state<=INIT;else index<=index+1'b1;
            end
            INIT: begin
                row_x<=extend(matrix[2])<<<5;row_y<=extend(matrix[5])<<<5;row_d<=extend(matrix[8]);
                numer_x<=extend(matrix[2])<<<5;numer_y<=extend(matrix[5])<<<5;denominator<=extend(matrix[8]);
                dest_x<=0;dest_y<=0;state<=PREPARE;
            end
            PREPARE: begin
                if (denominator<=0) begin done_status<=1;state<=DONE;end
                else begin y_phase<=0;begin_division(numer_x);end
            end
            DIVIDE: begin
                remainder<=final_remainder;quotient<=final_quotient;dividend<=dividend<<1;
                if (bit_index==0) state<=ROUND;else bit_index<=bit_index-1'b1;
            end
            ROUND: begin
                if (rounded>65'd2147483647) begin done_status<=2;state<=DONE;end
                else if (!y_phase) begin
                    source_x32<=negative ? -$signed(rounded[31:0]) : $signed(rounded[31:0]);
                    state<=Y_START;
                end else begin
                    source_y32<=negative ? -$signed(rounded[31:0]) : $signed(rounded[31:0]);
                    state<=OFFER;
                end
            end
            Y_START: begin y_phase<=1;begin_division(numer_y);end
            OFFER: if (sample_ready) begin
                if (sample_last) state<=DONE;
                else begin
                    if (dest_x==223) begin
                        dest_x<=0;dest_y<=dest_y+1'b1;
                        row_x<=row_x+(extend(matrix[1])<<<5);
                        row_y<=row_y+(extend(matrix[4])<<<5);
                        row_d<=row_d+extend(matrix[7]);
                        numer_x<=row_x+(extend(matrix[1])<<<5);
                        numer_y<=row_y+(extend(matrix[4])<<<5);
                        denominator<=row_d+extend(matrix[7]);
                    end else begin
                        dest_x<=dest_x+1'b1;
                        numer_x<=numer_x+(extend(matrix[0])<<<5);
                        numer_y<=numer_y+(extend(matrix[3])<<<5);
                        denominator<=denominator+extend(matrix[6]);
                    end
                    state<=PREPARE;
                end
            end
            DONE: if (done_ready) state<=IDLE;
        endcase
    end
endmodule
