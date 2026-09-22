param()
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
$manifestFile=Join-Path $root 'installation.json'
$manifest=Get-Content -LiteralPath $manifestFile -Raw | ConvertFrom-Json
if ($manifest.product -ne 'Web2API-Continue' -or $manifest.installation_target -ne 'codex' -or [IO.Path]::GetFullPath($manifest.root).TrimEnd('\') -ne $root) { throw 'Manifeste Codex invalide pour le superviseur.' }
$python=Join-Path $root 'venv\Scripts\python.exe'
$configFile=Join-Path $root 'config.json'
$configure=Join-Path $root 'app\installer\configure_codex.py'
foreach($path in @($python,$configFile,$configure)){if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw ('Fichier supervise absent : '+$path)}}
. (Join-Path $root 'Environment.ps1')
$logs=Join-Path $root 'logs'
$state=Join-Path $root 'state'
New-Item -ItemType Directory -Path $logs,$state -Force | Out-Null
$stopMarker=Join-Path $state 'service-stop.requested'
$supervisorLog=Join-Path $logs 'service-supervisor.log'
$stdoutLog=Join-Path $logs 'stdout.log'
$stderrLog=Join-Path $logs 'stderr.log'
$configArgument='(?:^|\s)--config\s+(?:"'+[regex]::Escape($configFile)+'"|'+[regex]::Escape($configFile)+')(?=\s|$)'
function Write-Supervisor([string]$Message){Add-Content -LiteralPath $supervisorLog -Value ((Get-Date -Format o)+' '+$Message) -Encoding UTF8}
function Get-OwnedBridge {
    @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -match '(?:^|\s)-m\s+chatgpt_web2api(?:\s|$)' -and $_.CommandLine -match $configArgument -and
        ($_.ExecutablePath -eq $python -or ($_.ExecutablePath -and $_.ExecutablePath.StartsWith((Join-Path $root 'python')+'\',[StringComparison]::OrdinalIgnoreCase)))
    })
}
Write-Supervisor 'Superviseur Codex demarre.'
try {
    $proxyOutput=@(& $python $configure --root $root --start-opencodex 2>&1)
    $proxyCode=$LASTEXITCODE
    foreach($line in $proxyOutput){Write-Supervisor ('OpenCodex : '+[string]$line)}
    if($proxyCode -ne 0){Write-Supervisor ('OpenCodex gere indisponible au demarrage, code '+$proxyCode+'.')}
} catch { Write-Supervisor ('Controle OpenCodex non bloquant : '+$_.Exception.Message) }
while(-not(Test-Path -LiteralPath $stopMarker)){
    $owned=@(Get-OwnedBridge)
    if($owned.Count){
        # A Windows venv launch exposes both its shim and the underlying Python
        # process. Poll the owned set as one service instead of waiting on each
        # PID in sequence, which could delay crash recovery by ten seconds.
        Start-Sleep -Seconds 1
        continue
    }
    Write-Supervisor 'Lancement de la passerelle Web2API.'
    try {
        $process=Start-Process -FilePath $python -ArgumentList @('-u','-m','chatgpt_web2api','--config',('"'+$configFile+'"')) -WindowStyle Hidden -WorkingDirectory $root -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -PassThru
        $process.WaitForExit()
        $code=$process.ExitCode
        if(-not(Test-Path -LiteralPath $stopMarker)){Write-Supervisor ('Passerelle terminee de facon inattendue, code '+$code+' ; relance dans 2 secondes.')}
    } catch {
        if(-not(Test-Path -LiteralPath $stopMarker)){Write-Supervisor ('Echec de la passerelle : '+$_.Exception.Message+' ; relance dans 2 secondes.')}
    }
    if(-not(Test-Path -LiteralPath $stopMarker)){Start-Sleep -Seconds 2}
}
Write-Supervisor 'Arret demande ; superviseur termine.'
