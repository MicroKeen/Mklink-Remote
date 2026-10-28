# Mklink Remote

[简体中文](README.md) · [Build](docs/BUILD.md) · [Agent CLI](desktop/mklink-wireless-config/docs/AGENT-CLI.md) · [Hardware](docs/HARDWARE.md)

Mklink Remote connects a MicroLink V4 debug probe to a workstation through an ESP32-S3 USB host bridge. The Windows workbench and an **unmodified MKLink remote MCP client** can share one debug session over Wi-Fi, an ESP32 access point, or BLE.

```text
Workbench / Remote CLI ─┐
                       ├─ Remote-owned backend ─ Wi-Fi or BLE ─ ESP32-S3 ─ USB ─ V4 ─ SWD ─ MCU
Original MKLink MCP ────┘
```

## Current scope

- Windows Tauri 2 workbench with three skins and light/dark themes.
- USB maintenance; AP, STA and AP+STA configuration; encrypted BLE; Wi-Fi/BLE S3 OTA.
- Shared target memory access, guarded APP programming, RTT, SuperWatch and RTOS Trace.
- JSON CLI for workbench operations and Agent integration; Info/Warning/Error log filtering, copying and export.
- Validated combination: third-party ESP32-S3 N16R8, S3 firmware 0.7.2, V4 4.7.2, STM32F411, desktop 0.8.0. See [qualification and limits](docs/VALIDATION-0.8.0.md).

Other MCUs, boards and V4 revisions are not qualified by that result. Android is environment preparation, not a completed mobile product. Center registration exists; public remote target debugging requires separate validation.

## Start here

1. Check [wiring and board requirements](docs/HARDWARE.md). USB1 is the USB-UART maintenance port; USB2 is the native USB OTG host port.
2. Use a qualified package from [Releases](https://github.com/MicroKeen/Mklink-Remote/releases) when available, or follow [source build instructions](docs/BUILD.md). This source publication does not imply an installer has been released.
3. Pair over USB1, configure a wireless connection, then open **共享目标调试** in the workbench.
4. Connect the original MKLink MCP to the site registered by Remote. Reload an already-running MCP after site creation or endpoint changes.
5. An Agent uses the bundled `mklink-remote.exe`; run `help` to list JSON operations. CLI and GUI share the same local service; MCP has a separate client identity on the shared backend.

Frontend preview (simulated devices only):

```sh
cd desktop/mklink-wireless-config
npm ci --legacy-peer-deps
npm run dev
```

Open `http://127.0.0.1:1420/?demo=1`. See [testing](docs/TESTING.md), [architecture](docs/ARCHITECTURE.md), [contributing](CONTRIBUTING.md) and [publishing SOP](.agents/skills/mklink-remote-publish/SKILL.md).

MIT for project code; dependencies and upstream components retain their own licenses. See [third-party notices](THIRD_PARTY_NOTICES.md). Firmware backups, pairing secrets, raw hardware logs, vendor documents and installed SDKs are deliberately absent.
