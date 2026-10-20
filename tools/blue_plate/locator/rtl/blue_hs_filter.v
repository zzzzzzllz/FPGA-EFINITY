// Exact H=101..139, S=96..254 predicate. value_allowed is the same-frame
// equalized-V gate (96..254), supplied with each input pixel by the caller.
module blue_hs_filter #(
    parameter SAT_FILE="blue_saturation.mem",
    parameter HUE_FILE="blue_hue.mem"
)(
    input wire clk, rst, abort,
    input wire in_valid,
    output wire in_ready,
    input wire [23:0] rgb,
    input wire value_allowed,
    output wire out_valid,
    input wire out_ready,
    output reg blue
);
    reg [15:0] saturation_rom [0:255];
    reg [17:0] hue_rom [0:255];
    initial begin
        $readmemh(SAT_FILE,saturation_rom);
        $readmemh(HUE_FILE,hue_rom);
    end
    wire [7:0] r=rgb[23:16],g=rgb[15:8],b=rgb[7:0];
    wire [7:0] difference=b-((r<g)?r:g);
    wire signed [8:0] rg=$signed({1'b0,r})-$signed({1'b0,g});
    reg valid1,valid2;
    reg [7:0] d1;
    reg signed [8:0] z1;
    reg allowed1;
    reg [15:0] saturation1;
    reg [17:0] hue1;
    wire advance=!valid2 || out_ready;
    assign in_ready=advance && !rst && !abort;
    assign out_valid=valid2 && !rst && !abort;
    always @(posedge clk) begin
        if(rst || abort)begin
            valid1<=0;valid2<=0;
        end else if(advance)begin
            valid1<=in_valid;
            valid2<=valid1;
            if(in_valid)begin
                saturation1<=saturation_rom[b];
                hue1<=hue_rom[difference];
                d1<=difference;z1<=rg;
                allowed1<=value_allowed && b>r && b>g;
            end
            if(valid1)
                blue<=allowed1 && d1>=saturation1[7:0] && d1<=saturation1[15:8] &&
                      z1 >= $signed(hue1[8:0]) && z1 <= $signed(hue1[17:9]);
        end
    end
endmodule
