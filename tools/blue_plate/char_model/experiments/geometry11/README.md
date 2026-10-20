# geometry signed11 实验配置

使用同一 `rtl/char_linear.v` 内核，`geometry11_char_linear.v` 只实例化一次并设置11位、实验ROM和原geometry普通门限。默认内核及candidate不被替换。

源NPZ SHA256：`b21a547399f17ecb50264d489eec4e4563c2269babab7149dc5447f7a12f5391`。`w1-s11.bin` 每行恰11位补码、class-major顺序；`b1.mem` 为32位补码。路径相对仿真/综合工作目录，集成前须复制ROM或明确覆盖参数。不能将11位截成10位。

在项目根运行：

```powershell
D:/Python/python.exe -X utf8 tools/blue_plate/char_model/experiments/geometry11/run.py export
D:/Python/python.exe -X utf8 tools/blue_plate/char_model/tests/run_sim.py
D:/Python/python.exe -X utf8 tools/blue_plate/char_model/experiments/geometry11/run.py sim
D:/Python/python.exe -X utf8 tools/blue_plate/char_model/experiments/geometry11/run.py boundary10
D:/Python/python.exe -X utf8 tools/blue_plate/char_model/experiments/geometry11/run.py boundary
D:/Python/python.exe -X utf8 tools/blue_plate/char_model/experiments/geometry11/run.py guards
D:/Python/python.exe -X utf8 tools/blue_plate/char_model/experiments/geometry11/run.py prepare
```

进入 `tmp/blue-plate-char-model/geometry11-hardware/synthesis` 执行：

```powershell
& D:/Efinity/bin/efx_run.bat geometry11_char_linear.xml --flow map --output_dir out
```

回项目根运行以下命令检查独立映射网表并收集证据：

```powershell
D:/Python/python.exe -X utf8 tools/blue_plate/char_model/experiments/geometry11/run.py mapped
D:/Python/python.exe -X utf8 tools/blue_plate/char_model/experiments/geometry11/collect.py
```

映射仿真采用已被独立复核的Icarus厂商LUT初值适配副本，安装模型和网表保持原样；适配哈希会记录。门级仿真时限为1800秒，RTL为300秒；首次门级运行触及300秒脚本时限后调高，仿真内的41796拍断言保持不变。`collect.py` 也读取主控独立审核记录 `tmp/blue-plate-review/geometry11/review-result.json`，检查其源文件哈希后归档。

boundary10/boundary只生成临时合成ROM来测试位宽边界和最坏累加，不是另一份训练模型。`sim`使用全部259个冻结真实ROI与极值、随机、越过signed10的实际权重探针及同分注入。尚未接摄像头top，不等于G1通过。
