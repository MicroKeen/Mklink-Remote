# Installed AP / BLE recovery regression — 2026-11-12

The tested Windows installer was Mklink Remote 0.8.4, SHA-256
`97b7a9431e6ef1e541873583315a73d8204d3f815bc134e2b3e78a632e9e299d`.
Its actual installed GUI, CLI and private backend were checked against the package,
including 2,292 resource files. The private backend remained pinned to 0.4.3;
the S3 ran `0.7.3-msc-fixed`, with V4 `V4.7.3` and an STM32F411 target.

## Reproduced failure and fix

Pausing the exclusive BLE backend for 18 seconds at 5% programming progress
expired the lease. In 0.8.3, the first reconnect then reported an invalid client
response: a retained job contained a Chinese error, and the Python sidecar wrote
Windows legacy-encoded JSON while Rust expected UTF-8. The workbench now reads
UTF-8 JSON bytes and emits ASCII-safe JSON escapes. Offline tests and the installed
component cover Chinese project paths, successful responses and errors. The 0.8.4
repeat passed first reconnect and retained-job lookup without replaying the write.

## Hardware cases

| Route | Injected cases | Result |
| --- | --- | --- |
| Native BLE | Backend pause/lease expiry; client exit; discarded submission reply; backend crash | 4 passed |
| AP through a separate C6 fixture | Lost upload begin, chunk and commit replies; client exit; discarded submission reply; lost programming-progress reply with actual fixture Wi-Fi interruption; lost native programming acknowledgement | 7 passed |

Actual installed WebView2 browser automation also passed normal session exit,
exit after client failure, saved-node reconnect and application restart on both
routes. Programming cases used the installed CLI and private backend. BLE used
the native BLE adapter. AP used a C6 USB-to-HTTP fixture joined to the S3 hotspot;
the development computer's Wi-Fi was unchanged.

The AP interruption was requested about 0.53 seconds after the native programming
command was accepted, upon a 5% progress reply. Fixture Wi-Fi was stopped for
three seconds and that reply was discarded. This combined injection does not
establish that every three-second radio outage will cause the same failure.

## Backup and restoration

Each route first read and compared two complete 512 KiB target backups. Writes
were limited to the original contents of APP sectors 3 and 4. Unknown outcomes
were not replayed: recovery waited at least 300 seconds, rebuilt the protocol,
checked full Flash and protection, then separately reset and checked CPU state.
All eleven cases matched the complete original image. Staging failures also
passed a separately submitted download after reconciliation and another full readback.
Historical unknown jobs stayed unknown; independent readback established recovery.

The C6 had a fresh, device-verified 16 MiB backup before fixture deployment. Its
current original image, rather than an older historical image, was restored and
verified by device-side full-image MD5. S3 configuration returned to its original
STA mode; pairing, preferences and site registry were unchanged. Final gateway
state was ready, without an owner, busy operation, queued RX or RX overflow.

## Limits

These results qualify the listed AP/BLE recovery cases for these exact installed
bytes. STA results from 0.8.3 are historical, not a new 0.8.4 STA qualification.
Physical power removal, cable removal, RF shielding, arbitrary GATT packet loss,
other targets and sustained-load limits were not tested here. The installer is
unsigned. This source update does not upload a binary Release or establish the
original user's unique root cause. Raw logs, identifiers, credentials, device
images and browser profiles remain private.
