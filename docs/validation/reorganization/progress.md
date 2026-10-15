# 目录整理结果

2026-10-15完成。四类各保留一版进入coding，所有文档归入docs，共享工具和结构图位于tools，tmp已清空。根目录仅保留上述四个目录、README和Git管理文件。

## 配套与验证

四套工程都有源码、XML、外设配置、时序约束、调试profile、release位流、运行配置，以及build/load/control/test入口。60帧保留用户选择的0x60101065：10ms优化版，偶发黑屏仍未解决。其备份缺失的peri.xml和SDC按原构建清单哈希补齐。

| 版本 | 完整构建 | 最小建立/保持余量，ns | 离线测试 |
|---|---|---|---|
| camera-30fps | 通过 | 0.387 / 0.026 | 2560×1440、四种Bayer、间隙与帧边界通过 |
| edge-30fps | 通过 | 0.322 / 0.026 | 删除旧目录后，small回归41条命令全部通过 |
| edge-quality-30fps | 通过 | 0.377 / 0.026 | 删除旧目录后，small回归41条命令全部通过 |
| edge-60fps | 通过 | 0.352 / 0.026 | 8组小帧、1381半行曝光及增益读回通过 |

四个控制入口的--help和冻结输入校验均在旧目录删除后通过。未修改生产RTL，四个原release位流的SHA256保持不变。本次未重新烧录或进行硬件画面验收；新构建位流仅用于验证构建链，未替换release。

修正了测试台、生成器及输出路径，包括Gamma测试读取本工程查找表、60帧test-work位置和DDR故障注入临时目录。传感器与分页协议测试直接检查tools内共享实现。结构图已更新为实际目录，Archify自动验证及浏览器检查通过。

## 文档和清理

硬件手册、厂家说明、17份阶段设计记录、四版本操作说明、所选版本验收证据和第三方许可均已归档，并通过文档索引串联。阶段记录标明历史属性，旧路径不再作为运行链接。项目文档不再散落在coding和tools中。

已删除旧camera_raw、camera_edge、camera_trials、backups、research、logs等目录、散落入口、重复压缩包和废弃工具。原项目约8.03GiB；整理后工程内容约139.5MiB，本地Git另占约11MiB。最终体积随后续Git提交略有变化。

本地main分支的迁移前基线是d9a1e7a；整理结果另有提交，未配置远程。基线只保存本轮选定的四套工程，未把所有废弃试验纳入Git。release位流和仿真器独立保留，不受Git恢复保护。

证据入口：[验证汇总](verification-summary.json)、[删除清单](cleanup-manifest.json)、[临时目录清理](temporary-cleanup.json)、[文档与目录检查](layout-check.json)、[体积记录](storage-after-cleanup.json)。完整构建报告位于build，离线测试日志位于tests；记录中的tmp路径是当次执行位置，临时文件已删除。
