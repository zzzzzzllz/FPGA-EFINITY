> 历史技术记录。仅说明记录时的版本；当前操作与状态以 [使用指南](../../../docs/for-reader/usage.md) 为准。文中旧路径用于溯源，不是当前运行入口。

# SC431HAI 720p 高帧率试验

2026-10-10：1280×720 的采集计数可稳定达到约 60 帧/秒，但用户确认画面有条纹和结构错乱，未通过显示验收。切换 Bayer 排列及补齐 21 个读出寄存器后仍未解决。已停止试验；用户断电重启后，重新加载全幅 2560×1440、约 30 帧位流，画面结构恢复；重新白卡校准为 RGB=389/256/427 后，用户确认白卡颜色正常。

## 使用

- `load-camera-720p60.cmd`：加载保存的 720p60 试验位流，并应用原白平衡参数；此位流显示验收未通过。
- `build-camera-720p-native.cmd`：构建 `camera_trials/720p_native/` 中的 720p60 源码。
- `load-camera-720p-native.cmd`：加载该目录最新构建的位流。
- `D:\Efinity\bin\python3.bat camera-720p-native-control.py --samples 5`：读取尺寸、帧数、错误、MIPI 字节时钟及部分寄存器读回。
- `test-camera-720p.cmd`：运行整帧 Bayer 转换和 DDR 数据排列仿真。
- `load-camera.cmd`：恢复原先的全幅 2560×1440、30 帧版本。

以上下载均写入 FPGA SRAM；断电后需重新加载。默认 `load-camera.cmd` 和全幅稳定工程没有修改。两路试验目录 `camera_trials/720p112/` 的位流不能用于正常显示。

## 试验配置

| 项目 | 设置 |
|---|---|
| 传感器输出 | 1280×720 RAW10，像素合并 |
| MIPI | 四路，3018=7a、3019=00 |
| HTS / VTS | 1400 / 750 |
| 曝光 3e00/01/02 | 00/5d/10，1489 个半行 |
| FPGA 接收时钟 | 100 MHz |
| RGB 增益 | 397 / 256 / 471，Q8.8 |
| Gamma / Bayer | 关闭 / BGGR |
| FPGA 程序标识 | 0x60101005 |

传感器完成配置并读回 streaming=1 后，FPGA 才解除 MIPI 接收器及输入 FIFO 复位。图像转换等待首个帧同步边沿，避免将启动时的半帧记作采集错误。

`raw_720p.v` 每周期处理四个 RAW 像素，使用相邻行和相邻列补齐颜色，输出四个 RGB 像素。DDR 写入宽度为 128 位，直接写入完整数据字；没有再缩成 640×360。最上面一行没有前一行可供补色，使用本地采样值填充。原白卡增益继续使用，720p 模式的最终颜色和视野仍需显示器人工确认。

## 验证与试验记录

最终启动修正版在 30.547 秒内增加 1833 帧，实测 60.0059 fps；31 次采样均为 1280×720，采集错误计数从启动起为零，MIPI 错误标志为零，DDR 就绪，未在采样中出现显示欠载。记录见 `logs/camera-720p60-final-result.json`；保存的位流为 `verified60/final.bit`，SHA-256 为 `d12ea9aab2ab3e1e8437db7492427ab35846fe6ac0892a3ff6f69e4540f8854d`。综合、接口、布局布线和位流生成均通过，最小建立余量 0.394 ns、保持余量 0.027 ns。完整参数保存在工程目录 `mode-720p60.json`。

第一份 60 帧位流在 30.484 秒内增加 1829 帧，实测 59.9987 fps；31 次采样均为 1280×720，无新增采集错误，MIPI 错误标志为零，DDR 就绪，未在采样中出现显示欠载。该版本有 1 次启动半帧错误，保存在 `verified60/ti60f225_oob.bit`；记录为 `logs/camera-720p-native60-result.json`。

整帧仿真覆盖四种 Bayer 排列、像素顺序、有效信号间隙、帧复位、白平衡增益和饱和截断。启动修正版另覆盖首帧前的零碎数据，见 `logs/camera-720p-native-full-simulation.log`。128 位入口数据排列仿真（不包含完整 DDR 和 HDMI）见 `logs/camera-720p-ddr-simulation.log`。

112 帧参考来自 [瑞芯微 SC431HAI 驱动](https://github.com/rockchip-linux/kernel/blob/develop-6.1/drivers/media/i2c/sc431hai.c)，原表为 24 MHz 输入、两路 MIPI、每路 630 Mbps。本板寄存器读回正确，但两路配置出现错误帧后停止接收；连续时钟模式、初始化后复位和输入延时 32 的试验均未得到可用采集，见 `logs/camera-720p-trial-config.json`。

四路配置保持原时钟，将 HTS 从 1400 缩为 750、VTS 保持 750 后，传感器未输出 MIPI 时钟。该失败版本保存在 `camera_trials/720p_native/failed112/`，日志为 `logs/camera-720p-native112-load.log`。60 帧只是已测得的采集计数，显示验收未通过；目前没有确认可用的 720p 高帧率配置。


## 花屏诊断与回退

- `0x60101006`：每帧计数为 230400 个 128 位字，DDR 写入持续，HDMI 有 921600 个非黑像素。累计欠载标志为 1，未区分启动与运行阶段；先前的瞬时欠载采样不能证明整个运行期间无欠载。
- `0x60101007`：在 RAW 转换后注入像素编号图，经过真实 DDR 和显示输出，逐像素与编号比较。8 次抽样对应的每帧 921600 个像素均无差错，见 `logs/camera-720p-display-pattern-status.log`。测试覆盖数字输出端，不包含 HDMI 线缆和显示器本身。
- `0x60101008`：通过 JTAG 分点读回 DDR 前的 RGB，预览明显偏紫。切换 Bayer 排列只改变颜色，用户确认结构异常仍在。预览由跨帧分点采样组成，不是同一时刻的完整帧。
- `0x60101009`：沿用四路原时钟，补齐公开 720p 表中的 21 个模拟读出寄存器。构建通过，采集仍约 60 帧，但用户确认仍有条纹或错乱。寄存器差异见 `logs/camera-720p-readout-changes.json`。

诊断位流及对应顶层保存在 `camera_trials/720p_native/diagnostic-display/`。诊断模式中 Gamma 控制位被用于选择像素编号图；它不表示普通 Gamma 功能。`camera-720p-display-control.py` 和 `camera-720p-snapshot.py` 仅对应 `readout.bit`（`0x60101009`）。诊断脚本需从工作区根目录运行。试验主源码及 `outflow_full` 位流已恢复为原 `0x60101005`，同样未通过显示验收；`verified60` 是历史目录名，不表示显示已验证。

首次直接加载旧 30 帧位流后，用户仍看到结构异常。原表没有软件复位，也未覆盖部分像素合并寄存器，怀疑传感器保留了试验状态。用户彻底断电后重载，结构恢复，剩余偏色另行调整。不能只凭 FPGA 下载成功认定传感器已完整复位。

30 帧位流 SHA-256 保持 `8856fef875d9434260f9b55aaf9d3689527b45a63dd02b26845bb155f94d5f8c`。断电后重载记录为 `logs/camera-720p-powercycle-restore30-load.log`，随后 5 次采样均为 2560×1440，采集错误、MIPI 标志和瞬时欠载均为零，DDR 就绪。原白卡校准记录备份为 `logs/white-balance-before-720p-recovery.json`。最新参数 RGB=389/256/427 保存到 `white-balance.json` 和 `load-camera.cmd`；调暗后的 12 次白卡采样通道均值为 171.74/260.69/156.21，通道最大相对波动小于 0.4%，用户确认白卡颜色正常。
