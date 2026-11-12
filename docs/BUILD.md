# Build from source

## Toolchain

- Windows 10/11 x64 for the supported desktop build; WebView2 and Visual Studio C++ build tools.
- Node.js 22+ (Node 24 also tested), npm, Rust stable with the MSVC target, Python 3.12 and Git.
- GCC on PATH (`gcc`, for example MinGW-w64) for Windows host-side HTTP/MUX boundary tests.
- ESP-IDF **5.5.2** for S3/C6 firmware. Activate its environment; do not hardcode someone else's SDK location.
- npm and Cargo dependency versions are locked. Direct Python build tools are pinned in `tools/requirements-build.txt`; upstream Python transitive dependencies are not fully locked yet, so this is not a bit-reproducibility claim.

## Obtain verified upstream inputs

Run from the repository root:

```powershell
python tools/prepare-upstream.py
python desktop/mklink-wireless-config/tools/stage_remote_runtime.py --source .deps/upstream --destination .deps/remote-staged
python -m venv .venv
.venv/Scripts/python -m pip install -r tools/requirements-build.txt
.venv/Scripts/python -m pip install ".deps/remote-staged[remote]"
```

The helper downloads the official v0.4.0 SDK archive and verifies its fixed SHA-256, then fetches the exact backend source commit listed in `adapter/upstream.json`. It writes only `.deps/`; it does not install a skill or edit the user's MCP. Offline inputs can be supplied with `--sdk-archive` and `--source`. A source checkout must contain the exact pinned commit. The SDK and upstream backend have different versions and roles.

The private backend pins `3905a68bceaf6d863b9159de2a390e161788af48` (0.4.3, PR #72),
verified against the official default branch on 2026-11-08. It includes PR #70;
PR #72 changes the upstream desktop startup, with no backend/protocol diff.
This is an exact tested pin, not a floating `latest` dependency.
For an existing dependency tree pinned to an older commit, prepare a fresh directory
with `--directory .deps/pr70` and use its `upstream` and SDK paths below; preserve
the old stage. Verification takes `--runtime <fresh-stage>` (default
`.deps/remote-staged`) and tests the adapted backend, not the old asset SDK.
The target helper also uses this stage and the same Remote transport adapter.
The 0.4.0 archive supplies only verified FLM/pack assets; its Python runtime is
not installed alongside the new backend. Rebuild both private binaries for a
release; an existing packaged helper is not updated by changing this source.

## Frontend and offline verification

```powershell
Push-Location desktop/mklink-wireless-config
npm ci --legacy-peer-deps
npm test
npm run build
npx playwright install chromium
npm run test:ui
Pop-Location
.venv/Scripts/python tools/verify-source.py --sdk .deps/sdk-0.4.0
```

The verification script sets `TAURI_CONFIG` with an empty bundle-resource list for Rust tests. This lets a fresh source tree run tests without invented EXEs or firmware. **It is not a deployable application bundle.** Physical tests are separate; see [TESTING](TESTING.md).

## S3 firmware

In an activated ESP-IDF 5.5.2 shell:

```powershell
idf.py -C boards/third-party-esp32-s3-n16r8/firmware/wireless_gateway build
python desktop/mklink-wireless-config/tools/prepare-firmware.py
```

Alternatively use the board's `build.ps1 -IdfPath <your-esp-idf-directory>`; existing IDF_TOOLS_PATH and IDF_PYTHON_ENV_PATH remain installation-specific. No command above flashes a device. Firmware defaults select ESP32-S3, N16R8 and its board pin configuration. C6 source is a separate test fixture.

If reusing an existing S3 `sdkconfig`, select **External SPIRAM** under Bluetooth → NimBLE Options → General → Memory allocation strategy. Existing `sdkconfig` values take precedence over `sdkconfig.defaults`. This moves NimBLE host allocations to PSRAM and leaves internal RAM available for USB DMA.

## Release algorithm assets

Before distributing binaries, run `python desktop/mklink-wireless-config/tools/prepare-release-assets.py --sdk .deps/sdk-0.4.0 --destination .deps/release-assets`.
Use `.deps/release-assets` as `-SdkRoot` for the target helper and `.deps/release-assets/mklink` as `--assets` for the private server. It verifies Pack/archive/license hashes and retains only FLM bytes matched to bundled Apache-2.0/BSD-3-Clause packs. The current input yields 167 FLM blobs, 414 target entries and 73 packs; this is not the full upstream algorithm catalogue. Keep the pack licenses and redistribution summary with the release.

The installer includes `resources/licenses/`, including Python, Rust, frontend and font notices, the corresponding esptool/installer-helper sources, and the unmodified MPL selectors crate. Populate it from the exact build dependencies before bundling. Release builds use installed resources only; a missing resource must not fall back to this development checkout. Cargo explicitly bundles only the GUI and CLI, even if private diagnostics exist under `src/bin/`.

## Prepare native resources and a Windows bundle

These are maintainer build steps; review third-party binary distribution terms before publishing the outputs.

```powershell
$app = Resolve-Path desktop/mklink-wireless-config
$python = (Resolve-Path .venv/Scripts/python.exe).Path
$sdk = (Resolve-Path .deps/release-assets).Path
$runtime = (Resolve-Path .deps/remote-staged).Path
& "$app/tools/build-device-tool.ps1" -Python $python
& "$app/tools/build-target-tool.ps1" -SdkRoot $sdk -RuntimeRoot $runtime -Python $python
# Reuse the verified stage above; do not overwrite it.
python -m venv .remote-venv
.remote-venv/Scripts/python -m pip install -r tools/requirements-build.txt
.remote-venv/Scripts/python -m pip install ".deps/remote-staged[remote]"
.remote-venv/Scripts/python "$app/tools/build_remote_server.py" --staged .deps/remote-staged --assets "$sdk/mklink" --output .deps/remote-build
```

To check STOP scheduling, measurement tail accounting and startup echo handling
without hardware, run `tests/run_staged_mux_slot.py`, `tests/run_staged_mux_tail.py`,
`tests/run_staged_watch_read_error.py`, `tests/run_staged_dump_echo.py` and
`tests/run_staged_pr70.py` with the remote Python environment and
`PYTHONPATH` set to the absolute path of `.deps/remote-staged`.

Use a fresh staging directory if it already exists; the script intentionally refuses to overwrite an existing stage. Both `builtin_flm/manifest.json` and `builtin_packs/manifest.json` must exist in the supplied SDK assets.

Run the following bundle commands in a fresh public clone/export. Tauri can discover private `src/bin` diagnostics even when Cargo has `autobins=false`; do not bundle an experiment working tree. Verify the installed root contains only the GUI, CLI and uninstaller.

Map local build paths out of Rust diagnostics before compiling a public binary. For example, set `CARGO_ENCODED_RUSTFLAGS` to `--remap-path-prefix=<user-home>=/build-home` and `--remap-path-prefix=<checkout>=/source`, separated by character 31; use both Windows and slash-normalized checkout spellings. Keep these flags for the complete release build and scan the installed files for private markers.

Prepare the CLI resource before the full Tauri bundle:

```powershell
Push-Location desktop/mklink-wireless-config
npm run build
$env:TAURI_CONFIG='{"bundle":{"resources":[]}}'
cargo build --locked --release --bins --features tauri/custom-protocol --manifest-path src-tauri/Cargo.toml
Remove-Item Env:TAURI_CONFIG
New-Item -ItemType Directory -Force src-tauri/resources/cli | Out-Null
Copy-Item src-tauri/target/release/mklink-remote.exe src-tauri/resources/cli/mklink-remote.exe
npm run desktop:build
# Synchronize the CLI after the final resource-aware build, then bundle it.
Copy-Item src-tauri/target/release/mklink-remote.exe src-tauri/resources/cli/mklink-remote.exe -Force
npm run tauri -- bundle --bundles nsis --ci
Pop-Location
```

The bundle must contain the real firmware manifest/images, installer helper, target helper, private backend, CLI and branding. Never distribute a source-test build with empty resources. Tauri's NSIS bundling can patch the GUI executable; compute qualification hashes after bundling completes.

The NSIS hooks refuse installation or removal while the installed GUI, local
service or private backend is using its executable. Finish target jobs and stop
those processes before upgrading. Upgrades replace the recognized private
backend directory so obsolete frozen dependencies cannot survive; pairing and
preferences live outside that directory. Verify the installed resource inventory
after an upgrade, not only an extracted installer.

`tools/package-release.py` additionally requires a genuine HIL qualification file with matching hashes and restoration evidence. Follow [RELEASING](RELEASING.md). Source build success does not recreate or replace that evidence.
