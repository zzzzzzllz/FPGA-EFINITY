# 文档索引

当前操作以for-reader内的文档为准。validation保存某次验证的原始结果，design/stages保存对应阶段的技术细节；其中的历史路径不是当前加载入口。

- [使用指南](for-reader/usage.md)：四个版本怎么构建、测试、烧录和控制。
- [版本与目录说明](for-reader/project-structure-audit.md)：功能差异、目录边界与已知问题。
- [术语](for-reader/GLOSSARY.md)：帧率、全视野、默认关闭和验收状态。
- [当前系统结构](design/architecture.md)：采集、算法、存储、显示和控制的关系。
- [第三方来源与许可](reference/third-party.md)：已采用实现的出处及许可证。
- [迁移记录](validation/reorganization/progress.md)：本次整理的验证与清理结果。

硬件手册位于 `reference/hardware/`：SC431HAI手册、易灵思赛题资料、Ti60F225装配图。厂家IP说明位于 `reference/vendor/`。识别打印测试图位于 `for-reader/test-targets/`。

按问题查阅技术资料：

| 内容 | 文档 |
|---|---|
| 采集、缩放与60帧 | [1080p转720p](design/stages/camera-1080-to720.md)、[60帧阶段记录](design/stages/camera-720p60.md) |
| 边缘系统与接口 | [系统设计](design/stages/edge-system-design.md)、[M01基线](design/stages/edge-m01-baseline-check.md) |
| 灰度、Sobel与显示 | [M02灰度](design/stages/edge-m02-grayscale.md)、[M03 Sobel](design/stages/edge-m03-sobel.md)、[M04对比](design/stages/edge-m04-compare.md) |
| 阈值、中值与叠加 | [M05阈值](design/stages/edge-m05-threshold.md)、[M06中值](design/stages/edge-m06-median.md)、[M07叠加](design/stages/edge-m07-overlay.md) |
| 帧管理、Canny与识别 | [M08帧功能](design/stages/edge-m08-frames.md)、[M09 Canny](design/stages/edge-m09-canny.md)、[M10识别](design/stages/edge-m10-shapes.md) |
| 曝光和画质 | [O1曝光](design/stages/edge-o1-exposure.md)、[EA前端](design/stages/edgeaware-area-fixed.md)、[画质基线](design/stages/image-quality-baseline.md)、[图像链配合](design/stages/image-chain-coordination.md) |

四个版本分别有 `validation/<版本名>/`。原始JSON中的日期、旧路径、board_tested等字段保持原样，结合对应版本说明理解，不能把早期离线记录当成后来板测状态。
