> 历史技术记录。仅说明记录时的版本；当前操作与状态以 [使用指南](../../../docs/for-reader/usage.md) 为准。文中旧路径用于溯源，不是当前运行入口。

# 自然细节保护与冗余边缘清理

已通过完整离线验收：画质、独立新图、整机资源、时序、七组56条回归命令及最终资源实现的720p完整链路补跑全部通过。验收记录为`acceptance.json`（历史路径：`acceptance.json`）。未上板。

36张照片完整对照（历史路径：`comparison.html`） · 四组局部放大（历史路径：`comparison-overview.png`） · 逐图数据（历史路径：`results.json`）

## 实际结果

| 图集 | 误删前边缘点 | 本轮减少的冗余点 | 边界召回 |
|---|---:|---:|---|
| 原12张开发照片 | 477052 | 2625（0.550%） | 每张恢复到误删前基准 |
| 另外24张未见照片 | 996703 | 5408（0.543%） | 每张与误删前基准相同 |

全部照片的完整1像素覆盖与8邻域连通分量均保持不变。640帧合成图共去掉7个冗余点，细线、圆弧及其他图案的覆盖和连接不下降，其中细线/圆弧检查400帧。

本轮的删除幅度比上一轮小，保留细节优先。上一轮“新合成图杂边减少30.05%”不再适用于本轮。这里报告的是冗余边缘点，不把真实纹理中未标注的边缘全部称作噪声。新照片的标注外边缘密度均值从22.5135%降到22.3756%，这不是传感器噪声率。

照片来自[Berkeley BSDS500测试集](https://www2.eecs.berkeley.edu/Research/Projects/CS/vision/grouping/resources.html)。最终24张在排除此前开发及试验批次的60张后，按路径哈希排序选择，清单在`heldout/manifest.json`。模型冻结后才评分，之后没有调参。RGB照片转换为灰度验证后级；合成RAW10经过EA前端。沿用原来的8像素有效区排除和1像素欧氏距离容差，不是官方BSDS榜单指标。

图库同时展示`quality_integrated`误删前基准、`quality_clean`上一轮和本轮输出。全部图片保留，最近邻放大，未美化、补线或生成图片。局部图选择依据记录在`overview-crops.json`。

## 修复方法

取消上一轮按梯度强弱直接清零斜向边缘的规则，在NMS分类之后增加3×3局部检查。只有强邻边满足以下条件才删除中心冗余点：覆盖中心的1像素十字邻域、强邻边互相连接、每个可能的弱邻点都能到达强邻边。

只处理横纵坐标均为偶数的点，因此它的八个支撑邻点都不会被同时删除。256种强邻点分布中有64种满足保护条件。9像素外圈不删除，使原8像素评分有效区的边缘也保留完整支撑。删除后不会切断弱边到强种子的路径，也不改变1像素覆盖。

“保留细节”指上述覆盖、连接性质与本批逐图结果；边缘图像素数会减少，不能把它理解为逐像素完全相同或已经消除全部自然纹理边。

## 硬件实现

最终整机在`resource2/`，基于上一轮已验收的`quality_clean/resource7/`，改动`rtl/canny_nms_pair.v`和`rtl/edge_algorithm_pair.v`。清理模块`edge_cleanup_pair`放在NMS文件末尾，后者将它接入流水线。单独的`edge_cleanup_pair.v`是生成源，不另行加入XML。

`project/`保存首次冻结的查表实现，整机48843 XLR未达到资源要求；`resource2/`仅把同一真值表改写为等价布尔表达式，整机降至48532 XLR。301510组穷举和连续帧验证重新检查了该改写，全部通过，其他200项构建输入与`project/`逐文件相同。改变综合重定时设置的`resource3/`、`resource4/`未达到逻辑余量门槛，不采用。

| 资源 | 最终占用 / 总量 | 剩余 |
|---|---:|---:|
| XLR | 48532 / 60800 | 20.178% |
| RAM块 | 189 / 256 | 26.172% |
| DSP | 127 / 160 | 20.625% |
| DDR | 140.25 / 256 MiB | 45.215% |

布局布线后全部报告时钟关系通过：最小建立余量0.377ns、保持余量0.026ns。已离线生成位流，未加载。资源及报告哈希见`build-verification.json`。

模块使用行缓存，不增加整帧缓存或DDR扫描；增加一行及流水寄存器延迟。RGB采用52位双像素状态/颜色打包，帧号、配置保持到上一帧输出完成，帧尾交接增加一拍保护。连续帧验证包含Canny/Sobel切换、RGB、帧号、配置及输入/输出暂停。

EA前端、精确中值、Gaussian列复用、低阈值移位加法和原24/12画质参数保留；配置字仍为`0x6018`（Canny、中值关闭）。上电默认设置沿用原工程，未在线设置、未加载。

## 验证与复现

局部检查穷举301510组状态窗口，覆盖全部合法邻域及旁路编码；另有300组随机状态场检查覆盖、连接和弱边传播不变。连续流检查4帧720p及两组小图各8帧。148张RAW与自然照片共7615232像素的RTL核对通过，完整Canny链路在32/16及24/12参数分别验证。最终`resource2/`又单独通过一次24/12完整720p链路，包含DDR、识别、每个输出像素、帧信息、结果发布及AXI暂停，记录为`final-canny.json`。

帧操作和三个显示回归只在编译源码及测试台逐文件哈希一致后复用既有完整结果，绑定记录为`reused-regressions.json`。新增/改变链路及识别测试重新运行。复用的帧操作检查10帧720p显示，三种显示分别检查3帧720p；32帧录放在小尺寸完整功能回归覆盖。

自然照片RTL仿真右侧复制到64像素宽倍数，并使用4KiB对齐的DDR状态区，以符合现有扫描器约束。全部扩展图的RTL像素都与对应模型比较。因9像素保护圈随帧宽变化，原图与扩展图另在距原边界至少10像素的区域核对一致；画质评分始终基于原尺寸图及原8像素规则。

在本目录执行（Python使用`D:/Python/python.exe`）：

```powershell
python -B evaluate.py
python -B verify_rules.py
python -B verify_stream.py
python -B verify_rtl.py
python -B regression.py small
python -B regression.py full --resume --store-only
python -B regression.py quality_full
python -B regression.py shape
python -B verify_resource2.py
python -B final_canny.py
Push-Location resource2
& D:/Efinity/bin/efx_run.bat ti60f225_oob.xml --flow compile
Pop-Location
python -B check_build.py
& ../../../tools/check-edge-build.ps1 -ReportPath resource2/outflow/ti60f225_oob.map.rpt
python -B finalize.py
```

`prepare.py`与`freeze.py`只用于首次初始化，拒绝覆盖已存在的目录。早期试验`quality_detail`及本目录第一次边界检查失败记录保留，未列为最终通过证据。最终24张不含这些试验图片。
