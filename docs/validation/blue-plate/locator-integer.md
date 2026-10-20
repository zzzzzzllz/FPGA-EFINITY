# 全帧定位整数化

2026-10-18。当前完成的是原蓝色掩码的整数等价参考，未更改`baseline.py`，未把定位器降级为包围框检测，也未完成全帧定位RTL。

## 实际研究材料

- [OpenCV 4.11.0 HSV源码](https://raw.githubusercontent.com/opencv/opencv/4.11.0/modules/imgproc/src/color_hsv.simd.hpp)：已读`RGB2HSV_b`的查表生成、最大通道分支、Q12乘法及舍入。
- [OpenCV 4.11.0直方图源码](https://raw.githubusercontent.com/opencv/opencv/4.11.0/modules/imgproc/src/histogram.cpp)：已读`equalizeHist`的首个非空bin、常量图、float32比例和累积乘法舍入。
- [LinkRunCCA源码](https://github.com/Topi-ab/linkruncca)：GitHub树API超时后，成功下载main归档。已读Verilog顶层、equivalence_resolver、table_reader、feature_accumulator、holes_filler、row_buf、table_ram及仿真输入生成代码。这里只研究实现，未执行仓库脚本/二进制或并入工程。

下载位于`tmp/blue-plate-normal-g1/locator-research/`。OpenCV两文件SHA分别为`bf819900ea530f6d04cdff0147eb3184edaa0c63babfbcd50b36d8319d7567f7`、`36a450f515c8bb3fe0203d3635942df543e2fb6e4baaf9a4aed91eb7977f12a7`。归档SHA及来源在`linkruncca-download.json`；它固定本次下载内容，不把可移动main名称当提交哈希。

## 蓝色掩码等价实现

现有门限为H=101..139、S=96..254、全帧均衡后的V=96..254。这个H范围意味着B严格大于R/G。令d=B-min(R,G)、z=R-G；根据OpenCV实际Q12倒数表和舍入反推，S门限可以转成以B索引的d上下界，H门限可以转成以d索引的z上下界。两表各256项，逐像素无需HSV乘除法。软件表和验证入口为`tools/blue_plate/blue_mask_integer.py`。

亮度均衡保留两次binary32舍入：先将255/N舍入成24位有效尾数，再将累积量乘尾数舍入成24位，最后最近偶数舍入到uint8。整数参考用整数尾数与二进制指数完成，不用一次有理数除法替代两次舍入。常量图仍保留原灰度值。

实测OpenCV版本为4.13.0；推导资料为4.11.0源码。验证结果位于`tmp/blue-plate-normal-g1/integer-blue-mask/report.json`：

| 检查 | 覆盖 | 差异 |
|---|---:|---:|
| H/S蓝色判断穷举 | 16777216种RGB，3086068种通过 | 0 |
| 亮度均衡 | 620组直方图、373788645像素；含256种常量、随机稀疏分布、两门限附近构造值 | 0 |
| 完整帧蓝色掩码 | 388帧、357580800像素 | 0 |

仅读取development/validation，112张heldout未读取图像或推理。完整掩码相同保证后续同一确定性定位代码输入不变；本次没有重新跑分类，也不声称解决现有248正确/6错/134拒识的准确率问题。

```powershell
D:\Python\python.exe -X utf8 tools/blue_plate/blue_mask_integer.py --frames
```

## 已在途的最小RTL验证

`locator/rtl/blue_hs_filter.v`实现H/S双表筛选，RGB24按R/G/B字节顺序，附同帧`value_allowed`。两级流水线，输出反压冻结全流水；rst/abort丢弃两级数据。外部仍须生成同帧亮度门限，这个模块没有把全帧均衡省略掉。

`locator/tests/run_blue_sim.py`使用OpenCV生成独立参考，全部16777216种RGB、10000个混合亮度允许位、2个复位恢复像素，共16787218次比较通过；包括随机式输入气泡、输出停顿、结果保持时取消和复位。记录`tmp/blue-plate-locator/blue-mask/simulation.json`，总25585930拍。独立Ti60F225 map为82 LUT4、21 FF、18 ADD、2 RAM10、0 DSP；未做PNR或整机接入。

主控已要求依据成熟整牌识别实测重新选择路线；本阶段完成上述在途检查后，暂停扩展依赖投影切分的实现。掩码等价与RTL通过不计作识别准确率改善。

## 连通域参考的适配边界

LinkRunCCA用行游程和Next/Head/Tail链表维护等价关系，特征表合并分量包围框；活动存储随图像宽度变化。读表有当前写入及合并转发，不能删掉这些旁路。原Verilog输出只有box，不能直接替代当前外轮廓、凸包、四点逼近及最小旋转矩形。

原代码还包含会置位背景像素的holes_filler；输出valid在输入datavalid=0时保持；行缓存没有复位清零；table_ram使用时序块内blocking和注册地址后的组合读。采用前需要独立验证8连通等价、边界填充、停顿、清空以及Efinity读写同址行为，不能仅凭README的单像素/拍声明直接接入。源码为LGPL-3.0-or-later，若实际采用需保留许可证及对应源码。

完整定位仍需全帧V直方图与同帧身份绑定、2×10闭运算、外轮廓/候选四角、蓝色覆盖率与排序，以及主定位无候选时的dual-local后备。16个既有候选的RGB包围范围超过reader单命令320×96限制，不能静默丢弃；已实现的2×2投影读取不受此限制。整机速度和资源需要将这些阶段与采集/显示DDR仲裁一起测量。
