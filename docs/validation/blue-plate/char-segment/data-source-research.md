# 新增开发数据来源核查

2026-10-18。本轮只读公开元数据，未下载图片、压缩数据包或启动训练。

现有207个训练正ROI覆盖41/65类，省份为皖198、浙3、苏2、沪/粤/闽/鲁各1。新增数据应补充省份、拍摄环境与自动裁切分布，不能只扩大相同皖A样本数量。现有76tune仅2身份含训练未见字符，因此数据覆盖不能解释全部识别失败。

| 来源 | 已核实内容与适用性 | 数据许可 | 获取状态 |
|---|---|---|---|
| [CCPD](https://github.com/detectRecog/CCPD) | 官方称2019版超过30万图；文件名含四角与号码；Base有train/val划分，其余难例子集作test。可先利用官方train补充开发样本，但省份分布须从清单统计，不能假定均衡。八字Green不混入七字蓝牌训练。 | README明确声明数据集MIT，已读取LICENSE。 | README和LICENSE实际下载成功；Google Drive/百度公开入口在当前网页工具不可访问，尚未验证压缩包下载。 |
| [CLPD](https://github.com/wangpengnorman/CLPD_dataset) | 1200图，覆盖大陆31省级地区；多场景，含新能源、警牌、遮挡及不足七个可见字符。CLPD.csv含路径、顺时针四角、标签，作者说明GBK编码。适合省份多样性核查；必须筛出完整七字蓝牌，不能对遮挡图补全。 | 仓库树仅README，未发现明确数据许可；不能按开源代码许可推定数据许可。 | README实际下载；[百度入口](https://pan.baidu.com/s/1iqEucjhfKXbB0tdduRz8xA)公开，码dt11；网页工具无法打开，包内CSV未获取。 |
| [CRPD](https://github.com/yxgong0/CRPD) | single/double/multi三部分；每图txt每行一个车牌，字段为四角、type、content；type0蓝牌、1单层黄牌、2双层黄牌、3白牌。适合七字蓝牌筛选及多候选场景；未获取清单，不宣称省份均衡或可用样本数。 | 仓库树仅README，未发现明确数据许可。 | README实际下载；[CRPD-single Google Drive](https://drive.google.com/file/d/1IBBHlg4VXXYSzq6TJR5S-6i_hTyh-6dD/view?usp=sharing)能看到文件名和登录入口，未确认匿名下载；百度入口网页工具不可访问。 |

实际保存的原始材料位于 `tmp/blue-plate-char-segment/data-source-research/`：`ccpd-readme.md`、`ccpd-license.txt`、`clpd-readme.md`、`crpd-readme.md`。`sources.json`记录URL、HTTP状态、大小和SHA256。只下载约14KB文本。CCPD解析实现此前已在 `tmp/blue-plate-review/mature-research/ccpd/rpnet/load_data.py` 阅读；本轮未获得CLPD/CRPD包内数据或代码，未声称完成其源码级研究。

后续优先方向：以许可明确的CCPD官方train清单建立候选元数据，再排除当前500样本的文件、SHA和身份交集；按省份、字符、重复字符分层统计后决定是否下载。CLPD更直接对应省份缺口，但须先确认许可和可用标注；CRPD可补多候选和牌型分布。任何新增train/tune均按号码身份隔离，当前val84/heldout112不改分组。本轮未执行上述筛选、下载或新训练。
