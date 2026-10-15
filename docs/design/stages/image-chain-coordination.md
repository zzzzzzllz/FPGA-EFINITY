> 历史技术记录。仅说明记录时的版本；当前操作与状态以 [使用指南](../../../docs/for-reader/usage.md) 为准。文中旧路径用于溯源，不是当前运行入口。

# 图像链优化协作与验收

## 最新采用决定

本轮A/B/C/D离线交付均已验收完成。选定A的`outflow_opt`（area2/retiming2）：48543 XLR/182 RAM/128 DSP/DDR140.25 MiB，四类余量均至少20%，时序0.408/0.026ns；114组/5735424 RGB像素与冻结参考一致，含全幅两种间隙各连续3帧。最终offline_gate_passed=true、failures=[]、board_tested=false。

用户指定「先完成离线验收，暂不上板」。本轮已按此范围收尾，正式工程和板卡未改；实拍画质、运动、处理帧率/延迟及全功能板测留待后续，不将离线通过标为整链实物验收。此前无下载器的接线问题不再是本轮依赖。

后级保留Sobel L1、四方向NMS和RGB24存储；弱高斯T24/低阈值18仅作细节研究候选。用户另开聊天的`median_source_20261013`是独立中值候选，未合入本次交付，其构建中48632 XLR数字不代替本次选定版。

## 最终交付绑定

选定位流：`camera_trials/edgeaware_area/Ti60f225_sc431hai2hdmi_v7/outflow_opt/ti60f225_oob.bit`，SHA256 `7198817480d42613eb85e0f64d72b551301c889e7ea97398702054bb66f17eda`。构建XML SHA256 `61e8574dccc1feb00f13de9dd85f7cf4722ca360ec502a8fd0973fee34718558`。

最终`logs/edgeaware-area/build-inputs.json`覆盖145项（补齐debug_top.v，覆盖77个XML设计文件），SHA256 `53ac66eb7d3c326846a36c989d5b1bea76c34b679bdd368dcd4140976e8b5c88`；本值取代历史144项清单。主控重算145项输入、完整回归源文件、201项正式文件及`row-128/snapshot-hashes.json`绑定的20项归档，全部匹配。

完整回归为114组/5735424 RGB像素，其中gaps=0/1各3个2560×1440输入帧、各2764800输出RGB像素；另有112厂商模型逐拍用例、两套模型各4096拍定向测试、8组2560×8全宽逐拍对照。检查报告明确完整证据current=true、failures=[]。初版52298→当前48543，减少3755 XLR且整数输出不变。最终资源及时序、构建/仿真绑定和报告审查均通过，板上结果尚未产生。

以下保留各里程碑历史，出现的“运行中”“未通过”对应当时版本，当前状态以上方最终交付为准。

2026-10-13，主控聊天 `01a13579-cbd0-7772-bc66-8fce90965ae5`。阶段状态以绑定版本的原始证据为准。

## 目标与约束

在Ti60上保留2560×1440 RAW10完整视野、1280×720约30fps处理、当前LED及全部既有功能，让轮廓更清楚、更稳定。保留Sobel/Canny、完整八邻域连接、中值开关、全部视图、圆/矩形识别、冻结单步、32帧录放、参考对比、曝光控制。

整机上限：XLR≤48640/60800、RAM≤204/256、DSP≤128/160、DDR≤204.8/256 MiB，各项分别验收。布局时序和实际吞吐另验。真实细节目标、运动补测及30分钟整机综合验收仍暂缓；先做已有场景和离线工作，不反复要求立即摆放目标。

## 主线及分工

顺序为：同输入质量基线 → 曝光增益/残余RAW校正/重建缩小/量化 → 联合选择滤波与阈值 → 按证据决定梯度/NMS升级 → 整链资源、时序、视频、识别、吞吐、延迟和全功能验收。

| 角色和聊天 | 当前交付 | 独占写入范围 |
|---|---|---|
| A：对比顶级作品的数据处理流程，`01a13457-6efa-73f0-be1c-5e0b4094cd63` | 保持EA整数输出及吞吐的硬件复用；统一集成和板卡操作 | camera_trials/edgeaware_area、logs/edgeaware-area、tmp/ea-*、tools/edgeaware_fixed.py、tools/test-edgeaware-area.py、tools/check-edgeaware-build.py、docs/edgeaware-area-fixed.md |
| B：滤波与阈值联合优化，`01a1357b-7009-7620-a5f2-b24b500ce878` | 旧/新前端上的滤波、双阈值联合候选与连接负载 | camera_trials/quality_parallel/b_filter |
| C：梯度与NMS优化评估，`01a1357b-ef82-77e2-8ed3-4c5cee263d2a` | 固定滤波下逐项消融，B候选后少量交叉验证 | camera_trials/quality_parallel/c_gradient |
| D：公共评价与前端标定，`01a1357a-e13a-7d01-b134-a016223baa1a` | 先发布manifest/指标API/合成真值，再审查标定及量化 | camera_trials/quality_parallel/d_common |
| 主控 | 方向、接口、依赖、采用决定和验收台账 | 根README/task_plan/progress/findings和本文件，A已确认交接 |

host均为local。原协调聊天为`01a13560-3bd4-76f1-b574-198dafa97453`。各线共享输入只读，各自输出不覆盖既有运行，不修改他线文件；B/C/D不操作板卡或产品RTL。不新增聊天、子代理或自动化。只在接口可用、有效结论、阻塞、完成时汇报。

## 冻结接口 v1

D公共入口为`camera_trials/quality_parallel/d_common/common.py`，SHA256 `c40871c38b86e294055d8c449334a5ce3f40253d8b265c9fb34143e2f32ee202`；`input_manifest.json` SHA256 `1256017c0c2d3841b9c5a2a87040a1191b4069166486a556e11b75e682656fbb`。主控只读运行`common.selftest()`、加载并校验15组捕获和4个冻结参考全部通过。9组允许静止主比较（7组连续灰度、2组重复静态RAW），其余按manifest排除。B/C复制本版本至各自snapshot并记录哈希，后续D更新不改变本轮版本。

- EA参考`tools/edgeaware_fixed.py` SHA256：`719074e85fa6c9c5b901356d48564942659af17a39d916bb5bacc95530fb88b0`。`area(raw,phase)`输出半宽半高RGB10，`rgb8(raw,phase,gains)`输出RGB8。RAW10范围0..1023；phase 0/1/2/3为BGGR/GBRG/GRBG/RGGB；默认增益389/256/427，Gamma0。
- `Y=(77R+150G+29B+128)//256`。RAW使用`tools/quality_frontend.py::read_raw`读取PGM原始大端16位载荷，避免maxval1023被图像库重标度。旧前端使用同文件`frontend(raw,'cell',gains)`，EA使用冻结整数参考。量化改动属于D的独立变量。
- 旧灰度连续ROI、RAW重复静态ROI、合成数据分开。RAW两组各4张128×128，间隔约25秒，输出64×64；不能称连续闪动/运动稳定性。无RAW的灰度不能伪装成EA连续输出。
- 完整ROI上运算后，在输出坐标去掉8像素外圈计分，所有候选共用有效掩模。较大支持域由D统一修订。ROI外连接未知，局部负载不能外推成整帧耗时。
- 原版基线：中值3×3+高斯3×3、Sobel L1、现有四方向NMS、T32、低阈值1/2、完整八邻域连接。阈值严格大于；低阈值`floor(T*(ratio+1)/4)`，ratio为0/1/2；NMS为`mag>before && mag>=after`，边界沿用参考。
- 每次结果绑定输入/参考/评价代码/参数哈希、数据类别、前端、滤波、梯度幅值单位、NMS规则、阈值舍入、有效区、输出哈希、复现命令和环境。接口更新报告版本及受影响结果。

## 评价与采用门槛

1. D先发布可调用的最小接口和自检，B/C读取同一版本。合成真值独立于待测边缘算法；逐项报告低对比、细线、斜线、圆、矩形，不能只报平均分。
2. 同时评价轮廓召回/保留、定位、断线、假边、静止波动。实拍无真值时边缘密度只称背景响应；空边缘不能获稳定性满分。真实运动拖影/贴合继续待测。已用于第一轮的留出样本称回顾式复核，不称新盲测。
3. B先扫描中值开关、有限高斯尺度和高低阈值，交付少量候选；报告弱/强候选、最终边缘及连接负载代理。组件标记可作加速实现，但须与完整连接参考逐像素一致；其内部队列数不能冒充RTL队列/周期。保边滤波须另有证据才加入。
4. C固定前端/滤波做Sobel/Scharr、L1/L2、四方向/插值NMS单变量消融。Scharr先标定幅值尺度，L1/L2用共同阈值扫描、相近召回/背景响应比较，不能只复用相同数字阈值。记录插值、平手规则及定点代价；允许结论为保留现有算法。
5. 主控按逐场景质量和负载选少量B×C组合，不能把模块单独最优直接拼为最终最优。平均改善不能掩盖细线/弱轮廓损失，权衡需明确评审。
6. A固定集成版本后完成像素等价或新算法参考对照、每拍吞吐/边界/元数据回归、全功能回归、整机布局资源/时序及综合像素通路检查。全部离线门槛通过后向主控申请板卡独占窗口，核对当前状态再操作。
7. 正式位流记录实际时间、采集与完整结果计数、跳帧、各错误增量，覆盖代表性目标/背景、识别开、参考视图和帧功能。目标约30fps、正常负载零跳帧、零新增错误；报告单帧耗时及帧间隔。P95≤25ms为设计预算，HDMI60不能代替处理吞吐。
8. 验证全部视图、Sobel/Canny、中值、识别开关与圆/矩形、冻结同帧调参、单步、32帧录放、参考及曝光恢复。内部阶段延迟和光学到屏幕延迟分开。自动检查后提供两分钟人工验收，实拍细节/运动缺失时不标整链完成。

## 当前证据与决定

- 正式O1/M10位流SHA256为`078fa0cbc8461b3bfd866213a164562262ac1495976962a07047802f67b6b771`；48598 XLR/171 RAM/64 DSP/140.25 MiB，XLR距上限42。201项保护清单在`logs/edgeaware-area/production-hashes.json`。
- 初版EA：114组/5735424 RGB像素一致、52298 XLR，资源不通过；快照`logs/edgeaware-area/initial-parallel`。
- 归一化复用版：114组/5735424 RGB像素通过、51337 XLR/179 RAM/64 DSP，超上限2697；快照`logs/edgeaware-area/normalized`。主控已核对该目录完整仿真记录、构建四阶段PASS和`outflow_reuse/ti60f225_oob.place.rpt`的51337；资源不合格，不采用。201项正式文件当前重新哈希全部一致。
- A逐行复用原型`tmp/ea-row`已过112组小图，正在独立综合并加入逐拍对照；完整帧、资源、时序尚未完成。
- 现有静止场景M1/T32约30fps且零跳，M0/T24为29.741fps、跳8，未采用；证据`logs/quality-baseline/summary.json`。全场景性能、O1/M10人工、真实细节与运动仍待验。

当前接口协调已完成：B/C收到D冻结版本；C收到B的`filters.py::smooth`接口。B弱3×3核实际为`[1,6,1]`外积，`(sum+32)>>6`；尚未选择最终参数。C的run-01自检记录42组原版像素等价、30组随机八邻域和200像素长弱链通过，候选质量结论尚未出炉。

下一依赖：B/C候选与小范围交叉验证，D完成标定/量化研究；A独立推进硬件复用。后级使用冻结整数参考，无需等前端上板。

## 首轮候选交叉验证交接

B的`dev_v2/baseline_reproduction.json`共29组历史结果，主控读取核对最大指标差值为0，文件SHA256为`0aa0e896ee5d4b5e350d068b587b619d5ba30e1b309889e3b83ed83d3de97131`。开发后、验证前冻结的`candidates_v1.json` SHA256为`35d57391d399fe1ae0430ce4203527bb286526dcd9d53ee02cdc1d41aa8aefd1`，滤波接口SHA256为`27bb4c5222005899c6e086338192a1ce3ef345a8e5d395decdde7142b59ecc4c`。

已转C的候选为gauss3/T16/低阈值3/4、gauss3_weak/T32/1/2、gauss3_weak/T24/3/4，保留原版和gauss3/T24/1/2参照。T值是Sobel L1单位，梯度变化须按约定比较。复制B接口时须保留其snapshot/tools依赖。

B独立验证`validation_v1/results.json` SHA256为`e204f1e82851844223c436646e6b8b78d072e73864277a3a7476c71151918b2d`。弱核T32在Y8低对比双细线上召回98.94%、最大真值覆盖连通占比94.37%，但raw-dark EA重复静态不匹配8.53%。主控已核对这两条原始记录：细节收益伴随该场景稳定性代价，暂不批准替换默认。C重点验证两个弱核是否获得进一步改善；G3/T16保留作质量/假边权衡参照。B汇报G5低对比细线损失，暂不进入C主候选。

D新增`run_v2/synthetic/manifest.json` SHA256为`0c6fa2c3289a2e8d4c1b61fe8d35164278cc9ae7bfcc25d9ad5f35dcc703bde0`；56个NPZ（开发28、留出28）文件哈希经主控逐一校验通过，已分发B/C用于冻结候选验证，留出不回调参数。每例8帧RAW10，几何真值独立于Canny；不作为传感器实测。D run_v1聚合报错未完成，不采用。

C后续将交叉范围收敛为现有/插值两种NMS与上述五组滤波参数，旧/EA前端分别评价；先补负45°平台平手规则。初扫Scharr/L2定位收益小，尚非正式消融结论。

A新增里程碑：普通逐行逻辑版112组逐拍对照通过，证据`logs/edgeaware-area/row-prototype/row-logic-cycles.json`；当前集成候选已切到逐行DSP版，完整构建`outflow_rowreuse`及厂商/轻量模型两套仿真在跑，整机资源、时序和全幅正确性均待验。普通逻辑版、初版EA的通过数据不迁移到DSP版。临时厂商模型的Icarus组合求值兼容修改须附diff、原件及模型哈希；厂商安装未改，轻量模型不参与综合。仍为50MHz、原输出周期，无新增CDC，未安排上板。

## B/C/D首轮审查结果

主控复核B报告SHA256 `e5f4f0c0799232999a4d3a1e8401441a11b26cbf70c4102cc46bc3bdeb9a8654`、D报告 `5c2a233887b4ab31495f9f85eeda53a5818f0196048c9f10d1fba9f8309aae27`及D的delivery索引 `4f571f1ecc42c4313409b0df474ae7a5008c2c6a698b0292f155942b67a6e3c6`，索引绑定11项文件哈希全部一致。报告分别位于`b_filter/report_v2/REPORT.md`和`d_common/REPORT.md`。

C `cross-01/results.json`共1230行，SHA256 `9098e3c7b8d327030086c97a6bd5ca7ed33e3aa28fc72fcd5f08a58880703146`；参数hash `50e3a6c5fd0050ed29ff23d909acd4f687d5c85ee3fa84cecbdc1a6b6b732829`，evaluate.py hash `d5b7c1ec55e34a76168202b2ba66510517c6e98fb1bc12d9dffa04083cb71416`均匹配。主控将C baseline与B公共结果联结560组，召回、假边密度、边缘量、静态不匹配及最大覆盖块的差值全部为0，null语义一致。

| 比较 | 有效结果 | 主控决定 |
|---|---|---|
| 弱核T24、低阈值18 | D公共EA低对比细线均值召回99.85%、最差99.51%；raw-dark EA静态重复差异3.69%，原版0.62% | 保留细节研究候选，不直接替换默认 |
| 弱核T32 | EA留出45°/c8/s1召回74.42%，与开发平均掩盖的局部损失一致 | 降为机制对照，G5退出主候选 |
| 插值NMS | EA弱T32留出召回98.5365%→98.7421%，匹配定位0.5844→0.5718px；raw-dark原版不匹配0.6197%→2.3048%，G3/T24为0.7611%→5.9067% | 小定位收益不足以补偿场景稳定性代价，保留原NMS及Sobel L1 |
| 高精度到Y8 | Q4量化RMSE约0.545～0.549→0.288 DN，但EA Q10 raw-dark静态差异1.743%→0.149%、raw-paper 3.825%→5.100%；固定G3/T32留出召回未统一改善 | 不扩大位宽/存储链；该T32基线与B中值基线不同，数字不混用 |
| 残余RAW标定 | 两小ROI没有RAW/WB饱和，缺合格暗场/平场 | 不新增黑电平扣除或坏点替换；保留最小补采清单 |

D核对RGB_ONLY/compact_capture只存RGB24、读回重算Y，高精度Y不能靠只改前端保留。RGB24+Y8的41槽估算使DDR140.25→181.25 MiB，每次720p30读/写各增加27.648MB/s；这是未综合的成本核算，本轮不实施。B/D结束当前离线工作，不继续扩搜。下一步等待A当前DSP版完整门槛，C最终报告归档；真实细节/运动/吞吐/全功能仍待验。

最终归档更新：C报告`c_gradient/README.md` SHA256为`3f3ee84ada0c6b9c4e90f16e3477d713af9895047ec22b07cbc908fb4f7b7dc1`；正式消融`run-04/results.json`共9968条，hash `00097b92ad729266fd1f0bb37a0e4849494f6233234f7d280185545390f4c947`。交叉脚本新增独立输出目录参数后，正式证据改为`cross-02/results.json`（1230条，hash `b22284f0f94ffa3e5cc9e9a33ef92bdad681465e893c6a9ddebc07bc5bbd1f25`）。主控逐条比较与cross-01除parameter_sha256外完全一致，包括输出像素hash；此前审查结论保持。`artifact-hashes.json` hash为`1636cf027bc6bd5f0d63d592a41acca6623961b9075574559e4977c150ce1d7c`，42项实际文件哈希均匹配，C本轮验收完成。

A最新汇报：DSP行复用版整机VDB报部分未使用DSP输入及组合DSP CE连接无效，本次综合未通过，无可用位流。A依据本机Ti60原语手册修正，失败版本和在跑回归分别绑定版本；独立前端综合或旧版像素通过不能抵消整机失败。保持不上板，等待修正版完整门槛。

后续修正：A改用乘一加C、合法ABC专用级联并从O输出，独立前端map/VDB通过（69 DSP）。整机预计127 DSP，尚非最终布局资源；构建目录`outflow_rowlegal`。主控读取`logs/edgeaware-area/dsp-unit.json`确认厂商临时模型与轻量模型各4096拍PASS，覆盖零启动、CE暂停、复位优先级、bit47和12位进位，RTL绑定hash `df2e73746182e011642e2e267b79b6860c8ab306c7b3ff963ebd1950c4cad48f`。短行/短帧错误及复位恢复已加入前端TB，112小例和两组完整帧间隙配置重跑中。失败版归档`row-invalid-dsp`，其未完成全帧结果不作验收。继续不上板，等待整机XLR/DSP/RAM、时序和完整回归。

row-legal收尾：主控核对`outflow_rowlegal/ti60f225_oob.place.rpt`为49531 XLR/182 RAM/127 DSP，构建四阶段PASS；XLR超891。归档`row-legal/rtl-vendor-small.json`记录112组逐拍等价、205824 RGB像素，旧完整帧停止不计通过。该JSON的vendor_model_sha256（551e13ef…f5a581）与source_hashes内临时模型（2d8e4f13…ba92a7e）不同，已交A澄清字段来源并冻结实际编译模型；尚不认定为模型漂移，也不跳过版本绑定。

模型哈希疑点已核清：vendor_model_sha256指原厂安装文件，主控重新计算得到`551e13efac2d55cd532097bb28bf50063848af637f62409890962216c1f5a581`；source_hashes记录实际编译临时模型。row-legal的2d8e4f13…ba92a7e为当时仅修移位启动求值的副本，两值不同符合字段定义，不是漂移证据。当前四处always_comb副本在dsp-model.json记录为`bdc3c1b45e11ad3e6af60046ff35df94e2fd60b3a50e553931000bfaa6f1df8b`。已核对驱动在回归开始/结束比较源哈希，变化则失败；A将编译副本随各版归档。关闭此疑点，完整回归/资源/时序门槛不变。

下一版row128采用DSP保存数据/坐标/统计及梯度减法等，同值接口保持。独立前端70 DSP，整机预计128而非最终值；整机综合曾异常退出0x40010004，A正定位重启。当前临时厂商模型diff为四处always @(*)改always_comb，表达式/寄存器不变；修正版两套4096拍单元测试及112+2前端回归按新版本记录。不新增板卡窗口。

row128后续完整构建四阶段通过：49133/60800 XLR、182/256 RAM、128/160 DSP，setup/hold最小0.395/0.026ns。主控核对`row-128-resources.json`、实际布局报告及位流SHA256 `9a5ec55ccf259e1eefab28eb6d41b19174b517554bc60efa3c8fdff48c7fdc04`；XLR超493，离线门槛仍失败。112组厂商模型回归由A报告通过，完整帧仍待结果。A仅在两个隔离副本比较area2/retiming2与area/retiming2综合选项，RTL/接口/时钟不变，不放宽128 DSP或48640 XLR上限。

## 独立中值选择网络候选

主控只读查明`median_source_20261013`由用户另开的聊天「对比顶级作品的数据处理流程 (2)」（`01a135aa-7f0d-7770-b65b-4afa5a4ca86e`）实施。用户在该聊天明确要求学习下载的参考源码并继续实际优化。该线将中值36次比较交换改成19次选择网络，`provenance.json`记录512组二值与362880排列验证；完整720p逐拍等价仍在跑。独立综合1593→1043 LUT、1722→1562 FF为该聊天报告，主控不将其当整机节省量。

其`integrated/outflow/ti60f225_oob.place.rpt`暂报48632 XLR、182 RAM、128 DSP，XLR低于上限8；检查时仍在退火布局，没有最终timing.rpt或bit。相对A已完成row128的49133，当前差501，但必须等本版完整构建确认。主控未终止任何进程、修改该线文件或批准上板。

证据复用核对：该线与A当前前端RTL同hash `dbcd92d4155fd1f4e48b483d6bef8b377ca84744e72f93b85694a6d304867215`，轻量模型同hash `d22e020909af65797981abbbd34a3171f97acac28c6eef1f26711a2bf4d7eb81`，TB同hash `4032101627e2308b94df122c5d0ba8bf98a46667ad6ce1b821dd60338bc6cf59`。两边前端完整回归尚在运行；任一完成后须再核对实际模型、参考、输入及覆盖，才可复用其前端结果。中值自身等价、整机构建及集成源清单仍独立验收，不能由前端同hash推出整链通过。已将上述信息发送A。

随后A汇报编译选项比较：area/retiming2打包49162 XLR，area2/retiming2副本`tmp/ea-optcompile`打包48543 XLR。后者保持107个非前端RTL原样，仅mode和retiming配置不同，主控优先等待该版最终结果；打包数不能代替最终资源/时序，仍未批准板卡操作。

area2/retiming2完整构建收尾：结果已复制至`camera_trials/edgeaware_area/Ti60f225_sc431hai2hdmi_v7/outflow_opt`，主控核对最终布局48543/182/128及位流SHA256 `7198817480d42613eb85e0f64d72b551301c889e7ea97398702054bb66f17eda`，时序0.408/0.026ns。`logs/edgeaware-area/build-inputs.json`实际144项；主控分别重哈希候选目录与原编译副本，144项均匹配，efx_map.exe与清单编译器hash一致。build.cmd已在构建前快照输入，XML固定area2/retiming2。完整前端JSON未完成，不运行或宣称最终全部通过，不提出下载。

最终检查现已实际运行，主控读取`verification.json`：资源/时序/构建绑定、107非前端RTL、201生产文件、RGB非零和两套模型均通过；`rtl_full_evidence_current=false`、像素数与用例数为null、`offline_gate_passed=false`。失败项为完整结果源hash过期，以及该旧结果缺112组逐拍字段，均须由当前完整回归JSON替代。`rtl-wide.json`另有2560×8的8组（四Bayer×两种间隙）逐拍/像素/统计/元数据通过，RTL/TB/轻量模型/参考hash与当前冻结版一致，但不能替代完整高度测试。当前DSP36实现CASCIN均为0、CASCOUT未接，外部专用级联仅属旧row-legal历史，后续报告按当前实现描述。
