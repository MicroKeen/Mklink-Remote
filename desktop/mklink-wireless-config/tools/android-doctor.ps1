$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'android-env.ps1')
$taskProject=Split-Path -Parent $PSScriptRoot
$taskChecks=[ordered]@{}
$taskChecks.java=(& "$env:JAVA_HOME/bin/java.exe" -version 2>&1 | Out-String).Trim()
$taskChecks.rust=(& rustc --version | Out-String).Trim()
$taskInstalled=@(& rustup target list --installed)
$taskRequired=@('aarch64-linux-android','armv7-linux-androideabi','i686-linux-android','x86_64-linux-android')
$taskChecks.rust_targets=$taskInstalled
$taskChecks.missing_targets=@($taskRequired | Where-Object {$_ -notin $taskInstalled})
$taskChecks.sdk=$env:ANDROID_HOME
$taskChecks.ndk=(Get-Content -LiteralPath "$env:NDK_HOME/source.properties" | Select-String '^Pkg.Revision' | Out-String).Trim()
$taskChecks.platform37=Test-Path -LiteralPath "$env:ANDROID_HOME/platforms/android-37.0/android.jar"
$taskChecks.build_tools37=Test-Path -LiteralPath "$env:ANDROID_HOME/build-tools/37.0.0/aapt2.exe"
$taskChecks.clang=Test-Path -LiteralPath "$env:NDK_HOME/toolchains/llvm/prebuilt/windows-x86_64/bin/clang.exe"
$taskChecks.adb=(& "$env:ANDROID_HOME/platform-tools/adb.exe" version | Out-String).Trim()
$taskChecks.devices=(& "$env:ANDROID_HOME/platform-tools/adb.exe" devices -l | Out-String).Trim()
$taskChecks.developer_mode=(Get-ItemProperty -LiteralPath 'HKLM:/SOFTWARE/Microsoft/Windows/CurrentVersion/AppModelUnlock' -Name AllowDevelopmentWithoutDevLicense -ErrorAction SilentlyContinue).AllowDevelopmentWithoutDevLicense
$taskChecks.environment_scope='Process only; global JAVA_HOME/Path unchanged'
$taskChecks.ready=($taskChecks.missing_targets.Count -eq 0 -and $taskChecks.platform37 -and $taskChecks.build_tools37 -and $taskChecks.clang)
$taskChecks | ConvertTo-Json -Depth 4
if (!$taskChecks.ready) {exit 1}
