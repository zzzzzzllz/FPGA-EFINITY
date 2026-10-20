# 字符分类：实施依据

2026-10-18。范围限于已切好的白字暗底字符，不修改定位、切分或整机 RTL。

实际读取了 [EasyPR](https://github.com/liuruoze/EasyPR) 的 `src/core/feature.cpp`（`charFeatures`、`charFeatures2`、`getGrayPlusProject`）、`src/core/core_func.cpp`（`GetCenterRect`、`CutTheRect`）、`src/core/chars_segment.cpp`（`preprocessChar`）、`src/core/chars_identify.cpp`（位置类别约束），以及 `src/train/ann_train.cpp`、`annCh_train.cpp`。本地材料分别在 `tmp/plate-research-20261018/easypr-*.cpp` 和 `tmp/blue-plate-g1/easypr/src/train/`。已联网核对原仓库和发布记录，未执行外部脚本。

二值 ANN 使用缩略像素和行列投影；灰度中文 ANN 使用均值中心化的像素及二值投影。训练器包含平移、旋转增广，且二值训练器的 `test()` 会回测训练目录，不能照搬其数字作为独立测试结果。仓库 README 明确源代码与训练数据采用 Apache-2.0；许可证本地为 `tmp/blue-plate-g1/easypr/LICENSE`。

已有 `diagnose_characters.py` 基本复现二值特征。需要核对一处奇偶尺寸细节：C++ 方形填充的偏移是 `m/2-w/2`（整数各自截断），Python 是 `(m-w)//2`，在 m 偶、w 奇时可相差一个像素。两者都随后裁前景再居中；该差异还可能通过缩放插值影响边缘。不能声称当前 Python 与 EasyPR 特征逐位一致。它也没有调用灰度中文 `getGrayPlusProject`。本任务重训统一的整数前处理模型，不直接把官方浮点 XML 当成可部署权重。

选择比较：同一内容去重数据、同一训练/验证/测试分组上的 12 个 medoid 模板（16×32 XOR、32×32 网格）、320 维线性 SVM、320→64/128→65 ReLU MLP。网格采用 2×2 计数，附加行列计数；运行时只需整数加法、乘加、移位、比较，不依赖主机。OpenCV、NumPy 和 scikit-learn 均已安装，不新增依赖；scikit-learn 只负责离线训练。

32×32 方形画布可保留汉字横向笔画；是否改善由相同数据的对照决定。线性模型先检验能否省掉隐藏层，再考虑小 MLP。不引入 CNN。先用验证集选模型及分数/类别分差阈值，最后只读测试统计。最终验收 CCPD 图没有进入训练或阈值拟合。

数据审计保存逐文件来源、文件哈希、解码像素哈希、归一化哈希及粗网格哈希。相同内容跨来源合并；相同内容但不同标签整组排除；一组只进入一个拆分。粗网格一致只是额外保守分组，不能证明所有增广亲缘都被找到。EasyPR 没有原车辆/场次元数据，因此本测试是内容去重的字符识别诊断。公开 CCPD 的四省分布不能补足31省车辆泛化验证。

指标为每类原始正确数、汉字混淆矩阵、拒识后的正确/误识/拒识，另记量化前后差异。资源记录权重字节、MAC 数和保守累加上界；它们是映射预算，不能替代 Efinity 综合与整机验收。
