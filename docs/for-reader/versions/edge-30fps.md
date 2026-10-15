# 原完整边缘系统

工程：[coding/edge-30fps](../../../coding/edge-30fps/ti60f225_oob.xml)。构建ID：`0x6010100a`。

M10/O1整机：灰度、Sobel、完整Canny、对比、中值、红边叠加、阈值、按键菜单、冻结/单步/32帧录放/参考对比、曝光控制和形状识别实现。

默认设置：默认Sobel对比、阈值32、中值开、识别关；恢复约20ms曝光配置。

已知状态：识别性能未完成验收；边缘闪动未解决。历史不开识别约30fps，开启识别约12.5～13.9fps的记录对应早期M10构建，不能当作本次重测结果。

在项目根运行 `coding\edge-30fps\load.cmd` 加载冻结版本，`control.cmd --help`查看选项，`test.cmd`运行离线回归，`build.cmd`构建到tmp。详细操作见 [使用指南](../usage.md)。

`release/manifest.json`保存位流与原始输入身份，`config/`保存运行参数。历史证据位于 `docs/validation/edge-30fps/`；本次路径迁移验证见 [迁移记录](../../validation/reorganization/progress.md)。
