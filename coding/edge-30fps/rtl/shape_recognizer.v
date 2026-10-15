// Connected horizontal runs replace per-pixel neighbor traversal. Geometry still
// checks every component pixel; DDR storage and the shared Canny cache are reused.
module shape_recognizer #(
 parameter W=1280,H=720,MIN_SIZE=64,MAX_SIZE=400,MARGIN=16,
 QUEUE_BASE=32'h0b000000,VISIT_BASE=32'h0b500000,STATE_BASE=32'h0b400000
)(
 input clk,rst_n,start,input [1:0] slot,
 output reg busy,done,ok,output reg [2:0] count,output reg overflow,
 output reg [175:0] boxes,output reg [7:0] kinds,
 output reg [31:0] candidates,cycles,
 output reg mem_valid,mem_write,mem_copy,output reg [31:0] mem_address,
 output reg [127:0] mem_data,input mem_done,mem_error,input [127:0] mem_result
);
 localparam IDLE=0,MEM_WAIT=1,SCAN=2,SCAN_CHECK=3,SEED=4,MARK=5,
 PUSH_READ=6,PUSH_WRITE=7,PUSH_DONE=8,POP=9,POP_USE=10,POINT_STATS=11,
 NEIGHBOR=12,NEIGHBOR_CHECK=13,NEXT_NEIGHBOR=14,COMPLETE=15,
 TRACE_BEGIN=16,TRACE_NEXT=17,TRACE_CHECK=18,TRACE_MOVE=19,TRACE_FINISH=20,
 PASS_BEGIN=21,PASS_READ=22,PASS_POINT=23,PASS_DISTANCE=24,PASS_CROSS=25,
 PASS_RADIAL=26,PASS_NEXT=27,CIRCLE_CHECK=28,RECT_BEGIN=29,RECT_LENGTH=30,
 RECT_ANGLE=31,RECT_ANGLE_SQUARE=32,RECT_ANGLE_TEST=33,RECT_AREA=34,
 RESIDUAL_BEGIN=35,RESIDUAL_CROSS=36,RESIDUAL_SQUARE=37,RESIDUAL_TEST=38,
 RESIDUAL_DOT=39,RESIDUAL_NEXT=40,PUBLISH=41,NEXT_COMPONENT=42,FINISH=43,
 MATH_WAIT=44,MATH_DONE=45,RECT_LENGTH_DONE=46,RECT_AREA_DONE=47,
 RESIDUAL_COMPARE=48,RESIDUAL_PROJECTION=49,RESIDUAL_FAIL=50,CIRCLE_PREPARE=51,CIRCLE_PRODUCTS=52,
 RUN_WORD=53,RUN_MARKED=54,RUN_EXTEND=55,RUN_RIGHT=56,
 NEIGHBOR_READ=57,NEIGHBOR_RESUME=58,ITER_USE=59;
 reg [5:0] state,mem_return,math_return,push_return;
 reg [127:0] word;
 reg [19:0] scan,head,tail,index,pixel;
 reg [10:0] scan_x;reg [9:0] scan_y;
 reg [31:0] point,seed,first,next_point;
 reg [10:0] run_lo,run_hi,visit_x,parent_lo,parent_hi,neighbor_x,neighbor_end;
 reg [9:0] run_y,parent_y,neighbor_y;
 reg [1:0] expansion,neighbor_side;
 reg extend_left;
 reg [10:0] iter_x,iter_end;
 reg [9:0] iter_y;
 reg iter_loaded;
 reg [5:0] iter_return;
 wire [31:0] selected={11'd0,iter_y,iter_x};
 wire [31:0] selected_run=word[index[1:0]*32 +:32];
 wire [31:0] popped_run=word[head[1:0]*32 +:32];
 wire [31:0] run_record={run_y,run_hi,run_lo};
 reg [95:0] queue_prefix;
 reg [31:0] corner[0:3];
 reg [23:0] lengths[0:3];
 reg [10:0] xmin,xmax;
 reg [9:0] ymin,ymax;
 reg [3:0] neighbor;
 reg [2:0] direction;
 reg [13:0] trace_count;
 reg signed [31:0] area2;
 reg [23:0] perimeter;
 reg [23:0] farthest,rmin,rmax;
 reg signed [23:0] cross_min,cross_max;
 reg [1:0] phase,side,kind;
 reg [11:0] cx2,cy2;
 reg [10:0] tolerance;
 reg [31:0] polygon_area;
 reg [23:0] dot_abs,cross_abs;
 reg [47:0] square;
 reg signed [23:0] ma,mb,mc,md;
 reg signed [47:0] m0,m1;
 // The largest consumed sum is squared distance in doubled image coordinates.
 // Full-width products remain available for the circularity/angle comparisons.
 localparam GEOMETRY_BITS=$clog2(4*((W-1)*(W-1)+(H-1)*(H-1))+1)+1;
 wire signed [GEOMETRY_BITS-1:0] sum=$signed(m0[GEOMETRY_BITS-1:0])+$signed(m1[GEOMETRY_BITS-1:0]);
 wire signed [GEOMETRY_BITS-1:0] difference=$signed(m0[GEOMETRY_BITS-1:0])-$signed(m1[GEOMETRY_BITS-1:0]);
 always @(posedge clk) begin m0<=ma*mb;m1<=mc*md;end
 wire [10:0] px=point[10:0],sx=seed[10:0];
 wire [9:0] py=point[20:11],sy=seed[20:11];
 wire [10:0] bw=xmax-xmin;
 wire [9:0] bh=ymax-ymin;
 wire [10:0] short_box=bw<bh ? bw : bh;
 reg signed [12:0] nx,ny;
 reg [2:0] move_direction;
 always @* begin
  move_direction=state==NEIGHBOR ? neighbor[2:0] : direction;
  nx=$signed({2'b0,px});ny=$signed({3'b0,py});
  case(move_direction)
   0:begin nx=nx-1;ny=ny-1;end
   1:ny=ny-1;
   2:begin nx=nx+1;ny=ny-1;end
   3:nx=nx+1;
   4:begin nx=nx+1;ny=ny+1;end
   5:ny=ny+1;
   6:begin nx=nx-1;ny=ny+1;end
   7:nx=nx-1;
  endcase
 end
 wire legal=nx>=0 && nx<W && ny>=0 && ny<H;
 wire [19:0] next_pixel=ny*W+nx;
 reg found;
 reg [5:0] lane;
 integer k;
 always @* begin
  found=0;lane=0;
  for(integer j=63;j>=0;j=j-1)
   if(word[j*2+1] && !word[j*2]) begin found=1;lane=j;end
 end
 function signed [11:0] dx;
  input [31:0] a,b;
  begin dx=$signed({1'b0,a[10:0]})-$signed({1'b0,b[10:0]});end
 endfunction
 function signed [11:0] dy;
  input [31:0] a,b;
  begin dy=$signed({1'b0,a[20:11]})-$signed({1'b0,b[20:11]});end
 endfunction
 task read_word;
  input [31:0] address;input [5:0] following;
  begin mem_address<=address;mem_write<=0;mem_copy<=0;mem_valid<=1;mem_return<=following;state<=MEM_WAIT;end
 endtask
 task write_word;
  input [31:0] address;input [127:0] data;input [5:0] following;
  begin mem_address<=address;mem_data<=data;mem_write<=1;mem_copy<=0;mem_valid<=1;mem_return<=following;state<=MEM_WAIT;end
 endtask
 task calculate;
  input signed [23:0] a,b,c,d;input [5:0] following;
  begin ma<=a;mb<=b;mc<=c;md<=d;math_return<=following;state<=MATH_WAIT;end
 endtask
 reg [127:0] marked,pushed;
 reg [5:0] run_left,run_right,neighbor_lane;
 reg neighbor_found;
 integer r;
 always @* begin
  run_left=0;run_right=63;
  for(r=0;r<64;r=r+1)
   if(r<pixel[5:0] && !(word[r*2+1] && !word[r*2])) run_left=r+1;
  for(r=63;r>=0;r=r-1)
   if(r>pixel[5:0] && !(word[r*2+1] && !word[r*2])) run_right=r-1;
  marked=word;
  for(r=0;r<64;r=r+1)
   marked[r*2]=word[r*2] | (r>=run_left && r<=run_right);
  // Sequential appends preserve the earlier lanes locally; no queue read is
  // needed before writing the new 32-bit run into its DDR word.
  case(tail[1:0])
   0:pushed={96'd0,run_record};
   1:pushed={64'd0,run_record,queue_prefix[31:0]};
   2:pushed={32'd0,run_record,queue_prefix[63:0]};
   3:pushed={run_record,queue_prefix};
  endcase
  neighbor_found=0;neighbor_lane=0;
  for(r=63;r>=0;r=r-1)
   if(r>=neighbor_x[5:0] && {neighbor_x[10:6],6'b0}+r<=neighbor_end && word[r*2+1] && !word[r*2]) begin
    neighbor_found=1;neighbor_lane=r;
   end
 end
 task advance_point;
  input [5:0] following;
  begin
   if(iter_x==iter_end) begin index<=index+1'b1;iter_loaded<=0;end
   else iter_x<=iter_x+1'b1;
   state<=following;
  end
 endtask
 wire [31:0] qa=corner[side],qb=corner[side+2'd1],qc=corner[side+2'd2];
 // Select point pairs before subtraction so all geometry shares four subtractors.
 reg [31:0] ga,gb,gc,gd;
 reg geometry_cross;
 always @* begin
  ga=point;gb=seed;gc=point;gd=seed;geometry_cross=0;
  case(state)
   PASS_POINT:begin
    gb=phase==0 ? seed : corner[0];gd=gb;gc=selected;
    ga=phase==2 ? corner[2] : selected;geometry_cross=phase==2;
   end
   RECT_LENGTH:begin ga=qb;gb=qa;gc=qb;gd=qa;end
   RECT_BEGIN:begin ga=qb;gb=qa;gc=qc;gd=qb;end
   RECT_AREA_DONE:begin ga=corner[2];gb=corner[0];gc=corner[3];gd=corner[1];geometry_cross=1;end
   RESIDUAL_CROSS:begin ga=qb;gb=qa;gc=selected;gd=qa;geometry_cross=1;end
   RESIDUAL_COMPARE:begin ga=point;gb=qa;gc=qb;gd=qa;end
   default:;
  endcase
 end
 wire signed [11:0] gx0=dx(ga,gb),gy0=dy(ga,gb),gx1=dx(gc,gd),gy1=dy(gc,gd);
 task geometry;
  input [5:0] following;
  begin calculate(gx0,geometry_cross ? gy1 : gx1,gy0,geometry_cross ? gx1 : gy1,following);end
 endtask
 reg [55:0] circle_n,circle_d;
 wire [55:0] circle_square={8'd0,m0};
 wire [55:0] circle_left=(circle_n<<4)+(circle_n<<2);
 wire [55:0] circle_low=circle_d<<4;
 wire [55:0] circle_high=(circle_d<<4)+(circle_d<<3)-circle_d;
 wire [55:0] angle_lhs=56'(square)*25;
 wire [55:0] angle_rhs=56'(m0);
 wire [55:0] residual_rhs=56'(m0);
 always @(posedge clk) begin
  if(!rst_n) begin
   state<=IDLE;mem_return<=IDLE;math_return<=IDLE;push_return<=IDLE;
   busy<=0;done<=0;ok<=0;count<=0;overflow<=0;boxes<=0;kinds<=0;candidates<=0;cycles<=0;
   mem_valid<=0;mem_write<=0;mem_copy<=0;mem_address<=0;mem_data<=0;
   word<=0;scan<=0;scan_x<=0;scan_y<=0;circle_n<=0;circle_d<=0;head<=0;tail<=0;index<=0;pixel<=0;point<=0;seed<=0;first<=0;next_point<=0;
   run_lo<=0;run_hi<=0;visit_x<=0;parent_lo<=0;parent_hi<=0;neighbor_x<=0;neighbor_end<=0;
   run_y<=0;parent_y<=0;neighbor_y<=0;expansion<=0;neighbor_side<=0;extend_left<=0;
   iter_x<=0;iter_end<=0;iter_y<=0;iter_loaded<=0;iter_return<=IDLE;
   queue_prefix<=0;
   xmin<=0;xmax<=0;ymin<=0;ymax<=0;neighbor<=0;direction<=0;
   trace_count<=0;area2<=0;perimeter<=0;farthest<=0;rmin<=0;rmax<=0;cross_min<=0;cross_max<=0;
   phase<=0;side<=0;kind<=0;cx2<=0;cy2<=0;tolerance<=0;polygon_area<=0;dot_abs<=0;cross_abs<=0;square<=0;
   ma<=0;mb<=0;mc<=0;md<=0;
   for(k=0;k<4;k=k+1) begin corner[k]<=0;lengths[k]<=0;end
  end else begin
   done<=0;mem_valid<=0;
   if(busy) cycles<=cycles+1'b1;
   case(state)
    IDLE:if(start) begin
     busy<=1;ok<=1;count<=0;overflow<=0;boxes<=0;kinds<=0;candidates<=0;cycles<=0;scan<=0;scan_x<=0;scan_y<=0;
     mem_valid<=1;mem_copy<=1;mem_write<=0;mem_address<=STATE_BASE+{12'd0,slot,18'd0};mem_return<=SCAN;state<=MEM_WAIT;
    end
    MEM_WAIT:if(mem_done) begin
     if(mem_error) begin ok<=0;state<=FINISH;end
     else begin word<=mem_result;state<=mem_return;end
    end
    MATH_WAIT:state<=MATH_DONE;
    MATH_DONE:state<=math_return;
    SCAN:if(scan>=W*H) state<=FINISH;
     else read_word(VISIT_BASE+{14'd0,scan[19:6],4'd0},SCAN_CHECK);
    SCAN_CHECK:if(found) begin
     pixel<=scan+lane;point<={11'd0,scan_y,11'(scan_x+lane)};seed<={11'd0,scan_y,11'(scan_x+lane)};state<=SEED;
    end else begin
     scan<=scan+64;state<=SCAN;
     if(scan_x==W-64) begin scan_x<=0;scan_y<=scan_y+1'b1;end else scan_x<=scan_x+64;
    end
    SEED:begin
     candidates<=candidates+1'b1;head<=0;tail<=0;kind<=0;
     xmin<=px;xmax<=px;ymin<=py;ymax<=py;corner[0]<=point;
     run_lo<=px;run_hi<=px;run_y<=py;visit_x<=px;expansion<=0;
     push_return<=POP;state<=RUN_WORD;
    end
    RUN_WORD:begin
     if({visit_x[10:6],run_left}<run_lo) run_lo<={visit_x[10:6],run_left};
     if({visit_x[10:6],run_right}>run_hi) run_hi<={visit_x[10:6],run_right};
     extend_left<=run_left==0 && visit_x>=64;
     write_word(VISIT_BASE+{14'd0,pixel[19:6],4'd0},marked,RUN_MARKED);
    end
    RUN_MARKED:if(expansion!=2 && extend_left) begin
     expansion<=1;visit_x<={visit_x[10:6],6'b0}-1'b1;
     pixel<=run_y*W+{visit_x[10:6],6'b0}-1'b1;
     read_word(VISIT_BASE+{14'd0,pixel[19:6]-14'd1,4'd0},RUN_EXTEND);
    end else state<=RUN_RIGHT;
    RUN_RIGHT:if(run_hi[5:0]==63 && run_hi<W-1) begin
     expansion<=2;visit_x<=run_hi+1'b1;pixel<=run_y*W+run_hi+1'b1;
     read_word(VISIT_BASE+((run_y*W+run_hi+1)>>6)*16,RUN_EXTEND);
    end else state<=PUSH_READ;
    RUN_EXTEND:if(word[pixel[5:0]*2+1] && !word[pixel[5:0]*2]) state<=RUN_WORD;
     else state<=expansion==1 ? RUN_RIGHT : PUSH_READ;
    PUSH_READ:if(tail>=(W*H+1)/2) begin ok<=0;state<=FINISH;end
     else write_word(QUEUE_BASE+{10'd0,tail[19:2],4'd0},pushed,PUSH_DONE);
    PUSH_DONE:begin
     case(tail[1:0])
      0:queue_prefix[31:0]<=run_record;
      1:queue_prefix[63:32]<=run_record;
      2:queue_prefix[95:64]<=run_record;
      default:;
     endcase
     tail<=tail+1'b1;
     if(run_lo<xmin) xmin<=run_lo;if(run_hi>xmax) xmax<=run_hi;
     if(run_y<ymin) ymin<=run_y;if(run_y>ymax) ymax<=run_y;
     state<=push_return;
    end
    POP:if(head==tail) state<=COMPLETE;
     else read_word(QUEUE_BASE+{10'd0,head[19:2],4'd0},POP_USE);
    POP_USE:begin
     parent_lo<=popped_run[10:0];parent_hi<=popped_run[21:11];parent_y<=popped_run[31:22];
     head<=head+1'b1;neighbor_side<=0;state<=NEIGHBOR;
    end
    NEIGHBOR:if(neighbor_side==2) state<=POP;
     else if(neighbor_side==0 && parent_y==0 || neighbor_side==1 && parent_y==H-1) begin
      neighbor_side<=neighbor_side+1'b1;
     end else begin
      neighbor_y<=neighbor_side==0 ? parent_y-1'b1 : parent_y+1'b1;
      neighbor_x<=parent_lo==0 ? 0 : parent_lo-1'b1;
      neighbor_end<=parent_hi==W-1 ? W-1 : parent_hi+1'b1;
      state<=NEIGHBOR_READ;
     end
    NEIGHBOR_READ:if(neighbor_x>neighbor_end) begin neighbor_side<=neighbor_side+1'b1;state<=NEIGHBOR;end
     else begin
      pixel<=neighbor_y*W+neighbor_x;
      read_word(VISIT_BASE+((neighbor_y*W+neighbor_x)>>6)*16,NEIGHBOR_CHECK);
     end
    NEIGHBOR_CHECK:if(neighbor_found) begin
     pixel<=neighbor_y*W+{neighbor_x[10:6],neighbor_lane};
     visit_x<={neighbor_x[10:6],neighbor_lane};
     run_lo<={neighbor_x[10:6],neighbor_lane};run_hi<={neighbor_x[10:6],neighbor_lane};run_y<=neighbor_y;
     expansion<=0;push_return<=NEIGHBOR_RESUME;state<=RUN_WORD;
    end else begin neighbor_x<={neighbor_x[10:6],6'b0}+11'd64;state<=NEIGHBOR_READ;end
    NEIGHBOR_RESUME:begin neighbor_x<=run_hi+1'b1;state<=NEIGHBOR_READ;end
    PASS_DISTANCE:begin
     if(sum>farthest || sum==farthest && point<corner[phase==0 ? 0 : 2]) begin
      farthest<=sum;corner[phase==0 ? 0 : 2]<=point;
     end
     state<=PASS_NEXT;
    end
    COMPLETE:if(bw<MIN_SIZE || bh<MIN_SIZE || xmin<MARGIN || ymin<MARGIN || xmax>=W-MARGIN || ymax>=H-MARGIN)
     state<=NEXT_COMPONENT;
     else begin
      cx2<=xmin+xmax;cy2<=ymin+ymax;tolerance<=short_box/32<3 ? 3 : short_box/32;
      point<=seed;first<=0;trace_count<=0;area2<=0;perimeter<=0;direction<=0;neighbor<=0;state<=TRACE_NEXT;
     end
    TRACE_NEXT:if(neighbor==8 || trace_count>8192) state<=NEXT_COMPONENT;
     else if(!legal) begin direction<=direction+1'b1;neighbor<=neighbor+1'b1;end
     else begin
      pixel<=next_pixel;next_point<={11'd0,ny[9:0],nx[10:0]};
      read_word(VISIT_BASE+{14'd0,next_pixel[19:6],4'd0},TRACE_CHECK);
     end
    TRACE_CHECK:if(!word[pixel[5:0]*2+1]) begin direction<=direction+1'b1;neighbor<=neighbor+1'b1;state<=TRACE_NEXT;end
     else if(trace_count!=0 && point==seed && next_point==first) state<=TRACE_FINISH;
     else begin
      if(trace_count==0) first<=next_point;
      trace_count<=trace_count+1'b1;
      area2<=area2 + (next_point[20:11]>py ? $signed({1'b0,px}) : next_point[20:11]<py ? -$signed({1'b0,px}) : 0)
                       - (next_point[10:0]>px ? $signed({1'b0,py}) : next_point[10:0]<px ? -$signed({1'b0,py}) : 0);
      perimeter<=perimeter+(next_point[10:0]!=px && next_point[20:11]!=py ? 362 : 256);
      // Backtracking pixel is the clockwise predecessor of the selected neighbor.
      direction<=(direction[0] ? direction+3'd7 : direction+3'd6);
      neighbor<=0;point<=next_point;state<=TRACE_NEXT;
     end
    TRACE_FINISH:if(area2==0 || trace_count>8192) state<=NEXT_COMPONENT;
     else begin
      if(area2<0) area2<=-area2;
      phase<=0;farthest<=0;index<=0;iter_loaded<=0;rmin<=24'hffffff;rmax<=0;state<=PASS_READ;
     end
    PASS_READ:if(index==tail) begin
      index<=0;iter_loaded<=0;farthest<=0;
      if(phase==0) begin phase<=1;state<=PASS_READ;end
      else if(phase==1) begin phase<=2;cross_min<=0;cross_max<=0;state<=PASS_READ;end
      else state<=CIRCLE_PREPARE;
     end else if(iter_loaded) state<=PASS_POINT;
     else begin iter_return<=PASS_POINT;read_word(QUEUE_BASE+{10'd0,index[19:2],4'd0},ITER_USE);end
    ITER_USE:begin
     iter_x<=selected_run[10:0];iter_end<=selected_run[21:11];iter_y<=selected_run[31:22];
     iter_loaded<=1;state<=iter_return;
    end
    PASS_POINT:begin
     point<=selected;
     if(phase!=2) geometry(PASS_DISTANCE);
     else geometry(PASS_CROSS);
    end
    PASS_CROSS:begin
     if(difference>cross_max || difference==cross_max && point<corner[1]) begin cross_max<=difference;corner[1]<=point;end
     if(difference<cross_min || difference==cross_min && point<corner[3]) begin cross_min<=difference;corner[3]<=point;end
     calculate($signed({1'b0,px,1'b0})-$signed({1'b0,cx2}),$signed({1'b0,px,1'b0})-$signed({1'b0,cx2}),
               $signed({1'b0,py,1'b0})-$signed({1'b0,cy2}),$signed({1'b0,py,1'b0})-$signed({1'b0,cy2}),PASS_RADIAL);
    end
    PASS_RADIAL:begin if(sum<rmin) rmin<=sum;if(sum>rmax) rmax<=sum;state<=PASS_NEXT;end
    PASS_NEXT:advance_point(PASS_READ);
    CIRCLE_PREPARE:calculate(perimeter,perimeter,area2[23:0],710,CIRCLE_PRODUCTS);
    CIRCLE_PRODUCTS:begin
     circle_n<={m1[39:0],16'd0};circle_d<=(circle_square<<7)-(circle_square<<4)+circle_square;state<=CIRCLE_CHECK;
    end
    CIRCLE_CHECK:begin
     if(bw<=MAX_SIZE && bh<=MAX_SIZE && bw*10>=bh*9 && bh*10>=bw*9 &&
        rmax*9<=rmin*11 && circle_left>=circle_low && circle_left<=circle_high) begin kind<=1;state<=PUBLISH;end
     else begin side<=0;state<=RECT_LENGTH;end
    end
    RECT_LENGTH:geometry(RECT_LENGTH_DONE);
    RECT_LENGTH_DONE:begin
     lengths[side]<=sum;
     if(sum<MIN_SIZE*MIN_SIZE) state<=NEXT_COMPONENT;
     else if(side==3) begin side<=0;state<=RECT_BEGIN;end
     else begin side<=side+1'b1;state<=RECT_LENGTH;end
    end
    RECT_BEGIN:if(lengths[0]>MAX_SIZE*MAX_SIZE && lengths[1]>MAX_SIZE*MAX_SIZE && lengths[2]>MAX_SIZE*MAX_SIZE && lengths[3]>MAX_SIZE*MAX_SIZE)
     state<=NEXT_COMPONENT;
     else geometry(RECT_ANGLE);
    RECT_ANGLE:begin dot_abs<=sum<0 ? -sum : sum;state<=RECT_ANGLE_SQUARE;end
    RECT_ANGLE_SQUARE:calculate(dot_abs,dot_abs,0,0,RECT_ANGLE_TEST);
    RECT_ANGLE_TEST:begin square<=m0;calculate(lengths[side],lengths[side+2'd1],0,0,RECT_AREA);end
    RECT_AREA:if(angle_lhs>angle_rhs) state<=NEXT_COMPONENT;
     else if(side==3) begin side<=0;state<=RECT_AREA_DONE;end
     else begin side<=side+1'b1;state<=RECT_BEGIN;end
    RECT_AREA_DONE:begin
     // Two diagonal cross products give the quadrilateral's doubled area.
     geometry(RESIDUAL_BEGIN);
    end
    RESIDUAL_BEGIN:begin
     polygon_area<=difference<0 ? -difference : difference;
     index<=0;iter_loaded<=0;side<=0;state<=RESIDUAL_NEXT;
    end
    RESIDUAL_NEXT:if(area2*20<polygon_area*18 || area2*20>polygon_area*23) state<=NEXT_COMPONENT;
     else if(index==tail) begin kind<=2;state<=PUBLISH;end
     else if(iter_loaded) state<=RESIDUAL_CROSS;
     else begin iter_return<=RESIDUAL_CROSS;read_word(QUEUE_BASE+{10'd0,index[19:2],4'd0},ITER_USE);end
    RESIDUAL_CROSS:begin
     point<=selected;
     geometry(RESIDUAL_SQUARE);
    end
    RESIDUAL_SQUARE:begin
     cross_abs<=difference<0 ? -difference : difference;
     state<=RESIDUAL_TEST;
    end
    RESIDUAL_TEST:calculate(cross_abs,cross_abs,tolerance,tolerance,RESIDUAL_DOT);
    RESIDUAL_DOT:begin
     square<=m0;calculate(lengths[side],m1[23:0],0,0,RESIDUAL_COMPARE);
    end
    RESIDUAL_COMPARE:if(square>residual_rhs) state<=RESIDUAL_FAIL;
     else geometry(RESIDUAL_PROJECTION);
    RESIDUAL_PROJECTION:if(sum < -$signed({1'b0,tolerance})*MAX_SIZE || sum > $signed({1'b0,lengths[side]})+$signed({1'b0,tolerance})*MAX_SIZE)
     state<=RESIDUAL_FAIL;
     else begin side<=0;advance_point(RESIDUAL_NEXT);end
    RESIDUAL_FAIL:if(side==3) state<=NEXT_COMPONENT;
     else begin side<=side+1'b1;state<=RESIDUAL_CROSS;end
    PUBLISH:begin
     if(count==4) overflow<=1;
     else begin
      boxes[count*44 +:44]<={1'b0,ymax,xmax,1'b0,ymin,xmin};kinds[count*2 +:2]<=kind;count<=count+1'b1;
     end
     state<=NEXT_COMPONENT;
    end
    NEXT_COMPONENT:state<=SCAN;
    FINISH:begin busy<=0;done<=1;state<=IDLE;end
    default:begin ok<=0;state<=FINISH;end
   endcase
  end
 end
endmodule
