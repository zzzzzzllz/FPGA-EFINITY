`timescale 1ns/1ps
module tb_shape_recognizer;
 parameter W=1280,H=720;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,start=0;
 wire busy,done,ok,overflow;
 wire [2:0] count;wire [175:0] boxes;wire [7:0] kinds;
 wire [31:0] candidates,cycles;
 wire mv,mw,mc,mdone,merror;wire [31:0] ma;wire [127:0] mdata,mresult;
 wire req,writing,wvalid;wire [31:0] address;wire [7:0] len;wire [127:0] wdata;
 reg ready=0,wready=0,rv=0,td=0,transfer_error=0;reg [127:0] rd;
 reg [127:0] plane[0:(W*H+16383)/16384*256-1],visit[0:(W*H+16383)/16384*256-1],queue[0:(W*H+16383)/16384*4096-1];
 reg [31:0] expected[0:11];
 reg [1023:0] input_file,expected_file;
 reg active=0,write_active=0,pending=0;
 reg [31:0] pos,rng=32'h10910001;
 integer left=0,i,n=0,transactions=0,timeout=20000000,error_at=0;
 integer memory_beats=0,max_runs=0,require_spill=0;
 shape_recognizer #(.W(W),.H(H)) dut(.clk(clk),.rst_n(rst_n),.start(start),.slot(2'd0),
  .busy(busy),.done(done),.ok(ok),.count(count),.overflow(overflow),.boxes(boxes),.kinds(kinds),
  .candidates(candidates),.cycles(cycles),.mem_valid(mv),.mem_write(mw),.mem_copy(mc),.mem_address(ma),
  .mem_data(mdata),.mem_done(mdone),.mem_error(merror),.mem_result(mresult));
 canny_hysteresis #(.W(W),.H(H)) cache(.clk(clk),.rst_n(rst_n),.start(1'b0),.slot(2'd0),
  .ext_valid(mv),.ext_write(mw),.ext_copy(mc),.ext_address(ma),.ext_data(mdata),.ext_done(mdone),.ext_error(merror),.ext_result(mresult),
  .req_valid(req),.req_write(writing),.req_address(address),.req_len(len),.req_ready(ready),
  .write_valid(wvalid),.write_ready(wready),.write_data(wdata),.read_valid(rv),.read_data(rd),.transfer_done(td),.transfer_error(transfer_error));
 function [127:0] read_memory;
  input [31:0] addr;
  begin
   if(addr>=32'h0b500000 && addr<32'h0b500000+(W*H+16383)/16384*4096) read_memory=visit[(addr-32'h0b500000)/16];
   else if(addr>=32'h0b400000 && addr<32'h0b400000+(W*H+16383)/16384*4096) read_memory=plane[(addr-32'h0b400000)/16];
   else if(addr>=32'h0b000000 && addr<32'h0b000000+W*H*4) read_memory=queue[(addr-32'h0b000000)/16];
   else begin $fatal(1,"read bounds %h",addr);read_memory=0;end
  end
 endfunction
 initial begin
  if(!$value$plusargs("input=%s",input_file) || !$value$plusargs("expected=%s",expected_file)) $fatal(1,"missing vectors");
  if($value$plusargs("error_at=%d",error_at)) begin end
  if($value$plusargs("spill=%d",require_spill)) begin end
  for(i=0;i<(W*H+16383)/16384*256;i=i+1) begin plane[i]=0;visit[i]=128'hffffffffffffffffffffffffffffffff;end
  $readmemh(input_file,plane,0,W*H/64-1);$readmemh(expected_file,expected);
  repeat(5) @(negedge clk);rst_n=1;start=1;@(negedge clk);start=0;
 end
 always @(negedge clk) if(rst_n) begin
  rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
  ready=!active && !pending && rng[2:0]!=0;
  wready=active && write_active && rng[5:3]!=0;
  rv=active && !write_active && rng[8:6]!=0;
  if(rv) rd=read_memory(pos);
  td=pending;transfer_error=pending && transactions==error_at;pending=0;
 end
 always @(posedge clk) if(rst_n) begin
  case(dut.state)
   24,26,46,31,49:if($signed(dut.sum)!=$signed(dut.m0)+$signed(dut.m1)) $fatal(1,"geometry sum width");
   25,35,37:if($signed(dut.difference)!=$signed(dut.m0)-$signed(dut.m1)) $fatal(1,"geometry cross width");
   default:;
  endcase
  n=n+1;
  if(dut.tail>max_runs) max_runs=dut.tail;
  if(req && ready) begin active=1;write_active=writing;pos=address;left=len+1;transactions=transactions+1;end
  if(rv || wvalid && wready) begin
   memory_beats=memory_beats+1;
   if(write_active) begin
    if(pos>=32'h0b500000 && pos<32'h0b500000+(W*H+16383)/16384*4096) visit[(pos-32'h0b500000)/16]=wdata;
    else if(pos>=32'h0b000000 && pos<32'h0b000000+W*H*4) queue[(pos-32'h0b000000)/16]=wdata;
    else $fatal(1,"write bounds or modified final edge %h",pos);
   end
   pos=pos+16;left=left-1;if(left==0) begin active=0;pending=1;end
  end
  if(done) begin
   if(error_at!=0) begin
    if(ok || transactions!=error_at || count!=0) $fatal(1,"DDR failure not aborted cleanly");
    $display("PASS shape DDR error abort at transfer %0d",error_at);$finish;
   end
   if(!ok || count!==expected[0] || kinds!==expected[1] || overflow!==expected[2][0])
    $fatal(1,"shape mismatch ok=%b count=%d expected=%d kinds=%h expected=%h overflow=%b candidates=%0d",ok,count,expected[0],kinds,expected[1],overflow,candidates);
   if(candidates!==expected[11]) $fatal(1,"component count %0d expected %0d",candidates,expected[11]);
   for(i=0;i<count;i=i+1) if(boxes[i*44 +:44]!=={expected[4+i*2][10:0],expected[4+i*2][26:16],expected[3+i*2][10:0],expected[3+i*2][26:16]})
    $fatal(1,"box %0d mismatch %h",i,boxes[i*44 +:44]);
   if(require_spill && max_runs<=4096) $fatal(1,"queue spill coverage missing: %0d runs",max_runs);
   $display("PASS shape %0dx%0d count=%0d kinds=%h overflow=%b candidates=%0d cycles=%0d transactions=%0d beats=%0d max_runs=%0d",W,H,count,kinds,overflow,candidates,cycles,transactions,memory_beats,max_runs);$finish;
  end
  if(n>timeout) $fatal(1,"timeout state=%0d cache=%0d head=%0d tail=%0d trace=%0d point=%h",dut.state,cache.state,dut.head,dut.tail,dut.trace_count,dut.point);
 end
endmodule

