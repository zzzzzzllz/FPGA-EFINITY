# 画质优化完整边缘系统

工程：[coding/edge-quality-30fps](../../../coding/edge-quality-30fps/ti60f225_oob.xml)。构建ID：`0x6010100f`。

保留完整边缘系统，使用EA前端、精确中值资源优化、高斯复用及自然边界保护清理。来自quality_preserve/resource2。

默认设置：Canny24/12，灰度/边缘对比，中值关、识别关、实时；约20ms曝光、3.032倍模拟增益。

已知状态：默认配置已有约30fps板测与画面确认；亮度波动减轻，但边缘闪动仍在。识别当前版本未完成实拍验收。

在项目根运行 `coding\edge-quality-30fps\load.cmd` 加载冻结版本，`control.cmd --help`查看选项，`test.cmd`运行离线回归，`build.cmd`构建到tmp。详细操作见 [使用指南](../usage.md)。

`release/manifest.json`保存位流与原始输入身份，`config/`保存运行参数。历史证据位于 `docs/validation/edge-quality-30fps/`；本次路径迁移验证见 [迁移记录](../../validation/reorganization/progress.md)。

[保留的自然边界局部对照图](../../validation/edge-quality-30fps/comparison-overview.png)展示这一版本的实际离线效果，逐图指标保存在同目录results.json；它不是边缘时间闪动已经解决的证明。
