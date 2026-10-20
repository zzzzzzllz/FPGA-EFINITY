# 七字切分核计划

当前状态：2026-10-18按主控指令暂缓新增投影七字切分RTL，等待商用/论文开源方案研究后的路线决定。保留已冻结软件参考与接口；尚无本核RTL、map或板测结果。

授权写入仅限 tools/blue_plate/char_segment、docs/validation/blue-plate/char-segment、tmp/blue-plate-char-segment。既有分类、前处理、几何、共享顶层、DDR、release和candidate均只读。

1. 完成：冻结baseline算法、阅读EasyPR/OpenCV实际源码和已有Otsu/前处理接口；推导有界CCL、RAM与最坏周期。
2. 已交接：契约见contract.md。OpenCV和实际Q32两套各656个dev/val候选软件逐阶段对照全部一致；合成向量尚未补充。
3. 暂缓：独立RTL，待主控确定路线后再决定是否实施。
4. 暂缓：RTL逐阶段、逐字符像素对照，协议/极值/取消回归。
5. 暂缓：独立map、资源与周期交接；不代表整机或G1通过。

算法基准SHA256：2329329c2b90f22bb7554713b36c4771d90a015d73bdc4ee4233319b574e0a89。

## 当前限定任务：轻量整牌模型研究

1. 完成：审读LPRNet论文全文、公开复现和主控CTC结果，核对reduced结构可复现边界；加入HyperLPR3作为主要准确率参考。
2. 完成：最小候选的逐层参数/MAC/激活核算，通道抽取与上下文线性重排数值检查；无优化器步骤。
3. 已交付：lightweight-model-contract.md，包含实际自动ROI训练适配、分组/量化/置信/CTC解码、残缺拒识与Ti60资源实验边界。主控审核后决定受限实验；不以结构检查代替效果改善。

初次结构研究阶段不启动训练；后续授权受限训练见下。baseline、共享RTL和既有权重保持只读；七字切分RTL继续暂缓。

## 后续受限离线实验（主控已批准）

1. 完成：教师head/Softmax实测输出[1,20,78]，修正原T40记录；固定Q8 resize通过独立标量有理数参考。
2. 完成：从320自动角点重建307个development Q32 ROI，228/76身份组；逐图视觉复核记录由Codex作出，不冒充人工标注签字。30个非车牌/裁切/可见性不确定ROI不带完整训练标签，训练正样本207个。
3. 完成：一次RGB-native、gray-native、gray-small-restored教师比较；只读304dev，不读val/heldout。
4. 完成：100步单牌数值/拟合检查后，新初始化400步学生试验；总量500步，GPU训练计时19.65秒。无RTL扩展。
5. 完成：冻结step400/全部拒绝阈值，同76组旧后端49/0/27、学生0/0/76；训练207正样本也0完整正确。冻结权重的BN统计诊断仍0，能量epsilon无命中，梯度有限。拒识探针全拒不能计作实用拒识通过。
6. 当前候选停止训练：详见experiment-results.md。val/heldout图片未读；后续须先明确小组精确拟合门槛和新预算，再考虑优化条件/固定缩放简化/容量路线，不启动量化或RTL。

## 严格8牌拟合门槛与根因试验（主控后续授权）

1. 完成：重新阅读上游初始化、RMSprop/15epoch安排及PyTorch CTC CPU/CUDA核心；下载CUDA实现，CPU下载超时但web已读实际源码。CPU/CUDA重复标签loss/梯度对照通过。
2. 完成：冻结train ROI 0,2,3,4,9,13,28,31及源/灰度/native SHA；包含88、99、LL、11、AA重复。
3. 完成：原配置在550/600/650步连续3次8/8；dropout0到2000步未通过eval门槛。原Candidate与旧实验结果未改；不触发仅在两者都失败后授权的第三条件。
4. 完成：原配置从seed701重置，207train独立训练2250步触发预定无改善停止。最佳1250步tune4/3/69；零错条件1/0/75，未改善旧49/0/27。
5. 完成：冻结权重诊断207train正常eval38正确、当前批BN63正确；tune仅无标签预测/长度/能量诊断，track_running_stats=False，逐张量确认无缓冲区/参数更新，未保存诊断模型。
6. 已交付fit-gate-results.md与fit-gate-summary.json。新训练总4900步/281.09秒；未读val/heldout、未量化/RTL。仅提出冻结权重、关闭dropout、用train重估固定BN统计的最小后续方向，尚未执行校准。

## 一次官方BN校准（主控后续授权）

1. 完成：复制1250步best，临时Dropout.p=0，按原顺序207train、batch16调用官方update_bn一次；恢复p/eval并先冻结独立产物，再评价tune。
2. 完成：全部参数逐项不变，仅18个BN buffer改变；各counter13，原checkpoint与评价期间状态不变，优化器步骤0。
3. 结果：train38→66/207；tune原门限4/3/69→5/2/69；≤3错选点8/3/65，未达到旧49/0/27。停止继续修补这个checkpoint。
4. 已交付bn-calibration-results.md/summary.json。覆盖审计41/65类、24省未见，但tune仅2身份含未见字符；不能把多数失败归为缺省份。后续建议准备最多2048新增独立development正ROI清单，当前未下载图像或新增训练。

## 固定预训练LPRNet＋新320/Q32候选（零训练）

1. 完成：核对公开loader的BGR、24×94、float32归一化及模型全batch能量均值；复用原模型、68类权重，固定batch1。
2. 完成：307个BGR ROI缓存哈希与历史冻结一致；304dev/76tune身份不变。每ROI与冻结HS、颜色分类及角点/框记录逐一匹配，不复用教师OCR接受标记。
3. 完成：原resize与现有Q8 BGR两组OCR单独均285/3/16（304dev，≤3错），相同76子集分别70/0/6、69/0/7；组合门控均283/3/18，76子集不变。0错点与原始贪心结果分列报告。
4. 完成：只读CCPD/CLPD/CRPD元数据核查，保存README/LICENSE与哈希；没有新增图像、训练、量化或RTL。
5. 完成：两组614条logits独立动态规划复算、候选选择、阈值最优性和原输入/模型状态不变检查通过。结果和输入已冻结，见pretrained-new-rois-results.md；待主控审核，不放行RTL。

## 固定Q8入口与84校准确认（主控后续授权）

1. 主控独立重跑614次推理、logits逐元素与CTC/门限复核PASS，见其pretrained-new-rois/review-result.json。
2. 完成：固定严格门限0.9931710550839266为主选，0.9386077887914179仅对照；读取84校准图前写协议，之后未调门限。
3. 完成：同320角点→整数Q32/Q5→85个224×64 BGR ROI→Q8 24×94。严格点OCR/组合均68/0/16；既定对照OCR76/2/6、组合75/2/7。旧后端50/3/31，冻结教师组合72/0/12。
4. 完成：fixed_lprnet.py薄封装入口与交接契约；4个开发ROI logits完全一致，85条校准CTC DP及逐图固定门限选择独立复核通过，原开发产物和模型状态不变。
5. 交接：pretrained-validation-results.md、fixed-lprnet-contract.md及逐图冻结结果。未读112heldout，无训练/量化/RTL；完整拒识链由主实现后续重跑。

## 零训练W8/A8开发可行性（主控后续授权）

1. 完成：读取LiteRT ConvPerChannel/QuantizeMultiplier、CMSIS-NN重定标与PyTorch融合/observer实际源码；下载GreenWaves厂商实现及TFLite，解析实际25算子结构，不执行其代码或引入依赖。
2. 完成：原207train统计min/max，先冻结唯一W8/A8参数，再评价307dev；不调门限。当前候选严格OCR304dev 229/3/72、76子集55/0/21，低于FP32 250/0/54、61/0/15。
3. 完成：两项预定混合精度诊断支持主干量化为主要损失。tap2范围约300、通道抽取后范围约8.31，共用1.177步长，抽取输出仅8个整数值。尚未实施按消费者分别量化的下一候选。
4. 完成：整数参考、逐ROI误差、真实36点积/4437八路周期及独立重放/NumPy/Fraction验证。交付quantization-w8a8-results.md、integer-mac-contract.md和冻结清单。
5. 状态：算术通过，精度未通过；主机CTC仍浮点。84量化确认待主控另行授权，112heldout未读，训练步骤0，无产品ROM或网络RTL。原FP32遮挡66/388错误接受仍是完整网络部署阻碍。
