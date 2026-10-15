

`timescale 1ps/1ps
module frame_buffer #(
parameter I_VID_WIDTH       = 16,
parameter O_VID_WIDTH       = 128,
parameter AXI_DATA_WIDTH	= 512,
parameter AXI_ADDR_WIDTH 	= 33,
parameter	WR_FIFO_DEPTH	= 1024,    
parameter	RD_FIFO_DEPTH 	= 1024,
parameter START_ADDR		= 33'h000201900,
parameter BURST_LEN         = 8'd15,
parameter FB_NUM			= 3,//2 buffer ,3 buffer 
parameter MAX_VID_WIDTH		= 1920 ,//video width 
parameter MAX_VID_HIGHT		= 1080 ,//wideo height
parameter O_FRAME_WIDTH     = 1920,
parameter O_FRAME_HEIGHT    = 1080,
parameter AXI_STRB_WIDTH 	= AXI_DATA_WIDTH/8
) (

input 												axi_clk,
input 												rst_n,

input	wire								i_clk	,
input	wire								i_vs, //active hgih
input	wire								i_de, //active high
input	wire	[I_VID_WIDTH-1:0] 			vin ,

input	wire							o_clk	,
input   wire                   fifo_rd_period,//!!
output wire                    m_axis_tuser,
output wire                    m_axis_tvalid ,
input  wire                    m_axis_tready,
output wire                    m_axis_tlast,
output wire  [O_VID_WIDTH-1:0] m_axis_tdata,



output 	[5:0] 								awid,
output  [AXI_ADDR_WIDTH-1:0] 	            awaddr,
output  [7:0] 								awlen,
output  [2:0] 								awsize,
output  [1:0] 								awburst,
output  [3:0] 								awcache,
output [2:0]                                awprot,
output  									    awlock,
output  									    awvalid,
output  									    awcobuf,
output  									    awapcmd,
output  									    awallstrb,
output  									    awqos,
input 										    awready,

output [5:0] 									arid,
output  [AXI_ADDR_WIDTH-1:0] 	                araddr,
output  [7:0] 								    arlen,
output  [2:0] 								    arsize,
output  [1:0] 								    arburst,
output  									    arlock,
output  									    arvalid,
output  									    arapcmd,
output 										    arqos,
input 										    arready,
output  [3:0] 									arcache,
output [2:0]                    arprot,

output  [AXI_DATA_WIDTH-1:0] 	wdata,  
output  [AXI_STRB_WIDTH-1:0] 	wstrb,
output  											wlast,
output  											wvalid,
input 												wready,

input [5:0] 									    rid,
input [AXI_DATA_WIDTH-1:0] 		rdata,
input 												rlast,
input 												rvalid,
output  											rready,
input [1:0] 									    rresp,

input [5:0] 									    bid,
input 												bvalid,
output  											bready,
output			[31:0]								test_rd_fifo_rddata,   
output	[31:0]								        test_wdata,
output	[31:0]								        test_rdata,
output [63:0] debug_write_status,
output [63:0] debug_bank_addresses,
output [7:0] test_BURST_LEN
);
assign test_BURST_LEN = BURST_LEN;
//=============================================================
//parameter define                                                  
//============================================================= 
wire [31:0]               ddr_frame_len ;
wire [AXI_DATA_WIDTH-1:0] wr_fifo_wrdata;

wire                      rd_fifo_rdvalid	;
wire [AXI_DATA_WIDTH-1:0] rd_fifo_rddata	 ; 
wire                      rd_fifo_rdempty	;
wire                      rd_fifo_rden     ;

wire		wr_sw_ack ;
wire		wr_sw 		;
wire		rd_sw			;
wire		rd_sw_ack ;

wire	[O_VID_WIDTH-1:0] o_fifo_rd_data;
wire					  o_fifo_rd_en;
wire  					  o_fifo_rd_empty;
//=============================================================  
//RTL                                                     
//=============================================================  
wire wr_clk_rst_n;
wire axi_clk_rst_n;
wire rd_clk_rst_n;
rst_n_piple #(                       
	.DLY ( 3 )                        
)	u_i_clk_rst_pip(                                          
/*i*/.clk			(i_clk),                        
/*i*/.rst_n_i	(rst_n),                    
/*o*/.rst_n_o (wr_clk_rst_n)            
);

  rst_n_piple #(                       
	.DLY ( 3 )                        
)	u_axi_rst_pip(                                          
/*i*/.clk			(axi_clk),                        
/*i*/.rst_n_i	(rst_n),                    
/*o*/.rst_n_o (axi_clk_rst_n)            
);

  rst_n_piple #(                       
	.DLY ( 3 )                        
)	u_o_clk_rst_pip(                                          
/*i*/.clk			(o_clk),                        
/*i*/.rst_n_i	(rst_n),                    
/*o*/.rst_n_o (rd_clk_rst_n)            
);


wire                      wr_fifo_wren;
wire                      frame_start;
wire                      frame_stable;

vid_rx_align_v1 #(
	.I_VID_WIDTH   (I_VID_WIDTH		),
	.AXI_DDR_WIDTH (AXI_DATA_WIDTH )
)u_vid_rx_align(
/*i*/.clk			    (i_clk			),  
/*i*/.rst_n			  (wr_clk_rst_n	),
/*i*/.i_vs			  (i_vs			), //active hgih
/*i*/.i_de			  (i_de			), //active high
/*i*/.vin			    (vin			),
/*o*/.fifo_wr_en	  (wr_fifo_wren		),
/*o*/.fifo_wr_data	(wr_fifo_wrdata	),
/*o*/.frame_start	  (frame_start	),
/*O*/.fifo_rst_p		  (fifo_rst		  ),
/*O*/.frame_stable  (frame_stable ),
/*O*/.ddr_frame_len (ddr_frame_len)
);

reg fifo_rd_period_r0 = 'd0;
reg fifo_rd_period_r1 = 'd0;
reg fifo_rd_period_r2 = 'd0;
always @( posedge axi_clk)
begin
  fifo_rd_period_r0 <= fifo_rd_period;
  fifo_rd_period_r1 <= fifo_rd_period_r0;
  fifo_rd_period_r2 <= fifo_rd_period_r1; 
end
wire pos_rd_period = {fifo_rd_period_r2,fifo_rd_period_r1} == 2'b01;
ddr_buffer #(
.AXI_DATA_WIDTH ( AXI_DATA_WIDTH	),
.AXI_ADDR_WIDTH ( AXI_ADDR_WIDTH	),
.WR_FIFO_DEPTH	( WR_FIFO_DEPTH		),    
.RD_FIFO_DEPTH 	( RD_FIFO_DEPTH 	),
.START_ADDR		( START_ADDR        ),
.I_VID_WIDTH    ( I_VID_WIDTH       ),
.BURST_LEN      (BURST_LEN          )
)u_ddr_buffer(
    .axi_clk		    (axi_clk	),
    .wr_clk_rst_n (wr_clk_rst_n),
    .axi_clk_rst_n(axi_clk_rst_n),
    .rd_clk_rst_n (rd_clk_rst_n),
    

/*i*/.wr_start	      (frame_start),// && frame_stable
/*i*/.rd_start	      (fifo_rd_period),// && frame_stable
    .debug_write_status(debug_write_status),
    .debug_bank_addresses(debug_bank_addresses),
    .wr_busrt_len     (ddr_frame_len ),//ddr address scope for one frame
    .rd_burst_len     (ddr_frame_len ),//ddr address scope for one frame

	   .test_cnt		(test_cnt         ),
/*i*/.wr_fifo_wrclk		(i_clk			  ),
/*i*/.wr_fifo_rst_p     ( fifo_rst        ),
/*i*/.wr_fifo_wren		(wr_fifo_wren	  ),
/*o*/.wr_fifo_wrfull	(wr_fifo_wrfull	  ),
/*i*/.wr_fifo_wrdata	(wr_fifo_wrdata	  ), 

/*i*/.rd_fifo_rdclk		(o_clk			  ),
/*i*/.rd_fifo_rst_p     (pos_rd_period    ),
/*o*/.rd_fifo_rdvalid	(rd_fifo_rdvalid  ),
/*o*/.rd_fifo_rddata	(rd_fifo_rddata	  ),
/*o*/.rd_fifo_rdempty	(rd_fifo_rdempty  ),
/*i*/.rd_fifo_rden		(rd_fifo_rden     ),

/*o*/.test_wdata    (test_wdata     ),
/*o*/.test_rdata    (test_rdata     ),    
    .awid			( awid			),
    .awaddr			( awaddr		),
    .awlen			( awlen			),
    .awsize			( awsize		),
    .awburst		( awburst		),
    .awvalid		( awvalid		),
    .awready		( awready		),
    .awqos			( awqos			),
    .awcache        ( awcache       ),
    .awprot         ( awprot        ),

    .arid			( arid			),
    .araddr			( araddr		),
    .arlen			( arlen			),
    .arsize			( arsize		),
    .arburst		( arburst		),
    .arlock			( arlock		),
    .arvalid		( arvalid		),
    .arapcmd		( arapcmd		),
    .arready		( arready		),
    .arqos			( arqos			),
    .arprot         (arprot         ),
    .arcache        (arcache        ),
    //
    .wdata			( wdata			),
    .wstrb			( wstrb			),
    .wlast			( wlast			),
    .wvalid			( wvalid		),
    .wready			( wready		),
    //
    .rid			( rid			),
    .rdata			( rdata			),
    .rlast			( rlast			),
    .rvalid			( rvalid		),
    .rready			( rready		),
    .rresp			( rresp			),
    .bid			( bid			),
    .bvalid			( bvalid		),
    .bready			( bready		));

// Direct AXI-width stream. The queue reserves space for the pending FIFO read.
reg [AXI_DATA_WIDTH-1:0] queue [0:3];
reg [1:0] qwr=0, qrd=0;
reg [2:0] queued=0;
reg pending=0;
reg [12:0] rd_h_cnt=0, rd_v_cnt=0;
wire take=m_axis_tvalid && m_axis_tready;
assign rd_fifo_rden=!fifo_rd_period && !rd_fifo_rdempty && queued+pending<4;
assign m_axis_tvalid=queued!=0 && !fifo_rd_period && rd_v_cnt<O_FRAME_HEIGHT;
assign m_axis_tdata=queue[qrd];
assign m_axis_tuser=rd_h_cnt==0 && rd_v_cnt==0;
assign m_axis_tlast=rd_h_cnt==O_FRAME_WIDTH-1;
always @(posedge o_clk) begin
 if(!rd_clk_rst_n || fifo_rd_period) begin
  qwr<=0; qrd<=0; queued<=0; pending<=0; rd_h_cnt<=0; rd_v_cnt<=0;
 end else begin
  pending<=rd_fifo_rden;
  if(pending) begin queue[qwr]<=rd_fifo_rddata; qwr<=qwr+1'b1; end
  if(take) begin
   qrd<=qrd+1'b1;
   if(rd_h_cnt==O_FRAME_WIDTH-1) begin rd_h_cnt<=0; rd_v_cnt<=rd_v_cnt+1'b1; end
   else rd_h_cnt<=rd_h_cnt+1'b1;
  end
  case({pending,take})
   2'b10: queued<=queued+1'b1;
   2'b01: queued<=queued-1'b1;
   default: ;
  endcase
 end
end
endmodule
