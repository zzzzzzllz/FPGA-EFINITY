# 独立帧读取核验证

2026-10-18。实现文件为`tools/blue_plate/frame_reader/rtl/frame_reader.v`。同一完成raw槽支持多条ROI/全图命令，身份持续到作业完成；每次最多32拍读请求，先完整接收再解包，算法反压不阻塞总线返回。协议与研究依据见[契约](contract.md)，命令见[README](../../../../tools/blue_plate/frame_reader/README.md)。

## 最终版本与真实综合

当前冻结RTL SHA256：`96de672190fa6792f797b2b53e9d11d17d2bdea861569efa3371adb2ab6539b3`。

Efinity 2026.1.132.4.5 / Ti60F225 I3，独立map：**1272 LUT4、573 FF、205 ADD、7 RAM10、0 DSP**。7 RAM10来自32×128位整突发缓冲的端口宽度映射。没有双缓冲、全帧缓存或乘法器。map使用真实任务、控制、数据端口；未做本核PNR，不能报告XLR或布线后100MHz通过。

| 输入/输出 | SHA256 |
|---|---|
| 综合RTL | `96de672190fa6792f797b2b53e9d11d17d2bdea861569efa3371adb2ab6539b3` |
| SDC | `3706f2f5fe329dc9354939bd1b8df11913846c146f2f75b66d5831ccc601c38f` |
| 工具前XML | `29dfb23da3ec4c125387d2d5ac58f667c0c22fc38ad2bef3af59ccc169c21c92` |
| 工具后XML | `3bbb8b3fce46601d4ec1519fc4e7a72cec566ea8a9e17327f775f395ee690470` |
| map报告 | `fffa9f6a13cc15307b59fd20ba6b6f1771a329f1dfb5a82977aaf14420574140` |
| map网表 | `2546d92099a459384a3346f74cf46dde290b944224589b34030836e53b6e5113` |

工具前XML和输入清单在启动map前已直接复制保存。工具后XML是Efinity ElementTree格式回写，逐节点语义相同；RTL/SDC未变。证据目录为`tmp/blue-plate-frame-reader/synthesis/`。

## 仿真

**最终完整回归PASS，编译/运行均退出0**，目录`tmp/blue-plate-frame-reader/final-v3/`，exec session10864。最终RTL、仿真快照和map源码SHA一致；TB SHA为`87261a126b5ae045c3e1797dbd847e94689b8987b3a910427a824a2c12921654`，也与编译前快照一致。完整命令、退出码和输入/二进制哈希见[执行清单](evidence/final-execution.json)，逐项结果见[运行日志](evidence/final-run.log)。

实测完成33个job、522条读取命令、1,042,260个正确像素、7,380个burst。32次hold对应31次release握手和1次协调复位清引用，最终引用为0。完整720p命令单独核验921,600像素，用3,872,104拍；在100MHz假设下约38.72104ms，包含本测试的仲裁/R通道气泡及像素反压。这不是物理DDR带宽或布局布线时序测试，也不支持逐帧30fps全图扫描的宣称。

最终RTL的快速协议回归`quick-v3b`已通过、退出0：33个完成job，32次hold、31次release、1次协调复位清引用；5条完成读取命令、1722个逐项正确像素、33个burst。协调复位清引用单独计数，没有冒充release握手。

完整用例在此基础上将首条小ROI替换为518条固定读取：全部16种首字节相位、48字节打包周期、奇偶宽、1/320宽、最大ROI、最后像素、跨行、4 KiB边界和完整720p。内存由Python按坐标生成RGB字节流，testbench按坐标独立计算期望RGB，不复用RTL拆包实现。两张不同图案检查旧数据隔离。当前参考内存、命令列表哈希记录在`oracle.json`。

协议回归覆盖：非法槽、hold拒绝、grant与cancel/配置不匹配同拍、显式扩位坐标溢出、无效尺寸、finish/cmd/cancel优先级、长像素反压、RRESP错误、早/缺last、少拍、offer取消、ack与request/response同拍、旧ack、迟到额外响应、配置变化、协调复位后恢复。WAIT_CMD/UNPACK/RELEASE/DONE/IDLE均检查无在途时异常返回的隔离。

主控先独立复现release同拍取消死锁，首次门控修复又被发现会撤回反压中的release_valid；最终实现保持valid/identity，将实际release握手优先归入DONE，同时保留取消状态。自身长期测试与主控`tmp/blue-plate-review/frame-reader-release-final/review-result.json`均覆盖显式取消/配置变化 × 无反压/先反压四例。主控认可该局部修复。

早期`tmp/blue-plate-frame-reader/final/`测试针对`b8c6c035...`版RTL，虽然完整像素与当时故障用例通过，**不是最终96de6721版本证据**。最初根目录`execution.json`对应88900e39版，`race-v2`对应中间门控版，同样只保留为过程记录。

## 接入条件

主实现须提供完成帧身份核验和原子引用、显示/采集优先的burst仲裁，以及真实清空旧事务/返回队列后的recover_ack。ack不是当前总线空闲采样；缺拍不允许靠超时直接释放。迟到协议异常会明确通知abort并进入隔离；普通cancel/config不撤回release握手。

核内按字节复用解包逻辑；单任务忙时应按G1契约跳过新识别任务，不反压相机。共享顶层、DDR、分类和显示目录、release均未改动；本结果不等于G1识别准确率或板上七位识别通过。

可交接证据：[汇总和哈希](evidence/handoff.json)、[map报告](evidence/frame_reader.map.rpt)、[综合输入审计](evidence/synthesis-summary.json)、[工具前XML](evidence/frame_reader.before.xml)、[工具后XML](evidence/frame_reader.after.xml)、[参考向量清单](evidence/oracle.json)。原研究/模板文件的版权头未移除，没有复制第三方RTL到实现中。
