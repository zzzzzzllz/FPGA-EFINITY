> 历史技术记录。仅说明记录时的版本；当前操作与状态以 [使用指南](../../../docs/for-reader/usage.md) 为准。文中旧路径用于溯源，不是当前运行入口。

# M04：灰度／Sobel 对比显示

状态：黑屏已修复，用户确认“两侧画面正常，能跟随物体移动”。修复版五分钟自动检查通过；用户随后要求“下一个任务”，M04阶段放行。

## 显示与数据

对比模式左侧是完整灰度视野，右侧是同一帧的 Sobel。两个窗口均为640×360，左上角分别为(0,180)、(640,180)，上下黑边各180行。灰度先按M02公式计算每个像素，再用`(Y00+Y01+Y10+Y11+2)>>2`四舍五入平均；边缘用2×2 OR。保留完整1280×720彩色、灰度和边缘模式。摄像头仍是全幅2560×1440约30fps，HDMI为720p60，Sobel继续`G>32`。

DDR每像素从`{E8,R8,G8,B8}`改为`{E1,frame_id[6:0],R8,G8,B8}`，不增加数据量。RGB保持原值，二值边缘按最高位恢复0/255。帧标记用于逐字检测混帧；7位标记在现有三个实时帧槽中足够区分相邻帧，不替代后续冻结／回放需要的完整帧描述符。

## 实现

- `compare_display.v`消费128位DDR字，每字四像素；以双像素流水计算灰度，保存一行水平和及两行缩小后的灰度／边缘。输出时先读同一缩小行的灰度，再读其边缘。
- `frame_buffer.v`改为直接输出原生128位字，用四项队列为异步FIFO读延迟预留空间；停止使用该实例原有逐像素转换器。工程中只有一个frame_buffer实例。
- DDR写端收到最后一个B响应后发布帧；读端收到最后一个R响应后才释放读银行。地址步进中的常量明确为32位，数值行为保持不变。
- 厂家FIFO的GrayDecode改为`always_comb`，使初始零地址也得到确定解码；组合逻辑公式不变。
- 原有两个视图位组合为四种模式：color=00、gray=01、edge=10、compare=11。模式仍在垂直消隐提交。`mixed_words`统计与该帧首字不一致或字内不一致的帧标记，`display_frames`统计完整送往HDMI FIFO的画面，两计数经格雷码跨域。

## 使用

```bat
load-edge.cmd
camera-control.cmd --edge --view compare
camera-control.cmd --edge --view color
camera-control.cmd --edge --view gray
camera-control.cmd --edge --view edge
camera-control.cmd --edge --samples 5
test-edge-m04.cmd
```

构建标识`0x60101004`，默认对比模式。加载脚本仍只下载SRAM，并应用RGB=389/256/427、Gamma=0、phase=0。原有调试会话保留白平衡修正不变。

## 黑屏原因与修复

M04初版的`stored_pixels`在帧缓存实例之后才通过带赋值的wire声明定义。Efinity报告该网线没有驱动，并将帧缓存入口的64位`fi_data`全部优化为零。板上因此能够完成DDR事务并输出HDMI时序，但实际图像为黑色。RTL仿真没有暴露这一综合结果，原有帧计数检查也未验证像素内容。

修复只改变连接写法：在帧缓存实例前声明`stored_pixels`，在Sobel输出处用显式`assign`打包。重新综合后64位像素总线保留，DDR写入／读回均有数据，显示端帧标记随采集更新。`tools/check-edge-build.ps1`已接入`build-edge.cmd`，旧故障报告会使检查失败，修复版通过。

新增诊断读数：`ddr_write_status`保存预期突发、完成突发、写响应与发布状态；`source_signature`保存每个显示帧的首像素及7位帧标记；`ddr_data`和`ddr_banks`记录DDR读写像素、缓冲区地址。它们用于本次定位，不改变显示算法。

## 修复版验证

- 顶层灰度／Sobel适配器四个完整720p帧仿真通过；原RGB和帧标记打包正确。见`logs/edge-m04-pixel-connection-sim.log`。
- Efinity综合、接口、布局布线、位流生成均通过；最小建立／保持余量为0.433／0.026ns。综合检查确认像素入口不再为常量零。
- SRAM下载后，十次视图切换的模式、白平衡、参数版本及异常计数检查通过，最终保持对比模式。
- 301次连续采样：305.406秒内采集和处理各增加9162帧（29.999fps），显示增加18325帧（60.002fps）；采集错误、MIPI异常、显示欠载、Sobel过载和混帧计数均无新增。共观察到126种首像素帧标记，各次均与最近完成的采集帧相符，排除了恒零帧和重复旧帧。
- 本次启动后累计欠载为8、混帧字为1330376；上述连续检查比较新增量，未将启动累计值记为零。
- 用户已确认两侧画面正常，移动物体时画面实时更新。用户随后要求“下一个任务”，已放行M04。

位流SHA-256：`b26a3a37963e5a1046d215dcda535a8171c415fbb619bc0b4782911af3f633c6`。完整修复版保存至`backups/m04-compare-black-screen-fixed/`，源码、位流、配置、工具和验证记录均纳入SHA-256清单。板上记录见`logs/edge-m04-repair-verification.json`和`logs/edge-m04-repair-health.log`。

## 历史验证与版本

原有四帧完整720p对比模块逐像素测试、延迟B响应的发布测试、三个完整720p的DDR读出／FIFO／CVO仿真通过，记录仍在`logs/edge-m04-compare-full.log`、`logs/edge-m04-publish.log`、`logs/edge-m04-pipeline.log`。本次连接修复未改变这些模块的算法或时序逻辑。

`backups/m04-compare-board-checked/`是黑屏故障版本，仅保留历史源码和当时记录；其中的自动计数通过不证明有效画面。M03已确认版本`backups/m03-sobel-t32-board-checked/`保持原样，位流SHA仍为`ba1be562e90760b14839fa66a49efe003457bf6dae19d2072e20a4d0d96b1aa8`。

M03噪点与残余断线继续留在M05/M06/M09，本次只修复M04黑屏。

