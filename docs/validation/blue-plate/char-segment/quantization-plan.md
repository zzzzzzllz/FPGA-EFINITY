# 零训练W8/A8算术可行性方案

2026-10-18。当前完整网络存在中部遮挡错误接受问题：主实现冻结报告中严格门限接受66/388项，颜色门控不能拦截。本轮只验证算术、精度损失和真实MAC向量，任何量化置信度变化均不能视为完整性修复，不放行网络RTL或产品ROM。

## 已读成熟实现与选择

- [LiteRT INT8规范](https://developers.google.com/edge/litert/conversion/tensorflow/quantization/quantization_spec)：逐输出通道对称权重、逐张量非对称激活、int32偏置和统一concat尺度。
- 实际下载并阅读 [ConvPerChannel](https://github.com/tensorflow/tensorflow/blob/master/tensorflow/lite/kernels/internal/reference/integer_ops/conv.h) 的偏移MAC、偏置、逐通道重定标和饱和路径，以及 [QuantizeMultiplier](https://github.com/tensorflow/tensorflow/blob/master/tensorflow/lite/kernels/internal/quantization_util.cc) 的frexp/Q31乘数。
- 实际下载并阅读 [CMSIS-NN arm_nn_requantize](https://github.com/ARM-software/CMSIS-NN/blob/main/Include/arm_nnsupportfunctions.h) 的单次/双次舍入分支；两者不能混称位精确等价。本候选明确采用单次最近偶数舍入，不宣称与CMSIS默认舍入位精确一致。
- 实际阅读本机PyTorch `fuse_conv_bn_weights` 与observer的 `_calculate_qparams`，保留副本。BN只融合既有运行统计，不更新统计或权重。采用min/max而不搜索百分位、MSE或按评价结果调尺度。

材料在 `tmp/blue-plate-char-segment/quantization-research/`，来源和SHA写入sources.json。GreenWaves厂商方案另做结构/预处理对比，不默认与当前68类模型等价；首次GitHub API请求超时，改用网页及原始文件定向获取。

## 冻结候选

1. 只以既有BN校准记录中的原207个train ROI统计原FP32各融合层输出和concat范围；输入仍为冻结BGR/Q8 24×94。76tune仅评价。读取dev307之前先写协议，训练207统计后先冻结量化参数再评价全部307；不读84或112图片，不新增优化器步骤。
2. 权重按每输出通道max-abs量化到[-127,127]。激活按含0的min/max量化到[-128,127]，带整数zero point。与已读PyTorch observer一致，尺度下限为float32 eps（2^-23），逐层报告触及下限的通道。首个算术预检发现融合BN后存在近零通道，裸max/127造成146位右移和不可表示偏置；按官方下限处理后才进入正式207统计。各层尺度不因后续饱和或评价结果而修改。
3. 第一层输入存储为 `pixel−128`，原 `(pixel−127.5)/128` 的半级差在首层偏置中离线融合；首层无padding，因此该仿射变换精确。其余层按 `real=scale×(q−zero)`。
4. BN使用官方融合公式。卷积为signed8×signed8→int32 MAC，偏置含静态zero-point修正；离线生成逐输出通道Q31乘数和移位，int64乘积、单次最近偶数舍入、ReLU与int8饱和。检查保守累加界和实际范围。
5. 4D输入下原MaxPool3d等价为空间3×3最大值后通道步进抽取，不改为通道最大池化。保持已有尺度/zero point。
6. 上下文均值池保留窗口中心化整数和v（int32），避免先压回A8。若窗口面积K、输入尺度s、元素数N，则归一化后真实值为 `N×K×v/(s×sum(v²))`。以共同concat尺度sc离线生成 `C=RNE(K/(s×sc)×2^30)`；运行时整数除法 `gain=RNE(C×N/sum(v²))`，再 `q=RNE(v×gain/2^30)+zero_concat`。能量和用int64，标量除法保留完整整数宽度，报告真实及保守位宽；零能量明确报错，不加epsilon。
7. concat统一A8尺度；末卷积W8/A8后，高度均值保留整数和，以末尺度/高度表示最终logits，不再次压缩为8位。
8. 网络算术参考使用真正整数张量运算。离线校准/融合/尺度生成使用浮点，评价时logits反量化和原log-softmax/CTC置信度使用float64。**端到端接受链仍是混合精度诊断，不能标为全整数系统通过。**

## 验证与停止条件

记录307个ROI逐层误差、范围/饱和、原始完整号码、固定严格门限0.9931710550839266下OCR和固定组合的接受变化；不选新门限。参数与原模型不变检查、整数MAC对独立标量核对、舍入正负边界和真实8路分组向量必须通过。

若A8明显损失（完整号码正确数或严格正确接受数减少超过5），只追加两项预定定位诊断：整数backbone接FP32上下文/头，以及FP32 backbone端点接固定整数上下文/头。两者使用同一冻结尺度，不搜索新参数；定位后报告根因，再由主控决定下一条技术路线。

输出研究用参数数组、整数参考、逐层证据与真实层MAC向量，不输出产品ROM或网络RTL。先冻结开发产物，84复核须主控另行授权。
