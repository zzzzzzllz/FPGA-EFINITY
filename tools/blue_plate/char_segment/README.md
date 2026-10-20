# 蓝牌七字切分

当前提供已核对的软件阶段参考与资源预检。[接口契约](../../../docs/validation/blue-plate/char-segment/contract.md)保留为审核稿；2026-10-18按主控要求暂缓新增RTL，等待商用及论文开源方案研究后的路线决定。

项目根目录运行：

```powershell
D:/Python/python.exe -X utf8 tools/blue_plate/char_segment/reference.py
D:/Python/python.exe -X utf8 tools/blue_plate/char_segment/reference.py --q32
```

前者使用656项冻结OpenCV warp候选，后者从相同dev/val源图生成实际Q32采样输入。两者各自逐阶段对固定baseline核对，输出到 `tmp/blue-plate-char-segment/`；Q32文件加 `q32-` 前缀。reference.npz含灰度、行清理mask、组件清理mask和连续字符像素，reference.json含阈值、组件、切线、框与各字符偏移/宽高。resource-audit.json记录输入/来源哈希和队列峰值。没有heldout推理。

这些Python程序只生成离线回归向量。最终硬件运行时从perspective_roi的唯一灰度RAM切字，不依赖PC切分，不在本核重复归一化。

## 轻量整牌模型研究

新增可执行结构/成本原型；[模型与实验契约](../../../docs/validation/blue-plate/char-segment/lightweight-model-contract.md)列出C8整牌CTC候选、实际自动ROI训练适配、教师完整性风险及Ti60缓存门槛。

```powershell
D:/Python/python.exe -X utf8 tools/blue_plate/char_segment/lprnet_cost.py
```

需要本机PyTorch和 `tmp/blue-plate-review/mature-research/` 内已下载的固定LPRNet源码、权重、论文。程序不联网，不训练或保存权重；检查结构、通道抽取、浮点上下文重排、合成CTC梯度和逐层成本。成功输出 `tmp/blue-plate-char-segment/lprnet-research/cost.json`；归档见验证目录 `lprnet-cost.json`。参考实现许可证见 `lprnet-reference-LICENSE.txt`。该成本脚本不验证真实识别率、INT8等价或硬件map。

后续受限训练已执行，见[实验结果](../../../docs/validation/blue-plate/char-segment/experiment-results.md)：100步单牌检查+400步学生训练，同76调参组0正确/0错/76拒，未改善旧后端49/0/27。当前停止该候选训练；没有INT8或硬件结果。

`experiment.py` 提供 `prepare-dev`（320自动角点/Q32及整数resize）、`diagnose`（一次教师输入比较）、`sanity`、`pilot`、`rejection-probe`。训练必须已有逐ROI视觉复核表，只使用development正样本；程序拒绝覆盖已有sanity/pilot目录。输出在 `tmp/blue-plate-char-segment/experiment/`，现有产物应保留，不能靠换目录无记录追加训练。`prepare-val`只提供冻结后输入准备，本轮未调用，不是完整val评价器。

复查冻结模型、不追加训练：

```powershell
D:/Python/python.exe -X utf8 tools/blue_plate/char_segment/analyze_experiment.py
```

最新[严格拟合门槛与BN诊断](../../../docs/validation/blue-plate/char-segment/fit-gate-results.md)：`fit_gate.py`要求固定8牌连续三次8/8才放行一次独立开发训练。原配置650步通过，dropout0到2000步未通过正常eval；后续独立训练2250步停止，最佳tune4/3/69，未改善旧49/0/27。新训练共4900步，旧结果保留。

`fit_gate_analysis.py`只分析冻结权重：训练207牌正常eval38正确、当前批BN63正确；tune不使用标签或更新BN。检查点和诊断状态哈希检查通过，未保存校准模型。该差异支持下一步研究固定BN统计校准，不代表识别目标已经完成。运行已有 `fit_gate.py` 会拒绝覆盖其输出目录。

后续已完成[一次官方BN校准](../../../docs/validation/blue-plate/char-segment/bn-calibration-results.md)：`calibrate_bn.py`临时关闭dropout，仅用207train运行一遍官方update_bn，零优化器步骤，参数不变，仅BN统计改变。tune原门限5/2/69，≤3错选点8/3/65，未达到旧49/0/27；停止继续修补该checkpoint。独立产物在 `tmp/blue-plate-char-segment/bn-calibration/`，原权重保留，重复运行拒绝覆盖。

固定公开预训练LPRNet的新自动ROI对照：

```powershell
D:/Python/python.exe -X utf8 tools/blue_plate/char_segment/pretrained_new_rois.py
D:/Python/python.exe -X utf8 tools/blue_plate/char_segment/verify_pretrained_new_rois.py
```

只读取已有307个development BGR缓存，比较原OpenCV线性resize与现有Q8 resize，两组均24×94、batch1。不训练；完整保留原68类softmax和blank67，用精确CTC序列概率选择合法七字候选。门限在304development按≤3错及0错选择，同一门限用于76tune子集。输出位于 `tmp/blue-plate-char-segment/pretrained-new-rois/`；后者从冻结logits用独立动态规划复算概率和阈值。公开权重训练身份重叠未知，结果是诊断对照。

[新增数据来源核查](../../../docs/validation/blue-plate/char-segment/data-source-research.md)记录CCPD、CLPD和CRPD的标注、许可与获取状态；本轮只下载README/LICENSE文本。

[新ROI预训练对照结果](../../../docs/validation/blue-plate/char-segment/pretrained-new-rois-results.md)：原resize与Q8的304dev均285/3/16；同76tune分别70/0/6、69/0/7。冻结HS/边界组合后304dev均283/3/18，76tune不变。全部614条CTC概率与阈值已独立复核，结果供主控审核，不包含量化或RTL放行。

主控审核通过后，Q8 BGR主选门限固定为 **0.9931710550839266**，0.9386077887914179只作对照。[84校准图确认](../../../docs/validation/blue-plate/char-segment/pretrained-validation-results.md)得到严格点68/0/16，旧后端50/3/31，冻结教师组合72/0/12；门限没有按校准调参。

可复用入口为 `fixed_lprnet.FixedLPRNet`，一次加载原模型后，逐张接收uint8 BGR `(64,224,3)`，返回原始greedy、合法性、精确CTC分数及两个固定OCR门限标记。主实现的候选排序和颜色/边界门控要求见[固定推理交接契约](../../../docs/validation/blue-plate/char-segment/fixed-lprnet-contract.md)。`confirm_validation.py`保留本轮一次性确认流程，已有输出时拒绝覆盖；112heldout未读，完整拒识链待主实现重跑。

## 一次零训练W8/A8研究

[量化结果](../../../docs/validation/blue-plate/char-segment/quantization-w8a8-results.md)：仅用原207train标定，参数先冻结，再评价307dev ROI。固定严格门限下，304dev OCR从FP32的250/0/54变为229/3/72，同76从61/0/15变为55/0/21。主要损失位于最后一次通道抽取后的激活分辨率；不放行网络RTL、产品ROM或84量化确认。

`integer_lprnet.py`提供真正整数卷积、池化、能量归一化和logits参考，主机CTC仍是浮点。`quantize_lprnet.py`保存唯一候选及两项预定定位诊断，已有目录时拒绝覆盖。`analyze_integer_lprnet.py`只汇总冻结开发结果。独立检查命令：

```powershell
D:/Python/python.exe -X utf8 tools/blue_plate/char_segment/verify_integer_lprnet.py
```

完整首层、四支上下文、555项舍入和36个真实点积/4437个八路周期均通过。数组位于 `tmp/blue-plate-char-segment/quantization-w8a8/`，格式见[整数与MAC契约](../../../docs/validation/blue-plate/char-segment/integer-mac-contract.md)。主实现另已确认原FP32中部遮挡66/388错误接受，量化不构成完整性修复；完整网络仍不可部署。
