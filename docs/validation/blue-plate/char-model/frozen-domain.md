# 冻结开发字符：Y/X、V/W 泛化分析

2026-10-18。几何增广在 38 组冻结实拍诊断批中修正了 Y→X 和 7→Z；但 geometry C=0.1 在原字符 validation 上正确接受下降 60、错误接受增加 1。V→W 尚未解决。两档实验候选已交接给主控做完整开发/校准链路比较，本轮不替换冻结 candidate。

## 数据与口径

- 核对 `tmp/blue-plate-normal-g1/frozen-development-rois/manifest.json` 的 632 个 PNG 哈希、20 张原图哈希和文件名标签，全部一致。
- 38 个车牌/模式组合：18 automatic、20 oracle；37 组有完整七字符，共 259 字符。`050-automatic` 无字符，按整牌拒识计入。
- 用 `border-diagnosis.json` 给出的 11 组修边后 ROI 替换对应原组，其余 27 组保留原冻结 ROI。这是选定故障与对照组成的混合诊断批，不是完整 196 张开发集，也不是代表性测试集。
- 每个 ROI 只规范化一次。冻结分类器的每个分数、margin、接受决定均与来源记录精确重放一致。
- 训练只使用原 EasyPR 内容分组的 18,112 个 train 样本；阈值只用 3,936 个 validation 样本选择。没有把开发车牌字符加入训练，没有评分 EasyPR test 或读取 CCPD final heldout。
- 冻结 candidate 全部 9 个文件哈希保持一致，`weights.npz` 为 `d9c78f399086b74d00417c982c37b6d5b2a1a836bfde8ad020bf9fe9d9c3da52`。

## 两处错误的证据

### `115-automatic`：皖A43Y26，位置 4

原灰度图、原二值 ROI 和规范化图保留 Y 的分叉与下干。修边改变的位置是 6，目标位置 4 没变。原紧框 42×21、前景密度 0.382；规范化后的紧框 27×14、密度 0.394。

训练集中 Y 有 66 个、X 有 63 个。320 维特征的 L1 最近 Y 距离为 642，最近 X 为 778。Y 密度的 10/50/90 百分位为 0.349/0.404/0.447，当前字形并非单纯笔画过厚。

冻结模型 X 得分 -27、Y 得分 -3982。Y−X 的分数差 -3955 可分解为：上半网格 +13672、下半网格 -17408、列投影 -554、行投影 -214、bias +549。当前线性边界对下干的位置变化敏感；几何增广后的修正支持这一判断。不能据此称原 ROI 不可辨认。

### `050-oracle`：皖AX815V，位置 6

该组修边前后字符框不变。图像保留 V 的单谷形状。原紧框 36×24、密度 0.589；规范化紧框 28×19、密度 0.607。

训练集中 V 有 36 个、W 有 51 个。最近 V 距离 1060，最近 W 为 1202；正确类近邻仍更近。训练 V 的密度 90 百分位为 0.561，宽高比 90 百分位为 0.607；输入分别是 0.607 和 0.679，属于现有 V 样本覆盖较少的粗宽字形。冻结模型 W 得分 -6333、V 得分 -11814，差 5481。

V−W 差值中，上半网格 -5120、下半网格 -6240、列投影 -2410、行投影 -1142、bias +9431。它与 Y 的单一下干位置问题不同。增广与类别平衡没有修正这个 V；MLP64 能得到 V，但未通过其验证集阈值，且整批有其他回退。这些证据支持分类泛化不足，尚不足以证明某一种增广能彻底解决。

原图、特征图及各正确/误判类四个训练近邻见 `tmp/blue-plate-char-model/frozen-domain/confusion-neighbors.png`。邻居来源路径、文件哈希、样本 ID、距离及投影保存在 `confusion-analysis.json`。

## 调研与方案依据

实际阅读了缓存的 EasyPR `src/train/ann_train.cpp` 中 `getSyntheticImage`：小幅平移/旋转扩充字符训练。文件位于 `tmp/blue-plate-g1/easypr/src/train/ann_train.cpp`，来源 [EasyPR](https://github.com/liuruoze/EasyPR/blob/master/src/train/ann_train.cpp)。

下载并阅读 [Tesseract degradeimage.cpp](https://github.com/tesseract-ocr/tesseract/blob/main/src/training/degradeimage.cpp)，保存为 `tmp/blue-plate-char-model/frozen-domain/tesseract-degradeimage.cpp`。其中的笔画扩散和图像退化提供了笔画增广依据。本轮仅借鉴机制，没有执行下载源码。

实际阅读 [OpenCV OCR 示例](https://docs.opencv.org/4.11.0/dd/d3b/tutorial_py_svm_opencv.html) 中 moments/warpAffine 的倾斜处理代码。GitHub 原始 `digits.py` 下载超时，未声称取得该文件。这里采用全类训练仿射增广，让现有推理预处理不变，而非直接接入该示例的 deskew/HOG。

阅读 [LinearSVC 的 class_weight 定义](https://scikit-learn.org/stable/modules/generated/sklearn.svm.LinearSVC.html)，并检查本机 sklearn 1.6.1 的 `compute_class_weight` 实现，确认 balanced 使用样本总数/(类别数×该类计数)。全类别平衡用来检验少数类训练权重不足的解释。

所有新模型沿用 320 维特征、65 类 LinearSVC、Q8 权重/Q13 bias、整数打分。没有类别对例外或车牌白名单。训练后用原验证分组按原规则重新校准阈值；各模型的接受数不能解释为只改权重的影响。

## 整批结果与回退

表内“接受正确/错误/拒识”按整牌计算，总数均为 38。

| 模型 | 字符原始正确 /259 | 整牌原始正确 | 接受正确 | 接受错误 | 拒识 |
|---|---:|---:|---:|---:|---:|
| 冻结 linear | 254 | 32 | 30 | 2 | 6 |
| 原 MLP64 | 255 | 33 | 29 | 1 | 8 |
| 原 MLP128 | 252 | 30 | 28 | 2 | 8 |
| cross 笔画增广 | 253 | 31 | 27 | 3 | 8 |
| horizontal 笔画增广 | 254 | 32 | 30 | 2 | 6 |
| balanced 类别权重 | 254 | 32 | 30 | 3 | 5 |
| geometry，C=0.1 | 256 | 34 | 32 | 1 | 5 |
| geometry，C=0.01 | 256 | 34 | 34 | 1 | 3 |

笔画增广使用原样本及各一次膨胀、腐蚀，分别为 3×3 十字核或 1×3 水平核。几何增广使用原样本及四种变换：水平剪切 ±0.2、横向缩放 0.85/1.15，共 90,560 个训练样本。变换在 64×64 画布上执行，避免裁掉前景，再紧框规范化；未变换的原训练样本不重复规范化。所有类别执行同一规则。

geometry C=0.1 的整牌变化只有两项：`030-oracle` 的 7→Z 从错误拒识变为正确接受；`115-automatic` 的 Y→X 从错误接受变为正确接受。其余 36 组的文本及接受状态不变。

geometry C=0.01 保留以上两项改进，并让原本正确但拒识的 `066-automatic`、`192-automatic` 通过阈值。其余 34 组不变。在本批没有新增回退。automatic 为 17 正确接受、0 错误接受、1 拒识；oracle 为 17 正确接受、1 错误接受、2 拒识。

其他模型的回退也完整保留：MLP64 使 `066-automatic` 皖→苏、`159-oracle` D→2，并错误接受原拒识的 `135-oracle`；MLP128 新增 D→2 错误接受；cross 增广新增 `030-oracle` K、`159-oracle` 9 等错误接受，且丢失两个正确接受；balanced 错误接受原拒识的 `135-oracle`。horizontal 没有净收益。

全部 304 行（8 模型×38 组）文本及接受状态见 `all-pair-results.csv`；每个模型的逐组变化与目标字符分数见 `comparison-summary.json`，不只报告两个目标字符。

## 原字符验证集与候选取舍

| 模型 | 原始正确 /3936 | 接受正确 | 接受错误 | 拒识 |
|---|---:|---:|---:|---:|
| 冻结 linear | 3726 | 3522 | 30 | 384 |
| MLP64 | 3764 | 3487 | 32 | 417 |
| MLP128 | 3782 | 3575 | 21 | 340 |
| cross | 3696 | 3446 | 30 | 460 |
| horizontal | 3723 | 3506 | 30 | 400 |
| balanced | 3731 | 3487 | 27 | 422 |
| geometry C=0.1 | 3726 | 3462 | 31 | 443 |
| geometry C=0.01 | 3707 | 3448 | 28 | 460 |

几何增广改善了选定实拍诊断批，但原字符验证集接受正确数减少 60/74。不能把本批收益直接推广为总体提升。

相对冻结模型的 30 个错误接受，C=0.1 消除 17 个、增加 18 个，最终 31 个；C=0.01 消除 16 个、增加 14 个，最终 28 个。逐样本真值、前后预测/分数/接受状态、文件路径和哈希均记录在 `comparison-summary.json` 的 `validation_error_changes`，没有只报告净变化。

65 类的每类样本数、原始正确、接受正确、接受错误、拒识见 `validation-by-class.csv`（8 模型×65 类）。关键类的接受正确/总数如下：

| 模型 | V | W | X | Y | Z | 7 |
|---|---:|---:|---:|---:|---:|---:|
| 冻结 | 11/11 | 8/8 | 7/8 | 15/16 | 9/9 | 96/96 |
| geometry C=0.1 | 11/11 | 8/8 | 7/8 | 16/16 | 8/9 | 96/96 |
| geometry C=0.01 | 11/11 | 8/8 | 7/8 | 15/16 | 8/9 | 95/96 |

三者 X 均有 1 个错误接受，其余表中关键类没有错误接受。验证集 V 只有 11 个且原模型已全对，无法代表当前粗宽实拍 V。全类变化中，C=0.1 在沪、吉、苏、闽、湘、粤、陕、新、A、G、T、U、6 等真值类增加错误接受；C=0.01 在沪、吉、苏、鲁、湘、粤、新、A、T 等真值类增加错误接受，具体计数以 CSV 为准。

- C=0.1 权重范围 [-586,468]，需要有符号 11 位；全特征范围的保守累加界 531070，需要有符号 21 位。因此不能直接放入冻结 10 位权重 ROM。
- C=0.01 权重范围 [-278,198]，适合 10 位；bias [-24442,-997]；保守累加界 277019，20 位足够，冻结核的 32 位累加也能容纳。输入、特征、类别顺序及打分形式不变。本轮未导出替代 ROM，也未扩展硬件验证。
- C=0.01 的省份阈值 score≥-9356、margin≥5119；字母数字 score≥-16417、margin≥2364。Y 得分 3974、margin 6101；V 仍被判 W，得分 -3068、margin 4222，错误被接受。

两个可复跑实验目录为 `tmp/blue-plate-char-model/frozen-domain/geometry/` 和 `geometry-regularized/`，均包含 `weights.npz`、`interface.json`，可直接供现有 Python `predict` 接口读取。两档候选的增强、超参数与阈值已固定，权重/接口/训练切片/脚本哈希见 `experiment-freeze.json`。交由主控在完整开发/校准自动链路比较两者；保留 11 位候选，不按原 10 位 ROM 门槛淘汰。若采用 11 位候选，应重新导出、验算与评估资源，不能截断权重。本轮的 normalize/features/类别顺序完全不变，预处理 RTL 可继续依据冻结 `model.py` 实现。

V 的后续改进需要独立的粗宽真实字符训练样本与可核验分组，或在更多开发实例上验证能保留拓扑的特征方案。不要把当前这张错误图直接加入训练来宣称修复，也不要为 V/W 增加特判。

## 复现与交付

主控独立重建特征、整数 MAC、位置约束 top2 和拒识判断，核对 3,936 个 validation 字符及 38 组/259 个冻结实拍字符，结果逐项一致。权重宽度 11/10 位、保守累加上界 531070/277019 也一致。审核原件位于 `tmp/blue-plate-review/augmentation-audit.json`，本目录保留[独立审核副本](frozen-domain-independent-augmentation-audit.json)。这项审核确认实验计算一致性，不等于候选已通过完整场景验收。

主控已安排主实现对两个固定实验目录进行 **dev304 + val84、相同冻结前处理、普通门限** 的完整链路对照。该结果尚未纳入本文；不得把本地 38 组诊断结果当成这次完整对照结果。后续选型依据完整链路收益、逐项回退及资源评估，保持 final heldout 未触碰。预处理契约不变，硬件实现可继续。

交接证据入口：

- [固定实验参数与哈希](frozen-domain-experiment-freeze.json)：两个候选的权重、接口、训练切片及脚本指纹。
- [65 类 validation 明细](frozen-domain-validation-by-class.csv)：8 个模型共 520 行，每类原始正确、正确接受、错误接受、拒识。
- [逐样本新增/消除错误接受](frozen-domain-comparison-summary.json)：`models.<模型>.validation_error_changes` 保存真值、前后决定及来源哈希；geometry 新增 18/消除 17，regularized 新增 14/消除 16。
- [整批实拍前后结果](frozen-domain-all-pair-results.csv)：8 个模型×38 组，共 304 行。

在项目根运行：

```powershell
D:/Python/python.exe -X utf8 tools/blue_plate/char_model/frozen_domain.py prepare
D:/Python/python.exe -X utf8 tools/blue_plate/char_model/frozen_domain_diagnose.py
D:/Python/python.exe -X utf8 tools/blue_plate/char_model/frozen_domain.py train
D:/Python/python.exe -X utf8 tools/blue_plate/char_model/frozen_domain.py variants
D:/Python/python.exe -X utf8 tools/blue_plate/char_model/frozen_domain.py regularized
D:/Python/python.exe -X utf8 tools/blue_plate/char_model/frozen_domain_report.py
```

运行证据统一位于 `tmp/blue-plate-char-model/frozen-domain/`：`input-audit.json`、`batch.json`、`confusion-analysis.json`、`comparison-summary.json`、`all-pair-results.csv` 与各模型 `*-batch.json`。文档旁保留本轮摘要、逐组 CSV、邻居图和输入审计副本。根 README、主流程、RTL、release 与冻结 candidate 未由本轮修改。
