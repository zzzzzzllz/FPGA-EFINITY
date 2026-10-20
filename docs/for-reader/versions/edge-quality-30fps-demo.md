# 第二版旧菜单上板记录（历史）

本文记录 `0x6010100f` 的旧菜单，保留当时的运行证据。当前按键及加载配置见[串行演示与验收步骤](edge-quality-30fps-serial-demo.md)，不再按下列旧菜单操作。

[按键、画面与架构思维导图](../../../tools/archify/edge-quality-30fps-guide-20261015/guide.html)

当前版本是edge-quality-30fps，构建ID为0x6010100f。初始画面是左灰度、右Canny边缘；高阈值24、低阈值12，中值关、识别关、实时，配套约20ms曝光和3.032倍模拟增益。

| 操作 | 作用 |
|---|---|
| KEY1短按 | 下一菜单；FRAME菜单中执行动作 |
| KEY2 / KEY3 | 减／加、关／开或上一项／下一项 |
| KEY1长按约0.8秒 | 实时或录制时冻结；冻结或回放时返回实时 |

建议先看默认Canny效果，然后长按KEY1冻结。从初始VIEW菜单短按KEY1两次到THRESHOLD，KEY2将24减到8，KEY3将24加到40；按键步长为16。底部菜单若已变化，按菜单名称定位，不沿用次数。

菜单顺序仍是VIEW → ALGORITHM → THRESHOLD → LOW RATIO → MEDIAN → RECOGNITION → FRAME。选择Sobel后会跳过LOW RATIO。VIEW中的GRAY、EDGE、COMPARE、DENOISE、OVERLAY、REFERENCE，以及FRAME的单步、32帧录放、参考等操作都在图中；COLOR原图不作为本次单独检查项。

这版的主要变化在图像处理：EA边缘感知颜色恢复与区域缩放、精确中值实现、高斯资源复用，以及Canny分类后的自然边界保护清理。按键菜单和阈值控制与第一版源码相同，其他帧管理逻辑也有共享。第一版被用户反馈存在多处问题，不能据此认为换到画质版就修复了这些问题。

本次已成功加载并通过版本、参数与运行计数检查，实际功能等待逐项检查。边缘闪动仍是已知问题；开启识别可能降低处理帧率。

[本次运行记录](../../validation/edge-quality-30fps/board-demo-20261015/summary.json) · [本地源码依据](../../validation/edge-quality-30fps/board-demo-20261015/diagram-sources.json)
