# Testing

## Offline source checks

Follow [BUILD](BUILD.md) to prepare an isolated Python environment and verified SDK. `tools/verify-source.py` runs the public-file audit, frontend tests/build, Python installer/transport/target boundary tests and Rust tests. It never connects hardware. Rust source tests explicitly omit distribution resources; they do not produce a qualified installer.

`npm run test:ui` launches a separate loopback preview and Playwright Chromium, checks the diagnostics/help navigation, screenshots and six theme variants, and closes its own server. No desktop computer use or OS Wi-Fi operation is involved.

ESP-IDF builds run separately for the S3 firmware. The C host tests in `tests/` cover node policy, base64 windows and OTA state transitions with doubles; they need `IDF_PATH` and a host C compiler (`CC`, default gcc).

## Physical HIL

The 0.8.0 result is summarized in [VALIDATION-0.8.0](VALIDATION-0.8.0.md). Historical raw scripts and recordings containing fixture identities and private paths are not included in the public source release. `tests/c6-network-fixture` provides source for a separately provisioned network fixture, not an auto-flash test.

For a new hardware qualification, record device/firmware versions, verify full backups, exercise STA/AP/BLE with the original MCP and workbench, validate complete target readback, RAM challenge, RTT bidirectional data, SuperWatch, Trace and both client-detach directions. Restore the target/C6 and S3 configuration and verify restoration. Publish only redacted summaries. Stop on an unknown write outcome and inspect the retained job; never replay it blindly.

BOOT gestures, physical RGB colors, sustained stress, other targets, Android business flows and public WSS target sessions need explicit separate evidence. CI does not stand in for these tests.

### Continuous memory reads over radio

Set the producer period explicitly in `measure_dump_memory`. For a single 4-byte SRAM region on the V4/F411 fixture, start at 1 ms (`period: 0.001`) over C6-forwarded Wi-Fi and 5 ms (`period: 0.005`) over BLE. Start with a 0.5 s capture at the selected SWD clock. Check the returned clock, period, integrity counters and a subsequent RAM read before running a 20 s capture. Record actual sample rate and host elapsed time separately. Keep wired saturation results and paced wireless results in separate series.

The S3 management port exposes `probe.rx_pending`, `rx_peak`, `rx_capacity` and `rx_overflows` through `get_status`. Queued data can delay a command response even when the overflow count is zero. If a local runtime call times out, check the outstanding operation and node state before sending another target command. Keep the C6 forwarder alive after detaching the workbench until the backend releases its node lease and the RX queue drains.

### Retained gateway stress results

On the V4.7.2/F411 bench with S3 firmware `0.7.2-wifiz1`, each case requested 90 seconds using the matching packaged Remote backend. STA used a real router. The eight-channel layout sampled SysTick and seven SRAM words together at 800 groups/s. BLE requested one contiguous 1,024-byte SRAM region every 100 ms using `capture_dump`.

| Route and load | 10 MHz SWD | 30 MHz SWD |
| --- | --- | --- |
| STA, eight channels | 7,247 complete groups recorded before interruption | 7,995 complete groups recorded before interruption |
| BLE, 1 KiB, cold session | First complete sample unavailable; subsequent RAM read succeeded | First complete sample unavailable; subsequent RAM read succeeded |
| BLE, 1 KiB, after a short MUX warmup | Session expired after about 24 s | Session expired after about 25 s |

Neither workload completed the 90-second window at either clock. Both STA recordings had zero timestamp-inferred gaps **within the saved prefix**. Both STA failures and both warm BLE failures prevented the immediate RAM check. A failed finite capture does not return partial samples or final integrity counters. Report those counts as unavailable. A zero USB receive-overflow count does not establish lossless end-to-end capture. These results are workload-specific and do not qualify an installer or establish a maximum stable rate.
