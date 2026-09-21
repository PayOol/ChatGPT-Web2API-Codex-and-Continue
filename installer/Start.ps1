param([switch]$ServiceOnly,[string]$Workspace='')
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'Environment.ps1')
$digest=[Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($PSScriptRoot))
$mutex=[Threading.Mutex]::new($false,('Local\Web2API-Start-'+([BitConverter]::ToString($digest).Replace('-',''))))
if (-not $mutex.WaitOne(10000)) { throw 'Un lancement est deja en cours.' }
try {
    $configFile=Join-Path $PSScriptRoot 'config.json'
    $python=Join-Path $PSScriptRoot 'venv\Scripts\python.exe'
    $endpoint='http://127.0.0.1:'+$runtimeManifest.api_port+'/health'
    $health=$null
    try { $health=Invoke-RestMethod $endpoint -TimeoutSec 3 } catch { }
    $owned=@(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object {
        $_.CommandLine -like '*-m chatgpt_web2api*' -and $_.CommandLine.Contains($configFile)
    })
    # Windows venv launchers have one managed Python child with the same arguments.
    $ownedIds=@($owned | ForEach-Object { $_.ProcessId })
    $owned=@($owned | Where-Object { $_.ParentProcessId -notin $ownedIds })
    if ($health -and -not $owned) { throw 'Le port API est occupe par un autre service. Fermer ce service ou modifier la configuration de cette installation.' }
    if ($owned.Count -gt 1) { throw 'Plusieurs services de cette installation existent. Utiliser Stop puis Start.' }
    if ($owned -and $health -and $health.status -eq 'broken' -and -not $health.chrome_running -and -not $health.driver_connected) {
        & (Join-Path $PSScriptRoot 'Stop.ps1')
        $owned=@()
    }
    if (-not $owned) {
        $occupied=@(Get-NetTCPConnection -LocalPort $runtimeManifest.api_port -State Listen -ErrorAction SilentlyContinue)
        if ($occupied.Count) { throw 'Le port API est deja occupe. Aucun processus tiers ne sera arrete.' }
        $logs=Join-Path $PSScriptRoot 'logs'
        New-Item -ItemType Directory -Path $logs -Force | Out-Null
        Start-Process -FilePath $python -ArgumentList @('-u','-m','chatgpt_web2api','--config',('"'+$configFile+'"')) -WindowStyle Hidden -WorkingDirectory $PSScriptRoot -RedirectStandardOutput (Join-Path $logs 'stdout.log') -RedirectStandardError (Join-Path $logs 'stderr.log') | Out-Null
    }
    if (-not $ServiceOnly) {
        $args=@('--user-data-dir',('"'+(Join-Path $PSScriptRoot 'vscode-data')+'"'),'--extensions-dir',('"'+(Join-Path $PSScriptRoot 'extensions')+'"'),'--new-window')
        if ($Workspace) { $args+=('"'+$Workspace+'"') }
        else { $args+=('"'+(Join-Path $PSScriptRoot 'BIENVENUE.md')+'"') }
        Start-Process -FilePath (Join-Path $PSScriptRoot 'apps\vscode\Code.exe') -ArgumentList $args | Out-Null
    }
} catch {
    $message=$_.Exception.Message
    Add-Content -LiteralPath (Join-Path $PSScriptRoot 'logs\launcher.log') -Value ((Get-Date -Format o)+' '+$message)
    if (-not $ServiceOnly) { Add-Type -AssemblyName PresentationFramework; [Windows.MessageBox]::Show($message,'Web2API Continue') | Out-Null }
    throw
} finally { $mutex.ReleaseMutex();$mutex.Dispose() }
