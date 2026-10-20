# 蓝牌脱机启动修正

隔离补丁已完成，回归全部通过。共享 `coding/` 与 release 未修改，没有执行板卡操作。

- [窄接口和集成约束](contract.md)
- [六文件补丁](standalone-boot.patch)，基于 [冻结输入 SHA256](frozen-inputs.json)
- 隔离源码：`tmp/blue-plate-standalone-boot/source/`
- [实际命令、输入/二进制哈希和退出码](../../../tmp/blue-plate-standalone-boot/execution.json)
- [补丁应用验证](../../../tmp/blue-plate-standalone-boot/patch-verification.json)
- [启动审计及参考材料](../../../docs/validation/blue-plate/standalone-startup/report.md)

修改内容：VIO/active/profile 增益同步为389/256/427；曝光为00/70/80、模拟增益80/3F；数字增益00/80位于最后stream-on之前，共166项。I²C释放等待使用bit15。新增初始化NACK锁存和成功状态，保留configured及运行期控制协议。

初始化失败后仍有限地完成原表，不重试；状态为configured=1、init_success=0、init_error=1。复位清除错误并重新初始化。成功仅表示表项均收到ACK，不等于已完成寄存器读回或确认视频输入正常。

新增状态在5MHz域，主实现需同步进入G1状态域。补丁只接出顶层内部线，尚未接入G1状态汇总；不可把未接出的线当作板上可见状态。Flash板型资料不足留在审计报告，不影响本补丁的离线验证。

## 已完成验证

| 检查 | 实际结果 |
|---|---|
| 正常ACK，默认CLK_DIV=32 | 166项字节逐个相符，首次START=6581.101µs，success/error=1/0 |
| 器件地址、寄存器高地址、低地址、数据各单次NACK | 每项均为configured=1、success/error=0/1 |
| 最后stream-on的数据NACK | 正确锁存；对success上升沿和逐拍检查均无假成功 |
| 全NACK | 664个NACK，表仍完成，明确失败，无自动重试 |
| 失败后复位恢复 | 重跑166项、再次等待≥4ms，恢复1/0 |
| 每轮结束后的运行期写入 | 等帧边界；ACK→NACK→ACK；仅runtime error变化，初始化结果保持 |
| 顺序和边界 | 数字增益两项紧邻最终0100=01；stream-on为第166项；无额外表项 |
| 实际VIO RTL及提取的active代码 | 上电、复位、12个帧边界均为389/256/427，phase/gamma=0 |
| 补丁 | `git apply --check`及在独立副本中应用均退出0；结果逐字节等于已测源码 |
| 输入保护 | 编译输入哈希未变；14个冻结工程输入与共享原文件仍一致 |

故障矩阵使用同一实际I²C RTL、CLK_DIV=2缩短仿真，首次START=6559.501µs；另以生产默认分频32完成正常ACK和运行期写入回归。从机模型只驱动ACK开漏，不替换控制器FSM。共有9轮初始化、1521次线上写事务（含27次运行期写），以及12帧增益检查。完整顶层的布局布线、G1状态接入和板上冷启动由主实现后续验证。

日志位于 `tmp/blue-plate-standalone-boot/tests/`：`boot-0`至`boot-6`、`boot-default`和`gains`。执行报告12个编译/运行阶段均exit 0。

## 离线复跑

在项目根目录运行：

```powershell
D:/Python/python.exe -B tools/blue_plate/standalone_boot/run.py
```

需要本机Icarus和Efinity的 `efx_gbufce.v` 仿真模型。`prepare.py`首次冻结输入，后续读取同一快照；生成器不写入原工程。运行前后核对哈希，源文件变化会明确报错。补丁路径相对于被冻结工程根目录；集成到已裁剪G1顶层时按六个文件的窄修改合入，不能覆盖G1顶层。

补丁SHA256：`185c0615db35d459e143dc75eb89b43ba950b85ada88e668a2119ecfde8429c4`。
