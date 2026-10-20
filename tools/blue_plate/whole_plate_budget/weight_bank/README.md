# 16KiB权重bank与8路MAC联调

`weight_bank8.v` 用16个EFX_RAM10实现2048×64bit：4个深度组，每组4个512×16bit银行。每次读出8个signed8权重，lane0为最低字节；bank仅保存位，不改变符号。`weight_mac8.v` 加一拍activation/mask对齐，连接已冻结的8路MAC。

## 接口契约

- `ce=1`的上升沿接受命令；同步高有效`rst`优先，清除pending、输出有效和MAC状态。RAM内容不清除；每次使用前必须写好所读地址，未提供“未加载权重”的硬件检查或默认权重。
- 单个写命令`wr_en`把64bit写入一个地址。单个`issue`发出同步权重读取，并保存本次activation及lane_mask。地址高2bit选择深度组，低9bit选择行。
- 在边沿N接受issue，权重和read_valid在N后更新；在下一个`ce=1`边沿MAC消费该权重及配套activation/mask。可以同时接受下一次issue，因此连续运行时每拍完成一个8lane MAC步骤。
- `ce=0`同时停止bank、对齐寄存器和MAC。pending/read_valid及权重保持，MAC不会重复消费。恢复后先消费原pending，同时可接受下一次issue。
- `issue=0, ce=1`空拍排空上一笔读取；随后read_valid=0。最后一项issue后至少排空一次，才可读取最终psum、load部分和或切换权重。
- `wr_en`、`issue`、`load`必须互斥；read_valid=1时禁止新write/load。冲突时command_error置1一拍，拒绝本拍新命令；原先pending的有效MAC仍正常退休。错误时不偷偷覆盖权重或部分和。
- `load`沿用MAC契约：装载全部8个int32 seed，不乘加。尾lane由mask关闭，其原部分和保持，不要求对应权重恰好为0。
- bank单独使用时也拒绝同拍读写，并输出conflict；它不依赖RAM同地址读写的行为。wrapper进一步要求权重切换前排空计算。

K3328示例：写入2048个64bit权重行 → load bias → issue 2048项 → 排空并保存psum → 写入剩余1280行到地址0…1279 → load保存的psum → issue 1280项 → 排空。没有第二套bank，也没有假设装载权重时还能计算。

## 参考与验证

已读取本机官方 `D:/Efinity/sim_models/verilog/efx_ram10.v` 的同步读、RE/RADDREN、输出reset和读写碰撞行为，并核对[Titanium原语指南第24—27页](https://www.efinixinc.com/docs/efinity-quantum-ti-primitives-ug-v3.3.pdf)。查重读取已有 `char_model/rtl/char_linear.v`，其同步ROM是固定分类权重，不能直接提供本可重装64bit银行。采用明确的16个原语实例，实际map检查每个READ/WRITE_WIDTH=16、OUTPUT_REG=0。

在仓库根运行：

```powershell
& D:/Python/python.exe -B tools/blue_plate/whole_plate_budget/weight_bank/test_weight_mac8.py
& ./tools/blue_plate/whole_plate_budget/weight_bank/build.ps1
& D:/Python/python.exe -B tools/blue_plate/whole_plate_budget/weight_bank/test_weight_mac8.py --mapped
```

产物在 `tmp/blue-plate-whole-plate-budget/weight-bank/`。输入是合成固定权重与整数golden，不含网络量化参数。这里只接通同步读取与MAC，不含DDR接口、描述符、层控制器或主工程接入。map使用10ns约束，尚无布局布线时序结论。
