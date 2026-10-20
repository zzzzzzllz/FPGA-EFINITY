# 2 RAM串行部分和：实施契约

冻结基线为现有 `weight_bank/rtl/weight_mac8.v`、`weight_bank8.v` 与 `mac8/rtl/mac8.v`，不改这三份RTL。新增两个512×16bit EFX_RAM10并联，提供单个512×32bit端口。地址为 `{slot[5:0], lane[2:0]}`；slot0…63均可用。16空间点×8lane占128字/512B。

先核对本机官方 `efx_ram10.v` 的同步读和RE/RST行为、已有权重bank的原语参数，并阅读[Titanium原语指南第22—27页](https://www.efinixinc.com/docs/efinity-quantum-ti-primitives-ug-v3.3.pdf)。沿用OUTPUT_REG=0的同步读；不依赖同地址读写碰撞。旧主干工作区已为部分和预留2 RAM，本次不增加第八个并行读端口。

## 冻结的接受、停顿和完成语义

- `save`/`restore`在IDLE且ce=1、权重读取已排空时接受，必须与write/issue/load互斥。pending读取未排空时拒绝新命令、报告错误，已有pending仍正常退休。
- 接受save的边沿N锁存slot，冻结MAC；后续8个ce有效边沿逐lane写入32bit。N+8后done=1、busy=0。部分和保持稳定，不增加整组快照寄存器。
- 接受restore后，每lane先用一拍同步读取32bit，再用一拍load回MAC。load时其余7lane反馈当前psum保持原值。共16个ce有效边沿完成8字，最后一次回填后done=1、busy=0。中间psum是部分恢复状态，调用方必须等done再使用。
- ce=0冻结状态、地址和core；done保持直到下一次ce有效边沿。错误为单个时钟脉冲。reset优先于ce，撤销进行中的操作及pending，清除MAC和完成标志；RAM内容不清。被reset中断的save槽无完整性保证，必须重新保存；先前完整保存的其他槽保留。
- busy期间的新命令被拒绝并报错，已接受的保存/恢复继续推进。不能在save期间改权重、改MAC或启动另一操作。
- 每组始终保存/恢复8个int32字，包括被mask关闭的lane。首次计算用load bias；第二段restore已有部分和，不重复加bias。
- 没有硬件槽有效位；只允许restore已经完成save的槽。协议不提供默认部分和。

最小实现复用现MAC的八lane seed端口，串行恢复一个lane时保持其他lane，避免新建256bit影子缓存。此处不实现DDR、DMA或层描述符。100MHz为SDC约束目标，map不等于时序通过。

## 运行与验证

仓库根目录执行：

```powershell
D:/Python/python.exe -B tools/blue_plate/whole_plate_budget/partial_sum/test_psum.py
powershell -File tools/blue_plate/whole_plate_budget/partial_sum/build.ps1
D:/Python/python.exe -B tools/blue_plate/whole_plate_budget/partial_sum/verify_synthesis.py
D:/Python/python.exe -B tools/blue_plate/whole_plate_budget/partial_sum/test_psum.py --mapped
```

RTL覆盖K=3328拆2048+1280；mapped采用K=12拆7+5的有界控制/串行存储回归，两者均覆盖64槽、停顿、复位、错误命令及16/8空间点×8/4有效lane。结果写入 `tmp/blue-plate-whole-plate-budget/partial-sum/`。

本机官方EFX_LUT4模型在输入从零时刻起保持0时可能不触发计算，输出停留在初始化值0。`--mapped`先生成本地仿真副本，只将显式输入敏感列表改成`always_comb`，并核对实际网表全部LUT掩码的初始化及四态真值表。未修改Efinity安装文件、硬件RTL或映射网表。初次失败证据保存在tmp的 `failure-2603/`；完整定位与验证见 `docs/validation/blue-plate/whole-plate-budget/partial-sum-implementation.md`。
