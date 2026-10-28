param([string]$Python='python')
$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
& $Python -m PyInstaller --noconfirm --onefile `
    --name mklink-device-tool --distpath (Join-Path $projectDir 'src-tauri\resources\device-tool') `
    --workpath (Join-Path $projectDir 'output\device-tool-build') `
    --specpath (Join-Path $projectDir 'output') --collect-all esptool --collect-all esp_pylib `
    (Join-Path $PSScriptRoot 'device_tool.py')
$toolBuildExitCode = $LASTEXITCODE
if ($toolBuildExitCode -ne 0) { exit $toolBuildExitCode }
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'PYSERIAL-NOTICE.txt') -Destination (Join-Path $projectDir 'src-tauri\resources\device-tool\PYSERIAL-NOTICE.txt') -Force
exit 0
