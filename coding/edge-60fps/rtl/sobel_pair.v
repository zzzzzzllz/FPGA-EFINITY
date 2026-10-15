// Two pixels per cycle, MS pixel first. EOL needs one tail cycle; EOF also
// needs one synthetic row. The camera supplies these cycles in blanking.
module sobel_pair #(
    parameter WIDTH=1280, HEIGHT=720, THRESHOLD=64
)(
    input clk, rst_n,
    input in_valid, output in_ready,
    input [63:0] in_rgby,
    input in_sof, in_eol, in_eof,
    input [31:0] in_frame_id, in_epoch,
    output reg out_valid, input out_ready,
    output reg [63:0] out_rgbe,
    output reg out_sof, out_eol, out_eof,
    output reg [31:0] out_frame_id, out_epoch
);
    localparam PAIRS=WIDTH/2, AW=$clog2(PAIRS);
    reg [63:0] row_rgb [0:PAIRS-1];
    reg [15:0] row_y [0:PAIRS-1];
    reg [AW:0] x;
    reg [15:0] y, tail_y;
    reg tail, flush;
    reg [31:0] frame_id, epoch;
    wire advance=!out_valid || out_ready;
    assign in_ready=advance && !tail && !flush;
    wire read_pair=advance && !tail && (flush || in_valid);
    wire [AW:0] rx=in_sof && !flush ? 0 : x;
    wire [15:0] ry=in_sof && !flush ? 0 : y;

    reg q_valid,q_tail;
    reg [AW:0] qx;
    reg [15:0] qy, top_q, bottom_q;
    reg [63:0] center_q;
    reg [31:0] q_id,q_epoch;
    // Synchronous read-before-write RAM. The second row is written one
    // enabled cycle later, using the first row's registered read data.
    always @(posedge clk) begin
        if(read_pair) begin
            center_q<=row_rgb[rx[AW-1:0]];
            top_q<=row_y[rx[AW-1:0]];
            bottom_q<={in_rgby[63:56],in_rgby[31:24]};
            if(!flush) row_rgb[rx[AW-1:0]]<=in_rgby;
        end
        if(advance && q_valid && !q_tail)
            row_y[qx[AW-1:0]]<={center_q[63:56],center_q[31:24]};
    end

    // Saved pair and its left neighbour, separately for all three rows.
    reg [15:0] pt,pm,pb;
    reg [7:0] lt,lm,lb;
    reg [63:0] pc;
    wire [15:0] ct=qy==1 ? {center_q[63:56],center_q[31:24]} : top_q;
    wire [15:0] cm={center_q[63:56],center_q[31:24]};
    wire [15:0] cb=qy==HEIGHT ? cm : bottom_q;

    function signed [10:0] gx;
        input [7:0] a,c,d,f,g,i;
        begin gx=$signed({3'b0,c})+($signed({3'b0,f})<<<1)+$signed({3'b0,i})
                -$signed({3'b0,a})-($signed({3'b0,d})<<<1)-$signed({3'b0,g}); end
    endfunction
    function signed [10:0] gy;
        input [7:0] a,b,c,g,h,i;
        begin gy=$signed({3'b0,g})+($signed({3'b0,h})<<<1)+$signed({3'b0,i})
                -$signed({3'b0,a})-($signed({3'b0,b})<<<1)-$signed({3'b0,c}); end
    endfunction
    function [10:0] magnitude;
        input signed [10:0] dx,dy;
        reg [10:0] ax,ay;
        begin ax=dx[10]?-dx:dx; ay=dy[10]?-dy:dy; magnitude=ax+ay; end
    endfunction
    reg signed [10:0] gx0,gy0,gx1,gy1;
    reg s_valid,s_sof,s_eol,s_eof,s_border,s_left,s_right;
    reg [63:0] s_rgb;
    reg [31:0] s_id,s_epoch;
    reg [10:0] mag0,mag1;
    reg m_valid,m_sof,m_eol,m_eof,m_border,m_left,m_right;
    reg [63:0] m_rgb;
    reg [31:0] m_id,m_epoch;
    wire edge0=!m_border && !m_left && mag0>THRESHOLD;
    wire edge1=!m_border && !m_right && mag1>THRESHOLD;

    always @(posedge clk) begin
        if(!rst_n) begin
            x<=0; y<=0; tail_y<=0; tail<=0; flush<=0; frame_id<=0; epoch<=0;
            q_valid<=0; q_tail<=0; qx<=0; qy<=0; q_id<=0; q_epoch<=0;
            pt<=0;pm<=0;pb<=0;lt<=0;lm<=0;lb<=0;pc<=0;
            s_valid<=0; m_valid<=0; out_valid<=0;
            out_rgbe<=0; out_sof<=0; out_eol<=0; out_eof<=0;
            out_frame_id<=0; out_epoch<=0;
        end else if(advance) begin
            q_valid<=read_pair || tail;
            q_tail<=tail;
            if(tail) begin
                qx<=PAIRS; qy<=tail_y; q_id<=frame_id; q_epoch<=epoch;
                tail<=0;
                if(tail_y==HEIGHT) begin flush<=0; y<=0; end
            end else if(read_pair) begin
                qx<=rx; qy<=ry;
                q_id<=in_sof && !flush ? in_frame_id : frame_id;
                q_epoch<=in_sof && !flush ? in_epoch : epoch;
                if(in_sof && !flush) begin frame_id<=in_frame_id; epoch<=in_epoch; end
                if((!flush && in_eol) || (flush && x==PAIRS-1)) begin
                    x<=0; y<=ry+1'b1; tail<=1; tail_y<=ry;
                    if(!flush && in_eof) flush<=1;
                end else begin x<=rx+1'b1; y<=ry; end
            end
            s_valid<=q_valid && qy!=0 && qx!=0;
            if(q_valid) begin
                if(!q_tail) begin
                    pt<=ct; pm<=cm; pb<=cb; pc<=center_q;
                    lt<=pt[7:0]; lm<=pm[7:0]; lb<=pb[7:0];
                end
                // At x=1 the first pixel's left neighbour is replicated.
                gx0<=gx(qx==1?pt[15:8]:lt,pt[7:0],qx==1?pm[15:8]:lm,pm[7:0],qx==1?pb[15:8]:lb,pb[7:0]);
                gy0<=gy(qx==1?pt[15:8]:lt,pt[15:8],pt[7:0],qx==1?pb[15:8]:lb,pb[15:8],pb[7:0]);
                gx1<=gx(pt[15:8],q_tail?pt[7:0]:ct[15:8],pm[15:8],q_tail?pm[7:0]:cm[15:8],pb[15:8],q_tail?pb[7:0]:cb[15:8]);
                gy1<=gy(pt[15:8],pt[7:0],q_tail?pt[7:0]:ct[15:8],pb[15:8],pb[7:0],q_tail?pb[7:0]:cb[15:8]);
                s_rgb<=pc; s_id<=q_id; s_epoch<=q_epoch;
                s_sof<=qy==1 && qx==1;
                s_eol<=q_tail; s_eof<=qy==HEIGHT && q_tail;
                s_border<=qy==1 || qy==HEIGHT;
                s_left<=qx==1; s_right<=q_tail;
            end
            mag0<=magnitude(gx0,gy0); mag1<=magnitude(gx1,gy1);
            m_valid<=s_valid; m_rgb<=s_rgb; m_id<=s_id; m_epoch<=s_epoch;
            m_sof<=s_sof; m_eol<=s_eol; m_eof<=s_eof;
            m_border<=s_border; m_left<=s_left; m_right<=s_right;
            out_valid<=m_valid;
            out_rgbe<={{8{edge0}},m_rgb[55:32],{8{edge1}},m_rgb[23:0]};
            out_sof<=m_sof; out_eol<=m_eol; out_eof<=m_eof;
            out_frame_id<=m_id; out_epoch<=m_epoch;
        end
    end
endmodule
