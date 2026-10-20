# 原工程 A/B 灰度与梯度参考

用于定位研究的独立整数参考，读取原 `edge-quality-30fps` 的实际计算规则，不修改产品。A 是主 `sobel_pair` 梯度；B 是 `median_pair` 内为去噪前后比较计算的原灰度梯度。输入是 **DDR原帧解包后的 uint8 RGB、HWC、完整图像坐标**。不读取开发数据集，不实现定位、OCR、NMS或全帧Canny连接。

## 接入入口

项目根目录下可直接导入；使用已有 NumPy，无新增依赖：

```python
from tools.blue_plate.edge_reference.reference import compute

# rgb.shape == (H, W, 3), dtype=uint8, channels R/G/B.
# 用OpenCV读取的BGR图像须先显式转为RGB；这里不会猜测或自动换通道。
r = compute(rgb, config=0x6838, recognition=False)
a_gx, a_gy = r["a_gx"], r["a_gy"]  # int16; signed 11-bit RTL values
b_gx, b_gy = r["b_gx"], r["b_gy"]  # independent of page filters
```

CLI接受 `.npy`，输出 `.npz` 及同名 `.json` 输入/输出哈希清单：

```powershell
D:/Python/python.exe -X utf8 tools/blue_plate/edge_reference/reference.py --input tmp/blue-plate-edge-gradient-reference/example-rgb.npy --output tmp/blue-plate-edge-gradient-reference/example-a-box-b-raw.npz --config 0x6838 --recognition
```

不要先对图像缩放或用通用灰度转换再调用本入口。若实验本身要求改变分辨率，应把它单列为适配，A/B使用相同输入，并保留输入像素哈希。当前接口明确检查uint8、三通道、H≥2及偶数W≥4；720p符合范围，小样测试不等同于完整720行时序验证。

| 输出键 | dtype / 形状 | 含义 |
|---|---|---|
| `b_gray` | uint8 / H×W | 实际DDR-read灰度；B的输入 |
| `median_y` | uint8 / H×W | 按配置选择的中值/原灰度 |
| `a_gray` | uint8 / H×W | 中值及可选平滑后的主Sobel输入 |
| `a_gx,a_gy,b_gx,b_gy` | little-endian int16 / H×W | 有符号梯度，不取绝对值、不裁到8bit、不清边界 |
| `a_magnitude,b_magnitude` | little-endian uint16 / H×W | `abs(Gx)+abs(Gy)`，对应11bit RTL量 |
| `a_direction,b_direction` | uint8 / H×W | 0水平、1垂直、2同号斜向、3异号斜向；B的direction是参考派生量，原median模块没有该端口 |
| `a_edge,b_edge` | uint8 / H×W | 值0或1，严格大于T，图像最外圈清零；**不是Canny最终accepted图** |
| `input_rgby,median_rgby,a_input_rgby,a_output_rgbe` | uint32 / H×W | 测试/适配载荷。高字节是灰度或0/255边缘；低24位受比较模式影响，不能始终当RGB |

`array_hashes()`记录每个数组的shape、端序dtype和C-order字节SHA256。`.npz`文件哈希另用于交付检查；比较算法输出时使用逐数组哈希。供成熟定位器比较 `abs(Gx)` 时，应显式选择11bit值或显式 `min(abs(Gx),255)`；后者是EasyPR式适配，不是硬件原输出。

## 精确整数规则

1. **灰度**：来自 `frame_store_dma.v` 的 `luma()`，`(77R+150G+29B+128)>>8`。没有先归一化、浮点计算或OpenCV色彩系数。输入RGB已经过相机白平衡，本参考不模拟Bayer重建。
2. **边界**：中值、平滑、Sobel每一级分别复制最近边界像素。不能仅在最初补边一次，也不能使用OpenCV默认反射边界。双像素先高32位（左/even列）、后低32位（右/odd列），对应两lane的Gx0/Gy0及Gx1/Gy1。
3. **中值**：`config[11]`控制3×3九个灰度值的第5小值。关时数值旁路，原RTL的窗口延迟仍存在。
4. **平滑**：`config[13]=0`时数值旁路；为1且recognition=False时使用 `[1,2,1]ᵀ[1,2,1]`、`(sum+8)>>4`；为1且recognition=True时使用3×3均值、`(sum+4)//9`。每级单独舍入为8bit后再做Sobel。合法uint8输入下这些结果不超出0…255，不发生饱和或回绕。
5. **梯度**：Gx为右列加权和减左列；Gy为下行加权和减上行。权重1/2/1，有符号11bit足够容纳±1020，不缩放、不8bit饱和。L1和仍保留11bit。方向依次比较 `abs(Gy)*256 <= abs(Gx)*106`、`abs(Gy)*106 >= abs(Gx)*256`，再按符号选斜向；零梯度方向为0。
6. **边缘与flags**：T是 `config[10:0]`，比较为 `magnitude>T`；只对二值mask清最外圈。`config[12]`改写比较载荷，不改梯度输入；`config[15:14]`是后续Canny低阈值比例，不改Gx/Gy；recognition在Canny位为0时无数值影响。两类signed梯度在边界可非零。

`config[12]=1`时低24位成为 `{original_Y,median_Y,raw_edge*255}`，用于03页前后比较。`a_input_rgby`高字节是A灰度，`a_output_rgbe`高字节是A二值边缘；两者保留同一比较载荷。

## 12页的梯度等价类

以下比较前提是**同一张DDR原RGB及同一坐标**，不表示不同实拍帧或回放帧数值相同。页面映射来自 `edge_ui.v` 和顶层的帧边界配置；没有重新运行完整UI/DDR仿真。

| 页面 | A梯度类别 | 变化说明 |
|---|---|---|
| 01彩色、02灰度 | A0：原灰度 | 两者梯度相同，且A0=B |
| 03中值比较 | 默认A1：中值；关闭中值为A0 | K3灰度/边缘比较只改显示，不改变梯度；中值开关改变A |
| 04Sobel、05阈值 | A1 | T改变二值边缘，不改变梯度 |
| 06Canny | A2：中值＋高斯 | 低阈值比例改变后续分类，不改变梯度 |
| 07红边 | 默认Canny为A2；切Sobel为A1 | 两种滤波不同；恢复保存的T不改对应类别内的梯度 |
| 08形状 | A3：中值＋均值 | 与普通Canny不同；调T不改梯度 |
| 10单帧、11录像、12回放、13四格 | A0 | 帧来源/节奏不同。13页取algorithm job的完整原帧，不取显示拼图 |

**B在全部页面配置下相同**，因为它在中值之前从DDR灰度计算；`b_edge`仍受T影响。A0/A1/A2/A3对一般图像不同，常量图等特殊输入可碰巧相等，不能要求每张图都不同。JTAG可形成无中值的高斯/均值等额外组合，参考同样支持，有限测试也包含；这些不称为第13种展示页。

四个典型调用：A0=`compute(rgb,0x4038,False)`；A1=`0x4838,False`；A2=`0x6838,False`；A3=`0x6838,True`。03页默认比较载荷用`0x5838,False`，梯度仍为A1。调用参数中的T=56仅为展示默认值，不替定位算法选择阈值。

## RTL对照与交付证据

运行：

```powershell
D:/Python/python.exe -X utf8 tools/blue_plate/edge_reference/run_validation.py --smoke
D:/Python/python.exe -X utf8 tools/blue_plate/edge_reference/run_validation.py
```

`tb_gradients.sv`直接实例化未修改的原 `edge_algorithm_pair`，包含真实median、gaussian、Sobel、NMS及cleanup。输入灰度调用保持复位的原DMA实例的 `luma()`，与参考灰度比较后送入算法。此项证明灰度数值及双像素顺序，**没有模拟AXI原帧解包、CDC或帧管理**。

A观测点是 `gradient_stage.gx*/gy*`，仅在 `s_valid && advance`采样，使用同级 `s_sof/s_eol/s_eof,s_id,s_epoch,s_flags,s_threshold`；B是 `median.raw_gx*/raw_gy*`，仅在 `valid_pipe[0] && advance`采样，使用同级 `marks[0],id_pipe[0],epoch_pipe[0],config_pipe[0]`。这些是仿真层级探针，**不是新产品输出端口**。禁止将早级梯度和晚级 `out_valid`直接拼接。

另外逐像素检查中值输出、原灰度/原边缘、平滑完整载荷、Sobel输出幅值/方向/边缘、flags和T；随机输入空拍、连续反压、行尾/帧尾、帧中故意改变外部config/id/epoch、不同图连续任务均参与对照。下一任务在前任务完整输出结束后开始，符合原单job约束；不声称支持帧间流水重叠。最终NMS/cleanup只检查完成计数、标签和停顿保持，本轮不重新验收其像素算法。

有限测试使用黑白、RGB左右lane、灰度半整数舍入、正负横纵阶跃、角点脉冲、棋盘、梯度等于T、彩色纹理和后续黑帧。主小图遍历24种配置，分别带反压和连续流；另测非二次幂行宽6×4及1280×6短帧。**不跑开发图集、不跑OCR、不运行映射或板卡**。

证据目录：`tmp/blue-plate-edge-gradient-reference/`。

最终结果：648个合成帧、每处tap 212256像素全部一致；两个tap共424512个像素位置，各含Gx和Gy。16×12反压/连续流各312帧，6×4和1280×6各12帧。测试汇总有A梯度停顿54355周期、B梯度停顿31356周期；Sobel输出行尾停顿3991周期、帧尾停顿311周期，均执行保持断言。6×4小帧只在最终输出发生停顿，前级为零，如实保留。

数值覆盖确认：灰度恰好半整数192处，高斯半整数400处，均值除以9的余数0…8全覆盖，Gx/Gy两者都覆盖-1020和+1020。幅值128的阶跃在T=127时有20个内部边缘点，T=128/129时为0，验证严格大于。CLI与import全部输出数组及dtype一致，反压/连续流的输入与A/B梯度文件相同；8个被依赖的产品RTL文件哈希未变。

- `report.json`：最终整套结果、命令、原源码/参考代码哈希、输入/期望/实际输出哈希。
- 各测试目录的 `vectors.json`：逐样本、逐配置的输入RGB及所有参考数组哈希；`observed-a.mem/observed-b.mem`是RTL实际观测值，与期望文件逐字节比较。
- `handoff.json`：CLI与import输出一致性、数值边界覆盖、12页映射及四类梯度哈希；`example-rgb.npy`和`example-a-box-b-raw.npz`可直接用于接入检查。
- `smoke-report.json`：前期12个小帧交接证据，若以后修改验证脚本，其脚本哈希只对应该次小样，最终以`report.json`为准。
- `smoke/initial-warning.log`保留最初26bit向量写了8位hex造成的宽度警告；已改为7位。`nonpower-width/initial-coverage-check.log`保留最初对每个尺寸强制全级停顿覆盖的失败；6×4帧可在反压到达前级前排空，最终按整套测试汇总覆盖，保留各尺寸真实计数。两项均未修改RTL或放宽像素比较。

研究依据：先阅读已有 `tests/tools/canny_reference.py` 的显式补边及整数流水线参考，再读取实际RTL；联网核对 [OpenCV deriv.cpp的3×3导数核](https://github.com/opencv/opencv/blob/4.12.0/modules/imgproc/src/deriv.cpp#L110)。只借用标准整数卷积机制，未复制上游代码、运行外部脚本或采用OpenCV默认边界。与EasyPR默认5×5平滑、8bit饱和Gx、Otsu/闭运算等适配差异沿用上一份审计，定位器窗口另行处理。

合成图逐像素一致证明这份参考准确对应现有计算，不证明定位效果、真实视频框稳定性或红边闪烁已改善。
