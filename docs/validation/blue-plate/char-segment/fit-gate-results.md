# 严格拟合门槛与BN诊断

2026-10-18。**原C8网络能精确拟合8张完整车牌，但当前开发集效果仍未达到旧后端。** 原配置在550/600/650步连续三次正常eval达到8/8，包含相邻重复字符；独立207张训练在2250步触发无改善停止，最佳tune为4正确/3错误/69拒绝，旧后端同76组为49/0/27。

本轮完成650步原配置、2000步dropout0对照和2250步独立开发训练，共4900个新优化器步骤，训练计时281.09秒，低于15分钟总预算。未新增容量、量化或RTL，未读val/heldout图片，未训练tune。原Candidate、旧500步代码与实验产物保持原样。严格门槛由新 `fit_gate.py` 执行，不再以loss下降放行。

## 先核对实现

复读固定上游 `train_LPRNet.py`：默认RMSprop，alpha0.9、lr0.1、momentum0.9、weight_decay2e-5、batch128、15epoch，步骤数是15×floor(数据量/128)，不能误写为固定15步或固定训练总量。本轮仍按授权保持Adam0.001等原配置，避免同时改变多个因素。

还实际检查了上游初始化匹配：代码按state_dict键名中的 `conv`/`bn` 定制权重初始化，但这个数字命名网络没有匹配项；bias会被设为0.01，卷积权重与BN权重保留框架默认初始化。本轮两条件使用同一个seed701初始state_dict/文件SHA，未混入该bias修改。

阅读[PyTorch 2.11 CTC CPU实现](https://raw.githubusercontent.com/pytorch/pytorch/v2.11.0/aten/src/ATen/native/LossCTC.cpp)及[CUDA实现](https://raw.githubusercontent.com/pytorch/pytorch/v2.11.0/aten/src/ATen/native/cuda/LossCTC.cu)：核对blank扩展目标、相邻重复字符不能直接跳过中间blank、log域前向和反向。CUDA源码已下载到 `tmp/blue-plate-char-segment/fit-gate/research/LossCTC.cu`；CPU下载超时，已通过web读取实际源码。三条含重复字符标签的CPU/CUDA对照，loss差3.8147e-6、梯度最大差1.3430e-6。没有发现维序/blank接口或CPU/GPU链路不一致。

## 固定8牌与硬门槛

冻结ROI索引 `0,2,3,4,9,13,28,31`，全部来自已复核完整train，记录原图、Q32灰度、native输入SHA和身份。标签为：皖AF3188、皖AZ798M、皖A81K37、皖AL3A23、皖A9U399、皖FLL589、皖BUN211、皖AA796N。

两条件同一初始权重、同8图、batch16（8图重复两次）、Adam0.001、梯度裁剪5、CTC和动态能量公式不变。每50步正常eval一次；**必须连续3次8/8完整greedy**，没有强制七位、按位置填字符或beam补全。

| 条件 | 优化器步数 | 正常eval结果 | 训练模式结果 | 门槛 |
|---|---:|---|---|---|
| 原dropout0.5 | 650提前停止 | 550/600/650均8/8 | 最后8/8 | 通过 |
| 仅dropout改0 | 2000达到上限 | 最佳6/8，最后3/8 | 最后8/8 | 未通过 |

这是“模型可以学会这8张”的证据，不是识别目标达成。关闭dropout没有修复eval问题。因原配置已通过，不满足“两者均失败”的第三条件触发前提，未训练固定缩放新学生。

主控已用独立CPU greedy复核两个best.pt，原配置8/8、dropout0为6/8，并核对train/tune身份隔离；审计位于 `tmp/blue-plate-review/fit-gate/review-result.json`。

## 一次独立开发训练

原配置从seed701重新初始化，**不继承8牌拟合权重**。仅207个完整train ROI参与梯度更新；76个tune身份、78个ROI只作评价与阈值选择。预先规定最多3000步，每250步评价；1500步后若最近4次评价的最多正确数不超过此前最佳，则停止。

| step | train正常eval整牌正确/207 | tune校准正确/错/拒 | tune未校准正确/错/拒 |
|---|---:|---:|---:|
| 500 | 0 | 0/0/76 | 0/10/66 |
| 750 | 3 | 0/0/76 | 0/18/58 |
| 1000 | 15 | 2/1/73 | 2/20/54 |
| **1250** | **38** | **4/3/69** | **9/30/37** |
| 1500 | 6 | 0/0/76 | 0/18/58 |
| 1750 | 26 | 2/2/72 | 5/21/50 |
| 2000 | 11 | 1/0/75 | 3/17/56 |
| 2250 | 12 | 2/1/73 | 2/9/65 |

2250步触发停止。冻结1250步best.pt，阈值-0.2126348189；SHA256 `f4689e4132485fdca7aa64633fc03d0527e1ad82ede870e897ec0ae3f5a07397`。在同一个checkpoint上把错接收限制为0，tune只有1/0/75，因此也没有在相同错误数下改善49/0/27。

开发训练81.78%的步骤触发范数裁剪；梯度始终有限，分支能量最小0.001277，epsilon命中0。训练曲线也发生回退，不能把所有差距归为未知数据泛化或仅增加步数即可解决。

## 冻结权重的统计差异

对同一best.pt复制模型，只把BN切为当前批统计，保持dropout关闭。为避免tune污染，设置 `track_running_stats=False`：没有running_mean/variance或num_batches_tracked更新。每次诊断前后逐张量核对state_dict完全相同；不反向、不保存模型，原checkpoint SHA不变。tune只使用输入，不计算标签loss、不校准模型、不按标签挑新权重；只记录预测、长度和能量变化。

| 207训练ROI | 正常eval | 当前批BN，不更新统计 |
|---|---:|---:|
| 完整正确 | 38 | 63 |
| 输出长度恰为7 | 99 | 104 |
| 平均blank帧比例 | 70.38% | 68.68% |

两模式有161/207条训练预测发生变化。tune的67/78条预测发生变化，七位长度输出39→34，blank比例71.76%→68.24%；本次无标签诊断不据此挑选模式或声称tune准确率提高。当前批BN依赖同时输入的其他样本，不能作为单牌部署方案。

逐层比较正常eval输入的当前批无偏方差与已存running variance。下表为所有训练batch/通道的范围，分子分母均加BN epsilon以稳定比值：

| BN层 | 最大标准化均值差 | 当前批方差/running variance |
|---|---:|---:|
| backbone.1 | 0.204 | 0.719–1.411 |
| backbone.5 | 0.318 | 0.665–1.461 |
| backbone.9 | 0.482 | 0.833–1.001 |
| backbone.12 | 0.227 | 0.828–1.114 |
| **backbone.17** | **0.145** | **0.243–0.820** |
| **backbone.21** | **0.187** | **0.193–0.691** |

实际代码在backbone.15和19先dropout，再经过卷积到BN17和21。后两层存下的方差系统性高于关闭dropout后的当前输入方差。这与[Dropout/BN方差漂移研究](https://openaccess.thecvf.com/content_CVPR_2019/html/Li_Understanding_the_Disharmony_Between_Dropout_and_Batch_Normalization_by_Variance_CVPR_2019_paper.html)描述的机制吻合；本项目判断主要依据上述代码位置与实测统计，未借论文结果替代本项目验证。

最后head分支能量：正常eval为0.0844–0.1238，当前批BN为0.1293–0.2574；两模式四分支均无epsilon命中。动态能量除法会继续影响分支相对尺度，不能只调整一个最终阈值解决内部统计差异。

**结论分两部分：** 推理统计差异确实造成一部分损失（38→63）；即使使用当前批统计，仍有144/207训练样本未精确识别，训练自身也没有充分学会。不能把当前批BN诊断当成完成修复，不能把8牌通过外推为207牌或独立数据性能。

## 一个最小后续方向

建议只做**冻结参数、关闭dropout、用207个train输入重估固定BN统计**的校准实验，不扩通道，不新增优化器训练，不使用tune输入更新统计。

依据是实际阅读的[PyTorch `update_bn`实现](https://raw.githubusercontent.com/pytorch/pytorch/v2.11.0/torch/optim/swa_utils.py)，本机对应文件与SHA记录在 `research/bn-calibration-source.json`。它提供用训练数据重估running统计的成熟做法，但直接调用会 `model.train()`，同时打开dropout；本项目必须明确保持dropout关闭，并按层冻结上游已校准统计，累计训练激活的通道矩，正确合并batch和最后不足16张的统计。

该校准将形成新的固定BN状态，可用于单ROI推理；与本次当前批统计诊断不同。应先冻结校准后的状态，再用原阈值和同76组对照以隔离校准收益，不能把tune当成校准数据。若正常eval仍不能取得实际改善，就停止这条校准路径；当前证据不支持直接扩容或继续叠加训练轮数。**本轮只提出此方向，没有更新或保存任何校准模型。**

## 交付

- `tools/blue_plate/char_segment/fit_gate.py`：严格门槛、受限对照、独立训练及停止规则。
- `tools/blue_plate/char_segment/fit_gate_analysis.py`：固定权重BN诊断、无标签tune诊断与零错误计数；无优化器步骤。
- `tmp/blue-plate-char-segment/fit-gate/`：8牌清单、初始化、各条件记录、checkpoint、完整BN统计、源码研究记录。
- 本目录 `fit-gate-summary.json`：精简结果与哈希归档。旧500步结果未覆盖。
