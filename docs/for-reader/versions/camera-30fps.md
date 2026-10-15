# 全视野30帧直显

工程：[coding/camera-30fps](../../../coding/camera-30fps/ti60f225_oob.xml)。构建ID：`0x60101001`。

完整2560×1440输入，输出1280×720彩色图像，约30fps采集处理、60Hz显示。支持RGB增益、Gamma、Bayer相位和状态统计。

默认设置：RGB389/256/427，Gamma关，BGGR。

已知状态：不含Sobel/Canny、录放和形状识别。

在项目根运行 `coding\camera-30fps\load.cmd` 加载冻结版本，`control.cmd --help`查看选项，`test.cmd`运行离线回归，`build.cmd`构建到tmp。详细操作见 [使用指南](../usage.md)。

`release/manifest.json`保存位流与原始输入身份，`config/`保存运行参数。历史证据位于 `docs/validation/camera-30fps/`；本次路径迁移验证见 [迁移记录](../../validation/reorganization/progress.md)。
