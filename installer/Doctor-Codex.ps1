param([switch]$Offline)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
$python=Join-Path $root 'venv\Scripts\python.exe'
$configure=Join-Path $root 'app\installer\configure_codex.py'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Python de cette installation est absent.' }
& $python $configure --root $root --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$manifest=Get-Content -LiteralPath (Join-Path $root 'installation.json') -Raw | ConvertFrom-Json
if ($manifest.desktop.status -eq 'skipped') { Write-Host 'Codex Desktop : installation ignoree explicitement (CI/test), non certifiee.' }
elseif (-not (Get-AppxPackage -Name OpenAI.Codex -ErrorAction SilentlyContinue)) { throw 'Codex Desktop manque : OpenAI.Codex non installe.' }
else { Write-Host 'Codex Desktop : package OpenAI.Codex present.' }
if (-not $Offline) {
    & $python $configure --root $root --health
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
exit 0
