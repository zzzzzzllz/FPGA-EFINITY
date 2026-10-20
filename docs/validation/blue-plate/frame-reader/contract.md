# Raw 帧读取核契约（主控已批准）

2026-10-18。只在 `tools/blue_plate/frame_reader/` 实现独立核；共享帧控制器、DMA、顶层由主实现接入。主控批准方案并要求补齐下列竞态，按本契约实现和测试。

## 已核实的布局与参考

已读根 README、G1 接口、`frame_store_control.v` 的 held/free 分配、`frame_pair_fifo.v` 的像素次序、`frame_store_dma.v` 的 compact_capture/compact_write/raw_address/raw_rgb 和突发仲裁。一个 raw 槽起点为 `slot*0x300000`，720p RGB24 长度2764800字节。像素顺序为逐行R/G/B；**逻辑流字节偏移 k 在返回拍 `rdata[127-8*(k%16) -: 8]`**，地址取 `base+(k&~15)`。现有写端把较早字节放在高位，因此不能套用低位字节优先假设。

外部源码实际阅读：

- [axi_fifo_rd.v](https://github.com/alexforencich/verilog-axi/blob/master/rtl/axi_fifo_rd.v) 145—244行：地址发出前为返回数据预留整个突发，消耗数据时归还容量。
- [axi_dma_rd.v](https://github.com/alexforencich/verilog-axi/blob/master/rtl/axi_dma_rd.v) 297—369行：根据长度、对齐和4 KiB边界切分读请求；另读其返回移位/FIFO段。
- 已下载的本地 Efinix FIFO 研究副本 `tmp/blue-plate-video-base/research/efx_fifo_wrapper.v` 与 RAM 示例用于核对存储推断。新外部源码经网页成功读取；PowerShell TLS失败、Python直连超时，未声称已下载这两份源码。

选择单在途、整突发缓存：发请求时缓冲为空且容量覆盖最大32拍；完整接收并核验后才解包，消费完本突发后再请求下一突发。参考FIFO_DELAY另有count=0就放行的例外，不能在突发大于FIFO时照搬；本核硬性限制burst拍数≤32=缓冲容量。省掉多在途记账与读写并发FIFO，算法暂停不会影响已发出的R通道。先测真实资源与吞吐，再决定是否有必要并行预取。

## 接口（同一100 MHz时钟域）

所有普通 valid/ready 在上升沿同时为1时传输，等待时字段稳定。高有效同步 `rst` 是**整条识别读通路的协调复位**，不是运行中局部取消。

| 接口 | 字段和约束 |
|---|---|
| `job_valid/job_ready` | `slot[5:0], frame_id/epoch/generation/source_time_ms[31:0]`，一次只持有一个完成raw帧；全部锁存到job结束 |
| `hold_valid/hold_ready`, `hold_granted` | 输出同一job完整身份；`job_ready`与hold握手对齐。外部控制器在该边沿核对完成帧身份并原子增加引用，`hold_granted=1`才成功；拒绝也完成job接收但走HOLD_DENIED结果，不发DDR请求。不可先ready后异步grant |
| `held`, `held_slot` | 表示核当前拥有引用。外部hold表必须在采集空槽选择之前纳入本周期成功grant及现有held，避免同周期再分配 |
| `cmd_valid/cmd_ready` | `full_scan`；ROI为`x[10:0],y[9:0],width[8:0],height[6:0]`。full_scan忽略ROI字段，固定1280×720；ROI要求width1..320,height1..96且不越界；无效命令结束整个job并报告BAD_ROI |
| `pixel_valid/pixel_ready` | `rgb0/rgb1[23:0],keep[1:0],x[10:0],y[9:0],line_last,cmd_last`。rgb0是较早像素；奇数行尾keep=01、rgb1=0，双像素keep=11；坐标属于rgb0，禁止跨行成对 |
| `cmd_done_valid/cmd_done_ready` | 当前命令成功，最后像素已握手且无在途事务；保持帧引用，握手后可接下一ROI/全图命令。失败只走job_done |
| `finish_valid/finish_ready`, `finish_status[3:0]` | 识别作业正常结束/无候选/切分失败/字符拒识等由外部流程给出。只在等待命令时接收，不能把一次ROI读完当整个job完成 |
| `cancel_valid`, `cancel_status[3:0]` | 电平/脉冲均可，持有期间有效；外部超时用此入口。锁存首次取消原因。取消是显式流中止：待消费pixel/cmd_done可撤销，外部丢弃该job局部数据 |
| `config_epoch/config_generation[31:0]` | 与锁存身份不同时自动取消；source_time_ms只保留原值，不能由读完时间更新 |
| `burst_valid/burst_ready`, `burst_addr[31:0],burst_len[7:0]` | 地址16字节对齐、INCR、size=4，len为拍数减1，最多32拍，绝不跨4 KiB。只有一个在途；ready只由外部仲裁器在显示/采集优先满足后给出。无直连AXI或更改共享仲裁 |
| `rsp_valid/rsp_ready`, `rsp_data[127:0],rsp_last,rsp_resp[1:0]` | 对应已接收burst，最早下一拍返回。从突发握手直到正确结束/恢复期间ready持续1，与算法ready无关；正常响应逐拍写完整缓存，错误/取消时丢弃返回但仍接收 |
| `recover_req/recover_ack` | recover_req表示需外部隔离/复位读通路。ack只能在仲裁器已清除本请求/在途事务/全部返回队列且保证旧返回永不再到达后给出；不是“当前rvalid=0”，也不是计时到期。核请求期间ack才有效 |
| `release_valid/release_ready` | 输出锁存的完整身份；确认排空后提出，握手只发生一次，外部在该边沿减引用。等待release期间不能接job，完成输出也不能先于release握手 |
| `job_done_valid/job_done_ready` | 输出完整锁存身份及status；错误或结束时仅一个结果，握手后才回IDLE；grant失败不发release |

状态码建议：0正常，1无候选，2切分失败，3字符拒识，4取消，5超时，6配置变化，7hold拒绝，8非法槽/ROI，9RRESP错误，10拍数/RLAST错误，11恢复完成后的中止。结果保留首次明确失败原因，恢复不会覆盖它。

## 请求与取消竞态

slot仅允许0..40。非法slot接收后报告状态8，不产生hold或DDR请求。合法hold获准但同拍cancel或配置不匹配时，引用仍须锁存并走release。所有身份输出使用共同的`identity[133:0]={slot,frame_id,epoch,generation,source_time_ms}`；hold阶段另用`hold_identity`透传待授予身份，完成与释放期间identity始终稳定。

WAIT_CMD优先级为配置变化、cancel、finish、cmd；finish_valid会屏蔽cmd_ready，两者不能同时握手。`abort_valid/abort_status`是面向消费方的持续中止通知（当前job有效直至job_done被消费）；配置/取消同周期即有效，允许撤回pixel/cmd_done，消费方必须丢弃当前job数据。正常反压不允许撤回valid或改变字段。普通完成进入JOB_DONE后状态冻结，配置代次由消费方根据identity判断；协议异常仍可中止未消费结果。

首次取消若与release握手同拍，保持release_valid，锁存中止原因并直接进入JOB_DONE；未握手时继续保持release_valid/identity。这避免同拍清held又按旧held返回RELEASE的死锁，也保持分配器反压期间普通握手稳定。首次配置/显式取消与总线错误同拍时，状态码采用配置/取消原因，但协议异常仍强制恢复；abort_status与锁存的最终status一致。

迟到的异常总线响应是恢复隔离事件，会同步拉高abort_valid并阻止release/job_done握手；已提出的release在这种协议故障下撤回，完成隔离后再次提出。这一例外用于阻止在确认有旧事务时释放引用，普通取消和配置变化不使用该例外。

即使当前没有在途事务，UNPACK、WAIT_CMD、RELEASE、JOB_DONE和IDLE收到rsp也属于异常，必须丢弃并进入恢复；该拍禁止release/job_done/job握手。晚到数据不能留给下一命令。配置/取消优先于finish/cmd；总线协议异常优先于通常状态推进，但不覆盖已经锁存的首个中止原因。

坐标比较使用12位x+width、11位y+height，地址运算使用32位显式零扩展，覆盖输入字段最大值的溢出测试。固定图像stride为3840字节，用扩位移位加减实现。

已经拉高的burst_valid保持地址/长度不变直到握手，即使此时取消；它属于已提出的旧请求，取消后不再产生后续请求。该旧请求被接受后立即进入丢弃排空。若旧请求始终不被接受，可经recover_req/ack撤销并安全释放。`recover_ack`与新burst接收同周期禁止；外部必须先停止本客户端的请求握手再确认。

正常完成突发要求**收到恰好len+1拍，且仅最后一拍rlast=1**。正确数量且正确last的RRESP错误可排空后释放；早last、末拍无last、多拍和少拍均不能靠拍数或超时证明安全。协议异常进入RECOVER，持续吸收/丢弃旧响应，只有recover_ack能解除。未到最后一拍而一直静默时，外部timeout/cancel触发恢复；不在核内添加未经规格确认的计时器。

每次recover_req出现后，先实际采样到ack=0才使能当前请求的确认；复位前遗留高ack不会生效。ack与rsp_valid或burst握手同拍时不采纳，并重新要求ack回到0后再确认。有效ack拍不允许响应/请求握手；测试明确断言这些条件。外部ack必须表示当前请求的隔离清理完成，不能把先前完成信号保持为高充作新确认。

取消时，若在途事务后续完整且last正确，可自然排空；若未完成，recover_req允许外部协调恢复。恢复确认之前held保持、release和新job均禁止。`rst`清内部状态的前提是外部同步冻结请求、清引用并恢复DDR通道；复位退出后仍停在BOOT_RECOVER等待一次新ack，防止局部复位把旧返回并入新job。运行中软复位必须使用cancel/recover，不允许只拉本核rst而保留外部引用。

## 状态与地址推进

`BOOT_RECOVER → IDLE →（原子hold）→ WAIT_CMD → PLAN_ROW → OFFER → RECEIVE → UNPACK →（下一burst/下一行）→ CMD_DONE → WAIT_CMD`。

`finish/取消/配置变化/错误 → DRAIN（必要时RECOVER）→ RELEASE → JOB_DONE → IDLE`。hold拒绝直接JOB_DONE。

每行从 `base+3*(1280*y+x)`计算逻辑字节范围；总线地址向下对齐16，首拍丢弃前导字节，行尾丢弃多读字节。每个请求长度为“本行剩余覆盖拍数、32拍、当前4 KiB页剩余拍数”的最小值。跨突发保留不足一个RGB/像素对的字节，行末清理并按原图stride3840推进。边界多读仍局限同一raw槽已完成帧的有效总线覆盖范围。

## 验证门槛

独立testbench先按(x,y,frame)生成RGB数组，再按上述真实字节布局建立128位内存oracle；不复用RTL拆包算法生成期望像素。遍历所有16种起始byte相位、48字节周期、奇偶宽、宽1/320、行尾、最后一行、4 KiB边界、全720p及同帧多ROI。断言输出坐标/keep/末标志、握手稳定、整突发容量预留、长算法停顿时RREADY不断、请求边界与引用次数。

故障覆盖hold拒绝、非法命令、RRESP、早/缺/迟last、少拍、取消与请求/响应同周期、输出长停顿取消、代次变化、release停顿、恢复ack延迟、协调复位。恢复之前不释放也不接新任务；恢复后新帧不得见旧像素。最后给出真实map开销、关键输入哈希、运行日志和退出码；不把map或核级正确性当G1识别准确率通过。
