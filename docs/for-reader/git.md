# 本地Git使用说明

仓库位置：`D:\Desktop_New\EfinityNEW\.git`。沿用已有历史，未建立嵌套仓库，也未上传网络。`main`以第二版 `coding/edge-quality-30fps/` 为唯一开发工程。

## 分支与恢复

| 要查看的版本 | 在项目根执行 | 工程目录 |
|---|---|---|
| 第二版主线 | `git switch main` | `coding/edge-quality-30fps/` |
| 第一版归档 | `git switch archive/edge-30fps` | `coding/edge-30fps/` |
| 第三版归档 | `git switch archive/edge-60fps` | `coding/edge-60fps/` |
| 彩色直显归档 | `git switch archive/camera-30fps` | `coding/camera-30fps/` |

各分支只保留对应代码目录，但保留共享工具和文档。第一、第三版按用户实测结果归档；第二版是继续讨论和开发的基础，现存问题并未因建分支而修复。

切换前运行 `git status --short`，先提交当前需要保留的修改；不要用强制切换覆盖修改。Git切换不会烧录FPGA。需要上板时，再运行所在版本的 `load.cmd`。

## 平时怎么提交

在 `main` 上修改第二版后，先验证，再按实际改动暂存：

```powershell
git diff -- coding
git add -- coding/edge-quality-30fps
git diff --cached --stat
git commit -m "Describe the change"
git log --oneline -- coding
```

如果修改共享脚本或文档，再明确添加相应文件，如 `git add -- tools/sensor_control.py README.md`。不需要每次把整个项目都提交。

源码、约束、配置、profile、测试、build/load/control入口和冻结的 `release/ti60f225_oob.bit` 都由Git跟踪。四个冻结位流总计约11MB，可直接保存在本地Git中，分支切换后能够恢复配套加载文件。新构建仍写入忽略的 `tmp/`，不会自动进入版本库。Icarus安装目录也保持忽略。

已有的第一版传感器恢复快照一并保存在第一版归档分支中。历史证据和旧导览可继续查阅，文档中的旧代码链接需要切到对应分支后打开。

## 本次组织方式的依据

采用Git原生分支保存各版本，沿用共同历史，避免复制工程或新增仓库嵌套；参照 [git-branch官方说明](https://git-scm.com/docs/git-branch)。确认原位流被忽略后，为冻结位流添加精确例外，构建产物继续忽略；参照 [gitignore官方说明](https://git-scm.com/docs/gitignore)。验证以各分支的源码／位流哈希、工程输入完整性和切换后工作区状态为准，本次不改RTL。
