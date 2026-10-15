> 历史技术记录。仅说明记录时的版本；当前操作与状态以 [使用指南](../../../docs/for-reader/usage.md) 为准。文中旧路径用于溯源，不是当前运行入口。

# 720p60 摄像头画质测试

独立于原来的全视野 30 帧基线和 M10/O1 主工程。摄像头中心 1920×1080 RAW10 输入，经逐像素颜色重建和 3:2 面积缩放，输出 1280×720。原 30 帧源码、位流、校准、加载入口和交付包保持不变。

## 当前状态（2026-10-14）

已修正两个相邻像素共用一个 RGB 值的问题。采用 3×3 双线性重建：保留每个位置实际采到的颜色，另外两色用同色邻域插值；四边镜像延拓，保持 Bayer 相位。RGB 在 10 位域完成缩放，随后应用增益并输出 RGB8。首行已有有效颜色，不再复制第二行覆盖它。

构建 `0x60101064` 已上板，约 30.58 秒内采集和处理各增加 1836 帧，实测 60.04 fps，错误计数无新增。用户反馈“画面正常，但清晰度差不多”，随后反馈画面闪烁。因此，像素重复已修复，实屏清晰度改善尚未确认。

用户选择保留 60 帧，优先测试约 10 ms 曝光并补偿亮度。当前源码 `0x60101065` 使用 1381 个半行曝光，寄存器 3e00/01/02=00/56/50；模拟增益 3e08/09=80/3d（约 2.94 倍），RGB 增益仍为 704/512/758，Gamma=0、BGGR、彩色视图。新增启动读回 `sensor_exposure_gain`，期望值为 `0x0565803d`；控制脚本读回不符会报错。10 ms 配置已上板，用户确认灯光闪烁减轻、亮度合适；清晰度仍不满意，并报告约十秒瞬间黑屏。当前源码与板上程序 0x60101066 增加编码前逐帧诊断。两次热加载未启动采集；用户完整断电后，同一位流采集正常。用户确认黑屏时，编码前黑帧、像素数、行/帧周期、复位和欠读计数均未增加，范围收窄到编码/串行输出/物理 HDMI/显示器接收侧；仍未定位具体原因。用户暂时不方便换线或接口对照。

参考源码、许可证、提交信息和防闪烁依据见调研记录（历史路径：`../../research/demosaic-60fps/findings.md`）。方向自适应重建尚未实施，本轮先处理用户反馈的闪烁。

## 验证

- 8 组四 Bayer 排列、连续/间隙输入的随机帧→黑帧检查，以及 8 组斜坡/斜向细线检查通过。逐像素对照独立 Bayer 掩码卷积参考，并断言每个实测 CFA 颜色保持不变。
- 完整 1920×1080 连续两帧通过：每帧 921600 个 RGB 输出与参考一致，灰度/Sobel 帧号、行尾、帧尾正确，无过载、缓存残留。最后像素在 100 MHz 的第 1565489 周期输出，约 15.655 ms，满足仿真帧期限。
- `0x60101064` 构建占用 30538/60800 XLR、139/256 RAM、60/160 DSP，建立/保持余量 0.406/0.026 ns。`0x60101065` 的图像前端与已验证版本逐字节相同，仅调整曝光/模拟增益和启动读回。
- 30 帧基线 83 个交付文件逐字节一致；位流、白平衡、加载脚本和 ZIP 哈希一致。
- 曝光 ROM 与读回打包的定向测试见 `tb_exposure.v`、`reports/exposure-simulation.log`。

在本目录运行：

```powershell
.\test.cmd
.\test.cmd --display-watch
.\test.cmd --exposure
.\test.cmd --detail
.\test.cmd --chain
.\build.cmd
D:\Python\python.exe verify_build.py
.\load.cmd
.\control.cmd --samples 31 --interval 1
```

`test.cmd` 使用本机 Python/NumPy 和仓库 `tools/iverilog-12/app/bin`。Efinity 路径在 `efinity-path.cmd`，当前使用 `D:\Efinity`。`load.cmd` 只加载 FPGA SRAM，随后应用白平衡与彩色视图，不写 Flash。使用 `control.cmd --view color|gray|edge` 切换视图；运行前确认板卡可占用。

## 结果与恢复

- `reports/build-verification.json`：构建、时序、资源、源码哈希及基线校验。
- `reports/board-bilinear-verification.json`：14.5 ms 逐像素重建版的板测与人工反馈。
- `reports/board-flicker-before.log`：防闪烁调整前的亮度采样，整帧统计会同时受场景运动影响。
- `reports/verification-small.json`、`verification-detail.json`、`verification-chain.json`：离线验证。
- `backups/edge60-bilinear-14ms-20261014/`（仓库根目录）：14.5 ms 逐像素重建版位流、控制脚本和报告，运行其中 `load.cmd` 恢复。
- `backups/edge60-quality-pair-20261014/`：更早的相邻列重复版，仅用于历史对照。

原 30 帧完整视野恢复入口为仓库根目录 `load-camera.cmd`，交付包为 `deliverables/Ti60F225_SC431HAI_FullView30_20261011.zip`。当前 60 帧模式仍是中心裁切，视野小于原 30 帧版。

0x60101065 的可恢复备份位于 `../../backups/edge60-bilinear-10ms-20261014/`，运行其中 `load.cmd` 可恢复。新诊断不改变像素、曝光或增益；黑屏根因尚未确认。

诊断版 66 的热加载失败、冷启动成功和运行数据见 `reports/board-display-watch-verification.json`。当前目录 `load.cmd` 指向诊断版，不能作为黑屏已修复的版本交付。若热加载后摄像头不计帧，需完整断电再加载。65 的恢复入口位于上述备份目录。

诊断 66 构建占用 35973/60800 XLR、139/256 RAM、60/160 DSP，最小建立/保持余量0.450/0.026ns。显示计数采用 Gray 编码同步；`display_dark_frames` 检测接近全黑或相邻帧亮度骤降四倍的候选，不覆盖编码器之后的信号异常。
