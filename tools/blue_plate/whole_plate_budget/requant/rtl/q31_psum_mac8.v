// Requantization borrows the single frozen bank/MAC; host saves live sums first.
module q31_psum_mac8 (
    input wire clk,rst,ce,
    input wire wr_en,issue,load,save,restore,
    input wire [10:0] wr_addr,rd_addr,
    input wire [63:0] wr_data,
    input wire [135:0] activation,
    input wire [7:0] lane_mask,
    input wire [255:0] seed,
    input wire [5:0] slot,
    output wire busy,done,read_valid,command_error,
    output wire [255:0] psum,
    output wire [7:0] updated,overflow,
    input wire q_start,q_reuse,q_relu,q_ready,
    input wire signed [31:0] q_acc,
    input wire [30:0] q_multiplier,
    input wire [5:0] q_shift,
    input wire signed [7:0] q_zero,
    output wire q_busy,q_valid,
    output reg signed [7:0] q_result
);
    localparam IDLE=0,W0=1,W1=2,L0=3,I0=4,D0=5,S0=6,
               L1=7,I1=8,D1=9,S1=10,SHIFT=11,FINISH=12,RESULT=13;
    reg [3:0] state;
    reg signed [31:0] original;
    reg original_valid,relu_q,sticky,local_error;
    reg [30:0] multiplier;
    reg [5:0] remaining;
    reg signed [7:0] zero_q;
    reg signed [63:0] product;
    reg [2:0] index;
    wire host_command=wr_en || issue || load || save || restore;
    wire core_error,core_busy;
    wire pass_host=state==IDLE && !q_start;
    wire bad_request=q_busy || core_busy || read_valid || host_command ||
                     q_multiplier==0 || q_shift==0 || q_shift==63 ||
                     (q_reuse && !original_valid);
    wire [31:0] a=(relu_q && original[31]) ? 32'd0 : original;
    wire [7:0] m0={1'b0,multiplier[6:0]},m1={1'b0,multiplier[13:7]},
               m2={1'b0,multiplier[20:14]},m3={1'b0,multiplier[27:21]},
               m4={5'b0,multiplier[30:28]};
    wire [63:0] weight0={m2,m1,m0,m4,m3,m2,m1,m0};
    wire [63:0] weight1={48'b0,m4,m3};
    wire [135:0] pieces;
    genvar i;
    generate for(i=0;i<8;i=i+1) begin: piece
        if(i<5) assign pieces[i*17 +:17]=(state==I1) ? {a[31],a[31:16]} : {1'b0,a[15:0]};
        else assign pieces[i*17 +:17]={a[31],a[31:16]};
    end endgenerate
    wire [31:0] partial=psum[index*32 +:32];
    wire signed [63:0] extended={{32{partial[31]}},partial};
    reg signed [63:0] term;
    always @* begin
        if(state==S1) term=index==0 ? extended<<<37 : extended<<<44;
        else case(index)
            0:term=extended; 1:term=extended<<<7; 2:term=extended<<<14;
            3:term=extended<<<21; 4:term=extended<<<28; 5:term=extended<<<16;
            6:term=extended<<<23; 7:term=extended<<<30;
        endcase
    end
    wire signed [63:0] translated=product+{{56{zero_q[7]}},zero_q};
    assign q_busy=state!=IDLE;
    assign q_valid=state==RESULT;
    assign busy=core_busy || q_busy;
    assign command_error=core_error || local_error;
    always @(posedge clk) begin
        if(rst) begin
            state<=IDLE;original<=0;original_valid<=0;multiplier<=0;remaining<=0;
            relu_q<=0;zero_q<=0;product<=0;index<=0;sticky<=0;local_error<=0;q_result<=0;
        end else begin
            local_error<=ce && ((q_start && bad_request) || (q_busy && host_command));
            if(ce) case(state)
                IDLE:if(q_start && !bad_request) begin
                    if(!q_reuse) original<=q_acc;
                    original_valid<=1;multiplier<=q_multiplier;remaining<=q_shift;
                    relu_q<=q_relu;zero_q<=q_zero;product<=0;sticky<=0;index<=0;state<=W0;
                end
                W0:state<=W1;
                W1:state<=L0;
                L0:state<=I0;
                I0:state<=D0;
                D0:state<=S0;
                S0:begin
                    product<=product+term;
                    if(index==7) begin index<=0;state<=L1;end else index<=index+1'b1;
                end
                L1:state<=I1;
                I1:state<=D1;
                D1:state<=S1;
                S1:begin
                    product<=product+term;
                    if(index==1) begin index<=0;state<=SHIFT;end else index<=index+1'b1;
                end
                SHIFT:begin
                    if(remaining==1) begin
                        product<=(product>>>1)+((product[0] && (sticky || product[1])) ? 64'sd1 : 64'sd0);
                        state<=FINISH;
                    end else begin product<=product>>>1;sticky<=sticky || product[0];remaining<=remaining-1'b1;end
                end
                FINISH:begin
                    q_result<=translated>127 ? 8'sd127 : translated< -128 ? -8'sd128 : translated[7:0];
                    state<=RESULT;
                end
                RESULT:if(q_ready) state<=IDLE;
            endcase
        end
    end
    psum_weight_mac8 core (
        .clk(clk),.rst(rst),.ce(ce),
        .wr_en(pass_host ? wr_en : (state==W0 || state==W1)),
        .wr_addr(pass_host ? wr_addr : (state==W1 ? 11'd2047 : 11'd2046)),
        .wr_data(pass_host ? wr_data : (state==W1 ? weight1 : weight0)),
        .issue(pass_host ? issue : (state==I0 || state==I1)),
        .rd_addr(pass_host ? rd_addr : (state==I1 ? 11'd2047 : 11'd2046)),
        .activation(pass_host ? activation : pieces),
        .lane_mask(pass_host ? lane_mask : (state==I1 ? 8'h03 : 8'hff)),
        .load(pass_host ? load : (state==L0 || state==L1)),
        .seed(pass_host ? seed : 256'b0),.save(save && pass_host),.restore(restore && pass_host),.slot(slot),
        .busy(core_busy),.done(done),.command_error(core_error),.read_valid(read_valid),
        .psum(psum),.updated(updated),.overflow(overflow)
    );
endmodule
