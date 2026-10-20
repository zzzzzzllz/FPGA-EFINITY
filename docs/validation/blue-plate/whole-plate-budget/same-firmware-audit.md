# 同一固件保留边缘演示与 OCR：资源审计

2026-10-19。当前路线保留完整边缘演示、OCR 和通用几何/输入写入模块；检测 CNN、颜色 CNN、HS 过滤退出本轮实现。旧三模型账本保留为历史。此次只读报告与源码，没有新综合、模型评测或板卡操作。

**直接拼接已有模块不能满足 204 RAM 的预算。** 完整 release 为 **49,156 XLR / 188 RAM / 111 physical DSP**，预算余量 **92 / 16 / 17**。原样增加 OCR 核心即需 206 RAM；已有输入、核心和号码显示一起加入则需 **232 RAM，缺 28 块**。采用完整 OCR 的既有 51-bank 分配计划需 **264 RAM，缺 60 块**。后二者尚不含新定位器和整链控制逻辑。需要真正实现存储/算术复用后重新映射，不能把删除未接入的 CNN 当作资源回收。

进一步收敛见[字库与共享边界](font-and-sharing-followup.md)：字库131,072种静态输入等价通过，提出9 RAM独立候选；Canny/shape/OCR所有权及串行/并行限制单独列出。候选尚未map，未扣减本报告资源。

## 1. 当前 release 的证据链

- manifest：`coding/edge-quality-30fps/release/manifest.json`，build ID `0x60101704`，revision `task8-keys-20261017`。
- release 位流与 `tmp/build/task8-keys-20261017-v5/outflow/ti60f225_oob.bit` 的 SHA256 相同：`6e8c40886106793b78ef0dea46ee7b77d266fddbf51ae1cf33b15cfc318709df`。
- 实际资源来自该 v5 目录的 `ti60f225_oob.place.rpt`；模块分布来自 `ti60f225_oob.hier_util.rpt`。map 为 LUT4 31,592、FF 22,725、ADD 4,304、SRL8 1,558、187 RAM10 + 1 DPRAM10、92 DSP48 + 18 DSP24 + 1 DSP12。
- v5 时序报告最小 setup/hold slack 为 0.424/0.026 ns。这是已发布边缘工程的证据，不是 OCR 集成时序。
- 通用目录 `tmp/build/edge-quality-30fps/outflow/` 的位流 SHA 为 `43d80412f7d706f9864f9583d24723f2e8a65e01d9e339de8d8c85999d0ce1e1`，与 release 不同，不能用它代表当前固件。
- live 实验保存的 237 个原工程文件 SHA 与当前原工程全部相同，支持下面全工程差值的来源对照。

完整路径和哈希见 [release 对照](same-firmware-release-evidence.json)，可复算数据见 [审计 JSON](same-firmware-audit.json)。预算固定为 **49,248 XLR / 204 RAM / 128 DSP / 私有 8 MiB DDR arena**，没有改用器件物理上限。

## 2. 从 live 底座恢复完整功能的真实代价

| 已有实际构建 | XLR | RAM | physical DSP |
|---|---:|---:|---:|
| 完整 release v5 | 49,156 | 188 | 111 |
| gates：关闭 Canny/shape | 34,833 | 154 | 92 |
| live：彩色直通、删减 UI/算法/历史控制 | 24,090 | 106 | 85 |
| 完整 − gates | 14,323 | 34 | 19 |
| gates − live | 10,743 | 48 | 7 |
| 完整 − live | **25,066** | **82** | **26** |

这些是成对完整构建的实际差值，含常量传播、控制裁剪和重新打包。不能把它们当独立模块的可加成本。live 的四处改动见 `../video-base/evidence/live-candidate.diff`：顶层固定彩色和禁用功能；算法流水替换为 RGB passthrough；OSD 只留描述符接收/显示确认；XML 改用裁剪源文件。原工程没被改写。

下表为完整构建的层次分配估计，用于定位资源。父子项不能重复相加；分数 XLR 是工具的归属分摊。

| 完整固件中的实例 | XLR | RAM | DSP | 保留/复用判断 |
|---|---:|---:|---:|---|
| algorithm_pipeline 总计 | 4,710 | 46 | 4 | 五级窗口仍需保留 |
| └ median | 1,927.5 | 9 | 0 | 旧演示的中值功能 |
| └ gaussian | 784 | 9 | 0 | 旧演示平滑功能 |
| └ gradient_stage | 937 | 9 | 4 | 可给定位器取现成梯度 |
| └ nms_stage | 688 | 12 | 0 | Canny NMS 所需 |
| └ cleanup_stage | 282 | 7 | 0 | 旧结果清理 |
| checker0 总计 | 22,512.5 | 62 | 31 | 含下列引擎/FIFO/管理器 |
| └ canny.engine | 2,323 | 34 | 0 | 已有共享缓存端口 |
| └ shapes.engine | 8,151 | 0 | 19 | 有算术复用潜力，未等价映射 |
| └ capture / algorithm / display / result FIFO | 328 / 212 / 212 / 273 | 各 7 | 0 | capture/display 工作期间不可借用 |
| gray_pipeline | 66.5 | 0 | 0 | 无灰度帧 RAM 可回收 |
| threshold_overlay | 1,784 | 1 | 0 | 旧菜单资源；与新号码字库不同 |
| display_compositor | 994 | 6 | 6 | live 也保留 6 RAM/6 DSP |
| full_view | 916.5 | 15 | 70 | 摄像头解码/ISP，持续使用 |
| u_ddr3_top | 5,963 | 39 | 0 | DDR 必需资源 |
| CSI / HDMI encoder / cvo_axi | 3,342.5 / 1,448 / 346 | 11 / 2 / 4 | 0 | 持续视频链路 |

按所有层次列出的 full/gates/live 和差值见 [restoration.csv](same-firmware-restoration.csv)。CSV 的 depth=1 加顶层 self 等于全工程资源，脚本已检查；不要跨 depth 求和。

## 3. OCR 新增项及不能虚减的项目

| 现有独立 map | LUT4 | FF | ADD | RAM | DSP |
|---|---:|---:|---:|---:|---:|
| frame_reader | 1,272 | 573 | 205 | 7 | 0 |
| perspective_quad COLOR_OUTPUT=1 | 9,687 | 4,730 | 4,300 | 2 | 1 |
| ocr_resize_q8 | 520 | 339 | 96 | 1 | 0 |
| ocr_hwc_writer | 506 | 355 | 14 | 0 | 0 |
| 已冻结 scalar-read OCR 核心 | 2,300 | 595 | 456 | 18 | 8 |
| plate_display | 2,740 | 4,085 | 400 | 16 | 3 |

每份原始 map 路径和 SHA 收录在 JSON。所有 LUT/FF 保持原始列，**没有转换成新整机 XLR 预测**；完整固件只剩 92 XLR，最终打包、接口复用及控制开销尚未知。

| 原样添加的范围 | 总 RAM | 超出 204 | 已映射总 DSP |
|---|---:|---:|---:|
| 完整固件 + 核心 | 206 | 2 | 119 |
| + reader/geometry/resize/writer/core | 216 | 12 | 120 |
| + 上述全部和 plate_display | 232 | 28 | 123 |
| 改用完整 OCR 51-bank 计划，保留 reader/geometry/display | 264 | 60 | 完整值未知 |

这给出的是**不改现有模块、独立存储相加**的缺口，并非证明所有共享设计都无法容纳。51-bank 计划替换 core 的 18 RAM 和 resize 的 1 RAM，不能再重复相加；剩下 32 块是参数、IO、上下文/height/logits/CTC/control 等既有分配，不会因为去掉检测 CNN 自动消失。

- 旧计划的外部 224×64 灰度缓存 14 RAM 从未在当前 release 中存在。`geometry_ocr_input.v` 中 gray_write/address/data 没有接存储数组，RGB 直接流入 resize。新计划不需要再加入这 14 块，也不能从 188 中减去它们。
- OCR 不需要字符切分与 Otsu。现有 geometry 仍包含 Otsu/直方图，完成信号与阈值阶段耦合；其 2 RAM 是当前实际 map，拆开之后节省多少需另行验证。移除它只缩小新模块，不释放 release 内资源。
- plate_display 的 16 RAM 全属字库；OSD 单独 map 也为 16 RAM。完整确认/CDC另用 3 DSP。原菜单的 1 RAM、已有 display_compositor 的 6 RAM 都已计入 188，不能抵扣一遍再说号码显示免费。
- 检测/颜色 CNN 没有独立硬件实例在 release 中，当前实际可回收量为 0。退出路线节省的是后续模型存储、计算和访存需求。
- 新边缘定位器、OCR 非卷积运算与整链调度的资源仍为 **unknown**，不是 0。

## 4. 保留功能的最小复用方向

按接口距离和现有证据排序，优先验证以下路径；本次没有实施或记入节省量。

1. **在已有梯度流上定位。** `edge_algorithm_pair.v` 已将 Sobel 的两像素 magnitude+2bit direction 送入 NMS。保持当前预处理、边界和坐标网格，定位器可取这条流，避免再建整套灰度/Sobel 窗口与第二次 DDR 全帧读取。若定位算法需要完整 signed gx/gy，要从 `sobel_pair.v` 内部新增输出。新分支需保证整帧接收或明确拒绝任务，保留 frame_id/epoch，不能让定位反压阻塞原演示。
2. **扩展现成的缓存所有权。** `canny_hysteresis.v` 的 `cache[0:2047]` 为 32 KiB，下半部缓存图像块，上半部给形状队列前缀；整个实例还含 queue/tag，实际 34 RAM。`frame_store.v` 已在 Canny 完成后把 ext_* 口交给 shape。OCR 可研究第三个所有者，进入前排空事务，保存/结束旧任务、失效 tag，离开时重建所需内容。端口宽度、银行布局、OCR 权重/部分和跨块寿命尚未证明兼容，不能预先记作省 32/34 RAM。
3. **页面串行时复用工作窗口和算术。** 原算法窗口共 46 RAM，在旧边缘页仍需完整工作。若识别页按“定位 → 持有来源帧 → 几何输入 → OCR”串行，可研究将完成定位后空闲的窗口银行交给 OCR，再在切页时排空并恢复旧算法状态。reader 的 7 RAM 与规划 OCR IO 的 7 RAM也需先证明非重叠生命周期。shape 的 19 DSP 是不同位宽/操作的实际映射，不等于可直接提供 8 路 signed17×signed8 MAC；复用需位精确回归和新 map。
4. **相同字形的存储布局优化。** 可研究相同 32×32 字形的紧凑打包或 DDR 预取，保留原号码、字号、TTL和逐像素输出。视频扫描不能等待 DDR；显示缓存必须在帧提交前就绪。现有 16 RAM 是基准，尚无新资源结果。

capture/display FIFO、CSI、ISP、DDR PHY 在两类页面都持续使用，不能因“页面串行”就划给 OCR。原 frame_store 管理 capture/job/pending/freeze/result/display 等引用，尚无 OCR 引用；需要把来源身份加入持有/释放管理。不能把现有视频 job 锁住约 433ms 来代替 OCR 所有权。

以上是同一硬件、保留原功能和显示语义的候选。删除边缘页/菜单/记录/四格、关闭 Canny/shape、减小字形、延长 TTL、减 MAC 位宽、换更大 FPGA或放宽预算，都不属于本次允许的解决路径。

## 5. OCR-only 时延与 DDR

scalar-read 候选保持冻结。已有事务周期推算得到 **43,341,492 cycles，100MHz 下 433.41492ms/ROI**。理想单引擎核心上限约 **2.307 ROI/s**，尚不含定位、几何、pool、energy/gain、height、CTC、控制与 DDR 停顿，不能当作整链识别帧率。

按现有 500ms 来源年龄门槛，核心本身之外只余 **66.58508ms** 给来源采集至识别完成的其余阶段。这是可用时间差，不是已达到 TTL。三次一致确认仍按现有逻辑保留，不能用处理完成时间代替来源时间。

已有全标量读 miss 场景的 OCR payload 为 **361,520,608 B/ROI**：输入 18,034,656 次、pool 1,686,528 次、context 2,175,552 次，各按 16B；加特征写 1,596,288B、权重读 9,561,760B、参数读 14,784B。没有测量 miss率、总线开销或重试。退出的检测/颜色两模型在旧单次场景中共占 723,762,976B；这是历史服务量的减少，不是实际带宽测量。

新输入链已有明确字节数：224×64 RGB 的 43,008B 在 geometry/resize 间走流，不再要求中间 DDR 写；OCR HWC 输入为 **6,768B，423 个 16B 写 beat**，不在每行补 16B padding。几何有 57,344 次邻点请求，实际 DDR 量取决于 reader 的突发/重复读，未按 0 计。私有原始帧拷贝若采用需额外读写 5,529,600B；接入已有帧引用持有后可研究避免拷贝，目前不能默认已经实现。

旧 497,664,000B/s 视频数字只覆盖如下固定 payload，不代表完整 Canny/shape 的总流量：

| 720p 假设：capture/job 30fps、display 60fps | B/s |
|---|---:|
| RGB24 capture 写 | 82,944,000 |
| RGB24 algorithm 读 | 82,944,000 |
| 32bit result 写 | 110,592,000 |
| 32bit display 读 | 221,184,000 |
| 合计 | **497,664,000** |

Canny 每帧 2bit/pixel state 为 230,400B；同样帧率下再加 state 写 6,912,000B/s、seed scan 6,912,000B/s、display state 13,824,000B/s，固定部分已到 **525,312,000B/s**。还要加数据相关的队列 push/pop、4KiB cache miss/回写以及 shape/reference/四格模式的读写。shape 的 state→visit 复制每次还需读写 460,800B。其余部分没有实测总量。

128bit×100MHz 的 1.6GB/s 是名义接口速率。现有 DMA 优先服务 capture/result/display，OCR 尚无带宽保证；不能用名义速率减上述视频固定值，宣称剩余带宽或有限最坏时延。shape 的 4,000,000 cycle watchdog 还需等待进行中的事务排空，也不保证40ms墙钟上界。

## 6. 私有 8 MiB arena

从冻结 integer-config 逐层重算权重并核对旧分配，当前可追溯的 OCR 部分为：

| 已知内容 | bytes |
|---|---:|
| 两个 262,144B feature slot | 524,288 |
| padded INT8 weights | 458,784 |
| 参数，含 tap2 分叉 | 14,784 |
| context A8 | 37,184 |
| 已知小计 | **1,035,040** |
| 加可选 RGB24 原始帧私有副本 | **3,799,840** |

已知小计距 8,388,608B 还余 7,353,568B，但描述符、定位工作区、查表/控制存储、输入提交区是否借用 feature slot 等尚未形成完整地址与生命周期计划，**不宣称 arena 已完成分配**。旧 7,052,352B 是三模型保留方案，继续作为历史，未改冻结 manifest。现有视频 raw/result/Canny DDR 区与这块私有 arena 分开；不能从原视频已占用区借空间而不做所有权设计。

## 7. 调研依据与下一步验收条件

实际阅读 AMD/Xilinx [Vitis Vision xf_sobel.hpp](https://raw.githubusercontent.com/Xilinx/Vitis_Libraries/main/vision/L1/include/imgproc/xf_sobel.hpp) 的 `ProcessSobel3x3`、三行缓存、窗口移位和 gx/gy 输出实现（约181–367行）。它支持“流上复用窗口”的成熟做法；HLS 平台和边界处理不同，未复制其代码，也未把它当 Ti60 的资源数据。直接下载因15秒读取超时失败，改由网页工具读取实际源码；记录位于 `tmp/blue-plate-whole-plate-budget/same-firmware/research/sources.json`。

本地逐项阅读了 `edge_algorithm_pair.v`、`sobel_pair.v`、`rgb_to_gray.v`、`frame_store*.v`、`canny_hysteresis.v`、`shape_recognizer.v`、`geometry_ocr_input.v`，并核对全部相关 map/place/hier 报告。原灰度为 `(77R+150G+29B+128)>>8`，几何路径没有相同舍入项；OCR还要求RGB/BGR，不能把灰度复制三通道当数值等价输入。

最小后续验证应围绕真实缺口：先给已有 Canny/shape ext_* 缓存建立第三所有者的银行/端口/生命周期方案，结合页面串行复用现有窗口；同时保持 capture/display 和原页功能。成功标准是实际整体映射低于三项预算、旧页逐像素及控制行为不变、OCR冻结整数输出不变、切页/取消/超时后无旧引用或未排空事务。新定位器的召回/几何误差需由算法效果比较单独给出，此审计没有把它当已经可用。

本次检查通过：原始 237 文件快照一致；static-Q 17项和scalar-read 31项冻结哈希一致；三构建 map/place/hier 计数相符；顶层层次分配求和一致；OCR RAM、权重与payload算术复算一致。未重跑长仿真、综合或实拍评测。

复算命令：`D:/Python/python.exe -X utf8 -B tools/blue_plate/whole_plate_budget/same_firmware_audit.py`。只写本审计目录和对应 tmp；旧证据不改。项目根 README 的功能与运行方式未变化，本次只更新本工具 README 的当前路线入口。
