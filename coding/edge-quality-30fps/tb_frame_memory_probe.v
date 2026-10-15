`timescale 1ns/1ps
module tb_frame_memory_probe;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0;wire done,failed;
 wire [31:0] fail_address,checks,awaddr,araddr;
 wire awvalid,wvalid,wlast,bready,arvalid,rready;
 wire [127:0] wdata;
 reg awready=0,wready=0,bvalid=0,arready=0,rvalid=0;
 reg [127:0] rdata;
 reg [31:0] addresses[0:305];reg [127:0] values[0:305];
 reg [31:0] write_address,mask=32'hffffffff;
 integer used=0,cycles=0,i,found,run;
 frame_memory_probe dut(.clk(clk),.rst_n(rst_n),.start(1'b1),
  .done(done),.failed(failed),.fail_address(fail_address),.checks(checks),
  .awaddr(awaddr),.araddr(araddr),.awvalid(awvalid),.wvalid(wvalid),
  .wlast(wlast),.bready(bready),.arvalid(arvalid),.rready(rready),.wdata(wdata),
  .awready(awready),.wready(wready),.bvalid(bvalid),.arready(arready),
  .rvalid(rvalid),.rlast(1'b1),.bresp(2'b0),.rresp(2'b0),.rdata(rdata));
 always @(posedge clk) begin
  cycles<=cycles+1;
  awready<=cycles%3!=0;wready<=cycles%5!=0;arready<=cycles%7!=0;
  if(!rst_n) begin bvalid<=0;rvalid<=0;end
  else begin
   if(awvalid && awready) write_address<=awaddr&mask;
   if(wvalid && wready) begin
    found=-1;
    for(i=0;i<used;i=i+1) if(addresses[i]==write_address) found=i;
    if(found<0) begin found=used;used=used+1;end
    addresses[found]=write_address;values[found]=wdata;bvalid<=1;
   end
   if(bvalid && bready) bvalid<=0;
   if(arvalid && arready) begin
    found=-1;
    for(i=0;i<used;i=i+1) if(addresses[i]==(araddr&mask)) found=i;
    if(found<0) $fatal(1,"read of unwritten address");
    rdata<=values[found];rvalid<=1;
   end
   if(rvalid && rready) rvalid<=0;
  end
 end
 initial begin
  repeat(5) @(negedge clk);rst_n=1;
  wait(done || failed);
  if(failed || checks!=306) $fatal(1,"healthy memory rejected %h %d",fail_address,checks);
  @(negedge clk);rst_n=0;used=0;mask=32'h07ffffff;
  repeat(5) @(negedge clk);rst_n=1;
  wait(done || failed);
  if(done || !failed) $fatal(1,"128 MiB alias was not detected");
  $display("PASS: DDR 256 MiB address probes, both patterns, AXI stalls; 128 MiB alias rejected at %h",fail_address);
  $finish;
 end
 initial begin #1000000;$fatal(1,"timeout");end
endmodule
