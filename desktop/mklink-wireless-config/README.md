# Mklink Remote desktop

Windows Tauri 2 + React + Rust workbench, version 0.8.0. Qualified S3 firmware: 0.7.2.

See the [project README](../../README.md), [source build guide](../../docs/BUILD.md), [hardware](../../docs/HARDWARE.md), [qualification](../../docs/VALIDATION-0.8.0.md) and [Agent CLI](docs/AGENT-CLI.md).

`npm ci --legacy-peer-deps`, then `npm run dev`; use `?demo=1` for simulated devices. Real hardware access requires the native resources described in the build guide. `npm test` and `npm run test:ui` do not access boards.

The workbench and CLI share a local service. The original MKLink MCP has an independent client identity on the Remote-owned shared backend; its source and installed skill remain unchanged.
