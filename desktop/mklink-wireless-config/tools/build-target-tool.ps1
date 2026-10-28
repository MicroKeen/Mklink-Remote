param([Parameter(Mandatory=$true)][string]$SdkRoot,[string]$Python)
$ErrorActionPreference='Stop'
$projectDir=Split-Path -Parent $PSScriptRoot
if (!$Python) { $Python=Join-Path $projectDir '.target-venv\Scripts\python.exe' }
if (!(Get-Command $Python -ErrorAction SilentlyContinue)) { throw 'Create the isolated native target build environment first. See docs/BUILD.md.' }
if (!(Select-String -LiteralPath (Join-Path $SdkRoot 'pyproject.toml') -Pattern '^version = "0\.4\.0"$' -Quiet)) { throw 'The pinned native SDK must be0.4.0.' }
$outputDir=Join-Path $projectDir 'src-tauri\resources\device-tool'
& $Python -m PyInstaller --noconfirm --onefile --name mklink-target-tool `
    --distpath $outputDir --workpath (Join-Path $projectDir 'output\target-tool-build') `
    --specpath (Join-Path $projectDir 'output') --paths $SdkRoot --collect-data mklink `
    --hidden-import mklink.mux --hidden-import mklink.mux_rtt --hidden-import mklink.memory_write `
    --hidden-import mklink.dump_memory --hidden-import mklink.mux_watch --hidden-import mklink.systemview --hidden-import mklink.systemview_parser `
    --hidden-import mklink.cmsis_dap.algorithm_catalog --collect-all cmsis_pack_manager `
    --exclude-module pyocd --exclude-module PySide6 --exclude-module PyQt5 --exclude-module tkinter `
    --exclude-module matplotlib --exclude-module numpy --exclude-module pandas `
    (Join-Path $PSScriptRoot 'target_worker.py')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Copy-Item -LiteralPath (Join-Path $SdkRoot 'LICENSE') -Destination (Join-Path $outputDir 'MKLINK-LICENSE.txt') -Force
& (Join-Path $outputDir 'mklink-target-tool.exe') --self-test
exit $LASTEXITCODE
