param([string]$Compiler=$(if ($env:CC) {$env:CC} else {'gcc'}))
$ErrorActionPreference = 'Stop'
$rootDir = Split-Path -Parent $PSScriptRoot
$outputDir = Join-Path $rootDir 'tmp/node-policy'
New-Item -ItemType Directory -Force $outputDir | Out-Null
& $Compiler -std=c11 -Wall -Wextra -Werror -I (Join-Path $rootDir 'boards/third-party-esp32-s3-n16r8/firmware/wireless_gateway/main') (Join-Path $PSScriptRoot 'test_node_policy.c') (Join-Path $rootDir 'boards/third-party-esp32-s3-n16r8/firmware/wireless_gateway/main/node_policy.c') -o (Join-Path $outputDir 'node-policy.exe')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& (Join-Path $outputDir 'node-policy.exe')
exit $LASTEXITCODE
