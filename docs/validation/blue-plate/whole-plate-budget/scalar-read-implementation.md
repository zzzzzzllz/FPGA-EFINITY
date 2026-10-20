# 部分和标量读：独立候选

本候选用现有两块部分和RAM直接读出指定slot/lane的原int32，消除动态主输出的整组恢复。RTL和map上的独立读为3拍，与Q31接受共用消费边沿后，动态主输出从44拍降为29拍。相对已冻结常数旁路/六步舍入候选，实际map增加91 LUT、1 FF，ADD、RAM和DSP不变。

旧 `partial_sum/`、`requant/` 和 `requant_static/` 均保留。后者已完成主控独立复核：原2,387条向量及追加600条原值保持向量通过，凭据为 `tmp/blue-plate-review/requant-static/review-result.json`；冻结清单位于 `tmp/blue-plate-whole-plate-budget/requant-static/delivery-freeze.json`。本次在新模块上验证旧向量，没有重跑旧核。

## 研究与选型

读取[Efinix Titanium primitives指南](https://www.efinixinc.com/docs/efinity-quantum-ti-primitives-ug-v3.3.pdf)的EFX_RAM10部分（22–25页），并检查安装版 `D:/Efinity/sim_models/verilog/efx_ram10.v` 358–415行：OUTPUT_REG=0仍为同步读；RE=0时RDATA保持，reset控制输出而非清除存储内容。

同时读取[axis_register.v](https://github.com/alexforencich/verilog-axis/blob/master/rtl/axis_register.v) 178–234行的单项缓冲实现，确认valid保持至ready、reset清valid的接口方式。源码通过网页读取；本机urllib下载超时，未声称已保存该源码。研究记录在 `tmp/blue-plate-whole-plate-budget/scalar-read/research/sources.json`，没有执行或复制参考RTL。

本任务只有一个未完成请求，原RAM输出已能保持数据，因此选用串行读状态和valid握手，不增加skid队列、32bit副本或256bit快照。实施前契约保存在 `tools/blue_plate/whole_plate_budget/scalar_read/README.md`。

## 接口及实际机制

`psum_scalar_mac8`在原组save/restore状态之外增加SCALAR_READ与SCALAR_HOLD。接受请求时复用原slot/lane寄存器；下一有效边沿同时读取两块512×16 RAM，拼成32bit；随后关闭RE并保持valid，直到ce与ready同时为1。scalar_data只在valid期间有意义，消费后不以旧数据冒充有效结果。

请求接受至消费期间busy有效；新load、issue、写权重、save、restore和标量读均拒绝并报告command_error。IDLE同时发生的部分和/普通命令也拒绝；未排空的MAC允许原运算退休，但不接受标量请求。ce=0不推进；reset优先于ce，取消读及valid，保留RAM内容。读取被中断save的槽仍需调用方先完整重写，合同没有增加隐藏的槽有效表。

`q31_scalar_mac8`只修改host命令判断、原值来源选择及内部标量握手。当scalar_valid、scalar_ready、合法非reuse/非constant q_start同时成立时，在同一边沿消费RAM响应并将其装入原值寄存器，忽略外部q_acc；后续乘法和六步舍入沿用已冻结候选。没有标量响应时仍支持原q_acc路径。

等待标量响应时，ready=0、非法参数、reuse或constant请求均拒绝，且不会让无效Q31请求偷偷消费标量。单独ready不是新命令；独立消费即使伴随被拒绝的普通命令仍可完成。Q31处理期间禁止新的标量读。tap2第二路沿用原q_reuse，常数旁路不覆盖原始int32。

原save仍为9拍，整组restore仍为17拍，K分块续算保持原接口。标量读不产生原done脉冲。

## 周期与总账

| 事务 | 有效拍数 |
|---|---:|
| 独立读：接受、RAM读出、消费 | 3 |
| 新动态主输出：读接受、RAM读出、Q31接受至消费 | 29 |
| 旧动态主输出：整组restore + Q31 | 44 |
| 每动态主输出节省 | 15 |
| tap2动态次消费者（reuse，不重复读） | 27 |

计数包含请求接受和输出消费。新路径的标量消费与Q31接受共用一拍，故增加到原27拍Q31之上的开销为2拍，不再另加3拍。CE停顿和背压另计，测试明确注入后再核对有效事务时间。

702,480个动态主输出共节省10,537,200拍。静态输出的2拍旁路、稠密MAC、全部组save及K分块restore均保留。

| 已知服务小计 | 上一候选 | 本候选 |
|---|---:|---:|
| LPR核心拍数 | 53,878,692 | 43,341,492 |
| 按100MHz换算 | 538.78692ms | 433.41492ms |
| 三模型已知拍数 | 77,553,448 | 67,016,248 |
| 按100MHz换算 | 775.53448ms | 670.16248ms |

这是由实测单次事务和冻结模型次数推算的服务小计。DDR、非卷积、context宽gain、CTC等原未计项继续单列；没有执行完整网络或验证整机100MHz。颜色CNN仍计入；500ms/三次确认内部合同未修改，也不作为用户目标不可能的依据。

## 验证范围

新RTL回放原178,888拍full-K向量，在96组结果处加入768次标量读，共182,056拍、1,456,448个lane状态检查。覆盖K=3328的2048+1280分块、8/16空间点及4/8有效lane。新增读取使用保存后的原值，并逐拍确认MAC部分和不变。映射回归使用原有界K=12向量及同样768次读取，共8,808拍。

专门接口测试在RTL与mapped上分别覆盖全部512地址、输入地址接受后变化、CE在读前/握手/输出阶段暂停、预先拉高ready、背压、所有普通命令和Q31冲突、非法Q31握手保留响应、消费后清valid、读前/读后reset，以及RAM保留。原组save/restore与未排空MAC拒绝也重新检查。

真实数据取自已有 `integer-deployment-audit/output-channel-mac-vectors.npz`，不运行模型：8组记录、2,320次MAC步骤、56个主输出及8个tap2次输出。每组先实际MAC再save，主输出通过新标量读交给Q31；次输出复用原int32，并在两消费者之间插入常数旁路。每次比较原始int32、完整64bit乘积及A8结果。此处强制真实主输出走动态路径以验证读入值，未把直接给定的常数当作动态数值证据。

映射仿真沿用已审查的本地LUT启动适配：仿真副本的敏感列表改为always_comb，厂商文件、RTL及网表均不改。此次152种LUTMASK通过39,064项启动/四态真值表比较；mapped结论保留该条件。所有用例数量、周期、源文件哈希和日志见 `scalar-read-validation.json` 及分项收据。

## 实际资源

| map资源 | 上一候选 | 本候选 | 增量 |
|---|---:|---:|---:|
| LUT4 | 2,209 | 2,300 | +91 |
| FF | 594 | 595 | +1 |
| ADD | 456 | 456 | 0 |
| RAM10 | 18 | 18 | 0 |
| 物理DSP | 8 | 8 | 0 |

map确认只有原16 RAM权重bank与2 RAM部分和，8个DSP；没有第二份组快照。状态、地址选择、输入选择和冲突控制已计入实际LUT/FF增量。提供10ns约束，map通过，尚无PNR时序结论。

含实际OCR模块（520 LUT、339 FF、96 ADD、1 RAM）后的总账：视频外组合槽21,976、FF 10,322；视频已place24,090 XLR。跨模块理想FF配对算式46,066（余3,182），模块内理想配对47,011（余2,237），不配对56,388（超7,140）。这些是配对条件算式，不是布局布线界限，未包含尚未实现的调度/DDR控制逻辑。

RAM规划仍196/204：已map150，外部灰度分配14，引擎未实现分配32；OCR使用原resize槽，无重复计数。物理DSP仍97/128。总预算保持49,248 XLR、204 RAM、128物理DSP。

本单点已消除动态标量的重复整组恢复，独立模块未接入产品顶层。接下来整合所需的是加载/张量调度与DDR服务，不需要为本次收益复制存储或改模型。实际设备HWC紧密行及context冻结行距仍以部署清单为准，旧16B行对齐流量仅作保守场景。
