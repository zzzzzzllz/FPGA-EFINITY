// Read the frame's T from FIFO metadata; overlay only the bottom status strip.
module threshold_osd #(parameter W=1280,H=720)(
 input clk,rst_n,vs,de,
 input [6:0] metadata,input [23:0] rgb,
 output [23:0] out_rgb,output reg [10:0] shown_threshold,output reg [2:0] shown_flags,
 output reg [300:0] shown_descriptor,output reg shown_toggle,
 input [63:0] ui_status
);
 reg [10:0] x,y;
 reg [6:0] low_bits;
 reg vs_d;
 reg [10:0] binary;
 reg [15:0] bcd,adjusted;
 reg [3:0] bits_left;
 reg [300:0] descriptor_bits;
 integer i;
 always @* begin
  adjusted=bcd;
  for(i=0;i<4;i=i+1)
   if(bcd[i*4 +:4]>=5) adjusted[i*4 +:4]=bcd[i*4 +:4]+4'd3;
 end
 always @(posedge clk) begin
  if(!rst_n) begin
   x<=0;y<=0;vs_d<=0;low_bits<=32;shown_threshold<=32;shown_flags<=1;
   binary<=0;bcd<=16'h0032;bits_left<=0;
   shown_descriptor<=0;shown_toggle<=0;descriptor_bits<=0;
  end else begin
   vs_d<=vs;
   if(vs && !vs_d) begin x<=0;y<=0;end
   else if(de) begin
    if(x==W-1) begin x<=0;y<=y+1'b1;end else x<=x+1'b1;
    if(y==0 && x==0) low_bits<=metadata;
    if(y==0 && x==1) begin
     shown_flags<=metadata[6:4];shown_threshold<={metadata[3:0],low_bits};
     binary<={metadata[3:0],low_bits};bcd<=0;bits_left<=11;
    end
    if(y==0 && x>=2 && x<=44) begin
     descriptor_bits<={metadata,descriptor_bits[300:7]};
     if(x==44) begin
      shown_descriptor<={metadata,descriptor_bits[300:7]};shown_toggle<=!shown_toggle;
     end
    end
   end
   if(bits_left!=0) begin
    bcd<={adjusted[14:0],binary[10]};binary<=binary<<1;bits_left<=bits_left-1'b1;
   end
  end
 end
 reg [7:0] character;
 function [7:0] hex_digit;
  input [3:0] n;
  begin hex_digit=n<10 ? 8'd48+n : 8'd65+n-10;end
 endfunction
 reg [31:0] frame_number;
 wire top_strip=y>=8 && y<24;
 wire [6:0] top_column=x[10:4];
 reg [7:0] top_character;
 // One byte lookup avoids storing and multiplexing every label in parallel.
 localparam [4095:0] MENU_TEXT={
  "VIEW COLOR      VIEW GRAY       VIEW EDGE       VIEW COMPARE    ",
  "VIEW DENOISE    VIEW OVERLAY    VIEW REFERENCE  ALGORITHM SOBEL ",
  "ALGORITHM CANNY THRESHOLD       LOW RATIO 1/4   LOW RATIO 1/2   ",
  "LOW RATIO 3/4   MEDIAN OFF      MEDIAN ON       RECOGNITION OFF ",
  "RECOGNITION ON  FRAME CANCEL    FRAME STEP LIVE FRAME RECORD 32 ",
  "FRAME PLAY LOOP FRAME PAUSE     FRAME NEXT CLIP FRAME SET REF   ",
  "FRAME LIVE      FRAME CLEAR REF  NEXT K2- K3+   HOLD K1 FREEZE/L",
  "IVE                                                             "};
 (* syn_romstyle="block_rom" *) reg [7:0] menu_rom[0:511];
 integer menu_i;
 initial for(menu_i=0;menu_i<512;menu_i=menu_i+1)
  menu_rom[menu_i]=MENU_TEXT[(511-menu_i)*8 +:8];
 reg [4:0] menu_label_id;
 reg [8:0] menu_address;
 reg [7:0] menu_character;
 wire [6:0] menu_column=x[10:4];
 always @* begin
  menu_label_id=31;
  case(ui_status[2:0])
   0:if(ui_status[9:7]<=6) menu_label_id={2'd0,ui_status[9:7]};
   1:menu_label_id=ui_status[16]?8:7;
   2:menu_label_id=9;
   3:if(ui_status[18:17]<=2) menu_label_id=10+{3'd0,ui_status[18:17]};
   4:menu_label_id=ui_status[10]?14:13;
   5:menu_label_id=ui_status[23]?16:15;
   6:if(ui_status[6:3]<=8) menu_label_id=17+{1'b0,ui_status[6:3]};
   default:;
  endcase
  menu_address=511;
  if(menu_column>=1 && menu_column<=16) menu_address={menu_label_id,4'd0}+menu_column-1'b1;
  if(menu_column>=17 && menu_column<=64) menu_address=9'd399+menu_column;
  menu_character=menu_rom[menu_address];
  if(ui_status[2:0]==6) case(menu_column)
   18:menu_character="E";19:menu_character="X";20:menu_character="E";21:menu_character="C";
   default:;
  endcase
  if(menu_column==67) menu_character="C";
  if(menu_column==68) menu_character="=";
  if(menu_column==69) menu_character=hex_digit({2'b0,ui_status[47:46]});
  if(menu_column==70) menu_character=hex_digit(ui_status[45:42]);
  if(menu_column==73) menu_character="E";
  if(menu_column==74) menu_character="=";
  if(menu_column==75) menu_character=hex_digit(ui_status[41:38]);
 end
 always @* begin
  top_character=" ";frame_number=0;
  case(top_column)
   1:top_character=shown_descriptor[100:98]==0 ? "L" : shown_descriptor[100:98]==1 ? "F" : shown_descriptor[100:98]==2 ? "R" : "P";
   2:top_character=shown_descriptor[100:98]==0 ? "I" : shown_descriptor[100:98]==1 ? "R" : shown_descriptor[100:98]==2 ? "E" : "L";
   3:top_character=shown_descriptor[100:98]==0 ? "V" : shown_descriptor[100:98]==1 ? "Z" : shown_descriptor[100:98]==2 ? "C" : "A";
   4:top_character=shown_descriptor[100:98]==0 ? "E" : shown_descriptor[100:98]==1 ? "N" : shown_descriptor[100:98]==2 ? " " : "Y";
   6:top_character=shown_descriptor[100:98]==4 ? "P" : " ";
   7:top_character=shown_descriptor[100:98]==4 ? "A" : " ";
   8:top_character=shown_descriptor[100:98]==4 ? "U" : " ";
   9:top_character=shown_descriptor[100:98]==4 ? "S" : " ";
   10:top_character=shown_descriptor[100:98]==4 ? "E" : " ";
   12:top_character="F";13:top_character="=";
   24:top_character="V";25:top_character="=";
   36:top_character="R";37:top_character="=";
   48:top_character=shown_descriptor[101]?"R":" ";
   49:top_character=shown_descriptor[101]?"E":" ";
   50:top_character=shown_descriptor[101]?"F":" ";
   53:top_character=shown_descriptor[102]?"C":"S";
   54:top_character=shown_descriptor[102]?"A":"O";
   55:top_character=shown_descriptor[102]?"N":"B";
   56:top_character=shown_descriptor[102]?"N":"E";
   57:top_character=shown_descriptor[102]?"Y":"L";
   59:top_character="R";60:top_character="=";
   61:top_character=shown_descriptor[104:103]==2?"3":"1";
   62:top_character="/";63:top_character=shown_descriptor[104:103]==1?"2":"4";
   66:top_character=ui_status[22]?"A":" ";67:top_character=ui_status[22]?"P":" ";
   68:top_character=ui_status[22]?"P":" ";69:top_character=ui_status[22]?"L":" ";
   70:top_character=ui_status[22]?"Y":" ";
   72:top_character="R";73:top_character="E";74:top_character="C";
   75:top_character="=";
   76:top_character=shown_descriptor[293] ? hex_digit({1'b0,shown_descriptor[291:289]}) : "-";
   77:top_character=shown_descriptor[292]?"+":" ";
   default: ;
  endcase
  if(top_column>=14 && top_column<22) begin
   frame_number=shown_descriptor[31:0];top_character=hex_digit(frame_number>>((21-top_column)*4));
  end
  if(top_column>=26 && top_column<34) begin
   frame_number=shown_descriptor[63:32];top_character=hex_digit(frame_number>>((33-top_column)*4));
  end
  if(top_column>=38 && top_column<46) begin
   frame_number=shown_descriptor[95:64];top_character=hex_digit(frame_number>>((45-top_column)*4));
  end
 end
 always @* begin
  case(x[10:5])
   1:character="T";2:character="=";
   3:character=8'd48+{4'd0,bcd[15:12]};4:character=8'd48+{4'd0,bcd[11:8]};
   5:character=8'd48+{4'd0,bcd[7:4]};6:character=8'd48+{4'd0,bcd[3:0]};
   8:character="K";9:character="E";10:character="Y";11:character="2";12:character="-";
   14:character="K";15:character="E";16:character="Y";17:character="3";18:character="+";
   20:character="M";21:character="=";22:character=shown_flags[0]?"1":"0";
   24:character="D";25:character="=";26:character=shown_flags[1]?"1":"0";
   28:character="O";29:character="=";30:character=shown_flags[2]?"1":"0";
   32:character="C";33:character=8'd48+ui_status[63:56]/10;34:character=8'd48+ui_status[63:56]%10;
   36:character="P";37:character=8'd48+ui_status[55:48]/10;38:character=8'd48+ui_status[55:48]%10;
   default:character=" ";
  endcase
 end
 function [34:0] glyph;
  input [7:0] c;
  begin case(c)
   "0":glyph=35'b01110100011001110101110011000101110;
   "1":glyph=35'b00100011000010000100001000010001110;
   "2":glyph=35'b01110100010000100010001000100011111;
   "3":glyph=35'b11110000010000101110000010000111110;
   "4":glyph=35'b00010001100101010010111110001000010;
   "5":glyph=35'b11111100001000011110000010000111110;
   "6":glyph=35'b01110100001000011110100011000101110;
   "7":glyph=35'b11111000010001000100010000100001000;
   "8":glyph=35'b01110100011000101110100011000101110;
   "9":glyph=35'b01110100011000101111000010000101110;
   "O":glyph=35'b01110100011000110001100011000101110;
   "A":glyph=35'b01110100011000111111100011000110001;
   "B":glyph=35'b11110100011000111110100011000111110;
   "C":glyph=35'b01111100001000010000100001000001111;
   "F":glyph=35'b11111100001000011110100001000010000;
   "G":glyph=35'b01111100001000010111100011000101111;
   "H":glyph=35'b10001100011000111111100011000110001;
   "X":glyph=35'b10001100010101000100010101000110001;
   "/":glyph=35'b00001000010001000100010001000010000;
   "I":glyph=35'b01110001000010000100001000010001110;
   "L":glyph=35'b10000100001000010000100001000011111;
   "N":glyph=35'b10001110011010110011100011000110001;
   "P":glyph=35'b11110100011000111110100001000010000;
   "R":glyph=35'b11110100011000111110101001001010001;
   "S":glyph=35'b01111100001000001110000010000111110;
   "U":glyph=35'b10001100011000110001100011000101110;
   "V":glyph=35'b10001100011000110001100010101000100;
   "Z":glyph=35'b11111000010001000100010001000011111;
   "M":glyph=35'b10001110111010110101100011000110001;
   "D":glyph=35'b11110100011000110001100011000111110;
   "T":glyph=35'b11111001000010000100001000010000100;
   "=":glyph=35'b00000000001111100000111110000000000;
   "K":glyph=35'b10001100101010011000101001001010001;
   "E":glyph=35'b11111100001000011110100001000011111;
   "Y":glyph=35'b10001100010101000100001000010000100;
   "-":glyph=35'b00000000000000011111000000000000000;
   "+":glyph=35'b00000001000010011111001000010000000;
   default:glyph=0;
  endcase end
 endfunction
 wire [10:0] text_y=y-(H-48);
 wire strip=de && y>=H-48 && y<H-16 && x>=16 && x<1264;
 wire [4:0] top_y=y-8;
 wire [10:0] menu_y=y-(H-80);
 wire split_shapes=shown_descriptor[296] || shown_descriptor[295];
 reg shape_border;
 reg [23:0] shape_color;
 reg [10:0] bx0,by0,bx1,by1,label_x,label_y;
 reg [10:0] chosen_label_x,chosen_label_y;reg [1:0] chosen_kind;reg label_valid;
 reg [47:0] label_text;
 reg [7:0] label_character;
 integer target;
 always @* begin
  chosen_label_x=0;chosen_label_y=0;chosen_kind=0;label_valid=0;
  shape_border=0;shape_color=24'h00ff66;
  bx0=0;by0=0;bx1=0;by1=0;label_x=0;label_y=0;label_text=0;label_character=0;
  for(target=0;target<4;target=target+1) begin
   if(shown_descriptor[293] && target<shown_descriptor[291:289] && (!shown_descriptor[294] || x>=W/2)) begin
    bx0=shown_descriptor[105+target*44 +:11];by0=shown_descriptor[116+target*44 +:11];
    bx1=shown_descriptor[127+target*44 +:11];by1=shown_descriptor[138+target*44 +:11];
    if(split_shapes) begin
     bx0=(bx0>>1)+(x>=W/2 ? W/2 : 0);bx1=(bx1>>1)+(x>=W/2 ? W/2 : 0);
     by0=(by0>>1)+H/4;by1=(by1>>1)+H/4;
    end
    if(x>=bx0 && x<=bx1 && y>=by0 && y<=by1 && (x<bx0+2 || x+2>bx1 || y<by0+2 || y+2>by1)) shape_border=1;
    label_x=x-bx0;label_y=y-(by0>=16 ? by0-16 : by0);
    if(x>=bx0 && label_x<96 && label_y<14) begin
     chosen_label_x=label_x;chosen_label_y=label_y;chosen_kind=shown_descriptor[281+target*2 +:2];label_valid=1;
    end
   end
  end
  label_text=chosen_kind==1 ? "CIRCLE" : "RECT  ";
  label_character=chosen_label_x<96 ? label_text[(5-chosen_label_x[10:4])*8 +:8] : " ";
 end
 wire top_active=de && top_strip && x>=16 && x<1280;
 wire menu_active=de && y>=H-80 && y<H-64 && x>=16 && x<1232;
 reg [7:0] font_character;
 reg [2:0] font_x,font_y;
 reg font_valid;
 // Only the visible region selects a glyph; all four text uses share the font.
 always @* begin
  font_character=label_character;font_x=chosen_label_x[3:1];font_y=chosen_label_y[3:1];
  font_valid=label_valid;
  if(top_active) begin
   font_character=top_character;font_x=x[3:1];font_y=top_y[3:1];font_valid=top_y<14;
  end else if(menu_active) begin
   font_character=menu_character;font_x=x[3:1];font_y=menu_y[3:1];font_valid=menu_y<14;
  end else if(strip) begin
   font_character=character;font_x=x[4:2];font_y=text_y[4:2];font_valid=text_y<28;
  end
 end
 wire [34:0] bitmap=glyph(font_character);
 wire ink=font_valid && font_x<5 && bitmap[34-font_y*5-font_x];
 assign out_rgb=top_active ? (ink?24'hffffff:24'h202020) :
                menu_active || strip ? (ink?24'h66ffff:24'h202020) :
                de && (shape_border || ink) ? shape_color : rgb;
endmodule
