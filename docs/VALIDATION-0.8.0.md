# 0.8.0 hardware qualification summary

This is a redacted summary of the 2026-10-28 bench campaign, not a test run performed by GitHub Actions. Windows desktop 0.8.0, ESP32-S3 N16R8 firmware 0.7.2, MicroLink V4 4.7.2 and STM32F411 were used.

STA, AP and BLE each passed: original MCP and workbench share the same backend/target, RAM challenge, APP programming, independent complete 512 KiB readback, preserved bootloader/options, RTT roundtrip, SuperWatch, RTOS Trace and both client-detach directions. AP additionally used native Tauri WebView browser automation while the original MCP was connected.

| Measurement | STA via C6 AP | AP via C6 STA | BLE via PC Bluetooth |
|---|---:|---:|---:|
| Programming job | 386.43 s, includes SDK verification | 54.96 s | 54.13 s |
| Independent 512 KiB readback | 155.36 s | 102.86 s | 229.83 s |
| SuperWatch, requested 10 Hz | 9.55 Hz | 9.97 Hz | 10.35 Hz |
| SuperWatch read errors | 0 | 0 | 0 |
| Trace events observed | 12,217 | 12,671 | 5,303 |

These are different observation windows, not throughput maxima. STA programming includes an extra verification step, so job times cannot be ranked directly. C6 USB/HTTP forwarding is part of the Wi-Fi measurements.

After an initial BLE readback timeout, Remote was fixed to use a 4 KiB delivery window and continue draining the same response; no write was replayed. The existing successful job was resumed for readback only. The final BLE binary was physically retested; STA/AP were tested before this BLE-only change, whose HTTP behavior was unchanged. A 4 KiB BLE read took approximately 1.58–1.77 seconds. The S3 USB PSRAM receive buffer remained 3 MiB.

The target's original APP was restored and the full 512 KiB matched the verified backup. C6 original 16 MiB firmware and S3 configuration were restored, V4 was ready and the control lease idle. The original skill and 211 installed Python modules remained unchanged. Host Wi-Fi was not switched. The user's separate C6 Companion application startup remained explicitly deferred.

Native GUI checks covered real clipboard/export, six skins/theme combinations, empty actions and 980 px layout. CLI management synchronization also used a local mock contract test; that does not replace hardware evidence.

Limits: no claim of long-duration stress, maximum Full Speed throughput, all target MCUs, Android production flows or public WSS target sessions. Public-source cleanup and offline CI are separate from this original hardware campaign; raw recordings, backups, IDs and credentials stay private.
