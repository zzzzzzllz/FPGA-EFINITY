# 冻结 Q8 OCR 输入接口

独立模块 `tools/blue_plate/ocr_input/rtl/ocr_resize_q8.v` 已实现固定224×64 RGB流缩至24×94 BGR uint8，遵守 `char_segment/experiment.py` 的 `axis_lut/resize_q8` 和 `fixed_lprnet.py` 合同。307个冻结dev ROI的2,077,776字节与独立整数参考及原冻结函数完全相同。模型、权重和输入尺度不变，颜色96×96路径另行接入。

## 实施前核对与最小缓存

已实际读取[OpenCV 4.12.0 resize.cpp](https://github.com/opencv/opencv/blob/4.12.0/modules/imgproc/src/resize.cpp)的半像素坐标、边界处理及分离水平/垂直插值实现。借鉴分离插值的行缓存机制；具体精度使用项目冻结Q8，不拿cv2默认输出近似替代。Q8轴坐标取半像素位置并钳边，分数乘256后半入，256进位到下一整数坐标。最终四邻居加权和加32768再右移16位，水平阶段不舍入。

固定224→94、64→24的相邻目标采样对不重叠，输入按行到达时，仅需保存上方源行的94×3个uint16水平和，等下方源行到达后完成垂直插值。最大水平和65280，282×16bit装入一个512×16 RAM10；两枚RGB像素寄存器保存当前左右邻居，无完整输入/输出帧缓存。固定轴表用逻辑case，乘法用共享的8步移位加法。

初次map将X轴case自动推成第二个RAM。依据[Efinity综合手册syn_romstyle](https://www.efinixinc.com/docs/efinity-synthesis-v4.4.pdf)及本机 `D:/Efinity/doc/topics/syn-attr-romstyle.html`，在轴信号上明确设置 `syn_romstyle="logic"`；相同常量和算术下最终map为520 LUT4、339 FF、96 ADD、1 RAM10、0 DSP。调整前424 LUT4、339 FF、96 ADD、2 RAM10的报告与源码保存在 `tmp/blue-plate-ocr-input/synthesis-before-rom-fix/`。此处是Ti60F225 I3、Efinity2026.1独立map，10ns约束不等于已通过100MHz PNR。

RAM归属：这是 `whole-plate-budget/full-lprnet-sharing.md` 中51 RAM引擎的“resize目标1 RAM”，不再加到196/204账本，也不占几何已有2 RAM。6768字节输出应由既有256KiB DDR特征槽和既有4KiB写块分批接收，本模块不拥有额外整图缓存。物理DDR地址仍由主控冻结。本次map符合1 RAM分配，不消耗剩余8 RAM；196/204仍是整机容量账本，不是整机实现结果。

## 接收与发布合同

一次start锁存134bit来源身份；输入必须是地址0…14335连续、末标志仅在14335的RGB流。输入word高字节R、中字节G、低字节B；输出按目标行优先，每拍一组BGR uint8及像素地址0…2255，输出word高字节B、中字节G、低字节R。外部写内存按高到低取字节得到HWC BGR。若模型存储使用CHW，消费者按`c×2256+pixel_address`写对应字节，数值不变。归一化仍由冻结模型输入处理执行，不能把uint8直接解释为signed int8。

输入、输出均支持ready背压。输出像素先写入当前任务的临时区域，不能见到last就启动模型。上游成功完成且接收端确认全部写入完成后，才保持成功done状态，允许发布有效输入；完成状态也支持背压。abort/rst撤销部分输出及成功状态，调用者须同步使临时区域失效并排空旧事务，再启动新身份。来源身份在任务期间保持锁存值，输入和完成接口不允许跨任务混用。

`source_done_ready`仅在全部2256个输出被接收后拉高；source成功后才接受sink完成。如果上游在输入未满时失败，调用者须用abort终止，不能等待末尾完成握手。`done_status`分别为0成功、1地址/last错误、2上游失败、3接收端失败、4非法状态；只有0允许模型使用这次输入。中途停止提供像素不会自动超时，任务期限和总线排空由调度者负责。

## 验证与复现

`tests/run_sim.py`核对307个development记录、每个ROI内容哈希、冻结输入文件哈希及全部118个轴表常量。实际RTL按`source_sha256, roi_index`排序取前4例：sample125/88/423/100（ROI72/48/263/55），加一组通道不同的极值/斜坡图案。合成图案包含784个加权结果恰为半整数的通道值，覆盖最终half-up舍入。

RTL共12次运行、19个任务通过。每个正常任务输入14336组RGB、输出2256组BGR，输出背压检查12397周期；测试还覆盖地址错误、提前last、上游失败、写入失败、中途abort、末像素阻塞时abort、复位后新身份恢复及done保持。完整输入输出在source/sink确认前均为临时数据。84校准和112heldout未读取。

```powershell
D:/Python/python.exe -X utf8 tools/blue_plate/ocr_input/tests/run_sim.py
D:/Python/python.exe tools/blue_plate/ocr_input/tests/prepare_synthesis.py
# 在 tmp/blue-plate-ocr-input/synthesis 中执行
& D:/Efinity/bin/efx_run.bat ocr_resize_q8.xml --flow map --output_dir out
# 回到项目根目录后执行
D:/Python/python.exe -X utf8 tools/blue_plate/ocr_input/tests/run_sim.py --mapped --lut-init-fix
```

原始厂商LUT模型在Icarus下的零时刻初始化失败记录为 `tmp/blue-plate-ocr-input/mapped-vendor-init-failure.log`。`--lut-init-fix`复用既有Otsu网表测试方法：只对临时副本将LUT灵敏度列表always换成always_comb；原模型及适配后哈希写入报告，厂商安装和综合网表均不改。网表结果须按这一适配条件解读。

适配模型下，4个真实case和1个合成case的综合网表全部通过，共11280组输出像素、61985周期背压核对。批次完成前三例后，为检查第四例的仿真耗时，最后两例使用同一网表和仅增加一行时钟/像素进度输出的bench继续执行；脚本逐字确认其余断言未变。前3例没有重跑，最后2例也都以2256像素和12397背压检查成功结束。明细、原始日志路径及续跑说明在 `tmp/blue-plate-ocr-input/mapped-report.json`，汇总在 `delivery.json`。

与真实frame_reader、彩色几何模块的[独立联调](ocr-input-integration.md)已通过8个任务，覆盖中途失败转abort、读写排空及不同来源恢复；sink仍为测试模型。本模块的逐像素与协议验证不代替真实DDR写入器和模型输入布局/归一化的实际连接，整链来源年龄和TTL须实测后决定。
