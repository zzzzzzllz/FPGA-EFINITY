# GreenWaves公开模型与本项目的差异

2026-10-18。实际读取了[厂商公开仓库](https://github.com/GreenWaves-Technologies/licence_plate_recognition)的 `model/gen_lpr_at_model.py`、`utils/lprnet_tflite_inference.py`、`lprnet.c`、CMakeLists及README，并下载1,471,656字节的 `model/lprnet.tflite`作结构读取，未执行其脚本或模型。

初次GitHub树API超时，后续由网页CMake入口找到生成脚本，通过raw地址下载所列文件。全部材料及URL/SHA位于 `tmp/blue-plate-char-segment/quantization-research/greenwaves/`。使用下载的TensorFlow官方schema与Python标准库struct读取FlatBuffer元数据，结果为 `model-structure.json`；没有安装新依赖。

| 项目 | GreenWaves实际材料 | 当前冻结sirius模型 |
|---|---|---|
| 字符表与输出 | 71类、blank70；TFLite `[1,88,71]` | 68类、blank67；`[1,68,18]` |
| 输入量化 | UINT8 `[1,24,94,3]`，scale=1/128、zero=128，即 `(p−128)/128` | BGR `(p−127.5)/128`；本轮首层偏置吸收半级差 |
| 示例通道 | Python推理明确转RGB；C端读一通道后复制三份，不能混为同一预处理 | 保持BGR三通道，不增加灰度变体 |
| 第一个卷积 | 输出仍24×94 | 有效3×3后22×92 |
| 池化与时序长度 | 普通2D最大池化，末宽88 | 4D输入下MaxPool3d包含通道抽取，末宽18 |
| 上下文 | 两层FC：6248→64→6248，Sigmoid后reshape，与71通道特征concat成142通道 | 四分支均值池化后除以各自全张量均方值，concat为516通道 |
| 最后投影 | 142→71的1×1卷积；输出UINT8 scale≈0.51296848、zero128 | 516→68的1×1卷积，再高度均值 |
| 量化生成 | `NNGraph.load_graph(...,load_quantization=True)`；布局调整、scaled/expression融合；NE16分支调用SQ8量化 | 本轮逐输出通道W8、逐张量A8，整数MAC和明确舍入/饱和参考 |

实际FlatBuffer含16个CONV_2D、3个MAX_POOL_2D、2个FULLY_CONNECTED、1个LOGISTIC、2个RESHAPE、1个CONCATENATION；没有MEAN、POW、MUL或DIV来执行当前模型那条动态能量链。卷积/FC权重在所读模型中为UINT8、单尺度，偏置为INT32。原始模型中带FakeQuant命名，不据此推断其训练流程或声称为零训练PTQ。

生成脚本加载已有量化信息，调用NNTool融合与AutoTiler生成，CMake配置GAP的L1/L2/外部存储。它说明厂商已有面向其架构的量化部署流程；不能据此认为Ti60资源满足、当前68类权重等价、或本项目动态能量算子已受支持。本轮没有移植其网络或替换权重。

可借鉴的是显式量化元数据、分层整数算子与内存调度验证；两层FC上下文属于不同训练模型，若以后考虑需另立效果与资源试验，不属于当前冻结候选的等价变换。C端/Python示例的解码处理也与本项目精确CTC概率不同，未借用其置信门限或解码代码。
