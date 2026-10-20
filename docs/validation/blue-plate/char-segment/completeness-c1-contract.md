# C1：冻结四角后的截字证据检查

2026-10-19。输入限定为 E1 已缓存的 373 个原尺寸粗框和 157 个最终 ROI，遍历全部 304 个开发身份。不得读取源图、运行定位/OCR/训练或修改 E1；84/112 集不参与。C1 是独立研究守门，不是产品验收。

## 实际源码与结论

资料保存在 `tmp/blue-plate-char-segment/completeness-research/openalpr/`，11 个文件按下载字节 SHA 固定，保留 AGPL-3.0 LICENSE 和文件头；只阅读，没有编译或执行第三方源码。首轮沙箱内 urllib SSL 超时，curl Schannel 失败；通过获准的同一下载脚本成功获取公开源文件。master 是下载 URL，不能当作已知 commit。

- [utility.cpp](https://github.com/openalpr/openalpr/blob/master/src/openalpr/utility.cpp)：实际 `produceThresholds` 恰好运行三种掩码：Wolf 18×18/k=.05、Wolf 22×22/k=.40、Sauvola 12×12/k=.18，均随后取反。注释中的 adaptiveMean 和亮度均衡没有执行。
- [binarize_wolf.cpp](https://github.com/openalpr/openalpr/blob/master/src/openalpr/binarize_wolf.cpp)：积分图求局部均值/标准差，Wolf 使用全图最小值及最大局部标准差，Sauvola 使用动态范围常数，边缘延伸最近有效阈值。它们可改善不均匀照明下的笔画可见性；没有最终裁剪之外的输入，不能独立证明字符完整。
- [textcontours.cpp](https://github.com/openalpr/openalpr/blob/master/src/openalpr/textdetection/textcontours.cpp)：`RETR_TREE` 保留轮廓父子层次。[characteranalysis.cpp](https://github.com/openalpr/openalpr/blob/master/src/openalpr/textdetection/characteranalysis.cpp) 的实际 `filter` 调用尺寸过滤和 `filterContourHoles`；父轮廓已接受时排除其内孔，防止一个字符重复计数。`filterByParentContour` 在此文件仅有定义，不把它说成已启用的投票阶段。
- [platemask.cpp](https://github.com/openalpr/openalpr/blob/master/src/openalpr/textdetection/platemask.cpp)：至少三枚字符支持、父轮廓面积至少模板 10%，优先子字符多、同数面积小的父轮廓；填充后用 7×7 椭圆开运算、最大外轮廓和 epsilon=2 近似。找不到时返回全白 mask。`filterByOuterMask` 只要求单轮廓剩余超过 10%，且至少 60% 字符可保留，否则恢复过滤前状态。这是背景排除，不能用作完整性证明。
- `filterBetweenLines` 要求至少 88% 面积在线带内，并检查端点距离。这可能排除离行噪声，也可能丢弃真实外侧笔画；C1 因而保留外侧证据，不先清边、开运算或删外轮廓。

选择更小的现有整数 Otsu32 上下文检查：最终 ROI 得出的同一阈值应用到对应原尺寸粗框，检测与已观测文字相连、但延伸出冻结四角的组件。它不移植上述 AGPL 实现，也不声称复现 OpenALPR。局部多阈值是后续分割候选，当前不同时引入第二套定位或阈值搜索。

## 实施前固定规则

1. 正、反灰度分别计算最终 ROI Otsu32，并将该阈值应用于粗框；保存清边前最终掩码、碰边组件和粗框关联组件的统计。不是先删 5 行/4 列再检查。
2. 从 E1 原粗框 Otsu 掩码重建组件，校验原 mask SHA。用每个冻结 `observed_groups.members` 的首像素 UID 找回实际像素，校验组面积与 bbox。不能拿 GT、字符等距预测或牌框代替字墨。
3. 新阈值组件与某组原墨像素重叠至少该组一半且至少 3 像素，才算强关联。一个组件强关联多个组、宽大于 1.5H、高不在 [0.5H,3H]、或接触粗框边界，标为证据不足，不直接判截字。H 是七个冻结组高度的中位数。
4. 以原像素中心和 Q16 四角的整数叉积判断内外。至少 15% 组件像素在四角内；同一条边外至少 max(3,ceil(5%组件面积)) 像素，且超出距离至少 max(2,ceil(0.1H)) 原像素，判为关联笔画越界。距离采用叉积 / 边向量最大绝对分量，避免浮点根号。任一有效组件满足即 `reject_truncation_evidence`。
5. 两种极性都保留原始证据，但只允许 E1 实际形成该文字行的 `source_polarities` 触发判定。未形成文字行的另一极性记 `no_frozen_line_association`，不能用背景反色假装字符。
6. 未发现越界只记 `unknown_no_truncation_evidence`，不认证完整。关联不足另记 unknown 原因。原 70 个选中中可列出“未新增拒绝、完整性未知”；原 34 个歧义始终拒绝，不能因为删除到一个就升级。原未选中不能新增选中。sample164 已有人工截字证据，单独记录人工结论，自动是否检出须如实报告，不硬编码它的身份到算法。
7. 实际全量评估前固定脚本、规则和身份 SHA。每个 157 假设只运行一次。结果可以生成图和统计，不能据此修改本轮参数。

## 对照与验收口径

冻结后按身份升序从缓存最终 ROI 选择前八个具有独立、未碰边、h≥23、w≤36 的亮字组件，每帧取面积最大的合格组件。使用其实际二值笔画作为模板，在已知背景上放置七个分开的副本。每个模板正反两种极性分别检查完整、上/下/左/右截断、独立牌框碰边六种情形，共 96 项。截断量固定为该模板对应尺寸的 1/4；这些是合成笔画完整性的已知对照，不宣称原自然图字符已标注完整。另加连接牌框的 unknown 控制。控制不用于调参。

汇报所有假设、原选中新增拒绝/保留、原歧义、人工未知、164 证据及合成检出/误拒绝。GT IoU 或外框包含率只可引用旧评估数据作代价统计，不能作为字符完整标签。新增守门不会恢复上游 64 个缺失或定位召回；必须报告这项代价，并给出有依据的上游/分割方向。
