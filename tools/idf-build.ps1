param(
    [Parameter(Mandatory=$true)][string]$Project,
    [string]$IdfPath=$env:IDF_PATH
)
$ErrorActionPreference='Stop'
if ($IdfPath) {
    $export=Join-Path $IdfPath 'export.ps1'
    if (!(Test-Path -LiteralPath $export)) { throw 'IDF_PATH must point to an ESP-IDF 5.5.2 checkout.' }
    . $export
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
if (!(Get-Command idf.py -ErrorAction SilentlyContinue)) { throw 'Activate ESP-IDF 5.5.2 first, or pass -IdfPath. IDF tools and Python paths are controlled by your ESP-IDF installation.' }
& idf.py -C (Resolve-Path -LiteralPath $Project).Path build
exit $LASTEXITCODE
