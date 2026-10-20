// Eight independent signed-17 x signed-8 lanes with explicit int32 state.
module mac8 (
    input wire clk,
    input wire rst,
    input wire ce,
    input wire valid,
    input wire load,
    input wire [7:0] lane_mask,
    input wire [135:0] activation,
    input wire [63:0] weight,
    input wire [255:0] seed,
    output wire [255:0] psum,
    output reg [7:0] updated,
    output reg [7:0] overflow
);
    genvar i;
    generate for (i=0; i<8; i=i+1) begin: lane
        wire signed [16:0] a = activation[i*17 +: 17];
        wire signed [7:0] w = weight[i*8 +: 8];
        wire [47:0] product;
        reg signed [31:0] acc;
        wire signed [32:0] sum = $signed({acc[31],acc}) + $signed(product[32:0]);

        // The DSP supplies the product. Fabric holds the reloadable int32 sum;
        // CASCIN is a dedicated cascade port, not a general 32-bit seed bus.
        EFX_DSP48 #(
            .MODE("NORMAL"), .SIGNED(1), .W_SEL("P"),
            .A_REG(0), .B_REG(0), .P_REG(0), .W_REG(0), .O_REG(0),
            .SHIFTER(0), .RST_SYNC(1)
        ) multiply (
            .A({{2{a[16]}},a}), .B({{10{w[7]}},w}), .C(18'd0),
            .CASCIN(48'd0), .OP(2'b00), .SHIFT_ENA(1'b0),
            .CLK(1'b0), .CE(1'b0), .RST(1'b0),
            .O(product), .CASCOUT(), .OVFL()
        );
        assign psum[i*32 +: 32] = acc;
        always @(posedge clk) begin
            if (rst) begin
                acc <= 32'sd0;
                updated[i] <= 1'b0;
                overflow[i] <= 1'b0;
            end else begin
                updated[i] <= 1'b0;
                overflow[i] <= 1'b0;
                if (ce && load) begin
                    acc <= seed[i*32 +: 32];
                    updated[i] <= 1'b1;
                end else if (ce && valid && lane_mask[i]) begin
                    acc <= sum[31:0];
                    updated[i] <= 1'b1;
                    overflow[i] <= sum[32] != sum[31];
                end
            end
        end
    end endgenerate
endmodule
