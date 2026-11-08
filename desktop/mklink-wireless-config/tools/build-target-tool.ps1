param([Parameter(Mandatory=$true)][string]$SdkRoot,[Parameter(Mandatory=$true)][string]$RuntimeRoot,[string]$Python)
$ErrorActionPreference='Stop'
$projectDir=Split-Path -Parent $PSScriptRoot
if (!$Python) { $Python=Join-Path $projectDir '.target-venv\Scripts\python.exe' }
if (!(Get-Command $Python -ErrorAction SilentlyContinue)) { throw 'Create the isolated native target build environment first. See docs/BUILD.md.' }
if (!(Select-String -LiteralPath (Join-Path $SdkRoot 'pyproject.toml') -Pattern '^version = "0\.4\.0"$' -Quiet)) { throw 'The pinned native SDK must be0.4.0.' }
$pin=Get-Content -Raw (Join-Path $projectDir 'adapter/upstream.json') | ConvertFrom-Json
$provenance=Get-Content -Raw (Join-Path $RuntimeRoot 'remote-provenance.json') | ConvertFrom-Json
if ($provenance.upstream_commit -ne $pin.upstream_commit) { throw 'Stage the pinned private backend before building the target helper.' }
$assetArgs=@()
foreach ($name in @('builtin_flm','builtin_packs')) {
    $asset=Join-Path $SdkRoot "mklink/$name"
    if (!(Test-Path -LiteralPath (Join-Path $asset 'manifest.json'))) { throw "Missing verified $name assets" }
    $assetArgs+=@('--add-data',"$asset;mklink/$name")
}
$outputDir=Join-Path $projectDir 'src-tauri\resources\device-tool'
& $Python -m PyInstaller --noconfirm --onefile --name mklink-target-tool `
    --distpath $outputDir --workpath (Join-Path $projectDir 'output\target-tool-build') `
    --specpath (Join-Path $projectDir 'output') --paths $RuntimeRoot --collect-data mklink --collect-all mklink_remote @assetArgs `
    --hidden-import mklink.mux --hidden-import mklink.mux_rtt --hidden-import mklink.memory_write `
    --hidden-import mklink.dump_memory --hidden-import mklink.mux_watch --hidden-import mklink.systemview --hidden-import mklink.systemview_parser `
    --hidden-import mklink.legacy_dump --hidden-import mklink.mux_bulk_watch --hidden-import mklink.transport_factory `
    --hidden-import mklink.cmsis_dap.algorithm_catalog --collect-all cmsis_pack_manager `
    --exclude-module pyocd --exclude-module PySide6 --exclude-module PyQt5 --exclude-module tkinter `
    --exclude-module matplotlib --exclude-module numpy --exclude-module pandas `
    (Join-Path $PSScriptRoot 'target_worker.py')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Copy-Item -LiteralPath (Join-Path $RuntimeRoot 'LICENSE-MKLINK') -Destination (Join-Path $outputDir 'MKLINK-LICENSE.txt') -Force
& (Join-Path $outputDir 'mklink-target-tool.exe') --self-test
exit $LASTEXITCODE
