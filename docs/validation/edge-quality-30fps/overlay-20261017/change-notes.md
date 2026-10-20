# 第07页双算法红边

目标：KEY2选择Canny红边，KEY3选择Sobel红边。两者都用前面的实际处理链，中值保持开启；Sobel恢复04/05最后离开时的阈值，Canny恢复06离开时的阈值和低阈值比例。

参考实际阅读的[OpenCV Canny演示源码](https://raw.githubusercontent.com/opencv/opencv/4.x/samples/cpp/tutorial_code/ImgTrans/CannyDetector_Demo.cpp)：25—42行用当前阈值执行去噪和Canny，并用检测输出作为彩色图像的掩码。该例不是红边叠加，也不实现跨页面参数保存；这里只借鉴检测结果与显示复用的机制，没有复制代码。本工程已有对应流水线和红边渲染，所需改动是UI选择算法、保存两组参数并通过现有帧提交接口恢复。

不新增算法支路。只运行现有UI短仿真，覆盖参数继承、来回切换及返回07，再做必要的FPGA编译和加载。实物视觉效果由用户验收。
