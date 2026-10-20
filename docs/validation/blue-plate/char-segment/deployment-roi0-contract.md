# 冻结整数模型部署清单与 ROI0 golden

2026-10-18。本次只执行开发 ROI0 一次整数前向：按清单调用已有整数卷积核、分叉核及冻结上下文公式。结果为 **皖AF3188，接受**；全部 1,224 个最终 int16 logits、五组原分叉向量、贪心路径、七字符目标、Q30 区间均与冻结结果一致。Q30 区间为 **[1073477593, 1073478856]**。

本交付供完整硬件对接使用。没有重新量化、训练、调阈值、运行其他 ROI、生成产品 ROM 或修改 RTL。相对 arena 仍为 **7,052,352B，51 RAM／8 DSP**；基址保持符号化，不分配物理 DDR 地址。硬件资源、端口时序及整机运行仍由相应窗口验证。

## 入口与执行

- 导出器：`tools/blue_plate/char_segment/export_lprnet_deployment.py`
- 清单：`tmp/blue-plate-char-segment/deployment-roi0/manifest.json`
- 数组：同目录 `golden.npz`，54 个命名数组，各数组的形状、类型、布局和 C-order 字节 SHA256 均在清单中。
- 验证：同目录 `verification.json`。
- 重定标明细：同目录 `requantization.csv`，每行给出层名、shift、通道数及对应输出数。
- 本次冻结：同目录 `delivery-freeze.json`。

只检查已交付文件及重放置信度，不运行网络：

```powershell
D:\Python\python.exe tools/blue_plate/char_segment/export_lprnet_deployment.py verify
```

导出入口为 `export --output <新目录>`，拒绝覆盖已有目录。它只取固定开发 ROI0。**本次已执行一次，不需要为了验证再次导出。** `plan(config)` 生成清单，`run(operators, config, parameters, bgr)` 执行清单；保存后的 `manifest.operators` 可直接作为该函数的 `operators` 参数。`confidence()` 重放固定 Q30 算法。`verify` 不调用 `run`。

没有引入另一种模型格式：`config_stage`、`config_tap` 索引原 `quantization-tap2-fork/integer-config.json`，权重、偏置、M 和 shift 均引用原 `integer-parameters.npz` 的键。清单同时记录原 NPZ 存储类型和硬件语义类型，例如 M/shift 原来是 int64 容器，硬件分别是 uint31/uint6。

## 数据及算子合同

清单含 26 个网络步骤和 9 个置信度步骤。网络步骤包括输入转换、16 个卷积、3 个池化、4 个上下文分支、逻辑 concat 及高度和。分叉卷积额外产生细尺度输出和原 int32 accumulator 边界；四个上下文步骤各自展开两遍窗口、能量、全宽 gain 与归一化。

- 输入为已冻结的 Q8 插值 BGR `[24,94,3]` uint8，减128并转 `[1,3,24,94]` int8，输入尺度1/128、zero0。
- golden 特征采用 NCHW；设备特征槽采用紧密 HWC，地址为 `feature_region_base + slot*262144 + offset + (h*W+w)*C+c`。每个网络算子的输入输出形状及读写槽位均在 `operators` 内。
- 卷积权重采用 OIHW，K 顺序为输入通道、ky、kx。padding 填该层的输入 zero，不能统一填整数0。偏置已含输入 zero 修正，点积使用原 int8 输入，不能再次减 zero。
- 完整 K 累加与偏置在 int32；可选 ReLU 后乘 M，用 signed64 保留乘积，只做一次最近偶数舍入，然后加输出 zero 并饱和为 int8。分段 K 必须先完成全部累加。
- 三个池化均为无 padding 的3×3空间 max，再按通道步长取样；步长分别为1、2、1。最后一处的1是因为 tap2 细分支已选出原通道0,4,…,252。
- tap2 粗分支256通道、细分支64通道，两者均由同一组原 int32 accumulator 重定标。粗 A8 不能作为细分支输入。输出槽粗支偏移0、202,752B，细支偏移202,752、50,688B；两者合计253,440B。每块12空间点对应3,072B粗支及768B细支。
- 原输入保留至所有分叉读结束；粗支保留至上下文第二遍结束；细支保留至 pool14 最后一次读取。宽乘法复用 MAC 时，仍须遵守原补充合同中的原始 psum 保存、恢复、双路消费后释放顺序。
- `context.i.average` 是**中心化整数窗口和**，没有除以窗口面积。清单保留旧命名以便和既有 trace 对照。窗口和采用 uint16 文件容器，硬件最多14bit。
- 上下文第一遍累加 `E=sum(v*v)`，然后计算 `gain=RNE(C_Q30*N/E)`；第二遍重读同一 tap 并重算 v，生成 `clip_int8(RNE(v*gain/2^30)-128)`。E为0明确报错。gain 最多53bit，禁止截为32bit；能量最多41bit，分子最多53bit，乘积使用uint64容器且严格小于2^53。
- 每个 tap 的上下文在主干继续之前完成，随后只保留归一化 A8。四支采用已冻结的分区偏移0／4608／13824／32256及行距1152／2304／4608／1232，合计37,184B。已验证按这些行距打包和读回一致。
- concat 是原分支0、1、2、3的逻辑通道拼接，不额外分配物理 concat。完整516项 projection 在每个 `(class,h,t)` 处先完成重定标和 A8 饱和，再累加4行 `(q−63)`。最终 `[1,68,18]` int16 logits 的尺度为0.2953726375804228，没有额外 A8 重定标。

golden 中的全 accumulator、全窗口和、concat 以及19行 DP 历史仅供主机核对；设备不按 golden 数组总量分配存储。projection 可以按最多16空间点的1,088B A8块立即更新既有 logits 银行；最终 logits 有效负载2,448B。

## Q30 边界

`ctc.greedy_path` 为18个类ID，`ctc.target` 为7个字符，`ctc.extended_target` 为15状态。ROI0 末尾两个“8”由 blank 分开，包含重复字符禁止跨两状态转移的实际路径。

`ctc.difference`、`ctc.exp`、`ctc.exp_sum`、`ctc.emissions` 保存逐列差值、exp上下界、68类上下界和、发射概率；`ctc.states` 形状为 `[19,15,2]`，第0行为初始化，其余18行为各时间步计算后状态。bounds轴始终按 lower、upper 排列。全部状态已从保存的 logits 重新计算，并逐元素比对；末状态区间同时与冻结 `ctc_bounds` 和 ROI0 历史结果核对。

冻结判断保持：L≥1,023,453,813接受；U<1,023,453,813拒绝；其余明确未决。排名沿用 `rank_candidates` 的区间支配及可证明同分规则，排名或阈值未决时不能输出猜测的接受号码。此前合成 ROI7／283 的排名未决仍保留；本次没有改用Q31。

两个512×20 RAM bank组合成有效512×32共享端口：LUT占word `[0,71)`，当前列概率 `[71,207)`，双行DP `[207,267)`。读写需串行协调，不能按“总容量放得下”假设有独立并发端口。详见清单引用的冻结 `finite-interface.json`。

## 供资源窗口使用的精确次数

下表为逐层输出重定标次数；shift的逐通道顺序直接读取原NPZ键 `<层名>.shift`，清单另给出每个shift的通道数和输出数。上下文使用本ROI全宽gain，固定右移30。

| 输出 | 次数 |
|---|---:|
| backbone.0 | 129,536 |
| backbone.4.block.0 | 57,600 |
| backbone.4.block.2 | 57,600 |
| backbone.4.block.4 | 57,600 |
| backbone.4.block.6 | 230,400 |
| backbone.8.block.0 | 50,688 |
| backbone.8.block.2 | 50,688 |
| backbone.8.block.4 | 50,688 |
| backbone.8.block.6 | 202,752 |
| backbone.11.block.0 | 50,688 |
| backbone.11.block.2 | 50,688 |
| backbone.11.block.4 | 50,688 |
| backbone.11.block.6 | 202,752 |
| tap2.trunk | 50,688 |
| backbone.16 | 73,728 |
| backbone.20 | 4,896 |
| container.0 | 4,896 |
| 卷积及细分叉合计 | **1,376,576** |
| context.0.normalized | 4,608 |
| context.1.normalized | 9,216 |
| context.2.normalized | 18,432 |
| context.3.normalized | 4,896 |
| 上下文合计 | **37,152** |
| 全部重定标 | **1,413,728** |

这些是输出算术次数，不等于DSP拍数或端到端延迟。本次不重新计算资源窗口正在处理的约899ms重定标预算。

## 依据与验证范围

本轮读取已有冻结实现 `integer_lprnet.py`、`integer_lprnet_fork.py`、`ctc_interval.py` 及真实配置/数组，复用已审计的整数核。部署及宽算术依据为既有 `integer-deployment-addendum.md` 和 `integer-deployment-audit/report.json`；其中保留此前实际读取的 LiteRT softmax、PyTorch CTC 和本工程 MAC/部分和 RTL 的研究记录与源码哈希。本次没有声称新增外部源码研究或实现新算法。

验证覆盖：清单依赖及全部形状、54个数组哈希、原参数数组哈希与shift统计、4个上下文DDR分区往返、完整冻结logits、5组冻结分叉向量、Q30全部状态及最终号码/决定。网络只执行一次；后续补充清单和 `verify` 均不再执行网络。既有四份交付清单共111个文件项的哈希保持不变。

本次新增本说明，未修改已冻结的 README 或旧结果文档。
