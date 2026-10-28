# Mklink Remote

[English](README.en.md) · [构建指南](docs/BUILD.md) · [Agent CLI](desktop/mklink-wireless-config/docs/AGENT-CLI.md) · [硬件接线](docs/HARDWARE.md)

让 MicroLink V4 通过 ESP32-S3 接入 Wi-Fi、热点或蓝牙。工作台与**原版 MKLink 远程 MCP**可以共用同一个目标调试会话，无线适配由 Mklink Remote 维护。

```text
工作台 / Remote CLI ─┐
                    ├─ Remote 共享后台 ─ Wi-Fi / BLE ─ ESP32-S3 ─ USB ─ V4 ─ SWD ─ MCU
原版 MKLink MCP ─────┘
```

## 已实现

- Windows Tauri 2 工作台，三套皮肤和深浅配色。
- USB 维护、AP/STA/AP+STA 配置、加密 BLE、Wi-Fi/BLE 节点 OTA。
- 共享目标读写、APP 烧录、RTT、SuperWatch 和 RTOS Trace。
- JSON CLI 与 Agent 操作帮助；Info/Warning/Error 日志筛选、搜索、复制和导出。
- 原技能和 MCP 保持不变，工作台与技能分别持有客户端身份，共享硬件状态和采集缓存。

已验证组合：非官方 ESP32-S3 N16R8、S3 固件 0.7.2、V4 4.7.2、STM32F411、桌面 0.8.0。详见[验收与性能口径](docs/VALIDATION-0.8.0.md)。其他板卡/MCU 不自动继承该结果；Android 仍是环境准备阶段，公网中心目标调试需另行验证。

## 开始使用

1. 核对[接线和供电](docs/HARDWARE.md)：USB1 是 USB-UART 维护口，USB2 是原生 USB-OTG Host。
2. 如有已发布的资格验证包，从 [Releases](https://github.com/MicroKeen/Mklink-Remote/releases) 下载；也可按[构建指南](docs/BUILD.md)编译。源码公开不表示安装包已发布。
3. USB1 配对并保存设备凭据，配置无线连接，进入「共享目标调试」。
4. 原版 MCP 连接 Remote 注册的站点；新增站点或端口改变后，重新加载已启动的 MCP。
5. Agent 使用同目录的 `mklink-remote.exe help` 查看 JSON 命令；操作细节见 [CLI 帮助](desktop/mklink-wireless-config/docs/AGENT-CLI.md)。

仅预览界面（模拟设备）：

```sh
cd desktop/mklink-wireless-config
npm ci --legacy-peer-deps
npm run dev
```

打开 `http://127.0.0.1:1420/?demo=1`。真实 USB/BLE/目标操作由 Windows 程序提供。

## 仓库导航

| 目录 | 内容 |
|---|---|
| desktop/mklink-wireless-config | 前端、Tauri、CLI、私有服务适配和构建工具 |
| boards/third-party-esp32-s3-n16r8/firmware/wireless_gateway | N16R8 无线网关固件 |
| tests | 离线边界测试、独立 C6 网络夹具源码 |
| tools | 上游依赖准备、公开内容检查、源码验证 |
| docs | 架构、构建、接线、测试、发布说明 |
| .agents/skills/mklink-remote-publish | 本仓库推送 SOP |

[参与贡献](CONTRIBUTING.md) · [安全报告](SECURITY.md) · [更新记录](CHANGELOG.md) · [发布规范](docs/RELEASING.md)

本项目新增代码使用 MIT；第三方许可见 [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md)。本地备份、厂商资料、凭据、原始实验日志、旧官方板实验和已安装的 SDK 不进入公开仓库。
