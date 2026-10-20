# 主线与归档版本操作指南

在项目根打开PowerShell。日常使用 `main` 中的第二版。其他版本分别保存在 `archive/camera-30fps`、`archive/edge-30fps`、`archive/edge-60fps`，需先切换对应分支才能执行下面的入口，具体见 [Git使用说明](git.md)。不要混用另一版的位流、profile或控制脚本。

## 选择与加载

| 目的 | 加载命令 |
|---|---|
| 查看完整视野彩色原图 | `.\coding\camera-30fps\load.cmd` |
| 使用原M10/O1算法作对照 | `.\coding\edge-30fps\load.cmd` |
| 使用最近确认的完整Canny画质版 | `.\coding\edge-quality-30fps\load.cmd` |
| 使用裁切视野60帧10ms试验版 | `.\coding\edge-60fps\load.cmd` |

连接电源、USB下载线、SC431HAI与HDMI后加载；只写FPGA SRAM，断电后需要重载。60帧版若热加载后摄像头不计帧，完整断电再加载；这不代表偶发黑屏已经修复。

四套load入口会先检查位流、profile和配置哈希，再加载并应用本版本默认参数。默认颜色参数来源于旧白卡校准；换光源后可用控制命令重新校准。

## 完整边缘版本

以下以画质版为例，原edge-30fps有相同主要控制接口。

```powershell
.\coding\edge-quality-30fps\control.cmd --samples 5
.\coding\edge-quality-30fps\control.cmd --view color
.\coding\edge-quality-30fps\control.cmd --view compare
.\coding\edge-quality-30fps\control.cmd --algorithm canny --threshold 24 --low-ratio 1/2
.\coding\edge-quality-30fps\control.cmd --median on
.\coding\edge-quality-30fps\control.cmd --recognition on
.\coding\edge-quality-30fps\control.cmd --frame freeze
.\coding\edge-quality-30fps\control.cmd --frame live
```

视图：color、gray、edge、compare、denoise、overlay、reference。算法：sobel或canny。帧操作：live、freeze、step、record、play、pause、next、reference、clear-reference。record会替换先前32帧录制内容。

第二版还可用 `--frame demo-next`、`demo-prev`、`demo-home` 调试串行路线，分别等同下一步、上一步和回第01步，保留录像和参考。单独使用 `--view` 等参数属于手动调试，不改变步骤编号；演示前执行 `--frame demo-home` 恢复路线预设。屏幕显示WAIT时等待完成再按键；忙碌期间的按键不会排队。

形状识别包含圆形/矩形和最多4个目标框；进入第08步自动开启，运行 `coding/edge-quality-30fps/recognition.cmd` 可直接进入该页。KEY2/KEY3以4为步长调低/调高阈值，支持长按，见[任务8调参说明](task8-shapes.md)。识别开启后不能保证30fps。中值开关也不是功能增删。画质版加载后进入第01步彩色实时，中值关、识别关；[12页循环演示](versions/edge-quality-30fps-serial-demo.md)由KEY1导航，第07步恢复对应算法参数，第08步保留本页阈值，其他页恢复预设；原edge-30fps加载为原默认Sobel阈值32、中值开、识别关。

曝光和增益操作须与算法/显示操作分开执行：

```powershell
.\coding\edge-quality-30fps\control.cmd --sensor-status
.\coding\edge-quality-30fps\control.cmd --exposure-ms 20
.\coding\edge-quality-30fps\control.cmd --sensor-gain 3
.\coding\edge-quality-30fps\control.cmd --sensor-restore .\coding\edge-quality-30fps\config\sensor.json
```

每次传感器修改前的恢复参数保存在对应版本 `config/sensor-history/`。这是可能需要恢复的配置，不能当临时测试输出删除。

## 直显与60帧

直显版用 `control.cmd --set 389 256 427 0 0` 设置RGB增益、Gamma和Bayer相位。60帧版用 `--set 704 512 758 0 0`，并支持 `--view color|gray|edge`。60帧65版曝光在传感器初始化ROM中固定为1381半行，控制入口会检查曝光/增益读回为0x0565803d。

## 构建与离线验证

各版本均有 `build.cmd`、`test.cmd`；构建工作区位于 `tmp/build/<版本>/`，测试输出位于 `tmp/tests/<版本>/`。已确认release保持独立，构建不会覆盖它。

- camera-30fps：test.cmd验证完整2560×1440、四种Bayer排列、间隙与帧边界。
- edge-30fps和edge-quality-30fps：无参数运行small回归；`test.cmd full`运行720p帧存储和显示；`test.cmd shape`运行识别回归；画质版另有`test.cmd quality_full`。耗时较长的组可在同一源码状态下用`--resume`继续已有结果；源码或测试改变后应从头运行。
- edge-60fps：test.cmd运行小帧四Bayer/连续与间隙测试；`--detail`测试细节；`--full`测试完整1080p输入；`--chain`测试完整前端与灰度/Sobel接口；`--exposure`测试10ms寄存器。65版不提供66版的display-watch测试。

`D:\Python\python.exe -B tools\verify-project.py coding\edge-quality-30fps`校验当前冻结源码、运行配置、工程输入和Python语法。修改算法后需要重新验收并更新release清单，不能手动改哈希来掩盖不匹配。
