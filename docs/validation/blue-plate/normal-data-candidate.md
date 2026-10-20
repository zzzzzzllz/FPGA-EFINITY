# 普通蓝牌：冻结的二值跳变定位候选

2026-10-18。当前离线候选为 `quad-binary + projection-char + linear`，右边框删除增加字符布局证据保护。G1 未通过；继续自动 ROI 精修与失败归因。

500 张预选图片已全部下载、通过固定 Git blob 和尺寸核验，没有替换预选对象。身份划分为开发 304、校准 84、留出 112；下列结果只运行前两组。数据选择依据几何而非识别结果，采集场次未知；字符高度/清晰度仍需另行核对。没有留出推理或预览。

## 固定同批比较

数字为正确接受 / 错误接受 / 拒绝；单图接受尚未经过三帧确认。

| 自动路径 | 开发304 | 校准84 |
|---|---|---|
| 原灰度梯度筛选，普通门限 | 123 / 3 / 178 | 32 / 3 / 49 |
| 二值跳变筛选，普通门限 | 134 / 4 / 166 | 35 / 3 / 46 |
| 原灰度梯度筛选，严格门限 | 61 / 0 / 243 | 17 / 0 / 67 |
| 二值跳变筛选，严格门限 | 63 / 0 / 241 | 17 / 0 / 67 |

两种定位的真值区域相同：普通门限开发225 / 7 / 72、校准56 / 4 / 24；严格门限开发146 / 0 / 158、校准42 / 0 / 42。二值筛选改善候选召回，但普通门限多一个误接受，严格门限正确接受比例仍低，不能称为可靠识别完成。

二值候选自动开发失败分布为无候选52、切分失败61、普通门限分类拒绝53；校准为8、22、16。接下来检查已有候选的几何裁剪与文字区域位置，参照 EasyPR `deleteNotArea`，不只放宽门限。

## 右边框保护与未采用方案

最初 `x>=210,w<=10` 无条件去边框确实会误删偏移后的真字符。`border-shift-diagnosis.json` 对97个真实自动可切分区域统计；末位窄字产生24个有效小范围平移案例，旧规则误删2个末位1，新字距保护保留这2个。它只证明这个具体边界，不代表全域鲁棒。

固定原196张的开发131/校准28比较：带保护的自动普通门限仍为59 / 1 / 71和12 / 0 / 16。真值区域开发由初版边框修正100 / 1 / 30变为99 / 1 / 31，校准仍19 / 1 / 8；与最初63 / 10 / 58相比仍有明确收益。少掉的正确接受是`皖AG683H`，保护没有把不可靠边缘块直接删除，该例转为拒绝，未新增误接受。保留保护与误删证据，不为追分撤掉。

同批196张上，anchor-char为开发59正确/1错、校准12/0，未提高总体收益；binary-guarded为66/2、12/0，binary-rect为53/5、10/1，均未替换当前候选。首末前景整体缩放的adaptive-char已证实回退，未采用。

## 复现与冻结

冻结目录 `tmp/blue-plate-normal-g1/candidate-20261018/` 保存 baseline、模型实现、权重和接口副本，`manifest.json` 含每份SHA、固定预选清单SHA和完整命令。后续源码继续开发不改变此目录。

```powershell
D:\Python\python.exe tmp/blue-plate-normal-g1/candidate-20261018/run_candidate.py --classifier linear --locator quad-binary --segmentation projection-char --input letterbox720 --images tmp/blue-plate-normal-g1/images --splits development validation --operating-point strict --out tmp/blue-plate-normal-g1/candidate-replay-strict
```

普通门限改为 `--operating-point standard` 并使用不同输出目录。对照定位用 `--locator quad-color`。完整结果在 `full-binary-standard/`、`full-binary-strict/`、`full-color-standard/`、`full-color-strict/`；四次运行使用同一个源SHA `3b41b625461a1a5aa164307420c2ec7e90bd6e9c58b1361560647bbc889df597` 和权重SHA `d9c78f399086b74d00417c982c37b6d5b2a1a836bfde8ad020bf9fe9d9c3da52`。冻结源码稍后增加了未选用的两个实验模式，主候选行为需由冻结复跑确认。

原196张的比较使用 `cohort196/images/` 独立文件集合，不能用下载过程中增长的目录比较前后分母。完整500张已固定。

当前仅变更离线算法和设计/验证记录，没有修改产品RTL、相机配置或冻结发布。

## 后续三模型同前处理比较

新增显式 `--model-dir`，默认仍为原candidate。缺少strict字段的新模型请求严格档会明确报错，不借用旧模型门限。源SHA `97f1d21310e6087ac4565f0357e915f5f039535a7617abd47bdf2a4fdf839671`、同一500张输入、`quad-binary / projection-char / refinement none`：

| 模型，使用自身普通门限 | 自动开发304 | 自动校准84 | 真值开发304 | 真值校准84 |
|---|---|---|---|---|
| original | 134 / 4 / 166 | 35 / 3 / 46 | 225 / 7 / 72 | 56 / 4 / 24 |
| geometry（11位权重） | 143 / 1 / 160 | 37 / 2 / 45 | 228 / 6 / 70 | 56 / 3 / 25 |
| geometry-regularized（10位权重） | 144 / 4 / 156 | 39 / 3 / 42 | 224 / 5 / 75 | 56 / 2 / 26 |

结果位于 `models-original/`、`models-geometry/`、`models-geometry-regularized/`。geometry降低错误接受、同时增加正确接受，但仍未达到整牌目标；本窗口没有覆盖candidate或RTL权重。

## 完整开发失败几何归因

`tools/blue_plate/diagnose_geometry.py` 从冻结源码复现全部开发结果，用真值四角/字符前景仅做诊断映射，绝不进入检测输入。170个非正确接受案例暂分：无候选52、字符裁掉24、区域过大7、斜切18、切分规则24、字符打分45。判据和逐例值在 `geometry-diagnosis/report.json`，每类前5张自动/真值对照图已人工查看。它是带明确阈值的诊断分类，不等于逐张人工可读性标注。

裁掉字符类可见首末笔画或上下笔画越界；区域过大类有车身背景占据大部分区域；斜切类出现共同笔画倾斜；切分规则类也包含阈值导致的笔画粘连，不能都归因于分类器。

## 二次区域修正的实测限制

同一固定196张、原模型普通门限，下表自动结果仍为正确/错/拒：

| 修正方式 | 开发131 | 校准28 |
|---|---|---|
| 冻结quad-binary，无修正 | 64 / 1 / 66 | 12 / 0 / 16 |
| EasyPR中区阈值、边框/左界裁剪 | 49 / 1 / 81 | 9 / 1 / 18 |
| 上述裁剪加复制边缘垂直留白 | 66 / 2 / 63 | 11 / 1 / 16 |
| 稳定矩形加蓝色边界共同剪切 | 54 / 5 / 72 | 11 / 1 / 16 |
| quad-binary加文字上下边界拟合 | 66 / 2 / 63 | 13 / 0 / 15 |
| 稳定矩形加文字上下边界拟合 | 47 / 5 / 79 | 11 / 0 / 17 |
| quad-binary加字符矩共同剪切 | 64 / 2 / 65 | 12 / 0 / 16 |
| 稳定矩形加字符矩共同剪切 | 62 / 6 / 63 | 11 / 1 / 16 |

裁剪到字面后直接拉满64行，与现有清除外围5行冲突；黑色补边又会改变Otsu分组，导致大量空白掩膜。复制真实边缘后消除了该实现问题，但总错误接受仍未改善，未采纳。几何步骤不会恢复原候选已经裁掉的像素。

新读取的成熟实现：HyperLPR_python固定revision `0b17acd2165aa6815c78525dbcdba2d7de80a3eb` 的 `hyperlpr/finemapping.py`，使用多局部阈值收集字符上下界、Huber直线拟合和透视映射。实际源码及Git blob/SHA在 `geometry-research/finemapping.py`、`finemapping-source.json`；只读参考，未执行第三方脚本。字符矩方法参考 [OpenCV OCR deskew源码](https://docs.opencv.org/4.11.0/dd/d3b/tutorial_py_svm_opencv.html) 的二阶矩机制，本项目对多个字符取中位数并检查一致性。

当前继续检查候选几何选择与切分，以上实验没有替换冻结候选。冻结候选复跑776个开发/校准结果记录与原full-binary-strict逐字段完全相同。

## 两种几何候选的完整对照

`binary-dual` 对同一个轮廓产生四角和旋转矩形候选，去掉几何重复后仍最多保留两个；候选排序继续只用字符完整性、接受位数与最小类别分差。没有使用标签、没有增加第三种分类模型。源SHA `648d0875dc7568eefde852c87d6a66ee13fd2ed4fce75bdc868647305ad81543`。

| 普通门限 | 自动开发304 | 自动校准84 |
|---|---|---|
| quad-binary + 原模型 | 134 / 4 / 166 | 35 / 3 / 46 |
| binary-dual + 原模型 | 174 / 9 / 121 | 43 / 5 / 36 |
| quad-binary + geometry | 143 / 1 / 160 | 37 / 2 / 45 |
| binary-dual + geometry | 181 / 3 / 120 | 47 / 3 / 34 |

输出为 `full-dual-original/` 和 `full-dual-geometry/`。geometry下新增48个正确接受，但错误接受从3增至6；切分失败从开发61/校准22降到41/16，无候选仍52/8。此结果支持继续改进候选几何选择，尚不支持可靠输出完成。

新增误接受需逐例分析，不靠提高门限掩盖剩余漏检。当前继续核对EasyPR `mserCharMatch` 的字符区域检测、字符评分/NMS、相邻种子分组和字符行拟合路径；相关核心实现已在 `tmp/plate-research-20261018/easypr-core-func.cpp` 实际读取。字符优先定位用于评估偏青蓝牌与同色车身粘连问题；OpenCV MSER仅为离线研究，不是已证明能满足FPGA资源/吞吐的实现。

## 无候选时的局部阈值定位

`dual-local`先执行binary-dual，仅在其返回零候选时使用local-text；非空候选即使切分/分类失败也不切换。local-text以41×41局部均值和四个偏移产生区域，再按蓝色邻域、字符评分、NMS、相邻种子分组与直线布局生成最多两个候选。检测输入不使用真值。

完整304开发/84校准结果为198/3/103、50/3/31，共248正确、6错误、134拒识。328张原本有候选的图片逐记录结果和IoU完全不变；60张原无候选图片新增20正确、0错误、40拒识。证据 `full-dual-local-geometry/`、`dual-local-transitions.json`。全局替换为MSER或local-text、改用清理后的全局二值字符，均未改善错误接受，未采纳。

60张实际fallback图片的4个局部阈值共221184000像素比较，浮点均值与整数式 `1681*gray > window_sum +1681*offset` 完全一致，见 `local-integer-threshold-check.json`。当前Python仍使用原局部均值实现。41行完整灰度缓存需要52480字节；硬件需评估held帧DDR行重读与每列纵向累加，不能据此宣称资源/带宽已经满足。

304张开发原图取车牌上方且与真值区域不重叠的背景条带，零号码输出，见 `background-probe/report.json`。这是相关背景压力测试，不是304个独立且人工核定的负场景，未计入G1负样本验收。

## 固定真实特征的模型比较

`freeze_pipeline_features.py`重放776条automatic/oracle记录，冻结4599个原始ROI只归一化一次的320维特征。文件 `frozen-pipeline-features/features.npz` SHA256 `7f085c6cdf84699b039fb3a364a2509f8ee43a0d15cfdbe8157075834075055c`；样本映射见同目录records.json，模型结果及来源哈希见comparison.json。六个误接受的原始二值字符及ROI在error-036/114/126/127/149/476目录。

| 同一已选ROI、各自普通门限 | 自动开发304 | 自动校准84 | oracle开发304 | oracle校准84 |
|---|---|---|---|---|
| geometry线性 | 198/3/103 | 50/3/31 | 228/6/70 | 56/3/25 |
| 现成MLP64 | 171/6/127 | 42/3/39 | 212/10/82 | 52/2/30 |
| 现成MLP128 | 178/4/122 | 44/5/35 | 220/6/78 | 54/2/28 |

保留geometry线性；未更改分类窗口权重、特征或RTL，未接触112张heldout推理。比较固定了候选选择，不等于重新用MLP跑定位和选框；这两份现成MLP也没有采用geometry同样的训练增强，结论不泛化为神经网络无效。主控未使用模型评分助手独立复算所有向量、类别与门限，结果一致。

geometry的11位有效权重加32位偏置共28860字节，每字20800MAC；现成MLP64/128有效10位打包加偏置分别31316/62372字节，每字24640/49280MAC。软件int16数组口径分别41860/49796/99332字节。物理RAM与时序仍须实际map/PNR，不能按字节直接换算。

硬件先落实已明确接口的必要核；[Otsu与真实RGB链验证](otsu-hardware.md)已完成独立RTL与map。整牌G1仍未通过。

## 几何整数化与字符裁剪排查

`geometry_sampler.py`重新跑完整dual-local定位，冻结656个真实候选的四角和224×64 RGB，位于 `integer-geometry/candidates.json`、`candidate-plates.npz`。参考OpenCV 4.11.0 `imgwarp.cpp` 的逆映射、5位子像素坐标与定点双线性插值；源码已下载到geometry-research，来源/hash记录在opencv-imgwarp-source.json。

| 采样形式 | 比较RGB分量 | 不同分量 | 最大绝对差 | 完整result记录变化 |
|---|---:|---:|---:|---:|
| float矩阵求解→Q24采样 | 28213248 | 188783 | 6 | 57 |
| float矩阵求解→Q32采样 | 28213248 | 871 | 4 | 1 |
| Q16四角整数求解→Q32采样 | 28213248 | 871 | 4 | 1 |

三种形式的388张号码及接受/拒识逐记录均与原候选相同，维持248正确/6错/134拒识。Q32唯一完整result差异是`皖AVV330`第五字3的score/margin变化，号码与该字accepted保持相同；不是逐像素/逐分数全等。矩阵求解参考[ZXing的squareToQuadrilateral](https://github.com/zxing/zxing/blob/master/core/src/main/java/com/google/zxing/common/PerspectiveTransform.java)同类投影公式，实际源码与来源hash也保存在geometry-research。本地整数实现把运算写成有理式、Q32最近偶数舍入，尚需RTL实现宽乘法/除法与退化几何检查；运行时不能依靠PC下发矩阵。

坐标RTL已经启动于 `tools/blue_plate/geometry/rtl/perspective_coords.v`；它接收9个signed48 Q32逆矩阵系数，输出224×64逐点的signed32 Q5源坐标。共享串行除法器用精确余数做最近偶数舍入、反压保持、取消/复位；该模块不等于完整采样器，下一步还需同帧DDR像素获取、RGB插值及板上系数求解。

另对全部656候选统一扩大字符灰度裁剪范围，测试是否因全牌阈值bbox丢失弱笔画。`diagnose_char_crop.py`固定定位和候选排序、模型与门限；结果在character-crop-study/report.json。x增加1像素后开发196/9/99、校准52/4/28；x增加2后198/3/103、49/4/31；y从2增至4后172/10/122、44/4/36。均未降低误接受，不采纳，不按六个错误号码做特例修补。
