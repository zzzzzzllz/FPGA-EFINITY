# 独立串行线性分类 RTL

该模块用于G1算术与资源验证，尚未接入摄像头顶层。输入为已生成的320个特征，归一化、切分、车牌有效性和七字确认由主实现负责。

后续受控扩展：同一内核新增 `WEIGHT_BITS` 参数，只接受10/11，默认仍为下述10位候选及门限。权重ROM/寄存器和乘积宽度随参数变化，signed32输出、协议与41796拍不变；geometry11实验另见 [硬件验证](geometry11-hardware.md)。本文的33RAM资源与历史map记录仍指原默认10位版本，不能用来代替11位实测资源。

## 实现依据与接口

实际读取了本工程 `rtl/simple_dual_port_ram.v`、`rtl/dvi_tx/simple_dual_port_ram.v` 的同步读及初始化写法，并对照 [Efinity Synthesis User Guide](https://www.efinixinc.com/docs/efinity-synthesis-v4.4.pdf) 的 `syn_ramstyle`、`syn_romstyle` 和DSP推断规则。独立模块为 `tools/blue_plate/char_model/rtl/char_linear.v`。

- 单时钟，上升沿采样，同步高有效复位。复位取消任何未完成请求；RAM不用清零，下一请求必须完整写入320项。
- `start_valid && start_ready` 接收位置0..6。之后按序接收320次 `feature_valid && feature_ready`，每项0..32。无需特征地址，内部从0递增。
- 运算中两个ready均为0，忽略未握手的输入。位置7或已握手特征值33..63产生 `result_error=1`、`result_accept=0`，结果同样需握手取走。
- `result_valid`保持直到 `result_ready`；整个结果包在反压下保持稳定。处理结果的同拍不接收新start，下一拍回空闲。
- `score_valid/score_id/score_value`为无反压的调试输出，每类一拍，依ID0..64发出原始分数。最终top2只在位置允许的类别中更新，严格大于比较保留较小ID的同分优先权，次佳来自不同类别。
- 默认权重文件为当前candidate导出的 `w1-s10.bin`，每行恰好10位补码；偏置为 `b1.mem` 32位补码。二进制写法避免Efinity将三位hex视为12位产生20800条宽度警告。权重值与原signed10 hex完全相同。
- 默认分数和分差门限与candidate一致，是有符号比较。更换权重或门限必须重新导出、生成测试向量、仿真及综合；不能只替换显示映射。

采用单个乘法单元，RAM同步读一拍、MAC一拍，每类再加偏置读/加载与排行拍。最后一个特征握手之后固定**41796拍**给出结果：`65*(2+320*2+1)+1`。320项输入加载及输入停顿另计；输出反压延长占用时间，但不会改变结果。

100MHz仅是约束目标；41796拍折合0.41796ms/字、七字计算2.92572ms，尚未完成布局布线，不能作为实测频率或整机帧率。

## RTL仿真

```powershell
D:\Python\python.exe -X utf8 tools/blue_plate/char_model/tests/run_sim.py
```

已有Icarus Verilog运行159组：89个覆盖65类与位置0/1/2的真实字符向量、10个拒识、3个score-bus同分注入、57个极值及固定种子随机特征。还测试输入停顿、忙碌时输入噪声、结果反压、非法位置/特征、load/MAC/hold期间复位和复位后重算。逐项比较所有65类原始分数和最终结果，共10465次类别分数比较，通过；包含额外的hold复位与重算，因此比较数超过159×65。

同分注入只存在testbench的`force accumulator=0`，用于精确验证排行逻辑；产品RTL和冻结ROM无测试答案或测试模式。它不是真实图准确率证据。结果与源/ROM哈希位于 `tmp/blue-plate-char-model/rtl/simulation.json`。

## 独立Efinity综合

```powershell
D:\Python\python.exe -X utf8 tools/blue_plate/char_model/tests/prepare_synthesis.py
Push-Location tmp/blue-plate-char-model/synthesis
& D:/Efinity/bin/efx_run.bat char_linear.xml --flow map --output_dir out
Pop-Location
```

Efinity 2026.1.132.4.5、Ti60F225/I3，map通过。最终候选明确设`retiming=0`，综合资源为：

| 资源 | 实测数量 |
|---|---:|
| RAM10 | 33 |
| DSP48 | 1 |
| LUT4 | 467 |
| FF | 216 |
| ADD | 65 |

RAM实例归属为权重ROM30、偏置ROM2、特征RAM1。此前按有效位数推算约24块没有覆盖综合器的深度拆分和映射开销，应以33块为当前预算。没有据此引入手动分bank。DSP报告为有符号`A*B`，累加使用逻辑加法；不能把“一个DSP”解读成整个MAC都打包在DSP内。未做PNR或板测，也不把LUT/FF直接相加当成最终XLR数量。

默认retiming的首次综合为222 FF，其余相同；关闭retiming后为216 FF。两个配置都曾在原始厂商仿真模型下遇到相同初始化问题，关闭retiming本身不是修复原因。最终资源报告及哈希为 `tmp/blue-plate-char-model/synthesis/synthesis-summary.json`，原始报告 `out/char_linear.map.rpt`。

最终综合仍报告两条只读ROM无动态driver的警告。初始化文件读入有日志，映射网表包含ROM INIT参数；不能仅依据“map PASS”略过ROM内容核对。

## 映射后仿真环境诊断

原厂 `D:/Efinity/sim_models/verilog/efx_lut4.v` 在Icarus下存在可独立复现的初始求值问题：输入始终0000、LUTMASK=c43f，输出0，而真值表要求1。这导致原映射仿真在非法位置测试中进入错误状态并失败，端口断言没有被删掉或放宽。

```powershell
D:\Python\python.exe -X utf8 tools/blue_plate/char_model/tests/check_vendor_lut.py
D:\Python\python.exe -X utf8 tools/blue_plate/char_model/tests/run_sim.py --mapped --lut-init-fix
```

适配只在独占tmp目录复制厂商模型，将敏感列表`always`改成`always_comb`以保证初始组合求值；保留原版权头，不修改安装目录、硬件RTL、综合网表或ROM。最小测试中原模型失败，适配副本的初始化和64个真值表条目通过。原模型SHA-256为 `49f8494172ab8ff1be8f9a487015451e924cff911ab36cfcefe2555fbb06586e`，适配副本为 `70c2e9fa0e813d2152dcc9dcaee614a60214b394be2a9855d5648671a7c1abfe`。主控亦已独立复现。

映射测试使用4个真实/拒识向量和4个极值/随机向量，仍核对每个65类分数、位置限制、结果握手、非法输入、复位和精确延迟。它不使用tie注入，避免依赖综合网表内部寄存器命名。**适配模型下8组全部通过，共650个类别分数精确一致，延迟41796拍**；650包括额外的hold复位与重算。记录为 `tmp/blue-plate-char-model/rtl-mapped/simulation.json`，包含原模型、适配模型、综合网表和ROM哈希。原始厂商模型未经适配的失败不能被表述为已通过。

本轮结束于独立分类核算术、协议及综合可实现性验证；不等于PNR时序、板上识别或整牌准确率达成。所有输出均在独占 `tmp/blue-plate-char-model/`，没有复用主线build目录或覆盖release。
