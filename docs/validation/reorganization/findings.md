# 迁移依据

- 已研究OpenTitan目录与prim.core、.gitignore：源码、工具、文档和构建输出分开；不引入它的构建系统。
- Git官方gitignore文档：https://git-scm.com/docs/gitignore 。忽略规则先于首次git add；只跟踪明确选择的目录。
- 四来源：camera_raw原直显、camera_edge当前O1、quality_preserve/resource2+board+a_input20ms、backups/edge60-bilinear-10ms-20261014中的65版。
- 65备份未包含全部IP/约束，必须用build-verification.json的source_sha256补齐；不能混用66诊断版的修改输入。
- 当前根无Git；历史仅通过工程副本保存。用户授权删除未选试验和多余记录，但必要设计、手册、许可证、操作及验收资料须集中保留。
