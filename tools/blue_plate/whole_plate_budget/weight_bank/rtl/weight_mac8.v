// One synchronous weight-read stage feeding the frozen mac8 arithmetic unit.
module weight_mac8 (
    input wire clk, rst, ce,
    input wire wr_en,
    input wire [10:0] wr_addr,
    input wire [63:0] wr_data,
    input wire issue,
    input wire [10:0] rd_addr,
    input wire [135:0] activation,
    input wire [7:0] lane_mask,
    input wire load,
    input wire [255:0] seed,
    output wire [63:0] weight_data,
    output wire read_valid,
    output reg command_error,
    output wire [255:0] psum,
    output wire [7:0] updated, overflow
);
    wire invalid_command=(wr_en && issue) || (load && (wr_en || issue)) ||
                         ((wr_en || load) && read_valid);
    wire issue_ok=issue && !invalid_command;
    reg [135:0] activation_q;
    reg [7:0] mask_q;
    always @(posedge clk) begin
        if (rst) command_error<=0;
        else command_error<=ce && invalid_command;
        if (!rst && ce && issue_ok) begin
            activation_q<=activation;
            mask_q<=lane_mask;
        end
    end
    weight_bank8 weights (
        .clk(clk), .rst(rst), .ce(ce),
        .wr_en(wr_en && !invalid_command), .wr_addr(wr_addr), .wr_data(wr_data),
        .rd_en(issue_ok), .rd_addr(rd_addr), .rd_data(weight_data),
        .rd_valid(read_valid), .conflict()
    );
    mac8 arithmetic (
        .clk(clk), .rst(rst), .ce(ce), .valid(read_valid),
        .load(load && !invalid_command), .lane_mask(mask_q),
        .activation(activation_q), .weight(weight_data), .seed(seed),
        .psum(psum), .updated(updated), .overflow(overflow)
    );
endmodule
