# Changelog

## 0.8.1 — Windows preview (2026-11-08)

- Rebuild the private backend and target helper from the tested 0.4.3 pin, including Remote heartbeat, STOP-tail and backpressure fixes. No experimental dual-core/64 KiB changes are included.
- Reduce the main navigation to overview, shared debugging, logs and help; retain setup and maintenance under an expandable group, with overview diagnostics collapsed.
- Update in-app Agent guidance and machine-readable CLI capabilities with the backend binding, task completion rules and sampling limitations.
- Keep STOP requests visibly pending until the target job ends; distinguish parser frame loss from sample loss and handle immediate cancellation without dividing by zero.
- Actual installed-CLI AP/STA/BLE 10/30 MHz qualification, explicit STOP/RAM verification and STA APP OTA; see [profiles and retained failures](docs/VALIDATION-0.8.1.md). High-load results do not imply unlimited wireless throughput.
- S3 0.7.3 uses software AES-GCM to avoid internal DMA scratch pressure on large BLE replies; OTA reserves 1 KiB readback memory before erase. Initial low-memory failures and USB APP-only recovery are documented.
- Package only the GUI/CLI and verified resources, map private Rust build paths, retain third-party notices and filter algorithm assets to licensed byte matches. Release gates bind both firmware and installer hashes. C6 is retained as a user-authorized test fixture.


## Unreleased

- Target helper reuses the staged Remote adapter; migrate SuperWatch tail callbacks and shared RTT recorder stop/drain, removing the duplicate transport and startup queue patch.

- Rebase the private backend onto MKLink PR #70 (`03f3dc8e`), reuse its transport policies and independently correlated HTTP PINGs, and retain Remote compression, HEX, recovery and diagnostics.
- Preserve measurement tails for acknowledged small/narrow and bulk MUX stops; retain upstream capability, timing and reset validation. Offline verification now uses the staged private backend.
- This source migration is not a firmware upgrade or a new hardware qualification; older probe sampling capabilities can be rejected by the new core.

- The shared Remote backend and S3 gateway negotiate independent Wi-Fi sample reads and optional lossless compression. Heartbeats and STOP can use the control connection during a read.
- SuperWatch checks already-queued samples at the read-error deadline. Dump measurements separate the startup echo from parser errors and account for in-window samples delivered at STOP.
- The single-channel 800 Hz STA result does not extend to eight channels. See the [wireless stress results](docs/TESTING.md#retained-gateway-stress-results) for tested workloads and limits.

## 0.8.0 — source publication

- Remote-owned wireless/server adapter; original MKLink skill and MCP remain unchanged.
- GUI and JSON CLI share a local service; original MCP joins the same target backend with an independent client identity.
- Diagnostics page with Info/Warning/Error, search, pause, copy and export; Agent help.
- BLE delivery window and delayed-notification handling corrected without replaying writes.
- STA/AP/BLE qualification with STM32F411, including complete readback, RTT, SuperWatch and RTOS Trace; original target/C6 firmware restored.
- Public source manifest, local publishing skill, dependency preparation, portable build inputs and offline CI.

The historical 0.8.0 source publication used S3 0.7.2. Desktop and S3 versions are independent; later preview qualification is described above.
