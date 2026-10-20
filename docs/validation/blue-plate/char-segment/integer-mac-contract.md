# 研究用整数算术与八路MAC向量契约

2026-10-18。本契约描述 `integer_lprnet.py` 的唯一冻结W8/A8候选。算术检查通过、识别精度未通过，见[实际结果](quantization-w8a8-results.md)。不包含网络RTL、产品ROM、时序收敛或Ti60容量通过结论。

## 输入、卷积与舍入

入口是已冻结的 `uint8 BGR[24,94,3]`，每次一张。上游224×64→24×94 Q8 resize沿用固定入口，本参考不重新实现。内部NCHW有符号输入 `q=pixel−128`，尺度1/128、zero=0。原FP32输入为 `(pixel−127.5)/128`，差值1/256已离线加到首卷积偏置 `b += sum(w)/256`；首层没有padding，此变换成立。

BN使用原运行统计离线融合；权重按输出通道max-abs量化至[-127,127]，最小尺度float32 eps。激活为 `real=s×(q−z)`，逐张量含0的min/max给出s和z，q范围[-128,127]。实际参数共443,344个int8权重，非零89,614；没有做稀疏裁剪或压缩。791个权重通道触及尺度下限。

每个输出位置/通道计算：

```text
b32 = RNE(b_float / (s_input × s_weight)) − z_input × sum(w8)
acc32 = b32 + sum(signed(q8) × signed(w8))
M31, shift = frozen per-output-channel multiplier and right shift
a = max(acc32, 0) if fused_ReLU else acc32
q_out = clamp(RNE((a × M31) / 2^shift) + z_output, -128, 127)
```

padding填 `z_input`，不能一律填数值0。权重OIHW；点积项展开顺序为输入通道、kernel_y、kernel_x，输出位置按y、x展开。所有卷积空间stride=1，kernel/padding/通道数逐层见 `integer-config.json`。int32偏置文件已含zero修正，RTL端不能再次减zero。

RNE是最近整数、恰好一半取偶数：以正分母d计算floor商q和非负余数r，`2r>d`或`2r==d且q为奇数`时q加1。该定义也适用负分子。**不等同于默认CMSIS-NN/TFLite双次舍入**。乘数由frexp和Q31离线生成；乘积使用有符号int64，右移量见逐通道数组。

16个卷积的保守 `K×128×127+max(abs(b32))` 界需要21～27个有符号位；最大为backbone.20的54,780,546，32位累加足够。保守界也覆盖每个点积前缀和。每层界乘该层最大M31均小于2^63，软件逐层断言。307 ROI实际卷积累加总范围为[-518751,1529163]；不能用实测范围替代上述界缩位宽。

## 最大池化与分叉

原模型在4D张量上调用MaxPool3d，其实际语义必须保留：空间3×3最大值，然后通道步进抽取；深度kernel为1，没有通道最大值。

| 节点 | 空间stride H,W | 通道步进 |
|---|---|---:|
| backbone.3 | 1,1 | 1 |
| backbone.7 | 1,2 | 2 |
| backbone.14 | 1,2 | 4 |

三个节点保持输入s/z。四个上下文端点取首卷积、backbone.4.block.6、backbone.11.block.6、backbone.20的融合ReLU后结果。tap2需在通道抽取之前分叉。

## 上下文归一化

四个端点均非负，zero=-128。对每个窗口保留中心化整数和 `v=sum(q−zero)`，不先舍入至A8。窗口面积K、窗口输出元素总数N、端点尺度s、统一concat尺度sc对应：

```text
E = sum(v²)
C = RNE(K / (s × sc) × 2^30)       # 离线固定整数
gain = RNE(C × N / E)             # 运行时整数除法
q_context = clamp(RNE(v × gain / 2^30) + z_concat, -128, 127)
```

来自原表达式 `avg / mean(avg²)`，其中 `avg=s×v/K`。E=0明确报错，不加epsilon、不生成默认识别结果。concat为NCHW通道拼接，端点顺序0、1、2、3，共516通道；统一尺度 `0.22444872388652726`、zero=-128。

| 分支 | 窗口 / stride | N | C_Q30 | v上界 | E保守无符号位数 | C×N位数 |
|---:|---|---:|---:|---:|---:|---:|
| 0 | 5×5 / 5×5 | 4608 | 1492183033738 | 6375 | 38 | 53 |
| 1 | 5×5 / 5×5 | 9216 | 266785973726 | 6375 | 39 | 52 |
| 2 | 4×10 / 4×2 | 18432 | 162566117952 | 10200 | 41 | 52 |
| 3 | 1×1 / 1×1 | 4896 | 122146304885 | 255 | 29 | 50 |

E使用64位和，标量分子/除法保留全宽。307 ROI的E实际最多31/25/29/21位，gain实际最多27/**33**/31/31位；不能把Q30增益误存为int32。任意非零整数E下，gain最多占C×N的位数。由于v为非负整数，E≥v²≥v，可得 `v×gain ≤ C×N + vmax/2`；四支最坏乘积仍小于2^53。软件int64可容纳，硬件需实现对应宽度乘法和除法，单独8路MAC通过不能证明这些单元已实现。

最后container.0输出是A8，尺度 `1.1814905503216913`、zero=63。沿高度4对 `(q−63)` 求和，保留int16[1,68,18]，logits尺度为 `0.2953726375804228`。实际整数范围[-544,231]；按固定zero可证明[-764,256]，通用中心化和界为±1020。后续主机浮点CTC不属于本整数契约。

## 真实八路点积向量

文件为 `tmp/blue-plate-char-segment/quantization-w8a8/real-mac-vectors.npz` 和同名JSON，源是development ROI 0。四个真实层各取首/中/末空间位置及首/中/末输出通道，共36个点积：

| 层 | K | 每点积八路周期数 | 尾周期有效lane数 |
|---|---:|---:|---:|
| backbone.0 | 27 | 4 | 3 |
| backbone.4.block.0 | 64 | 8 | 8 |
| backbone.20 | 3328 | 416 | 8 |
| container.0 | 516 | 65 | 4 |

总4,437周期。NPZ按 `v00.` 至 `v35.` 存储 `a[cycle,8]`、`w[cycle,8]`（signed int8）、`valid[cycle,8]`（uint8）及 `accumulator_after[cycle]`（int32）。无效尾lane填0且valid=0。JSON包含对应层、展平position、channel、K、初始累加值、末累加值、乘数、右移、ReLU、输出zero及预期重定标值。

测试端先装入 `initial_accumulator`，每周期加8个有效signed乘积并比较 `accumulator_after`，结束按本契约重定标并比较 `requantized`。如果硬件MAC只从0开始，先比较减去initial_accumulator的部分和，再单独验证偏置相加。这里没有规定valid/ready接口或流水延迟；消费端必须按自身接口对齐周期。

`verify_integer_lprnet.py`已用独立标量/有理数核对全部周期、末重定标值以及其在完整网络输出中的对应元素，另通过首层NumPy整层、四个上下文分支和末高度和检查。运行：

```powershell
D:/Python/python.exe -X utf8 tools/blue_plate/char_segment/verify_integer_lprnet.py
```

重新运行完整 `quantize_lprnet.py` 会因已有输出目录拒绝覆盖。交付参数是研究用数组，不是可直接烧录的产品ROM。
