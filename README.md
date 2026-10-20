# Ti60F225 摄像头与边缘检测

主线采用第二版 `edge-quality-30fps`：SC431HAI摄像头输入，经Ti60F225处理后输出720p HDMI，包含灰度、Sobel/Canny、中值、对比、叠加、12页循环演示（01—08、10—13）、帧管理和形状识别。后续开发以这版为基础；选为主线不代表所有功能已经验收。

加载后从第01步彩色实时画面开始；KEY1短按下一步、长按上一步，首尾循环，跳过已删除的09，13之后回01。KEY2/KEY3按屏幕提示操作；13页为三个保存画面加一个实时画面的四格对比，KEY2逐次保存并循环替换，KEY3清空。默认阈值56，约20ms曝光；第07步恢复前面对应算法的参数，第08步保留本页阈值，其他页面进入时恢复预设。第03步默认开启中值，可按K2切换；第04—08步固定开启中值。第06步使用一次高斯平滑后的Canny，第08步识别改用3×3均值平滑；第07步KEY2选Canny红边、KEY3选Sobel红边，分别沿用第06步的Canny参数和第04/05步的Sobel阈值。第08步进入即开启识别，KEY2降低阈值4、KEY3提高4，长按连续调整。新增平滑已通过合成噪声对比，实拍减抖效果待验收。

任务8实机反馈：按键调阈值正常；底图稳定，红色轮廓仍明显闪烁，当前平滑尚未解决这一问题。

[任务8独立调参说明](docs/for-reader/task8-shapes.md) · [第二版串行演示与验收步骤](docs/for-reader/versions/edge-quality-30fps-serial-demo.md) · [使用指南](docs/for-reader/usage.md) · [文档索引](docs/README.md)

参赛选题为赛题四《基于 FPGA 的实时图像边缘检测系统》，见[赛题要求逐条解读与验收清单](docs/for-reader/contest-requirements.md)。

## 本地分支

| 分支 | coding中保留的工程 | 用途 |
|---|---|---|
| `main` | `edge-quality-30fps` | 第二版，后续开发主线 |
| `archive/edge-30fps` | `edge-30fps` | 第一版；用户实测无法正常使用，留作历史 |
| `archive/edge-60fps` | `edge-60fps` | 第三版；用户实测不接受，留作历史 |
| `archive/camera-30fps` | `camera-30fps` | 原彩色直显版，留作参考 |

每个分支的 `coding/` 只保留对应工程。切换分支会一并切换源码、配置、入口和冻结位流。既有提交历史保留，远程仓库为 [FPGA-EFINITY](https://github.com/zzzzzzllz/FPGA-EFINITY)，对应本地 `origin`。

```powershell
git status --short
git switch main
git log --oneline -- coding
```

切换前先提交当前修改。其他分支的操作及日常提交方式见 [本地Git使用说明](docs/for-reader/git.md)。

## 目录

```text
coding/edge-quality-30fps/  main中的唯一工程：源码、配置、测试和release位流
docs/                      操作说明、技术资料、验证记录和许可证
tools/                     构建与控制依赖、仿真器和Archify导览
tmp/                       构建和测试输出，不进入Git
```

Git以 `coding/` 为核心，同时跟踪构建所需的共享脚本和配套文档，仓库位于项目根目录。`tools/iverilog-12/`安装包、临时输出和缓存不进入Git。历史文档、结构图中的四目录并存状态属于整理前记录，当前目录和分支以本README为准。

## 构建、测试与加载

本机工具：Efinity 2026.1位于 `D:\Efinity`，Python位于 `D:\Python`，Icarus Verilog位于 `tools/iverilog-12/app/bin`。

在项目根运行：

```powershell
.\coding\edge-quality-30fps\test.cmd
.\coding\edge-quality-30fps\build.cmd
.\coding\edge-quality-30fps\load.cmd
.\coding\edge-quality-30fps\control.cmd --samples 5
```

`load.cmd`校验并加载本分支 `release/ti60f225_oob.bit`，恢复配套参数，只写FPGA SRAM。`build.cmd`输出到 `tmp/build/<版本>/`，不会覆盖release。构建新版本后先验证，再更新冻结位流及清单。切换Git分支不会自动改变板上程序，需要运行对应load入口。

第三方版权见 [来源与许可证](docs/reference/third-party.md)。原四套工程完整构建和离线回归记录见 [整理与验证记录](docs/validation/reorganization/progress.md)。
