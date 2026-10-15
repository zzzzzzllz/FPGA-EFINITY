
/////////////////////////////////////////////////////////////////////////////
//
// Copyright (C) 2013-2021 Efinix Inc. All rights reserved.
//
// Description:
// Example top file for ti60f225 dev kit OOB design
//
// Language:  Verilog 2001
//Ti60f225_sc431hai2hdmi_v6：
//使用了最新版本的framebuffer_v3;
// ------------------------------------------------------------------------------

/////////////////////////////////////////////////////////////////////////////////
//`define SOFT_TAP 1
`include "ddr3_controller/ddr3_parameter.vh"
// `include "define.v"

module ti60f225_oob_top #(

	parameter                       RANK_RATIO         = 1,       // # of unique CS outputs per rank
	parameter                       ASYN_AXI_CLK       = `ASYN_AXI_CLK, 
	parameter                       RANKS              = `RANKS,
	parameter                       CK_WIDTH           = `CK_WIDTH,       // # of CK/CK# outputs to memory   
	parameter                       CKE_WIDTH          = `CKE_WIDTH,       // # of cke outputs
	parameter                       CS_WIDTH           = `CS_WIDTH,       // # of unique CS outputs
	parameter                       BANK_WIDTH         = `BANK_WIDTH,       // # of bank bits
	parameter                       ROW_WIDTH          = `ROW_WIDTH,       // DRAM address bus width
	parameter                       COL_WIDTH          = `COL_WIDTH,      // column address width
	parameter                       DM_WIDTH           = `DM_WIDTH,       // # of DM (data mask)
	parameter                       DQS_WIDTH          = `DQS_WIDTH,       // # of DQS (strobe)
	parameter                       DQ_WIDTH           = `DQ_WIDTH,      // # of DQ (data)
	parameter                       ODT_WIDTH          = `ODT_WIDTH,
	parameter                       DQ_CNT_WIDTH       = `DQ_CNT_WIDTH,       // = ceil(log2(DQ_WIDTH))
	parameter                       DQS_CNT_WIDTH      = `DQS_CNT_WIDTH,       // = ceil(log2(DQS_WIDTH))  
	parameter                       DRAM_WIDTH         = `DRAM_WIDTH,       // # of DQ per DQS   
	parameter                       DATA_WIDTH         = `DATA_WIDTH,
	parameter                       ADDR_WIDTH         = `ADDR_WIDTH,    
	parameter                       AXI_ID_WIDTH       = `AXI_ID_WIDTH,
	parameter                       AXI_ADDR_WIDTH     = `AXI_ADDR_WIDTH,
	parameter                       AXI_DATA_WIDTH     = `AXI_DATA_WIDTH
)
(

  (* syn_peri_port = 0 *) input jtag_inst1_CAPTURE,
  (* syn_peri_port = 0 *) input jtag_inst1_DRCK,
  (* syn_peri_port = 0 *) input jtag_inst1_RESET,
  (* syn_peri_port = 0 *) input jtag_inst1_RUNTEST,
  (* syn_peri_port = 0 *) input jtag_inst1_SEL,
  (* syn_peri_port = 0 *) input jtag_inst1_SHIFT,
  (* syn_peri_port = 0 *) input jtag_inst1_TCK,
  (* syn_peri_port = 0 *) input jtag_inst1_TDI,
  (* syn_peri_port = 0 *) input jtag_inst1_TMS,
  (* syn_peri_port = 0 *) input jtag_inst1_UPDATE,
  (* syn_peri_port = 0 *) output jtag_inst1_TDO,

   //Clocks 
	input	wire	i_arstn,
    input wire key_minus_n,key_plus_n,key_select_n,
    input	wire	i_mipi_rx_pclk,
    input wire  vid_clk_dvi2,
    input wire hdmi_tx_slow_clk,
    input wire CLK_5M,
    input  wire CLK_25M,
	output  wire    pll_inst1_RSTN,
	input	wire	i_pll_locked,
	input 	wire  	pll_locked,
	output  wire    pll_inst4_RSTN,
	input   wire    pll_inst4_LOCKED,
	output  wire  	USER_PLL_RSTN,
    output 	wire 	DDR3_PLL_RSTN,
	input 	wire  	user_pll_locked,
    //CSI Interface
    input	 wire		io_cam_sda_IN,
    output wire   io_cam_sda_OUT,
    output wire		io_cam_sda_OE,

    output io_cam_scl_OUT,
    input io_cam_scl_IN,
    output io_cam_scl_OE,

    output	wire		o_cam_rst_p,
    
    input	wire		i_cam_ck_LP_P_IN,
    input	wire		i_cam_ck_LP_N_IN,
    output	wire		o_cam_ck_HS_TERM,
    output	wire		o_cam_ck_HS_ENA,
    input	wire		i_cam_ck_CLKOUT,
    
    input	wire	[7:0]			cam_d0_HS_IN,
    input	  wire		      cam_d0_LP_P_IN,
    input	  wire		      cam_d0_LP_N_IN,
    output	wire		      cam_d0_HS_TERM,
    output	wire		      cam_d0_HS_ENA,
    output	wire		      cam_d0_RST,
    output	wire		      cam_d0_FIFO_RD,
    input	  wire		      cam_d0_FIFO_EMPTY,
    
    input 	wire	[7:0]			cam_d1_HS_IN,
    input	  wire		        cam_d1_LP_P_IN,
    input	  wire		        cam_d1_LP_N_IN,
    output	wire		        cam_d1_HS_TERM,
    output	wire		        cam_d1_HS_ENA,
    output	wire		        cam_d1_RST,
    output	wire		        cam_d1_FIFO_RD,
    input	  wire		        cam_d1_FIFO_EMPTY,
    
    input 	wire	[7:0]			cam_d2_HS_IN,
    input	  wire		        cam_d2_LP_P_IN,
    input	  wire		        cam_d2_LP_N_IN,
    output	wire		        cam_d2_HS_TERM,
    output	wire		        cam_d2_HS_ENA,
    output	wire		        cam_d2_RST,
    output	wire		        cam_d2_FIFO_RD,
    input	  wire		        cam_d2_FIFO_EMPTY,  
   
    input 	wire	[7:0]			cam_d3_HS_IN,
    input	  wire		        cam_d3_LP_P_IN,
    input	  wire		        cam_d3_LP_N_IN,
    output	wire		        cam_d3_HS_TERM,
    output	wire		        cam_d3_HS_ENA,
    output	wire		        cam_d3_RST,
    output	wire		        cam_d3_FIFO_RD,
    input	  wire		        cam_d3_FIFO_EMPTY,

	
	input 					tx_cal_clk_90edge,
  	input 					rx_cal_clk,
  	input 					tx_cal_clk,
	input                              core_clk,     // CORE CLK @ 100MHz
	input                              sdram_clk,    // SDRAM CK @ 400MHz
	// PLL status flags  
	output [2:0]                       pll_shift,  
	output [4:0]                       pll_shift_sel,
	output                             pll_shift_ena,  
	// memory interface ports
	output                             ddr_ck_hi,
	output                             ddr_ck_lo,
	output                             ddr_reset_n,
	output [CKE_WIDTH-1:0]             ddr_cke,     
	output [ROW_WIDTH-1:0]             ddr_addr,
	output [BANK_WIDTH-1:0]            ddr_ba,
	output                             ddr_cas_n,
 
	output [CS_WIDTH*RANK_RATIO-1:0]   ddr_cs_n,
	output                             ddr_ras_n,
	output                             ddr_we_n,
	
	input  [DQS_WIDTH-1:0]             ddr_dqs_in_hi,
	input  [DQS_WIDTH-1:0]             ddr_dqs_in_lo,
	input  [DQ_WIDTH-1:0]              ddr_dq_in_hi,
	input  [DQ_WIDTH-1:0]              ddr_dq_in_lo,
	
	output [DQS_WIDTH-1:0]             ddr_dqs_oe,
	output [DQS_WIDTH-1:0]             ddr_dqs_oe_n,
	output [DQ_WIDTH-1:0]              ddr_dq_oe,  
	output [DQS_WIDTH-1:0]             ddr_dqs_out_hi,
	output [DQS_WIDTH-1:0]             ddr_dqs_out_lo,
	output [DQ_WIDTH-1:0]              ddr_dq_out_hi,
	output [DQ_WIDTH-1:0]              ddr_dq_out_lo,
	output [DM_WIDTH-1:0]              ddr_dm_hi,
	output [DM_WIDTH-1:0]              ddr_dm_lo,
	output [ODT_WIDTH-1:0]             ddr_odt,

       //LED
       output [7:0] led,

       // MIPI DSI
       input	wire	                     i_mipi_tx_pclk		,
       output	wire	                     mipi_dp_clk_LP_P_OUT		,
       output	wire	                     mipi_dp_clk_LP_N_OUT		,
       output	wire	[7:0] 	              mipi_dp_clk_HS_OUT		,
       output	wire	                     mipi_dp_clk_HS_OE		,
       output	wire	                     mipi_dp_data3_LP_P_OUT	,
       output	wire	                     mipi_dp_data2_LP_P_OUT	,
       output	wire	                     mipi_dp_data1_LP_P_OUT	,
       output	wire	                     mipi_dp_data0_LP_P_OUT	,
       output	wire	                     mipi_dp_data3_LP_N_OUT	,
       output	wire	                     mipi_dp_data2_LP_N_OUT	,
       output	wire	                     mipi_dp_data1_LP_N_OUT	,
       output	wire	                     mipi_dp_data0_LP_N_OUT	,
       output	wire	[7:0] 	              mipi_dp_data0_HS_OUT	       ,
       output	wire	[7:0] 	              mipi_dp_data1_HS_OUT	       ,
       output	wire	[7:0] 	              mipi_dp_data2_HS_OUT	       ,
       output	wire	[7:0] 	              mipi_dp_data3_HS_OUT	       ,
       output	wire	                     mipi_dp_data3_HS_OE		,
       output	wire	                     mipi_dp_data2_HS_OE		,
       output	wire	                     mipi_dp_data1_HS_OE		,
       output	wire	                     mipi_dp_data0_HS_OE		,

       output	wire	                     mipi_dp_clk_RST		,
       output	wire	                     mipi_dp_data0_RST		,
       output	wire	                     mipi_dp_data1_RST		,
       output	wire	                     mipi_dp_data2_RST		,
       output	wire	                     mipi_dp_data3_RST		,
       output	wire	                     mipi_dp_clk_LP_P_OE		,
       output	wire	                     mipi_dp_clk_LP_N_OE		,
       output	wire	                     mipi_dp_data3_LP_P_OE	,
       output	wire	                     mipi_dp_data3_LP_N_OE	,
       output	wire	                     mipi_dp_data2_LP_P_OE	,
       output	wire	                     mipi_dp_data2_LP_N_OE	,
       output	wire	                     mipi_dp_data1_LP_P_OE	,
       output	wire	                     mipi_dp_data1_LP_N_OE	,
       output	wire	                     mipi_dp_data0_LP_P_OE	,
       output	wire	                     mipi_dp_data0_LP_N_OE	,

       input  wire	                     mipi_dp_data0_LP_P_IN	,
       input  wire	                     mipi_dp_data0_LP_N_IN	,
       output	wire	                     LCD_RST_P			,
       output wire                        LCD_POWER			,

       // hdmi interface

    output tmds_tx_clk_TX_OE,
    output [9:0] tmds_tx_clk_TX_DATA,
    output tmds_tx_clk_TX_RST,
    output tmds_tx_data0_TX_OE,
    output [9:0] tmds_tx_data0_TX_DATA,
    output tmds_tx_data0_TX_RST,
    output tmds_tx_data1_TX_OE,
    output [9:0] tmds_tx_data1_TX_DATA,
    output tmds_tx_data1_TX_RST,
    output tmds_tx_data2_TX_OE,
    output [9:0] tmds_tx_data2_TX_DATA,
    output tmds_tx_data2_TX_RST


);

function integer log2;
	input	integer	val;
	integer	i;
	begin
		log2 = 0;
		for (i=0; 2**i<val; i=i+1)
			log2 = i+1;
	end
endfunction


//===============================================================================
//localparam
//===============================================================================
localparam WR_FIFO_DEPTH  = 1024;
localparam RD_FIFO_DEPTH  = 1024;

// localparam	MAX_HRES		= 12'd1920;
// localparam	MAX_VRES		= 12'd1080;
// localparam	HSP			= 8'd2;
// localparam	HBP			= 8'd88;
// localparam	HFP			= 8'd120;
// localparam	VSP			= 8'd2;
// localparam	VBP			= 8'd20;
// localparam	VFP			= 8'd20;

localparam HACT     = 1280;
localparam HFP      = 110;
localparam HSP      = 40;
localparam HBP      = 220;

localparam VACT     = 720;
localparam VFP      = 5;
localparam VSP      = 5;
localparam VBP      = 20;
//===============================================================================
//signal
//===============================================================================
   
wire                              app_sr_active;
wire                              app_ref_ack;
wire                              app_zq_ack;
wire                              cal_done;

// Slave Interface Write Address Ports
wire [AXI_ID_WIDTH-1:0]           s_axi_awid;
wire [AXI_ADDR_WIDTH-1:0]         s_axi_awaddr;
wire [7:0]                        s_axi_awlen;
wire [2:0]                        s_axi_awsize;
wire [1:0]                        s_axi_awburst;
wire [0:0]                        s_axi_awlock;
wire [3:0]                        s_axi_awcache;
wire [2:0]                        s_axi_awprot;
wire                              s_axi_awvalid;
wire                              s_axi_awready;
// Slave Interface Write Data Ports
wire [AXI_DATA_WIDTH-1:0]         s_axi_wdata;
wire [(AXI_DATA_WIDTH/8)-1:0]     s_axi_wstrb;
wire                              s_axi_wlast;
wire                              s_axi_wvalid;
wire                              s_axi_wready;
// Slave Interface Write Response Ports
wire                              s_axi_bready;
wire [AXI_ID_WIDTH-1:0]           s_axi_bid;
wire [1:0]                        s_axi_bresp;
wire                              s_axi_bvalid;
// Slave Interface Read Address Ports
wire [AXI_ID_WIDTH-1:0]           s_axi_arid;
wire [AXI_ADDR_WIDTH-1:0]         s_axi_araddr;
wire [7:0]                        s_axi_arlen;
wire [2:0]                        s_axi_arsize;
wire [1:0]                        s_axi_arburst;
wire [0:0]                        s_axi_arlock;
wire [3:0]                        s_axi_arcache;
wire [2:0]                        s_axi_arprot;
wire                              s_axi_arvalid;
wire                              s_axi_arready;
// Slave Interface Read Data Ports
wire                              s_axi_rready;
wire [AXI_ID_WIDTH-1:0]           s_axi_rid;
wire [AXI_DATA_WIDTH-1:0]         s_axi_rdata;
wire [1:0]                        s_axi_rresp;
wire                              s_axi_rlast;
wire                              s_axi_rvalid;




////////////////////////////////////////////////////////////////
// System & Debugger
wire    w_arstn;
// wire	w_sysclk_mcu_arstn;
// wire	w_sysclk_mcu_arst;
wire	w_mipi_rx_pclk_arstn;
wire	w_mipi_rx_pclk_arst;

wire		       w_mipi_rx_vs;
wire		       w_mipi_rx_hs;
wire	       w_mipi_rx_de;
wire	[63:0]			w_mipi_rx_data	;

wire					io_systemReset;



//===================================================================================================
//reset module
//===================================================================================================

assign w_arstn  		       = i_pll_locked & pll_locked & user_pll_locked;
assign pll_inst1_RSTN  		= i_arstn;
assign USER_PLL_RSTN      		= i_arstn;
assign mipi_dsi_tx_pll_RSTN 	= i_arstn;
assign DDR3_PLL_RSTN 		= i_arstn;
reset_ctrl
#(
	.NUM_RST		(2),
	.CYCLE			(1),
	.IN_RST_ACTIVE	(4'b00),
	.OUT_RST_ACTIVE	(4'b10)
)
inst_reset_ctrl
(
	.i_arst		({2{w_arstn}}),//({{4{i_pll_locked}},                  {2{i_arstn}}}),
	.i_clk			({2{i_mipi_rx_pclk}}),
	.o_srst		({w_mipi_rx_pclk_arst, w_mipi_rx_pclk_arstn})
);



reg [25:0] cnt = 'd0;
always @( posedge core_clk)
begin 
       cnt <= cnt + 1'b1;
end
assign led[0]  = cal_done ? cnt[24] : 1'b0;

//========================================================================================================
//MIPI RX
//========================================================================================================
wire i_mipi_clk ;
assign i_mipi_clk = core_clk;

		assign	cam_d0_RST		= 1'b0;
		assign	cam_d1_RST		= 1'b0;
		assign  cam_d2_RST = 1'b0;
    assign  cam_d3_RST = 1'b0;
	
wire [15:0] mipi_debug_out;
		

		csi_rx_controller inst_efx_csi2_rx
		(
              .reset_n			(i_arstn),
              .clk				(i_mipi_clk),
              .reset_byte_HS_n	(i_arstn),
              .clk_byte_HS		  (i_cam_ck_CLKOUT),
              .reset_pixel_n		(w_mipi_rx_pclk_arstn),
              .clk_pixel			  (i_mipi_rx_pclk),
              
              .Rx_LP_CLK_P		  (i_cam_ck_LP_P_IN),
              .Rx_LP_CLK_N		  (i_cam_ck_LP_N_IN),
              .Rx_HS_enable_C		(o_cam_ck_HS_ENA),
              .LVDS_termen_C		(o_cam_ck_HS_TERM),
              
              .Rx_LP_D_P			({cam_d3_LP_P_IN, cam_d2_LP_P_IN, cam_d1_LP_P_IN, cam_d0_LP_P_IN}),//(r_mipi_rx_data_LP_P_IN_2P),
              .Rx_LP_D_N			({cam_d3_LP_N_IN, cam_d2_LP_N_IN, cam_d1_LP_N_IN, cam_d0_LP_N_IN}),//(r_mipi_rx_data_LP_N_IN_2P),
              .Rx_HS_D_0			(cam_d0_HS_IN),//(r_mipi_rx_data_HS_IN_2P[0*8+:8]),
              .Rx_HS_D_1			(cam_d1_HS_IN),//(r_mipi_rx_data_HS_IN_2P[1*8+:8]),
              .Rx_HS_D_2			(cam_d2_HS_IN),
              .Rx_HS_D_3			(cam_d3_HS_IN),
              .Rx_HS_D_4			(),
              .Rx_HS_D_5			(),
              .Rx_HS_D_6			(),
              .Rx_HS_D_7			(),
              .Rx_HS_enable_D		({cam_d3_HS_ENA    ,cam_d2_HS_ENA    ,cam_d1_HS_ENA    ,cam_d0_HS_ENA    }),//( w_cam_d_HS_ENA),
              .LVDS_termen_D		({cam_d3_HS_TERM   ,cam_d2_HS_TERM   ,cam_d1_HS_TERM   ,cam_d0_HS_TERM   }),
              .fifo_rd_enable		({cam_d3_FIFO_RD   ,cam_d2_FIFO_RD   ,cam_d1_FIFO_RD   ,cam_d0_FIFO_RD   }),
              .fifo_rd_empty		({cam_d3_FIFO_EMPTY,cam_d2_FIFO_EMPTY,cam_d1_FIFO_EMPTY,cam_d0_FIFO_EMPTY}),
              .DLY_enable_D		       (),
              .DLY_inc_D			(),
              .u_dly_enable_D		(),
              .u_dly_inc_D		       (),
              
              .axi_clk			(1'b0),
              .axi_reset_n		       (1'b0),
              .axi_awaddr			(6'b0),
              .axi_awvalid		       (1'b0),
              .axi_awready		       (),
              .axi_wdata			(32'b0),
              .axi_wvalid			(1'b0),
              .axi_wready			(),
              
              .axi_bvalid			(),
              .axi_bready			(1'b0),
              .axi_araddr			(6'b0),
              .axi_arvalid		       (1'b0),
              .axi_arready		       (),
              .axi_rdata			(),
              .axi_rvalid			(),
              .axi_rready			(1'b1),
              
              .hsync_vc0			(w_mipi_rx_hs),
              .hsync_vc1			(),
              .hsync_vc2			(),
              .hsync_vc3			(),
              .vsync_vc0			(w_mipi_rx_vs),
              .vsync_vc1			(),
              .vsync_vc2			(),
              .vsync_vc3			(),
              .vc				(),
              .word_count			(),
              .shortpkt_data_field        (),
              .datatype			(),
              .pixel_per_clk		(),
              .pixel_data			(w_mipi_rx_data),
              .pixel_data_valid	       (w_mipi_rx_de),
              .irq				(),
              .mipi_debug_out(mipi_debug_out)
		);

//     wire		       w1_mipi_rx_vs;
// wire		       w1_mipi_rx_hs;
// wire	       w1_mipi_rx_de;
// wire	[39:0]			w1_mipi_rx_data	;
// sensor_clipper  sensor_clipper_inst (
//     .clk(i_mipi_rx_pclk),
//     .i_vs(w_mipi_rx_vs),
//     .i_hs(w_mipi_rx_hs),
//     .i_de(w_mipi_rx_de),
//     .i_dat(w_mipi_rx_data[39:0]),

//     .o_hs(w1_mipi_rx_hs),
//     .o_vs(w1_mipi_rx_vs),
//     .o_de(w1_mipi_rx_de),
//     .o_dat(w1_mipi_rx_data)
   
//   );


wire mdebug_pixel_fifo_full     = mipi_debug_out[0] ;
wire mdebug_pixel_fifo_empty    = mipi_debug_out[1] ;
wire mdebug_crc_error           = mipi_debug_out[2] ;
wire mdebug_ecc_1bit_error      = mipi_debug_out[3] ;
wire mdebug_ecc_2bit_error      = mipi_debug_out[4] ;
wire mdebug_undersize_pkt_error = mipi_debug_out[5] ;
wire mdebug_line_vc0_error      = mipi_debug_out[6] ;
wire mdebug_frame_vc0_error    = mipi_debug_out[10];   
wire mdebug_receive_error      = mipi_debug_out[14];


//========================================================================================================
//
//========================================================================================================
		

//*************** imx219 in_config********************/
// mipi_config_imx219_top u_config_imx219(
// 										.i_sys_clk(CLK_5M)    	,    /////48M 
// 										.sys_rstn(vid_rst_n )    ,
// 										.o_sen_rst_n(o_cam_rstn)  	,
										
										// .o_iic_sda_OE(io_cam_sda_OE) ,
										// .i_iic_sda(io_cam_sda_IN)   	,
										// .o_iic_sda(io_cam_sda_OUT)   	,
										// .o_iic_scl(io_cam_scl)    	
										// ); 	

wire [25:0] sensor_command;
wire [10:0] sensor_response;
(* async_reg="true" *) reg [1:0] sensor_ack_sync, sensor_ready_sync;
reg [9:0] sensor_reply;
wire [10:0] sensor_response_cdc={sensor_reply[9:2],sensor_ready_sync[1],sensor_reply[1:0]};
// Bundled response remains fixed until the host sends its next request.
always @(posedge i_mipi_rx_pclk) begin
 if(!w_arstn) begin sensor_ack_sync<=0;sensor_ready_sync<=0;sensor_reply<=0;end
 else begin
  sensor_ack_sync<={sensor_ack_sync[0],sensor_response[0]};
  sensor_ready_sync<={sensor_ready_sync[0],sensor_response[2]};
  if(sensor_ack_sync[1]!=sensor_reply[0])
   sensor_reply<={sensor_response[10:3],sensor_response[1],sensor_ack_sync[1]};
 end
end
wire scl_padoen_o;
wire sda_padoen_o;


reg [12:0] i2c_rst_cnt = '0;

always @( posedge CLK_5M or negedge w_arstn )
begin
    if( !w_arstn )
       i2c_rst_cnt <= 'd0;
    else 
       i2c_rst_cnt <= i2c_rst_cnt[12] ? i2c_rst_cnt : i2c_rst_cnt + 1'b1;
end
wire i2c_rst_n = i2c_rst_cnt[12];

i2c_master_ctrl_top u2_i2c_master_ctrl_top(
  .sensor_command(sensor_command), .sensor_response(sensor_response),
  .frame_toggle(w_mipi_rx_vs),
  /*i*/.clk			(CLK_5M		),
  /*i*/.rst_n			(i2c_rst_n		),
  /*i*/.scl_pad_i     (io_cam_scl_IN),//(1'b1),
  /*o*/.scl_pad_o     (io_cam_scl_OUT),
  /*o*/.scl_padoen_o  (scl_padoen_o),
  /*i*/.sda_pad_i     (io_cam_sda_IN),
  /*o*/.sda_pad_o     (io_cam_sda_OUT),
  /*o*/.sda_padoen_o  (sda_padoen_o)
  
  );
assign o_cam_rst_p = ~w_arstn;
assign io_cam_scl_OE = ~scl_padoen_o;
assign io_cam_sda_OE = ~sda_padoen_o;

//=====================================================================================
//frame buffer
//=====================================================================================
wire [7:0] 	ch0_r;
wire [7:0]    ch0_g;
wire [7:0]    ch0_b;
wire ch0_vs;
wire ch0_hs;
wire ch0_de;

wire [63:0] debug_write_status,debug_bank_addresses;
wire [63:0] stored_pixels;
wire [63:0] frame_algorithm_pixels;
wire frame_algorithm_valid,frame_algorithm_sof,frame_algorithm_eol,frame_algorithm_eof,sobel_store_ready;
wire [31:0] frame_algorithm_id,frame_algorithm_epoch,frame_capture_overflow,frame_result_overflow;
wire [15:0] frame_algorithm_config;
wire [3:0] frame_command;
wire frame_command_toggle,frame_command_ack,reference_sel,frame_shown_toggle;
wire [293:0] frame_display_descriptor;wire [300:0] frame_shown_descriptor;
reg [252:0] shape_shown;
(* async_reg="true" *) reg [1:0] shape_shown_sync;
reg shape_shown_ack;
// The HDMI descriptor stays fixed for a whole frame. Its toggle crosses first;
// the bundled payload has settled before the destination captures it.
always @(posedge i_mipi_rx_pclk) begin
 if(!vid_rst_n) begin shape_shown<=0;shape_shown_sync<=0;shape_shown_ack<=0;end
 else begin
  shape_shown_sync<={shape_shown_sync[0],frame_shown_toggle};
  if(shape_shown_sync[1]!=shape_shown_ack) begin
   shape_shown<={frame_shown_descriptor[293:105],frame_shown_descriptor[63:0]};
   shape_shown_ack<=shape_shown_sync[1];
  end
 end
end
wire [319:0] frame_status;
wire [159:0] frame_traffic;
wire [223:0] algorithm_status;
wire [3:0] jtag_frame_command;
wire jtag_frame_toggle,jtag_frame_ack,jtag_reference,jtag_gray,jtag_edge,jtag_overlay,jtag_denoise,jtag_median;
wire ui_apply,ui_apply_ack,ui_median,ui_busy,ui_algorithm,jtag_algorithm;
wire [1:0] ui_ratio,jtag_ratio;
wire ui_recognition,jtag_recognition;reg recognition_active=0;
reg algorithm_active=0;reg [1:0] ratio_active=1;
wire [31:0] selected_epoch=config_epoch+threshold_epoch+median_epoch;
wire [2:0] ui_focus;wire [1:0] ui_presses;
wire [3:0] ui_action;
wire [2:0] ui_view,ui_error;
wire [31:0] ui_short_events,ui_long_events;
wire [63:0] ui_display_status;
wire [31:0] ui_state={8'd0,ui_recognition,(frame_status[127:96]!=selected_epoch),flags_shown[5:3],ui_ratio,ui_algorithm,ui_apply_ack,ui_error,ui_busy,ui_median,ui_view,ui_action,ui_focus};
reg [25:0] fps_timer=0;
reg [31:0] fps_capture_last=0,fps_process_last=0;
reg [7:0] capture_fps=0,process_fps=0;
always @(posedge i_mipi_rx_pclk) begin
 if(!w_arstn) begin fps_timer<=0;fps_capture_last<=0;fps_process_last<=0;capture_fps<=0;process_fps<=0;end
 else if(fps_timer==49999999) begin
  fps_timer<=0;capture_fps<=full_frames-fps_capture_last;process_fps<=algorithm_status[31:0]-fps_process_last;
  fps_capture_last<=full_frames;fps_process_last<=algorithm_status[31:0];
 end else fps_timer<=fps_timer+1'b1;
end
wire [2:0] jtag_view=jtag_reference?3'd6:jtag_denoise?3'd4:jtag_gray && jtag_edge?3'd3:
                       jtag_overlay?3'd5:jtag_edge?3'd2:jtag_gray?3'd1:3'd0;
edge_ui user_controls(.clk(i_mipi_rx_pclk),.rst_n(w_arstn),.key_select_n(key_select_n),
 .presses(ui_presses),.keys(threshold_keys),.frame_mode(frame_status[2:0]),.reference_valid(frame_status[14]),
 .jtag_view(jtag_view),.jtag_recognition(jtag_recognition),.jtag_median(jtag_median),.jtag_algorithm(jtag_algorithm),.jtag_ratio(jtag_ratio),.jtag_apply(ui_apply),.jtag_apply_ack(ui_apply_ack),
 .jtag_command(jtag_frame_command),.jtag_command_toggle(jtag_frame_toggle),.jtag_command_ack(jtag_frame_ack),
 .frame_command(frame_command),.frame_toggle(frame_command_toggle),.frame_ack(frame_command_ack),
 .focus(ui_focus),.action(ui_action),.view(ui_view),.recognition(ui_recognition),.median(ui_median),.algorithm(ui_algorithm),.ratio(ui_ratio),
 .short_events(ui_short_events),.long_events(ui_long_events),.error(ui_error),.busy(ui_busy));
assign gray_sel=ui_view==1 || ui_view==3 || ui_view==4 || ui_view==6;
assign edge_sel=ui_view==2 || ui_view==3 || ui_view==4 || ui_view==6;
assign overlay_sel=ui_view==5;
assign median_set=ui_median;
assign denoise_set=ui_view==4;
assign reference_sel=ui_view==6;
frame_mailbox #(.WIDTH(64)) ui_display_cdc(.rst_n(w_arstn),.src_clk(i_mipi_rx_pclk),.dst_clk(hdmi_tx_slow_clk),
 .src_data({capture_fps,process_fps,frame_status[8:3],frame_status[18:15],6'd0,ui_state}),
 .delivered(),.dst_data(ui_display_status));


reg [31:0] debug_written_pixel=0,debug_read_pixel=0;
always @(posedge core_clk) begin
 if(s_axi_wvalid && s_axi_wready) debug_written_pixel<=s_axi_wdata[31:0];
 if(s_axi_rvalid && s_axi_rready) debug_read_pixel<=s_axi_rdata[31:0];
end
wire [31:0] source_signature;
wire [127:0] ddr_pixels;
wire ddr_valid,ddr_ready;
wire [31:0] m_axis_tdata;
wire [31:0] display_rgb;
wire display_underflow;
wire           m_axis_tvalid;
wire           m_axis_tready;
wire           m_axis_tlast;
wire           m_axis_tuser;
wire  fifo_rd_period;
// IMX219
  frame_store #(.ENABLE_CANNY(1),.ENABLE_SHAPE(1)) checker0(
 .rst_n(vid_rst_n),.core_clk(core_clk),.pixel_clk(i_mipi_rx_pclk),.display_clk(hdmi_tx_slow_clk),.enabled(cal_done),
 .capture_pixels(gray_rgby),.capture_valid(gray_valid),.capture_sof(gray_sof),.capture_eof(gray_eof),.capture_frame_id(gray_frame_id),
 .recognition_enable(recognition_active),.config_value({ratio_active,algorithm_active,denoise_active,median_active,threshold_active}),.config_epoch(config_epoch+threshold_epoch+median_epoch),
 .algorithm_pixels(frame_algorithm_pixels),.algorithm_valid(frame_algorithm_valid),.algorithm_ready(median_ready),
 .algorithm_sof(frame_algorithm_sof),.algorithm_eol(frame_algorithm_eol),.algorithm_eof(frame_algorithm_eof),
 .algorithm_frame_id(frame_algorithm_id),.algorithm_epoch(frame_algorithm_epoch),.algorithm_config(frame_algorithm_config),
 .result_pixels(stored_pixels),.result_valid(sobel_valid),.result_sof(sobel_sof),.result_eof(sobel_eof),.result_ready(sobel_store_ready),
 .command(frame_command),.command_toggle(frame_command_toggle),.command_ack(frame_command_ack),
 .reference_mode(reference_sel),.display_period(fifo_rd_period),
 .display_pixels(ddr_pixels),.display_valid(ddr_valid),.display_ready(ddr_ready),.display_descriptor(frame_display_descriptor),
 .shown_toggle(frame_shown_toggle),.shown_slot(frame_shown_descriptor[97:96]),.status(frame_status),.traffic(frame_traffic),.algorithm_status(algorithm_status),
 .capture_overflow(frame_capture_overflow),.result_overflow(frame_result_overflow),
 .awaddr(s_axi_awaddr),.araddr(s_axi_araddr),.awlen(s_axi_awlen),.arlen(s_axi_arlen),
 .awvalid(s_axi_awvalid),.wvalid(s_axi_wvalid),.wlast(s_axi_wlast),.bready(s_axi_bready),
 .arvalid(s_axi_arvalid),.rready(s_axi_rready),.wdata(s_axi_wdata),.wstrb(s_axi_wstrb),
 .awready(s_axi_awready),.wready(s_axi_wready),.bvalid(s_axi_bvalid),.arready(s_axi_arready),
 .rvalid(s_axi_rvalid),.rlast(s_axi_rlast),.bresp(s_axi_bresp),.rresp(s_axi_rresp),.rdata(s_axi_rdata));
 assign s_axi_awid=0;assign s_axi_awsize=4;assign s_axi_awburst=1;assign s_axi_awlock=0;
 assign s_axi_awcache=3;assign s_axi_awprot=2;
 assign s_axi_arid=0;assign s_axi_arsize=4;assign s_axi_arburst=1;assign s_axi_arlock=0;
 assign s_axi_arcache=3;assign s_axi_arprot=2;
 assign debug_write_status=frame_status[319:256];
 assign debug_bank_addresses={s_axi_awaddr,s_axi_araddr};


		    
		    
cvo_axi # (
    .SYMBOL_WIDTH(8),
    .SYMBOL_NUM(4),
    .PIXEL_NUM(1),
    .HSYNC_POL(1),
    .VSYNC_POL(1),
    .FIFO_DEPTH(1024),
    .FIFO_ALMOST_FULL(1000),
    .MAX_H_VALID(1280),
    .MAX_V_VALID(720)
  )
  cvo_axi_inst (
    .o_clk          (hdmi_tx_slow_clk),
    .rst_n          (vid_rst_n      ),
    .fifo_rd_period (fifo_rd_period ),
    .fifo_rd_underflow(display_underflow),
    .s_axi_clk      (hdmi_tx_slow_clk),
    .s_axis_tdata   (m_axis_tdata   ),
    .s_axis_tvalid  (m_axis_tvalid  ),
    .s_axis_tready  (m_axis_tready  ),
    .s_axis_tlast   (m_axis_tlast   ),
    .s_axis_tuser   (m_axis_tuser   ),
    .H_FRONT_PORCH  (HFP            ),
    .H_SYNC         (HSP            ),
    .H_VALID        (HACT           ),
    .H_BACK_PORCH   (HBP            ),
    .V_FRONT_PORCH  (VFP            ),
    .V_SYNC         (VSP            ),
    .V_VALID        (VACT           ),
    .V_BACK_PORCH   (VBP            ),
     .vout          (display_rgb),
    .o_hs           (ch0_hs         ),
    .o_vs           (ch0_vs         ),
    .o_de           (ch0_de         )
  );		       


ddr3_top                 u_ddr3_top
(

.axi_clk                (core_clk            ),
.core_clk               (core_clk            ),
.sdram_clk              (sdram_clk           ),  
.rx_cal_clk             (rx_cal_clk          ),
.tx_cal_clk             (tx_cal_clk          ),
.tx_cal_clk_90edge      (tx_cal_clk_90edge   ),
.rstn                   (w_arstn             ),      
.pll_shift              (pll_shift           ),
.pll_shift_sel          (pll_shift_sel       ),
.pll_shift_ena          (pll_shift_ena       ),       
///////////////DDR BUS
.ddr_ck_hi              (ddr_ck_hi           ),
.ddr_ck_lo              (ddr_ck_lo           ),
.ddr_cke                (ddr_cke             ),    
.ddr_reset_n            (ddr_reset_n         ),
.ddr_cs_n               (ddr_cs_n            ),
.ddr_ras_n              (ddr_ras_n           ),
.ddr_cas_n              (ddr_cas_n           ),
.ddr_we_n               (ddr_we_n            ),     
.ddr_addr               (ddr_addr            ),
.ddr_ba                 (ddr_ba              ),

.ddr_dqs_oe             (ddr_dqs_oe          ),
.ddr_dqs_oe_n           (ddr_dqs_oe_n        ),
.ddr_dq_oe              (ddr_dq_oe           ),
.ddr_dqs_in_hi          (ddr_dqs_in_hi       ),
.ddr_dqs_in_lo          (ddr_dqs_in_lo       ),
.ddr_dq_in_hi           (ddr_dq_in_hi        ),
.ddr_dq_in_lo           (ddr_dq_in_lo        ),

.ddr_dqs_out_hi         (ddr_dqs_out_hi      ),
.ddr_dqs_out_lo         (ddr_dqs_out_lo      ),
.ddr_dq_out_hi          (ddr_dq_out_hi       ),
.ddr_dq_out_lo          (ddr_dq_out_lo       ),

.ddr_dm_hi              (ddr_dm_hi           ),
.ddr_dm_lo              (ddr_dm_lo           ),
.ddr_odt                (ddr_odt             ),

// Application interface ports
.app_sr_req                     (1'b0),
.app_ref_req                    (1'b0),
.app_zq_req                     (1'b0),
.app_sr_active                  (app_sr_active),
.app_ref_ack                    (app_ref_ack),
.app_zq_ack                     (app_zq_ack),

// Slave Interface Write Address Ports
.s_axi_awid                     (s_axi_awid        ),
.s_axi_awaddr                   (s_axi_awaddr      ),
.s_axi_awlen                    (s_axi_awlen       ),
.s_axi_awsize                   (s_axi_awsize      ),
.s_axi_awburst                  (s_axi_awburst     ),
.s_axi_awlock                   (s_axi_awlock      ),
.s_axi_awcache                  (s_axi_awcache     ),
.s_axi_awprot                   (s_axi_awprot      ),
.s_axi_awqos                    (4'h0              ),
.s_axi_awvalid                  (s_axi_awvalid     ),
.s_axi_awready                  (s_axi_awready     ),
// Slave Interface Write Data Ports
.s_axi_wdata                    (s_axi_wdata       ),
.s_axi_wstrb                    (s_axi_wstrb       ),
.s_axi_wlast                    (s_axi_wlast       ),
.s_axi_wvalid                   (s_axi_wvalid      ),
.s_axi_wready                   (s_axi_wready      ),
// Slave Interface Write Response Ports
.s_axi_bid                      (s_axi_bid         ),
.s_axi_bresp                    (s_axi_bresp       ),
.s_axi_bvalid                   (s_axi_bvalid      ),
.s_axi_bready                   (s_axi_bready      ),
// Slave Interface Read Address Ports
.s_axi_arid                     (s_axi_arid        ),
.s_axi_araddr                   (s_axi_araddr      ),
.s_axi_arlen                    (s_axi_arlen       ),
.s_axi_arsize                   (s_axi_arsize      ),
.s_axi_arburst                  (s_axi_arburst     ),
.s_axi_arlock                   (s_axi_arlock      ),
.s_axi_arcache                  (s_axi_arcache     ),
.s_axi_arprot                   (s_axi_arprot      ),
.s_axi_arqos                    (4'h0              ),
.s_axi_arvalid                  (s_axi_arvalid     ),
.s_axi_arready                  (s_axi_arready     ),
// Slave Interface Read Data Ports
.s_axi_rid                      (s_axi_rid         ),
.s_axi_rdata                    (s_axi_rdata       ),
.s_axi_rresp                    (s_axi_rresp       ),
.s_axi_rlast                    (s_axi_rlast       ),
.s_axi_rvalid                   (s_axi_rvalid      ),
.s_axi_rready                   (s_axi_rready      ),
//DEBUG       
.wrlvl_dq_check                 (wrlvl_dq_check    ) ,
.rd_level_dqs_check             (rd_level_dqs_check) ,
.init_cur_state                 (init_cur_state    ) ,
.idelay_ld                      (idelay_ld         ) ,
.mpr_rdlvl_dly                  (mpr_rdlvl_dly     ) ,
.cal_done                       (cal_done          ) 
);

//***************************************************************************
// debayer
//***************************************************************************


wire [15:0] r_gain,g_gain,b_gain;
wire [1:0] bayer_phase;
wire [31:0] full_frames,full_errors,sum_r,sum_g,sum_b;
wire [15:0] source_width,source_height;
wire full_vs,full_valid;
wire [63:0] full_rgb;
reg [15:0] active_r=397, active_g=256, active_b=471;
reg [1:0] active_phase=0;
reg [31:0] config_epoch=0;
reg camera_vs_d=0;
wire median_set,denoise_set;
reg median_active=1,denoise_active=0;
reg [31:0] median_epoch=0;
wire [15:0] algorithm_output_config;
wire median_ready;
wire [10:0] threshold_set,threshold_pending,threshold_active,sobel_frame_threshold;
wire threshold_toggle,threshold_ack;
wire [31:0] threshold_epoch,key_minus_events,key_plus_events;
wire [1:0] threshold_keys;
threshold_control threshold_controls(
 .clk(i_mipi_rx_pclk),.rst_n(w_arstn),.frame_start(w_mipi_rx_vs && !camera_vs_d),
 .key_minus_n(key_minus_n),.key_plus_n(key_plus_n),.canny_enabled(ui_algorithm),.adjust_enable(ui_focus==2),.press_events(ui_presses),
 .jtag_value(threshold_set),.jtag_toggle(threshold_toggle),.jtag_ack(threshold_ack),
 .pending(threshold_pending),.active(threshold_active),.epoch(threshold_epoch),
 .minus_events(key_minus_events),.plus_events(key_plus_events),.keys(threshold_keys));
always @(posedge i_mipi_rx_pclk) begin
 if (!w_arstn) begin
  active_r<=397; active_g<=256; active_b<=471; active_phase<=0;
  config_epoch<=0; camera_vs_d<=0;median_active<=1;denoise_active<=0;median_epoch<=0;algorithm_active<=0;ratio_active<=1;recognition_active<=0;
 end else begin
  camera_vs_d<=w_mipi_rx_vs;
  if (w_mipi_rx_vs && !camera_vs_d) begin
   median_active<=median_set;denoise_active<=denoise_set;algorithm_active<=ui_algorithm;ratio_active<=ui_ratio;recognition_active<=ui_recognition;
   if({recognition_active,median_active,denoise_active,algorithm_active,ratio_active}!={ui_recognition,median_set,denoise_set,ui_algorithm,ui_ratio}) median_epoch<=median_epoch+1'b1;
   active_r<=r_gain; active_g<=g_gain; active_b<=b_gain; active_phase<=bayer_phase;
   if ({r_gain,g_gain,b_gain,bayer_phase} != {active_r,active_g,active_b,active_phase})
    config_epoch<=config_epoch+1'b1;
  end
 end
end
raw_full_view full_view(
 .clk(i_mipi_rx_pclk),.rst_n(w_arstn),
 .vs(w_mipi_rx_vs),.hs(w_mipi_rx_hs),.valid(w_mipi_rx_de),
 .raw4(w_mipi_rx_data[39:0]),.phase(active_phase),
 .gain_r(active_r),.gain_g(active_g),.gain_b(active_b),
 .out_vs(full_vs),.out_valid(full_valid),.rgb2(full_rgb),
 .frames(full_frames),.errors(full_errors),
 .measured_width(source_width),.measured_height(source_height),
 .sum_r(sum_r),.sum_g(sum_g),.sum_b(sum_b));
// Calculate exact M02 luminance before the Sobel window.
wire [63:0] gray_rgby;
wire gray_valid,gray_sof,gray_eol,gray_eof;
wire [31:0] gray_frame_id,gray_epoch;
reg gray_vs=0;
reg [19:0] gray_pair=0;
reg [9:0] gray_x=0;
reg [31:0] processed_frames=0,last_frame_id=0,last_epoch=0;
always @(posedge i_mipi_rx_pclk) begin
 if (!w_arstn) begin
  gray_vs<=0; gray_pair<=0; gray_x<=0;
  processed_frames<=0; last_frame_id<=0; last_epoch<=0;
 end else begin
  gray_vs<=full_vs;
  if (full_vs != gray_vs) begin gray_pair<=0; gray_x<=0; end
  else if (full_valid) begin
   gray_pair<=gray_pair+1'b1;
   gray_x<=(gray_x==639)?0:gray_x+1'b1;
  end
  begin
   processed_frames<=algorithm_status[31:0];
   last_frame_id<=algorithm_status[63:32];last_epoch<=algorithm_status[95:64];
  end
 end
end
rgb_to_gray gray_pipeline(
 .clk(i_mipi_rx_pclk),.rst_n(w_arstn),
 .in_valid(full_valid),.in_ready(),.in_rgb(full_rgb),
 .in_sof(gray_pair==0),.in_eol(gray_x==639),.in_eof(gray_pair==460799),
 .in_frame_id(full_frames+32'd1),.in_epoch(config_epoch+threshold_epoch+median_epoch),
 .out_valid(gray_valid),.out_ready(1'b1),.out_rgby(gray_rgby),
 .out_sof(gray_sof),.out_eol(gray_eol),.out_eof(gray_eof),
 .out_frame_id(gray_frame_id),.out_epoch(gray_epoch));

// M03 keeps RGB intact and replaces the stored Y byte with binary edge.
wire sobel_valid,sobel_sof,sobel_eol,sobel_eof;
wire [31:0] sobel_frame_id,sobel_epoch;
reg [31:0] sobel_overrun_cycles=0;
edge_algorithm_pair algorithm_pipeline(
 .clk(i_mipi_rx_pclk),.rst_n(w_arstn),.in_config(frame_algorithm_config),
 .in_pixels(frame_algorithm_pixels),.in_valid(frame_algorithm_valid),.in_ready(median_ready),
 .in_sof(frame_algorithm_sof),.in_eol(frame_algorithm_eol),.in_eof(frame_algorithm_eof),.in_id(frame_algorithm_id),.in_epoch(frame_algorithm_epoch),
 .out_pixels(stored_pixels),.out_valid(sobel_valid),.out_ready(sobel_store_ready),
 .out_sof(sobel_sof),.out_eol(sobel_eol),.out_eof(sobel_eof),.out_id(sobel_frame_id),.out_epoch(sobel_epoch),.out_config(algorithm_output_config));
assign sobel_frame_threshold=algorithm_output_config[10:0];
// Assert frame sync in input blanking and hold it until the synthetic final
// row is complete. Starting at input SOF leaves a full row for DDR reset.
reg sobel_vs=1;
always @(posedge i_mipi_rx_pclk) begin
 if(!w_arstn) begin sobel_vs<=1; sobel_overrun_cycles<=0; end
 else begin
  if(gray_valid && gray_sof) sobel_vs<=0;
  if(sobel_valid && sobel_eof) sobel_vs<=1;
  sobel_overrun_cycles<=frame_capture_overflow;
 end
end

// Single-bit requests cross through two registers, then commit in blanking.
wire gray_sel,edge_sel,overlay_sel;
reg [1:0] overlay_sync=0,active_overlay_sync=0;
reg display_overlay=0;
reg [1:0] edge_sync=3;
reg display_edge=1;
reg [1:0] gray_sync=3,gamma_sync=0;
reg display_gray=1,display_gamma=0,display_vs_d=0;
always @(posedge hdmi_tx_slow_clk) begin
 if (!vid_rst_n) begin
  overlay_sync<=0;display_overlay<=0;edge_sync<=3; display_edge<=1; gray_sync<=3; gamma_sync<=0; display_gray<=1; display_gamma<=0; display_vs_d<=0;
 end else begin
  overlay_sync<={overlay_sync[0],overlay_sel};
  edge_sync<={edge_sync[0],edge_sel};
  gray_sync<={gray_sync[0],gray_sel}; gamma_sync<={gamma_sync[0],gamma_sel};
  display_vs_d<=ch0_vs;
  if (ch0_vs && !display_vs_d) begin
   display_overlay<=overlay_sync[1];display_edge<=edge_sync[1]; display_gray<=gray_sync[1]; display_gamma<=gamma_sync[1];
  end
 end
end
reg [1:0] active_gray_sync=3,active_gamma_sync=0,active_edge_sync=3;
reg [31:0] mipi_flag_cycles=0;
always @(posedge i_mipi_rx_pclk) begin
 if (!w_arstn) begin
  active_overlay_sync<=0;active_edge_sync<=3; active_gray_sync<=3; active_gamma_sync<=0; mipi_flag_cycles<=0;
 end else begin
  active_overlay_sync<={active_overlay_sync[0],display_overlay};
  active_edge_sync<={active_edge_sync[0],display_edge};
  active_gray_sync<={active_gray_sync[0],display_gray};
  active_gamma_sync<={active_gamma_sync[0],display_gamma};
  if (|mipi_debug_out) mipi_flag_cycles<=mipi_flag_cycles+1'b1;
 end
end
reg [31:0] underflow_cycles=0,underflow_gray=0;
wire [31:0] underflow_next=underflow_cycles+32'd1;
always @(posedge hdmi_tx_slow_clk) begin
 if (!vid_rst_n) begin underflow_cycles<=0; underflow_gray<=0; end
 else if (display_underflow) begin
  underflow_cycles<=underflow_next;
  underflow_gray<=underflow_next^(underflow_next>>1);
 end
end
reg [31:0] underflow_sync1=0,underflow_sync2=0;
always @(posedge i_mipi_rx_pclk) begin
 if (!w_arstn) begin underflow_sync1<=0; underflow_sync2<=0; end
 else begin underflow_sync1<=underflow_gray; underflow_sync2<=underflow_sync1; end
end
wire [31:0] underflow_total;
genvar ub;
generate for (ub=0;ub<32;ub=ub+1) begin: decode_underflow
 assign underflow_total[ub]=^(underflow_sync2>>ub);
end endgenerate
wire compare_mode=display_edge && display_gray;
wire [31:0] mixed_words,display_frames;
compare_display display_compositor(
 .clk(hdmi_tx_slow_clk),.rst_n(vid_rst_n),.frame_period(fifo_rd_period),
 .frame_descriptor(frame_display_descriptor),.compare_mode(compare_mode),.overlay_mode(display_overlay),.gray_mode(display_gray),.edge_mode(display_edge),.in_data(ddr_pixels),.in_valid(ddr_valid),.in_ready(ddr_ready),
 .out_data(m_axis_tdata),.out_valid(m_axis_tvalid),.out_ready(m_axis_tready),
 .out_sof(m_axis_tuser),.out_eol(m_axis_tlast),
 .mixed_words(mixed_words),.completed_frames(display_frames),.source_signature(source_signature));
// Gray-coded diagnostic counters cross back to the debug clock.
reg [31:0] mixed_gray=0,shown_gray=0;
reg [31:0] mixed_s1=0,mixed_s2=0,shown_s1=0,shown_s2=0;
always @(posedge hdmi_tx_slow_clk) begin
 mixed_gray<=mixed_words^(mixed_words>>1);
 shown_gray<=display_frames^(display_frames>>1);
end
always @(posedge i_mipi_rx_pclk) begin
 mixed_s1<=mixed_gray; mixed_s2<=mixed_s1;
 shown_s1<=shown_gray; shown_s2<=shown_s1;
end
wire [31:0] mixed_total,shown_total;
generate for(genvar cb=0;cb<32;cb=cb+1) begin: decode_display_counts
 assign mixed_total[cb]=^(mixed_s2>>cb);
 assign shown_total[cb]=^(shown_s2>>cb);
end endgenerate
// Recover exactly the M02 luminance from unchanged RGB; all views and
// HDMI timing pass through the same one-cycle register.
wire [63:0] display_rgby;
wire hdmi_tx_vs,hdmi_tx_hs,hdmi_tx_de;
reg [7:0] display_edge_byte=0;
reg [6:0] display_meta=0;
always @(posedge hdmi_tx_slow_clk) display_meta<=display_rgb[30:24];
always @(posedge hdmi_tx_slow_clk) display_edge_byte<={8{display_rgb[31]}};
rgb_to_gray display_luma(
 .clk(hdmi_tx_slow_clk),.rst_n(vid_rst_n),
 .in_valid(1'b1),.in_ready(),.in_rgb({32'd0,display_rgb}),
 .in_sof(ch0_vs),.in_eol(ch0_hs),.in_eof(ch0_de),
 .in_frame_id(32'd0),.in_epoch(32'd0),.out_valid(),.out_ready(1'b1),
 .out_rgby(display_rgby),.out_sof(hdmi_tx_vs),.out_eol(hdmi_tx_hs),
 .out_eof(hdmi_tx_de),.out_frame_id(),.out_epoch());
wire [7:0] base_rdata=display_rgby[23:16];
wire [7:0] base_gdata=display_rgby[15:8];
wire [7:0] base_bdata=display_rgby[7:0];
wire [7:0] hdmi_tx_rdata,hdmi_tx_gdata,hdmi_tx_bdata;
wire [10:0] shown_threshold;
wire [2:0] shown_flags;
threshold_osd threshold_overlay(
 .clk(hdmi_tx_slow_clk),.rst_n(vid_rst_n),.vs(hdmi_tx_vs),.de(hdmi_tx_de),
 .ui_status(ui_display_status),.shown_descriptor(frame_shown_descriptor),.shown_toggle(frame_shown_toggle),.metadata(display_meta),.rgb({base_rdata,base_gdata,base_bdata}),
 .out_rgb({hdmi_tx_rdata,hdmi_tx_gdata,hdmi_tx_bdata}),.shown_threshold(shown_threshold),.shown_flags(shown_flags));
// Bundled-data mailbox: the HDMI value is held until the debug domain acks.
reg [10:0] threshold_mailbox=32,threshold_shown=32;
reg [5:0] flags_mailbox=1,flags_shown=1;
reg shown_metadata_seen=0;
reg shown_request=0,shown_ack=0;
reg [1:0] shown_ack_sync=0,shown_request_sync=0;
always @(posedge hdmi_tx_slow_clk) begin
 if(!vid_rst_n) begin shown_metadata_seen<=0;flags_mailbox<=1;threshold_mailbox<=32;shown_request<=0;shown_ack_sync<=0;end
 else begin
  shown_ack_sync<={shown_ack_sync[0],shown_ack};
  if(shown_ack_sync[1]==shown_request && shown_metadata_seen!=frame_shown_toggle) begin
   shown_metadata_seen<=frame_shown_toggle;
   if({flags_mailbox,threshold_mailbox}!={frame_shown_descriptor[104:102],shown_flags,shown_threshold}) begin
   flags_mailbox<={frame_shown_descriptor[104:102],shown_flags};threshold_mailbox<=shown_threshold;shown_request<=!shown_request;
   end
  end
 end
end
reg [10:0] response_target=32;
reg [31:0] response_timer=0,response_cycles=0;
reg response_busy=0;
always @(posedge i_mipi_rx_pclk) begin
 if(!w_arstn) begin
  flags_shown<=1;threshold_shown<=32;shown_ack<=0;shown_request_sync<=0;
  response_target<=32;response_timer<=0;response_cycles<=0;response_busy<=0;
 end else begin
  shown_request_sync<={shown_request_sync[0],shown_request};
  if(shown_request_sync[1]!=shown_ack) begin
   flags_shown<=flags_mailbox;threshold_shown<=threshold_mailbox;shown_ack<=shown_request_sync[1];
  end
  if(response_target!=threshold_pending) begin
   response_target<=threshold_pending;response_timer<=0;response_busy<=1;
  end else if(response_busy) begin
   if(threshold_shown==response_target) begin response_cycles<=response_timer;response_busy<=0;end
   else if(response_timer!=32'hffffffff) response_timer<=response_timer+1'b1;
  end
 end
end
//==============================================================================
// MIPI DSI
//==============================================================================
// signal 

reg		[25:0]	r_rst_cnt;

wire	[31:0]	w_axi_rdata;
wire			w_axi_awready;
wire			w_axi_wready;
wire			w_axi_arready;
wire			w_axi_rvalid;
wire			w_axi_bvalid;

wire	[6:0]	w_axi_awaddr;
wire			w_axi_awvalid;
wire	[31:0]	w_axi_wdata;
wire			w_axi_wvalid;
wire			w_axi_bready;
wire	[6:0]	w_axi_araddr;
wire			w_axi_arvalid;
wire			w_axi_rready;

wire			w_confdone;
assign w_confdone = 1'b1;

assign  LCD_POWER 			= i_arstn;
assign	LCD_RST_P	      = ~w_arstn;//~r_rst_cnt[23]; LCD复位先释放，然后再释放MIPI 的复位
assign	mipi_dp_clk_RST		= ~i_arstn;
assign	mipi_dp_data0_RST	= ~i_arstn;
assign	mipi_dp_data1_RST	= ~i_arstn;
assign	mipi_dp_data2_RST	= ~i_arstn;
assign	mipi_dp_data3_RST	= ~i_arstn;
////////////////////////////////////////////////////////////////
always@(posedge i_mipi_clk or  negedge w_arstn )
begin
  if ( !w_arstn ) begin
    r_rst_cnt	<= 'd0;
  end else 		
    r_rst_cnt	<= r_rst_cnt[25] ? r_rst_cnt :r_rst_cnt + 1'b1;
end

wire axi_rst_n = r_rst_cnt[25];

reg [26:0] dly_cnt = 'd0;

always @( posedge vid_clk_dvi2 or negedge w_arstn )
begin
  if( !w_arstn )
    dly_cnt <= 'd0;
  else if( w_confdone )
    dly_cnt <= dly_cnt[26] ? dly_cnt :(dly_cnt + 1'b1);
  else 
    dly_cnt <= 'd0;
end 

assign vid_rst_n = dly_cnt[26];




wire hs;
wire vs;
wire de;
wire [7:0] rgb_r;
wire [7:0] rgb_g;
wire [7:0] rgb_b;
  
  // color_bar_rgb #(
  // .HS_POLORY 		(1'b1		),
  // .VS_POLORY 		(1'b1		),
  // .H_FRONT_PORCH 	(HFP		),///2
  // .H_SYNC 		(HSP		),//
  // .H_VALID 		(MAX_HRES	),//
  // .H_BACK_PORCH 	(HBP		),//
  // .V_FRONT_PORCH 	(VFP		),
  // .V_SYNC 		(VSP		),
  // .V_VALID 		(MAX_VRES	),
  // .V_BACK_PORCH 	(VBP		),
  // .TEST_MODE 		(2'd2)
  // )u_color_bar_rgb1(
  // /*i*/.clk	(hdmi_tx_slow_clk),//(vid_clk),
  // /*i*/.rst_n	(vid_rst_n),
  // /*o*/.hs	(hs),
  // /*o*/.vs	(vs),
  // /*o*/.de	(de),
  // // /*O*/.h_cnt (h_cnt),
  // // /*O*/.v_cnt (v_cnt),
  // /*o*/.rgb_r	(rgb_r),    //像素数据、红色分量
  // /*o*/.rgb_g	(rgb_g),    //像素数据、绿色分量
  // /*o*/.rgb_b (rgb_b)    //像素数据、蓝色分量
  
  // );

//=================================================================================
//hdmi tx ctrl 
//=================================================================================
wire                            video_hs;
wire                            video_vs;
wire                            video_de;
wire[7:0]                       video_r;
wire[7:0]                       video_g;
wire[7:0]                       video_b;

assign tmds_tx_data0_TX_OE = 1'b1;
assign tmds_tx_data1_TX_OE = 1'b1;
assign tmds_tx_data2_TX_OE = 1'b1;
assign tmds_tx_clk_TX_OE   = 1'b1;

assign tmds_tx_data0_TX_RST = 1'b0;
assign tmds_tx_data1_TX_RST = 1'b0;
assign tmds_tx_data2_TX_RST = 1'b0;
assign tmds_tx_clk_TX_RST   = 1'b0;

// 	  color_bar color_bar_m0(
// 	.clk(hdmi_tx_slow_clk),
// 	.rst(~vid_rst_n),
// 	.hs(video_hs),
// 	.vs(video_vs),
// 	.de(video_de),
// 	.rgb_r(video_r),
// 	.rgb_g(video_g),
// 	.rgb_b(video_b)
// );

wire [9:0] tmds_data0;
wire [9:0] tmds_data1;
wire [9:0] tmds_data2;
wire [9:0] tmds_clk ;
wire [7:0] gamma_rdata ;
wire [7:0] gamma_gdata ;
wire [7:0] gamma_bdata ;
wire gamma_valid;
wire gamma_hs;
wire gamma_vs;
wire gamma_sel;

wire [7:0] con_rdata ;
wire [7:0] con_gdata ;
wire [7:0] con_bdata ;
wire con_de;
wire con_hs;
wire con_vs;
wire con_sel;

wire [7:0] BRIGHT_SIG    ;
wire CONTRAST_SIG_G;
wire CONTRAST_SIG_R;
wire [7:0] CONTRAST_G    ;
wire CONTRAST_SIG_B;
wire [7:0] BRIGHT        ;
wire [7:0] CONTRAST_R    ;


wire CONTRAST_B    ;


gamma_correction
#(
	.DATA_WIDTH		(8),
	.GAMMA_CURVE	("./rtl/gamma_conrrection/2P2.mem")
)
inst_gamma_correction
(
	.i_pclk		(hdmi_tx_slow_clk),
	.i_rstn		(vid_rst_n),
	
	.i_red		(hdmi_tx_rdata),//(con_rdata  ),//
	.i_green	(hdmi_tx_gdata),//(con_gdata  ),//
	.i_blue		(hdmi_tx_bdata),//(con_bdata  ),//
  .i_valid	(hdmi_tx_de   ),//(con_de     ),//
  .i_hs     (hdmi_tx_hs   ),//(con_hs     ),//
  .i_vs     (hdmi_tx_vs   ),//(con_vs     ),//
	.o_blue		(gamma_bdata		),
  .o_green	(gamma_gdata	  ),
	.o_red		(gamma_rdata		),
	.o_valid	(gamma_valid	  ),
  .o_hs     (gamma_hs       ),
  .o_vs     (gamma_vs       )
);

dvi_encoder dvi_encoder_m0
(
	.pixelclk      		(hdmi_tx_slow_clk          ),// system clock
	.rst_p         		(~vid_rst_n      ),// reset
	.i_bdata      		(display_gamma ? gamma_bdata	: hdmi_tx_bdata 	),
	.i_gdata     		  (display_gamma ? gamma_gdata	: hdmi_tx_gdata   ),//(hdmi_tx_gdata ),//(video_g            ),//(gdata_in	),   //   
	.i_rdata       		(display_gamma ? gamma_rdata	: hdmi_tx_rdata 	),
  .i_de            	(display_gamma ? gamma_valid	: hdmi_tx_de      ),//(hdmi_tx_de    ),//(video_de           ),//(rx_de		  ),   //
	.i_hs         		(display_gamma ? gamma_hs	    : hdmi_tx_hs    ),//(video_hs           ),//(rx_hsync	),   //   
	.i_vs         		(display_gamma ? gamma_vs	    : hdmi_tx_vs    ),//(video_vs           ),//(rx_vsync	),   //  
	
  .video_format     (video_format), //// 00 = RGB, 01 = YCbCr 4:2:2, 10 = YCbCr 4:4:4
  .video_VIC        (0),
	.audio_L			    (audio_L),
  .audio_R			    (audio_R),
  .audio_valid		  (audio_valid),
  .audio_N                (6144),     //(20'h01880),//     
  .audio_CTS              (148500),      //(20'h28488),//      
  .audio_sample_frequency (audio_samp_freq),    //(3'b000),// 
  .audio_word_length      ({audio_samp_word_len,audio_max_word_length}),//(4'b1011),//

	.tmds_data0    		(tmds_data0),
  .tmds_data1    		(tmds_data1),
  .tmds_data2    		(tmds_data2),
  .tmds_clk      	  (tmds_clk  )
);
assign tmds_tx_clk_TX_DATA   = ~tmds_clk;
assign tmds_tx_data0_TX_DATA = ~tmds_data0;
assign tmds_tx_data1_TX_DATA = ~tmds_data1;
assign tmds_tx_data2_TX_DATA = ~tmds_data2;

// One capture for a complete CLI report; page reads never modify controls.
wire [1904:0] debug_live;
wire [5:0] debug_page,debug_page_ack;
wire debug_capture,debug_capture_ack;
wire [63:0] debug_page_data;
assign debug_live[0 +: 32]=32'h6010100f;
assign debug_live[32 +: 32]=full_frames;
assign debug_live[64 +: 32]=full_errors;
assign debug_live[96 +: 16]=source_width;
assign debug_live[112 +: 16]=source_height;
assign debug_live[128 +: 16]=mipi_debug_out;
assign debug_live[144 +: 1]=cal_done;
assign debug_live[145 +: 1]=display_underflow;
assign debug_live[146 +: 32]=sum_r;
assign debug_live[178 +: 32]=sum_g;
assign debug_live[210 +: 32]=sum_b;
assign debug_live[242 +: 32]=processed_frames;
assign debug_live[274 +: 32]=last_frame_id;
assign debug_live[306 +: 32]=last_epoch;
assign debug_live[338 +: 32]=config_epoch;
assign debug_live[370 +: 16]=active_r;
assign debug_live[386 +: 16]=active_g;
assign debug_live[402 +: 16]=active_b;
assign debug_live[418 +: 2]=active_phase;
assign debug_live[420 +: 1]=active_gamma_sync[1];
assign debug_live[421 +: 1]=active_gray_sync[1];
assign debug_live[422 +: 32]=mipi_flag_cycles;
assign debug_live[454 +: 32]=underflow_total;
assign debug_live[486 +: 1]=active_edge_sync[1];
assign debug_live[487 +: 11]=threshold_active;
assign debug_live[498 +: 32]=sobel_overrun_cycles;
assign debug_live[530 +: 32]=mixed_total;
assign debug_live[562 +: 32]=shown_total;
assign debug_live[594 +: 64]=debug_write_status;
assign debug_live[658 +: 32]=source_signature;
assign debug_live[690 +: 64]={debug_written_pixel,debug_read_pixel};
assign debug_live[754 +: 64]=debug_bank_addresses;
assign debug_live[818 +: 1]=threshold_ack;
assign debug_live[819 +: 11]=threshold_pending;
assign debug_live[830 +: 11]=threshold_shown;
assign debug_live[841 +: 32]=threshold_epoch;
assign debug_live[873 +: 32]=key_minus_events;
assign debug_live[905 +: 32]=key_plus_events;
assign debug_live[937 +: 2]=threshold_keys;
assign debug_live[939 +: 32]=response_cycles;
assign debug_live[971 +: 1]=response_busy;
assign debug_live[972 +: 1]=median_active;
assign debug_live[973 +: 1]=denoise_active;
assign debug_live[974 +: 1]=flags_shown[0];
assign debug_live[975 +: 1]=flags_shown[1];
assign debug_live[976 +: 32]=median_epoch;
assign debug_live[1008 +: 1]=active_overlay_sync[1];
assign debug_live[1009 +: 1]=flags_shown[2];
assign debug_live[1010 +: 1]=jtag_frame_ack;
assign debug_live[1011 +: 1]=reference_sel;
assign debug_live[1012 +: 32]=shape_shown[31:0];
assign debug_live[1044 +: 32]=shape_shown[63:32];
assign debug_live[1076 +: 32]=frame_status[159:128];
assign debug_live[1108 +: 32]=frame_status[191:160];
assign debug_live[1140 +: 32]=frame_status[223:192];
assign debug_live[1172 +: 32]=frame_status[255:224];
assign debug_live[1204 +: 32]=frame_status[287:256];
assign debug_live[1236 +: 32]=frame_status[319:288];
assign debug_live[1268 +: 32]=frame_result_overflow;
assign debug_live[1300 +: 32]=ui_short_events;
assign debug_live[1332 +: 32]=ui_long_events;
assign debug_live[1364 +: 32]=frame_status[31:0];
assign debug_live[1396 +: 32]=ui_state;
assign debug_live[1428 +: 477]={shape_shown[252:64],algorithm_status[223:96],frame_traffic};
debug_status_snapshot #(.WIDTH(1905)) status_snapshot(
 .clk(i_mipi_rx_pclk),.rst_n(w_arstn),.live(debug_live),
 .capture(debug_capture),.capture_ack(debug_capture_ack),
 .page(debug_page),.page_ack(debug_page_ack),.data(debug_page_data));
debug_edb_top debug_edb_top_inst(
 .bscan_CAPTURE(jtag_inst1_CAPTURE),
 .bscan_DRCK(jtag_inst1_DRCK),
 .bscan_RESET(jtag_inst1_RESET),
 .bscan_RUNTEST(jtag_inst1_RUNTEST),
 .bscan_SEL(jtag_inst1_SEL),
 .bscan_SHIFT(jtag_inst1_SHIFT),
 .bscan_TCK(jtag_inst1_TCK),
 .bscan_TDI(jtag_inst1_TDI),
 .bscan_TMS(jtag_inst1_TMS),
 .bscan_UPDATE(jtag_inst1_UPDATE),
 .bscan_TDO(jtag_inst1_TDO),
 .status_clk(i_mipi_rx_pclk),
 .snapshot_sensor_command(sensor_command),.snapshot_sensor_response(sensor_response_cdc),
 .snapshot_clk(i_mipi_rx_pclk),.snapshot_page(debug_page),.snapshot_capture(debug_capture),
 .snapshot_data(debug_page_data),.snapshot_page_ack(debug_page_ack),.snapshot_capture_ack(debug_capture_ack),
 
 
 .status_ui_apply(ui_apply),.status_algorithm_set(jtag_algorithm),.status_ratio_set(jtag_ratio),
 
 
 .status_frame_command(jtag_frame_command),.status_frame_command_toggle(jtag_frame_toggle),
 .status_reference_sel(jtag_reference),
 
 
 
 
 
 
 
 
 
 
 .status_recognition_set(jtag_recognition),
 .status_build_id(32'h6010100f),
 
 
 
 
 
 
 
 
 
 
 .status_r_gain(r_gain),
 .status_g_gain(g_gain),
 .status_b_gain(b_gain),
 .status_gamma_sel(gamma_sel),
 .status_phase(bayer_phase),
 .status_gray_sel(jtag_gray),.status_edge_sel(jtag_edge),
    
 .status_overlay_sel(jtag_overlay),
 .status_median_set(jtag_median),.status_denoise_set(jtag_denoise),
 
 
 .status_threshold_set(threshold_set),.status_threshold_toggle(threshold_toggle)
);

endmodule
