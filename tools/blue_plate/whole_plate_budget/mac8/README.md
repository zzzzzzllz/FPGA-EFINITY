# 独立8路整数MAC

`rtl/mac8.v` 是第一块计算RTL：8个独立的signed17×signed8乘法，各自累加到int32，可整体装载部分和。没有网络权重、量化参数、权重bank、DDR或层调度。

## 算术与时序契约

- lane 0占总线最低位：activation每lane17bit二补码，范围−65536…65535；weight每lane8bit二补码，范围−128…127。uint16激活须零扩展到17bit，signed8激活须符号扩展。zero-point减法、缩放、截断和激活函数在单元外。
- 每个clk上升沿优先级：`rst`清空全部状态；否则`ce && load`装载8个int32 seed；否则`ce && valid`只对lane_mask中为1的lane执行`acc + activation × weight`。load优先于valid，不乘加，也不受mask限制。
- `ce=0`、`valid=0`或mask为0时，对应部分和保持。同步高有效reset优先于ce，停顿时也能复位。
- 结果在接受命令的上升沿后更新，无隐藏流水队列；连续有效时每lane每拍一项乘加。updated是该拍实际更新的lane位图；无操作或reset时为0。停顿保持psum，但updated和overflow清零。
- int32溢出时保存低32位并将该lane的overflow置1一拍；调用方必须据此判定该次运算无效，不能把回绕值当正常量化结果。load不会溢出。
- K分块由调用方控制：停算后读psum，切换权重，再load保存的int32部分和并继续。单元不计K，也不在块间重复加bias。初始bias通过首次load装入。

DSP只承担乘法，33bit加法与可重装的32bit累加寄存器在fabric。这样无需把专用CASCIN当作通用32bitseed总线；代价已由实际映射计入LUT/FF/ADD。

## 验证与构建

在仓库根运行：

```powershell
& D:/Python/python.exe -B tools/blue_plate/whole_plate_budget/mac8/test_mac8.py
& ./tools/blue_plate/whole_plate_budget/mac8/build.ps1
& D:/Python/python.exe -B tools/blue_plate/whole_plate_budget/mac8/test_mac8.py --mapped
```

测试使用Python整数独立生成逐拍golden，Icarus加载本机Efinity官方DSP/映射元件模型。输出都在 `tmp/blue-plate-whole-plate-budget/mac8/`。映射目标Ti60F225 I3，SDC周期10ns；map-only不产生布局布线时序结论。大宽度模块端口是内部接口，不是F225外部引脚分配方案。

实际查重读取主工程 `raw_edgeaware_area.v` 的EFX_DSP48实例，未发现符合本算术/部分和重装契约的现有MAC。读取官方本机 `efx_dsp48.v` 的signed乘法、可选寄存器和乘法直通路径，并查阅[Efinix DSP说明](https://www.efinixinc.com/blog/blog-2026-dsp.html)及[Titanium原语指南](https://www.efinixinc.com/docs/efinity-quantum-ti-primitives-ug-v3.3.pdf)。沿用项目的原语实例化及独立map工程方式，没有复制第三方加速器或执行下载脚本。
