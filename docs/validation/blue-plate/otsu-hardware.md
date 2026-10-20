# 32档 Otsu 与 RGB ROI 采集核

2026-10-18。独立核位于 `tools/blue_plate/otsu/`；没有接入相机顶层、修改冻结 release 或下载硬件。

## 实现依据

精确比较沿用软件参考的32档直方图与最早并列阈值。实际阅读了 PicoRV32 的移位累加乘法路径，副本在 `tmp/blue-plate-normal-g1/geometry-research/picorv32.v`，来源哈希见同目录 `picorv32-source.json`。本实现自己编写100位无符号串行乘法器，不使用浮点、除法或近似分差。

直方图采集前阅读了 [ZipCPU histogram.v](https://github.com/ZipCPU/dspfilters/blob/master/rtl/histogram.v) 的逐地址清零、同步读、加一、写回及同地址转发，并核对其 [RAM读延迟与握手故障记录](https://zipcpu.com/dsp/2020/02/07/bad-histogram.html)。源码通过GitHub API下载至 `tmp/blue-plate-otsu/research/histogram.v`，Git blob `81da7721017aa64333b45768af325a6d92f1905b`，SHA256 `359cd6a31e61c42fa95e0c5c60e1b7a89ee817d226b2d83d6ba39c476f954130`；raw URL下载超时。只借鉴同步RAM设计机制，没有复制该GPL实现。

ROI允许反压，最多30720像素，因此选择完成一次读改写后再处理下一像素，避免流水转发复杂度。直方图统计与输出读地址共用同一RAM端口，32拍清零；两个同档像素也依次累加。

## 精确阈值核 `otsu32.v`

`start_valid/ready`开始；随后32次`hist_valid/ready`传入升序档位、15位计数。结果`result_valid/ready`保持阈值与状态直到消费。忙时不接新任务；同步高有效rst丢弃当前任务。

状态0可用，1空直方图，2总数超过30720，3只有一个非空档。阈值5位，二值化规则为 `gray[7:3] > threshold`。空、越界和常量输入不能按成功结果处理。

对每个有效分割 t，记总数N、总矩M、左数W、左矩S，比较 `(N*S-W*M)^2 / (W*(N-W))`；严格大于才更新，等值保留最早阈值。

| 数值 | 位宽与界限 |
|---|---|
| 原始总数/矩 | 20/24位，覆盖32档全部15位最大计数；先检查总数再缩窄 |
| 合法N、W / M、S | 15 / 20位，N≤30720，M≤952320 |
| N*S、W*M、绝对差 | 35位，单乘积≤29255270400 |
| 平方分子 / 分母 | 70 / 30位 |
| 两个方差的交叉乘积 | 100位，完整精度比较 |

单个共享移位加法器每拍消费乘数一位，最高位处理完即结束。原RTL SHA256 `5c1e759ce254addba170e9fc810f8ec1beed7a74df834aae5ce2f5bb6207ff28`。

## RGB串联核 `roi_otsu32.v`

开始时锁存`pixel_count[15:0]`；0返回空，>30720返回越界。像素接口是`rgb0/rgb1[23:0]`、`keep[1:0]`、`pixel_last`以及valid/ready。RGB顺序为R高字节、G中间、B低字节。灰度为`(77R+150G+29B)>>8`，全16位移位加法，档位直接取加权和[15:11]。

keep只能01或11，01忽略rgb1；允许每个奇数宽行尾使用01。pixel_last仅在整个ROI最后一拍置1，对应frame_reader的cmd_last，不能接line_last。每拍握手核对剩余数量与last；非法keep、提前/缺失last、超额像素返回状态4。传输中途长期缺数据由外部任务超时取消。

abort同步丢弃局部计算，屏蔽所有握手并复位子核；它不负责DDR事务排空或帧引用释放。任务调度器先遵守frame_reader取消契约，禁止旧像素进入下一ROI。正常反压保持输出，结果消费后才接新开始。身份、源时间、ROI坐标由单任务调度器持有，核内不复制一套身份状态。

该核只生成阈值。后续二值像素需要重读同一held帧/相同几何采样区域；不能把后来一帧的像素套用此阈值。

## 验证与资源

运行：

```powershell
D:\Python\python.exe -X utf8 tools/blue_plate/otsu/tests/run_sim.py
D:\Python\python.exe -X utf8 tools/blue_plate/otsu/tests/run_roi_sim.py
D:\Python\python.exe -X utf8 tools/blue_plate/otsu/tests/prepare_synthesis.py --roi
# 在 tmp/blue-plate-otsu/synthesis-roi 执行
D:\Efinity\bin\efx_run.bat roi_otsu32.xml --flow map --output_dir out
```

阈值核174向量加3复位重放，共177任务；独立Fraction有理数参考，包含空、32常量档、最大总数、非法总数、随机及6真实ROI。输入停顿、忙时噪声、结果反压、加载/计算/结果阶段复位均通过，直方图结束后最大4283拍。

RGB串联53案例加非法流/中止重放，共66完成任务、1856档直方图逐项一致；输入167570个像素拍，覆盖6真实ROI、宽1/2/3/31/32/223/224/319/320、同档成对像素、全灰度梯度及随机RGB。测试最长81191拍，含人为输入间隔与9拍输出保持；100MHz假设下0.812ms，不包含DDR等待，也不是整牌帧率。

证据分别为 `tmp/blue-plate-otsu/simulation.json` 和 `tmp/blue-plate-otsu/roi/simulation.json`，含源码/测试哈希。主控另外独立验证1707个阈值任务，并对RGB串联加入131072种颜色，72完成任务、2048档通过；主控证据位于 `tmp/blue-plate-review/otsu/`、`tmp/blue-plate-review/roi-otsu/`。

| Ti60F225I3 / Efinity2026.1 map | RAM10 | DSP | LUT4 | FF |
|---|---:|---:|---:|---:|
| otsu32独立 | 1 | 0 | 1944 | 790 |
| roi_otsu32含子核 | 2 | 0 | 1772 | 834 |

综合报告位于 `tmp/blue-plate-otsu/synthesis/out/otsu32.map.rpt` 与 `synthesis-roi/out/roi_otsu32.map.rpt`。组合后常量传播、映射结构会变化，不可相加估算或把LUT+FF当XLR。时钟约束10ns，尚未PNR验证100MHz。

串联综合网表测试完成20个任务，包含一张完整真实ROI、灰度梯度、随机输入、同档计数、非法流、取消/复位，外部阈值结果全部一致。内部直方图层次已被综合展开，所以此轮不声称逐档观测；逐档证据来自RTL测试。命令为 `run_roi_sim.py --mapped --lut-init-fix`，记录在 `tmp/blue-plate-otsu/roi-mapped/simulation.json`。

网表仿真使用本地复制的Efinity LUT模型，将灵敏度列表always改为always_comb，以便Icarus在零时刻计算常量输入；记录包含原/改模型哈希，安装目录及网表没有修改。此结果属于适配模型下的网表仿真，不是原始厂商模型原样仿真。
