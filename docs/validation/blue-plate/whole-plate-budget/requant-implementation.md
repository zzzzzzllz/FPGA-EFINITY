# 复用8 DSP的Q31重定标

2026-10-18。`q31_psum_mac8`已完成独立RTL、map与有界mapped验证。**同一份冻结MAC/bank/部分和核心仍为18 RAM、8 DSP；新增990 LUT4、160 FF、199 ADD，合计1898 LUT4、593 FF、463 ADD。** 无新增DSP、RAM或256bit部分和快照。

本结果覆盖signed32累加值、正Q31乘数、1…62右移、可选ReLU、一次最近偶数舍入、输出zero及int8饱和，并支持保留原始int32给tap2第二路使用。不是完整网络、上下文gain/除法或CTC通过；没有接主顶层、DDR或板卡。100MHz仅为SDC约束，无PNR/STA通过结论，也未据独立模块资源宣称整机XLR通过。

## 调研与算术选择

实施前读取模型新的 `integer-deployment-addendum.md`、冻结参数及输出通道向量，核对 `integer_lprnet.py::round_tensor`、`integer_lprnet_fork.py::fork_conv`、`audit_integer_deployment.py::wide_multiply`。实际源码参考为已下载的 `tmp/blue-plate-char-segment/quantization-research/tflite-quantization-util.cc` 与 `cmsis-nn-support.h`；来源分别为[LiteRT源码](https://github.com/tensorflow/tensorflow/blob/master/tensorflow/lite/kernels/internal/quantization_util.cc)与[CMSIS-NN源码](https://github.com/ARM-software/CMSIS-NN/blob/main/Include/arm_nnsupportfunctions.h)。后者默认双舍入，单舍入路径也按加半处理，不能直接替代本模型恰好一半取偶数的规定。

确定采用现有signed17×signed8端口能表达的分解。a低16位为非负uint16、高16位为signed16；M为5个非负7位段。10个局部乘积分别可放int32，按8+2两批执行，每批先load零再乘加，随后按0/7/14/21/28/16/23/30/37/44固定移位串行加到signed64。负数包含INT32_MIN，不做绝对值截断。golden逐项检查局部积及64位累加范围，并与Python精确乘法比较。

完整乘积使用逐拍算术右移，先前低位并入sticky，最后移出位为guard；当guard且(sticky或商最低位为1)时加1。该过程对正负数均符合floor商的RNE。最后全宽加signed zero，再裁剪到[-128,127]。没有第二次舍入。

## 接口与资源复用

顶层实例化一份未改动的 `psum_weight_mac8`。空闲时普通host命令透传；Q31请求仅在核心空闲、权重读排空、无其他命令时接受。M=0、shift=0/63、无有效原值时reuse以及busy冲突均报错，不改变已接受操作。ce=0保持计算和结果，reset优先于ce并撤销未完成结果。

Q31请求将原始a锁存到一个32bit标量寄存器。`q_reuse=1`重新使用该原值，外部q_acc的变化被忽略；ReLU、乘积及A8输出均不会覆盖原值。tap2两个消费者分别提交各自M/shift/zero。输出valid保持到ce且ready；消费后下一拍才接受下一请求。

整组8个卷积累加值在Q31运算前由上层save到既有部分和槽，每次处理一lane前restore，再送对应标量。该组save/8次restore及双写块提交仍由调用方安排，不在本块中隐式实现；reset时上层需丢弃尚未完整提交的两路结果。

两批7bit权重临时占用地址2046/2047。固定LPRNet完整K结束后的当前权重段最大1280，projection为516，故可保留这两字。适用前提是调用方已确认这两个地址空闲；通用2048项整块不能据此宣称仍完整保留。测试验证原32B部分和槽在权重改写及MAC状态破坏后可原样恢复。

冻结MAC、权重bank、包装器和部分和RTL的四个SHA均逐次检查；本轮没有改这些文件。新控制器只通过已有命令端口借用算术，没有另建一套8 DSP或直接weight旁路。

## 周期与验证

接受后需要2拍写权重、2拍装零、2拍issue、2拍排空、10拍64bit合成、shift拍右移及1拍输出，即**19+shift个有效边沿**。另计请求接受与结果消费各1拍，CE停顿和输出背压增加墙钟时间。两路输出各算一次；组save/restore另计。这个周期逐例由bench检查，不作为整网延迟估计。

| 验证 | 结果 |
|---|---|
| Python整数分解 | 1620个边界/随机用例加移位半值检查；分段乘法及串行RNE与精确整数/Fraction一致。 |
| 冻结真实数据 | 100个标量输出：当前输出通道向量56个、tap2附加分支8个、原研究标量36个；tap2真实A8结果逐项核对。旧36项用于算术回归，不混入当前模型效果指标。 |
| RTL | 638例、38900周期、3149次插入停顿；直接比较舍入前完整64位乘积及最终A8。 |
| mapped有界回归 | 218例、14249周期、1162次插入停顿；包含全部100个真实标量输出及边界/协议用例。 |
| mapped完整乘积探针 | 27个极值用例直接比较舍入前64位乘积，避免饱和掩盖高位错误；同时核对最终A8。 |
| 协议 | 参数锁存后故意变化输入、busy时拒绝请求/load、未排空请求拒绝、reuse无原值拒绝、输出ready/ce保持、reset取消计算及原值有效位、完整槽恢复。 |
| map | 18实际RAM实例与8 DSP；原语参数、源码副本、输入哈希及XML语义核对通过。 |

mapped使用上一阶段已由主控独立复核的本地EFX_LUT4启动修正。本网表141种掩码的36,237项启动及四态表值检查全部通过。仍保留原厂模型安装和所有冻结源码；这不是“未修改原厂模型下通过”，也不据此断言整个工具链均无问题。

模型当前原顺序projection的181.89792ms/ROI纯MAC、9,561,760B/ROI分块权重读取和7,052,352B arena来自新的部署补充合同。本块不沿用旧FP64高度换序预算，也没有重新测算全网重定标、save/restore、DDR或置信度总时间。

复跑入口见 [requant/README.md](../../../../tools/blue_plate/whole_plate_budget/requant/README.md)。最终证据为 [requant-validation.json](requant-validation.json)、[RTL收据](requant-rtl-validation.json)、[mapped收据](requant-mapped-validation.json)、[golden收据](requant-golden-validation.json)；原始向量、网表、日志与本地仿真模型在 `tmp/blue-plate-whole-plate-budget/requant/`。
