# Ti60F225 归档版本：edge-60fps

当前分支：archive/edge-60fps。coding/只保留此版本的源码、配置、测试、入口和冻结位流。

后续开发主线是第二版：运行 `git switch main` 返回。切换分支不会自动烧录FPGA。

[本版说明](docs/for-reader/versions/edge-60fps.md) · [Git使用说明](docs/for-reader/git.md) · [文档索引](docs/README.md)

在项目根打开PowerShell，使用以下入口：

```powershell
.\coding\edge-60fps\test.cmd
.\coding\edge-60fps\build.cmd
.\coding\edge-60fps\load.cmd
```

共享构建与控制工具保留在tools/；文档和历史证据保留在docs/。其他版本文档中的代码链接，需要切换到对应分支后使用。

第一版和第三版已被用户实测否定，仅作归档参考；原彩色直显版保留作对照。
