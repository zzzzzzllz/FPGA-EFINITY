# 同帧四角采样链

已新增并验证可选RGB输出，详见[彩色接口交付](geometry-color-output.md)。默认入口仍保持原灰度行为；彩色启用后的资源及测试以该交付为准，下文保留原版几何证据。

2026-10-18。独立目录`tools/blue_plate/geometry/`已经实现“四角→整数矩阵→逐点坐标→frame_reader同帧读取→RGB双线性插值→灰度写出/Otsu阈值”。没有修改共享顶层、冻结release或加载板卡；定位器与七字切分尚未接入。

## 整数行为与来源

参考并实际下载了OpenCV 4.11.0 `modules/imgproc/src/imgwarp.cpp` 的warpPerspectiveBlockline、INTER_BITS=5、定点双线性插值和舍入实现，以及ZXing `PerspectiveTransform.java` 的squareToQuadrilateral公式。源码与Git blob/SHA记录位于`tmp/blue-plate-normal-g1/geometry-research/`。

软件原候选四角依次为TL、TR、BR、BL。`geometry_sampler.py --integer-solver`把四角量化为signed Q16，用整数有理式求逆映射矩阵，再以最近偶数舍入生成signed48 Q32系数；输出采样坐标为signed32 Q5。四个RGB邻居分别越界补0，权重总和1024，结果加512后右移10，再按77R+150G+29B右移8得到灰度。不会提前灰度化再插值。

656个真实候选、28213248个RGB分量与当前OpenCV结果比较，871个分量不同、最大差4；388张号码和接受/拒识决定全部不变，仍为248正确/6错/134拒识。一条记录第五字score/margin不同，不能宣称像素或分数全等。软件报告与生成时源码快照在`tmp/blue-plate-normal-g1/integer-geometry-solver/`；`geometry_sampler-source.py` SHA精确匹配报告中的e8068b4c…，后续顶部说明修正没有改变算法。

## 模块与契约

| 模块 | 行为 |
|---|---|
| perspective_matrix | start后接收8个signed32 Q16坐标，顺序TLx/TLy/TRx/TRy/BRx/BRy/BLx/BLy；全部9个系数算完且合法后才输出，行优先顺序，最后系数固定1.0 |
| perspective_coords | 接收9个signed48 Q32系数，以行累加/列累加生成分子与分母，共享串行除法器输出224×64坐标；精确余数最近偶数舍入 |
| perspective_fetch | 每个坐标发起最多2×2的frame_reader命令，边界裁成1×2/2×1/1×1，全越界直接补0；核对坐标、keep和末标志，收到cmd_done后插值 |
| perspective_roi | 已给系数的采样+阈值编排，输出连续地址0..14335的gray_write/gray_data供切分缓存写入，并保持最终阈值/状态直到消费 |
| perspective_quad | 完整四角入口，自动启动矩阵核与采样链；运行时不需要PC提供变换矩阵 |

frame_reader在开始采样之前必须已持有同一完成帧。该链只发cmd，不发hold、finish或release；同一来源帧的两个候选可先后运行。frame_reader身份与source_time_ms由外部单任务调度持有，灰度缓存也只能属于该任务。gray_write是无反压RAM写使能，消费者须能每拍写一个字节；实际发生在采样像素与Otsu同时接收时。

所有ready/valid采用上升沿握手，反压时数据稳定。同步rst/abort丢弃局部状态并屏蔽握手；**它们不表示DDR已排空**。外部应把frame_reader.abort_valid接到该链abort；取消后必须等reader完成自然排空或真正recover，再释放/换帧。

perspective_quad结果状态：0阈值有效，1空，2像素数越界，3单灰度档，4ROI流数量/keep/last错误，5非正投影分母，6坐标溢出，7reader像素契约错误，9四角越界，10退化几何，11矩阵系数溢出。状态7要求owner取消reader任务，等待job_done或恢复完成后才能开始新任务；消费局部错误结果不能代替取消排空。错误任务已经写出的灰度缓存内容无效。四角错误在发出任何采样命令之前返回。

## 位宽与存储

四角输入限制为±2048像素（Q16绝对值≤134217728）。差分最多2^28，三角差最多2^29，det绝对值小于2^57，投影分子因子小于2^58。系数分子的乘加及Q32左移保守小于2^119，signed128覆盖；分母同样使用128位。共享128位移位加乘法器及48位商除法器，系数舍入后检查signed48范围，越界报错。

坐标核的列/行累加使用signed64：signed48系数乘以最大224/64扫描范围、再乘32仍小于2^61。分母必须>0。除法先检查高32位，直接播种余数，计算32个商位；跳过的是已证明为0的高商位，不是近似。最终Q5坐标超出对称signed31幅值报错。

采样核只保存四个RGB邻居和少量状态，不缓存整幅RGB ROI。后续切分需要224×64灰度缓存14336字节，其RAM开销尚未计入此模块map。

## 验证

根目录命令：

```powershell
D:\Python\python.exe -X utf8 tools/blue_plate/geometry/tests/run_matrix_sim.py
D:\Python\python.exe -X utf8 tools/blue_plate/geometry/tests/run_sim.py
D:\Python\python.exe -X utf8 tools/blue_plate/geometry/tests/run_fetch_sim.py --quad
D:\Python\python.exe -X utf8 tools/blue_plate/geometry/tests/run_fetch_sim.py --border-grid
D:\Python\python.exe -X utf8 tools/blue_plate/geometry/tests/run_lifecycle_sim.py
D:\Python\python.exe -X utf8 tools/blue_plate/geometry/tests/run_lifecycle_sim.py --roi
D:\Python\python.exe -X utf8 tools/blue_plate/geometry/tests/prepare_synthesis.py
```

- 矩阵核：656真实候选，额外identity、负坐标、±2048边界、越界/退化/系数溢出，及load/计算/输出/复位恢复。独立Fraction八方程高斯消元，共666任务、5967系数一致，最大计算等待753拍；等待不含全部握手耗时。记录`tmp/blue-plate-geometry/matrix/simulation.json`。
- 坐标核：6真实矩阵、identity、正负半整数并列、非法分母/溢出；abort/load/div/output和rst后均完整重放有效矩阵。14任务、172032坐标对精确匹配Fraction参考。记录`coords/simulation.json`。
- 读取与插值：真实720p图片重建RGB24大端DDR内存；14336采样RGB逐点匹配独立四邻居计算，另40边界点；14354命令、28730突发，一次hold和release。记录`fetch/simulation.json`。另以非黑公式图覆盖四角、四边和内部点的全部1024种子像素相位，加全越界点共10248点，10240命令、14336突发通过；已纳入`--border-grid`长期回归，记录`fetch-border/simulation.json`。
- 完整四角链：输入真实候选四角，板上求矩阵、坐标、DDR读取、插值、灰度写出和Otsu；14336个灰度写入地址/数值及最终阈值完全一致。14336命令、28706突发、一次hold/release，993061拍。记录`quad/simulation.json`。
- 主控独立生命周期检查使用真实frame_reader：ROI入口19任务/19次hold/release，10次完整灰度与Otsu；四角入口16任务/16次hold/release，5次完整灰度与Otsu。覆盖退化/越界/溢出、求矩阵和坐标各阶段取消、错误keep、RRESP错误、在途总线取消及恢复。隔离ack只在总线实际排空后给出。证据分别在`tmp/blue-plate-review/roi-lifecycle/`和`quad-lifecycle/`；两份testbench已原样复制到正式tests目录，由`run_lifecycle_sim.py`重现。

旧`coords-fetch`日志的PASS总数曾误加未执行的40个边界点；该模式实际为14336，原日志保留。已修正testbench打印实际offset，完整quad新日志为14336，不能把40边界点计入quad覆盖。

## 综合与整机预算

完整perspective_quad（含矩阵、坐标、读取命令/插值、Otsu；不含frame_reader及灰度缓存）独立map通过：9495 LUT4、4730 FF、4232 ADD、2 RAM10、1 DSP48，详见`tmp/blue-plate-geometry/synthesis/out/perspective_quad.map.rpt`及source-hashes.json。矩阵求解占6027 LUT4，是本链主要逻辑开销；后续整机资源不足时优先检查可共享运算通路，而不是降低几何精度。未做PNR，100MHz仍是约束。

实测仿真993061拍约为100MHz假设下9.93ms/候选。读核全720p测试另为3872104拍，七字线性分类计算约292572拍。二候选粗加约61.5ms，还缺全帧颜色/CCL/轮廓定位、local-text后备、七字切分及真实DDR显示/采集竞争；不能据此宣称整机达到10次/秒。下一步把灰度缓存和七字切分接到已验前处理/分类，继续完成主定位与共享仲裁接入。
