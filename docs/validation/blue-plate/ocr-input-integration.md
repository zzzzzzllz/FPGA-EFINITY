# 彩色几何与Q8输入的独立联调

`tools/blue_plate/ocr_input/rtl/geometry_ocr_input.v`已连接既有frame_reader、COLOR_OUTPUT=1的perspective_quad和ocr_resize_q8，通过8个独立联调任务；不接产品顶层。DDR写入器尚未接入，本次使用带背压、写完成延迟、错误和取消排空的sink模型。

## 实施前依据

已读取 `frame_reader.v` 的取消、DRAIN/RECOVER、hold/release和完成握手，以及 `perspective_quad.v`、`perspective_roi.v` 的结果保持与失败终止。reader在错误时直接发abort，不等待ROI凑够像素；几何失败通过非零result_status通知外层。Q8的source_done只在完整输出后接收，因此外层必须把中途错误转成abort。

外部参考实际读取了[verilog-axis axis_fifo.v](https://github.com/alexforencich/verilog-axis/blob/master/rtl/axis_fifo.v)的写指针提交和坏帧回滚实现（约239—339行，MIT许可证）。它区分临时写入和完整帧提交，坏帧不推进提交指针。本工程借鉴这一发布条件；不复制完整帧FIFO，因为已有DDR临时区域，额外帧RAM会超出当前分配。参考通过原始源码网页读取，本次未下载或引入第三方代码。

## 最小连接方案

独立会话连接层复用现有三个模块。接收任务后锁存原始134bit身份，同时启动几何和Q8；RGB直接握手，不加像素缓存。正常路径等待几何成功、2256组BGR被sink接收、sink写完成，再请求reader正常结束；来源释放和会话成功均必须在写端已静默之后。

读错误、几何错误、sink中途错误或外部取消锁存第一次失败，终止几何与Q8，调用reader取消并要求sink撤销临时有效性、排空所有已发写请求。sink排空确认须在本次请求后先观察低再观察高，避免复用旧确认。读侧继续使用reader的恢复握手。两端排空后释放一次来源并返回失败，结果保持期间不接收下一来源。复位后也先确认读写端静默。

8bit状态码保留故障来源和原模块代码：`00`成功、`1x`为reader状态、`2x`为几何状态、`3x`为Q8状态、`40`为sink异步错误、`50`为外部取消。同一拍多项出错时依次优先外部取消、sink、reader、几何、Q8；第一次记录后保持不变。几何错误先寄存再发abort，避免它的abort门控result_valid形成组合反馈。

外部写入器在`job_valid && job_ready`时建立本任务的临时写入上下文，以identity关联输入；不能仅凭sink_last发布成功。sink_error独立于末尾sink_done握手，允许输入未满时立即报错。sink_cancel_req要求撤销临时有效性并排空已发写请求，确认之前不得发新任务。复位后的BOOT也使用此握手排空；系统复位与任务取消含义不同，单任务终止应使用cancel_valid。

sink模型只验证调用契约，不代表真实DDR仲裁、地址分配或写响应已经完成。连接层没有新增RAM数组，Q8继续使用既有resize分配中的1 RAM；组合后整机资源与时序仍需由整机实现核对。

## 有限验证范围

使用已有按来源SHA固定的sample125/ROI72缓存文件核对一次完整几何→Q8真实输出，没有重新展开4例全几何回归。另用一个完整的合成任务覆盖末输出已接收但末写未完成时失败；其余错误在输入未满时注入，最后接不同来源的正常任务验证恢复。

结果：8个任务通过，8次hold与8次release一一对应。5种中途错误在接收13组BGR、256组几何RGB时发生，写端保留2个未完成请求；另一项退化四角在输入0像素时失败。末写失败项已接收2256组BGR，却因最后写入未完成而拒绝发布。最后的真实任务完成14336组RGB→2256组BGR逐字节比较并成功返回。

测试累计10064周期输出背压、920周期读写排空等待，检查payload保持、身份锁存、旧高电平排空确认、清理期间新任务阻止、释放前两端静默及done背压。状态码依次为19、27、40、50、16、2a、40、00。取消后的真实输入使用新的frame_id/source_time；运行中修改请求头不改变锁存身份。84校准和112heldout未读取。

复现：在项目根执行 `D:/Python/python.exe -X utf8 tools/blue_plate/ocr_input/tests/run_integration.py`。命令、完整日志、各模块及fixture哈希在 `tmp/blue-plate-ocr-input/integration/report.json`。仿真显示总时间20.75274ms包含测试背压、失败与恢复安排，不能作为真实硬件服务时间或TTL依据。

下一项是将sink合同接到真实DDR写入/错误/排空接口，并核对模型输入布局与归一化。模型、TTL和整机资源账本未更改。
