# 已读取的依据

- 根 README、G1 七位契约、frame_mailbox.v、threshold_osd.v、两个 OSD 测试已读。
- frame_mailbox 使用 held 数据配合双级 request/ack 同步；dst_data 在握手到达时立即更新，不能直接作正在扫描的字符状态。
- 结果来源时间必须属于与 now_ms 相同的单调毫秒时基，不能用收到结果时刻作为新鲜度起点。
- 原 CLASSES 是 65 类唯一映射源；字库生成读取它，不另写省份顺序。
- 已下载并逐段阅读 PULP common_cells v1.37.0 `src/cdc_2phase.sv`，明确 held 数据、req/ack 两级同步、共同异步复位及 bundled-data max_delay 要求。master 分支两个旧文件路径404后，改用固定版本取得源码。来源 https://github.com/pulp-platform/common_cells/blob/v1.37.0/src/cdc_2phase.sv 。参考代码只留在临时研究目录，不直接编入工程；新模块沿用项目 mailbox 的两相机制并增加显式目的域反压。
- 已下载 Google Fonts NotoSansSC[wght].ttf（17,772,300字节）与 OFL.txt 并读取完整许可：OFL-1.1 允许嵌入/修改/再分发，需保留版权和许可，Reserved Font Name 为 Source。生成位图子集命名 Blue Plate Bitmap Subset，随 ROM 附 FONT-OFL.txt；不用保留名字命名衍生字体。
- 字体 cmap 已逐字验证 CLASSES+未识别+空格共69字存在，32×32单色字模，原字体/ROM/类表源文件 SHA256 保存在 assets.json。font-atlas.png 为完整字表预览。
