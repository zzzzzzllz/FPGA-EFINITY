# 第一版上板记录

2026-10-15，用户要求从原完整边缘版开始逐项体验。已识别一个下载器，加载0x6010100a到SRAM并恢复配套配置；用户确认初始左右对比画面正常。最后按用户要求再次执行完整load.cmd，退出码0，结果见summary.json和load-final.log。其他功能的画面效果由用户继续检查，尚不标记全部验收。

首次加载暴露出sensor-history目录不存在的问题，保存传感器恢复点时中断。tools/sensor_control.py的save现在先创建父目录，继续用独占方式写文件，防止覆盖恢复点。两个版本的既有测试改为保存到尚不存在的子目录；测试和实际加载均通过。采用Python标准库Path.mkdir(parents=True, exist_ok=True)，依据[Python官方文档](https://docs.python.org/3.11/library/pathlib.html#pathlib.Path.mkdir)，并阅读本机Efinity Python的Lib/pathlib.py实现；没有下载第三方代码或新增依赖。

中途两次只读状态查询报告调试核心UUID不匹配，未据此自动切换其他版本。用户随后要求重烧第一版；最后加载及其内置状态采样成功。不能据此推断中途不匹配的具体原因。

导图的Archify自动检查和浏览器检查通过。项目只有本地Git，没有远程origin，工具的远程URL证据模式不适用；真实本地源码位置与固定提交保存在diagram-sources.json。图中按键与架构依据对应已提交RTL，本轮改动仅涉及共享保存逻辑、其测试和说明材料。
