# 第一块硬件：独立8路整数MAC

2026-10-18。已在独占目录实现 [mac8.v](../../../../tools/blue_plate/whole_plate_budget/mac8/rtl/mac8.v)，并完成独立Ti60F225 I3映射。没有接入共享顶层、显示、DDR或板卡，也未嵌入模型权重或量化参数。

## 已实现的算术

8路各自输入signed17 activation和signed8 weight，累加到可重装int32部分和。17bit可同时表达中心化的8bit输入及零扩展的uint16池化和。每lane独立输入支持depthwise；将相同activation送各lane即可做普通卷积广播。K=3328由调用方在2048项后保存int32，再load恢复并完成剩余1280项。

同步reset优先于ce；load优先于valid，装载全部8个seed且不乘加；普通MAC仅更新mask为1的lane。停顿保持部分和，updated/overflow是每拍脉冲。溢出保存低32位并显式报告，调用方须判定该运算无效。详细位序、数值范围、优先级与复现命令见 [mac8/README.md](../../../../tools/blue_plate/whole_plate_budget/mac8/README.md)。

先查重读取主工程 `raw_edgeaware_area.v` 的DSP实例，再核对本机官方 `efx_dsp48.v` 的signed乘法及寄存器路径，查阅[Efinix DSP说明](https://www.efinixinc.com/blog/blog-2026-dsp.html)和[Titanium原语指南](https://www.efinixinc.com/docs/efinity-quantum-ti-primitives-ug-v3.3.pdf)。采用8个EFX_DSP48组合乘法，fabric完成33bit加法、int32保存和seed装载，避免把专用CASCIN假设为通用32bit输入。

## 实测映射

| 资源 | 实际数量 |
|---|---:|
| EFX_DSP48 | **8** |
| EFX_LUT4 | **282** |
| EFX_FF | **272** |
| EFX_ADD | **264** |
| RAM10 | **0** |

证据在 `tmp/blue-plate-whole-plate-budget/mac8/synthesis/`：`out/mac8.map.rpt`、`out/mac8.map.v`、`map.console.log`与`synthesis-summary.json`。输入源码复制、SDC哈希及Efinity重写XML前后语义均已核对。

SDC设定10.000ns时钟，数据及控制端口输入/输出延迟均为0ns。**这里只完成map，尚无布局布线STA、Fmax或100MHz通过证据。** 469输入bit/272输出bit是内部模块边界，不是F225外部引脚分配；下一阶段集成时需真实上下游寄存器和延迟预算。8 DSP/0 RAM不代表整个51 RAM引擎或196 RAM系统已完成。

首轮map发现未启用内部寄存器却连接了DSP时钟，VDB-9038拒绝。已按组合原语要求将CLK/CE/RST绑0，重新跑RTL回归及map通过。首次错误与源码保存在 `mac8/first-map-error/`；Efinity的err/warn文件会累加历史，当前PASS以独立console、最新map.rpt及哈希回执为准。

## 验证范围

Python任意精度整数生成逐拍golden，RTL加载官方Efinity模型。共**12,938周期、103,504个lane状态检查**，实际执行71,923个lane MAC，覆盖31次复位、151次load、978次ce停顿及26个溢出lane事件。

定向覆盖signed17/signed8正负端点、0、uint16上界65535、mask单lane/交错/四尾lane、load与valid冲突、停顿期间load无效、停顿中reset有效，以及K=3328中间部分和保存后故意覆盖再恢复。K分块使用8个和4个有效lane；结果与不分块的独立整数点积一致。随机控制序列作为补充，不代替极值与块边界检查。

RTL回执为 `tmp/blue-plate-whole-plate-budget/mac8/rtl-validation.json`。映射后网表也使用同一逐拍golden复核，最终状态及哈希记录在本目录 `mac8-validation.json`。本测试不含网络精度、量化scale、权重bank端口或DDR调度。

当前交付范围止于计算单元，后续权重bank、完整层调度和DDR接入等待主控审核。颜色CNN补账及16路备选分别见 [color-cnn-sharing.md](color-cnn-sharing.md)、[lane16-comparison.md](lane16-comparison.md)；8路基线继续保留。
