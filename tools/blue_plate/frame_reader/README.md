# Raw RGB帧持有与读取

`rtl/frame_reader.v`是独立的100MHz单任务读取核。持有同一完成raw槽的身份，重复执行ROI或全图读取；输出两个RGB像素、keep、原图坐标及行/命令末标记。共享帧控制、DDR仲裁和顶层接入由主实现负责。

- 槽位0..40，地址为`slot*0x300000`；1280×720 RGB24逐行存储，每个128位返回拍的高字节在前。
- ROI宽1..320、高1..96；`full_scan`选择完整1280×720，避免把1280塞入9位ROI字段。
- 一个在途突发，最多32拍、16字节对齐且不跨4 KiB。整突发空间在请求前保留；消费方长停顿不阻塞DDR返回。
- `identity={slot,frame_id,epoch,generation,source_time_ms}`贯穿所有命令及最终完成；一次ROI完成不释放来源帧。
- hold授予必须与任务接收原子完成。取消输出通过`abort_valid/abort_status`明确通知；正常release在反压期间保持有效且身份不变。
- 缺拍、错误last及无在途时的额外响应进入恢复隔离；必须等当前`recover_req`对应的外部清理确认。超时只能发cancel，不能声称总线已排空。

端口、状态码、同拍优先级、协调复位与恢复握手见[完整契约](../../../docs/validation/blue-plate/frame-reader/contract.md)。外部必须按该契约实现hold和读通道隔离，不可直接把本核接到共享AXI上。

根目录运行：

```powershell
D:/Python/python.exe -B tools/blue_plate/frame_reader/tests/prepare.py
D:/Python/python.exe -B tools/blue_plate/frame_reader/tests/run.py --tag final-v3
D:/Python/python.exe -B tools/blue_plate/frame_reader/tests/run.py --tag quick --quick
./tools/blue_plate/frame_reader/build.ps1
```

测试从独立RGB字节内存取数据，与按坐标计算的像素逐项比较。`--quick`省略518条批量ROI/全图命令，保留协议与故障回归；完整验收使用不带此选项的命令。每次tag独立保存编译输入、二进制、命令、日志、退出码及哈希，不在运行中修改已编译输入。

map实测1272 LUT、573 FF、205 ADD、7 RAM10、0 DSP，来源为真实流接口端口；未做独立核PNR。验证结果和具体版本见[报告](../../../docs/validation/blue-plate/frame-reader/report.md)。没有修改共享视频工程或访问板卡。
