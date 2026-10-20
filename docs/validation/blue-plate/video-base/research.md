# 视频底座取舍与来源

日期：2026-10-18。本子任务只验证独立彩色视频构建，不接入字符识别，不上板。

读取了根 README、车牌设计及 G1 帧接口约束，以及原工程 `tools/build-project.ps1`、`tools/check-edge-build.ps1`、`tools/verify-project.py`、XML/SDC、顶层、`frame_store`、`frame_store_control`、`frame_store_dma`、`edge_algorithm_pair`、`compare_display`、`threshold_osd` 和现有帧存储/HDMI 测试。原构建会清理 `tmp/build/<工程名>`，本候选不调用该入口。

外部检索关键词：Efinity synthesis Verilog generate parameter unused logic；本地检索 SDK generate/FIFO 和综合/CLI 文档。实际参考：

- [Efinity Synthesis User Guide v4.4](https://www.efinixinc.com/docs/efinity-synthesis-v4.4.pdf)：读取综合选项、SystemVerilog generate 支持和网表导出章节。下载副本位于 `tmp/blue-plate-video-base/research/efinity-synthesis-v4.4.pdf`。据此使用原有参数裁剪，保留综合后网表检查；不采用 OOC 黑盒拼接估算整机。
- 本机 Efinity 2026.1 的 `D:/Efinity/doc/topics/cli-run-flow.html`、`cli-map-opts.html`：读取 map/interface/pnr/compile 分阶段入口；提取文本保存在同一 research 目录。实际命令也经 `efx_run.bat --help` 核对。
- 已有 Efinix FIFO 源码 `rtl/ddr3_controller/common/efx_fifo_v2.3/efx_fifo_wrapper.v`：读取参数定义和 Gray 指针 generate，实现按宽度展开的厂商 FIFO。保留版权头的研究副本在 research 目录。候选继续复用原 DDR/CDC 实现。
- 已有 `frame_store.v` 的 `ENABLE_CANNY/ENABLE_SHAPE` generate 是最直接的裁剪入口；`edge_algorithm_pair` 中 median/Gaussian/Sobel/NMS 即使运行时选择彩色仍会实例化，因此还需替换该处理核。

候选比较：

| 候选 | 机制 | 用途 |
|---|---|---|
| gates | 仅将顶层 Canny/shape 参数设为 0 | 测量参数开关的真实效果；仍有演示与历史控制，不作为专用底座 |
| live | gates 加固定彩色控制、关闭历史命令入口、RGB/元数据直通、移除菜单绘制 | 本次底座；保留原采集、画质、DDR、结果帧发布和 HDMI 握手 |

采用 live，因为仅切 generate 不会裁掉像素边缘核，也不能阻止历史操作。保留 raw→job→result→display 的实时临时帧复制，避免改写 DMA、显示描述符和帧回收协议。下一阶段识别必须另建帧持有/读取调度，不能用识别 `done` 代替这个视频复制 job 的完成。

目标指标：实际 RAM/DSP/逻辑占用下降，XLR≤49248、RAM≤204、DSP≤128；变化彩色帧逐像素一致，AXI/显示停顿下换帧正常，布局布线后时序满足原约束。分类器和剩余算法预算独立列示，整机仍需重新综合。
