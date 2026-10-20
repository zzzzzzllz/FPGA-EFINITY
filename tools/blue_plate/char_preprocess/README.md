# 字符前处理RTL

`rtl/char_preprocess.v`接收一张原始二值字符ROI，输出一次归一化后的32×32像素和冻结模型的320个整数特征。共享一套计算逻辑，支持1..320宽、1..96高；输入容量覆盖整牌320×96中的任意字符子区域。

协议：

- `start_valid/start_ready`接收宽高。输入和所有输出均在时钟上升沿valid且ready时传输。
- `pixel_data`是白色前景1，行优先；`pixel_last`必须恰好标记宽×高的最后像素。
- `norm_valid/norm_ready`输出1024个二值像素，`norm_index`为行优先0..1023。不观察该输出时将`norm_ready`置1。
- `feature_valid/feature_ready`输出320个6位特征：256个2×2计数乘8、32列计数、32行计数；`feature_index`为0..319。
- `done_valid/done_ready`保持完成状态。`error`：0成功、1尺寸无效、2原始前景不足4、3像素last错误、4异常状态。错误不输出伪特征。
- 高有效同步`rst`取消任务，复位期间所有valid/ready被屏蔽。停止发送但不提供last属于未完成事务，上游需要超时取消。

归一化精确使用`char_model/model.py`的默认square模式，不支持legacy模式，不改变阈值或特征。原始前景≥4但缩放后全空仍是正常任务。分类器在首个有效特征到达时启动，见核级测试连接；不要在可能失败的ROI输入开始时先启动分类器并让其无限等特征。

根目录运行：

```powershell
D:/Python/python.exe -B tools/blue_plate/char_preprocess/tests/prepare.py
D:/Python/python.exe -B tools/blue_plate/char_preprocess/tests/run.py
D:/Python/python.exe -B tools/blue_plate/char_preprocess/tests/run.py --stalls
D:/Python/python.exe -B tools/blue_plate/char_preprocess/tests/run.py --e2e
D:/Python/python.exe -B tools/blue_plate/char_preprocess/tests/run.py --e2e --stalls
D:/Python/python.exe -B tools/blue_plate/char_preprocess/tests/run.py --e2e --stalls --empty
./tools/blue_plate/char_preprocess/build.ps1
D:/Python/python.exe -B tools/blue_plate/char_preprocess/tests/verify_synthesis.py
```

`prepare.py`读取冻结开发ROI并生成参考向量，不训练或读取heldout。运行中的测试使用已冻结向量，不要同时重新运行prepare。附加`--empty`使用独立编号310..312，不覆盖原310例。测试编译前保存RTL/TB快照，输出位于`tmp/blue-plate-char-preprocess/`。

综合准备只依赖Python标准库，Efinity脚本使用其自带Python；需要NumPy/OpenCV的参考和仿真准备明确使用`D:/Python/python.exe`。没有安装新依赖。构建保留XML工具前后版本，分别记录哈希并检查语义一致，不将格式回写当作输入未变。

实测map为671 LUT、265 FF、189 ADD、5 RAM10、0 DSP。实际周期和证据见[验证报告](../../../docs/validation/blue-plate/char-preprocess/report.md)。本核未接视频、DDR或板卡，map资源不等于PNR时序通过。
