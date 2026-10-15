# 当前系统结构

四个coding目录是独立可构建的产品版本。它们共用硬件平台与主机工具，不在本轮合并RTL，避免改变已经验证的算法。

## 图像路径

SC431HAI通过I2C配置并输出MIPI RAW10。CSI接收与RAW转换在FPGA完成，颜色恢复后进入灰度/边缘处理、DDR存储和720p HDMI输出。直显版省去完整算法和帧管理；60帧版使用中心裁切及3:2缩放，仅保留基础灰度/Sobel。

完整边缘版中，edge_algorithm_pair选择Sobel或Canny。Canny包含高斯、梯度、四方向非极大值抑制、双阈值及八邻域滞后连接。frame_store系列模块协调RGB24原帧、算法结果、录放和参考帧；shape_recognizer在边缘结果上识别圆形/矩形；compare_display、threshold_osd和edge_ui负责显示及按键。

画质版在颜色恢复端采用raw_edgeaware_area，并在NMS分类之后做受覆盖与连接约束的局部冗余点清理。它保留完整功能，不代表传感器噪声和时间闪动已经全部解决。

## 控制路径

本版本control.cmd加载Efinity环境并执行control.py，经USB JTAG与匹配profile通信。分页状态由tools/paged_status.py读取，传感器操作由tools/sensor_control.py执行。构建ID不匹配、参数错误或传感器读回不符会报错。

load.cmd先用verify-project.py核对冻结位流及配置，再加载SRAM并应用颜色/视图设置；完整边缘版本单独恢复sensor.json。源码修改不影响已冻结位流的身份检查。

## 构建与文件职责

rtl和ip是逻辑与接口来源；工程XML列出设计文件，peri.xml和SDC保存外设/引脚及时序。tests保存可复现测试台和版本专用参考模型。release保留所选位流，config保留运行参数。build-project.ps1复制构建输入到tmp后调用Efinity，使综合和布局工作区不再污染工程目录。

历史算法规则和接口细节见stages目录；使用时以当前源码和对应版本的操作指南为准。
