module psum_weight_mac8 (
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
    input wire save, restore,
    input wire [5:0] slot,
    output wire busy,
    output reg done,
    output wire command_error,
    output wire read_valid,
    output wire [255:0] psum,
    output wire [7:0] updated, overflow
);
    localparam IDLE=0, SAVE=1, READ=2, CAPTURE=3;
    reg [1:0] state;
    reg [5:0] slot_q;
    reg [2:0] lane;
    reg local_error;
    wire core_error;
    wire normal_cmd=wr_en || issue || load;
    wire any_cmd=normal_cmd || save || restore;
    wire bad_partial=(save && restore) || normal_cmd || read_valid;
    wire forward_normal=state==IDLE && !save && !restore;
    wire [8:0] address={slot_q,lane};
    wire [31:0] ram_data;
    wire [31:0] save_data=psum[lane*32 +: 32];
    wire [255:0] restore_seed;
    assign busy=state!=IDLE;
    assign command_error=local_error || core_error;
    genvar i;
    generate for(i=0;i<8;i=i+1) begin: restore_lane
        assign restore_seed[i*32 +: 32]=(lane==i) ? ram_data : psum[i*32 +: 32];
    end endgenerate
    always @(posedge clk) begin
        if (rst) begin
            state<=IDLE; slot_q<=0; lane<=0; done<=0; local_error<=0;
        end else begin
            local_error<=ce && (busy ? any_cmd : ((save || restore) && bad_partial));
            if (ce) begin
                done<=0;
                case(state)
                    IDLE: if ((save || restore) && !bad_partial) begin
                        slot_q<=slot; lane<=0; state<=save ? SAVE : READ;
                    end
                    SAVE: if (lane==7) begin state<=IDLE; done<=1; end
                          else lane<=lane+1'b1;
                    READ: state<=CAPTURE;
                    CAPTURE: if (lane==7) begin state<=IDLE; done<=1; end
                             else begin lane<=lane+1'b1; state<=READ; end
                endcase
            end
        end
    end
    generate for(i=0;i<2;i=i+1) begin: partial_ram
        EFX_RAM10 #(.READ_WIDTH(16),.WRITE_WIDTH(16),.OUTPUT_REG(0),
            .WRITE_MODE("READ_UNKNOWN"),.RESET_RAM("SYNC"),.RESET_OUTREG("NONE")) ram (
            .WCLK(clk),.WCLKE(ce),.WADDREN(1'b1),
            .WE({2{ce && !rst && state==SAVE}}),.WADDR(address),.WDATA(save_data[i*16 +: 16]),
            .RCLK(clk),.RE(rst || (ce && state==READ)),.RST(rst),.RADDREN(1'b1),
            .RADDR(address),.RDATA(ram_data[i*16 +: 16])
        );
    end endgenerate
    weight_mac8 core (
        .clk(clk),.rst(rst),.ce(ce && (state==IDLE || state==CAPTURE)),
        .wr_en(wr_en && forward_normal),.wr_addr(wr_addr),.wr_data(wr_data),
        .issue(issue && forward_normal),.rd_addr(rd_addr),.activation(activation),.lane_mask(lane_mask),
        .load(state==CAPTURE || (load && forward_normal)),
        .seed(state==CAPTURE ? restore_seed : seed),
        .weight_data(),.read_valid(read_valid),.command_error(core_error),
        .psum(psum),.updated(updated),.overflow(overflow)
    );
endmodule
