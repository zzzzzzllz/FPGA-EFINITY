// One selected algorithm per serial frame job. RGB/denoise payload follows each window.
module edge_algorithm_pair #(parameter W=1280,H=720)(
 input clk,rst_n,input [15:0] in_config,
 input [63:0] in_pixels,input in_valid,output in_ready,
 input in_sof,in_eol,in_eof,input [31:0] in_id,in_epoch,
 output [63:0] out_pixels,output out_valid,input out_ready,
 output out_sof,out_eol,out_eof,output [31:0] out_id,out_epoch,
 output [15:0] out_config
);
 wire [63:0] med,gauss,sobel,nms,classified;
 wire nv,nr,ns,nl,ne;wire [31:0] ni,np;wire [15:0] nc;
 wire mv,mr,ms,ml,me,gv,gr,gs,gl,ge,sv,sr,ss,sl,se;
 wire [31:0] mi,mp,gi,gp,si,sp;
 wire [15:0] mc,gc;
 wire [25:0] gradient;
 reg [15:0] job_config;
 always @(posedge clk) begin
  if(!rst_n) job_config<=16'h4820;
  else if(in_valid && in_ready && in_sof) job_config<=in_config;
 end
 median_pair #(.WIDTH(W),.HEIGHT(H),.CONFIG_WIDTH(16)) median(
  .clk(clk),.rst_n(rst_n),.in_config(in_config),.out_config(mc),
  .in_rgby(in_pixels),.in_valid(in_valid),.in_ready(in_ready),.in_sof(in_sof),.in_eol(in_eol),.in_eof(in_eof),
  .in_frame_id(in_id),.in_epoch(in_epoch),.out_rgby(med),.out_valid(mv),.out_ready(mr),
  .out_sof(ms),.out_eol(ml),.out_eof(me),.out_frame_id(mi),.out_epoch(mp));
 function [7:0] luma;
  input [23:0] rgb;reg [15:0] sum;
  begin sum=77*rgb[23:16]+150*rgb[15:8]+29*rgb[7:0]+128;luma=sum[15:8];end
 endfunction
 wire [63:0] payload=mc[12] ?
  {med[63:56],luma(med[55:32]),med[63:56],8'd0,med[31:24],luma(med[23:0]),med[31:24],8'd0}:med;
 gaussian_pair #(.WIDTH(W),.HEIGHT(H)) gaussian(
  .clk(clk),.rst_n(rst_n),.in_config(mc),.out_config(gc),
  .in_rgby(payload),.in_valid(mv),.in_ready(mr),.in_sof(ms),.in_eol(ml),.in_eof(me),
  .in_frame_id(mi),.in_epoch(mp),.out_rgby(gauss),.out_valid(gv),.out_ready(gr),
  .out_sof(gs),.out_eol(gl),.out_eof(ge),.out_frame_id(gi),.out_epoch(gp));
 sobel_pair #(.WIDTH(W),.HEIGHT(H)) gradient_stage(
  .clk(clk),.rst_n(rst_n),.threshold(gc[10:0]),.in_flags(gc[12:11]),.out_flags(),.out_luma(),.out_threshold(),
  .in_rgby(gauss),.in_valid(gv),.in_ready(gr),.in_sof(gs),.in_eol(gl),.in_eof(ge),
  .in_frame_id(gi),.in_epoch(gp),.out_rgbe(sobel),.out_gradient(gradient),.out_valid(sv),.out_ready(sr),
  .out_sof(ss),.out_eol(sl),.out_eof(se),.out_frame_id(si),.out_epoch(sp));
 canny_nms_pair #(.WIDTH(W),.HEIGHT(H)) nms_stage(
  .clk(clk),.rst_n(rst_n),.in_config(job_config),.out_config(nc),
  .in_rgby({gradient[25:13],sobel[63:32],gradient[12:0],sobel[31:0]}),
  .in_valid(sv),.in_ready(sr),.in_sof(ss),.in_eol(sl),.in_eof(se),.in_frame_id(si),.in_epoch(sp),
  .out_rgby(classified),.out_valid(nv),.out_ready(nr),
  .out_sof(ns),.out_eol(nl),.out_eof(ne),.out_frame_id(ni),.out_epoch(np));
 edge_cleanup_pair #(.WIDTH(W),.HEIGHT(H)) cleanup_stage(
  .clk(clk),.rst_n(rst_n),.in_config(nc),.out_config(out_config),
  .in_rgby(classified),.in_valid(nv),.in_ready(nr),.in_sof(ns),.in_eol(nl),.in_eof(ne),.in_frame_id(ni),.in_epoch(np),
  .out_rgby(nms),.out_valid(out_valid),.out_ready(out_ready),
  .out_sof(out_sof),.out_eol(out_eol),.out_eof(out_eof),.out_frame_id(out_id),.out_epoch(out_epoch));
 reg second;
 always @(posedge clk) begin
  if(!rst_n) second<=0;
  else if(out_valid && out_ready) second<=out_sof;
 end
 assign out_pixels=out_config[13] ? nms :
  {nms[63],(second ? {1'b0,out_config[12:11],out_config[10:7]} : out_id[6:0]),nms[55:32],
   nms[31],(out_sof ? out_config[6:0] : out_id[6:0]),nms[23:0]};
endmodule
