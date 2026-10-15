`timescale 1ns/1ps
module tb_canny_hysteresis;
 parameter W=32,H=24,BURST=16;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,start=0;
 reg [15:0] config_value;
 wire busy,done,ok,req_valid,req_write,write_valid;
 wire [31:0] cycles,enqueued,highwater,misses,address;
 wire [7:0] len;
 wire [127:0] write_data;
 reg req_ready=0,write_ready=0,read_valid=0,transfer_done=0;
 reg [127:0] read_data;reg transfer_error=0,faulted=0;
 integer error_at=0,transactions=0;
 reg [127:0] memory[0:(W*H*8+((W*H+16383)/16384)*4096+16)/16-1];
 reg [31:0] source[0:W*H-1],expected[0:W*H-1];
 reg [1023:0] input_file,final_file;
 reg [31:0] rng=32'h93401;
 reg active=0,writing=0,pending=0;
 integer pos=0,left=0,i,lane,count=0,expect_count=0;
 reg [31:0] want;
 canny_hysteresis #(.W(W),.H(H),.SCAN_BURST(BURST),.QUEUE_BASE(W*H*4),.STATE_BASE(W*H*8)) dut(
  .clk(clk),.rst_n(rst_n),.start(start),.slot(2'd0),
  .busy(busy),.done(done),.ok(ok),.cycles(cycles),.enqueued(enqueued),.highwater(highwater),.cache_misses(misses),
  .req_valid(req_valid),.req_write(req_write),.req_address(address),.req_len(len),.req_ready(req_ready),
  .write_data(write_data),.write_valid(write_valid),.write_ready(write_ready),
  .read_valid(read_valid),.read_data(read_data),.transfer_done(transfer_done),.transfer_error(transfer_error));
 initial begin
  if(!$value$plusargs("input=%s",input_file) || !$value$plusargs("expected=%s",final_file) ||
     !$value$plusargs("config=%d",config_value)) $fatal(1,"missing vector arguments");
  if($value$plusargs("error_at=%d",error_at)) begin end
  $readmemh(input_file,source);$readmemh(final_file,expected);
  for(i=0;i<(W*H+16383)/16384*256;i=i+1) memory[W*H/2+i]=0;
  for(i=0;i<W*H;i=i+1) begin
   memory[i/4][(3-i%4)*32 +:32]=source[i];
   memory[W*H/2+i/64][i%64*2 +:2]=source[i][31:30];
   if(expected[i][31]) expect_count=expect_count+1;
  end
  repeat(5) @(negedge clk);rst_n=1;start=1;
  @(negedge clk);start=0;
 end
 always @(negedge clk) if(rst_n) begin
  rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
  req_ready=!active && !pending && rng[2:0]!=0;
  write_ready=active && writing && rng[5:3]!=0;
  read_valid=active && !writing && rng[8:6]!=0;
  if(read_valid) read_data=error_at!=0 && transactions==error_at ? 128'hffffffffffffffffffffffffffffffff : memory[pos];
  transfer_done=pending;transfer_error=pending && error_at!=0 && transactions==error_at;pending=0;
 end
 always @(posedge clk) if(rst_n) begin
  count=count+1;
  if(transfer_done && transfer_error) faulted=1;
  if(req_valid && req_ready) begin
   if(faulted) $fatal(1,"issued memory request after failed transaction");
   transactions=transactions+1;
   if(address[3:0]!=0 || address/16+len>=(W*H*8+((W*H+16383)/16384)*4096+16)/16) $fatal(1,"memory bounds addr=%h len=%d",address,len);
   active=1;writing=req_write;pos=address/16;left=len+1;
  end
  if(read_valid || write_valid && write_ready) begin
   if(writing) memory[pos]=write_data;
   pos=pos+1;left=left-1;
   if(left==0) begin active=0;pending=1;end
  end
  if(done) begin
   if(error_at!=0) begin
    if(ok || !faulted) $fatal(1,"DDR error was not propagated");
    $display("PASS hysteresis DDR error transaction=%0d detected, aborted, no subsequent request",error_at);$finish;
   end
   if(!ok || enqueued!=expect_count || highwater>W*H) $fatal(1,"counts ok=%b enqueued=%0d expected=%0d highwater=%0d",ok,enqueued,expect_count,highwater);
   for(i=0;i<W*H;i=i+1) begin
    if(memory[W*H/2+i/64][i%64*2+1]!==expected[i][31]) $fatal(1,"final accepted pixel %0d mismatch",i);
    if(memory[i/4][(3-i%4)*32 +:32]!==source[i]) $fatal(1,"hysteresis changed RGB result %0d",i);
   end
   $display("PASS hysteresis %0dx%0d cycles=%0d enqueued=%0d highwater=%0d cache_misses=%0d transactions=%0d",W,H,cycles,enqueued,highwater,misses,transactions);$finish;
  end
  if(count>W*H*400) $fatal(1,"timeout state=%d head=%d tail=%d",dut.state,dut.head,dut.tail);
 end
endmodule
