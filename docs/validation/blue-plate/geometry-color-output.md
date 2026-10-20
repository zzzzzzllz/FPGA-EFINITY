# RGB 几何输出接口交付

已将现有 `perspective_fetch` 的彩色结果接通到 `perspective_roi` 和 `perspective_quad`，增加可背压的 RGB 输出。没有更换插值算法、增加采样副本或新增缓存；默认关闭彩色输出，保留原灰度/Otsu行为。当前仅为独立接口验证，不涉及共享顶层、模型算子、确认策略、TTL或板卡烧录。

## 最小修改与采样依据

两个上层模块新增 `COLOR_OUTPUT` 参数，默认0；需要彩色消费时设为1。底层 `perspective_matrix`、`perspective_coords`、`perspective_fetch` 与软件 `geometry_sampler.py` 均未修改。

实施前核对已有 Q16四角→Q32矩阵→Q5坐标的整数合同，并重新阅读 [OpenCV 4.12.0 imgwarp.cpp](https://github.com/opencv/opencv/blob/4.12.0/modules/imgproc/src/imgwarp.cpp) 的 `interpolateLinear` 和 `initInterTab2D`：双线性权重由两个一维权重的乘积组成。本次保留项目已冻结的坐标最近偶数舍入、四邻居权重和越界补零，以及像素累加加512后右移10位；没有改为不同的OpenCV浮点矩阵求解或新的采样算法。外部源码通过网页阅读，未复制进RTL。

| 接口 | 合同 |
|---|---|
| `color_valid/color_ready` | 上升沿同时为1接收一个像素；背压时valid、数据、地址和last保持，rst/abort可撤销 |
| `color_rgb[23:0]` | `[23:16]=R`、`[15:8]=G`、`[7:0]=B`；软件冻结数组为BGR，消费者写BGR字节序时依次取低、中、高字节 |
| `color_address[13:0]` | 224×64行优先地址，成功任务恰好0…14335 |
| `color_last` | 只随地址14335的像素握手一次，背压期间允许保持1 |
| 原 `gray_write/address/data` | 彩色启用时，gray_write与彩色握手严格同拍；灰度数值仍为`(77R+150G+29B)>>8` |

新增逻辑为同步消费：fetch的ready是Otsu ready与彩色ready的与；Otsu valid由彩色ready门控；彩色valid由Otsu ready门控。Otsu在等待像素时ready不依赖输入valid，因此不存在这两端相互等待的环。复用fetch已有输出寄存器保持像素，不增加分支FIFO或重放机制。

`COLOR_OUTPUT=0`时彩色valid固定0，color_ready不参与原路径。旧命名端口调用者可不消费新输出；使用`.*`的三个既有测试台显式接空输出并把ready接1，避免隐式端口名缺失。新测试同时检查关闭模式。

## 来源、取消与结果

帧身份仍由调用者及 `frame_reader` 持有，包含slot、frame_id、epoch、generation、source_time_ms。采样前先hold完成帧，两个候选若复用来源也必须持有同一身份。RGB接口不另造来源标签或任务队列；消费者须把整个ROI归属当前held身份。

`frame_reader.abort_valid`继续接几何abort。取消会丢弃尚未握手的彩色像素；已接收的部分ROI必须由消费者失效，不能送入模型。局部abort不代表DDR排空，仍需reader自然排空或recover完成再release。错误恢复和下一任务均验证没有残留像素。

保留Otsu只是为了维持旧入口契约，不把Otsu阈值新增为LPR接受条件。`color_last`证明像素流结束，不代表OCR成功；调用者还须检查几何/reader状态。原Otsu状态3表示单灰度档，不能误称坐标或总线故障，也不能用灰度复制三通道代替这里的RGB。

## 实际验证

证据在 `tmp/blue-plate-geometry/color-output/`。

- 按源SHA256、ROI序号排序预选4个已有development ROI：sample125/88/423/100。原图SHA、冻结BGR像素SHA逐一匹配；从原图重建720p、执行未改Q32/Q5软件采样，再与已冻结缓存逐字节比较。没有读取84校准或112 heldout。
- RTL从四角开始，经过实际矩阵/坐标/采样链及真实frame_reader，输出4×14336＝57344个RGB像素全部匹配冻结BGR交换后的参考；每个fixture含R≠B像素，可检测通道交换。地址、last、每任务计数、原灰度写入和Otsu阈值同时匹配。
- 彩色启用时每像素强制4拍背压，共229376拍有效背压检查；数据稳定、灰度与彩色同拍接收。关闭彩色时同4个ROI的57344灰度像素及阈值一致。背压拍数不是额外服务时间：本流水线与下一坐标计算存在重叠。
- 彩色生命周期20任务、20次hold/release通过，覆盖坏四角、退化/溢出、求解/坐标阶段取消、错误keep、RRESP错误、在途总线取消，以及首个和最后一个RGB像素背压期间取消。取消后重跑正常任务；总线实际排空后才允许释放。
- 生命周期测试在hold后改变外部job frame_id/source_time输入，所有输出仍核对已锁定身份；数据握手时检查held与非abort状态。旧quad生命周期16任务、旧ROI生命周期19任务保持通过。

复现命令：

```powershell
D:\Python\python.exe -X utf8 tools/blue_plate/geometry/tests/run_color_sim.py
D:\Python\python.exe -X utf8 tools/blue_plate/geometry/tests/run_lifecycle_sim.py
D:\Python\python.exe -X utf8 tools/blue_plate/geometry/tests/run_lifecycle_sim.py --roi
D:\Python\python.exe tools/blue_plate/geometry/tests/prepare_synthesis.py --color-output
```

`report.json`保存测试输入和源码哈希，`commands.json`保存实际编译/仿真命令及输出。原源码保存在`before/`，同一dev125输入还用于原版RTL对照；未更改冻结模型或数据。

## 独立综合增量

使用Efinity 2026.1、Ti60F225、相同100 MHz约束与map参数，分别重新综合修改前源码和启用彩色输出的源码。独立map均通过：

| 项目 | 修改前 | 彩色启用 | 增量 |
|---|---:|---:|---:|
| LUT4 | 9495 | 9687 | +192 |
| FF | 4730 | 4730 | 0 |
| ADD | 4232 | 4300 | +68 |
| RAM10 | 2 | 2 | 0 |
| DSP48 | 1 | 1 | 0 |

详见`resource-comparison.json`及两份map报告。没有增加状态寄存器、RAM或DSP；逻辑映射增量以实际综合为准，不能按“仅接线”宣称零资源。未做PNR，100 MHz仍是约束而非已关闭时序；也未计未来RGB缓存或缩放消费者。直接调用map可执行文件曾因缺运行环境崩溃，改用安装自带`efx_run.bat --flow map`后两版均成功，不涉及RTL规避修改。

## 下一项整链接入缺口

RGB数据现在已可取用，下一项是把它接入**同来源的模型输入准备**：将224×64 RGB按冻结通道顺序转换为BGR，完成既有软件合同中的Q8 24×94输入、颜色96×96输入及HS计数，并对齐量化模型输入布局。消费者需要接入ready背压、计数/last、部分ROI取消失效；若落DDR，还需冻结缓存地址、帧所有权与采集/HDMI仲裁。这些消费者和模型算子本轮未实现。

首轮按用户已确认的受控、清晰完整无遮挡单蓝牌推进，不要求先修完所有遮挡反例。真实彩色视频连续、真实七位号码、来源与过期清除仍须整链实拍验证；确认次数及TTL等实际服务时间测定后冻结。
