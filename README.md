# Ti60F225 摄像头与边缘检测

SC431HAI摄像头输入，经Ti60F225处理后输出720p HDMI。项目保留四个独立版本；源码、位流、配置、构建、加载和测试入口都在各自的 `coding/` 子目录。

| 版本 | 作用 | 状态 |
|---|---|---|
| [camera-30fps](docs/for-reader/versions/camera-30fps.md) | 全视野30帧彩色直显与白平衡 | 已有板测及人工确认 |
| [edge-30fps](docs/for-reader/versions/edge-30fps.md) | 原M10/O1完整边缘系统 | 10月15日用户实测反馈多处问题、无法正常使用，待定位 |
| [edge-quality-30fps](docs/for-reader/versions/edge-quality-30fps.md) | 完整边缘系统加EA前端和自然边界保护 | 最近确认的30帧画质版；边缘闪动仍存在 |
| [edge-60fps](docs/for-reader/versions/edge-60fps.md) | 中心裁切60帧彩色／灰度／Sobel，10ms曝光 | 保留65版；偶发黑屏未解决，无完整Canny |

首次使用先看 [操作指南](docs/for-reader/usage.md)。当前正在逐版上板复核，已切换到 [画质版导览](docs/for-reader/versions/edge-quality-30fps-demo.md) 继续检查。

## 目录

```text
coding/              四套独立工程，每套有build/load/control/test入口
docs/                所有项目说明、技术资料、验收证据和许可证
  for-reader/        操作指南、版本比较、测试图
  design/            当前结构及历史实现说明
  reference/         硬件手册、厂家说明、第三方来源
  validation/        原始验收与本次迁移验证
tools/               共享控制模块、构建检查、仿真器、结构图
tmp/                 构建和测试输出，可清空
```

[文档索引](docs/README.md) · [项目结构图](tools/archify/project-structure-20261015/target.html) · [四版本说明](docs/for-reader/project-structure-audit.md)

## 构建、测试与加载

本机工具：Efinity 2026.1位于 `D:\Efinity`；测试Python位于 `D:\Python`，需要NumPy；Icarus Verilog位于 `tools/iverilog-12/app/bin`。

以完整画质版为例，在项目根运行：

```powershell
.\coding\edge-quality-30fps\test.cmd
.\coding\edge-quality-30fps\build.cmd
.\coding\edge-quality-30fps\load.cmd
.\coding\edge-quality-30fps\control.cmd --samples 5
```

`load.cmd`加载该目录 `release/` 内冻结的已选版本，并恢复配套颜色和传感器参数，只写SRAM。加载前校验位流、profile和配置哈希。`build.cmd`从当前源码在 `tmp/build/<版本>/` 中完整构建，结果不会覆盖已确认的release位流。构建新版本后先验证，再决定是否替换release；不要把“构建成功”当作已上板确认。

硬件已知问题、各版本专用命令及完整测试参数见操作指南。修改Efinity安装位置时设置 `EFINITY_HOME`；测试Python路径统一写在四个 `test.cmd` 中。

## 本地Git

本地 `main` 分支跟踪源码、配置、测试、文档和工具脚本，未设置远程仓库。迁移前四版本快照已有基线提交。

位流、Icarus安装包、缓存和生成数据不进入Git。`release/manifest.json`记录位流与源码哈希；复制项目到其他电脑时，除Git内容外还需带上四个release位流和仿真工具。Git不会恢复未纳入跟踪的二进制文件。

```powershell
git status --short
git log --oneline -5
```

第三方版权见 [来源与许可证](docs/reference/third-party.md)。

本轮整理已完成四套完整构建、离线回归及清理后的入口校验，结果见 [整理与验证记录](docs/validation/reorganization/progress.md)。
