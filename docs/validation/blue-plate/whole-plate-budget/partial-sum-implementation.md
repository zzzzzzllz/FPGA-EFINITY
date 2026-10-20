# 2 RAM串行部分和：实现与验证

2026-10-18。新增独立 `psum_weight_mac8`，连接已冻结的16 RAM权重bank和8 DSP MAC。**map合计18 RAM、8 DSP、908 LUT4、433 FF、264 ADD；部分和增量为2 RAM、0 DSP、461 LUT4、13 FF。** 两个512×16 RAM并联成512×32bit串行端口，16空间点×8输出只占128字/512B。没有增加256bit影子缓存，也没有宣称8个并行RAM读端口。

本次仍在共享引擎原有2 RAM部分和分配内；它只验证独立模块，不代表整机49,248 XLR / 204 RAM10 / 128物理DSP已完成布局。100MHz仅为SDC约束，尚无PNR/STA通过结果。

## 契约与实现

地址是 `{slot[5:0], lane[2:0]}`。仅在IDLE、ce=1且权重读取已排空时接受互斥的save/restore。save接受后，用8个有效边沿依次保存8个int32；restore用每lane一拍同步读取、一拍回填，共16个有效边沿。回填时另外7个MAC累加值反馈保持，最后一lane完成才释放busy、置done。

ce=0冻结内部操作和done。reset优先于ce，清除控制、MAC和pending，不清RAM；被中断的save槽必须重存。busy期间的新命令报错，当前操作继续。尚未排空的MAC结果仍正常退休，同时拒绝新save/restore。只允许恢复完整保存的槽，没有默认值或有效槽位图。即使尾块只有4个有效输出，仍保存8字，关闭lane保持原bias。第二K段恢复第一段结果，bias不重复装载。

实现前实际读取本机 `efx_ram10.v`、现有bank及MAC源码，并核对[官方Titanium原语指南](https://www.efinixinc.com/docs/efinity-quantum-ti-primitives-ug-v3.3.pdf)中的同步读、OUTPUT_REG和reset语义。采用OUTPUT_REG=0的已有同步读写方式，不使用读写碰撞行为。文件与端口契约见 [partial_sum/README.md](../../../../tools/blue_plate/whole_plate_budget/partial_sum/README.md)。

## 验证范围

| 检查 | 结果与覆盖 |
|---|---|
| RTL完整K | 178,888周期、1,431,104项逐lane状态检查；四组16/8空间点×8/4有效lane均使用K3328=2048+1280。 |
| mapped有界回归 | 5,640周期、45,120项逐lane状态检查；同四种空间/尾块组合采用K12=7+5，验证新增串行存储和控制。 |
| 容量与切换 | 64槽覆盖全部512个物理字地址；每组先计算所有空间点并save，覆写权重bank，逆序restore各点后续算。 |
| 协议 | 114次save、114次restore完成，6次预期错误、4次reset；包含ce停顿、done保持、pending未排空、busy冲突、save/restore中断及其他完整槽保留。 |
| map结构 | 检查18个实际RAM实例的宽度/OUTPUT_REG/模式，其中2个属于partial_ram；8 DSP保持不变。源码副本、XML语义、map输入和冻结源码SHA均核对。 |

整数golden独立维护权重、部分和RAM、MAC和控制状态，每个时钟比较psum、updated、overflow、busy、done、command_error与pending。四组最终共384个输出值（含mask关闭lane）精确相等。数据为合成向量；没有把软件“8个K项横向求和”的真实向量直接接到硬件“8个输出通道”端口。

## 初次mapped失败及定位

初次运行在cycle2603恢复slot0 lane0时失败：预期`00000000`，实际`ff163040`。失败源码、网表、向量、日志与map目录完整保留在 `tmp/blue-plate-whole-plate-budget/partial-sum/failure-2603/`。后续没有重新map，也没有修改该硬件RTL或网表。

将初次save与末尾restore抽出为42周期用例，在其cycle20复现同一错误。端口追踪显示原始psum[31:0]=0、地址0、WE=11时，写数据已经是`ff163040`；读端随后返回相同值。错误出现在写数据选择器路径，并非RAM地址、读延迟或回填mux误配。

检查稳定LUT输入发现，例如LUT__5925的输入为0000、LUTMASK为0777，输出却为0；真值表应为1。官方模型以`lut=0`初始化，仅在显式输入敏感列表触发时计算，部分输入从仿真启动起保持0，因此没有执行首次计算。独立单LUT用例中，恒定0输入得到错误0；输入翻转再回0后得到正确1。这个证据独立于部分和设计。

`lut_startup.py`只在tmp生成本地EFX_LUT4副本，把显式敏感列表改为SystemVerilog `always_comb`以执行首次计算；函数、掩码、端口、弱默认驱动等均保留。使用该副本后，42周期复现用例及完整5,640周期有界mapped回归通过。另以独立表值计算验证网表60种不同掩码：每种1项启动检查及256种0/1/X/Z输入，共15,420项全部通过。X输入按可能表项是否一致确定，未连接/Z按原模型弱0处理。

这是**使用局部仿真模型初始化修正后的mapped通过结果**，不是未修改厂商模型下通过。原Efinity安装文件、DSP/RAM/FF模型、硬件源码、网表均不变。证据包括 `audit.log`、`probe.sv`、`probe-vectors.txt`、`probe-fixed.log`、`lut-startup.sv`、`lut-stock.log`、`lut-fixed.log`、`lut-startup-validation.json`。

## 可复核记录

- [partial-sum-validation.json](partial-sum-validation.json)：资源、范围、最终文件哈希。
- [partial-sum-rtl-validation.json](partial-sum-rtl-validation.json)：完整K RTL结果。
- [partial-sum-mapped-validation.json](partial-sum-mapped-validation.json)：有界mapped结果与本地模型哈希。
- [partial-sum-lut-validation.json](partial-sum-lut-validation.json)：初始化与四态表值检查。
- [quantization-fork-budget.md](quantization-fork-budget.md)：双消费者分叉容量及尚缺的算术接口。

首轮验收按受控摄像头、清晰完整无遮挡的单普通蓝牌推进；遮挡研究不阻塞本模块。此次未接入主顶层、DDR、真实模型或板卡。
