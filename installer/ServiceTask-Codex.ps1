param([ValidateSet('Install','Start','Stop','Remove','Status')][string]$Action='Status')
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
$manifestFile=Join-Path $root 'installation.json'
$manifest=Get-Content -LiteralPath $manifestFile -Raw | ConvertFrom-Json
if($manifest.product -ne 'Web2API-Continue' -or $manifest.installation_target -ne 'codex' -or [IO.Path]::GetFullPath($manifest.root).TrimEnd('\') -ne $root){throw 'Manifeste Codex invalide pour la tache de fond.'}
$digest=[Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($root.ToLowerInvariant()))
$suffix=([BitConverter]::ToString($digest).Replace('-','')).Substring(0,16)
$taskName='Web2API-Codex-'+$suffix
$scriptPath=Join-Path $root 'Service-Codex.ps1'
$statePath=Join-Path $root 'service-task.json'
$stopMarker=Join-Path $root 'state\service-stop.requested'
$powershell=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$arguments='-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+$scriptPath+'"'
function Get-ManagedTask { Get-ScheduledTask -TaskName $taskName -TaskPath '\' -ErrorAction SilentlyContinue }
function Read-OwnedState {
    if(-not(Test-Path -LiteralPath $statePath -PathType Leaf)){return $null}
    $state=Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    if($state.product -ne 'Web2API-Codex-service' -or $state.task_name -ne $taskName -or [IO.Path]::GetFullPath($state.root).TrimEnd('\') -ne $root){throw 'Etat de tache Web2API non reconnu.'}
    return $state
}
function Assert-OwnedTask($Task,$State){
    if(-not $Task){throw 'Tache Web2API Codex absente.'}
    if(-not $State){throw 'Une tache de meme nom existe sans preuve de propriete.'}
    $actions=@($Task.Actions)
    if($actions.Count -ne 1 -or [IO.Path]::GetFullPath($actions[0].Execute) -ne [IO.Path]::GetFullPath($powershell) -or $actions[0].Arguments -ne $arguments -or [IO.Path]::GetFullPath($actions[0].WorkingDirectory).TrimEnd('\') -ne $root){throw 'La tache Web2API Codex a ete modifiee ; operation refusee.'}
}
$task=Get-ManagedTask
$ownedState=Read-OwnedState
switch($Action){
    'Install' {
        if(-not(Test-Path -LiteralPath $scriptPath -PathType Leaf)){throw 'Superviseur Codex absent.'}
        if($task){Assert-OwnedTask $task $ownedState}
        $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
        $taskAction=New-ScheduledTaskAction -Execute $powershell -Argument $arguments -WorkingDirectory $root
        $trigger=New-ScheduledTaskTrigger -AtLogOn -User $identity.Name
        $principal=New-ScheduledTaskPrincipal -UserId $identity.User.Value -LogonType Interactive -RunLevel Limited
        $settings=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 99 -RestartInterval (New-TimeSpan -Minutes 1)
        Register-ScheduledTask -TaskName $taskName -TaskPath '\' -Action $taskAction -Trigger $trigger -Principal $principal -Settings $settings -Description ('Supervise ChatGPT Web2API pour Codex : '+$root) -Force | Out-Null
        @{product='Web2API-Codex-service';version=1;task_name=$taskName;root=$root;script=$scriptPath;user_sid=$identity.User.Value} | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
        Remove-Item -LiteralPath $stopMarker -Force -ErrorAction SilentlyContinue
    }
    'Start' {
        Assert-OwnedTask $task $ownedState
        Remove-Item -LiteralPath $stopMarker -Force -ErrorAction SilentlyContinue
        if($task.State -ne 'Running'){Start-ScheduledTask -TaskName $taskName -TaskPath '\'}
    }
    'Stop' {
        if(-not $task -and -not $ownedState){break}
        Assert-OwnedTask $task $ownedState
        New-Item -ItemType Directory -Path (Split-Path $stopMarker -Parent) -Force | Out-Null
        Set-Content -LiteralPath $stopMarker -Value 'stop' -Encoding ASCII
        if($task.State -eq 'Running'){Stop-ScheduledTask -TaskName $taskName -TaskPath '\'}
    }
    'Remove' {
        if(-not $task -and -not $ownedState){break}
        Assert-OwnedTask $task $ownedState
        New-Item -ItemType Directory -Path (Split-Path $stopMarker -Parent) -Force | Out-Null
        Set-Content -LiteralPath $stopMarker -Value 'stop' -Encoding ASCII
        if($task.State -eq 'Running'){Stop-ScheduledTask -TaskName $taskName -TaskPath '\'}
        Unregister-ScheduledTask -TaskName $taskName -TaskPath '\' -Confirm:$false
        Remove-Item -LiteralPath $statePath -Force
    }
    'Status' {
        $status=if($task){[string]$task.State}else{'Missing'}
        [pscustomobject]@{task_name=$taskName;state=$status;owned=[bool]$ownedState;root=$root} | ConvertTo-Json -Compress
    }
}
