param([string]$IdfPath=$env:IDF_PATH)
$ErrorActionPreference='Stop'
& (Join-Path $PSScriptRoot '../../tools/idf-build.ps1') -Project $PSScriptRoot -IdfPath $IdfPath
exit $LASTEXITCODE
