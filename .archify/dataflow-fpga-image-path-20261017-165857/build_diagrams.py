import json
import subprocess
from pathlib import Path
from html import escape

folder = Path(__file__).resolve().parent
root = folder.parents[1]
snapshot = folder / 'source-snapshot'
revision = subprocess.check_output(['git','-C',str(snapshot),'rev-parse','HEAD'],text=True).strip()
relative = folder.relative_to(root).as_posix()
rtl = 'coding/edge-quality-30fps/rtl/'

def source(file, first, last):
    return dict(path=rtl+file,line=first,end_line=last)

def node(id,label,sub,stage,row,sources,type='backend',tag=None):
    n=dict(id=id,type=type,label=label,sublabel=sub,stage=stage,row=row,sources=sources)
    if tag: n['tag']=tag
    return n

def flow(a,b,label,primary=True):
    return dict(id=a+'-'+b,**{'from':a,'to':b},label=label,variant='emphasis' if primary else 'default')

def save(name,title,stages,nodes,flows,cards):
    data=dict(schema_version=1,diagram_type='dataflow',meta=dict(title=title,locale='zh-CN',
        output=f'{relative}/{name}.html',quality_profile='showcase',
        repository=dict(url='https://localhost/archify-snapshots/fpga-image-path-20261017-165857.git',revision=revision,link_mode='local-only')),
        stages=[dict(label=s) for s in stages],nodes=nodes,flows=flows,cards=cards)
    (folder/f'{name}.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')

save('main-flow','FPGA 图像主线：采集、处理、显示',
 ['采集与输出','彩色恢复与时序','帧来源与呈现','局部算法与读回','全帧处理与发布'],[
 node('sensor','MIPI 接收','csi_rx_controller',0,0,[source('ti60f225_oob_top.v',381,448)],'external', 'RAW10'),
 node('color','恢复彩色与灰度','raw_full_view / RGBY',1,0,[source('ti60f225_oob_top.v',849,890),source('raw_edgeaware_area.v',1,12),source('rgb_to_gray.v',15,38)],tag='1280 × 720'),
 node('rawstore','原帧与任务调度','frame_store + DMA',2,0,[source('frame_store.v',31,39),source('frame_store_control.v',180,193),source('frame_store_dma.v',145,167)],'database','RGB24 / DDR'),
 node('local','共用局部算法链','edge_algorithm_pair',3,0,[source('edge_algorithm_pair.v',1,59),source('ti60f225_oob_top.v',896,901)],tag='每拍两像素'),
 node('post','全帧连接与识别','Canny / shape 可选',4,0,[source('frame_store.v',65,97)],tag='依配置启用'),
 node('publish','发布同帧结果','像素 + 框 + 参数',4,2,[source('frame_store_control.v',168,193),source('frame_store.v',194,217)],'database','3 个结果槽'),
 node('readback','结果读回','frame_store_dma',3,2,[source('frame_store_dma.v',333,346),source('frame_store.v',185,217)],tag='128 bit'),
 node('quad','四格原帧读回','3 保存 + 1 实时',2,1,[source('frame_store_dma.v',112,121),source('frame_store_dma.v',284,345),source('frame_store_control.v',231,235)],tag='屏幕 13'),
 node('compose','画面选择与拼接','compare_display',2,2,[source('compare_display.v',25,63),source('compare_display.v',84,127),source('ti60f225_oob_top.v',970,975)],tag='彩色 / 灰度 / 边缘'),
 node('timing','视频输出时序','cvo_axi + 对齐寄存',1,2,[source('ti60f225_oob_top.v',666,700),source('ti60f225_oob_top.v',992,1009)],tag='720p HDMI 时序'),
 node('osd','框、类别与菜单','threshold_osd',0,2,[source('ti60f225_oob_top.v',1013,1016),source('threshold_osd.v',214,277)],tag='CIRCLE / RECT'),
 node('hdmi','HDMI 编码输出','可选 Gamma → DVI',0,3,[source('ti60f225_oob_top.v',1212,1245)],'external','显示器'),
 ],[
 flow('sensor','color','RAW4 + 同步'),flow('color','rawstore','RGBY → RGB24'),
 flow('rawstore','local','读 RGB，重算 Y'),flow('local','post','结果 / 分类图'),
 flow('post','publish','job_done / ok'),flow('publish','readback','结果槽 + 描述符'),
 flow('readback','compose','RGB + 最终边缘'),flow('rawstore','quad','已保存原帧',False),
 flow('quad','compose','四格 RGB',False),flow('compose','timing','32 bit 像素流'),
 flow('timing','osd','RGB + 帧元数据'),flow('osd','hdmi','RGB + HS/VS/DE'),
 ],[
 dict(dot='cyan',title='主线是整帧任务，不是页面串联',items=[
 '摄像头持续采集；frame_store_control 从实时、冻结或录像槽中选择 job_source。同一时刻执行一个算法任务。',
 '原帧按 RGB24 存入 DDR。读给算法时重算 Y=(77R+150G+29B+128)>>8，形成每像素 32 bit 的 RGBY。',
 '正常路径保留 RGB24，并把最高字节换为边缘/分类/元数据。01、02 页也走共用结果链，只是不显示边缘。']),
 dict(dot='emerald',title='显示取什么，由页面配置决定',items=[
 'compare_display 选 RGB、由 RGB 重算的灰度、最终二值边缘，或用红色替换边缘像素。03 页使用专用比较载荷。',
 '13 页是旁路：DMA 直接从三张保存原帧和当前显示对应原帧取样，拼成四个 640×360 画面。',
 '识别框来自 shape_recognizer 的描述符；threshold_osd 最后画绿色框和类别，红边由 compare_display 画。']),
 dict(dot='violet',title='数据接口与时钟域',items=[
 '采集/局部算法：i_mipi_rx_pclk；DDR、滞后连接、识别和调度：core_clk；显示：hdmi_tx_slow_clk。',
 '跨域像素用 FIFO，配置和帧描述符用 frame_mailbox 或稳定载荷加 toggle/ack；不是软件函数调用。',
 'DDR 总线为 128 bit AXI。局部算法是 64 bit 双像素 valid/ready，附 sof/eol/eof、frame_id、epoch。']),
 ])

save('algorithm-flow','共用算法链：图像数据与控制接口',
 ['输入与任务完成','中值与几何识别','高斯与全帧连接','梯度与 DDR','分类与局部清理'],[
 node('input','RGBY 输入','in_pixels[63:0]',0,0,[source('edge_algorithm_pair.v',1,19),source('frame_store.v',158,184)],tag='in_config[15:0]'),
 node('median','3×3 中值','median_pair',1,0,[source('edge_algorithm_pair.v',22,29),source('median_pair.v',111,148),source('median_pair.v',410,418)],tag='bit11：开 / 旁路'),
 node('gaussian','3×3 高斯','gaussian_pair',2,0,[source('edge_algorithm_pair.v',30,34),source('gaussian_pair.v',62,75),source('gaussian_pair.v',106,114)],tag='bit13：Canny 才用'),
 node('sobel','梯度与 Sobel','sobel_pair',3,0,[source('edge_algorithm_pair.v',35,39),source('sobel_pair.v',72,97),source('sobel_pair.v',144,155)],tag='幅值 / 方向 / E'),
 node('nms','NMS 与双阈值','canny_nms_pair',4,0,[source('edge_algorithm_pair.v',40,45),source('canny_nms_pair.v',59,83),source('canny_nms_pair.v',120,128)],tag='高 T / 低 R×T'),
 node('cleanup','局部边缘清理','edge_cleanup_pair',4,1,[source('edge_algorithm_pair.v',46,50),source('canny_nms_pair.v',176,223)],tag='Canny 条件清理'),
 node('intermediate','写结果与分类平面','frame_store_dma',3,1,[source('frame_store.v',219,238),source('frame_store_dma.v',230,266)],'database','RGB24 + 状态'),
 node('hysteresis','八邻域滞后连接','canny_hysteresis',2,1,[source('frame_store.v',75,97),source('canny_hysteresis.v',1,36)],tag='algorithm=1 时执行'),
 node('shape','轮廓与形状判定','shape_recognizer',1,1,[source('frame_store.v',75,83),source('shape_recognizer.v',1,25),source('shape_recognizer.v',295,399)],tag='recognition=1 时执行'),
 node('finish','同帧结果发布','job_done / job_ok',0,1,[source('frame_store.v',65,78),source('frame_store_control.v',168,178)],tag='count / boxes / kinds'),
 ],[
 flow('input','median','Y + RGB'),flow('median','gaussian','Y中值 + RGB'),flow('gaussian','sobel','Y平滑 + RGB'),
 flow('sobel','nms','幅值方向 + RGB'),flow('nms','cleanup','强 / 弱 / 无'),flow('cleanup','intermediate','out_pixels'),
 flow('intermediate','hysteresis','Canny 写完'),flow('hysteresis','shape','识别开'),flow('shape','finish','s_done / s_ok'),
 flow('intermediate','shape','Sobel 识别开',False),flow('intermediate','finish','Sobel 识别关',False),
 flow('hysteresis','finish','识别关',False),
 ],[
 dict(dot='cyan',title='Sobel 和 Canny 如何共用',items=[
 'Sobel：中值（可开关）→ 高斯旁路 → |Gx|+|Gy| > T → NMS/cleanup 透传 → 跳过全帧滞后连接。',
 'Canny：中值 → 3×3 高斯 → 共用 Sobel 梯度 → 四方向非极大值抑制 → 双阈值 → 条件局部清理 → 完整八邻域连接。',
 '灰度和彩色页也使用这一任务路径；“选择显示原图”不等于物理绕开全部算法模块。']),
 dict(dot='amber',title='in_config 的实际位定义',items=[
 '[10:0] threshold：Sobel 二值阈值 / Canny 高阈值 T；默认 56。',
 '[11] median：替换 Y 为中值；[12] denoise：启用 03 页比较载荷；[13] algorithm：0=Sobel，1=Canny。',
 '[15:14] low_ratio：页面开放 0/1/2，对应 1/4、1/2、3/4。recognition_enable 独立传给 frame_store，不在这 16 bit 内。']),
 dict(dot='emerald',title='03 页为何能比较前后',items=[
 'median_pair 额外输出 out_original_luma 和 out_raw_edge（未滤波 Sobel）。并未另建第二套完整图像处理链。',
 'denoise=1 时，原 RGB24 载荷改装为原灰度、滤后灰度和未滤波边缘；主链继续产生滤后 Sobel 边缘。',
 '显示器根据 view=4/7，选择灰度前后或边缘前后。中值关时两侧应一致。']),
 dict(dot='violet',title='识别的触发和输出',items=[
 '识别关闭：edge_done 直接完成任务；识别开启：边缘成功后再启动 shape_recognizer，完成后发布。',
 '输入是 DDR 中的最终边缘状态，输出 count[2:0]、boxes[175:0]、kinds[7:0] 和 overflow；最多四个目标。',
 '识别复用 canny_hysteresis 的 ext_* 存储接口。threshold 并不直接调几何容差；圆径/矩形短边 64～400、边距 16 是 RTL 参数。']),
 ])

pages=[
 ('01','彩色实时','实时原帧','RGB24','Sobel；M=0；识别关','无操作','RGB 保留到结果槽，显示端直接选 RGB；并非摄像头直连 HDMI。'),
 ('02','灰度','实时原帧','Y0：从保留的 RGB 重算灰度','Sobel；M=0；识别关','无操作','Y0 与 rgb_to_gray 使用同一加权公式；灰度转换不销毁 RGB。'),
 ('03','中值去噪对比','实时原帧','Y0 ↔ Ym；或 E0 ↔ Em','Sobel；M 默认 1；denoise=1','K2 开关中值；K3 切灰度/边缘对比','左侧是未滤波结果，右侧取决于 M。E0 来自中值窗口复用，Em 来自主链。'),
 ('04','Sobel','实时原帧','Y0 ↔ Es；或 Es 全屏','Sobel；M=1；高斯旁路；T=56','K2 全屏边缘；K3 灰度/边缘分屏','默认左灰度、右中值后的 Sobel；左侧不是中值输出 Ym。'),
 ('05','阈值调节','实时原帧','Y0 ↔ Es','Sobel；M=1；T 默认 56','K2 阈值 −16；K3 阈值 +16','改变 |Gx|+|Gy| > T 的 T，页面仍显示同一 Sobel 链的结果。'),
 ('06','Canny','实时原帧','Y0 ↔ Ec','Canny；M=1；高斯开；T=56；R=1/2','K2 降低 R；K3 提高 R','显示完成 NMS、双阈值、局部清理、滞后连接后的 Ec；不是梯度图。'),
 ('07','红边叠加','实时原帧','RGB24 + 红色 Es 或 Ec','M=1；默认 Canny；识别关','K2 Canny；K3 Sobel','进入和 K2 恢复 06 的 Canny 参数；K3 恢复 04/05 的 Sobel 阈值。'),
 ('08','形状识别','实时原帧','RGB24 + 红色 Ec + 绿色框/类别','Canny；M=1；T=56；R=1/2；识别默认关','K2 关闭识别；K3 开启识别','形状从 Ec 提取；OSD 只负责画框/文字。开关关或未找到目标时，与红边页很相似。'),
 ('10','现场单帧','新采集帧 → 冻结原帧','RGB24','Sobel；M=0；识别关','K2 抓下一现场帧并冻结；K3 实时','改变帧调度来源；不是一类新算法。每次 K2 都请求新的现场帧。'),
 ('11','录制','实时；保留 32 个原帧槽','RGB24','Sobel；M=0；识别关','K2 停止并实时；K3 覆盖录制','录制保存的是原帧引用与帧号，录满暂停；不是保存 32 张 Canny 图。'),
 ('12','回放','录像中的原帧槽','RGB24','Sobel；M=0；识别关','K2 播放/暂停；K3 下一帧并暂停','有录像时进入首帧暂停；选中的原帧仍由共用任务链处理。'),
 ('13','四帧对比','3 个保存原帧 + 1 个实时原帧','四格 RGB24；每格 640×360','DMA 原帧拼接；M=0；识别关','K2 循环保存三格；K3 清空','此页直接取原帧 RGB 偶数行列缩小，旁路结果图显示；内部 reference 命名沿用旧接口。'),
]
controls=[
 ('threshold / T','threshold_control.pending → active → config[10:0]','Sobel 与 Canny NMS','默认 56；Sobel 判幅值 > T；Canny 将 T 作为高阈值。05 页按键调节。','threshold_control.v'),
 ('median / M','edge_ui.median → median_active → config[11]','median_pair','只改变用于后续计算的 Y。03 可开关；04—08 固定开。','median_pair.v'),
 ('algorithm','edge_ui.algorithm → config[13]','gaussian / NMS / cleanup / hysteresis','0=Sobel，1=Canny；两种算法共用 sobel_pair 梯度。','edge_algorithm_pair.v'),
 ('low_ratio / R','edge_ui.ratio → config[15:14]','canny_nms_pair','06 页选择 1/4、1/2、3/4；低阈值按整数截断 R×T。','canny_nms_pair.v'),
 ('denoise','view=4 或 7 → config[12]','edge_algorithm_pair 与 compare_display','03 的前后对比载荷开关；不要与 median 滤波开关混为一谈。','edge_algorithm_pair.v'),
 ('recognition_enable','edge_ui.recognition → frame_store.core_config[48]','shape_recognizer','边缘完成后才触发识别。几何尺寸/容差不是 threshold 控制的。','frame_store.v'),
 ('view / 显示选择','edge_ui.view → gray_sel / edge_sel / overlay_sel / reference_sel','compare_display / frame_store_dma','选择显示哪种数据。view=6 在当前版对应 13 页四格；不等于开启新算法。','ti60f225_oob_top.v'),
 ('frame_command','edge_ui → command + toggle / ack','frame_store_control','实时、冻结、抓新帧、录制、回放、保存三格。改变原帧槽的持有和读取。','frame_store_control.v'),
 ('gain_r/g/b、phase','JTAG 配置 → 帧起始锁存 → raw_full_view','RAW 彩色恢复','白平衡增益和 Bayer 相位在灰度/边缘算法之前；不是页面 05 的 threshold。','raw_edgeaware_area.v'),
 ('sensor_command','JTAG → I²C 控制 → 摄像头寄存器','i2c_master_ctrl_top','曝光/增益改变传感器输出；独立于 FPGA 边缘阈值。','ti60f225_oob_top.v'),
 ('gamma_sel','JTAG → display_gamma → DVI 输入选择','gamma_correction','显示末端可选 Gamma；不回馈到边缘或识别输入。','ti60f225_oob_top.v'),
]

rows=''.join('<tr>'+''.join(f'<td>{escape(v)}</td>' for v in (str(i),*p))+'</tr>' for i,p in enumerate(pages,1))
ctrlrows=''.join('<tr>'+''.join(f'<td>{escape(v)}</td>' for v in c[:-1])+f'<td><a href="source-snapshot/{rtl}{c[-1]}">{escape(c[-1])}</a></td></tr>' for c in controls)
html='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FPGA 图像主线与 12 页取图位置</title><style>
:root{color-scheme:light dark;--bg:#f6f8fa;--fg:#192c3e;--line:#cbd5df;--accent:#006d8f;--surface:#fff}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.7 'Segoe UI','Microsoft YaHei',sans-serif}main{max-width:1440px;margin:auto;padding:30px}h1{font-size:30px;margin:0 0 12px}h2{font-size:23px;margin:34px 0 12px}p{max-width:1100px}a{color:var(--accent)}nav{display:flex;flex-wrap:wrap;gap:22px;margin:18px 0}iframe{width:100%;height:790px;border:1px solid var(--line);border-radius:6px;background:var(--surface)}table{border-collapse:collapse;width:100%;background:var(--surface);font-size:14px}th,td{text-align:left;vertical-align:top;padding:12px;border-bottom:1px solid var(--line);overflow-wrap:anywhere}th{background:var(--bg)}.table-wrap{overflow-x:auto}code{font-size:.94em}.notice{border-left:4px solid var(--accent);padding:4px 18px}.minor{font-size:13px}summary{cursor:pointer}details{margin:22px 0}footer{margin-top:28px;border-top:1px solid var(--line);padding-top:16px;font-size:13px}@media(prefers-color-scheme:dark){:root{--bg:#111b24;--fg:#e3edf4;--line:#3b5264;--accent:#70d4f4;--surface:#182733}}@media(max-width:700px){main{padding:16px}iframe{height:640px}h1{font-size:24px}table{min-width:950px}}
</style><main>
<h1>一条共用处理链，12 个演示页面</h1>
<p class="notice">你的理解可以再补上两点：<strong>RGB 转灰度时仍保留 RGB；页面选择的是同一任务结果中的不同信息。</strong> 摄像头采集、算法处理、HDMI 显示由 DDR 解耦；只有局部窗口算法是一段接一段的像素流水。</p>
<nav><a href="#main">① 整帧主线</a><a href="#algorithm">② 算法与接口</a><a href="#pages">③ 每页取哪张图</a><a href="#controls">④ 参数控制哪里</a></nav>
<h2 id="main">① 图像从哪里进来，最终怎样上屏</h2>
<p>按箭头阅读：上排从左向右处理，下排从右向左显示。图内列标题的 01—05 是分区序号，不是屏幕页号。<a href="main-flow.html" target="_blank">展开主线图（可缩放、点选节点、导出）</a></p>
<iframe title="FPGA 整帧主线" src="main-flow.html"></iframe>
<p><strong>01 页的“原图”</strong>指经过 RAW 彩色恢复、缩小、白平衡后的 RGB，并不是传感器 RAW10。<strong>13 页四格</strong>直接读取原帧槽的 RGB，走图中的四格支路。冻结和回放复用同一套算法，只换输入原帧。</p>
<h2 id="algorithm">② 展开共用算法链</h2>
<p><a href="algorithm-flow.html" target="_blank">展开算法接口图</a>。Sobel 模式下，高斯、NMS 和局部清理保留连接但透传对应数据；全帧 Canny 连接则跳过。识别关闭时也直接跳过形状阶段。</p>
<iframe title="共用算法与接口" src="algorithm-flow.html" loading="lazy"></iframe>
<details><summary>接口里的 64 bit、valid/ready、frame_id、epoch 是什么</summary>
<p>普通 RGBY：每个像素 32 bit，<code>[31:24]=Y，[23:16]=R，[15:8]=G，[7:0]=B</code>；64 bit 一次带两个相邻像素。Sobel 把 Y 字节换成二值边缘，Canny 暂存两位分类；最终边缘在显示读回时合入。</p>
<p><code>valid &amp;&amp; ready</code> 表示这一拍数据被接收；<code>sof/eol/eof</code> 表示帧首/行尾/帧尾；<code>frame_id</code> 绑定原帧；<code>epoch</code> 绑定这一帧使用的配置。参数在帧边界和任务开始时锁存，不是中途对某个像素临时改值。</p>
<p>普通路径的 RGB 保留用于彩色与红边叠加。03 页 <code>denoise=1</code> 时，24 bit 载荷改为 <code>{原灰度, 滤后灰度, 未滤波边缘}</code>；最高字节继续携带主链边缘。因此它的灰度前后对比不从普通 RGB 重算。</p>
<p>局部处理通过 <code>result_pixels/result_valid/result_ready</code> 写回 DDR。<code>local_done</code> 后按配置执行 Canny 全帧连接，再按 <code>recognition_enable</code> 执行形状识别。全部成功后才发布 <code>job_done/job_ok</code> 对应的结果槽、框和类别。</p></details>
<h2 id="pages">③ 12 个页面各自取用哪部分图像</h2>
<p>屏幕编号保留 <strong>01—08、10—13</strong>，删除了 09，所以“第 9 个页面”是屏幕 10，“第 12 个页面”是屏幕 13。下面的按键和预设来自当前 RTL。</p>
<p><code>Y0</code>＝原 RGB 灰度；<code>Ym</code>＝中值后的灰度；<code>E0</code>＝未滤波 Sobel；<code>Em/Es</code>＝按中值设置处理后的 Sobel；<code>Ec</code>＝完整 Canny 最终边缘；<code>M</code>＝中值开关。</p>
<div class="table-wrap"><table><thead><tr><th>顺序</th><th>屏幕编号</th><th>功能</th><th>输入帧来源</th><th>显示信息</th><th>算法配置</th><th>K2 / K3</th><th>怎样接回主线</th></tr></thead><tbody>PAGE_ROWS</tbody></table></div>
<h2 id="controls">④ 参数并不都在控制同一个模块</h2>
<div class="table-wrap"><table><thead><tr><th>参数</th><th>接口连接</th><th>实际作用模块</th><th>作用</th><th>源码快照</th></tr></thead><tbody>CONTROL_ROWS</tbody></table></div>
<p><strong>08 页识别取的是最终边缘 Ec，不是 HDMI 上的红色像素。</strong> 红边和绿色框只是显示层的表达。threshold 改变边缘输入，不能直接放宽圆度、矩形直角或尺寸要求。</p>
<footer>依据：2026-10-17 当前工作区 RTL 的独立源码快照（含尚未提交的改动）；未修改项目 RTL 或板子配置。本图解释已实现连接，不代表实拍识别已验收。主要涉及 edge_ui、edge_algorithm_pair、frame_store/control/dma、compare_display、threshold_osd、median_pair、gaussian_pair、threshold_control 和顶层连线。<br>快照 revision：REVISION。<a href="provenance.json">来源记录</a>；<a href="main-review-4/main-flow.finalize-summary.json">主线检查记录</a>；<a href="algorithm-review-3/algorithm-flow.finalize-summary.json">算法图检查记录</a>。</footer>
</main></html>'''
(folder/'index.html').write_text(html.replace('PAGE_ROWS',rows).replace('CONTROL_ROWS',ctrlrows).replace('REVISION',revision),encoding='utf-8')
(folder/'provenance.json').write_text(json.dumps(dict(snapshot_revision=revision,source_root=str(root),
 source_head=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip(),
 note='Snapshot of current working RTL, including uncommitted edits; not evidence for original HEAD. localhost URL is a local fixture identity required by Archify, not a hosted service; no upload or network origin access.',
 status=subprocess.check_output(['git','-C',str(root),'status','--short'],text=True)),ensure_ascii=False,indent=2),encoding='utf-8')
print(folder)
