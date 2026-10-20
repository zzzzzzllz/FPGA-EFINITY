# 部分和标量读取：实施前契约

保留 `partial_sum/`、`requant/`、`requant_static/` 已冻结文件。独立候选仅扩展两块既有512×16部分和RAM的读控制，并连接同一8 DSP重定标核；不新增RAM、DSP、256bit快照或产品顶层接口。

研究依据为Efinix Titanium primitives指南的EFX_RAM10读口说明、安装版 `efx_ram10.v` 358–415行及alexforencich `axis_register.v` 178–234行。前两者确认OUTPUT_REG=0时一拍读、RE=0保持既有RDATA、同步reset需RE；后者确认单项valid保持至ready以及reset清valid的成熟做法。本接口是串行请求，不需要skid缓冲；由原RAM输出保存数据，不复制第三方RTL。来源记录在 `tmp/blue-plate-whole-plate-budget/scalar-read/research/`。

## 请求、冲突及有效值

- 新增 `scalar_read`、`scalar_lane[2:0]`、`scalar_ready`、`scalar_valid`、signed32 `scalar_data`，复用原 `slot[5:0]`。空闲、无未排空MAC时，在ce=1边沿接受一次请求并锁存slot/lane。
- 下一ce=1边沿读取两块RAM对应地址 `{slot,lane}`，直接拼成原int32，进入保持状态并置valid。busy从请求接受至消费有效值为止持续为1；原MAC部分和不改变。
- valid保持至ce与ready同时为1；保持期间RE=0，输入地址变化不影响数据。ready预先为1也不能在读出边沿消费新结果，最早在下一边沿消费。
- load、issue、权重写、save、restore、scalar_read互斥。多个部分和命令同拍、部分和命令与普通命令同拍、未排空MAC时的请求均报command_error，命令不执行。busy时新命令也拒绝，不替换当前请求。
- 单独ready不是命令；busy时即使同时来了非法新命令，已有效的旧结果仍可按ready消费。Q31组合请求若非法，则连同该请求所带的ready一起拒绝，保留标量valid供重试。
- ce=0保持状态和输出，且不接受/消费；reset优先于ce，取消未完成读、清valid/busy和Q31原值有效位。RAM内容保留；不以输出残留值代表新结果。消费后valid为0，新请求在读出前不得暴露上次valid。
- 原组save仍9拍，restore仍17拍。scalar_read不设置原done；done只代表原组传输。读取尚未完成save或被中断save的槽不在有效使用合同内，调用方需先完整保存，不新增64槽有效位表。

## 与Q31的连接

`q31_scalar_mac8`从已冻结 `q31_static_mac8`独立派生。当scalar_valid=1且scalar_ready=1，合法非constant、非reuse的q_start可与标量消费同拍接受，内部直接把scalar_data装入原值寄存器，忽略外部q_acc。其余Q31请求仍按原契约执行。标量等待时，constant/reuse或ready=0的Q31请求拒绝；不静默丢弃未消费标量。无scalar_valid时直接q_acc路径不变。

Q31期间禁止新的标量读或其他host命令。tap2第一路从标量读接受原值；第二路用原q_reuse，不能重新读取被Q31覆盖的MAC部分和。静态常数旁路不改变原值，原双路证明继续适用。

## 周期预算与验收

独立读预期3个有效边沿：请求、RAM读出、消费。与Q31组合时，消费和Q31接受共用一拍，总计29拍（读请求+读出+Q31的27拍），旧路径为17+27=44拍，预计每动态主输出省15拍。702,480个动态主输出预计省10,537,200拍；两路动态的次消费者继续27拍reuse，无重复读。LPR已知核心预计43,341,492拍，三模型已知小计67,016,248拍。100MHz下分别433.41492ms与670.16248ms，未含DDR及原未计项。

预计仅增加状态/命令判断和32bit来源选择逻辑；地址沿用9bitslot/lane寄存器，输出借用RAM内部保持。必须用独立map给出实际LUT/ADD/FF增量并更新OCR累计账，不把预期当实测。资源上限维持49,248 XLR、204 RAM、128物理DSP。

验收覆盖全部512地址、CE/背压、所有命令冲突、读前/读后reset、过期valid、原full-K分块向量，以及真实tap2双消费者。RTL验证完整K；mapped用有界向量并保留已审查的本地LUT启动模型条件。成功旧仿真不重跑，旧向量用于新候选回归；不执行模型前向或板卡操作。

## 实现与复现入口

实现为 `rtl/psum_scalar_mac8.v` 与 `rtl/q31_scalar_mac8.v`。独立map实测2300 LUT、595 FF、456 ADD、18 RAM、8 DSP，相对冻结六步候选增加91 LUT、1 FF；原MAC、权重bank及两份旧部分和/Q31候选不改。

在仓库根目录运行：

```powershell
& D:/Python/python.exe -B tools/blue_plate/whole_plate_budget/scalar_read/prepare_tests.py
& D:/Python/python.exe -B tools/blue_plate/whole_plate_budget/scalar_read/test.py --bench psum
& D:/Python/python.exe -B tools/blue_plate/whole_plate_budget/scalar_read/test.py --bench scalar
& ./tools/blue_plate/whole_plate_budget/scalar_read/build.ps1
```

build设置当前终端PYTHONHOME；之后在新终端继续：

```powershell
& D:/Python/python.exe -B tools/blue_plate/whole_plate_budget/scalar_read/verify_synthesis.py
& D:/Python/python.exe -B tools/blue_plate/whole_plate_budget/scalar_read/test.py --bench scalar --mapped
& D:/Python/python.exe -B tools/blue_plate/whole_plate_budget/scalar_read/test.py --bench psum --mapped
& D:/Python/python.exe -B tools/blue_plate/whole_plate_budget/scalar_read/finalize.py
```

依赖既有部分和full-K/有界向量、冻结模型与输出通道向量、已认可候选的delivery-freeze、Efinity及Icarus。测试输入缺失或冻结哈希不一致直接失败。单次读3拍、读与动态Q31合并29拍；协议测试插入的CE停顿和背压另外计数。

输出在 `tmp/blue-plate-whole-plate-budget/scalar-read/`。报告及可追踪凭据在 `docs/validation/blue-plate/whole-plate-budget/scalar-read-implementation.md`、`scalar-read-validation.json`。总账纳入实际OCR，但不代表已完成整链或PNR。
