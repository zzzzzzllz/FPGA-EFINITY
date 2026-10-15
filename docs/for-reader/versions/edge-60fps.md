# 裁切视野60帧10ms试验版

归档分支：`archive/edge-60fps`。用户本轮实测不接受此版，后续以第二版为主。下方工程链接和命令须先切换到归档分支。

工程：[coding/edge-60fps](../../../coding/edge-60fps/ti60f225_oob.xml)。构建ID：`0x60101065`。

[第三版上板导览与思维导图](edge-60fps-demo.md)：电脑切换灰度／Sobel及实际架构。此版没有板上功能菜单。

1920×1080中央裁切输入，经逐像素双线性颜色重建与面积缩放输出720p，支持彩色、灰度和Sobel。

默认设置：RGB704/512/758，Gamma关，BGGR，彩色；1381半行曝光、增益寄存器803d，约10ms。

已知状态：用户明确保留此版并接受偶发黑屏未解决。清晰度未验收；不是全幅60fps，也没有完整Canny、32帧录放及识别。

在项目根运行 `coding\edge-60fps\load.cmd` 加载冻结版本，`control.cmd --help`查看选项，`test.cmd`运行离线回归，`build.cmd`构建到tmp。详细操作见 [使用指南](../usage.md)。

`release/manifest.json`保存位流与原始输入身份，`config/`保存运行参数。历史证据位于 `docs/validation/edge-60fps/`；本次路径迁移验证见 [迁移记录](../../validation/reorganization/progress.md)。
