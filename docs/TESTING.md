# Testing

## Offline source checks

Follow [BUILD](BUILD.md) to prepare an isolated Python environment and verified SDK. `tools/verify-source.py` runs the public-file audit, frontend tests/build, Python installer/transport/target boundary tests and Rust tests. It never connects hardware. Rust source tests explicitly omit distribution resources; they do not produce a qualified installer.

`npm run test:ui` launches a separate loopback preview and Playwright Chromium, checks the diagnostics/help navigation, screenshots and six theme variants, and closes its own server. No desktop computer use or OS Wi-Fi operation is involved.

ESP-IDF builds run separately for the S3 firmware. The C host tests in `tests/` cover node policy, base64 windows and OTA state transitions with doubles; they need `IDF_PATH` and a host C compiler (`CC`, default gcc).

## Physical HIL

The 0.8.0 result is summarized in [VALIDATION-0.8.0](VALIDATION-0.8.0.md). Historical raw scripts and recordings containing fixture identities and private paths are not included in the public source release. `tests/c6-network-fixture` provides source for a separately provisioned network fixture, not an auto-flash test.

For a new hardware qualification, record device/firmware versions, verify full backups, exercise STA/AP/BLE with the original MCP and workbench, validate complete target readback, RAM challenge, RTT bidirectional data, SuperWatch, Trace and both client-detach directions. Restore the target/C6 and S3 configuration and verify restoration. Publish only redacted summaries. Stop on an unknown write outcome and inspect the retained job; never replay it blindly.

BOOT gestures, physical RGB colors, sustained stress, other targets, Android business flows and public WSS target sessions need explicit separate evidence. CI does not stand in for these tests.
