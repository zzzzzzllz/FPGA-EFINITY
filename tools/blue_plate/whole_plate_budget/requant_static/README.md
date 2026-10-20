# 固定通道常数旁路与六步RNE：独立候选契约

冻结 `requant/` 及MAC/bank/部分和不改。当前500ms TTL与三次确认是现实现接入合同，不是用户目标的硬性条件；本候选仍不改它。

先实际读取已下载hls4ml `nnet_dense_compressed.h` 的非零索引/偏置累加和 `nnet_dense_latency.h` 的固定权重实例化，以及FINN `MoveMaxPoolPastMultiThreshold` 的无fork、单调条件。只借鉴固定参数可证明简化的原则，不引入稀疏索引、跳MAC或HLS移植；FINN交换方向和分叉约束不直接适用。

常数证明以冻结bias及所有权重计算全int8输入域的精确独立项区间：`lo=b-128Σw正+127Σw负`、`hi=b+127Σw正-128Σw负`。正M、ReLU、RNE与饱和均单调，只有两端A8相等才标记常数。tap2两路各自证明，不使用实际图像范围。稠密MAC、组save、张量地址、原常数A8字节均保留。

选择固定六步1/2/4/8/16/32位分级移位，而非一拍全宽桶形移位+舍入。每步按shift对应bit决定是否移位；有移位时，新的guard为此次最高丢弃位，sticky合并原sticky、原guard和此次其余低位；未移位则三者保持。第六步合并RNE加1，再走原饱和输出状态。对负数使用算术右移，保留floor商语义。每个动态请求接受后固定25拍，接受/消费另计各1拍，共27拍，不依赖shift。

`q_const`及signed8 `q_const_value`由经过证明的冻结通道描述提供；它不是运行时猜测。空闲且无冲突的常数请求在接受边沿直接设置q_result和valid，下一有效边沿可消费，共2拍。忽略M/shift/reuse/acc，不读取或改变MAC、RAM、原始标量及其有效位。输出背压与reset撤销规则与原核一致。非法busy/未排空/同时host命令仍报错。调用方必须把结果写入该通道原稠密位置。

动态请求仍从每lane整组restore得到原int32；两路动态输出复用原值。若某未来冻结版本出现“主分支常数、次分支动态”，必须先restore并以非reuse装入原值，不能复用前一通道。本候选脚本明确证明当前没有该组合；当前主分支动态/次分支常数时，旁路不破坏原值。

预计保留18 RAM、8 DSP，控制仅增加guard 1bit；现index复用为六步索引，shift寄存器保留不递减。LUT变化来自固定移位选择和sticky归约，按实际map核算，不预估成零。常数标志/值由参数流携带，不增加片内ROM/RAM；完整参数加载器仍未实现，不把这一接口当作已经集成。

派生参数可沿用72bit行：bias32原样保留（稠密MAC仍需它），原M32的最高位在所有正常正Q31参数中为0，可用作constant标志；constant=1时该字低8位放原A8值，其余位为0。动态行保留原M和shift。`proof-and-schedule.json`给出每个通道的派生packed_multiplier及原参数，未覆盖冻结NPZ，不新增并行参数表。参数bank/DDR加载器对该位的接线留给之后的整合；本次端口直接消费证明后的flag/value。

独立证明预计658256个常数输出；动态718320个。计入每常数2拍写出事务、保留所有组save和稠密MAC后，LPR已知核心从136445460降至53878692拍；三模型已知小计从160120216降至77553448拍。当前只将该数作为实施前目标，后续以RTL周期和实际map复核；未计DDR、非卷积等，不能宣称已达到整链服务目标。

## 已完成验证与复现

上述实施前契约已由独立RTL与有界mapped验证：动态接受后25个有效边沿，常数接受时valid；RTL 2387例、mapped 271例通过。实际map为2209 LUT、594 FF、456 ADD、18 RAM、8 DSP，相对冻结Q31为+311 LUT、+1 FF、−7 ADD，不增加RAM/DSP。网络周期总数由已验证事务周期推算，未运行完整网络。

在仓库根目录按顺序运行（build会在当前进程设置Efinity的PYTHONHOME，后续外部Python命令需用新终端或恢复该变量）：

```powershell
& D:/Python/python.exe -B tools/blue_plate/whole_plate_budget/requant_static/prove_schedule.py
& D:/Python/python.exe -B tools/blue_plate/whole_plate_budget/requant_static/test_requant.py
& ./tools/blue_plate/whole_plate_budget/requant_static/build.ps1
```

新终端继续：

```powershell
& D:/Python/python.exe -B tools/blue_plate/whole_plate_budget/requant_static/verify_synthesis.py
& D:/Python/python.exe -B tools/blue_plate/whole_plate_budget/requant_static/test_requant.py --mapped
& D:/Python/python.exe -B tools/blue_plate/whole_plate_budget/requant_static/finalize.py
```

依赖原冻结模型、主控区间证明、服务总账、已下载参考源码、既有100条标量记录和实际OCR map；材料缺失或哈希不符直接失败。mapped仿真使用 `partial_sum/lut_startup.py` 生成的本地仿真副本，并先执行152种LUTMASK、39064项启动/四态真值表验证。

输出在 `tmp/blue-plate-whole-plate-budget/requant-static/`。`finalize.py` 校验现有证据、冻结源及map哈希，纳入OCR实际资源，复制证明/测试凭据并生成 `docs/validation/blue-plate/whole-plate-budget/requant-static-validation.json`。完整结论见同目录 `requant-static-implementation.md`。
