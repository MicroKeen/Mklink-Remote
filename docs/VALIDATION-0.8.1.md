# Windows 0.8.1 installer qualification (2026-11-08)

Windows installer, S3 0.7.3, V4.7.3 and STM32F411. Private MKLink backend 0.4.3 is pinned to `3905a68bceaf6d863b9159de2a390e161788af48`. This preview release is qualified only for the profiles below.

The actual NSIS installer was installed into the normal user directory. All target commands used its installed CLI and private binaries. Final resource verification covers 2306 files, including notices. Only GUI, CLI and uninstaller remain at the root. No private marker was found. GUI hashing accounts for Tauri's three-byte NSIS bundle-type marker.

## Physical CLI regression

Each row passed, reported zero parser drops/CRC errors, firmware read/drop flags and incomplete samples, and read 4 B RAM after STOP. Sample counts exclude 200 ms warmup; they do not claim perfect end-to-end sampling. Queues were sampled approximately once per second, so peaks are observed lower bounds. All final queues were zero and leases released.

| Route | SWD MHz | Payload | Hz | Seconds | Samples | Observed RX peak B | RAM after call ms |
|---|---:|---|---:|---:|---:|---:|---:|
| STA | 10 | 8ch | 100 | 30 | 2980 | 2517 | 266 |
| STA | 10 | 1KiB | 10 | 30 | 298 | 1221 | 297 |
| STA | 10 | 4KiB | 10 | 1 | 8 | 0 | 297 |
| STA | 30 | 8ch | 100 | 30 | 2980 | 2496 | 265 |
| STA | 30 | 1KiB | 10 | 30 | 298 | 2250 | 282 |
| STA | 30 | 4KiB | 10 | 1 | 8 | 4696 | 312 |
| AP | 10 | 8ch | 20 | 30 | 596 | 645 | 344 |
| AP | 10 | 1KiB | 10 | 30 | 298 | 2421 | 313 |
| AP | 10 | 4KiB | 10 | 1 | 8 | 65744 | 1875 |
| AP | 30 | 8ch | 20 | 30 | 596 | 645 | 360 |
| AP | 30 | 1KiB | 10 | 30 | 298 | 16821 | 454 |
| AP | 30 | 4KiB | 10 | 1 | 8 | 4696 | 344 |
| BLE | 10 | 8ch | 20 | 30 | 596 | 645 | 360 |
| BLE | 10 | 1KiB | 10 | 30 | 298 | 2421 | 375 |
| BLE | 10 | 4KiB | 10 | 30 | 298 | 9392 | 343 |
| BLE | 30 | 8ch | 20 | 30 | 596 | 827 | 266 |
| BLE | 30 | 1KiB | 10 | 30 | 298 | 2421 | 297 |
| BLE | 30 | 4KiB | 10 | 30 | 298 | 9392 | 360 |

Single RAM reads of 4/16/1024/4096 B passed on all six route/clock combinations. The existing target APP matched before and after each route; the initial 10 MHz was restored.

Explicit CLI STOP smoke (128 B, 20 Hz, STA): accepted in 125 ms, pending state observed, task ended in 1641 ms. Native acknowledged STOP/tail drain took 296 ms; RAM readback passed. CLI time includes process and polling overhead.

## Preserved failure and release fix

The initial 0.7.3 hardware-AES build accepted small BLE management responses but failed a roughly 2.5 KiB status reply before target acquisition. S3 recorded reply-crypto failures while V4 remained ready/RX=0. Internal free memory was about 11 KiB. ESP-IDF's AES DMA fallback allocates internal scratch buffers for unaligned PSRAM output. The release disables hardware AES to remove that DMA scratch dependency, retaining authenticated encryption. The hardware-AES build also failed OTA readback allocation: the largest internal block was below its 8 KiB scratch requirement, including after reboot. Recovery required a fresh verified full Flash backup and USB APP-only installation. The release reserves a 1 KiB readback buffer before erase; host tests cover successful verification with a 1 KiB allocation limit and refusal before erase below that limit. Subsequent product OTA and all final rows use the resulting verified APP. Earlier failed attempts remain private evidence, not passed captures.

## Limits

- STA 4 KiB at 10 Hz failed a 30-second attempt with sustained backlog; protected STOP drained RX and released the node without outcome_unknown. Wi-Fi 4 KiB qualification is limited to 1-second captures plus single reads.
- AP uses a separately provisioned C6 USB-to-Wi-Fi fixture. Its timings include the fixture and are not direct PC-to-AP throughput.
- 800 Hz multichannel Wi-Fi remains unqualified. These 30-second profiles are an installer regression, not maximum-rate or long-term endurance guarantees.
- No new target programming, RTOS Trace, simultaneous multi-client, Android, power-loss rollback, BLE OTA or GUI-native interaction qualification in this round. Browser smoke uses simulated devices.
- Unsigned Windows installer. The distributed catalogue has 167 verified licensed algorithm blobs / 414 target entries; other MCUs are not hardware-qualified.

## Recovery and scope

S3 APP-only OTA to 0.7.3 was hash-verified, activated and confirmed. Router STA settings were restored after AP testing and reconnection checked. C6 runs the user-retained 0.2.4 fixture; its original desktop application is preserved in a verified private 16 MiB backup, not marked restored. V4/F411 were not flashed. PC Wi-Fi, original MKLink runtime and skill were unchanged. A power cycle and USB APP-only recovery were needed before the final matrix; no probe unplug/replug was needed within completed final profiles.

Offline source verification, 14 Rust tests, frontend build and browser demo smoke passed. Raw device logs, credentials, backups and original application files stay private. Release assets contain sanitized qualification JSON/HTML, checksums and notices/corresponding source.
