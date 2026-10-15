> 历史技术记录。仅说明记录时的版本；当前操作与状态以 [使用指南](../../../../docs/for-reader/usage.md) 为准。文中旧路径用于溯源，不是当前运行入口。

# 720p60 颜色重建修复，2026-10-14

目标：去掉相邻两列强制使用同一个 RGB 值的问题，保留 30 帧基线，对 60 帧实屏清晰度做验证。

## 已阅读的参考实现

- Antmicro FPGA ISP：<https://github.com/antmicro/fpga-isp-core/blob/main/fpga_isp/debayer/bilinear.py>。实际下载并阅读 `antmicro-bilinear.py` 的 `get_decoder`、缓存与扫描状态机。3×3 窗口在 R/B 位置保留中心值，绿色取十字邻域平均，另一色取对角平均；G 位置按行列方向补 R/B。其 Migen/LiteX 状态机与本项目四像素并行接口不同，不直接移植。
- Colour Science：<https://github.com/colour-science/colour-demosaicing/blob/develop/colour_demosaicing/bayer/demosaicing/bilinear.py>。实际下载并阅读 `colour-bilinear.py`，使用 Bayer 掩码和 G/RB 两组 3×3 卷积核，可作为独立数值参考。边界需明确适配，不能默认软件卷积边界等于硬件处理。
- 本地已有 `camera_trials/edgeaware_area/.../rtl/raw_edgeaware_area.v`：读取了两行 RAM、四像素窗口和边界处理实现。该模块还包含 2:1 缩放与器件专用 DSP 运算，不能整体用于当前 3:2 链路；借鉴同步行缓存与组间邻域组织方式。

下载源码、提交元数据及许可证放在本目录。只阅读参考资料，没有执行下载的程序。采用标准双线性公式自行适配，不引入 Migen、LiteX 或 Python 运行时依赖到 FPGA 工程。

## 决策与验证

采用逐像素 3×3 双线性重建，四 RAW10 输入对应四个独立 RGB10 输出。已测颜色保留中心样本，缺失颜色用同色邻域整数四舍五入；边缘按镜像延拓，保持 Bayer 相位。增加一行 RAW 缓存和窗口邻居，最后一行在垂直消隐期补齐。现有 3:2 面积缩放、曝光、增益、DDR 与 HDMI 链路保持；移除缩放器原先对人工灰色首行的替换，因为新重建已有有效首行。

本轮先不采用 5×5 Malvar 或方向自适应算法：修复已确认的相邻列复制不需要引入更大窗口和梯度选择。先证明标准重建消除复制，再根据实屏决定后续。

验证：独立 Bayer 掩码卷积参考、四相位、随机帧后接黑帧、连续/间隙输入、四边与分组边界逐像素比较；保留中心实测颜色断言；斜坡/细线图检查相邻列不再成对复制；完整 1080p→720p 与灰度/Sobel 链仿真、资源和时序检查；上板测帧率/错误并由用户检查清晰度。模拟结果只证明算术与吞吐，实屏改善才作为画质验收。

## 上板反馈与防闪烁测试

`0x60101064` 上板后用户反馈“画面正常，但清晰度差不多”，随后反馈“一直在闪”。方向自适应重建仅继续阅读了本地 OpenCV `Bayer2RGB_EdgeAware_T` 相关位置和已有 EA RTL，尚未修改算法。用户选择保留 60 帧，优先测试 10 ms 曝光并补偿亮度。

成熟防闪烁依据：libcamera 的 `AeFlickerPeriod` 将 50 Hz 市电常见的 100 Hz 光照周期设为 10000 µs：<https://github.com/raspberrypi/libcamera/blob/main/src/libcamera/control_ids_core.yaml>。这不是当前灯具频率的实测值，需上板检查闪烁是否减轻。

实际读取本地 `research/sc431hai-60fps/thingino-t41-sc431hai.c` 的曝光写入和模拟增益表；表中包含 0x802a、0x803d，两者对数增益分别为 66524、101833。原始来源索引见根目录 `logs/sc431hai-60fps-research.json`；未复制驱动代码。

VTS=1150、已测约 60.04 fps，对应 10 ms 约 1381 个半行，曝光寄存器为 00/56/50。同一增益档内微调 3e09 从 0x2a 到 0x3d，增益比约 61/42，补偿曝光从 2000 到 1381 个半行的缩短；理论亮度比约 1.003。保持 RGB=704/512/758、Gamma=0，不增加显示端数字增益。新增启动后曝光/增益读回状态，验证摄像头确实接受配置。

## 噪点与偶发黑屏排查

用户确认 10 ms 后灯光闪烁减轻、亮度合适，细节仍模糊且噪点明显，约十秒黑一下。Basler 的 [增益说明](https://docs.baslerweb.com/gain) 与 [画质优化](https://docs.baslerweb.com/optimizing-image-quality)说明增益放大像素值，不能增加收到的光子；保持 60 fps、10 ms 时，应补光后降低总增益，而不是继续提高锐化。

已下载并阅读 `projf-display_480p.sv` 的行/帧计数、同步极性、DE 生成，来源 https://github.com/projf/projf-explore/blob/main/lib/display/display_480p.sv 。其时序自由运行；本工程 CVO 在 FIFO 欠读时复位时序。当前累计欠读没有增长，不能将该路径直接认定为根因。现有 0.25 秒轮询也可能漏掉一个黑帧。

选择仅增加编码前逐帧监测：有效像素数、行/帧时钟周期、黑帧/亮度骤降、显示复位次数，跨时钟用每项 Gray 计数传输。它不改变任何视频输出、曝光或增益。通过注入黑帧、缺像素、短行与复位验证能捕获，再上板关联人工黑屏；不把计数正常当作 HDMI 电气链路正常的证明。
