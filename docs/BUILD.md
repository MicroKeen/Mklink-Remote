# Build from source

## Toolchain

- Windows 10/11 x64 for the supported desktop build; WebView2 and Visual Studio C++ build tools.
- Node.js 22+ (Node 24 also tested), npm, Rust stable with the MSVC target, Python 3.12 and Git.
- ESP-IDF **5.5.2** for S3/C6 firmware. Activate its environment; do not hardcode someone else's SDK location.
- npm and Cargo dependency versions are locked. Direct Python build tools are pinned in `tools/requirements-build.txt`; upstream Python transitive dependencies are not fully locked yet, so this is not a bit-reproducibility claim.

## Obtain verified upstream inputs

Run from the repository root:

```powershell
python tools/prepare-upstream.py
python -m venv .venv
.venv/Scripts/python -m pip install -r tools/requirements-build.txt
.venv/Scripts/python -m pip install ".deps/sdk-0.4.0[remote]"
```

The helper downloads the official v0.4.0 SDK archive and verifies its fixed SHA-256, then fetches the exact backend source commit listed in `adapter/upstream.json`. It writes only `.deps/`; it does not install a skill or edit the user's MCP. Offline inputs can be supplied with `--sdk-archive` and `--source`. A source checkout must contain the exact pinned commit. The SDK and upstream backend have different versions and roles.

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

## Prepare native resources and a Windows bundle

These are maintainer build steps; review third-party binary distribution terms before publishing the outputs.

```powershell
$app = Resolve-Path desktop/mklink-wireless-config
$python = (Resolve-Path .venv/Scripts/python.exe).Path
$sdk = (Resolve-Path .deps/sdk-0.4.0).Path
& "$app/tools/build-device-tool.ps1" -Python $python
& "$app/tools/build-target-tool.ps1" -SdkRoot $sdk -Python $python
& $python "$app/tools/stage_remote_runtime.py" --source .deps/upstream --destination .deps/remote-staged
python -m venv .remote-venv
.remote-venv/Scripts/python -m pip install -r tools/requirements-build.txt
.remote-venv/Scripts/python -m pip install ".deps/remote-staged[remote]"
.remote-venv/Scripts/python "$app/tools/build_remote_server.py" --staged .deps/remote-staged --assets "$sdk/mklink" --output .deps/remote-build
```

Use a fresh staging directory if it already exists; the script intentionally refuses to overwrite an existing stage. Both `builtin_flm/manifest.json` and `builtin_packs/manifest.json` must exist in the supplied SDK assets.

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

`tools/package-release.py` additionally requires a genuine HIL qualification file with matching hashes and restoration evidence. Follow [RELEASING](RELEASING.md). Source build success does not recreate or replace that evidence.
