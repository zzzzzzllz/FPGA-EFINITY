# Q8预训练LPRNet：84张校准图固定门限确认

2026-10-18。主选严格门限 **0.9931710550839266** 在既有84张校准图上得到 **68正确／0错误接受／16拒绝**；OCR单独和固定颜色/边界组合结果相同。旧后端为50/3/31，因此这批样本上增加18个完整正确号码，同时消除3个错误接受。冻结教师组合为72/0/12。

本轮开始前已冻结两个开发门限，未利用校准结果重选。预训练权重的历史身份重叠未知；本次是固定方案在既有校准split上的离线确认，不称独立泛化测试。76tune属于304门限拟合集的子集，本轮未把它改称验证集。

## 同84张图结果

数字为正确／错误接受／拒绝。

| 方法 | 固定门限 | 结果 |
|---|---:|---:|
| Q8 LPRNet，OCR单独，主选严格点 | **0.9931710550839266** | **68/0/16** |
| Q8 LPRNet，固定颜色/边界组合，主选严格点 | 同上 | **68/0/16** |
| Q8 LPRNet，OCR单独，既定对照点 | 0.9386077887914179 | 76/2/6 |
| Q8 LPRNet，固定颜色/边界组合，既定对照点 | 同上 | 75/2/7 |
| Q8 LPRNet，原始合法贪心，OCR单独 | 无置信门限 | 77/4/3 |
| Q8 LPRNet，原始合法贪心，固定组合 | 无置信门限 | 76/4/4 |
| 旧切分分类后端，冻结输出 | 原既定规则 | 50/3/31 |
| 教师原生crop，冻结HS/颜色/边界组合 | 原既定规则 | 72/0/12 |

教师对照读取同84张图的 `color-candidate-confirmation/records.json` positive/validation记录，使用其 `candidate_selected`；它仍包含教师自己的原置信门控。旧后端读取 `full-dual-local-geometry/results.json` automatic/validation记录。没有混入其他split或重新调整教师规则。教师使用原生透视crop，本次LPRNet使用Q32定尺寸ROI，不能把二者差距全归于识别网络。

对照门限的两个错误为sample106的“闽G1102K→皖G1102K”（score 0.9762386061398519）和sample463的“皖AE8110→皖AL8110”（0.9828134823004839），主选严格门限均拒绝。颜色门控额外拒绝sample57“皖AT357W”，使对照点少一个正确接受；严格点本已拒绝，因此主选指标不变。

## 输入、入口和验证

1. 读取前写入 `protocol.json`，锁定两门限、84个sample_index、源码和元数据哈希；禁止输出目录覆盖。
2. 复用 `experiment.prepare('validation')`，只对split=validation的84张图读取源字节并核对SHA。复用既有720p适配和320检测整数角点，经整数Q32矩阵/Q5采样生成 **85个224×64 BGR自动ROI**。未使用标注框或完整号码选择候选，未读取112heldout图片。
3. `fixed_lprnet.FixedLPRNet`仅接受单个uint8 BGR 64×224×3输入，复用Q8 resize至24×94及既有CTC解码，保持原68类/blank67、batch1和能量归一化。入口、返回字段、两个固定门限与颜色门控边界见[交接契约](fixed-lprnet-contract.md)。
4. 每ROI与冻结颜色记录按sample_index/candidate_index关联，核对源路径、四角、框与原教师输出一致，只提取颜色类别、HS计数和边距。LPRNet接受逻辑不借用教师OCR置信度。
5. 新入口先对开发ROI 0、1、13、306复跑，logits与主控已审核的Q8冻结数组逐元素完全相等。全部85条校准logits用独立NumPy CTC动态规划核对，最大log概率差 **7.15×10⁻¹⁶**。
6. 独立重建每图候选排序与两个固定门限结果，全部一致；没有门限扫描。非法dtype、尺寸、灰度、batch和train模式均明确报错。模型state_dict逐项不变，开发交付冻结哈希不变。

本轮优化器步骤0，没有BN更新、量化或RTL。保持严格点为主选；完整拒识链由主实现接手后重跑，本轮没有以这些正样本结果代替拒识验收。

## 产物

- 入口：`tools/blue_plate/char_segment/fixed_lprnet.py`。
- 一次性确认脚本：`tools/blue_plate/char_segment/confirm_validation.py`；存在输出时拒绝覆盖。
- 缓存：`tmp/blue-plate-char-segment/experiment/val-inputs.npz`、`val-manifest.json`。
- 确认目录：`tmp/blue-plate-char-segment/pretrained-validation/`，包含protocol、roi-records、frame-records、logits、results、verification和冻结清单。
- 逐图完整输出在 `frame-records.json`，逐ROI原始greedy/合法性/CTC分数在 `roi-records.json`，无删减错误项。

校准缓存SHA256：`33d44d3cd29ebcea00a9d536365d2512162ec0b8f3d854d64467db7ddf956bb3`。

校准manifest SHA256：`7879b0ae9c8b37b74641ff4bbb6fd530f784bb108022ed2eb8f21b6d919e7511`。
