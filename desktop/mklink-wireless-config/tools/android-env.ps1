param([switch]$AllowIncomplete)
$ErrorActionPreference='Stop'
$taskProject=Split-Path -Parent $PSScriptRoot
$taskConfig=Join-Path $taskProject '.android-env.local.json'
if (!(Test-Path -LiteralPath $taskConfig)) {throw 'Missing local Android paths. See repository docs/ANDROID.md.'}
$taskPaths=Get-Content -LiteralPath $taskConfig -Raw | ConvertFrom-Json
foreach ($taskKey in @('JAVA_HOME','ANDROID_HOME','NDK_HOME')) {
    $taskValue=[string]$taskPaths.$taskKey
    if (!$taskValue) {throw "Missing $taskKey in Android path configuration"}
    if (!$AllowIncomplete -and !(Test-Path -LiteralPath $taskValue)) {throw "Missing Android tool: $taskKey"}
    [Environment]::SetEnvironmentVariable($taskKey,$taskValue,'Process')
}
$env:ANDROID_SDK_ROOT=$env:ANDROID_HOME
$taskBins=@("$env:JAVA_HOME/bin","$env:ANDROID_HOME/cmdline-tools/latest/bin","$env:ANDROID_HOME/platform-tools")
$env:Path=($taskBins -join ';')+';'+$env:Path
