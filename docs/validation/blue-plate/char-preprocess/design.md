# 字符归一化与320维特征核

2026-10-18。主控确认最大原始二值ROI为320×96，覆盖整牌320×96内任何字符子区域；超过尺寸报错，不截断。共享一份输入RAM、一个32×32归一化RAM和一组顺序计算逻辑。

实施前实际读取：`char_model/model.py`的`normalize/features`、冻结`candidate/interface.json`、`rtl/char_linear.v`的输入握手与同步RAM模板；原视频工程厂商`simple_dual_port_ram.v`的独立同步读写实现。外部检索并阅读[Efinity综合指南](https://www.efinixinc.com/docs/efinity-synthesis-v4.4.pdf)的RAM属性和[Efinix BRAM Wrapper说明](https://www.efinixinc.com/support/ip/bram-wrapper.php)。厂商RAM源码和综合指南研究副本在`tmp/blue-plate-char-preprocess/research/`。不执行下载代码。

采用同步RAM推断，读写阶段分开，不复位整个RAM。每个有效任务完整写入其输入区域；所有1024个归一化像素都重新写入后才读特征。避免异步大数组读口被映射成逻辑。

处理顺序：

1. 接收宽高及行优先二值像素，同时统计紧bbox和饱和到4的原始前景计数。
2. 原始前景小于4报错；否则按参考公式计算缩放尺寸。28乘法用移位加减；尺寸除法用顺序减法，商最多28。
3. 对完整32×32画布输出零背景或最近邻原始像素，同时写归一化RAM。源坐标用加法、余数和顺序减法实现`floor(dst*size/new_size)`，只归一化一次。缩放后即使全空也不加拒绝规则。
4. 一次复用同一读口和累加器：256个2×2计数乘8，32列计数，32行计数，按冻结模型顺序输出无符号6位特征。

起始、像素输入、归一化输出、特征输出、完成状态均有valid/ready。像素`last`必须与宽高计算的最后一像素一致，提前/缺失时报协议错误并结束该任务。错误码0成功、1尺寸、2前景不足、3像素last、4状态异常。错误不输出伪特征。复位取消任务并屏蔽valid，下一任务重新装载。

320维接口及量化不变，直接匹配`char_linear.feature_data[5:0]`，无需修改冻结分类器。本阶段仅验证前处理可实现性和核级算术，不接视频top/DDR，不代表G1通过。

验证使用冻结开发批次的原始`char-*-binary.png`，按`frozen-domain/input-audit.json`逐个验哈希；`roi-masks.npy`和`frozen-masks.npy`是canonical，不能当原始ROI再归一化。加入窄1、边缘前景、极端宽高比、半整数尺寸、少于4前景、超限、last错误、输入/输出停顿及复位用例。逐个比较1024像素、320特征及可选冻结分类器的65个分数，记录无停顿周期和真实映射资源。
