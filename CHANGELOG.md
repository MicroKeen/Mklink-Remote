# Changelog

## 0.8.0 — source publication

- Remote-owned wireless/server adapter; original MKLink skill and MCP remain unchanged.
- GUI and JSON CLI share a local service; original MCP joins the same target backend with an independent client identity.
- Diagnostics page with Info/Warning/Error, search, pause, copy and export; Agent help.
- BLE delivery window and delayed-notification handling corrected without replaying writes.
- STA/AP/BLE qualification with STM32F411, including complete readback, RTT, SuperWatch and RTOS Trace; original target/C6 firmware restored.
- Public source manifest, local publishing skill, dependency preparation, portable build inputs and offline CI.

The desktop version is 0.8.0. Bundled/qualified S3 firmware is 0.7.2; these version numbers are independent. Source publication is not a new hardware qualification or a claim that an installer is available.
