// Each complete 2x2 Bayer cell becomes one RGB pixel; no region is cropped.
module raw_full_view #(
    parameter WIDTH=2560, HEIGHT=1440
)(
    input clk, rst_n, vs, hs, valid,
    input [39:0] raw4,
    input [1:0] phase, // 0 BGGR, 1 GBRG, 2 GRBG, 3 RGGB
    input [15:0] gain_r, gain_g, gain_b,
    output reg out_vs, out_valid,
    output reg [63:0] rgb2,
    output reg [31:0] frames, errors,
    output reg [15:0] measured_width, measured_height,
    output reg [31:0] sum_r, sum_g, sum_b
);
    localparam AW=$clog2(WIDTH/4);
    reg [39:0] line_mem [0:(1<<AW)-1];
    reg [39:0] top_q, bottom_q;
    reg [AW:0] x;
    reg [15:0] y;
    reg vs_d, hs_d, row_has_data, pair_valid;
    reg [2:0] vs_pipe;
    reg [31:0] accum_r, accum_g, accum_b;
    wire input_valid=valid && hs && x<WIDTH/4 && y<HEIGHT;

    always @(posedge clk) begin
        if(input_valid && !y[0]) line_mem[x[AW-1:0]]<=raw4;
        top_q<=line_mem[x[AW-1:0]];
        bottom_q<=raw4;
    end

    function [29:0] decode;
        input [19:0] top_row, bottom_row;
        input [1:0] p;
        reg [9:0] a,b,c,d,r,g,blue;
        reg [10:0] green_sum;
        begin
            a=top_row[9:0]; b=top_row[19:10];
            c=bottom_row[9:0]; d=bottom_row[19:10];
            case(p)
                0: begin r=d; blue=a; green_sum={1'b0,b}+c; end
                1: begin r=c; blue=b; green_sum={1'b0,a}+d; end
                2: begin r=b; blue=c; green_sum={1'b0,a}+d; end
                3: begin r=a; blue=d; green_sum={1'b0,b}+c; end
            endcase
            g=green_sum[10:1];
            decode={r,g,blue};
        end
    endfunction
    function [7:0] apply_gain;
        input [25:0] product;
        begin apply_gain=(|product[25:18])?8'hff:product[17:10]; end
    endfunction
    wire [29:0] c0=decode(top_q[19:0],bottom_q[19:0],phase);
    wire [29:0] c1=decode(top_q[39:20],bottom_q[39:20],phase);
    reg [25:0] r0,g0,b0,r1,g1,b1;
    reg color_valid;
    always @(posedge clk) begin
        if(!rst_n) begin
            x<=0; y<=0; vs_d<=0; hs_d<=0; row_has_data<=0;
            pair_valid<=0; color_valid<=0; out_valid<=0; vs_pipe<=0; out_vs<=0;
            frames<=0; errors<=0; measured_width<=0; measured_height<=0;
            accum_r<=0; accum_g<=0; accum_b<=0; sum_r<=0; sum_g<=0; sum_b<=0;
            rgb2<=0;
        end else begin
            vs_d<=vs; hs_d<=hs;
            vs_pipe<={vs_pipe[1:0],vs}; out_vs<=vs_pipe[2];
            pair_valid<=input_valid && y[0];
            color_valid<=pair_valid; out_valid<=color_valid;
            if(vs!=vs_d) begin
                if(y!=0) begin
                    frames<=frames+1;
                    measured_height<=y;
                    if(y!=HEIGHT) errors<=errors+1;
                    sum_r<=accum_r; sum_g<=accum_g; sum_b<=accum_b;
                end
                x<=0; y<=0; row_has_data<=0;
                accum_r<=0; accum_g<=0; accum_b<=0;
            end else begin
                if(valid && hs) begin x<=x+1; row_has_data<=1; end
                if(hs_d && !hs && row_has_data) begin
                    measured_width<=x*4;
                    if(x!=WIDTH/4) errors<=errors+1;
                    x<=0; y<=y+1; row_has_data<=0;
                end
                if(pair_valid) begin
                    accum_r<=accum_r+{22'd0,c0[29:20]}+c1[29:20];
                    accum_g<=accum_g+{22'd0,c0[19:10]}+c1[19:10];
                    accum_b<=accum_b+{22'd0,c0[9:0]}+c1[9:0];
                end
            end
            r0<=c0[29:20]*gain_r; g0<=c0[19:10]*gain_g; b0<=c0[9:0]*gain_b;
            r1<=c1[29:20]*gain_r; g1<=c1[19:10]*gain_g; b1<=c1[9:0]*gain_b;
            // The DDR serializer sends the most significant pixel first.
            rgb2<={8'd0,apply_gain(r0),apply_gain(g0),apply_gain(b0),
                   8'd0,apply_gain(r1),apply_gain(g1),apply_gain(b1)};
        end
    end
endmodule
