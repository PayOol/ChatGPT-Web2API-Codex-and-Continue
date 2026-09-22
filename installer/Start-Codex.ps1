param([switch]$ServiceOnly,[switch]$SkipDesktop,[string]$Workspace='')
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
$manifestFile=Join-Path $root 'installation.json'
$runtimeManifest=Get-Content -LiteralPath $manifestFile -Raw | ConvertFrom-Json
if ($runtimeManifest.product -ne 'Web2API-Continue' -or $runtimeManifest.installation_target -ne 'codex' -or [IO.Path]::GetFullPath($runtimeManifest.root).TrimEnd('\') -ne $root) { throw 'Manifeste Codex invalide pour ce dossier.' }
$python=Join-Path $root 'venv\Scripts\python.exe'
$configure=Join-Path $root 'app\installer\configure_codex.py'
& $python $configure --root $root --check
if ($LASTEXITCODE -ne 0) { throw 'Installation incomplete. Relancer Repair.cmd.' }
. (Join-Path $root 'Environment.ps1')
$logs=Join-Path $root 'logs'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$digest=[Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($root.ToLowerInvariant()))
$mutex=[Threading.Mutex]::new($false,('Local\Web2API-Start-'+[BitConverter]::ToString($digest).Replace('-','')))
if (-not $mutex.WaitOne(10000)) { $mutex.Dispose(); throw 'Un lancement est deja en cours.' }
$configFile=Join-Path $root 'config.json'
$serviceTaskHelper=Join-Path $root 'ServiceTask-Codex.ps1'
$serviceTaskState=Join-Path $root 'service-task.json'
$configArgument='(?:^|\s)--config\s+(?:"'+[regex]::Escape($configFile)+'"|'+[regex]::Escape($configFile)+')(?=\s|$)'
function Get-OwnedBridge {
    @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object {
        $_.CommandLine -match '(?:^|\s)-m\s+chatgpt_web2api(?:\s|$)' -and $_.CommandLine -match $configArgument -and
        ($_.ExecutablePath -eq $python -or ($_.ExecutablePath -and $_.ExecutablePath.StartsWith((Join-Path $root 'python')+'\',[StringComparison]::OrdinalIgnoreCase)))
    })
}
function Assert-PortOwner($Processes) {
    $ids=@($Processes | ForEach-Object { $_.ProcessId })
    $listeners=@(Get-NetTCPConnection -LocalPort $runtimeManifest.api_port -State Listen -ErrorAction SilentlyContinue)
    if (@($listeners | Where-Object { $_.OwningProcess -notin $ids }).Count) { throw 'Le port API est occupe par un autre service. Aucun processus tiers ne sera arrete.' }
    return $listeners
}
function Test-BridgeAwaitingLogin($Processes) {
    if (-not @($Processes).Count) { return $false }
    $authLog=Join-Path $logs 'stderr.log'
    if (-not (Test-Path -LiteralPath $authLog)) { return $false }
    if (-not (Get-Content -LiteralPath $authLog -Tail 30 | Select-String 'Auth failed: .*waiting for login')) { return $false }
    $created=($Processes | Sort-Object CreationDate | Select-Object -First 1).CreationDate
    if ((Get-Item -LiteralPath $authLog).LastWriteTimeUtc -lt $created.ToUniversalTime()) { return $false }
    $profile=Join-Path $root 'browser-profile'
    $profileArgument='--user-data-dir(?:=|\s+)(?:"'+[regex]::Escape($profile)+'"|'+[regex]::Escape($profile)+')(?=\s|$)'
    $browsers=@(Get-CimInstance Win32_Process -Filter "Name = 'chrome.exe'" | Where-Object {
        $_.ExecutablePath -eq $runtimeManifest.browser -and $_.CommandLine -match $profileArgument -and $_.CommandLine -notlike '*--type=*'
    })
    $browserIds=@($browsers | ForEach-Object { $_.ProcessId })
    $cdp=@(Get-NetTCPConnection -LocalPort $runtimeManifest.cdp_port -State Listen -ErrorAction SilentlyContinue)
    return ($cdp.Count -gt 0 -and @($cdp | Where-Object { $_.OwningProcess -notin $browserIds }).Count -eq 0)
}
try {
    if (-not $ServiceOnly -and -not $SkipDesktop) {
        $desktop=Get-AppxPackage -Name OpenAI.Codex -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $desktop) { throw 'Codex Desktop absent. Relancer l''installation ou utiliser -SkipDesktop explicitement pour le CLI.' }
        $application=(Get-AppxPackageManifest $desktop).Package.Applications.Application | Where-Object { $_.EntryPoint -eq 'Windows.FullTrustApplication' -and $_.Executable -match '(^|[/\\])(Codex|ChatGPT)\.exe$' } | Select-Object -First 1
        if (-not $application) { throw 'Point de lancement de Codex Desktop introuvable.' }
        $desktopId=$desktop.PackageFamilyName+'!'+$application.Id
    }
    $supervised=(Test-Path -LiteralPath $serviceTaskHelper -PathType Leaf) -and (Test-Path -LiteralPath $serviceTaskState -PathType Leaf)
    if($supervised){
        & $serviceTaskHelper -Action Start
    }
    $owned=@(Get-OwnedBridge)
    $ownedIds=@($owned | ForEach-Object { $_.ProcessId })
    $top=@($owned | Where-Object { $_.ParentProcessId -notin $ownedIds })
    if ($top.Count -gt 1) { throw 'Plusieurs services de cette installation existent. Utiliser Stop puis Start.' }
    $listeners=@(Assert-PortOwner $owned)
    $endpoint='http://127.0.0.1:'+$runtimeManifest.api_port+'/health'
    $health=$null
    try { $health=Invoke-RestMethod $endpoint -TimeoutSec 3 } catch { }
    if ($health -and -not $owned.Count) { throw 'La reponse API ne provient pas de cette installation.' }
    if ($owned.Count -and $listeners.Count -and $health.status -eq 'broken' -and -not $health.chrome_running -and -not $health.driver_connected) {
        foreach ($service in $owned) {
            $current=Get-OwnedBridge | Where-Object { $_.ProcessId -eq $service.ProcessId -and $_.CreationDate -eq $service.CreationDate }
            if ($current) { Stop-Process -Id $current.ProcessId -ErrorAction Stop; Wait-Process -Id $current.ProcessId -Timeout 15 -ErrorAction SilentlyContinue }
        }
        $owned=@(Get-OwnedBridge)
        if ($owned.Count) { throw 'La passerelle de cette installation reste active.' }
    }
    if (-not $owned.Count) {
        $null=Assert-PortOwner @()
        if(-not $supervised){
            Start-Process -FilePath $python -ArgumentList @('-u','-m','chatgpt_web2api','--config',('"'+$configFile+'"')) -WindowStyle Hidden -WorkingDirectory $root -RedirectStandardOutput (Join-Path $logs 'stdout.log') -RedirectStandardError (Join-Path $logs 'stderr.log') | Out-Null
        }
    }
    $deadline=[DateTime]::UtcNow.AddSeconds(60)
    $awaitingLogin=$false
    do {
        $owned=@(Get-OwnedBridge)
        $listeners=@(Assert-PortOwner $owned)
        if ($listeners.Count -and $owned.Count) { break }
        $awaitingLogin=Test-BridgeAwaitingLogin $owned
        if ($awaitingLogin) { break }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)
    if ($awaitingLogin) {
        $notice='Passerelle demarree ; connexion ChatGPT requise dans le navigateur dedie. API en attente de connexion.'
        Write-Host $notice
        Add-Content -LiteralPath (Join-Path $logs 'launcher.log') -Value ((Get-Date -Format o)+' '+$notice)
    }
    elseif (-not $listeners.Count) { throw 'La passerelle ne repond pas sur son port. Consulter logs\stderr.log.' }
    # Python starts only the recorded managed proxy; existing OpenCodex is never restarted.
    & $python $configure --root $root --start-opencodex
    if ($LASTEXITCODE -ne 0) { throw 'OpenCodex gere indisponible. Consulter les journaux.' }
    if (-not $ServiceOnly) {
        if ($SkipDesktop) {
            # Explicit CLI mode uses native defaults; no -c, tools, or permission overrides.
            $cliArgs=@()
            if ($Workspace) { $cliArgs+=@('-C',('"'+$Workspace+'"')) }
            if ($cliArgs.Count) { Start-Process -FilePath $runtimeManifest.codex -ArgumentList $cliArgs -WorkingDirectory $root | Out-Null }
            else { Start-Process -FilePath $runtimeManifest.codex -WorkingDirectory $root | Out-Null }
        } else {
            Start-Process -FilePath (Join-Path $env:SystemRoot 'explorer.exe') -ArgumentList ('shell:AppsFolder\'+$desktopId) | Out-Null
        }
    }
} catch {
    $message=$_.Exception.Message
    Add-Content -LiteralPath (Join-Path $logs 'launcher.log') -Value ((Get-Date -Format o)+' '+$message)
    if (-not $ServiceOnly -and -not $SkipDesktop) { Add-Type -AssemblyName PresentationFramework; [Windows.MessageBox]::Show($message,'Web2API Codex') | Out-Null }
    throw
} finally { $mutex.ReleaseMutex(); $mutex.Dispose() }
