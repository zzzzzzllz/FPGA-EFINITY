# 四版本与目录边界

四类各保留一份完整工程，统一位于coding；旧试验、重复备份和散落入口在验证后清理。项目使用本地Git，位流和工具链二进制另行保留。

| 目录 | 职责 |
|---|---|
| coding/camera-30fps | 完整视野彩色直显基线 |
| coding/edge-30fps | 原完整M10/O1边缘系统 |
| coding/edge-quality-30fps | 最近确认的完整Canny画质优化版 |
| coding/edge-60fps | 用户选择的65版10ms裁切60帧试验 |
| docs/for-reader | 使用指南、功能比较、测试图 |
| docs/design | 当前结构和阶段实现细节 |
| docs/reference | 硬件手册、厂家说明、第三方出处和许可证 |
| docs/validation | 所选版本的原始验收与迁移证据 |
| tools | 共享控制、构建核查、Icarus和结构图 |
| tmp | 可重建的构建、仿真及一次性输出 |

前三类保留全视野30fps，60帧是中心裁切。完整边缘版与质量版都有Canny和帧管理；质量版默认关闭中值和识别，功能仍存在。识别性能、边缘闪动、60帧黑屏仍按已知问题记录。

四套源码独立保存，不在此次目录迁移中合并算法；各自的XML、约束、profile、位流和运行参数配套。

[使用指南](usage.md) · [当前结构图](../../tools/archify/project-structure-20261015/target.html) · [本轮验证与清理](../validation/reorganization/progress.md)
