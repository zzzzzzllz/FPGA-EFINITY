# 蓝牌实时彩色视频底座资源验证

生成器只读取 `coding/edge-quality-30fps`，将候选放到 `tmp/blue-plate-video-base/{gates,live}`。所有报告、仿真和失败记录均在独占 tmp 目录。未接入车牌识别，无下载或摄像头配置命令。

`gates` 只关闭现有 Canny/shape generate，供对照。`live` 固定彩色、断开历史命令、用 RGB/帧元数据直通替换边缘核，并将旧 OSD 缩减为显示帧描述符接收器。相机、RAW 处理、增益、gamma、DDR/PHY、帧槽管理、HDMI/FIFO 和诊断保留。

根目录运行，第一次生成：

```powershell
./tools/blue_plate/video_base/build.ps1 -Variant live -Flow map -Generate
./tools/blue_plate/video_base/build.ps1 -Variant live -Flow interface
./tools/blue_plate/video_base/build.ps1 -Variant live -Flow pnr
```

将 `live` 换成 `gates` 可复跑对照。已生成候选可直接复跑任一阶段；完整重建用 `-Flow compile`，不加 `-Generate`。Efinity 默认 `D:/Efinity`，也读取 `EFINITY_HOME`。

生成器拒绝覆盖已有候选，避免丢失证据。需要更新源码快照时，先将对应候选目录移到本 `tmp/blue-plate-video-base/` 下的归档目录，再重新 `-Generate`。每次生成记录全部原工程文件 SHA256、候选输入 SHA256 和 RTL diff。源文件或候选输入被修改会导致验证报错。

```powershell
D:/Python/python.exe -B tools/blue_plate/video_base/test.py
D:/Python/python.exe -B tools/blue_plate/video_base/test.py --full
D:/Python/python.exe -B tools/blue_plate/video_base/test_display.py
D:/Python/python.exe -B tools/blue_plate/video_base/test_display.py --full
D:/Python/python.exe -B tools/blue_plate/video_base/verify.py live
```

测试复用原工程的 AXI 响应器、像素参考和 CDC/FIFO 检查，替换算法为实际候选直通核。`test.py` 检查四张不同 RGB 帧与帧槽换帧；`test_display.py` 检查三张 RGB 帧在算法读竞争下的 HDMI 像素、期限和显示元数据。仿真不包含相机硬核和实际 DDR 物理器件。

预算线固定：XLR≤49248、RAM≤204、DSP≤128。map 阶段检查 RAM/DSP 和网表连通性，精确 XLR 等待 place 报告；pnr 检查全部已分析 setup/hold 关系和三条视频时钟。没有关闭余量检查。

结果和接入依赖见 [验证报告](../../../docs/validation/blue-plate/video-base/report.md)，调研见 [来源与取舍](../../../docs/validation/blue-plate/video-base/research.md)。
