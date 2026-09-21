param([switch]$Offline)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'Environment.ps1')
$args=@((Join-Path $PSScriptRoot 'app\installer\doctor.py'),'--root',$PSScriptRoot)
$args+='--check-tools'
if($Offline){$args+='--offline'}
& (Join-Path $PSScriptRoot 'venv\Scripts\python.exe') @args
exit $LASTEXITCODE
