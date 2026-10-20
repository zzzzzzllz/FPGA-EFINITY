// 2048 rows x eight signed-byte weights; four depth groups x four width banks.
module weight_bank8 (
    input wire clk, rst, ce,
    input wire wr_en,
    input wire [10:0] wr_addr,
    input wire [63:0] wr_data,
    input wire rd_en,
    input wire [10:0] rd_addr,
    output wire [63:0] rd_data,
    output reg rd_valid,
    output reg conflict
);
    wire wr_fire=ce && !rst && wr_en && !rd_en;
    wire rd_fire=ce && !rst && rd_en && !wr_en;
    reg [1:0] selected;
    wire [63:0] group_data [0:3];
    assign rd_data=group_data[selected];
    always @(posedge clk) begin
        if (rst) begin
            selected<=0;
            rd_valid<=0;
            conflict<=0;
        end else begin
            conflict<=ce && wr_en && rd_en;
            if (ce) begin
                rd_valid<=rd_fire;
                if (rd_fire) selected<=rd_addr[10:9];
            end
        end
    end
    genvar g,b;
    generate for (g=0;g<4;g=g+1) begin: depth
        for (b=0;b<4;b=b+1) begin: width_bank
            EFX_RAM10 #(
                .READ_WIDTH(16), .WRITE_WIDTH(16), .OUTPUT_REG(0),
                .WRITE_MODE("READ_UNKNOWN"), .RESET_RAM("SYNC"), .RESET_OUTREG("NONE")
            ) ram (
                .WCLK(clk), .WCLKE(ce), .WADDREN(1'b1),
                .WE({2{wr_fire && wr_addr[10:9]==g}}),
                .WDATA(wr_data[b*16 +: 16]), .WADDR(wr_addr[8:0]),
                .RCLK(clk), .RE(rst || (rd_fire && rd_addr[10:9]==g)),
                .RST(rst), .RADDREN(1'b1), .RADDR(rd_addr[8:0]),
                .RDATA(group_data[g][b*16 +: 16])
            );
        end
    end endgenerate
endmodule
