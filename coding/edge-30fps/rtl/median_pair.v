// Two pixels per cycle, MS pixel first. EOL needs one tail cycle; EOF also
// needs one synthetic row. The camera supplies these cycles in blanking.
module median_pair #(
    parameter WIDTH=1280, HEIGHT=720, CONFIG_WIDTH=13
)(
    input clk, rst_n,
    input in_valid, output in_ready,
    input [CONFIG_WIDTH-1:0] in_config,
    output reg [CONFIG_WIDTH-1:0] out_config,
    input [63:0] in_rgby,
    input in_sof, in_eol, in_eof,
    input [31:0] in_frame_id, in_epoch,
    output reg out_valid, input out_ready,
    output reg [63:0] out_rgby,
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
    reg [CONFIG_WIDTH-1:0] frame_config;
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

    // Odd/even transposition network: nine fixed layers sort all nine values.
    reg [71:0] sort0[0:9],sort1[0:9];
    reg [63:0] rgb_pipe[0:9];
    reg [CONFIG_WIDTH-1:0] config_pipe[0:9];
    reg [31:0] id_pipe[0:9],epoch_pipe[0:9];
    reg [2:0] marks[0:9];
    reg [9:0] valid_pipe;
    genvar stage,j;
    generate for(stage=0;stage<9;stage=stage+1) begin: sorting
        for(j=0;j<9;j=j+1) begin: lane
            if ((j%2)==(stage%2) && j<8) begin
                always @(posedge clk) if(advance) begin
                    sort0[stage+1][j*8+:8]<=sort0[stage][j*8+:8]<sort0[stage][(j+1)*8+:8]?sort0[stage][j*8+:8]:sort0[stage][(j+1)*8+:8];
                    sort1[stage+1][j*8+:8]<=sort1[stage][j*8+:8]<sort1[stage][(j+1)*8+:8]?sort1[stage][j*8+:8]:sort1[stage][(j+1)*8+:8];
                end
            end else if(j>0 && ((j-1)%2)==(stage%2)) begin
                always @(posedge clk) if(advance) begin
                    sort0[stage+1][j*8+:8]<=sort0[stage][j*8+:8]>sort0[stage][(j-1)*8+:8]?sort0[stage][j*8+:8]:sort0[stage][(j-1)*8+:8];
                    sort1[stage+1][j*8+:8]<=sort1[stage][j*8+:8]>sort1[stage][(j-1)*8+:8]?sort1[stage][j*8+:8]:sort1[stage][(j-1)*8+:8];
                end
            end else begin
                always @(posedge clk) if(advance) begin
                    sort0[stage+1][j*8+:8]<=sort0[stage][j*8+:8];
                    sort1[stage+1][j*8+:8]<=sort1[stage][j*8+:8];
                end
            end
        end
        always @(posedge clk) if(advance) begin
            rgb_pipe[stage+1]<=rgb_pipe[stage];config_pipe[stage+1]<=config_pipe[stage];
            id_pipe[stage+1]<=id_pipe[stage];epoch_pipe[stage+1]<=epoch_pipe[stage];marks[stage+1]<=marks[stage];
        end
    end endgenerate
    always @(posedge clk) begin
        if(!rst_n) begin
            frame_config<=13'd2080;out_config<=13'd2080;
            x<=0; y<=0; tail_y<=0; tail<=0; flush<=0; frame_id<=0; epoch<=0;
            q_valid<=0; q_tail<=0; qx<=0; qy<=0; q_id<=0; q_epoch<=0;
            pt<=0;pm<=0;pb<=0;lt<=0;lm<=0;lb<=0;pc<=0;
            valid_pipe<=0; out_valid<=0;
            out_rgby<=0; out_sof<=0; out_eol<=0; out_eof<=0;
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
                if(in_sof && !flush) begin frame_id<=in_frame_id; epoch<=in_epoch; frame_config<=in_config; end
                if((!flush && in_eol) || (flush && x==PAIRS-1)) begin
                    x<=0; y<=ry+1'b1; tail<=1; tail_y<=ry;
                    if(!flush && in_eof) flush<=1;
                end else begin x<=rx+1'b1; y<=ry; end
            end
            if(q_valid) begin
                if(!q_tail) begin
                    pt<=ct; pm<=cm; pb<=cb; pc<=center_q;
                    lt<=pt[7:0]; lm<=pm[7:0]; lb<=pb[7:0];
                end
                sort0[0]<={qx==1?pt[15:8]:lt,pt,qx==1?pm[15:8]:lm,pm,qx==1?pb[15:8]:lb,pb};
                sort1[0]<={pt,q_tail?pt[7:0]:ct[15:8],pm,q_tail?pm[7:0]:cm[15:8],pb,q_tail?pb[7:0]:cb[15:8]};
                rgb_pipe[0]<=pc;config_pipe[0]<=frame_config;
                id_pipe[0]<=q_id;epoch_pipe[0]<=q_epoch;
                marks[0]<={qy==1 && qx==1,q_tail,qy==HEIGHT && q_tail};
            end
            valid_pipe<={valid_pipe[8:0],q_valid && qy!=0 && qx!=0};
            out_valid<=valid_pipe[9];
            out_rgby<={config_pipe[9][11]?sort0[9][39:32]:rgb_pipe[9][63:56],rgb_pipe[9][55:32],
                        config_pipe[9][11]?sort1[9][39:32]:rgb_pipe[9][31:24],rgb_pipe[9][23:0]};
            out_config<=config_pipe[9];
            {out_sof,out_eol,out_eof}<=marks[9];
            out_frame_id<=id_pipe[9];out_epoch<=epoch_pipe[9];
        end
    end
endmodule
