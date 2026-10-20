# 固定Q8 BGR LPRNet推理交接

2026-10-18。入口：`tools/blue_plate/char_segment/fixed_lprnet.py` 中的 `FixedLPRNet`。只作已冻结模型的离线推理，供主实现调用；不训练、不拟合阈值、不包含检测、颜色门控或RTL。

## 输入与原模型

- 每次调用只接受 `numpy.ndarray`，dtype为uint8、shape严格为 **(64, 224, 3)**，通道顺序 **BGR**。
- 输入已由调用者完成：720p画面上的320检测整数角点 → `geometry_sampler.sample_integer(frame, points, 32, integer_solver=True)`。该函数解算Q32矩阵、以Q5坐标做双线性采样，输出224×64 BGR。不得用标注框替代自动角点。
- 入口复用既有 `experiment.resize_q8`，缩至24×94，再执行float32 `(pixel−127.5)/128`、CHW；始终CPU、batch1、eval、dropout0。四个分支保留原源码对整个张量的能量均值，不增加epsilon或改为批处理。
- 原模型、loader、权重从 `tmp/blue-plate-review/mature-research/lprnet/` 加载，初始化时核对三者SHA256。模型结构直接导入，未复制网络或新建框架。
- 保留完整68类与blank67，I/O仍占softmax概率质量；七字语法不接受I/O。序列解码复用冻结脚本 `pretrained_new_rois.decode`。

原始loader和模型实现已在先前研究中实际下载、阅读；本轮再次核对[上游loader](https://github.com/sirius-ai/LPRNet_Pytorch/blob/master/data/load_data.py)与[模型源码](https://github.com/sirius-ai/LPRNet_Pytorch/blob/master/model/LPRNet.py)。原比较脚本和开发冻结产物保持不变；新入口沿用同一加载过程，4个开发ROI重跑logits逐元素完全相等。

## 固定门限

| 常量 | 数值 | 用途 |
|---|---:|---|
| `STRICT_THRESHOLD` | **0.9931710550839266** | 主选；所有后续确认及主实现使用此值 |
| `COMPARISON_THRESHOLD` | 0.9386077887914179 | 仅保留既定对照，不作严格门限拒绝后的回退 |

二者来自既有304dev的Q8结果，在读取84校准图之前锁定。本轮不重选、不扫描、不按84校准结果调整。76tune属于304门限拟合集的子集，不称独立验证。

## 返回值

`recognizer(roi_bgr)` 返回dict：

| 字段 | 含义 |
|---|---|
| `code` | 原始CTC贪心字符串，包含不合法长度的结果；不补字、不纠错 |
| `legal` | 是否符合普通七字语法 |
| `sequence_log_probability` | 原68类概率下，对该贪心字符串的所有CTC路径求和后取log |
| `score` | 合法七字时为 `exp(sequence_log_probability/7)`；非法时为None |
| `strict_accepts` | 仅OCR条件：legal且score≥严格门限 |
| `comparison_accepts` | 仅OCR条件：legal且score≥对照门限 |
| `greedy_path`、`decoded_ids` | 18步原始路径及去重复/blank后的类别索引 |
| `logits` | float32 NumPy数组，shape (68,18)，供数值回归；序列化JSON前移除 |

灰度、float输入、错误尺寸、外部batch或train模式会明确报错。模型只加载一次，随后逐ROI调用。入口不会调整全局线程数；复现本轮参考时调用者先设PyTorch线程数4。

```python
from pathlib import Path
import sys
import torch

sys.path.insert(0, str(Path('tools/blue_plate/char_segment').resolve()))
from fixed_lprnet import FixedLPRNet, STRICT_THRESHOLD

torch.set_num_threads(4)
recognizer = FixedLPRNet()
result = recognizer(roi_bgr)  # uint8, (64, 224, 3), BGR
ocr_accepts = result['strict_accepts']
```

## 选牌和完整链边界

主实现对各自动ROI分别推理，先按合法性和当前固定颜色/边界条件筛候选，再按 `(score, -roi_index)` 最大值选牌，最后使用严格门限。标签不得参与选牌。OCR单独统计可只按合法性筛选；两种统计须保留区别。

固定颜色/边界组合仍使用原生透视crop的冻结规则：学习型颜色类别0，HS蓝计数大于黄计数，raw角点与检测框边距均≥1。HS条件为蓝 `100<H<140`、黄 `15<H<40`，共用 `95<S<255`，不设V条件。本次没有改成在Q32 ROI上计算颜色，入口本身也不读取教师OCR置信度或其接受标记。

`strict_accepts`不是完整系统的接受标志，边界门控也不证明字符全部可见。主实现交接后需继续重跑完整拒识链；本轮不放行量化、RTL或部署。

## 复核产物

[84校准结果](pretrained-validation-results.md)及 `tmp/blue-plate-char-segment/pretrained-validation/` 保存读取校准图前的协议、85条ROI输出/logits、84条逐图选牌及固定门限结果。开发产物、模型状态和输入哈希保持不变。
