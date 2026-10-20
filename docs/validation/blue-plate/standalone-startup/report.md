# 脱机启动只读审计

审计日期：2026-10-18。对象为 `coding/edge-quality-30fps` 的现有启动链路，供蓝牌 G1 集成使用。本次只读取工程、离线仿真并保存报告，没有修改共享 RTL、调用控制程序或操作板卡。

**当前加载后的画面参数依赖两条主机控制命令。将现有 bitstream 直接写入 Flash，不能保证得到相同画面。** 已定位白平衡、曝光/增益、初始化等待和错误状态四项；脱机 Flash 接线还缺本板原理图和器件信息。

## 默认值和主机依赖

`load.cmd` 先以 `-m jtag` 配置 FPGA SRAM，再执行 `control.cmd --set 389 256 427 0 0 ...`，最后执行 `--sensor-restore config/sensor.json`。这三步中，后两步不会因 FPGA 从 Flash 启动而自动发生。

| 参数 | RTL 上电路径 | 加载脚本完成后 | 最小修正位置 |
|---|---|---|---|
| RGB 增益 | VIO 为 397/256/471；active 初值和复位值相同；每个摄像头帧起点重新采样 VIO | 389/256/427 | `debug_top.v` 的 OUT0/OUT2 改为 `0x185/0x1ab`；顶层 active 初值与复位值同时改；同步 `full_view_profile.json` |
| Bayer phase / gamma | 0 / 0 | 0 / 0 | 保持 |
| 曝光 3E00/01/02 | `00 BA D0`，2989 个半行 | `00 70 80`，1800 个半行 | ROM 两字节 BA→70、D0→80 |
| 模拟增益 3E08/09 | `80 2A`，约 2.021 倍 | `80 3F`，约 3.032 倍 | ROM 3E09：2A→3F |
| 数字增益 3E06/07 | 初始化表没有显式写入 | `00 80`，单位增益 | 建议在 stream-on 前补写两字节，让启动值可追溯 |
| 输出尺寸 / 翻转 | ROM 为 2560×1440 / 3221=60 | 相同 | 保持 |
| HTS / VTS | 表中未显式写入 | 快照为 1400 / 1500；restore 仅核对，不修改 | 不把快照误算为脚本写入；冷启动后读回核验 |
| 视图 / median / recognition | UI 复位为 color / off / off | color / off / off | 当前功能默认已一致；G1 自有识别开关另按集成定义 |
| threshold / algorithm / ratio | active threshold=56；Sobel；1/2 | 相同 | 无需因 VIO threshold=32 而改 active；VIO 需 toggle 才提交 |
| frame mode | LIVE | live | 保持 |

曝光换算依赖实际帧率和行长：按 30 fps、VTS=1500，2989/1800 半行约为 33.211/20 ms；半行寄存器值才是本次确定的启动差异。手册说明见本地 SC431HAI 数据手册第 23—25 页。

源文件证据：[source-audit.json](evidence/source-audit.json) 包含 164 项 ROM 写入、快照对照、VIO 初值及文件 SHA256。`host_restore_writes` 明确只有 3E00/01/02、3E08/09、3E06/07 七个寄存器。`sensor_control.py` 另以 3812=00/30 包围更新并读回核验；它不恢复 HTS/VTS、尺寸或翻转。

只改 active 不够：摄像头首个帧边界会从旧 VIO 值覆盖它。只改 profile 也不够：XML 直接编译 `debug_top.v`，debugger auto-instantiation=off；`tools/build-project.ps1` 复制并编译源文件，没有从 profile 生成该模块。`control.py` 读取 `full_view_profile.json`；另一个 `debug.json` 含旧值，不能作为当前硬件初值来源。

## 初始化等待与错误状态

顶层由 PLL lock 合成 `w_arstn`，`o_cam_rst_p=~w_arstn`。5 MHz 域计数到 bit12 后释放 I²C 模块，计数部分为 819.2 µs。独立 testbench 逐字复制顶层计数块，直接编译现有 I²C RTL，以开漏上拉且无从机应答的总线运行：

```text
MEASURE first_start_after_w_arstn_us=846.701
MEASURE no_sensor_ack configured=1 runtime_error=0 starts=164 time_us=207560.300
PASS observed all-NACK init still declares configured
```

编译与运行均 exit 0，表示成功复现当前行为，不表示初始化正确。[运行日志](evidence/run.log)、[命令与源文件哈希](evidence/execution.json)、[testbench](evidence/tb_startup.sv)。传感器手册第 8 页要求 XSHUTDN 释放至初始化的 T4 **至少 4 ms**。当前从 FPGA 逻辑复位释放至 START 仅 0.847 ms；实际 XSHUTDN 与 `o_cam_rst_p` 的极性/中间电路尚无本板原理图证明，因此不能把这个仿真直接等同于已测得的物理时序。

建议最小修正：将现有计数器扩为 `[15:0]`，饱和检测和输出均使用 bit15，等待约 6.5536 ms，再验证首次 START 至少 4 ms。无需新增定时模块。还应按本板连接确认传感器复位和外部时钟在此期间已稳定。

已在独立 testbench 中仅替换上述计数位，保持现有 I²C RTL 不变，首次 START 为 **6581.101 µs**，编译/运行均 exit 0；[建议延迟的仿真日志](evidence/proposed-delay-run.log)与[命令](evidence/proposed-delay-execution.json)保留。此结果验证计数方案，未将改动应用到工程，也未验证板上复位电路。

`i2c_master_reg_set` 的 finished 仅为 `cnt==DATA_LENGTH`，cnt 在 wr_done/rd_done 时前进；它不接收 NACK。`i2c_master_ctrl_top` 的 error 仅记录主机运行期命令，因此断开传感器也可得到 configured=1/error=0。最小状态修正可锁存初始化 NACK，并将其作为启动失败状态；不要简单把内部 configured 门控掉，否则会改变初始化/运行期命令的切换条件。若继续沿用现有 configured 含义，应明确它只是“表项结束”，由单独成功状态决定传感器是否可用。关键寄存器读回比较可随后用于冷启动验收，不能用 configured 替代。

补入数字增益两项时，保持 0100=01 为最后一项；表长从 164 调整为 166，连同 ctrl 的 DATA_LENGTH 和相关检查一起更新。现有 ROM 参数向下传递深度，地址宽度仍为 8 bit。HTS/VTS 不应无依据顺手改动。

顶层 `w_confdone=1'b1`，显示延迟不是传感器成功确认。即使 HDMI 开始输出，也需分别检查 sensor init、DDR 初始化和连续帧输入。

## 脱机配置的硬件边界

本地 `docs/reference/hardware/TI60F225_DEMOBOARD-装配图.pdf` 为带 EliteStek 标识、日期 2026-03-13 的装配图，能看到 JTAG、CRESTN 和 SELMODE 等标识，但不能确定 Flash 料号、电源输入规格或 SELMODE 对应电气状态。

公开资料中找到两类板卡，但均不能直接认定为本板：

- [Efinix Ti60 F225 DK v2.6](https://www.efinixinc.com/docs/ti60f225-devkit-ug-v2.6.pdf) 使用 Ti60F225C4 和 HyperRAM，与项目 DDR3 平台不同。
- [OVS 的 VF-Ti60F225 页面](https://www.szovs.com/en/fpga-development-board/726967) 提供 HDK V2.2（2026-10-14）下载入口，但未取得并匹配其原理图/BOM。该页的板卡供电、Flash 容量不能移用于当前装配图。此前 V4.1 PDF 的网页读取超时，未作为已读设计证据。

已实际下载并阅读 [Efinix AN033 v3.1](https://www.efinixinc.com/docs/an033-configuring-titanium-fpgas-v3.1.pdf) 的配置模式、连接图、电源复位、Flash 选择和 JTAG bridge 章节。材料位于 `tmp/blue-plate-standalone-startup/an033-v3.1.pdf`，SHA256 为 `b0b355b3e3c717aa5652ae670ab0c9cc27321087bd612b95e3cddb5589a294b5`。核心适配条件如下：SPI active 需要 CSI/TEST_N/SSL_N 为高；Ti60 配置使用三字节地址；单镜像从地址 0 读取；JTAG bridge 先临时配置桥接 bit，再向 Flash 写 SPI hex。选择此成熟路径的原因是现有板有 JTAG 接口，无需另加主机控制器，但仍需确认本板 Flash 接线。

当前 XML 已设置 active、x1、DIV8、enable_roms=on、CRC/compression=on，同时生成 bit/hex；这些是离线生成选项，**不是已写入 Flash 的证据**。本机 `D:/Efinity/scripts/efx_run.py:843` 将 `cold_boot` 列入 `pgmignoreopts`，读取 XML 时不把它传入 pgm 参数；因此不能把 XML 的 `cold_boot=off` 当作禁用冷启动的开关，也无需为脱机启动盲改为 on。[工具源码定位与哈希](evidence/efinity-option-audit.json)。Flash low-power 选项表示配置结束后让 Flash 休眠，不等于禁止下次上电配置。

本机 Efinity 文档已核实 `read_flash`、JTAG bridge、地址/长度和 verify 参数；正文摘取保存于同一 tmp 目录。特别是 `export_bitstream_flashloaderv3.py` 会连接板卡并配置 FPGA、写 Flash，不属于纯离线导出，本次没有执行。

在准备可执行烧录步骤前，主控还需取得或核验：

1. 与装配图版本一致的原理图/BOM：电源输入电压和极性、Flash 料号/容量/电压、SPI 与 SELMODE/SSL_N 路径、CRESET_N 上电释放电路。
2. 计划使用的下载器/目标标识，以及 Flash JEDEC ID 与工具支持情况。桥接加载本身会替换运行中的 SRAM 配置，应安排在板卡验证窗口。
3. 原 Flash 备份范围、实际 SPI 镜像长度和哈希、地址 0 的单镜像计划及 verify 方式。不能拿 JTAG bit 文件长度直接当作 Flash 有效负载长度。

本报告只列准备条件，没有执行探测、读取 Flash、擦除或烧录。

## 建议验收顺序

先在 G1 隔离工程同步控制源/active/传感器 ROM 默认值，复用现有模块延长初始化等待并暴露初始化失败。离线检查首帧及后续帧的 389/256/427、正确曝光/增益写入、stream-on 顺序、首次 START 延迟；给定 NACK 时不能显示传感器成功。随后在授权板卡窗口只加载 SRAM，省略两条配置命令，验证画面与已确认基线一致并读回关键寄存器。最后在板卡资料和备份齐备后，由主控决定 Flash 操作，验收时断开 PC 控制连接并真实断电重启。

本次交付是有复现证据的启动修正清单；尚未实施这些共享代码修改，也没有证明实际脱机冷启动成功。
