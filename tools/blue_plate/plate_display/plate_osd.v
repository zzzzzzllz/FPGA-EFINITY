`include "plate_defs.vh"
// One pixel clock latency for RGB and all video control signals.
module plate_osd #(parameter FONT_FILE="tools/blue_plate/plate_display/plate_font.mem", X=16,Y=656)(
 input clk,rst_n,input [10:0] x,y,input de,hs,vs,input [23:0] rgb,
 input [`PD_BITS:0] active_packet,
 output [23:0] out_rgb,output reg out_de,out_hs,out_vs
);
 (* syn_romstyle="block_rom" *) reg [31:0] font[0:4095];
 initial $readmemh(FONT_FILE,font);
 wire panel=de && x>=X && x<X+256 && y>=Y && y<Y+48;
 localparam [10:0] TEXT_X=X+16,TEXT_Y=Y+8;
 localparam [6:0] UNRECOGNIZED=`PD_UNRECOGNIZED;
 wire [10:0] tx=x-TEXT_X,ty=y-TEXT_Y;
 wire text_area=panel && tx<224 && ty<32;
 wire [5:0] id_bit_offset={tx[7:5],3'b000}-{3'b000,tx[7:5]};
 reg [6:0] glyph;
 always @* begin
  glyph=`PD_BLANK;
  if(text_area) begin
   if(active_packet[`PD_BITS]) glyph=active_packet[`PD_IDS_LSB+id_bit_offset +:7];
   else if(tx[7:5]>=2 && tx[7:5]<=4) glyph=UNRECOGNIZED+{4'd0,tx[7:5]}-7'd2;
  end
  if(glyph>`PD_BLANK) glyph=`PD_BLANK;
 end
 reg [31:0] row_bits;reg [4:0] column;
 reg panel_d,text_d;reg [23:0] rgb_d;
 always @(posedge clk or negedge rst_n) begin
  if(!rst_n) begin row_bits<=0;column<=0;panel_d<=0;text_d<=0;rgb_d<=0;out_de<=0;out_hs<=0;out_vs<=0;end
  else begin
   row_bits<=font[{glyph,ty[4:0]}];column<=tx[4:0];panel_d<=panel;text_d<=text_area;
   rgb_d<=rgb;out_de<=de;out_hs<=hs;out_vs<=vs;
  end
 end
 assign out_rgb=panel_d ? (text_d && row_bits[31-column] ? 24'hffffff : 24'h123b78) : rgb_d;
endmodule
