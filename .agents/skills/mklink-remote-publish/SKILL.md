---
name: mklink-remote-publish
description: "整理、检查并推送本仓库到 MicroKeen/Mklink-Remote；用于本项目开源发布、提交与推送，不用于操作板卡或改动原 MKLink 技能。"
---

# Mklink Remote 推送 SOP

目标固定为 `https://github.com/MicroKeen/Mklink-Remote.git`，公开仓库，新增代码 MIT，默认分支 `main`。用户已明确授权本次首发创建与推送；不要重复要求确认。后续按当次用户授权的推送范围操作。

1. **盘点与保留**：先读 `AGENTS.md`、`docs/RELEASING.md`、Git status/remotes。保留未提交内容，创建本地 Git bundle 和源码备份；不删除 `runs/`、`backups/`、厂商资料、旧实验，不强推、不改写远端历史。官方板实验与 N16R8 产品明确分开。
2. **整理公开集合**：以 `tools/public-files.json` 为文件范围。新增源码必须更新清单。第三方代码/图标/字体保留许可证；SDK、FLM、设备 Pack 不随源码镜像提交。原 MKLink 技能、MCP 和安装目录保持不变。
3. **检查敏感信息**：运行 `python tools/check-public.py --report output/public-audit.json`，再使用 Gitleaks 或等价扫描器检查拟发布树及拟推送历史。本机具体标识通过 `--private-markers <本地JSON数组>` 提供，规则源码必须保持通用，不能把待屏蔽的信息写进规则本身。复核所有命中，只记录文件、行号和规则，不输出秘密。禁止发布固件备份、配对密钥、Wi-Fi 参数、端点文件、真实目标工程、设备标识、本机绝对路径、日志或浏览器 profile。已公开代码中的泄漏不能仅靠删当前文件解决。
4. **验证源码**：依 `docs/BUILD.md` 准备固定版本依赖；在只包含公开文件的干净目录运行 `tools/verify-source.py`、浏览器自动化及 ESP-IDF 构建。更新报告，明确离线检查与手动 HIL 的差别。不为仓库发布重新烧录、不改电脑 Wi-Fi、不用 computer use 测 UI。
5. **检查实际提交**：显式暂存清单中的文件；运行 `python tools/check-public.py --index`，检查 staged diff、文件体积及许可证。记录提交 SHA 和源码集合摘要，确认没有将完整依赖/安装包/固件放进 Git。首次公开可建立无父提交的干净 main，原实验分支与 bundle 仅留本地；绝不能 `push --all` 或 `--mirror`。
6. **建仓与推送**：核验登录账号及组织权限。只有目标不存在时才创建公开仓库；确认 origin 精确匹配目标后，显式推送指定分支。GitHub 插件不支持建仓时可使用 GitHub API/Git；凭据只通过现有 credential helper 或安全环境注入，不落盘、不打印。
7. **验收**：核对远端 SHA、公开可见性、默认分支、CI 实际状态，以及匿名克隆。CI 失败先修复，不能把“已触发”写成“已通过”。将结果和证据写入本地报告；用户已授权的流程不用再次等待批准。

发布二进制是独立步骤：依 `docs/RELEASING.md` 验证版本、实机资格摘要、第三方分发许可和 SHA-256 后才上传 Releases。不要把源码 CI 或演示 UI 当作硬件资格。

首次建仓的隐私修正例外：仅当当前任务刚创建仓库、远端只有本次生成的初始化提交、没有他人提交，而且用户已经授权整理脱敏和公开推送时，可先备份，再以显式旧 SHA 的 `--force-with-lease=refs/heads/main:<旧SHA>` 定向替换该初始化提交。先核对远端 SHA，任何变化即停止；绝不使用无条件 `--force`、不改其他分支、不把此例外用于已有协作历史。GitHub 缓存或已有克隆无法由改写分支保证撤回，应如实说明。
