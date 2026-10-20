# 独立单 bit 字库候选

`plate_osd_compact.v` 保持原 `plate_osd.v` 的接口与一拍输出，将只读字库分为64个字形的65536×1区和4个字形的4096×1区，空格输出零。原字体与原模块不改；生成的bit文件逐行从原ROM提取，column0对应原bit31。

从仓库根目录复现：

```powershell
& D:/Python/python.exe -X utf8 -B tools/blue_plate/whole_plate_budget/font_compact/run.py prepare
& D:/Python/python.exe -X utf8 -B tools/blue_plate/whole_plate_budget/font_compact/run.py rtl
powershell -NoProfile -File tools/blue_plate/whole_plate_budget/font_compact/build.ps1
& D:/Python/python.exe -X utf8 -B tools/blue_plate/whole_plate_budget/font_compact/run.py mapped
& D:/Python/python.exe -X utf8 -B tools/blue_plate/whole_plate_budget/font_compact/finalize.py
```

prepare可重复运行，只生成隔离目录的输入/项目；有意修改源码后应重新运行prepare与验证。build只执行map。Efinity在子PowerShell中设置PYTHONHOME，避免影响后续通用Python。

输出位于 `tmp/blue-plate-whole-plate-budget/font-compact/`。实际结果、mapped仿真的本地LUT模型条件、剩余整机缺口见 `docs/validation/blue-plate/whole-plate-budget/font-compact-implementation.md`。`delivery-freeze.json`冻结输入、源码、测试、网表、报告和原始依赖，不代表整机集成完成。
