# 脱机启动修正接口与范围

冻结原输入来自 coding/edge-quality-30fps；只生成隔离副本和统一 diff，由主实现合入。原工程与 release 不写入。

- `i2c_master_ctrl_top` 新增两个 5 MHz 域输出：`init_error` 为初始化事务完成时发现 NACK 的锁存状态，仅 rst_n=0 清除；`init_success = configured && !init_error`。
- `sensor_response[2]` 仍为 configured，表示全部表项结束；原 runtime error、ack 和读回字节布局不变，初始化失败不阻断运行期命令，也不触发自动重试。
- 顶层把新增输出接至 `sensor_init_success` / `sensor_init_error` 内部线，供主实现接入 G1 状态汇总。此补丁不扩展 VIO 布局、FPGA 引脚或外设配置；未接入汇总的状态线可能被综合裁剪。
- 两个状态均属于5MHz域；主实现须同步后再用于G1状态域，不能跨域直接组合。复位后success/error均为0，完成后为1/0或0/1；初始化中允许0/1表示已经发现错误。最后stream-on的NACK必须与表完成一起判定，不得输出短暂success。
- VIO、active 初值/复位值和当前 profile 同步为 RGB 389/256/427；保留帧边界提交和现有调节能力。
- ROM 曝光 00/70/80，模拟增益 80/3F，末尾增加数字增益 00/80，0100=01 仍为最后事务；表长166，8位地址/计数能够表示结束值166。
- I2C 复位计数器改16位、bit15饱和与释放，在5MHz下等待6.5536ms。时序基准仍是现有 w_arstn；物理摄像头复位极性由主控结合板图确认。

仿真直接使用冻结后的实际 I²C 栈和开漏从机模型，覆盖正常ACK、器件地址/寄存器地址/数据NACK（含最后stream-on）、全NACK、错误锁存、运行期命令、复位恢复、166项顺序及≥4ms首次START。增益用实际VIO输出初值和提取的active帧边界代码验证，不能只核对JSON。

已读成熟实现与设计依据：审计目录报告中的SC431HAI手册、Efinix AN033 v3.1、当前OpenCores I²C控制栈及其已有 nack_error 事务锁存。复用 nack_error，不另写I²C驱动。
