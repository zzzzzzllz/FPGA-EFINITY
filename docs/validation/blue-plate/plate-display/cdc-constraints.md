# 集成时的 CDC 与时序约束

本轮完成 RTL 仿真与独立 map，尚未完成 CDC 物理时序闭合。`prepare_synthesis.py` 的 SDC 只有源时钟10ns、像素时钟13.468ns，用于独立综合；不应把它当成整机可签核约束。大端口测试顶层不分配真实外部管脚，最终时序在整机内部连接后检查。

## 实际参考

- 已下载并阅读 [PULP common_cells v1.37.0 cdc_2phase.sv](https://github.com/pulp-platform/common_cells/blob/v1.37.0/src/cdc_2phase.sv) 的实现与复位/约束说明。它要求 bundled-data req/ack/data 的路径延迟受较快时钟周期约束。研究副本在 `tmp/blue-plate-plate-display/research/cdc_2phase.sv`，本模块没有编入该外部源码。
- 已阅读本机 Efinity 2026.1 文档 `syn-attr-async_reg.html`、`constraint_setmaxdelay-setmindelay.html`、`constraint-set-bus-skew.html`、`tcl-report-bus-skew.html`。`async_reg="true"` 防止同步器被合并/复制，并指导相邻放置。`set_bus_skew` 约束以寄存器/时钟引脚为起点、寄存器/D引脚为终点，输入输出端口不是合法总线偏斜端点。

不能把其他工具的 `-datapath_only` 语法未经验证直接加入 Efinity，也不能用 `set_clock_groups -asynchronous` 或源域到目的域的整体 `set_false_path` 隐去下面的数据路径要求。

## 必须覆盖的实际路径

设 `Tfast=min(Tsrc,Tpixel)`。当前100MHz/74.25MHz目标下 Tfast=10ns；下表采用更紧的8ns数据路径目标和8ns总线偏斜目标，为采样留出余量。若整机时钟改变，应重新计算，不硬编码沿用。

| 发送寄存器 → 接收端 | 目的与约束 |
|---|---|
| `state/results/held[*]` → `state/pending[*]`、`state/active_packet[*]`及其有效性组合判断终点 | 整包数据稳定，数据路径与偏斜均≤8ns；覆盖同拍frame_start直接提交路径，不能只约束pending |
| `state/config_link/held[*]` → `state/display_config[*]`、active有效位及clear_pending判断终点 | 配置原子跨域，数据路径与偏斜均≤8ns；覆盖cfg_received时直用cfg_packet的路径 |
| 两个 mailbox 的 `request` → 各自`req_sync[0]` | 请求第一级异步采样；路径≤8ns。第一级到第二级保持正常目的域时序分析 |
| 两个 mailbox 的 `ack` → 各自`ack_sync[0]` | 确认第一级异步采样；路径≤8ns。第一级到第二级保持正常源域时序分析 |
| `state/time_gray[31:0]` → `state/time_sync0[31:0]` | Gray总线每比特路径≤8ns，整组偏斜≤8ns；保持寄存编码，不允许直接跨组合异或输出 |
| `time_sync0` → `time_sync1`，Gray解码 → 年龄判定/active | 正常像素域 setup/hold 分析，不切断第二级或解码路径 |
| `src_reset`、`dst_reset` 释放同步链 | 共同异步断言，各域同步释放；按工具要求单独检查复位恢复/移除与扇出，不能用复位例外隐藏普通数据路径 |

mailbox源寄存器在目的域接收并回传ack以前不改变；接收的最早时机在request经过两级同步之后。上述数据路径上界确保held位比采样控制先稳定。时间Gray编码每次仅保持或单步变化，8ns偏斜远小于1ms更新间隔。不能只依赖RTL“看起来有两级寄存器”，还需检查映射后的同步器与路径。

## 约束表达与签核步骤

使用 Efinity 支持的 `set_max_delay -from <解析后的源寄存器集合> -to <目的寄存器集合> 8.0`、对应 `set_min_delay ... 0.0`，并对两个held数据总线及Gray总线使用 `set_bus_skew -from <源寄存器/CLK引脚集合> -to <目的寄存器/D引脚集合> 8.0`。这里的集合必须从整机映射结果取得；不是可直接粘贴的占位符SDC。

1. 查明集成实例层级，解析每个源/目的集合并断言非空。held结果总线为716位、配置总线64位、Gray总线32位；综合常量折叠可能减少held字段实际位数，须把减少的位逐项对应为常量/不用位，不能接受空集合。
2. 保留两级同步器的 `async_reg` 属性，确认没有重定时或额外组合逻辑插入同步级之间。当前独立map使用retiming=0。
3. 只在需要消除第一级采样的异步hold关系时，对明确的第一级异步端点使用工具支持的窄例外；不得覆盖held总线或整个时钟域。max/min delay与正常时钟的相互覆盖以工具实际异常报告为准，不假定设置即生效。
4. 对所有CDC路径查看实际数据延迟，而不只看含有利clock skew的slack。检查约束没有被忽略、没有被false_path/clock_groups覆盖；输出 `report_bus_skew` 的slow/fast结果及详细路径。最慢数据/请求/ack路径和每条总线偏斜都应满足上界。
5. 正常域内逻辑也需闭合：bbox面积乘法/IoU/位移比较、确认输出、Gray解码/年龄判定、字符选择与ROM像素流水。独立map通过不证明这些路径达到100MHz或74.25MHz。

本轮不提供未经整机对象解析的自动通配符约束，避免“命令执行成功但实际没有约束任何寄存器”。后续集成应把解析后的实际集合和时序报告加入验收证据。

## 配置频率、失效与停钟前提

配置通道持续发布最新完整 epoch/generation，源缓冲及在途held包保持稳定。允许单源周期一次的连续变化，中间代次可以合并；源确认状态在每次权威配置变化时立即清零。不得在未清空系统的情况下重用旧 epoch/generation 二元组形成ABA。需要每个配置都被外部观察的功能不属于这个最新状态通道。

当配置最后一次变化后保持稳定，两个时钟连续运行时，目的域最多16Tsrc+16Tpixel内获知最终值，之后第一个frame_start清空。结果通道反压不阻塞该独立通道。实测连续39次generation变化、途中epoch变化且旧确认在途被反压，最后配置传播耗时分别86ns、122ns、208ns，低于三组时钟的256ns、384ns、512ns上界。目的域一旦获知新配置，旧包就不能重新点亮；clear_pending也不能被后续成功包覆盖。

系统毫秒时基和src_clk在正常显示期间必须连续运行。若源时钟/计数器要停或重置，必须共同断言本模块复位，不能期待停止的时基判断墙钟过期。像素时钟暂停期间不产生新扫描帧；无复位恢复后，视频上游先保持消隐并等待16个源周期+16个像素周期，让时间/配置跨域恢复，再给frame_start。共同复位可在任一时钟停止时异步断言，各域恢复后独立同步释放；这不等于支持任意单域复位。

499/500ms以源时基判断；显示域时间有同步延迟，视觉清空发生在获知过期后的第一个frame_start，允许这段同步延迟加最多一个显示帧，不允许收到旧包重新启动500ms计时。
