`timescale 1ns/1ps
module tb_vendor_lut_init;
    reg [3:0] inputs=0;
    wire [3:0] outputs;
    localparam [63:0] MASKS={16'haaaa,16'h0000,16'hffff,16'hc43f};
    genvar g;
    generate for(g=0;g<4;g=g+1) begin
        EFX_LUT4 #(.LUTMASK(MASKS[g*16+:16])) lut(
            .I0(inputs[0]),.I1(inputs[1]),.I2(inputs[2]),.I3(inputs[3]),.O(outputs[g]));
    end endgenerate
    integer i,j;
    initial begin
        #1;
        $display("initial LUT c43f at 0000: output=%b expected=1",outputs[0]);
        if(outputs!==4'b0011) $fatal(1,"constant-input LUT initialization differs from truth table");
        for(i=0;i<16;i=i+1) begin
            inputs=i;#1;
            for(j=0;j<4;j=j+1)
                if(outputs[j]!==MASKS[j*16+i]) $fatal(1,"truth table mismatch");
        end
        $display("PASS constant initialization and 64 truth-table entries");$finish;
    end
endmodule
