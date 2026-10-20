/*M///////////////////////////////////////////////////////////////////////////////////////
//
//  IMPORTANT: READ BEFORE DOWNLOADING, COPYING, INSTALLING OR USING.
//
//  By downloading, copying, installing or using the software you agree to this license.
//  If you do not agree to this license, do not download, install,
//  copy or use the software.
//
//
//                           License Agreement
//                For Open Source Computer Vision Library
//
// Copyright (C) 2000-2008, 2018, Intel Corporation, all rights reserved.
// Copyright (C) 2009, Willow Garage Inc., all rights reserved.
// Copyright (C) 2014-2015, Itseez Inc., all rights reserved.
// Copyright (C) 2025, Advanced Micro Devices, all rights reserved.
// Third party copyrights are property of their respective owners.
//
// Redistribution and use in source and binary forms, with or without modification,
// are permitted provided that the following conditions are met:
//
//   * Redistribution's of source code must retain the above copyright notice,
//     this list of conditions and the following disclaimer.
//
//   * Redistribution's in binary form must reproduce the above copyright notice,
//     this list of conditions and the following disclaimer in the documentation
//     and/or other materials provided with the distribution.
//
//   * The name of the copyright holders may not be used to endorse or promote products
//     derived from this software without specific prior written permission.
//
// This software is provided by the copyright holders and contributors "as is" and
// any express or implied warranties, including, but not limited to, the implied
// warranties of merchantability and fitness for a particular purpose are disclaimed.
// In no event shall the Intel Corporation or contributors be liable for any direct,
// indirect, incidental, special, exemplary, or consequential damages
// (including, but not limited to, procurement of substitute goods or services;
// loss of use, data, or profits; or business interruption) however caused
// and on any theory of liability, whether in contract, strict liability,
// or tort (including negligence or otherwise) arising in any way out of
// the use of this software, even if advised of the possibility of such damage.
//
//M*/
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
    output reg [31:0] out_frame_id, out_epoch,
    output reg [15:0] out_original_luma,
    output reg [1:0] out_raw_edge
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

    // OpenCV 3x3 median selection: 19 compare-exchanges, nine stages.
    // Nine stages preserve the existing handshake and pixel latency.
    reg [71:0] sort0[0:9],sort1[0:9];
    reg [63:0] rgb_pipe[0:9];
    reg [CONFIG_WIDTH-1:0] config_pipe[0:9];
    reg [31:0] id_pipe[0:9],epoch_pipe[0:9];
    reg [2:0] marks[0:9];
    reg [9:0] valid_pipe;
    // Reuse the median window for the unfiltered Sobel comparison.
    // Both edge masks use the same source frame, threshold and zero border.
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
    reg signed [10:0] raw_gx0,raw_gy0,raw_gx1,raw_gy1;
    reg [10:0] raw_mag0,raw_mag1;
    reg [1:0] raw_border0,raw_border1;
    reg [1:0] raw_edge_pipe[2:9];
    integer raw_stage;
    always @(posedge clk) if(advance) begin
        if(q_valid) begin
                raw_gx0<=gx(qx==1?pt[15:8]:lt,pt[7:0],qx==1?pm[15:8]:lm,pm[7:0],qx==1?pb[15:8]:lb,pb[7:0]);
                raw_gy0<=gy(qx==1?pt[15:8]:lt,pt[15:8],pt[7:0],qx==1?pb[15:8]:lb,pb[15:8],pb[7:0]);
                raw_gx1<=gx(pt[15:8],q_tail?pt[7:0]:ct[15:8],pm[15:8],q_tail?pm[7:0]:cm[15:8],pb[15:8],q_tail?pb[7:0]:cb[15:8]);
                raw_gy1<=gy(pt[15:8],pt[7:0],q_tail?pt[7:0]:ct[15:8],pb[15:8],pb[7:0],q_tail?pb[7:0]:cb[15:8]);
            raw_border0<={qy==1 || qy==HEIGHT || qx==1,qy==1 || qy==HEIGHT || q_tail};
        end
        raw_mag0<=magnitude(raw_gx0,raw_gy0);raw_mag1<=magnitude(raw_gx1,raw_gy1);
        raw_border1<=raw_border0;
        raw_edge_pipe[2]<={!raw_border1[1] && raw_mag0>config_pipe[1][10:0],
                           !raw_border1[0] && raw_mag1>config_pipe[1][10:0]};
        for(raw_stage=3;raw_stage<=9;raw_stage=raw_stage+1)
            raw_edge_pipe[raw_stage]<=raw_edge_pipe[raw_stage-1];
        out_raw_edge<=raw_edge_pipe[9];
        out_original_luma<={rgb_pipe[9][63:56],rgb_pipe[9][31:24]};
    end
    always @(posedge clk) if(advance) begin
        sort0[1][0+:8]<=sort0[0][0+:8];
        sort1[1][0+:8]<=sort1[0][0+:8];
        sort0[1][8+:8]<=sort0[0][8+:8]<sort0[0][16+:8]?sort0[0][8+:8]:sort0[0][16+:8];
        sort1[1][8+:8]<=sort1[0][8+:8]<sort1[0][16+:8]?sort1[0][8+:8]:sort1[0][16+:8];
        sort0[1][16+:8]<=sort0[0][8+:8]<sort0[0][16+:8]?sort0[0][16+:8]:sort0[0][8+:8];
        sort1[1][16+:8]<=sort1[0][8+:8]<sort1[0][16+:8]?sort1[0][16+:8]:sort1[0][8+:8];
        sort0[1][24+:8]<=sort0[0][24+:8];
        sort1[1][24+:8]<=sort1[0][24+:8];
        sort0[1][32+:8]<=sort0[0][32+:8]<sort0[0][40+:8]?sort0[0][32+:8]:sort0[0][40+:8];
        sort1[1][32+:8]<=sort1[0][32+:8]<sort1[0][40+:8]?sort1[0][32+:8]:sort1[0][40+:8];
        sort0[1][40+:8]<=sort0[0][32+:8]<sort0[0][40+:8]?sort0[0][40+:8]:sort0[0][32+:8];
        sort1[1][40+:8]<=sort1[0][32+:8]<sort1[0][40+:8]?sort1[0][40+:8]:sort1[0][32+:8];
        sort0[1][48+:8]<=sort0[0][48+:8];
        sort1[1][48+:8]<=sort1[0][48+:8];
        sort0[1][56+:8]<=sort0[0][56+:8]<sort0[0][64+:8]?sort0[0][56+:8]:sort0[0][64+:8];
        sort1[1][56+:8]<=sort1[0][56+:8]<sort1[0][64+:8]?sort1[0][56+:8]:sort1[0][64+:8];
        sort0[1][64+:8]<=sort0[0][56+:8]<sort0[0][64+:8]?sort0[0][64+:8]:sort0[0][56+:8];
        sort1[1][64+:8]<=sort1[0][56+:8]<sort1[0][64+:8]?sort1[0][64+:8]:sort1[0][56+:8];
        rgb_pipe[1]<=rgb_pipe[0];
        config_pipe[1]<=config_pipe[0];
        id_pipe[1]<=id_pipe[0];
        epoch_pipe[1]<=epoch_pipe[0];
        marks[1]<=marks[0];
    end
    always @(posedge clk) if(advance) begin
        sort0[2][0+:8]<=sort0[1][0+:8]<sort0[1][8+:8]?sort0[1][0+:8]:sort0[1][8+:8];
        sort1[2][0+:8]<=sort1[1][0+:8]<sort1[1][8+:8]?sort1[1][0+:8]:sort1[1][8+:8];
        sort0[2][8+:8]<=sort0[1][0+:8]<sort0[1][8+:8]?sort0[1][8+:8]:sort0[1][0+:8];
        sort1[2][8+:8]<=sort1[1][0+:8]<sort1[1][8+:8]?sort1[1][8+:8]:sort1[1][0+:8];
        sort0[2][16+:8]<=sort0[1][16+:8];
        sort1[2][16+:8]<=sort1[1][16+:8];
        sort0[2][24+:8]<=sort0[1][24+:8]<sort0[1][32+:8]?sort0[1][24+:8]:sort0[1][32+:8];
        sort1[2][24+:8]<=sort1[1][24+:8]<sort1[1][32+:8]?sort1[1][24+:8]:sort1[1][32+:8];
        sort0[2][32+:8]<=sort0[1][24+:8]<sort0[1][32+:8]?sort0[1][32+:8]:sort0[1][24+:8];
        sort1[2][32+:8]<=sort1[1][24+:8]<sort1[1][32+:8]?sort1[1][32+:8]:sort1[1][24+:8];
        sort0[2][40+:8]<=sort0[1][40+:8];
        sort1[2][40+:8]<=sort1[1][40+:8];
        sort0[2][48+:8]<=sort0[1][48+:8]<sort0[1][56+:8]?sort0[1][48+:8]:sort0[1][56+:8];
        sort1[2][48+:8]<=sort1[1][48+:8]<sort1[1][56+:8]?sort1[1][48+:8]:sort1[1][56+:8];
        sort0[2][56+:8]<=sort0[1][48+:8]<sort0[1][56+:8]?sort0[1][56+:8]:sort0[1][48+:8];
        sort1[2][56+:8]<=sort1[1][48+:8]<sort1[1][56+:8]?sort1[1][56+:8]:sort1[1][48+:8];
        sort0[2][64+:8]<=sort0[1][64+:8];
        sort1[2][64+:8]<=sort1[1][64+:8];
        rgb_pipe[2]<=rgb_pipe[1];
        config_pipe[2]<=config_pipe[1];
        id_pipe[2]<=id_pipe[1];
        epoch_pipe[2]<=epoch_pipe[1];
        marks[2]<=marks[1];
    end
    always @(posedge clk) if(advance) begin
        sort0[3][0+:8]<=sort0[2][0+:8];
        sort1[3][0+:8]<=sort1[2][0+:8];
        sort0[3][8+:8]<=sort0[2][8+:8]<sort0[2][16+:8]?sort0[2][8+:8]:sort0[2][16+:8];
        sort1[3][8+:8]<=sort1[2][8+:8]<sort1[2][16+:8]?sort1[2][8+:8]:sort1[2][16+:8];
        sort0[3][16+:8]<=sort0[2][8+:8]<sort0[2][16+:8]?sort0[2][16+:8]:sort0[2][8+:8];
        sort1[3][16+:8]<=sort1[2][8+:8]<sort1[2][16+:8]?sort1[2][16+:8]:sort1[2][8+:8];
        sort0[3][24+:8]<=sort0[2][24+:8];
        sort1[3][24+:8]<=sort1[2][24+:8];
        sort0[3][32+:8]<=sort0[2][32+:8]<sort0[2][40+:8]?sort0[2][32+:8]:sort0[2][40+:8];
        sort1[3][32+:8]<=sort1[2][32+:8]<sort1[2][40+:8]?sort1[2][32+:8]:sort1[2][40+:8];
        sort0[3][40+:8]<=sort0[2][32+:8]<sort0[2][40+:8]?sort0[2][40+:8]:sort0[2][32+:8];
        sort1[3][40+:8]<=sort1[2][32+:8]<sort1[2][40+:8]?sort1[2][40+:8]:sort1[2][32+:8];
        sort0[3][48+:8]<=sort0[2][48+:8];
        sort1[3][48+:8]<=sort1[2][48+:8];
        sort0[3][56+:8]<=sort0[2][56+:8]<sort0[2][64+:8]?sort0[2][56+:8]:sort0[2][64+:8];
        sort1[3][56+:8]<=sort1[2][56+:8]<sort1[2][64+:8]?sort1[2][56+:8]:sort1[2][64+:8];
        sort0[3][64+:8]<=sort0[2][56+:8]<sort0[2][64+:8]?sort0[2][64+:8]:sort0[2][56+:8];
        sort1[3][64+:8]<=sort1[2][56+:8]<sort1[2][64+:8]?sort1[2][64+:8]:sort1[2][56+:8];
        rgb_pipe[3]<=rgb_pipe[2];
        config_pipe[3]<=config_pipe[2];
        id_pipe[3]<=id_pipe[2];
        epoch_pipe[3]<=epoch_pipe[2];
        marks[3]<=marks[2];
    end
    always @(posedge clk) if(advance) begin
        sort0[4][0+:8]<=sort0[3][0+:8]<sort0[3][24+:8]?sort0[3][0+:8]:sort0[3][24+:8];
        sort1[4][0+:8]<=sort1[3][0+:8]<sort1[3][24+:8]?sort1[3][0+:8]:sort1[3][24+:8];
        sort0[4][8+:8]<=sort0[3][8+:8];
        sort1[4][8+:8]<=sort1[3][8+:8];
        sort0[4][16+:8]<=sort0[3][16+:8];
        sort1[4][16+:8]<=sort1[3][16+:8];
        sort0[4][24+:8]<=sort0[3][0+:8]<sort0[3][24+:8]?sort0[3][24+:8]:sort0[3][0+:8];
        sort1[4][24+:8]<=sort1[3][0+:8]<sort1[3][24+:8]?sort1[3][24+:8]:sort1[3][0+:8];
        sort0[4][32+:8]<=sort0[3][32+:8]<sort0[3][56+:8]?sort0[3][32+:8]:sort0[3][56+:8];
        sort1[4][32+:8]<=sort1[3][32+:8]<sort1[3][56+:8]?sort1[3][32+:8]:sort1[3][56+:8];
        sort0[4][40+:8]<=sort0[3][40+:8]<sort0[3][64+:8]?sort0[3][40+:8]:sort0[3][64+:8];
        sort1[4][40+:8]<=sort1[3][40+:8]<sort1[3][64+:8]?sort1[3][40+:8]:sort1[3][64+:8];
        sort0[4][48+:8]<=sort0[3][48+:8];
        sort1[4][48+:8]<=sort1[3][48+:8];
        sort0[4][56+:8]<=sort0[3][32+:8]<sort0[3][56+:8]?sort0[3][56+:8]:sort0[3][32+:8];
        sort1[4][56+:8]<=sort1[3][32+:8]<sort1[3][56+:8]?sort1[3][56+:8]:sort1[3][32+:8];
        sort0[4][64+:8]<=sort0[3][40+:8]<sort0[3][64+:8]?sort0[3][64+:8]:sort0[3][40+:8];
        sort1[4][64+:8]<=sort1[3][40+:8]<sort1[3][64+:8]?sort1[3][64+:8]:sort1[3][40+:8];
        rgb_pipe[4]<=rgb_pipe[3];
        config_pipe[4]<=config_pipe[3];
        id_pipe[4]<=id_pipe[3];
        epoch_pipe[4]<=epoch_pipe[3];
        marks[4]<=marks[3];
    end
    always @(posedge clk) if(advance) begin
        sort0[5][0+:8]<=sort0[4][0+:8];
        sort1[5][0+:8]<=sort1[4][0+:8];
        sort0[5][8+:8]<=sort0[4][8+:8]<sort0[4][32+:8]?sort0[4][8+:8]:sort0[4][32+:8];
        sort1[5][8+:8]<=sort1[4][8+:8]<sort1[4][32+:8]?sort1[4][8+:8]:sort1[4][32+:8];
        sort0[5][16+:8]<=sort0[4][16+:8]<sort0[4][40+:8]?sort0[4][16+:8]:sort0[4][40+:8];
        sort1[5][16+:8]<=sort1[4][16+:8]<sort1[4][40+:8]?sort1[4][16+:8]:sort1[4][40+:8];
        sort0[5][24+:8]<=sort0[4][24+:8]<sort0[4][48+:8]?sort0[4][24+:8]:sort0[4][48+:8];
        sort1[5][24+:8]<=sort1[4][24+:8]<sort1[4][48+:8]?sort1[4][24+:8]:sort1[4][48+:8];
        sort0[5][32+:8]<=sort0[4][8+:8]<sort0[4][32+:8]?sort0[4][32+:8]:sort0[4][8+:8];
        sort1[5][32+:8]<=sort1[4][8+:8]<sort1[4][32+:8]?sort1[4][32+:8]:sort1[4][8+:8];
        sort0[5][40+:8]<=sort0[4][16+:8]<sort0[4][40+:8]?sort0[4][40+:8]:sort0[4][16+:8];
        sort1[5][40+:8]<=sort1[4][16+:8]<sort1[4][40+:8]?sort1[4][40+:8]:sort1[4][16+:8];
        sort0[5][48+:8]<=sort0[4][24+:8]<sort0[4][48+:8]?sort0[4][48+:8]:sort0[4][24+:8];
        sort1[5][48+:8]<=sort1[4][24+:8]<sort1[4][48+:8]?sort1[4][48+:8]:sort1[4][24+:8];
        sort0[5][56+:8]<=sort0[4][56+:8];
        sort1[5][56+:8]<=sort1[4][56+:8];
        sort0[5][64+:8]<=sort0[4][64+:8];
        sort1[5][64+:8]<=sort1[4][64+:8];
        rgb_pipe[5]<=rgb_pipe[4];
        config_pipe[5]<=config_pipe[4];
        id_pipe[5]<=id_pipe[4];
        epoch_pipe[5]<=epoch_pipe[4];
        marks[5]<=marks[4];
    end
    always @(posedge clk) if(advance) begin
        sort0[6][0+:8]<=sort0[5][0+:8];
        sort1[6][0+:8]<=sort1[5][0+:8];
        sort0[6][8+:8]<=sort0[5][8+:8];
        sort1[6][8+:8]<=sort1[5][8+:8];
        sort0[6][16+:8]<=sort0[5][16+:8];
        sort1[6][16+:8]<=sort1[5][16+:8];
        sort0[6][24+:8]<=sort0[5][24+:8];
        sort1[6][24+:8]<=sort1[5][24+:8];
        sort0[6][32+:8]<=sort0[5][32+:8]<sort0[5][56+:8]?sort0[5][32+:8]:sort0[5][56+:8];
        sort1[6][32+:8]<=sort1[5][32+:8]<sort1[5][56+:8]?sort1[5][32+:8]:sort1[5][56+:8];
        sort0[6][40+:8]<=sort0[5][40+:8];
        sort1[6][40+:8]<=sort1[5][40+:8];
        sort0[6][48+:8]<=sort0[5][48+:8];
        sort1[6][48+:8]<=sort1[5][48+:8];
        sort0[6][56+:8]<=sort0[5][32+:8]<sort0[5][56+:8]?sort0[5][56+:8]:sort0[5][32+:8];
        sort1[6][56+:8]<=sort1[5][32+:8]<sort1[5][56+:8]?sort1[5][56+:8]:sort1[5][32+:8];
        sort0[6][64+:8]<=sort0[5][64+:8];
        sort1[6][64+:8]<=sort1[5][64+:8];
        rgb_pipe[6]<=rgb_pipe[5];
        config_pipe[6]<=config_pipe[5];
        id_pipe[6]<=id_pipe[5];
        epoch_pipe[6]<=epoch_pipe[5];
        marks[6]<=marks[5];
    end
    always @(posedge clk) if(advance) begin
        sort0[7][0+:8]<=sort0[6][0+:8];
        sort1[7][0+:8]<=sort1[6][0+:8];
        sort0[7][8+:8]<=sort0[6][8+:8];
        sort1[7][8+:8]<=sort1[6][8+:8];
        sort0[7][16+:8]<=sort0[6][32+:8]<sort0[6][16+:8]?sort0[6][16+:8]:sort0[6][32+:8];
        sort1[7][16+:8]<=sort1[6][32+:8]<sort1[6][16+:8]?sort1[6][16+:8]:sort1[6][32+:8];
        sort0[7][24+:8]<=sort0[6][24+:8];
        sort1[7][24+:8]<=sort1[6][24+:8];
        sort0[7][32+:8]<=sort0[6][32+:8]<sort0[6][16+:8]?sort0[6][32+:8]:sort0[6][16+:8];
        sort1[7][32+:8]<=sort1[6][32+:8]<sort1[6][16+:8]?sort1[6][32+:8]:sort1[6][16+:8];
        sort0[7][40+:8]<=sort0[6][40+:8];
        sort1[7][40+:8]<=sort1[6][40+:8];
        sort0[7][48+:8]<=sort0[6][48+:8];
        sort1[7][48+:8]<=sort1[6][48+:8];
        sort0[7][56+:8]<=sort0[6][56+:8];
        sort1[7][56+:8]<=sort1[6][56+:8];
        sort0[7][64+:8]<=sort0[6][64+:8];
        sort1[7][64+:8]<=sort1[6][64+:8];
        rgb_pipe[7]<=rgb_pipe[6];
        config_pipe[7]<=config_pipe[6];
        id_pipe[7]<=id_pipe[6];
        epoch_pipe[7]<=epoch_pipe[6];
        marks[7]<=marks[6];
    end
    always @(posedge clk) if(advance) begin
        sort0[8][0+:8]<=sort0[7][0+:8];
        sort1[8][0+:8]<=sort1[7][0+:8];
        sort0[8][8+:8]<=sort0[7][8+:8];
        sort1[8][8+:8]<=sort1[7][8+:8];
        sort0[8][16+:8]<=sort0[7][16+:8];
        sort1[8][16+:8]<=sort1[7][16+:8];
        sort0[8][24+:8]<=sort0[7][24+:8];
        sort1[8][24+:8]<=sort1[7][24+:8];
        sort0[8][32+:8]<=sort0[7][48+:8]<sort0[7][32+:8]?sort0[7][32+:8]:sort0[7][48+:8];
        sort1[8][32+:8]<=sort1[7][48+:8]<sort1[7][32+:8]?sort1[7][32+:8]:sort1[7][48+:8];
        sort0[8][40+:8]<=sort0[7][40+:8];
        sort1[8][40+:8]<=sort1[7][40+:8];
        sort0[8][48+:8]<=sort0[7][48+:8]<sort0[7][32+:8]?sort0[7][48+:8]:sort0[7][32+:8];
        sort1[8][48+:8]<=sort1[7][48+:8]<sort1[7][32+:8]?sort1[7][48+:8]:sort1[7][32+:8];
        sort0[8][56+:8]<=sort0[7][56+:8];
        sort1[8][56+:8]<=sort1[7][56+:8];
        sort0[8][64+:8]<=sort0[7][64+:8];
        sort1[8][64+:8]<=sort1[7][64+:8];
        rgb_pipe[8]<=rgb_pipe[7];
        config_pipe[8]<=config_pipe[7];
        id_pipe[8]<=id_pipe[7];
        epoch_pipe[8]<=epoch_pipe[7];
        marks[8]<=marks[7];
    end
    always @(posedge clk) if(advance) begin
        sort0[9][0+:8]<=sort0[8][0+:8];
        sort1[9][0+:8]<=sort1[8][0+:8];
        sort0[9][8+:8]<=sort0[8][8+:8];
        sort1[9][8+:8]<=sort1[8][8+:8];
        sort0[9][16+:8]<=sort0[8][32+:8]<sort0[8][16+:8]?sort0[8][16+:8]:sort0[8][32+:8];
        sort1[9][16+:8]<=sort1[8][32+:8]<sort1[8][16+:8]?sort1[8][16+:8]:sort1[8][32+:8];
        sort0[9][24+:8]<=sort0[8][24+:8];
        sort1[9][24+:8]<=sort1[8][24+:8];
        sort0[9][32+:8]<=sort0[8][32+:8]<sort0[8][16+:8]?sort0[8][32+:8]:sort0[8][16+:8];
        sort1[9][32+:8]<=sort1[8][32+:8]<sort1[8][16+:8]?sort1[8][32+:8]:sort1[8][16+:8];
        sort0[9][40+:8]<=sort0[8][40+:8];
        sort1[9][40+:8]<=sort1[8][40+:8];
        sort0[9][48+:8]<=sort0[8][48+:8];
        sort1[9][48+:8]<=sort1[8][48+:8];
        sort0[9][56+:8]<=sort0[8][56+:8];
        sort1[9][56+:8]<=sort1[8][56+:8];
        sort0[9][64+:8]<=sort0[8][64+:8];
        sort1[9][64+:8]<=sort1[8][64+:8];
        rgb_pipe[9]<=rgb_pipe[8];
        config_pipe[9]<=config_pipe[8];
        id_pipe[9]<=id_pipe[8];
        epoch_pipe[9]<=epoch_pipe[8];
        marks[9]<=marks[8];
    end
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
                sort0[0]<={qx==1?pt[15:8]:lt,qx==1?pm[15:8]:lm,qx==1?pb[15:8]:lb,pt[15:8],pm[15:8],pb[15:8],pt[7:0],pm[7:0],pb[7:0]};
                sort1[0]<={pt[15:8],pm[15:8],pb[15:8],pt[7:0],pm[7:0],pb[7:0],q_tail?pt[7:0]:ct[15:8],q_tail?pm[7:0]:cm[15:8],q_tail?pb[7:0]:cb[15:8]};
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
