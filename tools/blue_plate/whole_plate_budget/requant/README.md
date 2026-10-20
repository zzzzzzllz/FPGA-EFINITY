# Q31重定标：冻结算术和接口契约

本阶段消费已含一次bias/输入zero修正的int32。公式为 `clamp(RNE((relu ? max(a,0) : a) * M / 2^s) + z, -128,127)`；M为1…2^31−1，s为1…62，z为signed8。参数越界报错，不启动运算。负数按floor商、非负余数实现最近偶数舍入。

实际读取模型 `integer-deployment-addendum.md`、`integer_lprnet.py`、`integer_lprnet_fork.py` 和 `audit_integer_deployment.py`；读取已下载 `quantization-research/tflite-quantization-util.cc::QuantizeMultiplier`、`cmsis-nn-support.h::arm_nn_requantize`。来源为[LiteRT量化实现](https://github.com/tensorflow/tensorflow/blob/master/tensorflow/lite/kernels/internal/quantization_util.cc)与[CMSIS-NN实际头文件](https://github.com/ARM-software/CMSIS-NN/blob/main/Include/arm_nnsupportfunctions.h)。两者使用全宽乘积和移位；CMSIS默认双舍入、单舍入的加半方式均不替代本模型RNE。参考资料留在原研究目录，本模块不复制第三方算法代码。

采用模型已验证的16+16位乘数分解：a低16位零扩展到signed17，高16位符号扩展；M拆5个非负7位段。10个signed17×signed8局部积放入现MAC的int32寄存器，分8+2两批。按固定移位0/7/14/21/28/16/23/30/37/44串行加到signed64。范围由Python整数逐步检查，不截断成32bit。

独立顶层只实例化一份冻结 `psum_weight_mac8`，包含原18 RAM与8 DSP。普通主机命令在空闲时透传；Q31启动必须core空闲且pending排空、无其他命令。Q31占用期间屏蔽并报告新命令。没有新增第二组DSP或权重旁路；两批乘数写入2046/2047。这两个地址须由调用方保留：固定网络当前最后K段最大1280，projection K516，满足条件；不能声称通用K2048整块仍完整保留。

`q_start`锁存一个原始signed32标量以及M/s/ReLU/z。`q_reuse=1`从上次锁存的**原始a**重新计算，忽略外部q_acc；复用前必须已有有效原值。这样tap2两路均从相同原值开始，ReLU、乘积、输出不会覆盖它。reset清除原值有效位和结果。整组8输出的原值仍由调用方先save到现有部分和槽，每个lane处理前restore，再把对应int32送入q_acc；本块不自动调度全组8次restore，不增加256bit快照。

移位使用逐拍算术右移，记录sticky；最后一位是guard，按guard且(sticky或商最低位)加1。最后加signed zero并饱和。避免64bit可变桶形移位器，代价是s拍。请求被接受后的有效边沿：2写权重+2装零seed+2发起乘法+2排空+10次串行合成+s次右移+1次输出，共**19+s拍**。输出valid保持到ce且q_ready，期间不接受下一个请求。外加接受与消费各1拍。两路请求各计一次上述成本；组save/restore另计，不能隐藏在MAC小计中。

状态预算包括原值32、M31、shift6、ReLU1、zero8、64位乘积/商、sticky1、原值有效1、结果8、状态/索引等，预计新增约160 FF；无新增RAM/DSP。实际LUT/FF和10ns约束结果以map为准。当前不实现上下文53bit gain、整数除法、CTC或网络调度，也不使用旧FP64高度换序预算。

验证先运行 `D:/Python/python.exe -B tools/blue_plate/whole_plate_budget/requant/golden.py`：只读冻结真实输出通道向量、tap2分叉输出和旧标量重定标值，独立Fraction核对。随后逐阶段验证RTL、协议、与冻结MAC/bank/psum共用的资源；不接DDR或板卡。

## 实际验证与复跑

在仓库根目录的当前PowerShell执行：

```powershell
D:/Python/python.exe -B tools/blue_plate/whole_plate_budget/requant/golden.py
D:/Python/python.exe -B tools/blue_plate/whole_plate_budget/requant/test_requant.py
& ./tools/blue_plate/whole_plate_budget/requant/build.ps1
D:/Python/python.exe -B tools/blue_plate/whole_plate_budget/requant/verify_synthesis.py
D:/Python/python.exe -B tools/blue_plate/whole_plate_budget/requant/test_requant.py --mapped
```

map实际为18 RAM、8 DSP、1898 LUT4、593 FF、463 ADD；相对部分和基线新增0 RAM、0 DSP、990 LUT4、160 FF、199 ADD。RTL638例/38900周期，mapped218例/14249周期通过。mapped沿用已独立复核的本地EFX_LUT4启动修正，当前141种掩码共36237项表值检查通过；没有改变厂商安装或冻结硬件源码。报告见 `docs/validation/blue-plate/whole-plate-budget/requant-implementation.md`。

`q_valid`在结果状态持续有效，`q_ready && ce`消费后下一拍才可接受新请求。`busy`是部分和核心busy与q_busy的或；旧`done`仍只对应save/restore。非法请求不会覆盖原值或参数，busy冲突不取消当前计算。reset优先于ce，撤销结果和原值有效位。两路结果的写块提交、复位时取消半组输出由上层负责；本模块不提供双结果原子提交。
