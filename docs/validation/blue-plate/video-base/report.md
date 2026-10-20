# 实时彩色视频底座验证

2026-10-18，Efinity 2026.1.132.4.5，Ti60F225 / I3。

专用 `live` 候选完成综合、接口生成、布局布线和离线位流生成：**24,090 XLR、106 RAM、85 DSP**。保持 XLR≤49248、RAM≤204、DSP≤128 的原预算，余量为 **25,158 XLR、98 RAM、43 DSP**。本结果用于车牌整机集成预算；尚未接入识别，也未上板。

## 实测资源

| 构建 | XLR | RAM | DSP | 状态 |
|---|---:|---:|---:|---|
| 冻结边缘工程（G1 文档记录，未在本任务重建） | 49,156 | 188 | 111 | 历史基线 |
| gates：只关闭 Canny/shape generate | 34,833 | 154 | 92 | 本次 map/interface/pnr 通过 |
| live：专用彩色直通、关闭历史命令及菜单 | 24,090 | 106 | 85 | 本次 map/interface/pnr/pgm 通过 |
| live 相对冻结记录减少 | 25,066 | 82 | 26 | 物理资源差值 |

map 原语数据：gates 为 20,557 LUT、18,622 FF、3,348 ADD、1,365 SRL8；live 为 14,282 LUT、13,586 FF、2,031 ADD、1,154 SRL8。live 的 RAM 为105 RAM10+1 DPRAM10，DSP 为70 DSP48+15 DSP24；最终 place 报告确认106/85块。XLR取布局报告，不将 LUT 或 LUT+FF 直接称作 XLR。

原始证据：[live map](evidence/live-map.rpt)、[live place](evidence/live-place.rpt)、[live timing](evidence/live-timing.rpt)、[live 层级资源](evidence/live-hier_util.rpt)、[自动核验](evidence/live-verification.json)。对照报告采用同目录 `gates-` 前缀。

## 时序

| live 时钟 | 目标频率 | 同时钟 setup slack | 同时钟 hold slack | 分析得到的最高频率 |
|---|---:|---:|---:|---:|
| core_clk | 100MHz | 2.847ns | 0.035ns | 139.801MHz |
| i_mipi_rx_pclk | 50MHz | 9.186ns | 0.027ns | 92.473MHz |
| hdmi_tx_slow_clk | 74.25MHz | 7.782ns | 0.045ns | 175.871MHz |

live 全部已分析关系的最小 setup/hold 为0.430ns/0.027ns；gates 为0.387ns/0.026ns。SDC和外设时钟配置沿用原工程，未降低时钟或新增例外以通过时序。HDMI fast clock仍为2.694ns的接口时钟；fabric最高频率表没有该时钟的内部寄存器路径，不能将slow clock表当作串行PHY实测。

原工程的未使用接口约束警告仍在，例如 `ddr_addr[15:14]` 找不到有效输出端口。主控已与原v5核对：新增的Missing Interface项为`key_select_n`，对应本次移除菜单按键；其他缺失/未分配项与原v5一致。报告的时序结论针对工具实际分析的约束路径，不代替板级相机/DDR/HDMI验证。

## 候选改动与保留项

全部产品源码复制自 `coding/edge-quality-30fps/`。仅在独立候选中做以下改动，详见 [逐行 diff](evidence/live-candidate.diff)：

1. `rtl/ti60f225_oob_top.v`：`ENABLE_CANNY/ENABLE_SHAPE` 均为0；删除 `edge_ui` 实例，固定彩色控制和零历史命令；帧处理配置固定0；配置代次仍跟随画质配置；实例化 `video_rgb_passthrough`。
2. 新增 `rtl/video_rgb_passthrough.v`：保持两个像素的RGB24、valid/ready、SOF/EOL/EOF和帧身份；只重建原结果帧的标记字节。第二像素、首两对像素的阈值/标记位置均保留原协议，未将图像输入或输出绑常量。
3. `rtl/threshold_osd.v`：保留原前48行的坐标/元数据接收和 `shown_descriptor/shown_toggle` 确认机制；RGB直接输出，移除边缘演示文字/图框绘制。
4. XML项目改名为 `blue_plate_video_live`，外设XML根名和引用同步修改；设计源表用直通模块替换边缘核源文件。原顶层模块名和端口保持一致，SDC、外设管脚/PLL配置不变。

相机CSI、I²C初始化、RAW edge-aware/area处理、RGB增益、gamma、DDR控制器/PHY、FIFO、实时帧分配、HDMI时序/编码和JTAG诊断均保留。`full_view`保留70 DSP、15 RAM，DDR层级保留39 RAM，`frame_store`保留27 RAM，HDMI时序FIFO保留4 RAM。层级XLR是工具分摊估计，整机总数以place为准。

网表确认 Canny/shape实例、median/Gaussian/Sobel/NMS实例、`user_controls`、菜单ROM、`clip_id/recorded_slots`已消失。历史控制RTL保留在候选来源文件中，但零命令入口让其综合消除。未删除旧边缘工程中的历史功能。

通用 `compare_display`仍保留6 RAM/6 DSP：它读DDR返回的元数据，综合器无法把所有存储内容证明为常量。本次保留原显示数据路径，不为继续压资源重写显示器；这些资源已计入24,090/106/85的实测总数。

## 帧与接口依赖

实际数据链路为：相机→RAW画质→RGB→capture FIFO→DDR raw slot→原算法读FIFO→RGB直通→result FIFO→DDR result slot→显示读FIFO→compositor→HDMI FIFO/时序→元数据确认及RGB输出。

- raw仍有41槽，地址 `slot*0x300000 + four_pixel_offset*12`，RGB24为三相位128位总线打包；result为3槽，基址`0x07b00000`、步长`0x400000`。这些是实时临时缓冲，没有保存/录像/回放入口。
- 保留原视频job。只有完整result写入并得到总线成功响应，控制器才发布显示帧；后续 `shown_toggle/shown_slot`保证正在显示的槽不会被复用。删除OSD时不能删掉这条确认链。
- 识别要另加raw帧持有引用；当前 `held`只有原有capture/pending/job/result/display引用，没有G1要求的独立识别引用。不能把当前视频job占到七字符识别结束。
- G1需独立DDR读取仲裁与ROI拆包。现有raw地址/三相位拆包机制必须复用，不能把128位总线拍直接当作两个RGB像素。当前通用算法端为50MHz、每拍两个像素；G1核心处理100MHz，需要明确CDC或在core域另接读流。
- ROI/识别忙时跳过新识别任务，并在结束、错误、超时排空后释放引用；采集和显示保持优先。这些接入内容由主实现窗口负责，本子任务没有改动接口协议。
- 未来车牌OSD可在本候选RGB输出处添加，必须保留帧描述符接收器；号码包跨域后仍需在显示帧边界原子提交。

按采集/复制30fps、显示60Hz计算，现有临时帧链路的有效数据量约497.664MB/s：raw写82.944、raw读82.944、result写110.592、显示读221.184MB/s，不含突发和等待开销。识别每秒10次全幅RGB24扫描再增加27.648MB/s，ROI重读另计。这是地址格式推算，未测实际DDR持续吞吐；集成需验证显示期限与识别仲裁。

## 集成预算

| 项目 | XLR预算 | RAM | DSP | 依据 |
|---|---:|---:|---:|---|
| 实测live底座 | 24,090 | 106 | 85 | 本次布局布线 |
| 字符分类器暂留 | 1,000 | 33 | 1 | 上游给出的独立map为467 LUT/222 FF、33 RAM、1 DSP；1000 XLR为规划预留，非其place结果 |
| 定位、ROI、归一化、OSD及接入预留 | 6,000 | 28 | 8 | 工程预算，尚未以RTL整机证明 |
| 预算合计 | 31,090 | 167 | 94 | 资源规划加法 |
| 距原工程预算线 | **18,158** | **37** | **34** | 不使用物理剩余替代预算余量 |

28 RAM可先规划为二值ROI 4、字符暂存1、中文字库5、行缓存/投影/直方图/FIFO等18。只是规划分配，真实块数由位宽、深度和端口决定；若增加320×96完整灰度片上缓存，需要重新核算。字符模型的功能修正或ROM布局变化也需更新数据。本表证明有集成空间，不证明整机综合、带宽、时序或识别性能通过。

## 命令与验证

工作入口：[tools/blue_plate/video_base](../../../../tools/blue_plate/video_base/README.md)。实际运行：

```powershell
./tools/blue_plate/video_base/build.ps1 -Variant gates -Flow map -Generate
./tools/blue_plate/video_base/build.ps1 -Variant gates -Flow interface
./tools/blue_plate/video_base/build.ps1 -Variant gates -Flow pnr
./tools/blue_plate/video_base/build.ps1 -Variant live -Flow map -Generate
./tools/blue_plate/video_base/build.ps1 -Variant live -Flow interface
./tools/blue_plate/video_base/build.ps1 -Variant live -Flow pnr
./tools/blue_plate/video_base/build.ps1 -Variant live -Flow pgm
D:/Python/python.exe -B tools/blue_plate/video_base/test.py
D:/Python/python.exe -B tools/blue_plate/video_base/test.py --full
D:/Python/python.exe -B tools/blue_plate/video_base/test_display.py
D:/Python/python.exe -B tools/blue_plate/video_base/test_display.py --full
D:/Python/python.exe -B tools/blue_plate/video_base/verify.py live
```

`pgm`是Efinity离线位流生成阶段，本任务没有运行`program`、`load`或设备操作。

已通过：32×16四张不同RGB帧各128词完整核对；1280×128和1280×720三帧HDMI彩色输出、持续算法读竞争、AXI气泡、显示期限及变化frame_id/epoch/slot的描述符接收。HDMI原session 88335退出0。

旧完整存储session 81016退出0，但主控发现其完成条件累计了重复显示帧，不能证明13号新帧最后一词已验证；旧PASS标为覆盖不足，不计四帧完整验收。已改为记录`completed_frame_id/epoch`及逐ID的`verified_words`，等待10/11/12/13各完成全部词，小图已通过；修正后的720p完整测试原 session 29664 已退出0，10/11/12/13号帧各完整核对230400词。原日志、二进制和输入快照保留，没有将旧PASS挪作新测试结论。

修正后完整证据：[逐ID四帧日志](evidence/full-complete-run.log)、[冻结编译输入、命令、二进制哈希和退出码](evidence/full-complete-execution.json)。原进程持续运行至完成，未重启；核对编译快照哈希未变化。

原日志：[720p存储](evidence/full-run.log)、[720p HDMI](evidence/display-full-run.log)。[编译输入/二进制哈希及退出码](evidence/compiled-inputs.json)对应`tmp/blue-plate-video-base/tests/compiled-inputs/`的源码快照；候选源文件与生成时清单逐个相符。存储测试使用原测试的BURST=16，HDMI测试使用产品BURST=128；两者验证范围分别为存储像素与显示期限，不据此声称实机吞吐已测。

综合后沿用 `check-edge-build.ps1`，capture/result FIFO各48个RGB寄存器输入均为非零常量源；另检查实际相机画质、采集FIFO、结果FIFO、DDR与HDMI时序层级存在。资源来自真实顶层端口/外设构建，不是仿真驱动或固定图案顶层。

两次早期构建问题均已修复：工具内置Python需要显式`PYTHONHOME`；首版UI裁剪把阈值控制器输出`ui_presses`误加了常量驱动，Efinity拒绝展开，现已移除该驱动。失败工程和日志留在`tmp/blue-plate-video-base/live-elaboration-failed/`。

## 原工程保护与交付物

生成时对原工程237个文件取SHA256，构建后逐个复核通过；包括源码、配置、测试和release。完整列表见 [live inputs](evidence/live-inputs.json)。关键哈希：

| 原文件 | SHA256 |
|---|---|
| `rtl/ti60f225_oob_top.v` | `bf9f348865c69d7bc03377d1f0dd44cd30a8d270b487319ef03132a183378dbe` |
| `rtl/frame_store.v` | `2aaa5037cc3cb220dd07135d252c84ab11befe752618184d56b442c6b46ad628` |
| `rtl/frame_store_control.v` | `3f5e0b41c35c77a3f4142ea9b2d1409d4f483d023fc2cb8624a62e178b5eaa96` |
| `rtl/frame_store_dma.v` | `b70b6ff71c0029bc8041f321edbd6983e596aaa2cbe369d83fc8e4402bbd8377` |
| `release/ti60f225_oob.bit` | `6e8c40886106793b78ef0dea46ee7b77d266fddbf51ae1cf33b15cfc318709df` |

离线候选位流：`tmp/blue-plate-video-base/live/outflow/blue_plate_video_live.bit`，2,490,729字节，SHA256 `770b57ed2ef7aeb7533d8f7ff71363c54be7646a8c378f660da99bc2edd155f2`。未覆盖release。生成/构建脚本、研究副本、输入清单、diff、报告及仿真日志均在授权的三个目录内。

本次未修改根README、主控台账、主实现目录或字符模型目录。独立生成器的README记录可复跑方式。

尚未验证：板上实时彩色画质/30fps与HDMI稳定性、相机独立上电默认增益与I²C初始化、识别接入后的DDR竞争/帧引用释放、完整号码识别及Flash独立启动。原工程active增益与load设置不一致的问题仍存在，本任务未操作或更改相机配置。
