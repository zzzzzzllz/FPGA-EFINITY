`timescale 1ns/1ps
// Q16 TL/TR/BR/BL corners -> nine signed48 Q32 inverse-map coefficients.
// Square-to-quadrilateral equations; all intermediate arithmetic is exact.
module perspective_matrix (
    input wire clk,rst,abort,
    input wire start_valid,
    output wire start_ready,
    input wire corner_valid,
    output wire corner_ready,
    input wire signed [31:0] corner_data,
    output wire coeff_valid,
    input wire coeff_ready,
    output wire signed [47:0] coeff_data,
    output wire coeff_last,
    output wire done_valid,
    input wire done_ready,
    output reg [1:0] done_status
);
    // 1: corner beyond +/-2048 pixels; 2: degenerate; 3: coefficient overflow.
    localparam IDLE=0,LOAD=1,CHECK=2,DERIVE=3,MULTIPLY=4,PRODUCT=5,
               SELECT=6,DIVIDE=7,ROUND=8,EMIT=9,DONE=10;
    reg [3:0] state,index,phase;
    reg signed [31:0] points[0:7];
    reg signed [47:0] matrix[0:8];
    reg bad_input;
    reg signed [127:0] dx1,dx2,dx3,dy1,dy2,dy3,det,gn,hn,temp;
    reg signed [127:0] selected_point,selected_factor,selected_denominator;
    reg [127:0] mul_a,mul_b,mul_acc;
    reg mul_negative;
    reg signed [127:0] product_value;
    reg [127:0] dividend,divisor;
    reg [128:0] remainder;
    reg [47:0] quotient;
    reg [5:0] bit_index;
    reg div_negative;
    wire reset_local=rst || abort;
    assign start_ready=state==IDLE && !reset_local;
    assign corner_ready=state==LOAD && !reset_local;
    assign coeff_valid=state==EMIT && !reset_local;
    assign coeff_data=matrix[index];
    assign coeff_last=index==8;
    assign done_valid=state==DONE && !reset_local;
    wire [127:0] mul_next=mul_acc+(mul_b[0] ? mul_a : 128'd0);
    wire [128:0] shifted={remainder[127:0],dividend[127]};
    wire subtract=shifted>={1'b0,divisor};
    wire [128:0] next_remainder=subtract ? shifted-{1'b0,divisor} : shifted;
    wire [47:0] next_quotient={quotient[46:0],subtract};
    wire [129:0] twice={remainder,1'b0};
    wire round_up=twice>{2'b0,divisor} || (twice=={2'b0,divisor} && quotient[0]);
    wire [48:0] rounded={1'b0,quotient}+round_up;
    function signed [127:0] extend;
        input signed [31:0] v;
        begin extend={{96{v[31]}},v};end
    endfunction
    function signed [127:0] times223;
        input signed [127:0] v;
        begin times223=(v<<<8)-(v<<<5)-v;end
    endfunction
    function signed [127:0] times63;
        input signed [127:0] v;
        begin times63=(v<<<6)-v;end
    endfunction
    task multiply;
        input signed [127:0] a,b;
        input [3:0] purpose;
        begin
            mul_a<=a<0 ? -a : a;mul_b<=b<0 ? -b : b;mul_acc<=0;
            mul_negative<=a[127]^b[127];phase<=purpose;state<=MULTIPLY;
        end
    endtask
    task divide;
        input signed [127:0] n,d;
        reg [127:0] magnitude,den;
        begin
            magnitude=n<0 ? -n : n;den=d<0 ? -d : d;
            if (den==0) begin done_status<=2;state<=DONE;end
            else if ((magnitude>>48)>=den) begin done_status<=3;state<=DONE;end
            else begin
                dividend<=magnitude<<80;divisor<=den;remainder<={49'd0,magnitude[127:48]};
                quotient<=0;bit_index<=47;div_negative<=n[127]^d[127];state<=DIVIDE;
            end
        end
    endtask
    always @(posedge clk) begin
        if (reset_local) begin state<=IDLE;index<=0;done_status<=0;end
        else case(state)
            IDLE: if (start_valid) begin index<=0;bad_input<=0;done_status<=0;state<=LOAD;end
            LOAD: if (corner_valid) begin
                points[index]<=corner_data;
                if (corner_data>32'sd134217728 || corner_data< -32'sd134217728) bad_input<=1;
                if (index==7) state<=CHECK;else index<=index+1'b1;
            end
            CHECK: begin
                if (bad_input) begin done_status<=1;state<=DONE;end
                else begin
                    dx1<=extend(points[2])-extend(points[4]);dx2<=extend(points[6])-extend(points[4]);
                    dx3<=extend(points[0])-extend(points[2])+extend(points[4])-extend(points[6]);
                    dy1<=extend(points[3])-extend(points[5]);dy2<=extend(points[7])-extend(points[5]);
                    dy3<=extend(points[1])-extend(points[3])+extend(points[5])-extend(points[7]);
                    phase<=0;state<=DERIVE;
                end
            end
            DERIVE: case(phase)
                0:multiply(dx1,dy2,0);
                1:multiply(dx2,dy1,1);
                2:multiply(dx3,dy2,2);
                3:multiply(dx2,dy3,3);
                4:multiply(dx1,dy3,4);
                5:multiply(dx3,dy1,5);
            endcase
            MULTIPLY: begin
                mul_acc<=mul_next;
                if (mul_b<=1) begin
                    product_value<=mul_negative ? -$signed(mul_next) : $signed(mul_next);state<=PRODUCT;
                end else begin mul_a<=mul_a<<1;mul_b<=mul_b>>1;end
            end
            PRODUCT: case(phase)
                0,2,4:begin temp<=product_value;phase<=phase+1'b1;state<=DERIVE;end
                1:begin
                    det<=temp-product_value;
                    if (temp==product_value) begin done_status<=2;state<=DONE;end
                    else begin phase<=2;state<=DERIVE;end
                end
                3:begin gn<=temp-product_value;phase<=4;state<=DERIVE;end
                5:begin hn<=temp-product_value;index<=0;state<=SELECT;end
                6:begin temp<=product_value;multiply(selected_factor,selected_point,7);end
                7:divide((temp+product_value)<<<32,selected_denominator);
            endcase
            SELECT: case(index)
                0,1,3,4:begin
                    if (index==0 || index==3) begin
                        selected_denominator<=times223(det)<<<16;selected_factor<=gn;
                        selected_point<=index==0 ? extend(points[2]) : extend(points[3]);
                        multiply(index==0 ? extend(points[2])-extend(points[0]) : extend(points[3])-extend(points[1]),det,6);
                    end else begin
                        selected_denominator<=times63(det)<<<16;selected_factor<=hn;
                        selected_point<=index==1 ? extend(points[6]) : extend(points[7]);
                        multiply(index==1 ? extend(points[6])-extend(points[0]) : extend(points[7])-extend(points[1]),det,6);
                    end
                end
                2,5:begin
                    matrix[index]<=index==2 ? (extend(points[0])<<<16) : (extend(points[1])<<<16);
                    index<=index+1'b1;
                end
                6:divide(gn<<<32,times223(det));
                7:divide(hn<<<32,times63(det));
                8:begin matrix[8]<=48'sd4294967296;index<=0;state<=EMIT;end
            endcase
            DIVIDE: begin
                remainder<=next_remainder;quotient<=next_quotient;dividend<=dividend<<1;
                if (bit_index==0) state<=ROUND;else bit_index<=bit_index-1'b1;
            end
            ROUND: begin
                if (rounded>(div_negative ? 49'd140737488355328 : 49'd140737488355327)) begin done_status<=3;state<=DONE;end
                else begin
                    matrix[index]<=div_negative ? -$signed(rounded[47:0]) : $signed(rounded[47:0]);
                    index<=index+1'b1;state<=SELECT;
                end
            end
            EMIT: if (coeff_ready) begin
                if (index==8) state<=DONE;else index<=index+1'b1;
            end
            DONE: if (done_ready) state<=IDLE;
        endcase
    end
endmodule
