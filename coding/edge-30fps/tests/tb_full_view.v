`timescale 1ns/1ps
module tb_full_view;
    parameter W=16,H=8;
    reg clk=0; always #5 clk=~clk;
    reg rst_n=0,vs=0,hs=0,valid=0;
    reg [39:0] raw4=0;
    reg [1:0] phase=0;
    wire out_vs,out_valid;
    wire [63:0] rgb2;
    wire [31:0] frames,errors,sr,sg,sb;
    wire [15:0] mw,mh;
    integer count=0,x,y,k,p,run;
    raw_full_view #(.WIDTH(W),.HEIGHT(H)) dut(
        .clk(clk),.rst_n(rst_n),.vs(vs),.hs(hs),.valid(valid),.raw4(raw4),
        .phase(phase),.gain_r(16'd256),.gain_g(16'd256),.gain_b(16'd256),
        .out_vs(out_vs),.out_valid(out_valid),.rgb2(rgb2),
        .frames(frames),.errors(errors),.measured_width(mw),.measured_height(mh),
        .sum_r(sr),.sum_g(sg),.sum_b(sb));
    function [23:0] expected;
        input integer px,py;
        reg [7:0] r,g,b;
        begin
            r=20+(px%80);g=40+(py%80);b=90+((px+py)%80);
            expected={r,g,b};
        end
    endfunction
    function [9:0] mosaic;
        input integer px,py,ph;
        reg [23:0] color;
        integer cell_index;
        begin
            color=expected(px/2,py/2);
            cell_index=((py%2)*2+(px%2))^ph;
            case(cell_index)
                0:mosaic={color[7:0],2'b00};
                3:mosaic={color[23:16],2'b00};
                default:mosaic={color[15:8],2'b00};
            endcase
        end
    endfunction
    always @(negedge clk) if(out_valid) begin
        if(rgb2!=={8'd0,expected(count%(W/2),count/(W/2)),
                    8'd0,expected((count+1)%(W/2),(count+1)/(W/2))})
            $fatal(1,"RGB/coordinate mismatch at output pixel %0d: %h",count,rgb2);
        count=count+2;
    end
    initial begin
        for(p=0;p<4;p=p+1) begin
            @(posedge clk); #1; rst_n=0;vs=0;hs=0;valid=0;phase=p;
            repeat(5) @(posedge clk);
            #1;rst_n=1;count=0;
            @(posedge clk);#1;vs=1;
            repeat(6) @(posedge clk);
            #1;vs=0;
            repeat(6) @(posedge clk);
            for(y=0;y<H;y=y+1) begin
                for(x=0;x<W;x=x+4) begin
                    @(posedge clk);#1;hs=1;valid=1;
                    for(k=0;k<4;k=k+1)raw4[k*10+:10]=mosaic(x+k,y,p);
                    if(x%12==0) begin
                        @(posedge clk);#1;valid=0;
                    end
                end
                @(posedge clk);#1;valid=0;hs=0;
                repeat(7) @(posedge clk);
            end
            repeat(8) @(posedge clk);
            #1;vs=1;
            repeat(8) @(posedge clk);
            #1;
            if(count!=W*H/4 || frames!=1 || mw!=W || mh!=H || errors!=0)
                $fatal(1,"Frame mismatch count=%0d frames=%0d size=%0dx%0d errors=%0d",count,frames,mw,mh,errors);
        end
        $display("PASS: all Bayer phases, RGB ordering, gaps, frame resets, full-field %0dx%0d",W,H);
        $finish;
    end
endmodule
