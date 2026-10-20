# 蓝牌字符整数分类候选

当前单一接入候选为 `candidate/` 的 320→65 线性分类器（C=0.1）。它用于主实现的集成评估；真实开发集仍有误接受，不能当成已通过整牌验收的模型。完整比较及失败分析见 [验证报告](../../../docs/validation/blue-plate/char-model/report.md)。本目录不修改主实现RTL。

独立算术RTL现位于 `rtl/char_linear.v`，仿真和单模块Efinity综合命令见 [RTL交接](../../../docs/validation/blue-plate/char-model/rtl.md)。它不接现有顶层，也不代表整牌通过。

同一内核现支持 `WEIGHT_BITS=10/11`，默认10位ROM路径及门限不变，其他位宽明确报错。geometry 的11位实验ROM与单核参数包装位于 `experiments/geometry11/`，见 [受控硬件验证](../../../docs/validation/blue-plate/char-model/geometry11-hardware.md)。该实验没有覆盖candidate或建立第二套分类逻辑。

## 无训练数据自检

在项目根目录运行：

```powershell
D:\Python\python.exe -X utf8 tools/blue_plate/char_model/verify.py --candidate tools/blue_plate/char_model/candidate
```

检查导出的 16/10 位权重 ROM、32 位偏置、102 条真实字符/拒识/同分向量及标量整数运算。预期 `exact: true`。原始 65 类分数与按位置约束的预测分别记录。

```python
import sys
sys.path.insert(0, 'tools/blue_plate/char_model')
from model import predict
# roi 必须是切好的二维0/1白字掩码；位置0..6。
result = predict(roi, position=0, model_dir='tools/blue_plate/char_model/candidate')
```

`predict` 是离线整数参考，NumPy 不进入 FPGA。主实现可按 `interface.json` 实现同样的串行乘加。不得把 `accepted` 当成车牌区域检测或非字符检测；上游仍须确认有效字符区域，七字结果由整机一起提交。

## 前处理与 ROM 契约

- 将亮字置1，背景置0；空白或少于4个前景像素报错，不翻转极性。
- `predict`接收**原始裁剪mask**并只归一化一次。ROM测试向量中的`input`已经归一化，应直接`features→integer_scores→decide`；不能再传给`predict`。主控在3897个test canonical masks中测到74个二次归一化后变化，最近邻采样可能丢失边缘像素，因此不能假设幂等。
- 裁前景紧包围框，保比例放入28×28，再居中放入32×32。缩放尺寸按整数四舍五入，采样坐标为 `floor(dst*src_size/dst_size)`。具体边界公式在 `normalize`；不用 OpenCV 插值代替。
- 320个特征依次为16×16网格的2×2计数乘8（行优先），32列计数，32行计数。范围0..32，使用无符号6位。
- 类别ID0..30为 `皖沪津渝冀晋蒙辽吉黑苏浙京闽赣鲁豫鄂湘粤桂琼川贵云藏陕甘青宁新`；31..54为 `ABCDEFGHJKLMNPQRSTUVWXYZ`；55..64为 `0123456789`。
- 权重为Q8，偏置为Q13。`score[c]=b[c]+sum(x[i]*w[i,c])`，不加激活、不再移位。推荐32位有符号累加；全部合法特征的保守绝对上界为349142，20位有符号即可容纳。类别分差建议继续使用32位，避免减法符号错误。
- `.mem` 按输出类别优先排列，地址 `c*320+i`。`w1.mem` 为16位补码，`w1-s10.mem` 为同一权重的10位补码；三位十六进制是文本写法，应按10位符号扩展，不能当12位补码。`b1.mem` 为32位补码。NPZ矩阵为输入×输出。
- RTL默认读取逐行10位二进制的 `w1-s10.bin`，数值与signed10 hex一致；此格式避免Efinity的hex宽度警告。
- 位置0允许ID0..30；位置1允许31..54；位置2..6允许31..64。同分取较小ID。次佳必须为不同类别。
- 默认门限：省份 `score>=-1351 && margin>=4245`；字母数字 `score>=-20593 && margin>=3556`。分数不是概率。更严格的验证集零错误门限单列在 `strict_operating_point`，未替换默认门限。

## 重新生成证据

依赖已安装的 Python、NumPy、OpenCV、scikit-learn、threadpoolctl。训练数据来自已有 `tmp/blue-plate-g1/characters` 和 `chinese-gray/annCh`；来源与内容哈希保存在 `tmp/blue-plate-char-model/manifest*.json`。

```powershell
D:\Python\python.exe -X utf8 tools/blue_plate/char_model/experiment.py prepare
D:\Python\python.exe -X utf8 tools/blue_plate/char_model/experiment.py train
D:\Python\python.exe -X utf8 tools/blue_plate/char_model/roi_diagnostic.py prepare
D:\Python\python.exe -X utf8 tools/blue_plate/char_model/roi_diagnostic.py score --model linear0.1 --audited 3,6,7,8,9,28,29,39,40,60,62,65,69,71,75
D:\Python\python.exe -X utf8 tools/blue_plate/char_model/roi_diagnostic.py score --model mlp64 --audited 3,6,7,8,9,28,29,39,40,60,62,65,69,71,75
D:\Python\python.exe -X utf8 tools/blue_plate/char_model/roi_diagnostic.py score --model mlp128 --audited 3,6,7,8,9,28,29,39,40,60,62,65,69,71,75
D:\Python\python.exe -X utf8 tools/blue_plate/char_model/confidence.py
D:\Python\python.exe -X utf8 tools/blue_plate/char_model/verify.py --model linear0.1
D:\Python\python.exe -X utf8 tools/blue_plate/char_model/verify.py --model mlp128
D:\Python\python.exe -X utf8 tools/blue_plate/char_model/export.py
```

ROI生成依赖主窗口 `baseline.py`，其SHA-256记录在 `roi-records.json`。主窗口继续修改切分后，新生成ROI不应被声称与本次冻结诊断相同；本次冻结掩码在 `tmp/blue-plate-char-model/roi-masks.npy`。公开CCPD最终测试图标签没有进入训练或门限拟合。内容拆分不等于原车辆身份隔离。

EasyPR代码和训练数据的许可说明及来源见 [research.md](../../../docs/validation/blue-plate/char-model/research.md)，许可证副本为 `LICENSE-EasyPR.txt`。本目录分类实现为新写的整数参考，权重由EasyPR训练数据离线训练导出。
