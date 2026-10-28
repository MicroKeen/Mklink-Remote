param([string]$Executable)
$ErrorActionPreference = 'Stop'
$appDir = Split-Path -Parent $PSScriptRoot
if (-not $Executable) {
    $latestPath = Join-Path $appDir 'output\current-release.json'
    if (Test-Path -LiteralPath $latestPath) { $Executable = (Get-Content -LiteralPath $latestPath -Raw | ConvertFrom-Json).executable }
    else { $Executable = Join-Path $appDir 'output\MklinkRemote-current\MklinkRemote.exe' }
}
$resolvedExecutable = (Resolve-Path -LiteralPath $Executable).Path
$desktopDir = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktopDir 'Mklink 无线工作台.lnk'
$shellObject = New-Object -ComObject WScript.Shell
$shortcut = $shellObject.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $resolvedExecutable
$shortcut.WorkingDirectory = Split-Path -Parent $resolvedExecutable
$shortcut.Description = 'Mklink 无线工作台 · USB / Wi-Fi / BLE 配置与可视化帮助'
$version = (Get-Content -LiteralPath (Join-Path $appDir 'package.json') -Raw | ConvertFrom-Json).version
$iconPath = Join-Path (Split-Path -Parent $resolvedExecutable) "resources\branding\MklinkRemote-$version.ico"
if (-not (Test-Path -LiteralPath $iconPath)) { $iconPath = $resolvedExecutable }
$shortcut.IconLocation = "$iconPath,0"
$shortcut.Save()
$check = $shellObject.CreateShortcut($shortcutPath)
if ($check.TargetPath -ne $resolvedExecutable -or -not (Test-Path -LiteralPath $check.TargetPath)) {
    throw 'Desktop shortcut target verification failed'
}
[pscustomobject]@{ Shortcut=$shortcutPath; Target=$check.TargetPath; WorkingDirectory=$check.WorkingDirectory; Icon=$check.IconLocation } | ConvertTo-Json
