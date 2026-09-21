$installDirectory = $PSScriptRoot
# Do not inherit the IPC endpoint, node-only mode or portable root of another editor.
foreach ($name in @('VSCODE_IPC_HOOK_CLI','VSCODE_PORTABLE','ELECTRON_RUN_AS_NODE')) {
    [Environment]::SetEnvironmentVariable($name,$null,'Process')
}
$environmentFile = Join-Path $installDirectory 'environment.json'
if (-not (Test-Path -LiteralPath $environmentFile)) { throw 'Installation incomplete : relancer Repair.cmd.' }
$runtimeEnvironment = Get-Content -LiteralPath $environmentFile -Raw | ConvertFrom-Json
foreach ($property in $runtimeEnvironment.PSObject.Properties) { [Environment]::SetEnvironmentVariable($property.Name,[string]$property.Value,'Process') }
$env:PATH = (@('apps\node','apps\npm\node_modules\.bin','apps\git\cmd','apps\rg','venv\Scripts') | ForEach-Object { Join-Path $installDirectory $_ }) -join ';'
$env:PATH += ';'+[Environment]::GetEnvironmentVariable('PATH','User')+';'+[Environment]::GetEnvironmentVariable('PATH','Machine')
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $installDirectory 'browsers'
$runtimeManifest = Get-Content -LiteralPath (Join-Path $installDirectory 'installation.json') -Raw | ConvertFrom-Json
