# 13步循环演示修改依据

确认：KEY1从13回01；中值移到03；KEY2切中值开关，KEY3切灰度/灰度和Sobel/Sobel对比；删除性能页及C/P实时显示；红边明确为Canny。

外部参考：实际阅读了Microchip SmartHLS 2023.1 [Optimization Guide](https://microchiptech.github.io/fpga-hls-docs/2023.1/optimizationguide.html) 的Sobel代码与LineBuffer类实现（网页503—564行）。两行缓存加3×3窗口可以复用邻域，不需要额外整帧存储。读取到的是官方文档内的代码；没有下载或执行第三方程序。此前导航研究的LVGL wrap机制继续适用。

对照本地 median_pair.v、sobel_pair.v、edge_algorithm_pair.v 和 compare_display.v 后，选择复用中值的原始3×3窗口计算未滤波Sobel，只增加梯度/阈值流水线，不复制行缓存或DDR调度。原始灰度直接使用已保存的RGBY中的Y，避免重复计算灰度。保持既有Sobel的零边框、|Gx|+|Gy|和严格大于阈值规则。

两路边缘来自同一帧、同一阈值。原始边缘放入去噪载荷原本空闲的蓝字节，处理后的边缘沿用bit31。显示两侧均按2×2 OR缩小，保持细线；灰度两侧保持原2×2均值缩小。中值关闭时两路像素应一致，开启时使用独立软件参考逐像素核对。

验证范围：按键循环、两种中值对比、左右像素及菜单提示的针对性仿真已通过。用户要求减少验证后，停止运行全量回归，不追加扩展仿真；保留生成可加载位流所需的完整编译。实物画面交给用户验收。
