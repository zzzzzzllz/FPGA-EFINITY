# 独立七位确认与号码栏

`plate_display.v` 组合来源结果确认、整包CDC、帧边界状态提交和32×32中文号码栏。未接共享top/DDR，没有操作硬件。

- 输入715位结果包的位段由 `generate_assets.py` 生成到 `plate_defs.vh` 和 `assets.json`；ID0位于七字ID字段的低7位。
- 输入采用 `result_valid/result_ready`；反压时上游保持整包。当前epoch/generation和毫秒计数在src_clk域稳定。
- 结果时间戳须在来源采集帧开始时锁存，不能用识别完成/显示接收时间。`now_ms`同域单调每毫秒加一。
- 同目标连续三个不同且有序来源帧的完整号码一致才确认。重复、乱序忽略；拒识、号码变化、目标跳变、配置变化及源年龄≥500ms清空/重建。
- `frame_start`只在像素域消隐时发出；active包仅在该边界变化。配置清除具有粘滞优先级，不被成功包覆盖。
- `display_accept`正常接1；用于对显示CDC入口施加反压。配置另走独立通道。
- 默认号码栏位于(16,656)，256×48；RGB/DE/HS/VS延迟一个pixel_clk。pixel输入x/y为当前有效像素坐标。无结果时显示“未识别”。

接口/复位/时间与同目标策略详见 [交接文档](../../../docs/validation/blue-plate/plate-display/handoff.md)，集成必须另落实 [CDC约束](../../../docs/validation/blue-plate/plate-display/cdc-constraints.md)。共同异步复位，各域同步释放，不支持任意单域复位。

从项目根运行：

```powershell
D:/Python/python.exe -X utf8 tools/blue_plate/plate_display/run_sim.py
D:/Python/python.exe tools/blue_plate/plate_display/prepare_synthesis.py
```

然后分别进入 `tmp/blue-plate-plate-display/synthesis/plate_osd` 和 `plate_display` 运行：

```powershell
& D:/Efinity/bin/efx_run.bat plate_osd.xml --flow map --output_dir out
# 完整模块目录使用 plate_display.xml
```

完成两次map后回到项目根运行 `D:/Python/python.exe tools/blue_plate/plate_display/freeze_evidence.py`。测试只证明合成输入下的状态与显示，不证明真实识别。

`plate_font.mem` 是从 Noto Sans SC 生成的 Blue Plate Bitmap Subset，遵循附带的 [SIL OFL-1.1](FONT-OFL.txt)，版权为 Adobe 2014–2021。字形衍生物不使用保留字体名 Source。CLASSES直接从冻结 `char_model/model.py` AST读取；省份、英数、未识别映射不手工维护两份。

可用 `generate_assets.py` 重建字库；它读取 `tmp/blue-plate-plate-display/research/NotoSansSC.ttf` 和 `OFL.txt`。上游来源及原字体SHA256见 `assets.json`，完整下载字体仅保存在研究目录，交付ROM及许可。重建后必须重跑仿真/综合并更新证据。
