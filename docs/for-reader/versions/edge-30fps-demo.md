# 第一版上板导览

[按键、画面与架构思维导图](../../../tools/archify/edge-30fps-guide-20261015/guide.html)

当前演示的是原完整边缘版edge-30fps，构建ID为0x6010100a。加载后默认实时COMPARE、Sobel、阈值32、中值开、识别关，恢复配套约20ms曝光。本次先检查这一版，画质版与60帧版随后分别加载。

## 按键

| 按键 | 作用 |
|---|---|
| KEY1短按 | 下一菜单；在FRAME中则执行选中动作并回到VIEW |
| KEY1长按约0.8秒 | 实时／录制时冻结；冻结／回放时返回实时 |
| KEY2 / KEY3 | 当前项减／加、关／开或上一个／下一个 |
| KEY0 | 系统复位；演示无需按，录制和参考帧会丢失 |

菜单顺序：VIEW → ALGORITHM → THRESHOLD → LOW RATIO → MEDIAN → RECOGNITION → FRAME → VIEW。Sobel模式自动跳过LOW RATIO。以屏幕底部菜单为准，不靠累计按键次数寻找功能。

## 建议检查顺序

1. 在初始VIEW COMPARE观察左右同帧对比。KEY2切EDGE，再按一次切GRAY；KEY3反向返回。COLOR在循环中，但本次不用专门检查。
2. 到ALGORITHM，KEY2选择Sobel、KEY3选择Canny，观察线条与细节差异。
3. 长按KEY1冻结同一原帧；到THRESHOLD，KEY2减16、KEY3加16。长按阈值键约0.5秒后开始连调；Canny最低为1，Sobel最低为0，上限2040。
4. Canny下的LOW RATIO可选1/4、1/2、3/4。比例较小允许更多连接到强边的弱边保留。
5. 在MEDIAN用KEY2关闭、KEY3开启。再到VIEW的DENOISE看左原灰度、右滤波灰度。OVERLAY会在彩色图上叠红边。
6. RECOGNITION用KEY3开启，观察圆／矩形分类和框，最多4个目标；处理帧率可能下降。KEY2关闭。[打印测试图](../test-targets/m10-camera-test-targets.pdf)可用于摆放目标。
7. 在FRAME用KEY2／KEY3选动作，再短按KEY1执行。完成后用LIVE或长按KEY1返回实时。

| FRAME动作 | 执行后的效果 |
|---|---|
| CANCEL | 不做操作，退出菜单 |
| STEP LIVE | 从摄像头采一张新帧，随后冻结 |
| RECORD 32 | 覆盖旧片段并录32帧，录满停在首帧 |
| PLAY LOOP | 循环播放已录片段，须先录制 |
| PAUSE | 停在当前显示帧 |
| NEXT CLIP | 前进到已录片段的下一帧，须先录制 |
| SET REF | 保存当前显示原帧为参考 |
| LIVE | 回到实时 |
| CLEAR REF | 清除参考帧 |

参考对比：先SET REF，再回VIEW选择REFERENCE，画面左侧是参考灰度、右侧是当前灰度。没有参考时，VIEW会跳过REFERENCE。STEP LIVE采新画面，NEXT CLIP翻已有片段，二者不同。

## 项目架构

SC431HAI采集 → raw_full_view颜色恢复 → RGB与灰度 → DDR保存原帧 → 帧管理器选择原帧 → Sobel/Canny及可选识别 → 发布完整结果 → compare_display合成画面 → threshold_osd叠菜单与框 → HDMI。

实时、冻结和回放共用算法路径。按键由edge_ui解释，threshold_control管理阈值；电脑JTAG入口可控制同类参数。曝光设置使用电脑控制入口，没有板载曝光菜单。

导图根据本地Git提交7965d09中的RTL绘制。项目没有远程仓库，因此本地源码行号单独记录在[图示依据](../../validation/edge-30fps/board-demo-20261015/diagram-sources.json)，不虚构在线仓库链接。
