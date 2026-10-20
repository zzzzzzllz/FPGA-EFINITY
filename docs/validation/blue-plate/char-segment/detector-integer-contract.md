# 检测器整数部署：静态审计与一次有界验证契约

2026-10-19。当前检测 ONNX 是 FP32 图，旧资源账中的 INT8 主干、INT32 解码只是容量假设。本次完成原图、逐层尺度关系和部署接口审计，提出一个不训练的 W8/A8 候选。**本轮图像读取、模型前向、量化参数导出均为 0**；未修改模型、产品 ROM、RTL、物理 DDR 地址、8 DSP／51 RAM 目标、阈值或颜色 CNN。以下校准与验证是后续执行计划，尚未运行。

六个绿色负例的前一任务已冻结：25 个交付文件，清单 SHA256 `138a5cfbea4b70f72404e5b24db2bcfc5504c92d385243755778cc6c20e01117`。六次整数 OCR 均未新增接收，详见 [six-green-negatives.md](six-green-negatives.md)。该结论不授权删除颜色 CNN。

## 1. 证据、成熟实现及选择

静态读取 `tmp/blue-plate-normal-g1/mature-detector/y5fu_320x_sim.onnx`，SHA256 为 `2a985dc63a5cc947ec36d18503d6fc0fd54525b9dba17f2fe29a71e86b44456d`。使用独立研究目录中的 ONNX 1.19.1 读取 protobuf 和运行 checker；不使用推理运行时。旧 `detector_sharing.py` 包含一次合成图前向，本轮只读其源码和已保存结果，没有运行它。

实际阅读的实现与取舍：

| 参考 | 实际阅读内容 | 本候选采用的机制 |
|---|---|---|
| 已下载的 TFLite `reference/integer_ops/conv.h` | `ConvPerChannel` 的分组、输入 zero-point、padding、INT32 累加与逐通道乘数 | W8 逐输出通道，A8 逐张量；舍入改用当前引擎的一次 RNE，不声称与 TFLite 位精确 |
| 已有本地 PyTorch `observer.py` 源码副本 | `MinMaxObserver` 与范围到 scale/zero 的计算 | 固定一次 min/max 校准，范围包含实数 0，不搜索百分位 |
| [TFLite v2.20.0 common.h](https://github.com/tensorflow/tensorflow/blob/v2.20.0/tensorflow/lite/kernels/internal/common.h) | `LUTPopulateInt8`、`LUTLookup(int8_t)`，约 440–480、595–637 行 | 256 个离散输入值全枚举，运行时直接查表 |
| [TFLite v2.20.0 activations.cc](https://github.com/tensorflow/tensorflow/blob/v2.20.0/tensorflow/lite/kernels/activations.cc) | `EluPrepare/Eval`、`GeluPrepare`，约 1552–1630 行 | 参考一元激活的准备／执行分离；SiLU 公式是本图适配，不称其为现成 SiLU 内核 |
| [TFLite v2.20.0 concatenation.h](https://github.com/tensorflow/tensorflow/blob/v2.20.0/tensorflow/lite/kernels/internal/reference/concatenation.h) | `ConcatenationWithScaling` 的同尺度复制、异尺度转换 | 每条拼接输入边对齐到共同尺度；该参考内部使用 float，本候选转换为 Q31 |
| 冻结 HyperLPR `inference/multitask_detect.py` | 全部预处理、框转换、NMS、坐标恢复 | 保留原字段、筛选顺序和跨类别 NMS |

前三份新源码保存在 `tmp/blue-plate-char-segment/detector-integer-research/`，来源和 SHA 在 `new-sources.json`。旧卷积和 observer 参考在 `quantization-research/`；HyperLPR 在 `tmp/blue-plate-review/mature-research/hyperlpr/`。新下载的源码只读；解析依赖仅解包到研究目录，记录于 `parser-packages.json`，没有全局安装。

逐层材料位于 `tmp/blue-plate-char-segment/detector-integer-audit/`：

- `nodes.json`：416 个节点逐一列出原 dtype、输入输出形状、属性、小常量、消费者和整数化方式。
- `convolutions.json`：85 层的 K、分组、尾 lane、输出数、权重 tile 和符号尺度。
- `silu.json`、`concat-scales.json`：63 个 SiLU 的真实配对、25 个拼接的输入尺度和其他消费者。
- `head-decode.json`、`initializers.json`：anchor、grid、全零常量证明，以及全部常量形状、范围和内容哈希。
- `bounded-plan.json`：逐身份路径、原图 SHA、split、207 校准身份的原顺序和 304 验证身份；不依赖通配符选择数据。
- `summary.json`、`source-hashes.json`：统计、静态检查和输入来源。

## 2. 原始图与逐层数据类型

ONNX IR 7、opset 12，输入 `[1,3,320,320]`，输出 `[1,6300,15]`。416 个算子、235 个 initializer、415 条 value_info；417 个输入／中间／输出张量均为 FLOAT。常量有 FP32 和 INT64，图内没有 Q/DQ、整数量化卷积或现成 scale/zero。

| 算子 | 数量 | 部署处理 |
|---|---:|---|
| Conv | 85 | W8、A8 输入、INT32 累加、Q31 到 A8；19 层 depthwise |
| Sigmoid / Mul | 69 / 87 | 主干 63 对融合为 SiLU A8 查表；余下属于检测头解码 |
| Concat | 32 | 主干 25 个需对齐尺度；检测头 7 个为字段／尺度拼接，不能把坐标和概率共用量化尺度 |
| Reshape / Transpose / Slice | 38 / 19 / 59 | 主干 32 / 16 / 26 个保持 A8 尺度；其余融合到检测头索引 |
| Resize | 2 | nearest、asymmetric、floor，倍数 `[1,1,2,2]`，逐值复制 |
| MaxPool | 1 | 2×2、stride 2、无 padding、ceil_mode=1；160→80，保持 A8 尺度 |
| Add / Sub / Pow | 18 / 3 / 3 | 全部在检测头；零加法删除，grid 加法精确整数，其他融合进表 |

旧 435 节点是 OpenCV 展开图，与原 ONNX 节点数口径不同。静态脚本已逐一核对 85 层卷积的输入输出／权重形状及 MAC 数，共 183,417,600 MAC。卷积权重 436,800 个，输出通道合计 5,103；已有 bias，图内没有 BatchNormalization，不能再次融合 BN。

**主干没有残差 Add。** 分支通过 Slice、Concat 和 channel shuffle 连接。18 个 Add 中 3 个加全零，3 个加 box grid，12 个加角点 grid。不得套用残差两路直接相加的实现。

设备张量采用紧密 HWC 字节地址 `((y*W+x)*C+c)`，逻辑数值与 ONNX NCHW 一致。权重按输出 lane 分组，K 顺序固定为 `(input_channel, kernel_y, kernel_x)`；host 导出和硬件地址生成必须同序。Transpose 按原 `perm` 映射；Reshape 按 ONNX C-order 逻辑展平再重塑，不能把 HWC 字节流直接套 NCHW shape。第一版允许物化所有这些转换，沿用旧多对象生命周期；不宣称它们都是免费 view。每个实际 reshape shape、slice start/end/axis/step 和 transpose perm 均在逐节点清单中。

## 3. 唯一候选：W8/A8、边尺度转换和查表

### 输入和校准

保持现有 `canvas720`：源图按原 INTER_AREA 路径置入 1280×720 黑底。检测 `letter_box` 用原 INTER_LINEAR 得到 320×180，top=bottom=70、left=right=0，r=1/4；BGR 转 RGB。FP 基线保持 float32 `/255`。整数入口为 RGB 字节 `q=pixel−128`，`s=1/255,z=−128`，黑色 padding 也为 −128。

校准只观察指定 207 张**整帧**的 FP32 张量；原 207 ROI 选择仅用于确定身份，不把裁剪 ROI 送入检测器。对每个 Conv 原始输出和 SiLU 输出收集全元素 min/max；复制、切片、shuffle、池化继承源尺度；Concat 范围取各输入观测范围的并集。范围含 0，使用：

```
lo=min(observed_min,0); hi=max(observed_max,0)
s=max((hi-lo)/255, 2^-23)
z=clip(RNE(-128-lo/s), -128,127)
q=clip(RNE(real/s)+z, -128,127)
```

所有 RNE 均为最邻近、正负 ties-to-even。scale 保存为 float64 的精确二进制值，导出比值时按其有理数值计算，避免平台舍入差异。head 45 通道在每个尺度共用一个 A8 scale；第一版不混用 A16、不逐字段重新选择量化精度。

### 卷积和 Q31

每输出通道 `sw=max(max(abs(W))/127,2^-23)`，`Wq=clip(RNE(W/sw),−127,127)`。采用当前原始 A8 点积模式：

```
b0 = RNE(b/(s_in*sw))
bias_seed = b0 - z_in*sum(Wq)
acc = bias_seed + sum(q_in*Wq)
ratio = s_in*sw/s_out
out = clip(RNE(acc*M / 2^shift) + z_out, -128,127)
```

padding tap 必须送 `q_in=z_in` 并参加固定 K；不能既用了全 K 的 zero 修正 bias，又直接跳过边界 tap。另一种中心化输入算法不是本候选，不能在同一执行中混用。

取 `ratio=m*2^e, m∈[0.5,1)`，`M=RNE(m*2^31), shift=31−e`；若 M 恰为 `2^31`，令 M 减半、shift 减 1。必须满足 `0<M<2^31`、`1≤shift≤62`，否则停止，不增加隐式左移或改精度。所有 Conv 设 `q_relu=0`。逐通道检查 bias 和**每个实际 MAC 批次前缀**的全 A8 域上下界都在 int32 内；不能只检查最终和。64 位乘积对 int32×正31位 M 足够。

普通卷积每组 8 个输出通道广播同一输入；19 个 depthwise 卷积逐 lane 取不同输入通道，multiplier=1，不能照普通卷积广播。三层检测头 Cout=45，末组只有 5 个有效 lane。现有 8 lane、signed17 activation×signed8 weight 可以表示这些数值，但 depthwise 取数控制仍需接入。

### SiLU 和拼接

63 组 `x*sigmoid(x)` 各生成一张 256×8 表：`T[uint8(q)] = quant_out(s_in*(q−z_in) / (1+exp(−s_in*(q−z_in))))`。表索引为字节重解释，顺序 0…127、−128…−1；不使用 `q+128` 索引。离线用 Decimal 80 位与 160 位各生成一次，所有最终整数值须一致，否则停止；head 表也执行相同检查。运行时没有 exp 或激活乘法。每次表生成同时保存全 256 输入的浮点参考误差。

SiLU 在负区间并非全程单调，不能把当前 ReLU/Q31 的端点常数证明直接扩到 SiLU。首个候选不启用检测器通道常数旁路；后续若单独研究，必须从本检测器权重证明，不能套用 OCR 的 658,256 个常数输出。

25 个主干 Concat 在输入边执行 `q_dst=clip(RNE((q_src−z_src)*M/2^shift)+z_dst)`，ratio=`s_src/s_dst`；中心化值 −255…255 放 int32，仍可调用 Q31。相同 scale/zero 时直接复制。异尺度结果直接写 Concat 目的区，不覆盖仍有其他消费者的源张量；不新建整张边临时张量。固定第一版不把转换折进 SiLU 表，避免因多消费者改变其他分支。`concat-scales.json` 明确列出所有这些消费者。

## 4. 三个检测头的整数解码

| head Conv | 网格 / stride | anchors (w,h) | 行数 |
|---|---|---|---:|
| Conv_500 | 40×40 / 8 | (4,5), (8,10), (13,16) | 4,800 |
| Conv_596 | 20×20 / 16 | (23,29), (43,55), (73,105) | 1,200 |
| Conv_692 | 10×10 / 32 | (146,217), (231,300), (335,433) | 300 |

三个原始输出为 `[1,45,H,W]`，逻辑 reshape 到 `[1,3,15,H,W]`，transpose 到 `[1,3,H,W,15]`。最终行号 `head_base + (anchor*H+y)*W+x`，head_base 为 0、4800、6000。字段 `[cx,cy,w,h,obj,x1,y1,x2,y2,x3,y3,x4,y4,class0,class1]`；角点字段 5…12 **没有 sigmoid**。

令 `x=s_head*(q−z_head)`、`p=σ(x)`、S 为 stride、a 为对应 anchor 分量。每个 head 固定 14 张 256×32 表：

| 表 | 张数/head | 存储值 |
|---|---:|---|
| 概率 | 1 | `RNE(p*2^30)`，uint32，值域 0…2^30，供 obj 和两个 class |
| 中心偏移 | 1 | `RNE((2*p−0.5)*S*2^16)`，int32，供 cx/cy |
| 宽高 | 6 | `RNE((2*p)^2*a*2^16)`，int32，三 anchors 的 w/h |
| 角点偏移 | 6 | `RNE(x*a*2^16)`，int32，四角点复用对应 anchor w/h |

中心和角点分别加 `(grid_x或grid_y)*S*2^16`，加法精确。这个表定义避免在运行时对 Q30 sigmoid 平方后再乘 anchor，也避免要求现有 Q31 直接产生宽坐标。三个零加法和重复 grid/anchor 张量可以融合掉；脚本已逐元素证明全零、grid 坐标、anchor 的空间广播一致。

decoded 输出仍是 `[1,6300,15]` 的 32 位字段，但有字段类型：坐标 signed Q16.16；obj/class unsigned Q30。它不是统一 INT32 量化张量，禁止把全部字段使用一个 scale 或统一有符号比较。逐表检查 256 输入以及所有网格位置、恢复到原帧后的值均能装入目标类型；超界停止，不饱和坐标。

后处理严格顺序：

1. 先筛 `obj_q30 > 2^28`，不另加 score 阈值。原源码构造函数的 box_threshold/nms_threshold 未传进 post 函数；实际默认值为 0.25 和 0.5。
2. 两类 `score_k=RNE(obj_q30*class_k_q30/2^30)`，乘积用 uint64；取最大类，类内完全相同取 class0。保留与 FP 类别和排序比较所需的逐字段诊断。
3. `x1=cx−RNE(w/2), x2=cx+RNE(w/2)`，y 同理，仍为 Q16.16。除 2 的 RNE 是明确的新定点舍入点，需要测与 FP 框的差异。
4. 按原来源执行跨类别 NMS，再进行既有下游单／双层处理，不先删 class1。离线原型用冻结版本的 `np.argsort(scores)[::-1]`；NumPy 默认 quicksort 对相同分数的顺序不能擅自替换为最低 row_id。验证记录全部分数 ties 和排序行号；出现新增等分、排序差异或依赖未定义 tie 的保留结果即停止候选晋级。硬件排序必须实现冻结参考的可观察顺序，或另行获得 tie 规则变更授权，当前没有这项变更。
5. 宽高为 `max(0,min(x2)-max(x1))`，无 `+1`。area/inter/union 用 uint64 Q32.32；`IoU>0.5` 等价 `2*inter>areaA+areaB−inter`，等于 0.5 保留。union=0 必须报出退化框并停止验证，不用 epsilon。宽高最大分别 1340、1732 像素，按 Q16.16 舍入再保守加 2 LSB 后，两个 area 和及 `2*inter` 仍小于 2^55；导出时再按每个 anchor 精确核对。
6. 恢复 canvas720 坐标：x 乘 4，y 先减 `70*2^16` 再乘 4。保留浮点基线不裁边的语义。供 warp 的角点最后从 Q16.16 **向零截断**，负数不能用算术右移代替。保留原角点顺序。

NMS 的 64B 记录可容纳 4 框坐标、score、8 角点、class（14×4B），另加 row_id 和 flags（8B）。两份 8B score/index 排序数组沿用原预留。6300 条均过阈值时仍按原语义处理，最多 19,841,850 对比较；不偷偷引入 top-K。现有实验性 32 个 pre-NMS／2 个单层 ROI fail-closed 包装没有作为本候选的新生产规则。

## 5. 与现有 8 DSP／Q31／51 RAM 的具体差距

| 项目 | 当前可复用部分 | 尚缺部分或必须满足的限制 |
|---|---|---|
| 卷积和重定标 | MAC8、部分和 save/restore、正31位 M、shift 1…62、RNE、A8 饱和 | 检测器 W8/bias/M/shift 未生成；stride、padding、depthwise 取数及整图控制未接入 |
| 权重容量 | 最大 K=576，8-lane tile=4,608B，低于原 bank 深度 | Q31 借地址 2046/2047，须 full-K 完成并排空；保留原累加器后才借 MAC，后续卷积不得读到临时乘数 |
| SiLU | 两个 LUT RAM 可组合成 512×32 接口 | 当前 q_relu 不是 SiLU；新增表地址、装载及消费控制，不新增 RAM 或 DSP |
| Concat／shuffle | 原 DDR 多对象生命周期、Q31 输入可容纳中心化值 | 25 个尺度对齐、HWC 与 ONNX reshape/perm 映射没有完整执行器，不能依靠 OCR 双槽覆盖长支路 |
| head 解码 | A8 raw head 和 32 位 LUT 端口；每次一张 1,024B 表 | 坐标加法、字段输出、anchor/head 索引需实现；Q31 A8 输出接口不能冒充宽坐标接口 |
| score／NMS | DSP 时分复用和 64 位分段乘积的已有设计方式可参考 | uint31×uint31→uint64 score、面积乘积、64位比较和排序控制尚无完整接口；不能直接复用饱和 A8 输出 |
| 输入 resize | 原图及 320×320 输入空间已计入容量；可复用原采样思路 | 现有 OCR 224→94、24 高度专用 resize 不是检测 1280×720→320×180 的位精确实现；本计划先冻结参考 RGB 输入字节，不能据此声称整条硬件预处理完成 |
| 静态常数旁路 | 已映射 Q31 候选的证明方法、参数格式 | 本检测器没有全域常数证明；SiLU 非单调，首候选全部按动态路径 |

一次检测共 3,262,500 个 Conv→A8 输出、2,643,200 次 SiLU 查表；全部拼接边都转换时为 1,632,000 个元素。8 lane depthwise 方式下的 22,977,600 拍／229.776ms（100MHz）仍然**只有 MAC**。不把 Q31、save/restore、LUT、DDR、非卷积、NMS 或排队等待当成零；本轮不重新承诺整链时延，也没有整合后的 100MHz PNR 证据。

内存只作原预算内的子分配建议：

- SiLU 表 `63*256=16,128B`；head 表 `3*14*256*4=43,008B`；合计 **59,136B**。
- 原图常量源预留 529,280B，三份全零常量共 378,000B。即使保守保留其余全部常量，再加入新表也只需 **210,416B**；无需增加常量区域。尚未导出这些表或给产品 ROM 写值。
- RAM 一次装一张 SiLU 256B 表或 head 1024B 表；原两块 LUT RAM 的有效 2048B 足够。SiLU 与 head、OCR 不并行驻留，切换时重新加载。表与参数指针使用原逐节点描述符预留，具体二进制打包仍待验证，不能另增一套隐形 RAM。
- 检测临时区沿用 1,536,000B high-water 和旧原图生命周期。拼接转换直接落目的张量；不能切换成 OCR 的两个 256KiB 槽。原帧、副本和 NMS 存储寿命不缩短。
- 全 arena 仍为 **7,052,352B**，引擎仍为 **51 RAM10、8 DSP**；这不是整合综合结果。控制新增的 XLR、真实 DDR 服务和地址落地尚待主控整合，不在本审计中修改预算。

## 6. 唯一一次校准／验证计划

唯一输入名单是 `bounded-plan.json`，从冻结 `experiment/dev-manifest.json` 得到 304 个 development 身份：train 228、tune 76。校准为原 `quantization-w8a8/parameter-freeze.json` 中 207 个 ROI 对应的 **207 个互异 train 身份**；顺序亦冻结。其他 21 个 train 身份及 76 个 tune 身份不参与量化参数选择。每个条目含原始 source SHA；执行前只对名单内文件核验，不枚举 84 validation 或 112 heldout 图像。

执行顺序与硬上限：

1. 每个校准身份读取原图一次，冻结 canvas720、320 RGB 字节、路径与 SHA。FP32 每身份前向一次，共 **207 次**；使用 OpenCV DNN `enableFusion(False)`，一次 `forward(output_names)` 同时返回所需中间层、raw heads 和原 output，禁止为不同层重复前向。旧 OpenCV 名称清单与 `nodes.json` 建立显式对应；缺少任一输出先停止。校准输出无损缓存到独立实验目录，供后续层误差核对，不能为了省缓存再做一次 FP 前向。保持原输入和未改权重，固定运行时／线程和版本。
2. 用上述固定 min/max 规则生成唯一候选并冻结参数、表、逐节点 dtype、舍入、边转换和全域溢出证明。只作一次生成，不按后续误差改 scale。存在非法 shift、非有限值、int32 前缀越界、坐标越界、宽乘积越界、内存或描述符超限时立即停止，不用 A16、截断或加预算兜底。
3. 其余 97 个身份各一次 FP32 前向；复用前 207 次缓存，得到 304 张基线。FP32 总计 **304 次**。新收集多输出图必须与冻结单输出图的缓存检测记录逐身份核对：最终保留框、类别、顺序和整像素角点；不一致先判基线执行路径问题，不能拿它当量化误差。已知缓存为最终检测记录，不虚称拥有全部原始 FP32 层输出。
4. 参数已经冻结后，304 个身份各一次整数前向，**304 次**。按固定 sample_index 升序执行；首个停止条件成立即停止，已完成的 pass 不重跑，报告失败身份和已用次数。上限 **608 次检测器前向（304 FP32+304 INT）**，早停只会减少。每身份整数输入来自同一份冻结 RGB 字节。
5. 本轮未来计划也不执行颜色 CNN、OCR 或优化器；不生成绿色／遮挡新图，不读取 84/112，不进行第二个量化候选、阈值搜索或训练。算子核对从这些已有 trace 取值，不为取向量追加模型前向。内核整数运算必须与 Python 任意精度标量核对，不能只用溢出后相等的两个 int32 实现自证。

冻结后逐身份记录的指标：

| 层级 | 指标及通过条件 |
|---|---|
| 算术 | 逐层全域范围证明；选定首／末位置、每层首／末通道及所有 padding 类别的标量 dot/requant 一致；SiLU/head 表全部 256 输入核对；不允许溢出或非法参数 |
| 张量 | 每层 max/mean 绝对误差、RMSE、按 `max(rms(FP),2^-23)` 归一化的 NRMSE、上下端饱和比例；按 train/tune 分开汇总。仅诊断，不据此调参数 |
| raw head | 按 xywh、obj、8 landmark、2 class 分字段统计，记录阈值附近样本，不把 15 列混算一个误差 |
| 候选与 NMS | 全 6300 行 obj 筛选位图一致，保留候选 class 一致，score 排序与 NMS 留存 row_id 顺序一致；新增等分、任何不一致、union=0 即候选不通过 |
| 几何 | 最终保留框及角点在 canvas720 上 mean/p95/max 像素误差，预设 max≤0.5 像素；warp 使用的全部整数角点必须逐点相同；原始 FP 通过／失败的边界判断必须相同 |
| 资源 | 表、参数、描述符、存活区在原预算内；所有执行步骤显式记账，不把未实现算子计零周期 |

这些条件用于判断“是否可以继续硬件接入，并保持已冻结 ROI 输入的依据”。候选通过仍不等于 FPGA 已完成；若整像素角点不同，就不能沿用旧 OCR 和颜色 CNN 的整链结果。本次没有预先授权重跑下游来放宽条件。

失败后只冻结首个失败证据、层误差和实际 forward 计数，区分尺度饱和、concat 错配、实现错误、raw head 精度、NMS 排序与几何变化，向主控提交下一方向。不在此计划内自动改 A16、重选校准图、改阈值或训练；一个 W8/A8 候选失败不等于用户整链目标无法实现。

## 7. 本轮验证与交付范围

`tools/blue_plate/char_segment/audit_detector_integer.py` 已运行一次：ONNX checker、85 层卷积交叉核对、63 组 SiLU 配对、25 个 Concat 依赖、18 个 Add 分类、全部 grid/anchor 广播及全零证明、207/304 身份隔离均通过。它只读取模型、源码和 JSON，不打开图像文件、不生成量化参数。输出目录已存在时拒绝覆盖。

本轮保留所有既有冻结文件；新审计的输入和交付哈希列于该目录的清单。项目运行方式和产品功能未变，根 README 不更新。
