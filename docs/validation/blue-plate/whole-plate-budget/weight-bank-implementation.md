# 第二块硬件：16KiB权重bank及8路MAC联调

2026-10-18。在第一块MAC完整映射后回归通过、冻结源码SHA保持不变后，按主控授权实现 [weight_bank8.v](../../../../tools/blue_plate/whole_plate_budget/weight_bank/rtl/weight_bank8.v) 与 [weight_mac8.v](../../../../tools/blue_plate/whole_plate_budget/weight_bank/rtl/weight_mac8.v)。使用原有16 RAM预算，不复制MAC、不增加第二组权重缓存。

## 实际组织与时序

16个EFX_RAM10按4深度组×4宽度银行组织，每块512×16bit，合计2048×64bit=16,384B。16个物理实例的READ_WIDTH/WRITE_WIDTH均为16，OUTPUT_REG均为0，端口配置由映射网表逐个核对。OUTPUT_REG=0仍是同步RAM读取，不是异步ROM。

边沿N接受读取并保存activation/mask，N之后权重与read_valid有效；下一个ce有效边沿完成对应MAC。停顿冻结整个待消费项；连续发issue时每拍消费一项。末项之后一个ce有效空拍排空，再保存部分和、装载另一段权重或load。写入与issue/load冲突、新write/load遇到pending时明确拒绝并报告command_error，已有pending仍可正常完成。

K=3328按2048+1280在同一bank重装，int32部分和在两段间保存和恢复；load bias只在首段进行。尾4lane测试使用非零高lane权重，确认mask真正屏蔽MAC。完整接口与调用顺序见 [weight_bank/README.md](../../../../tools/blue_plate/whole_plate_budget/weight_bank/README.md)。

先读取官方本机 `efx_ram10.v`，核对[Titanium原语指南](https://www.efinixinc.com/docs/efinity-quantum-ti-primitives-ug-v3.3.pdf)第24—27页及原工程同步ROM实现，再选用该组织。reset只复位RAM输出与控制，不清RAM内容；所有被读地址须先加载。没有利用同地址读写返回值来掩盖时序问题。

## 映射资源

| 独立bank+MAC联调顶层 | 实际数量 |
|---|---:|
| EFX_RAM10 | **16** |
| EFX_DSP48 | **8** |
| EFX_LUT4 | **447** |
| EFX_FF | **420** |
| EFX_ADD | **264** |

相对MAC单元新增165 LUT、148 FF、16 RAM，无新增DSP/ADD。新增148 FF对应136bit activation、8bit mask、2bit深度组选取、1bit pending及1bit错误状态。顶层输入/输出是内部接口，不构成F225外部引脚配置。

工程设置10.000ns时钟及端口延迟，实际完成独立map；没有PNR、STA或100MHz通过结论。报告与端口审计为 `tmp/blue-plate-whole-plate-budget/weight-bank/synthesis/out/weight_mac8.map.rpt`、`weight_mac8.map.v`、`synthesis-summary.json`。

## 整数与协议验证

Python独立整数与RAM数组golden逐拍比较权重输出、read_valid、command_error、8个psum、updated和overflow。RTL与映射后网表均通过**18,087周期、144,696个lane状态**；各覆盖8,705次写入、8,717次读取、53,652次lane MAC、477次停顿、5次命令冲突、3次复位及8个溢出事件。2048个地址全部读回，覆盖511/512、1023/1024、1535/1536及2047边界。

两组K3328用例分别启用8lane、4lane；中途保存部分和、故意覆盖MAC状态、重装1280行后恢复，最终与未分块整数点积完全一致。另验证复位撤销pending但保留已写RAM内容、停顿期间改变输入不会重复消费、切换权重未排空时明确报错。

映射后网表使用同一全量golden复核；最终结果、源码/测试/网表/日志SHA见本目录 `weight-bank-validation.json`。冻结MAC SHA始终为 `f3490692d9bd2160144da3c92693bb8b65f0cbe0a9d435dc4321514cd2c7ffee`。

此阶段只完成权重读数到MAC的最小联调。没有DDR控制器、网络权重、量化scale、层描述符或共享顶层改动，仍不能把16 RAM/8 DSP小模块视为整个51 RAM引擎或系统fit。
