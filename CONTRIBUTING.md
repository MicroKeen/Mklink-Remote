# Contributing

Start with [BUILD](docs/BUILD.md), [architecture](docs/ARCHITECTURE.md) and [testing](docs/TESTING.md). Use a focused branch and describe the concrete behavior change, validation and remaining limits in a pull request.

- Preserve compatibility with the original MKLink remote MCP. Put wireless/server adaptations in this repository.
- Add public files to `tools/public-files.json`; run the publication audit. Never commit credentials, local paths, target backups, live endpoints or raw HIL logs.
- Offline tests must not open physical devices. A hardware report must identify its scope, backup/restoration outcome and whether it changed a target; use anonymized identities in public reports.
- Do not automatically retry a write after a transport timeout. Preserve job identity and query the outcome.
- Keep Chinese UI text readable and validate all six appearance variants with browser automation.

Contributions are submitted under the project's MIT license; third-party code must retain its original attribution and license. Do not paste proprietary board manuals, firmware, keys or target project source into issues.
