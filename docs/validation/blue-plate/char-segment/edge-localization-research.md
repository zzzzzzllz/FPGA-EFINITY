# 无颜色门的边缘定位：源码结论与受控候选

2026-10-19。建议先验证一条**共享现有 Sobel 的竖向边缘、横向闭运算、有界连通域、七区文字结构、原彩色 OCR**路线。首个候选限定单张近水平车牌，固定参数，不训练、不使用颜色筛选。当前是源码研究与离线验证计划，尚未证明定位效果，没有修改产品。

去除 CNN 和 HS 门的冻结回放已完成，304 帧为 **251 正确／1 错／52 拒绝**，见 [no-color-gates.md](no-color-gates.md)。这只是后续新定位的同身份参考线，不能把它当成边缘定位成绩。

## 1. EasyPR 实际调用链：Sobel 名称不保证无颜色

已逐段阅读本地 `tmp/plate-research-20261018/easypr-plate-locate.cpp`、`easypr-core-func.cpp`、`easypr-chars-segment.cpp`、Apache-2.0 许可证与 Issues 缓存。补充下载固定提交 `a0a9f3c3f612e7c8d9046bd9c5770249cfb86850` 的 [plate_locate.h](https://github.com/liuruoze/EasyPR/blob/a0a9f3c3f612e7c8d9046bd9c5770249cfb86850/include/easypr/core/plate_locate.h) 和 [plate_detect.cpp](https://github.com/liuruoze/EasyPR/blob/a0a9f3c3f612e7c8d9046bd9c5770249cfb86850/src/core/plate_detect.cpp)，位于 `tmp/blue-plate-char-segment/edge-localization-research/`。原本地 cpp 按内容 SHA 冻结，既有获取记录有 master URL；未将未核验的文件版本冒充固定提交。

| 路径／函数 | 实际实现 | 对当前任务的意义 |
|---|---|---|
| `plateDetect`，新下载 cpp 18–65 行 | type=0 同时启用 Sobel、COLOR、CMSER；最后调用 `PlateJudge::plateJudgeUsingNMS` | 默认入口不是纯 Sobel；只改检测 flag 仍会进入 SVM 判牌 |
| `plateLocate`，locate.cpp 970–1000 行 | 两个重载均直接调用颜色、Sobel、MSER | 不能把这个方便入口包装成无颜色定位 |
| `sobelOper`，308–344 行 | Gaussian→gray→3×3 Gx→绝对值并饱和至8位→Otsu→矩形闭运算 | 可借鉴“竖向笔画成组”的机制；不需要颜色掩膜 |
| `sobelFrtSearch`，159–200 行 | 外轮廓→minAreaRect→verifySizes→安全包围框 | 第一阶段几何筛选；并不要求七字完整 |
| `sobelSecSearch`，268–305 行 | 候选内重新执行3×3 blur、10×3 close，再找轮廓和旋转矩形 | 是第二次局部图像处理，不是免费精修 |
| `sobelSecSearchPart`，203–265 行 | 6×2 close，清铆钉、找左右界，在中间行连线，再取轮廓 | 有人工连线修补，不能把连上的块视为七个真实字符 |
| `plateSobelLocate`，865–966 行 | 对窄块扩展左右及上下，跑上述两种二次搜索；最后再次全图 Sobel 并 deskew | 包含多轮扫描；不是单遍流式现成硬件方案 |
| `deskew`，420–513 行 | minAreaRect 角度，旋转、三行左缘估计 shear，默认 deleteNotArea，最终136×36 | 可参考几何思想，不能直接把136×36图替代原224×64彩色 OCR 入口 |

隐藏颜色依赖有两条，均已核到源码：

1. `plate_locate.h` 的 deskew 默认 `useDeteleArea=true, color=UNKNOWN`。`plateSobelLocate` 调用时不传这两个参数，因此 `deleteNotArea`（347–418行）会调用 `getPlateType`，按 BLUE/YELLOW 决定 Otsu 极性和中区取样。`UNKNOWN` 是触发颜色判断，不是关闭颜色。纯边缘参考必须显式关闭此项，并用亮／暗两种灰度极性作结构诊断，不能硬编码 BLUE 或 YELLOW。
2. `plate_judge.cpp` 默认 `useLBP=false`，取 `getHistomPlusColoFeatures`；`feature.cpp` 94–99行拼接二值投影与180-bin HSV hue 直方图，再送预训练 SVM。即使不调用显式颜色定位，默认判牌仍使用颜色特征。当前候选不调用该判牌器、不改训练集重训 SVM。

纯 Sobel 的离线参考边界应是：显式调用 `sobelFrtSearch`／`sobelSecSearch` 的灰度路径，deskew 关闭 deleteNotArea，跳过 PlateJudge，保留完整原图坐标。候选过滤由下述可审计的几何和实际七区前景完成。

## 2. 可复用机制、已知缺陷与不照搬的部分

- 默认 header 的 blur=5、close=17×3、area=272…6528；lifemode 才扩到 54400。默认 aspect=3.75、error=.9，计算出的 rmin/rmax 为 .375/7.125，而 r 已归一化到≥1，下限几乎不起筛选作用。它不是专为720p当前拍摄尺度校准的参数，不能原样当作产品规格。
- `sobelOper` 用 `CV_RGB2GRAY`，`sobelOperT` 用 `CV_BGR2GRAY`，同一类内存在通道解释不一致。新候选直接用已验证的 FPGA luma `(77R+150G+29B+128)>>8`，不继承这种差异。
- `rotation` 用 `Mat::create` 建1.5倍画布，只写入源图矩形，外围没有显式初始化，再做 cubic warp。这是静态发现的未初始化边缘风险，未在本轮运行证明其影响。当前候选不复制此分配方式。
- `isdeflection` 仅取高度1/4、1/2、3/4三行最左非零点估计 shear；边框、铆钉或局部缺笔都能改变这些点。首候选不依此自动扭曲原彩色 ROI；明显倾斜先记录失败。
- `deleteNotArea` 最终 `Rect(posLeft,top,w-posLeft,bottom-top)` 没用 `posRight` 作为右裁界。已有本项目实验证明强裁剪和补边会显著改变阈值分组和首末字符，不再照搬。
- `verifyCharSizes` 把 `countNonZero/bboxArea` 存为 int，并仅判断 `<=1`，对正常二值图不能提供有效填充率约束。`GetChineseRect` 从第二字符位置反推汉字框，不能证明左侧真实存在完整汉字。当前候选要求首区真实前景；不补出推测字符。
- 已读 Issues #334（VS2022/OpenCV3 批量运行断言）、#332（模型加载接口不匹配）以及 #329（无汉字前缀牌适配问题）。这些是报告者的具体兼容／适配问题，不是本项目定位精度测试；不把仓库宣传准确率当作当前数据证据。源码和许可证 hash 记录在本次来源清单。

EasyPR 源码许可证为 Apache-2.0；若未来适配代码，应保留相应版权和许可证。本轮不运行它的训练、ANN/SVM 或下载测试图片。

## 3. 对照来源：OpenALPR 的边界精修不等于全帧检测

复用主控已下载的 `tmp/blue-plate-review/edge-reuse-research/openalpr/`。本窗口也阅读了 `detectorcpu.cpp`、`detectorfactory.cpp`、`detectormorph.cpp`、`characteranalysis.cpp` 的尺寸筛选、`linefinder.cpp` 的字符行组织、`edgefinder.cpp` 的回原图扩区以及 `platecorners.cpp` 的候选边界评分。源码获取记录在主控 `acquisition*.json`；API超时，raw master 文件按 SHA 冻结，不能声称 commit-pinned。本窗口早期独立下载的重复核心文件保留为研究记录，收到协调后不再继续重复下载。

实际对照如下：

| 组件 | 机制 | 与候选的关系 |
|---|---|---|
| 默认 CPU detector | equalizeHist + 已训练 LBP cascade / detectMultiScale | 不满足无模型全帧边缘定位，不能冠以纯边缘检测 |
| 可选 `DetectorMorph` | 5×5 blur、30×4灰度开运算顶帽、Otsu、5×5菱形开、13×4闭、轮廓；每ROI多阈值正反极性找blob | 真正的传统替代路径，但不是默认 CPU 路径；比当前共享Sobel增加灰度形态学通路，不作为首候选 |
| `DetectorMorph` blob检查 | 7个阈值×正反极性累计有效blob，允许4…50；字符尺寸5…20宽、15…40高，候选宽70…300 | 同一个字可被多阈值重复计数，不能拿累计数证明七个独立字符；固定像素域也需适配 |
| CharacterAnalysis / LineFinder | 已有 crop 内多阈值、字符盒尺寸及孔洞过滤、对齐成行 | 支持“几何与实测字符结构”作为候选证据；没有独立解决全帧入口 |
| EdgeFinder / PlateCorners | 根据文字行高度回原图扩区；图像边线与物理长宽假设评分；可回退理想边界 | 可参考保留原图上下文，不能把先验补出来的边界当作完整可见证据 |

原始实现入口为 [DetectorMorph](https://github.com/openalpr/openalpr/blob/master/src/openalpr/detection/detectormorph.cpp)、[CharacterAnalysis](https://github.com/openalpr/openalpr/blob/master/src/openalpr/textdetection/characteranalysis.cpp) 和 [EdgeFinder](https://github.com/openalpr/openalpr/blob/master/src/openalpr/edges/edgefinder.cpp)。OpenALPR 为 AGPL-3.0。本候选只借鉴公开算法机制，不引入其代码或依赖；如以后决定复制其实现，应先处理该许可证与产品分发方式的关系。

## 4. 原传统定位失败证据：先纠正“纯边缘”口径

实际读取 `tools/blue_plate/baseline.py` 268–358行：`quad-sobel` 先取 HSV 蓝色轮廓，再追加 Sobel 轮廓；**所有轮廓都要求 blue coverage≥.25**，排名还乘 coverage。`quad-binary`／`binary-dual` 的“binary”指后续字符结构，并不代表去掉了颜色定位。`mser_locator.py` 的 local/MSER 种子也要求蓝色邻域比例，并调用既有字符分类器。它们均不能直接改名字作为当前方案。

只摘取旧 summary 的 development 部分，没有重跑或读84/112图像：

| 旧实验 | 开发帧 | 正确／错／拒 | 有用证据 |
|---|---:|---|---|
| quad-sobel-standard | 131 | 63 / 2 / 66 | IoU≥.5为110；无候选20、切分失败21、分类拒绝25；这是颜色+Sobel，不是纯边缘 |
| border-sobel-standard | 131 | 63 / 3 / 65 | IoU≥.5仍110；只改字符边框处理并未解决定位 |
| easypr-refined-standard | 131 | 49 / 1 / 81 | 强裁剪造成明显正确损失 |
| easypr-pad-standard | 131 | 34 / 0 / 97 | 黑色补边改变二值化，不能靠“补边”宣称恢复文字 |
| easypr-replicate-standard | 131 | 66 / 2 / 63 | 复制边缘缓解实现问题，但仍有错，未建立完整解决方案 |

304帧冻结 `geometry-diagnosis/report.json` 的170个失败／错误归因为：无候选52、字符裁掉24、斜切18、区域过大7、切分规则24、字符打分45。这是明确阈值下的诊断分类，不等于逐图人工可读性标注。至少说明定位缺失、裁剪和识别错误是不同问题；删除颜色条件有望解除一类漏检，却不能自动恢复裁掉的字。

已有 `structure-development.md` 还给出直接反例：全局七区结构在304个原正图中通过278、在304个中间遮挡图中通过0；EasyPR行跳变统计分别通过291、256。七区结构也误拒完整图，并能被七根竖条通过。因此本方案把结构作为有界候选证据，保留七字 OCR 与置信度；不宣称“七个区域=七个完整字符”。这些旧结构结果属于当时的浮点识别与旧组合门，不混入本次251/1/52整数成绩。

## 5. 适合共享720p流水线的最小候选 E0

目标域预先限定为：同一1280×720帧内一个主要单行七字号码区域，近水平，无需强透视／shear矫正。全部304帧仍要报告，不在看结果后剔除失败图。

### 共享入口与不可改变的内容

现有 `rgb_to_gray.v` 输出双像素每拍 luma；`sobel_pair.v` 已有 signed11位 gx0/gx1、gy0/gy1。`out_gradient` 仅导出方向和 `|gx|+|gy|`，不能无损还原 `|gx|`。因此首候选是在**已有 Sobel 内部增加两个比较结果旁路** `abs(gx)>56`，与 frame_id、epoch、valid 同步，不新实例化一套 Sobel。禁止直接把当前显示的二值边缘或 Canny 清理图当成彩色 OCR 输入。

边缘展示和识别在同一固件保留。识别作为现有帧作业的串行消费者：同一共享 luma／滤波／Sobel 数据通路，识别作业冻结“median bypass、3×3 Gaussian、固定阈值56”；显示仍使用原按键配置。Gaussian 的当前 recognition box-mode 控制必须由主控在作业描述中分清，不能让原形状识别的均值滤波标志意外覆盖本候选。阈值56来自当前工程既有默认值，是首轮固定假设，不是搜索后的最优值。

这是对 EasyPR Otsu 的流式适配，避免首轮增加全帧梯度存储及帧末阈值回读。低对比漏检必须单独量出；离线保留一个固定 Otsu 参考用于判断差距，不自动扫阈值。原边界像素强制非边缘，复制行列的时序沿用已验证 Sobel 行尾／帧尾 flush。

### 固定几何与结构规则

1. `abs(Gx)>56` 后执行17×3二值闭运算。按可分离横／纵方向实现，两个像素每拍；边界补0。只需四条1bit行历史，共640B逻辑数据；RAM个数还取决于端口和打包，不能按字节直接宣称综合结果。
2. 流式8连通 RLE 合并区域，行内最多128段、最多256个活动等价标签、最多32个满足几何的候选；容量溢出显式丢弃本帧，不静默截取前K。区域统计 bbox、面积和一阶／二阶矩，不存全部轮廓像素。不把 OpenCV 动态 findContours 当成硬件已实现。
3. 几何域固定为宽80…640、高20…160、宽高比2.3…6，均在720p坐标中；这些是本轮受控工作域，不冒称上游原参数。按旧Sobel笔画外扩原则，候选四周扩大至宽1.08倍、高1.4倍，超出原边界即拒绝，不用复制边缘伪造文字。
4. 将每个候选的**原彩色像素**按既有 Q32/Q5 路径临时采样至224×64，仅从其灰度建立全局 Otsu 正、反两极性；这是笔画极性，不是蓝／绿／黄分类。两个极性都独立观察，不按颜色选一支。复用既有七区结构参数：六个谷值窗口中心34/70/101/132/163/194、半径9、谷投影≤8；每区真实前景高≥23、宽≤36，不机械均切或从第二字补首字。按现有 rim 保护处理末位窄字；先记录清边前触边情况，再清理，不能把被清掉的笔画当成不存在。
5. 七区 bbox 中心拟合一条文字行，只用于**拒绝明显倾斜**：绝对斜率≤0.0875（约5°），高度最小／最大≥0.65，中心对拟合线的最大残差≤0.3倍最大高度；全部是固定整数比较可表达的条件。首候选不进行额外旋转／shear，也不裁到字面再拉满64行。EasyPR与OpenALPR的 deskew 保留为后续有实证需要时的方向。
6. 任一极性通过仅表示该 bbox 是一个结构候选；同一 bbox 两极性都通过只记一次。遍历全部≤32个候选后，恰好一个通过才给 OCR；0个拒绝，多个记 ambiguity 并拒绝，不用颜色或 OCR 偷偷重排挑牌。该约束明确属于受控单牌方案，不能据此宣称一般多牌能力。
7. 最终输出的是原帧四角和 bbox，再从同一帧原RGB取得224×64彩色 ROI，调用原 Q8 BGR resize 至24×94及冻结整数 OCR。原七字语法、Q30阈值／排名和 frame margin 检查不变；没有颜色 CNN、HS门或颜色类别。

这里选择固定阈值、轴对齐包围框和唯一结构候选，是为先验证最小共享路径。若低对比或小倾斜仍大量丢失，下一步必须依据分阶段结果选择 Otsu 或几何精修；不继续围绕一个已证实无效阈值微调。

### 存储和实时接口约束

RLE 上述容量需要双行run表、标签／统计表和候选表；最多256标签不等于256个总历史区域，行终结后必须释放且检查等价类回收。粗略逻辑字节下界不能替代RAM端口调度及最坏merge次数。7区分析逐候选复用已有ROI scratch；32候选×2极性×224×64最多917,504个结构像素检查，候选量必须计入延迟。

识别可以跳过新帧，但不能反压相机或让边缘展示停止；共用作业调度保留源帧副本直到最终彩色 ROI 读完，frame_id/epoch 不匹配就丢弃结果。对接主控现有帧槽／租约，不能另造物理 DDR 地址。本轮不宣布删除CNN后已自动释放哪些综合网表资源，也不把恢复边缘展示的成本漏计。51 RAM／8 DSP仅保留为原引擎目标，实际整合是否满足由后续map、DDR服务和720p显示回归决定。

## 6. 一次有界离线验证计划

精确身份沿用本次307 ROI manifest去重后的304个 development sample；计划文件保存每个身份路径／SHA，不按颜色抽样、不读84/112。一次冻结 E0 参数后再观察结果，保持所有失败在分母中。

**A：定位和结构，零模型前向。** 每个身份只读取源图一次、生成一次与冻结数据相同的canvas720；各运行一次 E0 和一次纯灰度成熟参考：3×3 Gaussian、`abs(Gx)`饱和8位、固定32-bin Otsu、17×3 close、同一后续几何／结构。参考仅诊断全帧自适应阈值是否必要，不自动代替E0。最多608次传统定位调用，0次CNN/OCR。输出每阶段候选、overflow/ambiguity、七区证据、所选四角、border状态和整数采样 SHA。GT角点／号码只在候选生成结束后计算指标，不进入定位。

记录所有候选及唯一选中候选的 IoU≥.5/.7、完整 GT 四角包含率、角点误差、原正确251帧的定位丢失、字符结构拒绝、两极性分布与耗时；未被人工确认的“完整可见”保留未知，不能拿 bbox包含率替代。按预先的尺寸／倾斜工作域分层，同时保留全304总数。RLE只要溢出就报告容量瓶颈，不提高上限后重新计同一次实验。

**B：冻结彩色 OCR，需主控按A结果决定是否执行。** 只对 E0 恰好一个结构候选的帧各跑一次原整数 OCR，上限304次；没有检测CNN、颜色CNN、训练或阈值搜索。缓存224×64和24×94彩色输入及其SHA；总计最多304次模型前向。与本次无颜色门的251/1/52逐帧比较，完整列新增正确、丢失正确、新增错误、拒绝及边界变化。若新定位引入更多错误接收，不能靠改置信阈值掩盖。

晋级条件：A没有未经处理的容量／时序／帧身份错误；对旧251个正确帧不能无解释地丢失；B全304正确数至少251、错误数不超过1，并逐例审查新增错误身份（不能用别处纠错抵消新错）。若只在受控域达标，必须将结果明确交给主控决定受控演示范围，不能称为一般定位替代。显示侧还需在同一固件验证原边缘菜单／按键／720p输出持续正常，随后才谈整合完成。

本轮只交付研究、去门回放和上述计划。A、B均未执行；产品、边缘展示功能、原OCR输入和参数均未改。失败证据已说明为什么不能直接复活旧传统定位器，也没有据此断言无颜色边缘定位不可行。
