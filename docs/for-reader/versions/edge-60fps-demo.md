# 第三版上板导览

[操作、效果与架构思维导图](../../../tools/archify/edge-60fps-guide-20261015/guide.html)

本次加载edge-60fps，构建ID为`0x60101065`，约10ms曝光。已切到全屏Sobel边缘：预期是黑底白色轮廓，阈值固定64。当前保持这一模式供检查。

这版没有按键菜单。KEY1／KEY2／KEY3不切换功能；KEY0仅复位。画面通过电脑命令切换，在项目根运行：

| 命令 | 预期画面 |
|---|---|
| `.\coding\edge-60fps\control.cmd --view edge` | 全屏Sobel黑底白边，当前模式 |
| `.\coding\edge-60fps\control.cmd --view gray` | 全屏灰度，保留明暗层次 |
| `.\coding\edge-60fps\control.cmd --view color` | 恢复彩色，本次跳过原图演示 |
| `.\coding\edge-60fps\control.cmd --samples 5` | 只读取状态，不切换视图 |

先在当前Sobel画面下移动物体，看轮廓是否连续、是否有噪点或瞬间黑屏；再切灰度观察亮度细节。这版不支持Canny、可调阈值菜单、中值开关、冻结、32帧录放、识别、左右对比或边缘叠加。

实际图像链为：SC431HAI的1920×1080中央裁切输入 → MIPI → 双线性颜色恢复 → 3:2面积缩放至1280×720 → 灰度和Sobel → DDR三帧缓冲 → HDMI。DDR缓冲服务于连续显示，不是录放功能。`control.py`通过JTAG控制显示模式及颜色参数。

工程XML选择的前端是`raw_1080_to_720.v`，其模块名为`raw_full_view`；同目录旧文件`raw_full_view.v`未参与本工程构建，不能据它判断当前处理流程。

本次加载及Sobel切换成功，边缘模式采样约59.6fps；版本、曝光寄存器和显示模式回读正确。采样期间错误及欠载计数无新增。偶发黑屏仍是已知问题，短时计数正常不代表已修复；画面与功能等待本轮人工检查。

[本次运行记录](../../validation/edge-60fps/board-demo-20261015/summary.json) · [本地源码依据](../../validation/edge-60fps/board-demo-20261015/diagram-sources.json)
