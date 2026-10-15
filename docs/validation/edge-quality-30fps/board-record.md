> 历史技术记录。仅说明记录时的版本；当前操作与状态以 [使用指南](../../../docs/for-reader/usage.md) 为准。文中旧路径用于溯源，不是当前运行入口。

# 上板记录

2026-10-14，经用户授权，将已通过离线验收的`../resource2/outflow/ti60f225_oob.bit`通过JTAG加载到Ti60F225的SRAM。下载成功，器件ID为`0x10660A79`，运行构建编号为`0x6010100f`。用户确认画面正常，能够跟随物体移动。

当前保留实时灰度/边缘对比、Canny高低阈值24/12、中值关闭、识别关闭。白平衡为389/256/427，Gamma关闭，BGGR。未写入Flash，断电后运行本目录的`load.cmd`重新加载。

## 板上检查

- 彩色视图、Sobel/Canny切换、实际显示参数、冻结与恢复实时全部通过。
- 连续61.406秒：采集和处理各1842帧，均为29.997fps；显示3683帧，为59.978Hz。
- 观察期间采集错误、MIPI异常、显示欠载、算法过载、混帧、处理失败、总线错误、结果溢出和跳帧均无新增。
- 首次读回的累计显示欠载为194，不能称为上电以来零欠载；本次稳定运行窗口内该值不变。
- 本轮未重新做识别准确率、32帧录放或全部实物按键验收。离线完整回归仍对应父目录冻结的`acceptance.json`。

详细采样及位流哈希见`verification.json`（历史路径：`verification.json`），下载日志见`program.log`（历史路径：`program.log`）。已冻结的离线报告保留当时“未上板”的状态，上板结果单独记在本目录。

## 使用

双击`load.cmd`可恢复本次画质预设。在线控制使用本目录`camera-control.cmd --edge`，其构建编号、profile及状态布局对应本次候选；原工程入口保留。

```bat
camera-control.cmd --edge --view compare
camera-control.cmd --edge --view color
camera-control.cmd --edge --view overlay
camera-control.cmd --edge --frame freeze
camera-control.cmd --edge --frame live
```

下载前的原板上程序调试UUID不匹配，未能读取其运行配置。下载后旧控制脚本因仅接受`0x6010100a`拒绝读取，未写入参数；本目录控制脚本沿用原工具，仅适配本候选路径和`0x6010100f`，随后完成设置和验证。
