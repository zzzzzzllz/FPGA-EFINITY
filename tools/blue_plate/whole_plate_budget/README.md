# 整牌模型成本审计

**当前入口（2026-10-19）**：[同一固件资源审计](../../../docs/validation/blue-plate/whole-plate-budget/same-firmware-audit.md)。完整边缘演示与 OCR 必须共存，检测/颜色 CNN 和 HS 退出当前实现路线。运行 `D:/Python/python.exe -X utf8 -B tools/blue_plate/whole_plate_budget/same_firmware_audit.py` 可只读核对 release、实际报告、资源缺口和 OCR-only 流量。下述三模型预算、裁剪 live 底座的累计预算都是历史，不能当作当前完整固件的余量。scalar-read 候选冻结保留，不扩大实现。

静态分析见[字库与共享边界](../../../docs/validation/blue-plate/whole-plate-budget/font-and-sharing-followup.md)。后续授权的 [font_compact/](font_compact/README.md) 已实现独立候选，实际map从16降至9 RAM、475降至123 LUT4，原字体和原OSD不变。RTL/mapped等价证据见[实施报告](../../../docs/validation/blue-plate/whole-plate-budget/font-compact-implementation.md)；仍未接产品，单项节省不能当作整机fit。

[RAM分块研究](../../../docs/validation/blue-plate/whole-plate-budget/ram-tile-audit.md)核对512/256权重深度、Q31临时地址、部分和事务，以及替代旧51-bank计划的22/16-bank条件方案。`ram_tile_audit.py`只读取冻结权重做分块算术/地址核对，输出 `ram-tile-audit.json` 和 `ram-tile-layers.csv`；没有新RTL/map，推荐512深度独立验证。

核算脚本读取现有综合报告与主控已获取的模型，用合成输入核对尺寸、MAC、池化语义和内存调度，不训练或评测数据集。后来授权的 `mac8/` 提供独立计算RTL、仿真和map；所有工作均不访问板卡。

在仓库根目录运行：

```powershell
& D:/Python/python.exe -B tools/blue_plate/whole_plate_budget/audit.py
```

依赖现有 Python/PyTorch 环境、`tmp/blue-plate-review/mature-research/lprnet/`、`tmp/blue-plate-normal-g1/mature-detector/model-costs.json`、脚本中列出的现有 map/place 报告和本机 Efinity RAM primitive。缺少材料时直接报错，不以默认资源数补齐。

输出：`tmp/blue-plate-whole-plate-budget/costs.json`，以及 `docs/validation/blue-plate/whole-plate-budget/` 下的 `costs.json`、`layers.csv`。完整结论见该目录 `report.md`。RAM/DSP 分配和调度是解析估算，XLR 尚无新引擎映射结果。

唯一学生的缓冲/端口调度检查：

```powershell
& D:/Python/python.exe -B tools/blue_plate/whole_plate_budget/student_schedule.py
```

该脚本读取已有 `Candidate(8,native=True)`，用合成整数输入逐地址执行并与 PyTorch 比较，输出同目录 `student-schedule.json`。报告是 `docs/validation/blue-plate/whole-plate-budget/student-schedule.md`。测试量化参数仅作地址与算术夹具，不能作为训练后模型的导出参数。

检测+识别共享成本复核：

```powershell
& D:/Python/python.exe -B tools/blue_plate/whole_plate_budget/detector_sharing.py
```

依赖现有OpenCV和已下载的320检测ONNX；以全零输入检查形状，从实际图连接检查DDR存活期、相对地址和共享银行分配，并估算分块权重、保守流量与NMS边界。输出 `detector-sharing.json`，报告为 `detector-sharing.md`。不运行真实图像，不实现检测执行器；INT8主干/INT32解码是待验证的存储假设。

19层depthwise的八路独立通道检查（先运行上一条命令生成DOT与地址计划）：

```powershell
& D:/Python/python.exe -B tools/blue_plate/whole_plate_budget/depthwise_schedule.py
```

输出 `depthwise-schedule.json`，以PyTorch grouped Conv逐元素比较int32结果、测试重量化后uint8写回，以及真实MaxPool_9。池化仅支持该模型的无padding情况；卷积覆盖真实padding与非零输入zero-point。报告 `depthwise-schedule.md` 区分MAC周期、cache请求、DDR miss和未计入的控制时间。

完整预训练LPRNet共享预算复核：

```powershell
& D:/Python/python.exe -B tools/blue_plate/whole_plate_budget/full_lprnet_sharing.py
```

加载已有预训练权重，只用随机输入核对分支重排；另用不来自模型的整数内积核对K=3328分段及尾块。输出 `full-lprnet-sharing.json`，报告 `full-lprnet-sharing.md`。不量化或导出模型，不评测图像；W8/A8与中间位宽均为容量条件。

补入当前联合门槛仍调用的颜色CNN：

```powershell
& D:/Python/python.exe -B tools/blue_plate/whole_plate_budget/color_cnn_sharing.py
```

直接读取冻结的 `litemodel_cls_96x_r1.onnx`，输出 `color-model-cost.json`、`color-cnn-sharing.json`，核对17个depthwise层的尾通道与跨字地址、1280通道参数/输出分块、静态DDR区间及三模型MAC小计。报告 `color-cnn-sharing.md`。HS规则不替代该模型；本脚本未做量化数值复现或真实图像评测。

16路备选只读比较：`D:/Python/python.exe -B tools/blue_plate/whole_plate_budget/lane16_comparison.py`。输出 `lane16-comparison.json`、`lane16-layers.csv`，核对尾lane、16KiB权重bank重排、K分段和部分和；报告 `lane16-comparison.md`。不替换8路基线，不改显示或资源上限。

已授权的第一块独立计算RTL位于 [mac8/](mac8/README.md)：8路signed17×signed8、int32部分和装载/续算、mask/停顿/复位及溢出报告。独立测试和map产物在tmp，未接入主工程。验证报告见 `docs/validation/blue-plate/whole-plate-budget/mac8-implementation.md`。

第二块 [weight_bank/](weight_bank/README.md) 提供16 RAM的2048×64bit权重bank及一拍同步读对齐，连接冻结MAC。报告为 `docs/validation/blue-plate/whole-plate-budget/weight-bank-implementation.md`；同样只作独立仿真/map，不接DDR或主顶层。

第三块 [partial_sum/](partial_sum/README.md) 加入2 RAM、512×32bit串行部分和保存/恢复，复用上述冻结bank和MAC。报告为 `docs/validation/blue-plate/whole-plate-budget/partial-sum-implementation.md`。mapped仿真包含经独立真值表验证的本地LUT初始化修正，详见报告。

tap2量化分叉只读预算：`D:/Python/python.exe -B tools/blue_plate/whole_plate_budget/quantization_fork_budget.py`。报告 `quantization-fork-budget.md` 区分缓存/参数容量、未实现的Q31算术接口，以及真实向量的K项lane与硬件输出通道lane。

第四块 [requant/](requant/README.md) 已实现最小整数Q31重定标，复用同一份8 DSP、权重bank和部分和核心；支持保留原始int32供tap2两路使用。报告 `requant-implementation.md` 给出分段乘法、一次RNE、串行周期及独立map结果。前述分叉审计保留当时状态；本模块不自动完成整组调度、上下文gain或CTC。

当前服务成本与累计资源入口：`D:/Python/python.exe -B tools/blue_plate/whole_plate_budget/service_cost.py`。读取冻结整数参数的真实shift、现有map和显示TTL源码，输出 `service-cost.json`、`service-cost-layers.csv`；结论见 `docs/validation/blue-plate/whole-plate-budget/service-cost.md`。该报告覆盖原顺序projection和Q31/save/restore实际契约，替代早期纯MAC数字作为当前服务时间评估入口；不运行模型或综合。

独立加速候选 [requant_static/](requant_static/README.md) 保留冻结Q31，增加全int8域静态常数旁路和固定六步精确RNE。RTL及有界mapped已验证事务周期，实际map不增加RAM/DSP。`requant-static-implementation.md` 与 `requant-static-validation.json` 给出周期推算、OCR实际资源及累计预算；候选尚未接入整链。

后续单点 [scalar_read/](scalar_read/README.md) 复用原两块部分和RAM提供指定slot/lane的32bit读取与握手，独立连接常数/六步Q31候选，避免每动态主输出整组restore。合同、复现命令及包含OCR的资源总账见 `scalar-read-implementation.md` 和 `scalar-read-validation.json`；旧候选冻结保留。
