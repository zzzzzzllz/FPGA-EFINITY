`timescale 1ns/1ps
// Fixed 224x64 RGB -> 94x24 BGR bytes. One unrounded horizontal row, no frame RAM.
module ocr_resize_q8 (
    input wire clk,rst,abort,
    input wire start_valid,
    output wire start_ready,
    input wire [133:0] start_identity,
    input wire in_valid,
    output wire in_ready,
    input wire [23:0] in_rgb,
    input wire [13:0] in_address,
    input wire in_last,
    input wire source_done_valid,source_done_ok,
    output wire source_done_ready,
    output wire out_valid,
    input wire out_ready,
    output reg [23:0] out_bgr,
    output reg [11:0] out_address,
    output wire out_last,
    output reg [133:0] identity,
    input wire sink_done_valid,sink_done_ok,
    output wire sink_done_ready,
    output wire done_valid,
    input wire done_ready,
    output reg [2:0] done_status
);
    // Status: 0 complete, 1 malformed input, 2 source failure, 3 sink failure, 4 bad state.
    localparam IDLE=0,RECEIVE=1,H_SETUP=2,MULTIPLY=3,STORE=4,
               READ_ROW=5,V_SETUP=6,OUTPUT_PIXEL=7,WAIT_SOURCE=8,WAIT_SINK=9,HOLD=10;
    reg [3:0] state;
    wire reset_local=rst || abort;
    reg [13:0] count;
    reg [7:0] sx;
    reg [5:0] sy;
    reg [6:0] dx;
    reg [4:0] dy;
    reg bottom;
    reg [23:0] left_rgb,right_rgb;
    reg [1:0] channel;
    reg vertical;
    reg [2:0] bit_index;
    reg [7:0] fraction;
    reg signed [25:0] multiplicand,accumulator;
    reg [15:0] horizontal;
    (* syn_romstyle = "logic" *) wire [15:0] x_axis=axis_x(dx);
    (* syn_romstyle = "logic" *) wire [13:0] y_axis=axis_y(dy);
    wire [7:0] x0=x_axis[15:8],fx=x_axis[7:0];
    wire [5:0] y0=y_axis[13:8];
    wire [7:0] fy=y_axis[7:0];
    // Channel order is B,G,R; the output word puts B in bits 23:16.
    wire [7:0] left_byte=channel==0 ? left_rgb[7:0] : channel==1 ? left_rgb[15:8] : left_rgb[23:16];
    wire [7:0] right_byte=channel==0 ? right_rgb[7:0] : channel==1 ? right_rgb[15:8] : right_rgb[23:16];
    wire signed [25:0] partial=accumulator+(fraction[0] ? multiplicand : 26'sd0);
    wire signed [25:0] horizontal_sum=$signed({10'd0,left_byte,8'd0})+partial;
    wire [15:0] row_data;
    wire signed [25:0] vertical_sum=$signed({2'd0,row_data,8'd0})+partial+26'sd32768;
    wire [8:0] row_address=({2'd0,dx}<<1)+{2'd0,dx}+{7'd0,channel};
    wire row_write=state==STORE && !reset_local;
    EFX_RAM10 #(.READ_WIDTH(16),.WRITE_WIDTH(16),.OUTPUT_REG(0),
        .WRITE_MODE("READ_UNKNOWN"),.RESET_RAM("SYNC"),.RESET_OUTREG("NONE")) row_ram (
        .WCLK(clk),.WCLKE(1'b1),.WADDREN(1'b1),.WE({2{row_write}}),.WDATA(horizontal),.WADDR(row_address),
        .RCLK(clk),.RE(state==READ_ROW && !reset_local),.RST(1'b0),.RADDREN(1'b1),.RADDR(row_address),.RDATA(row_data));
    assign start_ready=state==IDLE && !reset_local;
    assign in_ready=state==RECEIVE && !reset_local;
    assign out_valid=state==OUTPUT_PIXEL && !reset_local;
    assign out_last=out_address==2255;
    assign source_done_ready=state==WAIT_SOURCE && !reset_local;
    assign sink_done_ready=state==WAIT_SINK && !reset_local;
    assign done_valid=state==HOLD && !reset_local;

    always @(posedge clk) begin
        if(reset_local) begin
            state<=IDLE;count<=0;sx<=0;sy<=0;dx<=0;dy<=0;bottom<=0;
            left_rgb<=0;right_rgb<=0;channel<=0;vertical<=0;bit_index<=0;fraction<=0;
            multiplicand<=0;accumulator<=0;horizontal<=0;out_bgr<=0;out_address<=0;
            identity<=0;done_status<=0;
        end else case(state)
            IDLE: if(start_valid) begin
                identity<=start_identity;count<=0;sx<=0;sy<=0;dx<=0;dy<=0;bottom<=0;
                out_address<=0;out_bgr<=0;done_status<=0;state<=RECEIVE;
            end
            RECEIVE: if(in_valid) begin
                if(in_address!=count || in_last!=(count==14335)) begin
                    done_status<=1;state<=HOLD;
                end else begin
                    count<=count+1'b1;
                    if(sx==223) begin sx<=0;sy<=sy+1'b1;end else sx<=sx+1'b1;
                    if(sy==y0+bottom) begin
                        if(sx==x0) left_rgb<=in_rgb;
                        if(sx==x0+1'b1) begin right_rgb<=in_rgb;channel<=0;state<=H_SETUP;end
                    end
                end
            end
            H_SETUP: begin
                multiplicand<=$signed({1'b0,right_byte})-$signed({1'b0,left_byte});
                fraction<=fx;bit_index<=0;accumulator<=0;vertical<=0;state<=MULTIPLY;
            end
            MULTIPLY: begin
                accumulator<=partial;multiplicand<=multiplicand<<<1;fraction<=fraction>>1;
                if(bit_index==7) begin
                    if(!vertical) begin horizontal<=horizontal_sum[15:0];state<=bottom ? READ_ROW : STORE;end
                    else begin
                        case(channel)
                            0:out_bgr[23:16]<=vertical_sum[23:16];
                            1:out_bgr[15:8]<=vertical_sum[23:16];
                            2:out_bgr[7:0]<=vertical_sum[23:16];
                        endcase
                        if(channel==2) state<=OUTPUT_PIXEL;
                        else begin channel<=channel+1'b1;state<=H_SETUP;end
                    end
                end else bit_index<=bit_index+1'b1;
            end
            STORE: begin
                if(channel!=2) begin channel<=channel+1'b1;state<=H_SETUP;end
                else begin
                    if(dx==93) begin dx<=0;bottom<=1;end else dx<=dx+1'b1;
                    state<=RECEIVE;
                end
            end
            READ_ROW: state<=V_SETUP;
            V_SETUP: begin
                multiplicand<=$signed({1'b0,horizontal})-$signed({1'b0,row_data});
                fraction<=fy;bit_index<=0;accumulator<=0;vertical<=1;state<=MULTIPLY;
            end
            OUTPUT_PIXEL: if(out_ready) begin
                if(out_last) state<=WAIT_SOURCE;
                else begin
                    out_address<=out_address+1'b1;
                    if(dx==93) begin dx<=0;dy<=dy+1'b1;bottom<=0;end else dx<=dx+1'b1;
                    state<=RECEIVE;
                end
            end
            WAIT_SOURCE: if(source_done_valid) begin
                if(source_done_ok) state<=WAIT_SINK;
                else begin done_status<=2;state<=HOLD;end
            end
            WAIT_SINK: if(sink_done_valid) begin
                done_status<=sink_done_ok ? 0 : 3;state<=HOLD;
            end
            HOLD: if(done_ready) state<=IDLE;
            default: begin done_status<=4;state<=HOLD;end
        endcase
    end

    // Fixed axis constants are checked against experiment.axis_lut for every entry.
    function [15:0] axis_x(input [6:0] index);
        begin case(index)
            0:axis_x=16'hb1;
            1:axis_x=16'h313;
            2:axis_x=16'h575;
            3:axis_x=16'h7d7;
            4:axis_x=16'ha39;
            5:axis_x=16'hc9b;
            6:axis_x=16'hefd;
            7:axis_x=16'h115f;
            8:axis_x=16'h13c1;
            9:axis_x=16'h1623;
            10:axis_x=16'h1885;
            11:axis_x=16'h1ae7;
            12:axis_x=16'h1d4a;
            13:axis_x=16'h1fac;
            14:axis_x=16'h220e;
            15:axis_x=16'h2470;
            16:axis_x=16'h26d2;
            17:axis_x=16'h2934;
            18:axis_x=16'h2b96;
            19:axis_x=16'h2df8;
            20:axis_x=16'h305a;
            21:axis_x=16'h32bc;
            22:axis_x=16'h351e;
            23:axis_x=16'h3780;
            24:axis_x=16'h39e2;
            25:axis_x=16'h3c44;
            26:axis_x=16'h3ea6;
            27:axis_x=16'h4108;
            28:axis_x=16'h436a;
            29:axis_x=16'h45cc;
            30:axis_x=16'h482e;
            31:axis_x=16'h4a90;
            32:axis_x=16'h4cf2;
            33:axis_x=16'h4f54;
            34:axis_x=16'h51b6;
            35:axis_x=16'h5419;
            36:axis_x=16'h567b;
            37:axis_x=16'h58dd;
            38:axis_x=16'h5b3f;
            39:axis_x=16'h5da1;
            40:axis_x=16'h6003;
            41:axis_x=16'h6265;
            42:axis_x=16'h64c7;
            43:axis_x=16'h6729;
            44:axis_x=16'h698b;
            45:axis_x=16'h6bed;
            46:axis_x=16'h6e4f;
            47:axis_x=16'h70b1;
            48:axis_x=16'h7313;
            49:axis_x=16'h7575;
            50:axis_x=16'h77d7;
            51:axis_x=16'h7a39;
            52:axis_x=16'h7c9b;
            53:axis_x=16'h7efd;
            54:axis_x=16'h815f;
            55:axis_x=16'h83c1;
            56:axis_x=16'h8623;
            57:axis_x=16'h8885;
            58:axis_x=16'h8ae7;
            59:axis_x=16'h8d4a;
            60:axis_x=16'h8fac;
            61:axis_x=16'h920e;
            62:axis_x=16'h9470;
            63:axis_x=16'h96d2;
            64:axis_x=16'h9934;
            65:axis_x=16'h9b96;
            66:axis_x=16'h9df8;
            67:axis_x=16'ha05a;
            68:axis_x=16'ha2bc;
            69:axis_x=16'ha51e;
            70:axis_x=16'ha780;
            71:axis_x=16'ha9e2;
            72:axis_x=16'hac44;
            73:axis_x=16'haea6;
            74:axis_x=16'hb108;
            75:axis_x=16'hb36a;
            76:axis_x=16'hb5cc;
            77:axis_x=16'hb82e;
            78:axis_x=16'hba90;
            79:axis_x=16'hbcf2;
            80:axis_x=16'hbf54;
            81:axis_x=16'hc1b6;
            82:axis_x=16'hc419;
            83:axis_x=16'hc67b;
            84:axis_x=16'hc8dd;
            85:axis_x=16'hcb3f;
            86:axis_x=16'hcda1;
            87:axis_x=16'hd003;
            88:axis_x=16'hd265;
            89:axis_x=16'hd4c7;
            90:axis_x=16'hd729;
            91:axis_x=16'hd98b;
            92:axis_x=16'hdbed;
            93:axis_x=16'hde4f;
            default:axis_x=0;
        endcase end
    endfunction
    function [13:0] axis_y(input [4:0] index);
        begin case(index)
            0:axis_y=14'hd5;
            1:axis_y=14'h380;
            2:axis_y=14'h62b;
            3:axis_y=14'h8d5;
            4:axis_y=14'hb80;
            5:axis_y=14'he2b;
            6:axis_y=14'h10d5;
            7:axis_y=14'h1380;
            8:axis_y=14'h162b;
            9:axis_y=14'h18d5;
            10:axis_y=14'h1b80;
            11:axis_y=14'h1e2b;
            12:axis_y=14'h20d5;
            13:axis_y=14'h2380;
            14:axis_y=14'h262b;
            15:axis_y=14'h28d5;
            16:axis_y=14'h2b80;
            17:axis_y=14'h2e2b;
            18:axis_y=14'h30d5;
            19:axis_y=14'h3380;
            20:axis_y=14'h362b;
            21:axis_y=14'h38d5;
            22:axis_y=14'h3b80;
            23:axis_y=14'h3e2b;
            default:axis_y=0;
        endcase end
    endfunction

endmodule
