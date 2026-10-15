module tb_mix;
 raw_full_view #(.WIDTH(48),.HEIGHT(18)) dut();
 integer a,b;
 initial begin
  for(a=0;a<1024;a=a+1)for(b=0;b<1024;b=b+1)
   if(dut.mix_channel(a,b)!==(2*a+b+1)/3)
    $fatal(1,"mix mismatch a=%0d b=%0d",a,b);
  $display("PASS: all 1048576 RGB10 input pairs equal exact rounded division");
  $finish;
 end
endmodule
