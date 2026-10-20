`include "plate_defs.vh"
// The original glyph bits, selected before a one-cycle synchronous ROM read.
module plate_osd_compact #(parameter FONT_LOW_FILE="font-low.mem", FONT_HIGH_FILE="font-high.mem", X=16,Y=656)(
 input clk,rst_n,input [10:0] x,y,input de,hs,vs,input [23:0] rgb,
 input [`PD_BITS:0] active_packet,
 output [23:0] out_rgb,output reg out_de,out_hs,out_vs
);
 (* syn_romstyle="block_rom" *) reg font_low[0:65535];
 (* syn_romstyle="block_rom" *) reg font_high[0:4095];
 initial begin $readmemh(FONT_LOW_FILE,font_low);$readmemh(FONT_HIGH_FILE,font_high);end
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
 reg low_bit,high_bit,high_d,blank_d;
 reg panel_d,text_d;reg [23:0] rgb_d;
 always @(posedge clk or negedge rst_n) begin
  if(!rst_n) begin low_bit<=0;high_bit<=0;high_d<=0;blank_d<=0;panel_d<=0;text_d<=0;rgb_d<=0;out_de<=0;out_hs<=0;out_vs<=0;end
  else begin
   low_bit<=font_low[{glyph[5:0],ty[4:0],tx[4:0]}];
   high_bit<=font_high[{glyph[1:0],ty[4:0],tx[4:0]}];
   high_d<=glyph[6];blank_d<=glyph==`PD_BLANK;panel_d<=panel;text_d<=text_area;
   rgb_d<=rgb;out_de<=de;out_hs<=hs;out_vs<=vs;
  end
 end
 wire ink=!blank_d && (high_d ? high_bit : low_bit);
 assign out_rgb=panel_d ? (text_d && ink ? 24'hffffff : 24'h123b78) : rgb_d;
endmodule
