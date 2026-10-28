# Repository instructions

- Product: Mklink Remote. Main sources are `desktop/mklink-wireless-config/` and `boards/third-party-esp32-s3-n16r8/firmware/wireless_gateway/`.
- Read `docs/BUILD.md` and `docs/ARCHITECTURE.md` before changing build or session behavior.
- For repository publishing, use `.agents/skills/mklink-remote-publish/SKILL.md` and the public-file manifest. Keep confidential local artifacts outside tracked files.
- Wireless adaptation belongs to Remote's `adapter/`; do not modify the user's original MKLink skill, MCP, SDK checkout, or installed runtime.
- No serial/BLE/HIL operations in ordinary tests. Hardware writes require explicit scope, verified backups and restoration evidence. Never retry writes whose outcome is unknown.
- Do not change the development computer's Wi-Fi. AP/STA HIL uses a separately provisioned C6 fixture. Use browser automation for UI checks, not desktop computer use.
- Preserve local backups, historical experiments and unrelated changes. Never use unconditional force-push, push all branches, or publish raw experiment directories. The publishing skill defines a narrowly guarded privacy-correction exception for this task's own newly initialized repository only.
- Source test build omits binary resources explicitly; it is not a deployable release. Do not invent HIL, CI, Android or performance claims.
