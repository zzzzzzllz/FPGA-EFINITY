# 分区单 bit 同步字库：独立实现结果

2026-10-19。候选保留原32×32字体、面板位置/颜色、七槽、未识别/空格、非法ID钳位、异步复位与一拍RGB/DE/HS/VS输出。原 `plate_osd.v`、`plate_font.mem` 和字体assets未改。

**实际map达到9 RAM，较原模块减少7 RAM和352 LUT4。** 这项局部优化有效；没有据此宣布整机满足预算。

| 同配置独立map | RAM10 | LUT4 | FF | ADD | DSP |
|---|---:|---:|---:|---:|---:|
| 原plate_osd | 16 | 475 | 34 | 7 | 0 |
| plate_osd_compact | **9** | **123** | 38 | 9 | 0 |
| 差值 | **−7** | **−352** | +4 | +2 | 0 |

使用Efinity 2026.1.132.4.5、Ti60F225/I3、retiming=0、use-logic-for-small-rom=0、13.468ns时钟约束，仅运行map。原始报告分别为 `../plate-display/plate_osd.map.rpt` 和 `tmp/blue-plate-whole-plate-budget/font-compact/synthesis/out/plate_osd_compact.map.rpt`。没有PNR或74.25MHz时序闭合结论，LUT/FF没有相加成XLR。

## 实现与初始化核对

已有调研见[静态候选与共享分析](font-and-sharing-followup.md)。读取原ROM的单个像素时，column从行读取之后的32选1移动到ROM地址中：ID0–63存为65536×1，ID64–67存为4096×1，ID68空格为零。两个ROM同步读取，bank/blank标志同拍寄存，与原视频控制保持对齐。任意坐标跳变都不依赖预取下一个像素。

网表实际有8个font_low RAM和1个font_high RAM，均READ_WIDTH=WRITE_WIDTH=1、OUTPUT_REG=0、RESET_RAM=ASYNC。逐块解析40个INIT参数，8个低区8192bit块与生成输入精确匹配，高区4096bit与原末4字形精确匹配，未用bit为零；不是只核对非零bit数。所有18,411个墨迹bit完整保留。

无需32bit分区备选，未继续扩大搜索或改缓存所有权。

## 周期行为验证

原RTL、候选RTL/映射网表及独立坐标/字体参考同时比较。RTL与mapped各通过 **981,712周期、58次复位检查**，RGB和DE/HS/VS逐周期一致：

- 全128输入ID × 7槽 × 32行 × 32列，共917,504像素。相邻槽放不同ID，检查槽位寻址和非法ID钳位。
- 未确认状态224×32区域，共7,168像素，覆盖“未识别”三字与两侧空格。
- 面板及外边界逐点分别测试de=0/1，共27,040周期。
- 30,000次确定性随机坐标/输入包跳变，含完整11bit坐标域及定向文字区，逐周期改变valid、字形、RGB与同步信号。
- 29次非时钟沿异步复位，每次检查立即清零和保持复位时清零；释放后继续比较，输出没有增加一拍。

mapped仿真沿用先前已研究的vendor LUT启动问题修正：只在本候选tmp中复制 `efx_lut4.v`，将显式输入敏感列表改成always_comb，工具安装与网表不改。对本网表全部LUT mask重新做time-zero及0/1/X/Z真值表检查；实际mask数和检查数在 `font-compact-validation.json`。因此mapped结果明确以该局部仿真模型为条件。RAM使用原厂模型。

## 剩余缺口与交付

在旧独立模块账本上替换这7块RAM，232→225，仍超204预算 **21 RAM**；完整51-bank计划264→257，仍超 **53 RAM**。这是单项差值代入，尚未重新映射完整plate_display或整机。geometry的9,687 LUT4、4,730 FF、4,300 ADD以及新定位/调度资源仍需解决；原release余92 XLR的事实不变。旧预算数据保持冻结。

入口：[候选源码/复现说明](../../../../tools/blue_plate/whole_plate_budget/font_compact/README.md)。验证汇总：[font-compact-validation.json](font-compact-validation.json)。完整源码、输入、日志、网表和报告哈希冻结于 `tmp/blue-plate-whole-plate-budget/font-compact/delivery-freeze.json`。scalar-read 31项和static-Q 17项冻结证据重新核对，没有重跑其长测试。

本次只新增独占目录的候选、测试和报告；没有接产品、改字体/TTL/页面/预算、运行整机PNR或操作板卡。
