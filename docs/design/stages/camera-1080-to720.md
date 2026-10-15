> 历史技术记录。仅说明记录时的版本；当前操作与状态以 [使用指南](../../../docs/for-reader/usage.md) 为准。文中旧路径用于溯源，不是当前运行入口。

# 1080p60 采集转 720p 主线接口

直显工程：`camera_trials/1080_to_720_60/`。已实测 30.547 秒采集与缩放输出均增加 1833 帧，约 60.006 fps，31 次采样尺寸均正确、错误与溢出均为零。用户确认画面结构正常。主线 Sobel 的独立适配副本位于 `camera_trials/edge_720p60/`；原 `camera_edge/` 保持原样。

## 数据路径

传感器输出 1920×1080、四通道 RAW10。FPGA 先恢复 Bayer 彩色，再在两个方向每三个像素保留两个，输出 1280×720。使用最近邻抽样，没有低通抗混叠滤波；细密纹理可能出现锯齿或摩尔纹。该模式裁取传感器中心区域，视野小于原来的 2560×1440 全幅模式。

`raw_1080_to_720.v` 保留主线 `raw_full_view` 的双像素 RGB64 接口；前端时钟为 100 MHz。接入主线时必须同步更新接收器时钟及约束，并重新验证处理帧率。仅 HDMI 为 60 Hz 或采集计数达到 60 fps，不能证明 Sobel 等后级已经处理 60 fps。

## 初始化

用户 INI 的 HTS=1400、VTS=1500 配置在本板收到不完整帧后停止；切换接收器时钟模式也未解决。可用配置采用 [Iris 的同型号 1080p60 初始化表](https://github.com/Iris-FPGA/Iris/blob/7873413d916c471d553f3717566cfa4db2a68fc5/firmware/video-1080p60-20261003/README.md)，本地来源为 `research/sc431hai-60fps/iris-sc431hai-rom.v`。HTS=1622、VTS=1150，PLL 的 36e9/37f9=44，接收器设为 70 MHz 字节时钟、Continuous、4096 深度像素 FIFO。仍使用厂家原工程的 5.15 接收 IP，未替换为参考工程的 5.17 IP。

增加软件复位与 10 ms 等待，显式设置四通道 RAW10、关闭镜像翻转，保留原稳定版模拟增益 3e08/3e09=80/2a。曝光由参考表的 512 个半行改为 2000 个半行（3e00/01/02=00/7d/00），约 14.5 ms。主线副本还补齐 `i2c_16addr_8data.v` 的读回数据连线，初始化读回成功后才释放接收器。

12 次白卡采样 RAW10 均值约为 120.134/165.278/111.629，得到归一化 Q8.8 白平衡 352/256/379；采用两倍整体亮度后实际加载 704/512/758，Gamma=0、BGGR。用户确认色彩正常，但弱光下偏暗。三倍增益 1056/768/1137 被用户判为噪点明显、画面偏灰，已恢复两倍增益。参数保存在 `white-balance-60fps.json`，30 帧校准文件不覆盖。

## 入口与检查

- `test-camera-1080-to720.cmd`：两帧完整分辨率仿真，连续像素突发、逐像素比较、帧计数与缓存溢出检查。
- `build-camera-1080-to720.cmd`：构建独立工程。
- `load-camera-1080-to720.cmd`：SRAM 下载并应用白平衡。
- `D:\Efinity\bin\python3.bat camera-1080-to720-control.py --samples 31`：读取状态，不重置白平衡和 Gamma。

直显构建标识为 `0x6010100d`。状态应为采集尺寸 1920×1080、每帧输出 921600 像素、缩放溢出为零；还需检查采集错误、MIPI 状态、DDR 就绪和显示欠载。`output_frames` 是缩放输出帧计数，尚不是 HDMI 或主线算法完成帧计数。直显版 Gamma=1 保留给调试数据选择；正常显示使用 Gamma=0。`--diagnostics` 会临时修改控制参数，结束后恢复 704/512/758、Gamma=0、BGGR。

主线副本入口为 `build-edge60.cmd`、`load-edge60.cmd` 和 `camera-edge60-control.py`，构建标识 `0x60101013`。默认加载彩色视图，`--view gray` 或 `--view edge` 切换显示；`processed_frames` 统计实际完成的 Sobel 帧。主线副本 `sum_r/g/b` 为增益前 RAW10 通道总和，排除人工生成的灰色首行，除数为 1920×1079=2071680。

离线带间隙和连续突发的两帧完整分辨率仿真通过，日志为 `logs/camera-1080-to720-simulation.log`、`logs/camera-1080-to720-burst-simulation.log`。`test-edge60.cmd` 覆盖 RAW 通道统计和实际顶层灰度/Sobel 适配器的四个完整 720p 帧。直显曝光调整版 Efinity 综合、接口生成、布局布线及位流生成通过；建立余量最小 0.386 ns，保持余量最小 0.026 ns。

原稳定版入口 `load-camera.cmd` 和 `white-balance.json` 保持不变。

## 主线副本实测

`logs/camera-edge60-final-status.log` 的 61 次采样跨越 61.031 秒，采集和 Sobel 完成计数各增加 3665，约 60.051 fps，全部采集尺寸为 1920×1080。采集错误、MIPI 标志周期、Sobel 输入过载均为零；启动后显示欠载累计为 4，持续测试无新增，DDR 始终就绪。见 `logs/camera-edge60-verification.json`。该结果验证吞吐，不代替算法检测效果验收。

最终构建建立/保持余量最小为 0.357/0.026 ns，位流 SHA256 为 `1D99E6D5277F1B288622ED2451F93D8D563DC72C333F448C69A5BE0DACD16551`。

两版实屏对比使用 `load-camera.cmd`（全幅 30 帧）和 `load-edge60.cmd`（中心裁切、720p 输出、约 60 帧）。两版还存在视野、彩色恢复方式、曝光和增益差异，因此这是当前可用程序的整体对比。

最终选择：用户明确要求“恢复 30 帧，优先画质和完整视野”。已使用 `load-camera.cmd` 恢复原版，主线保持原 30 帧方案。60 帧工程与校准参数保留，不作为默认加载版本。恢复记录为 `logs/camera-ab-selected30-load.log`、`logs/camera-ab-selected30-status.log`。
