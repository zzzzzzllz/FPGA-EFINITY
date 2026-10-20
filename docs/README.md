# 文档索引

当前操作以for-reader内的文档为准。validation保存某次验证的原始结果，design/stages保存对应阶段的技术细节；其中的历史路径不是当前加载入口。

当前主线为第二版 `edge-quality-30fps`，其他代码版本已移到归档分支。旧文档中的工程链接需切换到对应分支；当前分支安排见 [本地Git使用说明](for-reader/git.md)。

- [使用指南](for-reader/usage.md)：四个版本怎么构建、测试、烧录和控制。
- [赛题四要求逐条解读](for-reader/contest-requirements.md)：平台、五项基础要求、六项高阶挑战及验收清单，对应赛题 PDF 第 12—17 页。
- [第一版按键与效果导览](for-reader/versions/edge-30fps-demo.md)：原完整边缘版的上板检查顺序和思维导图。
- [第二版画质版导览](for-reader/versions/edge-quality-30fps-demo.md)：画质版的默认参数、按键与架构图。
- [第二版串行演示与验收](for-reader/versions/edge-quality-30fps-serial-demo.md)：14步按键路线、全部赛题要求对应环节、实现说明与验收顺序。
- [第三版60帧导览](for-reader/versions/edge-60fps-demo.md)：归档60帧版本的电脑切换命令、效果与架构图。
- [版本与目录说明](for-reader/project-structure-audit.md)：功能差异、目录边界与已知问题。
- [术语](for-reader/GLOSSARY.md)：帧率、全视野、默认关闭和验收状态。
- [当前系统结构](design/architecture.md)：采集、算法、存储、显示和控制的关系。
- [纯 FPGA 蓝牌实时识别设计](design/license-plate-recognition.md)：实时画面与完整蓝牌号码显示，不建设保存系统；包含识别方案、资源预算和独立启动验收，尚未实现。
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
