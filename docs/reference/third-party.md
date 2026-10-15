# 第三方来源与许可证

本工程包含厂家及第三方代码，不统一改写其版权或声明为自有开源作品。原源码版权头保持完整。

- 画质版精确中值选择网络参考OpenCV 4.13.0的median_blur.simd.hpp。原文件、许可证和来源记录保存在 `third-party/opencv/`。median_pair.v内Intel、Willow Garage、Itseez、AMD等原有版权条款保留。
- 60帧双线性重建研究参考Antmicro和Colour Science公开实现，资料、提交信息与许可证在 `third-party/demosaic/`。未引入Migen运行框架；未采用的Malvar和其他ISP完整源码库不保留。
- 厂家RTL中的Efinix、Intel、OpenCores等版权声明随源文件保留；参考手册在hardware和vendor目录。
- Icarus Verilog使用现有独立工具分发，命令手册和其中的版权说明集中在 `iverilog/`；其二进制不进入项目Git。

目录方案借鉴 [OpenTitan的源码/工具/文档划分](https://opentitan.org/book/doc/contributing/directory_structure.html)，Git忽略规则依据 [Git官方说明](https://git-scm.com/docs/gitignore)。未引入新的构建系统或运行库。
