# Testing

## Offline source checks

Follow [BUILD](BUILD.md) to prepare an isolated Python environment and verified SDK. `tools/verify-source.py` runs the public-file audit, frontend tests/build, Python installer/transport/target boundary tests and Rust tests. It never connects hardware. Rust source tests explicitly omit distribution resources; they do not produce a qualified installer.

`npm run test:ui` launches a separate loopback preview and Playwright Chromium, checks the diagnostics/help navigation, screenshots and six theme variants, and closes its own server. No desktop computer use or OS Wi-Fi operation is involved.

ESP-IDF builds run separately for the S3 firmware. The C host tests in `tests/` cover node policy, base64 windows and OTA state transitions with doubles; they need `IDF_PATH` and a host C compiler (`CC`, default gcc).

The HTTP diagnostic counters can be tested without IDF or hardware:
`gcc -std=c11 -Wall -Wextra -Werror -I boards/third-party-esp32-s3-n16r8/firmware/wireless_gateway/main tests/test_http_diagnostics.c -o http-diag-test`, then run the executable.
`get_status.http` counts authenticated, size-validated RPC requests at body receive,
processing and send completion. Read it over the maintenance port after an HTTP
failure to locate the last authenticated RPC stage. A request absent from these
counters may still have reached the TCP listener or HTTP parser. An HTTP status
response contains its own processing/send counts from before those steps finish.
The counters contain no payloads or credentials and reset on node reboot.

On Windows, `python tests/run_http_reply.py` compiles the actual bounded response
sender with platform doubles. It checks a blocked send alongside a completing
send, admission limits, initialization/queue/send/completion failures, cleanup
ordering and 1,000 buffer ownership/reuse cycles. It does not qualify the RTOS
or radio. Request diagnostics also cover out-of-order response completion.

For physical HTTP isolation, compare a slow-reading static-page connection with
an independent periodic status connection while recording USB maintenance
`get_status.http_send`. Check active slots drain, errors and rejections are
accounted for, worker stack headroom is adequate, and control requests remain
responsive. Then repeat sustained native RTT and idle recovery before claiming
the wireless disconnect problem resolved. Preserve failure logs; never clear
probe quarantine to make a test pass.

## PR #70 backend migration (2026-11-07)

The private runtime and target helper now use upstream commit
`03f3dc8e3dcbea2b9c9a1fe735e24a758326e75a` (0.4.3) plus the Remote patch.
The nine patched files retain routing and bounded capture-tail handling; the
core bridge, Device and MUX scheduler come unchanged from that commit.

Local offline results on the adapted stage: 312 upstream/integration pytest
cases passed; 58 Remote target/transport unittest cases passed; the complete
source verifier, frontend build, Rust tests and desktop source build passed.
The browser demo smoke passed six theme variants. The target tests include
native RTT startup retention, recorder STOP before subscription close, idle-only
legacy B1 capture and the helper's selected-relay ownership. No serial/BLE IO,
firmware write, packaged-installer qualification or hosted CI run is claimed.

The new SuperWatch requires capability mask `0x618`; bulk-watch additionally
requires `0x800`. Shared SystemView requires incremental RTT support. Preserve
these upstream checks: older probe firmware may reject capture before START.
The historical V4.7.2 measurements below do not qualify the new backend. Before
release, rebuild both private binaries and repeat short capture, stop/RAM and
10/30 MHz STA/AP/BLE long tests with the actual negotiated capabilities logged.

### Wireless OTA and limited PR #70 HIL (2026-11-08)

With the S3 independently powered and no management USB connected to the PC,
the Remote service completed APP-only same-image OTA over both router STA and
BLE: inactive-slot write/readback, activate, reconnect, health check and confirm.
The retained S3 `0.7.2-recovery1` APP was unchanged; the configuration fingerprint
matched after each boot. Upload/write/verify took 147.859 s over STA and 304.062 s
over BLE; reboot/reconnect/confirm took 10.453 s and 13.281 s respectively.
This used the product service from a source build, not a qualified installer.

The verified isolated 0.4.3 backend then exercised V4.7.2/F411 on both radios at
10 and 30 MHz: all 44 single reads (4–4096 B), four 4×4 B scattered reads, and
four 30-second shared RTT sessions passed. Each session preserved capture after
a second client detached, stopped in 156–218 ms and read RAM afterwards. The
RTT cursor reported zero cache loss; that is not an end-to-end lossless claim.
The target APP was read back and matched its existing symbol fixture.

All 12 attempted continuous captures were rejected by the probe capability
checks (`0x618` for SuperWatch, `0x800` for bulk); RAM remained readable after
each rejection. They are unsupported on this fixture, not passed captures.
No `outcome_unknown` occurred in supported cases. The initial harness race
against asynchronous `connect-init` was retained as a failed attempt; waiting
for target ID and the initialization resource to clear resolved that race.

Cleanup restored the initial 10 MHz, released the lease, disconnected BLE and
verified ready/RX=0. No V4, target or C6 firmware was written, and the PC network
was unchanged. AP, target programming, SystemView, RTT downlink, sustained load,
power-loss/rollback and installer qualification remain untested in this round.
Local evidence is retained privately; no credentials or fixture paths are added
to the public source tree.

### V4.7.3 and latest pinned backend (2026-11-08)

Remote now pins official commit `3905a68bceaf6d863b9159de2a390e161788af48`
(0.4.3, PR #72), checked online against the default branch. Its staged backend,
frontend and adapter payloads match the previous PR #70 stage across 336 files;
provenance is updated. Frozen-server builds additionally reject a stale commit
or patch manifest. The existing target-helper commit guard remains in place.
The 15 staged protocol tests and 59 target-boundary tests passed.

V4.7.3 actually negotiated MUX `0x1FFF` and 480-byte transfer quantum, including
SuperWatch `0x618`, bulk `0x800` and incremental RTT `0x80`. On router STA and BLE
at both 10/30 MHz, all 44 single reads (4–4096 B), four scattered reads and four
30-second shared RTT sessions passed. The following 20-second cases completed
with zero reported parser loss/read errors/incomplete tails and readable RAM
after STOP:

| Route | Eight discontiguous 4 B regions | One contiguous 1 KiB region |
| --- | --- | --- |
| STA, both clocks | 100 Hz; 1,980 measured groups | 10 Hz; 198 groups |
| BLE, both clocks | 20 Hz; 396 measured groups | 10 Hz; 198 groups |

Counts exclude the first 200 ms warmup. BLE 1 KiB calls took 24.016/26.797 s
including collection and stopping; they do not establish unlimited duration.
All short capture sizes were attempted. Two BLE 4 KiB cases failed: 10 MHz
reported discarded bulk fragments and later session expiry; 30 MHz returned
samples after 25.094 s but the immediate RAM read failed with session expiry.
STA 10 MHz, eight regions at 800 Hz also failed: roughly 2.9 MB accumulated,
STOP was sent but remained pending when a heartbeat timed out. USB overflow
stayed zero, which did not prevent failure. Preserve these negative results.
One first STA 30 MHz/512 B harness assertion failed after RAM was readable;
its combined assertion did not preserve the complete result. Recheck passed,
but the original cause is unconfirmed and is not erased by the recheck.

Three product known-MUX recovery operations restored fresh generations without
USB unplug, reboot or target reset; old failed outcomes remain unresolved.
Final cleanup restored the initial 10 MHz, read RAM, released ownership and
verified ready/RX=0/BLE disconnected. No hardware firmware was written during
this regression. No AP, long-duration stress, target programming, actual
SystemView capture or packaged-installer qualification is claimed.

## V4.7.3 high-load repair qualification (2026-11-08)

The Remote-only patch remains pinned to upstream `3905a68bceaf6d863b9159de2a390e161788af48`.
The S3 candidate `0.7.2-highload3` was updated through the product's inactive-slot
OTA flow, verified and confirmed. Its image SHA-256 is
`f31649cb86afc965fc9ebad6096ecdd4d1fb9a3ef5deda8cb7b698ca65af26a9`.
Existing APP/full-flash backups were retained. A stronger compression candidate
was rejected and restored to this image with verified readback. V4/F411/C6
firmware and the development computer's Wi-Fi were not changed.

With 16 KiB capability-gated compressed BLE reads and fixed notification pacing,
4 KiB at a requested 10 Hz passed three separate 30-second windows at each of
10/30 MHz. Each returned 298 in-window samples (200 ms warmup excluded), measured
9.975–9.984 Hz, and zero reported parser loss, firmware read errors or incomplete
tails. Observed S3 RX peaks were at most 14,109 B. All six STOPs were followed by
successful RAM reads. This is real sample6 RAM, not an incompressible-payload
benchmark. It is not one continuous 90-second recording or an installer test.

STA eight-channel 800 Hz is **not qualified**. Historical 20-second successes
had growing queues, and repeat attempts failed. The old single-observation
backpressure threshold also rejected 400/250 Hz runs during network stalls;
those are failures, not maximum-rate measurements. The retained guard allows
transient catch-up but rejects sustained lag or lag beyond four seconds through
normal STOP cleanup. Failure results without final integrity counters are
unavailable, never zero-loss claims. Software recovery is not a retroactive
success for a failed capture.

The final guard passed three 30-second STA windows at 100 Hz per SWD clock:
2,979–2,980 complete groups per window, measured 100 Hz, no reported parser loss
or incomplete tail, queue peaks at most 2,517 B and RAM readable after every STOP.
For six final 800 Hz attempts, capture failed explicitly but STOP/RAM succeeded;
STOP-to-matching-ACK took 2.453–10.437 seconds. This improves recoverability, not
high-load stop responsiveness. The 100 Hz result is a qualified operating point,
not a maximum-rate claim.

STOP tail draining and client cancellation cleanup are separately tested.
No V4 session/heartbeat timeout was lengthened. No automatic rate change,
sample decimation, protocol fallback or target write was introduced. The
original MKLink checkout, installed runtime, skill and MCP remain untouched.

## Physical HIL

`python tests/wireless-system/test_hex_staging.py` checks the actual adapter's
BIN/HEX staging without hardware: sparse HEX preservation, invalid records,
changed images, old gateway rejection and sequenced file commit. Hardware HEX
qualification additionally requires an APP-only image, a preserved full backup,
native download verification, and readback proving Bootloader and other sectors
unchanged; host tests alone do not establish flash compatibility.

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
