# Q8 OCR输入的独立DDR写入器

`tools/blue_plate/ocr_writer/rtl/ocr_hwc_writer.v`已完成2256组BGR uint8→紧密HWC int8写入器，20项独立RTL/AXI模型测试通过。实际map增量为506 LUT4、355 FF、14 ADD、0 RAM、0 DSP。已交付geometry/ocr_input源码保持冻结。物理地址保持符号化，不接产品顶层、不接板、不实现共享DDR仲裁或颜色路径。

## 实施前研究

已读取实际 `coding/edge-quality-30fps/rtl/frame_store_dma.v` 的写状态机：AW接受后发送W，最后一拍后等待B；只有B返回才更新完成状态，非零BRESP记为错误。顶层 `ti60f225_oob_top.v` 约654—660行将这些信号接到DDR3 AXI端口，AWID=0、AWSIZE=4、AWBURST=INCR、AWCACHE=3。`ddr3_parameter.vh` 定义32bit地址、128bit数据、4bit ID。`ddr3_top.v` 和 `axi4_bus_ctl.v` 的公开端口确实包含BVALID/BREADY/BRESP/BID，B响应不是测试模型新增的接口。

`axi4_bus_ctl.v` 内部为加密实现，未读取其内部完成逻辑。本阶段保证公开AXI事务层面的全部响应已接收及已报告错误处理；不把B响应解释为DRAM内部物理写入时刻。实际控制器的写后读次序及错误覆盖仍需使用厂商模型或后续板级验证。

外部实际读取[verilog-axi axi_dma_wr.v](https://github.com/alexforencich/verilog-axi/blob/master/rtl/axi_dma_wr.v)约428—447行的4KiB切分、647—674行的已发burst收尾、695—722行的B完成/错误归属。该MIT实现会以空WSTRB补齐已发长burst，再等待响应；本次固定单拍且数据已完整缓存，取消时直接完成原数据拍，不需要填充或完整帧FIFO。参考源码通过原始文件网页读取，未下载或复制第三方实现。

## 冻结接口合同

- 2256组输入按像素地址0…2255顺序提供，last只允许在2255；word高字节B、中G、低R。每字节变换为`uint8 ^ 8'h80`，等价于`int8(uint8−128)`。
- 设备内存采用部署manifest规定的紧密HWC：`feature_region_base + feature_slot*262144 + (h*94+w)*3+c`，c依次B/G/R，输入offset固定0。每行282字节，不加行填充，不转CHW。软件golden中的NCHW容器与硬件HWC布局需区分。
- 低地址字节放在AXI WDATA低位：地址`A+j`对应`WDATA[8*j+:8]`。本特征区域合同不改变原始摄像头帧的高字节优先容器。
- base必须16字节对齐，两个256KiB槽的整个区域必须落在32bit地址空间内，slot只允许0或1。符号基址由调用方提供；测试地址不是物理地址分配。每次恰写6768字节，共423个完整16B拍，WSTRB始终FFFF；单拍不会跨4KiB边界。
- 同时仅一笔写事务，AWID=0、AWLEN=0、AWSIZE=4、AWBURST=1；接入时AWCACHE/PROT沿用实际接口常量3/2。AW与W分别记录是否接受，允许地址先到、数据先到或同拍接受。只有AWVALID&&AWREADY接收地址，WVALID&&WREADY接收数据；W握手不等于完成。等相应BVALID&&BREADY且BID=0、BRESP=OKAY后，该拍才完成。最后一拍B完成且输入计数正确后才保持成功done。
- 一枚128bit打包寄存器和一枚24bit像素寄存器跨pixel保留剩余字节，不占新的图像RAM，也不另建4KiB写块。这是低并发的最小路径；仅在实际服务时间证明需要时，才使用既有IO/写块做burst优化。
- cancel请求保持到cancel_ack；停止接新像素，丢弃未发出的半拍。已拉高的AWVALID/WVALID必须保持到握手，已经发出的完整单拍必须等B完成，随后才确认取消。部分内存写入不能撤销，调用方必须使该任务的整个临时区域失效。
- 134bit身份在start握手锁存。运行时epoch/generation变化立即使任务失败，旧事务完成或取消排空前不允许接新身份；原始时间不改写。
- 没有未完成写时出现B、W完成前出现B、BID不匹配都属于协议故障。停止新任务并要求控制器与写入器共同复位；不能仅因观察到短暂空闲就把后来的旧B归属给新任务。已经承诺的AW/W仍保持并收尾，故障通道不发布成功或取消完成。复位必须与实际控制器隔离一起执行，不能单独清零写入器来假装排空。

本接口要求独占这笔事务的AW/W/B归属。未来共享仲裁必须将B交还原写请求者，不能把camera/frame_store_dma的B直接广播成OCR完成。AXI B没有epoch字段；对于违反协议且恰好落入新事务响应窗口的同ID重复B，仅靠该接口无法区分。本实现以单笔未完成、完整排空、共享复位隔离保证合法旧事务不进入新窗口，未声称能识别任意伪造响应。

状态码：0成功，1地址范围/对齐/slot/初始配置错误，2像素地址或last错误，3取消，4运行中配置变化，5非零BRESP，6响应归属/时序错误，7非法状态。`error`及时通知上游撤销临时输入；`isolation_required`表示普通取消已不足以恢复归属。`done_valid/done_ready`保持最终状态，`cancel_req/cancel_ack`单独处理排空，不能用done消费替代取消确认。enabled仅控制新任务进入，不撤销正在进行的总线握手。

## 验证范围

按来源SHA排序选取既有development sample125/ROI72，直接使用冻结Q8输出；独立以int16减128、转int8形成6768字节HWC参考。两个不同身份/feature slot的正常任务逐字节通过，各恰好423 AW、423 W、423 B，头尾保护区未变。起点故意位于4KiB页末的16B地址，覆盖跨页及每行282字节无填充。

20项测试依次覆盖：正常写入；半拍取消；AW被阻塞而W已接受时取消；W被阻塞而AW已接受时取消；普通B等待时取消；第423笔B等待时取消；SLVERR；DECERR；错像素地址；提前last；缺末last；基址未对齐；非法slot；32bit区域溢出；区域恰好到4GiB的合法边界；空闲旧B；错误BID；AW/W未接受时提前B；epoch改变后排空；新epoch/slot的正常写入。早B/旧B/BID错误是明确的协议违规注入，恢复时共同复位模型队列和写入器。

总计24次AW先接受、23次W先接受、1655次同拍接受，73周期AW背压、90周期W背压。VALID在取消期间持续保持，载荷稳定；每个取消确认都检查AW/W/B计数相等，完整末写取消仍收到423个B才确认，且没有成功done。配置变化保留状态4，完成旧写后才允许新身份。84校准和112heldout未读取。

总线模型确实使用实际存在的BVALID/BREADY/BRESP/BID，但不是加密DDR控制器仿真。模型中的延迟与错误注入用于检验主机合同，不能据此宣布DDR/板卡验收。

## 资源与复现

Ti60F225 I3 / Efinity2026.1独立map：506 LUT4、355 FF、14 ADD、0 RAM、0 DSP。既有7 RAM IO/写块分配未增加，也没有拿剩余8 RAM兜底；本模块的寄存器与逻辑是明确的新增量，不声称整机XLR已容纳。10ns约束仅用于map，尚未PNR验证100MHz。

```powershell
D:/Python/python.exe -X utf8 tools/blue_plate/ocr_writer/tests/run_sim.py
D:/Python/python.exe tools/blue_plate/ocr_writer/tests/prepare_synthesis.py
# 在 tmp/blue-plate-ocr-writer/synthesis 中执行
& D:/Efinity/bin/efx_run.bat ocr_hwc_writer.xml --flow map --output_dir out
```

验证记录在 `tmp/blue-plate-ocr-writer/report.json`，源码冻结前后检查在 `frozen-input-sources.json`，综合报告在 `synthesis/out/ocr_hwc_writer.map.rpt`。本次只新增本说明，没有改旧输入源码、README或产品工程。

接入前仍需分配物理基址、实现共享写通道归属及复位隔离，随后连接已冻结的geometry_ocr_input并检查实际控制器写后读路径。颜色CNN的native crop→96路径不在本次范围。
